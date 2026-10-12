# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""One lookup end to end: EDGAR (if SEC-listed) -> Claude research and extraction -> engine.

Used by the MCP server and the CLI. Without an Anthropic key it falls back to EDGAR plus the
heuristic extractor, which only covers SEC filers.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Callable
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel

from . import heuristic
from .config import has_anthropic_key
from .engine import certify
from .llm import Claude, Spend
from .models import Certification, Entity
from .policy import Policy, default_policy
from .locate import locate_sources
from .models import Location
from .research import dedupe, research_entity
from .sources.edgar import Edgar, Snippet
from .sources.ipeds import IPEDS
from .sources.propublica import ProPublica
from .sources.website import website_snippets


REVIEW_LOG = Path(__file__).resolve().parents[2] / "logs" / "review_queue.jsonl"


class LookupResult(BaseModel):
    certification: Certification
    cost_usd: float
    web_searches: int
    web_fetches: int
    method: str
    notes: list[str]
    queries: list[str] = []
    run_at: datetime | None = None
    duration_s: float | None = None
    models: dict[str, str] = {}


def edgar_snippets(edgar: Edgar, cik: int, limit: int = 5) -> list[Snippet]:
    """Employee snippets from recent annual filings, keeping only those with a headcount figure."""
    company = edgar.company(cik)
    snippets = [s for f in edgar.annual_filings(company, limit=limit) for s in edgar.snippets(f)]
    return [s for s in snippets if heuristic.snippet_sources([s])]


# Pipeline stages reported to `progress(stage, message)` as they actually happen.
STAGES = ("resolve", "filings", "sweep", "corroborate", "score", "certified")
Progress = Callable[[str, str], None]


def _noop(stage: str, message: str) -> None:
    pass


def lookup(entity: Entity, cik: int | None = None, lookup_date: date | None = None, policy: Policy | None = None,
           edgar: Edgar | None = None, claude: Claude | None = None, parent_cik: int | None = None,
           propublica: ProPublica | None = None, progress: Progress | None = None,
           spend: Spend | None = None) -> LookupResult:
    """Run one lookup and stamp it with run time, duration and models (the record's methodology).
    `progress(stage, message)` is called as each pipeline stage starts (see STAGES). Pass `spend` to
    read the cost so far even if the lookup fails (the hosted allowances settle on it)."""
    policy = policy or default_policy()
    run_at, started = datetime.now(timezone.utc), time.monotonic()
    result = _lookup(entity, cik, lookup_date, policy, edgar, claude, parent_cik, propublica, progress or _noop,
                     spend or Spend(policy))
    return result.model_copy(update={
        "run_at": run_at, "duration_s": round(time.monotonic() - started, 1),
        "models": {"research": policy.models.research, "extraction": policy.models.extraction}
        if result.method != "edgar-heuristic" else {}})


