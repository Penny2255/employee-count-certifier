"""Research (build step 3): gather candidate sources across tiers with Claude, then extract
them into engine Sources. EDGAR snippets, when available, are passed in as tier 1 evidence."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .examples import load_examples
from .llm import Claude, Spend
from .models import Entity, LinkedInEvidence, Source
from .policy import Policy
from .sources.edgar import Snippet
from .sources.website import PageSnippet


# --- Extraction schema (what Claude returns) -------------------------------------------------

class XCount(BaseModel):
    category: str
    count: int


class XSource(BaseModel):
    url: str
    tier: int = Field(description="Policy tier 1-9")
    value: int = Field(description="The figure as stated (5,000 for 'more than 5,000')")
    qualifier: Literal["exact", "more_than", "approximately", "up_to"]
    basis: Literal["headcount", "fte"]
    scope: Literal["global", "partial", "broader"] = Field(
        description="global: the whole entity worldwide; partial: a region, segment, subsidiary or department; "
                    "broader: also covers bodies outside the entity (e.g., a city figure including schools)")
    as_of_date: date | None = Field(description="Date the count applies to, if stated or clearly implied")
    published_date: date | None
    excerpt: str = Field(description="Verbatim quote containing the figure")
    contractors_included: int | None = Field(description="Independent contractors included in value, if stated")
    separately_reported: list[XCount] = Field(
        description="Worker categories the source lists outside its stated total (e.g., graduate assistants)")
    note: str = Field(description="Nuances: definition used, exclusions, seasonal peak, etc. Empty if none")


class XLinkedIn(BaseModel):
    member_count: int | None
    size_range_low: int | None
    size_range_high: int | None
    growth_6m: float | None = Field(description="Fraction, e.g. 0.08 for 8%; only if publicly visible")
    growth_1y: float | None
    growth_2y: float | None


class XEvent(BaseModel):
    description: str
    url: str | None = Field(description="Source confirming the event; null if not confirmed by a found source")
    headcount_impact: float | None = Field(
        description="Approximate change to headcount as a fraction (0.25 = +25%), null if unknown")


class Extraction(BaseModel):
    sources: list[XSource]
    linkedin: XLinkedIn
    workforce_profile: Literal["white_collar", "mixed", "blue_collar"]
    events: list[XEvent] = Field(description="Mergers, acquisitions, spinoffs or similar affecting headcount")
    complexities: list[str] = Field(
        description="Only genuine entity-scope ambiguity that could change the count materially and needs human "
                    "review, e.g. 'University has an affiliated health system that IPEDS excludes' or 'city figure "
                    "may include the school district'. Wholly owned subsidiaries are simply included by policy and "
                    "are NOT a complexity; neither are partial-scope figures already marked partial. Usually empty")
    notes: str


def material_events(events: list[XEvent], policy: Policy) -> tuple[list[str], list[str]]:
    """Events become confidence flags only when a found source confirms them and the impact is
    material (above the corroboration threshold) or unknown. Others are kept as notes."""
    flags, notes = [], []
    for e in events:
        material = e.headcount_impact is None or abs(e.headcount_impact) > policy.agreement.corroborates_within
        if e.url and material:
            flags.append(f"{e.description} ({e.url})")
        else:
            notes.append(f"Event noted, not flagged ({'unconfirmed' if not e.url else 'immaterial'}): {e.description}")
    return flags, notes


# --- Prompts ------------------------------------------------------------------------------------

def _policy_brief(policy: Policy) -> str:
    tiers = "\n".join(f"  {n}. [{t.cls}] {t.name}" for n, t in sorted(policy.tiers.items()))
    guidelines = "\n".join(f"- {g}" for g in policy.research_guidelines)
    lessons = "\n".join(f"- {ex.case}: {ex.lesson.strip()}" for ex in load_examples())
    return (f"SOURCE TIERS (1 is best):\n{tiers}\n\nRESEARCH GUIDELINES:\n{guidelines}\n\n"
            f"WORKED EXAMPLES (what good looks like):\n{lessons}")


RESEARCH_SYSTEM = """You research the global employee headcount of one organization for a certification
engine. Find the best available sources across the tiers below, highest tier first, plus 2-3
corroborating sources. You do not decide the final number; the engine does. Report evidence only.

