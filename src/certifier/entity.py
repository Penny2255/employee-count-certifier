"""Entity validation (build step 4): resolve a name to candidate organizations for the user
to confirm before any research runs (SPEC.md: Entity validation)."""

from __future__ import annotations

import urllib.parse
from typing import Literal

from pydantic import BaseModel, Field

from .llm import Claude, Spend
from .sources.edgar import Edgar

OrgType = Literal["public_company", "private_company", "nonprofit", "university", "government", "other"]


class XCandidate(BaseModel):
    name: str = Field(description="Full legal or common name")
    website: str | None
    description: str = Field(description="One line: what the organization does")
    hq: str | None = Field(description="Headquarters city and country")
    org_type: OrgType
    ticker: str | None = Field(description="Primary U.S. stock ticker if SEC-listed (incl. ADRs), else null")
    is_subsidiary: bool
    legal_parent: str | None = Field(description="Ultimate global parent if this is a subsidiary or campus")
    parent_website: str | None
    parent_ticker: str | None


class XCandidates(BaseModel):
    candidates: list[XCandidate]


class EntityCandidate(XCandidate):
    cik: int | None = None
    parent_cik: int | None = None
    logo_url: str | None = None


SYSTEM = """You identify which real organization a user means, before a headcount lookup. Use web search
sparingly. Return the organizations that plausibly match (usually one; at most four), most likely
first. For each, give its website, a one-line description, headquarters, type, U.S. ticker if
SEC-listed (including ADRs), and whether it is a subsidiary, campus or affiliate of a larger
organization, naming the ultimate global parent. Do not invent tickers or websites."""


def _logo(website: str | None) -> str | None:
    if not website:
        return None
    host = urllib.parse.urlsplit(website if "://" in website else "https://" + website).netloc
    return f"https://{host}/favicon.ico" if host else None


def _cik(edgar: Edgar, ticker: str | None) -> int | None:
    if not ticker:
        return None
    try:
        matches = [c for c in edgar.find_companies(ticker, limit=1) if c.ticker == ticker.upper()]
    except Exception:
        return None
    return matches[0].cik if matches else None


def find_entities(name: str, website: str | None, claude: Claude, spend: Spend,
                  edgar: Edgar | None = None) -> list[EntityCandidate]:
    edgar = edgar or Edgar()
    prompt = f"Organization name: {name}" + (f"\nWebsite given by the user: {website}" if website else "")
    notes = claude.research(SYSTEM, prompt, spend, max_searches=3, max_fetches=1)
    parsed = claude.extract("Convert these notes into the candidate list. Copy facts only; never invent.",
                            f"{prompt}\n\nNotes:\n{notes}", XCandidates, spend)
    out = []
    for c in (parsed.candidates if parsed else [])[:4]:
        out.append(EntityCandidate(**c.model_dump(), cik=_cik(edgar, c.ticker), parent_cik=_cik(edgar, c.parent_ticker),
                                   logo_url=_logo(c.website)))
    return out
