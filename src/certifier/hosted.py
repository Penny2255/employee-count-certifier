# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Open-beta allowances and caching for the hosted service, shared by the web app and the MCP tools.

- No codes for visitors. Each visitor has a daily allowance of lookup spend (CERTIFIER_VISITOR_USD_PER_DAY,
  default $2), keyed on a hash of their IP: a keyed hash (server secret) that is then salted with a
  random salt rotated every day. Connector tokens carry the keyed hash of the IP that signed in, so
  they draw on the same allowance as the website.
- A global hard cap across everyone (CERTIFIER_DAILY_USD_CAP, default $5).
- Before each lookup the per-lookup maximum is reserved against both; the unused part is released
  when the lookup finishes or fails, so neither cap can be exceeded. Days reset at midnight Pacific.
- One lookup in progress per visitor. Cached certifications (CERTIFIER_CACHE_DAYS, default 90) and
  sample results are free.
- Admin codes (CERTIFIER_ACCESS_CODES) bypass the allowances.

Local use (no hosted identity, e.g. Claude Desktop over stdio) runs without limits or cache.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterator
from urllib.parse import urlsplit

from .llm import Spend
from .models import Entity
from .policy import default_policy
from .service import LookupResult
from .store import Store

VISITOR_LIMIT = "You've reached today's beta limit. Back tomorrow."
GLOBAL_LIMIT = "Beta capacity reached for today. Back tomorrow."
BUSY = "One lookup at a time, please: your current lookup is still running."
FIND_RESERVE_USD = 0.10  # an entity search costs a few cents; reserved the same way as a lookup


class LimitExceeded(Exception):
    """An allowance or fair-use limit was hit; the message is shown to the person as is."""

    def __init__(self, message: str, kind: str = "limit"):
        super().__init__(message)
        self.kind = kind


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Who:
    """Whose allowance a request draws on: a visitor bucket ("v:<hash>") or an admin ("admin:<name>")."""

    bucket: str
    admin: bool = False


@dataclass
class Controls:
    store: Store
    visitor_usd: float = 2.0
    daily_usd_cap: float = 5.0
    cache_days: int = 90
    lookup_reserve_usd: float = 0.50
    typical_lookup_usd: float = 0.20  # for "About N searches left today"
    _busy: set = field(default_factory=set)
    _busy_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_env(cls, store: Store | None = None) -> "Controls":
        return cls(store=store or Store(), visitor_usd=_env_number("CERTIFIER_VISITOR_USD_PER_DAY", 2.0),
                   daily_usd_cap=_env_number("CERTIFIER_DAILY_USD_CAP", 5.0),
                   cache_days=int(_env_number("CERTIFIER_CACHE_DAYS", 90)),
                   lookup_reserve_usd=default_policy().budget.max_cost_usd_per_lookup)

    # --- identity ---------------------------------------------------------------------------------

    def ip_key(self, ip: str) -> str:
        """Keyed hash of an IP address (the address itself is never stored)."""
        return hmac.new(self.store.secret().encode(), ip.strip().encode(), hashlib.sha256).hexdigest()

    def visitor(self, ip_key: str) -> Who:
        """Today's allowance bucket for a keyed IP hash, salted with today's random salt."""
        return Who("v:" + hashlib.sha256((self.store.salt() + ip_key).encode()).hexdigest()[:32])

    def resolve(self, subject: str | None) -> Who | None:
        """A token subject: "ip:<key>" is a beta guest; any other name is an admin code; None is local use."""
        if not subject:
            return None
        if subject.startswith("ip:"):
            return self.visitor(subject[3:])
        return Who("admin:" + subject, admin=True)

    # --- allowances -------------------------------------------------------------------------------

    def reserve(self, who: Who, amount: float) -> None:
        reason = self.store.reserve(who.bucket, amount, None if who.admin else self.visitor_usd,
                                    None if who.admin else self.daily_usd_cap)
        if reason == "visitor":
            raise LimitExceeded(VISITOR_LIMIT)
        if reason == "global":
            raise LimitExceeded(GLOBAL_LIMIT)

    def settle(self, who: Who, reserved: float, actual: float, lookups: int = 0) -> None:
        self.store.settle(who.bucket, reserved, actual, lookups)

    @contextmanager
    def metered(self, who: Who | None, amount: float) -> Iterator[Spend]:
        """Reserve `amount`, yield a Spend to run the work with, then settle on what it actually cost."""
        spend = Spend(default_policy())
        if who is None:
            yield spend
            return
        self.reserve(who, amount)
        try:
            yield spend
        finally:
            self.settle(who, amount, spend.usd)

    def searches_left(self, who: Who) -> int | None:
        """Approximate new lookups left today (None for admins: no limit)."""
        if who.admin:
            return None
        mine, total = self.store.used(who.bucket)
        room = min(self.visitor_usd - mine, self.daily_usd_cap - total)
        if room < self.lookup_reserve_usd:
            return 0
        return max(1, math.floor(room / self.typical_lookup_usd))

    @contextmanager
    def one_at_a_time(self, who: Who) -> Iterator[None]:
        """Max one lookup in progress per visitor."""
        if who.admin:
            yield
            return
        with self._busy_lock:
            if who.bucket in self._busy:
                raise LimitExceeded(BUSY, kind="busy")
            self._busy.add(who.bucket)
        try:
            yield
        finally:
            with self._busy_lock:
                self._busy.discard(who.bucket)