For every figure you find, report one FINDING block:
FINDING
url: <exact URL>
source: <publisher and document, e.g. "Adobe 10-K FY2025" or "LinkedIn company page">
tier: <1-9 per the table>
quote: "<verbatim sentence containing the figure>"
as_of: <date the count applies to, or unknown>
published: <publication date, or unknown>
scope: <whole organization worldwide | region/segment/subsidiary/department | includes outside bodies>
notes: <FTE vs headcount, contractors, separately reported categories, exclusions>

SEARCH PLAN (searches are limited; follow this order and stop early once you have a tier 1-2
figure plus two corroborating sources):
1. If a website is given, fetch the organization's own About / Company page first (try the
   homepage, then /about, /company, /about-us). Stat tiles like "1,500 Employees" count (tier 4).
2. Search "<name> number of employees" and "<name> employees <current year>".
3. Search for the organization's annual report by type: 10-K/20-F and full annual or
   integrated report (companies), Form 990 (nonprofits, via ProPublica), IPEDS (U.S.
   universities), ACFR or adopted budget (governments).
4. Search "<name> LinkedIn" for the public company page snippet: size range and member count.
5. Press releases or executive quotes stating headcount.
6. Data providers (Crunchbase, PitchBook, ZoomInfo, Revelio, Growjo public pages) for corroboration.

Never repeat a search query you have already run; vary the wording or move to the next step.

Also report, if visible in public search results only (never log in or scrape): LinkedIn member
count ("N associated members", "N employees on LinkedIn"), the LinkedIn size range, and any
headcount growth figures; and the workforce profile (white-collar, mixed, blue-collar). A
LinkedIn member count is NOT a tier 5 source: tier 5 is only headcount text the company wrote in
its LinkedIn description ("with more than 4,500 employees across the globe"). Report a merger, acquisition or
spinoff only when a source you found confirms it, with its URL and the approximate headcount
impact; never from background knowledge alone. Do not invent figures. If nothing is found, say so.

