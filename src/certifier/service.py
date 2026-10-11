"""One lookup end to end: EDGAR (if SEC-listed) -> Claude research and extraction -> engine.

Used by the MCP server and the CLI. Without an Anthropic key it falls back to EDGAR plus the
heuristic extractor, which only covers SEC filers.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from . import heuristic
from .config import has_anthropic_key
from .engine import certify
from .llm import Claude, Spend
from .models import Certification, Entity
from .policy import Policy, default_policy
from .research import dedupe, research_entity
from .sources.edgar import Edgar, Snippet
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


def edgar_snippets(edgar: Edgar, cik: int, limit: int = 3) -> list[Snippet]:
    """Employee snippets from recent annual filings, keeping only those with a headcount figure."""
    company = edgar.company(cik)
    snippets = [s for f in edgar.annual_filings(company, limit=limit) for s in edgar.snippets(f)]
    return [s for s in snippets if heuristic.snippet_sources([s])]


def lookup(entity: Entity, cik: int | None = None, lookup_date: date | None = None, policy: Policy | None = None,
           edgar: Edgar | None = None, claude: Claude | None = None, parent_cik: int | None = None,
           propublica: ProPublica | None = None) -> LookupResult:
    """`parent_cik` lets a subsidiary without its own filings use its parent's combined filing
    (e.g., FPL's headcount in NextEra's 10-K); Claude extraction scopes the figures to the entity."""
    policy = policy or default_policy()
    lookup_date = lookup_date or date.today()
    edgar = edgar or Edgar()
    notes: list[str] = []
    snippets: list[Snippet] = []
    filing_cik = cik or parent_cik
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

    known = [] if filing_cik else form990_sources(entity, notes, propublica)
    claude = claude or Claude(policy)
    spend = Spend(policy)
    site = website_snippets(entity.website) if entity.website else []
    found = research_entity(entity, snippets, lookup_date, claude, spend, site=site, known=known)
    sources = dedupe(known + found.sources)
    if not found.sources and snippets:  # extraction failed; keep the filings
        sources += heuristic.best_per_filing(snippets, policy)
        notes.append("Claude extraction returned nothing; fell back to rule-based extraction of SEC filings.")
    cert = certify(entity, sources, linkedin=found.linkedin, lookup_date=lookup_date,
                   event_flags=found.event_flags, review_flags=found.complexities, policy=policy)
    notes.extend(spend.notes)
    if found.notes:
        notes.append(found.notes)
    result = LookupResult(certification=cert, cost_usd=round(spend.usd, 4), web_searches=spend.searches,
                          web_fetches=spend.fetches, method=("edgar+" if snippets else "990+" if known else "") + "research", notes=notes,
                          queries=spend.queries)
    log_for_review(result)
    return result


def form990_sources(entity: Entity, notes: list[str], propublica: ProPublica | None = None) -> list:
    """Form 990 line 5 (tier 2) when the name exactly matches one U.S. nonprofit on ProPublica."""
    propublica = propublica or ProPublica()
    try:
        match = propublica.exact_match(entity.name)
        sources = propublica.line5_sources(match.ein) if match else []
    except Exception as e:  # ProPublica outage shouldn't stop the lookup
        notes.append(f"ProPublica Nonprofit Explorer unavailable: {e}")
        return []
    if sources:
        notes.append(f"Form 990 filings found on ProPublica (EIN {match.ein}).")
    return sources


def log_for_review(result: LookupResult) -> None:
    """Append lookups with conflicts, events or complexities to the review queue, so hard cases
    can be reviewed and turned into examples later."""
    cert = result.certification
    if not cert.flags:
        return
    path = Path(os.environ.get("CERTIFIER_REVIEW_LOG", REVIEW_LOG))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "entity": cert.entity.name,
                 "certified_count": cert.certified_count, "confidence": cert.confidence_score, "flags": cert.flags,
                 "notes": result.notes}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # the review log is a convenience; never fail a lookup over it