def _lookup(entity: Entity, cik: int | None, lookup_date: date | None, policy: Policy, edgar: Edgar | None,
            claude: Claude | None, parent_cik: int | None, propublica: ProPublica | None,
            progress: Progress = _noop, spend: Spend | None = None) -> LookupResult:
    """`parent_cik` lets a subsidiary without its own filings use its parent's combined filing
    (e.g., FPL's headcount in NextEra's 10-K); Claude extraction scopes the figures to the entity."""
    policy = policy or default_policy()
    lookup_date = lookup_date or date.today()
    edgar = edgar or Edgar()
    notes: list[str] = []
    snippets: list[Snippet] = []
    progress("resolve", f"Confirming {entity.name}")
    if cik is None:
        cik = resolve_cik(edgar, entity.name, notes)
    filing_cik = cik or parent_cik
    if cik and not entity.address:  # the entity's own registered address (never its parent's)
        try:
            address = edgar.business_address(cik)
            if address:
                entity = entity.model_copy(update={"address": address,
                                                   "address_source": "SEC EDGAR (registered business address)"})
        except Exception:
            pass
    progress("filings", "Reading SEC filings" if filing_cik else "Checking official filings and registers")
    if filing_cik:
        try:
            snippets = edgar_snippets(edgar, filing_cik)
        except Exception as e:  # EDGAR outage shouldn't stop the lookup
            notes.append(f"SEC EDGAR unavailable: {e}")

    if claude is None and not has_anthropic_key():
        if not cik:  # rule-based extraction can't scope a parent's filing to a subsidiary
            snippets = []
        sources = heuristic.best_per_filing(snippets, policy)
        cert = certify(entity, sources, lookup_date=lookup_date, policy=policy)
        notes.append("No Anthropic API key: used SEC EDGAR filings and rule-based extraction only.")
        return LookupResult(certification=cert, cost_usd=0.0, web_searches=0, web_fetches=0,
                            method="edgar-heuristic", notes=notes)

    found_990: dict = {}
    known = [] if filing_cik else form990_sources(entity, notes, propublica, found_990) + ipeds_sources(entity, notes)
    if found_990.get("address") and not entity.address:
        entity = entity.model_copy(update={"address": found_990["address"],
                                           "address_source": "IRS record via ProPublica (organization address)"})
    claude = claude or Claude(policy)
    spend = spend or Spend(policy)
    site = website_snippets(entity.website) if entity.website else []
    progress("sweep", "Sweeping the web for other sources")
    found = research_entity(entity, snippets, lookup_date, claude, spend, site=site, known=known,
                            on_extract=lambda: progress("corroborate", "Cross-checking every figure"))
    progress("score", "Scoring confidence")
    sources = locate_sources(attach_site_locations(dedupe(known + found.sources), site), edgar)
    if not found.sources and snippets:  # extraction failed; keep the filings
        sources += heuristic.best_per_filing(snippets, policy)
        notes.append("Claude extraction returned nothing; fell back to rule-based extraction of SEC filings.")
    sources = stamp_filing_forms(sources, snippets)
    # Every annual filing EDGAR returned is represented: if research dropped one, read it by rule.
    present = {x.url.split("#")[0] for x in sources if x.tier == 1}
    missing = [sn for sn in snippets if sn.filing.url.split("#")[0] not in present]
    if missing and found.sources:
        added = heuristic.best_per_filing(missing, policy)
        if added:
            sources += locate_sources(added, edgar)
            notes.append(f"{len(added)} SEC filing figure(s) not reported by research were read by rule: "
                         + ", ".join(f"{a.value:,} as of {a.as_of_date}" for a in added) + ".")
    cert = certify(entity, sources, linkedin=found.linkedin, lookup_date=lookup_date,
                   events=found.events, review_flags=found.complexities, scope_notes=found.scope_notes,
                   subsidiary_questions=found.subsidiary_questions,
                   policy=policy)
    notes.extend(spend.notes)
    if found.notes:
        notes.append(found.notes)
    result = LookupResult(certification=cert, cost_usd=round(spend.usd, 4), web_searches=spend.searches,
                          web_fetches=spend.fetches, method=("edgar+" if snippets else "990+" if known else "") + "research", notes=notes,
                          queries=spend.queries)
    log_for_review(result)
    progress("certified", "Certified")
    return result


_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "se", "sa",
             "ag", "nv", "the", "llc", "lp", "holdings"}


def _norm(name: str) -> str:
    return " ".join(w for w in re.findall(r"[a-z0-9&]+", name.lower()) if w not in _SUFFIXES)


def resolve_cik(edgar: Edgar, name: str, notes: list[str]) -> int | None:
    """Find the SEC CIK when the caller didn't pass one, so SEC filers always get their filings from
    EDGAR directly (never a mirror). Only a unique exact name match counts."""
    try:
        matches = {c.cik for c in edgar.find_companies(name, limit=20) if _norm(c.name) == _norm(name)}
    except Exception as e:
        notes.append(f"SEC EDGAR lookup unavailable: {e}")
        return None
    if len(matches) == 1:
        cik = matches.pop()
        notes.append(f"SEC CIK {cik} resolved from the name.")
        return cik
    return None