{brief}"""

EXTRACT_SYSTEM = """You convert research notes and filing snippets about one organization's headcount into
structured sources for a certification engine. One source per distinct figure statement. Copy
quotes verbatim. Assign tiers using the table. Record a qualified figure as stated with its
qualifier ("more than 5,000" -> 5000, more_than). Mark scope carefully: segment, regional,
subsidiary and department figures are partial; figures that include outside bodies (e.g. school
systems for a city) are broader. Mark FTE figures as basis fte. Never invent a figure, URL or
date; leave fields null when unknown. Exclude figures that are not headcounts (customers'
employees, layoffs, hires, survey participants, share counts). A LinkedIn member count ("N
associated members", "N employees" on LinkedIn pages) goes in linkedin.member_count, never in
sources; tier 5 is only headcount text the company wrote in its LinkedIn description.

{brief}"""


def _snippet_block(snippets: list[Snippet]) -> str:
    if not snippets:
        return "No SEC filings were found for this organization."
    lines = []
    for s in snippets:
        f = s.filing
        lines.append(f"[{f.form} | period {f.period} | filed {f.filed} | {f.url}] {s.text}")
    return "SEC filing snippets (tier 1):\n" + "\n".join(lines)


def _entity_block(entity: Entity, lookup_date: date) -> str:
    parts = [f"Organization: {entity.name}"]
    for label, value in (("Website", entity.website), ("Headquarters", entity.hq),
                         ("Legal parent", entity.legal_parent), ("Relationship to parent", entity.relationship_to_parent)):
        if value:
            parts.append(f"{label}: {value}")
    parts.append(f"Today's date: {lookup_date.isoformat()}")
    return "\n".join(parts)


# --- Running ------------------------------------------------------------------------------------

class ResearchResult(BaseModel):
    sources: list[Source]
    linkedin: LinkedInEvidence
    event_flags: list[str]
    complexities: list[str] = []
    notes: str
    research_notes: str


def _site_block(site: list[PageSnippet]) -> str:
    if not site:
        return "No headcount statements were read from the organization's own website."
    return ("Organization website statements (tier 4 unless the page is a dated report; usually undated):\n"
            + "\n".join(f"[{s.url}] {s.text}" for s in site))


def _known_block(known: list[Source]) -> str:
    if not known:
        return ""
    return ("Primary sources already retrieved (do not search for these again):\n"
            + "\n".join(f"- tier {s.tier}: {s.value:,} as of {s.as_of_date} ({s.url})" for s in known))


def research_entity(entity: Entity, snippets: list[Snippet], lookup_date: date, claude: Claude,
                    spend: Spend, site: list[PageSnippet] | None = None,
                    known: list[Source] | None = None) -> ResearchResult:
    """`known` are structured sources fetched directly (e.g., Form 990 line 5); research skips them."""
    site, known = site or [], known or []
    brief = _policy_brief(claude.policy)
    have_primary = bool(snippets or known)
    edgar_note = (f"SEC filings already retrieved for this organization ({len(snippets)} snippets from "
                  f"{len({s.filing.url for s in snippets})} filings). Focus on what they don't cover: a more "
                  "specific full annual or integrated report, other tiers for corroboration, LinkedIn public "
                  "data, and events." if snippets else
                  "No SEC filings found. Search all tiers (annual reports, Form 990, IPEDS, government "
                  "financial reports, press releases, website, LinkedIn, executive quotes, data providers).")
    budget = claude.policy.budget
    notes = claude.research(RESEARCH_SYSTEM.format(brief=brief),
                            f"{_entity_block(entity, lookup_date)}\n\n{edgar_note}\n\n{_known_block(known)}\n\n"
                            f"{_site_block(site)}", spend,
                            max_searches=budget.max_web_searches_when_sec_filer if have_primary else None)
    extraction = claude.extract(
        EXTRACT_SYSTEM.format(brief=brief),
        f"{_entity_block(entity, lookup_date)}\n\n{_snippet_block(snippets)}\n\n{_site_block(site)}"
        + (f"\n\n{_known_block(known)}\nThese are recorded separately; do not enter them again or note their absence."
           if known else "")
        + f"\n\nResearch notes:\n{notes or '(none)'}",
        Extraction, spend)
    if extraction is None:
        return ResearchResult(sources=[], linkedin=LinkedInEvidence(), event_flags=[], notes="Extraction failed.",
                              research_notes=notes)
    event_flags, event_notes = material_events(extraction.events, claude.policy)
    return ResearchResult(
        sources=dedupe([to_source(x) for x in extraction.sources if 1 <= x.tier <= 9 and x.value >= 0]),
        linkedin=LinkedInEvidence(
            member_count=extraction.linkedin.member_count,
            size_range=(extraction.linkedin.size_range_low, extraction.linkedin.size_range_high)
            if extraction.linkedin.size_range_low is not None and extraction.linkedin.size_range_high is not None
            else None,
            workforce_profile=extraction.workforce_profile,
            growth_6m=extraction.linkedin.growth_6m, growth_1y=extraction.linkedin.growth_1y,
            growth_2y=extraction.linkedin.growth_2y),
        event_flags=event_flags, complexities=extraction.complexities,
        notes=" ".join([extraction.notes, *event_notes]).strip(), research_notes=notes)


def to_source(x: XSource) -> Source:
    return Source(
        url=x.url, tier=x.tier, value=x.value, qualifier=x.qualifier, basis=x.basis, scope=x.scope,
        excerpt=x.excerpt, as_of_date=x.as_of_date, published_date=x.published_date,
        contractors_included=x.contractors_included or None,
        separately_reported={c.category: c.count for c in x.separately_reported} or None,
        notes=[x.note] if x.note else [],
    )


def dedupe(sources: list[Source]) -> list[Source]:
    """Drop repeats of the same figure from the same URL."""
    seen, out = set(), []
    for s in sources:
        key = (s.url, s.value, s.qualifier, s.as_of_date, s.scope)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out
