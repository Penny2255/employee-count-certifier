"""Spend controls and caching for the hosted service, shared by the MCP tools and the web app.

- Per-user daily lookup limit (CERTIFIER_DAILY_LOOKUPS_PER_USER, default 10). Cached results are free;
  a refresh counts.
- Global daily dollar cap across all users (CERTIFIER_DAILY_USD_CAP, default $10).
- Certifications cached per entity and shared by everyone (CERTIFIER_CACHE_DAYS, default 90), with refresh.

Local use (no signed-in user, e.g. Claude Desktop over stdio) runs without limits or cache.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

from .models import Entity
from .service import LookupResult
from .store import Store


class LimitExceeded(Exception):
    """A spend control was hit; the message is shown to the user as is."""


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Controls:
    store: Store
    daily_lookups: int = 10
    daily_usd_cap: float = 10.0
    cache_days: int = 90

    @classmethod
    def from_env(cls, store: Store | None = None) -> "Controls":
        return cls(store=store or Store(), daily_lookups=int(_env_number("CERTIFIER_DAILY_LOOKUPS_PER_USER", 10)),
                   daily_usd_cap=_env_number("CERTIFIER_DAILY_USD_CAP", 10.0),
                   cache_days=int(_env_number("CERTIFIER_CACHE_DAYS", 90)))

    def check_spend(self) -> None:
        spent = self.store.spend_today()
        if spent >= self.daily_usd_cap:
            raise LimitExceeded(
                f"The service has reached today's spending cap (${spent:.2f} of ${self.daily_usd_cap:.2f}). New lookups "
                "resume after midnight UTC; cached certifications are still available. The administrator can raise "
                "CERTIFIER_DAILY_USD_CAP.")

    def check_lookups(self, subject: str, needed: int) -> None:
        used = self.store.lookups_today(subject)
        if used + needed > self.daily_lookups:
            raise LimitExceeded(
                f"You've used {used} of your {self.daily_lookups} new lookups today, and this request needs {needed}. "
                "The limit resets at midnight UTC. Cached certifications don't count toward it.")


def cache_key(entity: Entity, cik: int | None, parent_cik: int | None) -> str:
    name = " ".join(re.findall(r"[a-z0-9&]+", entity.name.lower()))
    host = (urlsplit(entity.website if "://" in (entity.website or "") else f"https://{entity.website or ''}")
            .hostname or "").removeprefix("www.")
    return f"{name}|{host}|{cik or ''}|{parent_cik or ''}"


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


def run_lookups(jobs: list[Job], run: Callable[..., LookupResult], subject: str | None = None,
                controls: Controls | None = None, refresh: bool = False) -> list[Outcome]:
    """Run (or fetch from cache) each job. With a subject and controls, apply limits and caching."""
    if subject is None or controls is None:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return [Outcome(r, cached=False) for r in pool.map(lambda j: run(j.entity, cik=j.cik, parent_cik=j.parent_cik), jobs)]

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
        else:
            live.append(i)

    if live:
        controls.check_spend()
        controls.check_lookups(subject, len(live))
        with ThreadPoolExecutor(max_workers=len(live)) as pool:
            results = list(pool.map(lambda i: run(jobs[i].entity, cik=jobs[i].cik, parent_cik=jobs[i].parent_cik), live))
        controls.store.record_usage(subject, len(live), sum(r.cost_usd for r in results))
        for i, result in zip(live, results):
            controls.store.cache_put(cache_key(jobs[i].entity, jobs[i].cik, jobs[i].parent_cik), result.model_dump_json())
            outcomes[i] = Outcome(result, cached=False)
    return [o for o in outcomes if o is not None]


def charge(subject: str | None, controls: Controls | None, usd: float) -> None:
    """Record spend that isn't a lookup (entity search)."""
    if subject is not None and controls is not None and usd:
        controls.store.record_usage(subject, 0, usd)