def stamp_filing_forms(sources: list, snippets: list) -> list:
    """SEC sources take their form (10-K, 20-F, 40-F) from the filing itself, not from research."""
    forms = {s.filing.url.split("#")[0]: s.filing.form for s in snippets}
    return [s.model_copy(update={"document_type": forms[s.url.split("#")[0]]}) if s.url.split("#")[0] in forms else s
            for s in sources]


def attach_site_locations(sources: list, site: list) -> list:
    """Website figures read by the stat-tile reader: record the page and the tile's surrounding text."""
    out = []
    for s in sources:
        snip = next((p for p in site if p.url.rstrip("/") == s.url.rstrip("/") and f"{s.value:,}" in p.figure), None)
        if snip is not None:  # the tile reader saw the page itself: its readable context is authoritative
            section = (s.location.section if s.location and s.location.section else
                       f"Statistics on the {s.url.rstrip('/').rsplit('/', 1)[-1] or 'home'} page")
            s = s.model_copy(update={"location": Location(
                section=section, context=snip.readable_context,
                note="Web page: no page numbers; read from the page's stat tiles (embedded page data).")})
        out.append(s)
    return out


def form990_sources(entity: Entity, notes: list[str], propublica: ProPublica | None = None,
                    found: dict | None = None) -> list:
    """Form 990 line 5 (tier 2) when the name exactly matches one U.S. nonprofit on ProPublica. The
    organization's IRS address is put in `found["address"]` when available."""
    propublica = propublica or ProPublica()
    try:
        match = propublica.exact_match(entity.name)
        sources = propublica.line5_sources(match.ein) if match else []
    except Exception as e:  # ProPublica outage shouldn't stop the lookup
        notes.append(f"ProPublica Nonprofit Explorer unavailable: {e}")
        return []
    if sources:
        notes.append(f"Form 990 filings found on ProPublica (EIN {match.ein}).")
        if found is not None:
            try:
                found["address"] = propublica.address(match.ein)
            except Exception:
                pass
    return sources


_COLLEGE = re.compile(r"(university|college|institute of technology|polytechnic)", re.I)


def ipeds_sources(entity: Entity, notes: list[str], ipeds: IPEDS | None = None) -> list:
    """IPEDS "Total all staff" (tier 2) for a U.S. college or university matched exactly by name."""
    host = urlsplit(entity.website if "://" in (entity.website or "") else f"https://{entity.website or ''}").hostname or ""
    if not (_COLLEGE.search(entity.name) or host.endswith(".edu")):
        return []
    ipeds = ipeds or IPEDS()
    try:
        inst = ipeds.find(entity.name)
        source = ipeds.staff_source(inst) if inst else None
    except Exception as e:  # an IPEDS outage shouldn't stop the lookup
        notes.append(f"IPEDS unavailable: {e}")
        return []
    if source is None:
        return []
    notes.append(f"IPEDS Human Resources found (unit ID {inst.unitid}, {inst.name}).")
    return [source]


def log_for_review(result: LookupResult) -> None:
    """Append lookups with conflicts, events or complexities to the review queue, so hard cases
    can be reviewed and turned into examples later."""
    cert = result.certification
    if not cert.flags:
        return
    path = Path(os.environ.get("CERTIFIER_REVIEW_LOG", REVIEW_LOG))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        selected = next((s.url for s in cert.sources if s.role == "selected"), None)
        entry = {"logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "entity": cert.entity.name,
                 "certified_count": cert.certified_count, "confidence": cert.confidence_score,
                 "method": result.method, "selected_url": selected,
                 "breakdown": [f"{s.points:+d} {s.reason}" for s in cert.confidence_breakdown],
                 "flags": cert.flags, "notes": result.notes}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # the review log is a convenience; never fail a lookup over it