# Bump when a change alters which figure is certified or how it's scored: cached results made by older
# code are then ignored (they stay in the database but are never served) and the next search recertifies.
ENGINE_VERSION = "2026.10.13b"


def cache_key(entity: Entity, cik: int | None, parent_cik: int | None) -> str:
    name = " ".join(re.findall(r"[a-z0-9&]+", entity.name.lower()))
    host = (urlsplit(entity.website if "://" in (entity.website or "") else f"https://{entity.website or ''}")
            .hostname or "").removeprefix("www.")
    return f"v{ENGINE_VERSION}|{name}|{host}|{cik or ''}|{parent_cik or ''}"


@dataclass
class Job:
    entity: Entity
    cik: int | None = None
    parent_cik: int | None = None


@dataclass
class Outcome:
    result: LookupResult
    cached: bool
    cached_at: datetime | None = None


def run_lookups(jobs: list[Job], run: Callable[..., LookupResult], who: Who | None = None,
                controls: Controls | None = None, refresh: bool = False) -> list[Outcome]:
    """Run (or fetch from cache) each job. With an identity and controls, apply the allowances.
    `run(entity, cik=..., parent_cik=..., spend=...)` performs one lookup."""
    if who is None or controls is None:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return [Outcome(r, cached=False) for r in
                    pool.map(lambda j: run(j.entity, cik=j.cik, parent_cik=j.parent_cik), jobs)]

    outcomes: list[Outcome | None] = [None] * len(jobs)
    live: list[int] = []
    for i, job in enumerate(jobs):
        hit = None if refresh else controls.store.cache_get(cache_key(job.entity, job.cik, job.parent_cik),
                                                           controls.cache_days)
        if hit:
            payload, created = hit
            result = LookupResult.model_validate_json(payload)
            result = result.model_copy(update={"notes": [f"Cached certification from {created.date().isoformat()}; "
                                                         "ask for a refresh to run a new lookup."] + result.notes})
            outcomes[i] = Outcome(result, cached=True, cached_at=created)
            controls.store.note_cache_hit(who.bucket)  # free: never counts against an allowance
        else:
            live.append(i)

    if live:
        with controls.one_at_a_time(who):
            reserve = controls.lookup_reserve_usd
            reserved = 0
            try:
                for _ in live:  # all or nothing: a subsidiary and its parent are reserved together
                    controls.reserve(who, reserve)
                    reserved += 1
            except LimitExceeded:
                for _ in range(reserved):
                    controls.settle(who, reserve, 0.0)
                raise

            def one(i: int) -> LookupResult:
                spend = Spend(default_policy())
                try:
                    result = run(jobs[i].entity, cik=jobs[i].cik, parent_cik=jobs[i].parent_cik, spend=spend)
                except BaseException:
                    controls.settle(who, reserve, spend.usd)  # release the unused part; keep what was spent
                    raise
                controls.settle(who, reserve, max(result.cost_usd, spend.usd), lookups=1)
                return result

            with ThreadPoolExecutor(max_workers=len(live)) as pool:
                results = list(pool.map(one, live))
        for i, result in zip(live, results):
            controls.store.cache_put(cache_key(jobs[i].entity, jobs[i].cik, jobs[i].parent_cik), result.model_dump_json())
            outcomes[i] = Outcome(result, cached=False)
    return [o for o in outcomes if o is not None]
