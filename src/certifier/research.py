# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Research (build step 3): gather candidate sources across tiers with Claude, then extract
them into engine Sources. EDGAR snippets, when available, are passed in as tier 1 evidence."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .examples import load_examples
from .llm import Claude, Spend
from .locate import text_fragment_link
from .models import Entity, Event, LinkedInEvidence, Location, Source
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
    as_of_estimate: date | None = Field(description="When as_of_date is null: best estimate of the date the count "
                                                    "applies to from context (article date, 'as of early 2025' -> "
                                                    "2025-02-15); null if there is no basis at all")
    as_of_estimate_basis: str | None = Field(description="What the estimate rests on, e.g. 'article dated 2025-01-22'")
    published_date: date | None
    modified_date: date | None = Field(description="Page's last-updated date, if shown")
    predates_change: bool = Field(description="True if the source itself says the figure is from before a change "
                                              "it describes (e.g. 'before taking the layoffs into account')")
    restates: bool = Field(description="True if this source repeats another source's figure (e.g. Wikipedia, "
                                       "Bullfincher or an aggregator quoting the 10-K) rather than reporting its own")
    # A plain string, not an enum, and no separate publisher field: the structured-output grammar sits near the
    # API's size limit (400 "compiled grammar is too large"). to_source() normalizes this against
    # taxonomy.DOCUMENT_TYPES; the publisher comes from the URL (taxonomy.publisher_of).
    document_type: str | None = Field(
        description="What the document is, one of: 10-K, 20-F, 40-F, annual_report (full annual/integrated report "
                    "with financial statements), acfr (government Annual Comprehensive Financial Report), fact_sheet "
                    "(the company's official Corporate Fact Sheet or 'company facts' page/PDF), form_990, ipeds, "
                    "non_financial_report (impact/sustainability/annual review), press_release, company_document "
                    "(other company-published document), website_about, website_other, linkedin_description, news, "
                    "data_provider, other")
    excerpt: str = Field(description="Verbatim quote containing the figure")
    context: str = Field(description="Detailed excerpt: the verbatim passage around the figure, 2-4 sentences")
    section: str | None = Field(description="Heading or part of the page/document where the figure appears, "
                                            "e.g. 'Item 1. Business > Human Capital' or 'About us > Our team'")
    page_number: str | None = Field(description="Page number for PDFs and printed documents; null for web pages")
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
    close_date: date | None = Field(description="Date the deal closed, the spinoff completed, or layoffs/hiring "
                                                "took effect; the announcement date if that is all that is known")
    kind: Literal["merger", "acquisition", "spinoff", "layoff", "hiring", "other"]
    headcount_change: int | None = Field(description="Signed change in headcount if stated (e.g. -300)")
    headcount_impact: float | None = Field(
        description="Approximate change to headcount as a fraction (0.25 = +25%), null if unknown")


class XComplexity(BaseModel):
    description: str
    kind: Literal["subsidiary", "health_system", "joint_venture", "affiliate", "other"]


ENTITY_CHANGING = {"subsidiary", "health_system", "joint_venture", "affiliate"}


class Extraction(BaseModel):
    sources: list[XSource]
    linkedin: XLinkedIn
    workforce_profile: Literal["white_collar", "mixed", "blue_collar"]
    events: list[XEvent] = Field(description="Completed or definitively announced mergers, acquisitions, spinoffs, "
                                             "layoffs or hiring that change headcount. Not bids, proposals or rumors")
    complexities: list[XComplexity] = Field(
        description="Entity-scope questions. Use kind subsidiary / health_system / joint_venture / affiliate only "
                    "when the question could change WHICH entity is counted (e.g. 'the university's affiliated health "
                    "system may or may not be included'). Anything else (data disagreements, missing data, "
                    "wholly owned subsidiaries already included by policy) is kind other. Usually empty")
    notes: str


def material_events(events: list[XEvent], policy: Policy) -> tuple[list[Event], list[str]]:
    """Confirmed (sourced) events go to the engine with a materiality flag: any that took effect after
    the as-of date label the figure pre-adjustment, and material ones also lower confidence.
    Unconfirmed events are kept as notes."""
    confirmed, notes = [], []
    for e in events:
        material = e.headcount_impact is None or abs(e.headcount_impact) > policy.agreement.corroborates_within
        if e.url:
            confirmed.append(Event(description=e.description, url=e.url, close_date=e.close_date, kind=e.kind,
                                   headcount_change=e.headcount_change, material=material))
        else:
            notes.append(f"Event noted, not flagged (unconfirmed): {e.description}")
    return confirmed, notes


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
passage: "<verbatim 2-4 sentences around the figure>"
section: <heading or part of the page/document where it appears>
page: <page number for PDFs and printed documents, or none for web pages>
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
its LinkedIn description ("with more than 4,500 employees across the globe"). Report a merger, acquisition,
spinoff, layoff or hiring push only when it has taken effect or been definitively announced (not
a bid, proposal, rumor or talks) and a source you found confirms it, with its URL, the date it
took effect (or was announced) and the headcount change if stated; never from background
knowledge alone. When a figure has no stated as-of date, say what dates it (article date, "as of
early 2025"). Do not invent figures. If nothing is found, say so.

{brief}"""

EXTRACT_SYSTEM = """You convert research notes and filing snippets about one organization's headcount into
structured sources for a certification engine. One source per distinct figure statement. Copy
quotes verbatim. Assign tiers using the table. Record a qualified figure as stated with its
qualifier ("more than 5,000" -> 5000, more_than). Mark scope carefully: segment, regional,
subsidiary and department figures are partial; figures that include outside bodies (e.g. school
systems for a city) are broader. Mark FTE figures as basis fte. Never invent a figure, URL or
date; leave fields null when unknown. Always use the URL where you actually read the figure: a
10-K or annual report copied on a third-party site (Quartr, AnnualReports.com, aggregators) keeps
that site's URL, not sec.gov's. Mark restates true when the source repeats another source's
figure (Wikipedia, Bullfincher, data sites quoting the 10-K). For events, give the close date.
Exclude targets, plans, goals and forecasts ("aims to reach 10,000 by end of 2025",
"plans to hire 2,000"): they are not headcounts. Exclude figures that are not headcounts (customers'
employees, layoffs, hires, survey participants, share counts, people a programme or initiative
"reaches", employees affected by a restructuring). The goal is the whole organization's total: when
one document gives several figures, report its organization-wide total (a "Total Headcount" table
row, "N people who work for X") as global and mark smaller programme, gender, age, country or
management figures partial or leave them out. Snippets joined with " · " are table cells or stat
tiles read in order; a label applies to the figure right after it, and in a multi-year table the
first figure is the latest year. On the organization's own careers, about, company or fact-sheet pages and
in its LinkedIn description, "team members", "teammates", "associates", "colleagues", "people" and similar
words mean employees: record such a figure as a whole-organization headcount (global scope), keeping its
qualifier ("10,000+ team members" -> 10000, more_than). A LinkedIn member count ("N
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
    events: list[Event]
    complexities: list[str] = []
    subsidiary_questions: list[str] = []  # resolved by the engine once the anchor is known
    scope_notes: list[str] = []
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
                    known: list[Source] | None = None, on_extract=None) -> ResearchResult:
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
    if on_extract is not None:
        on_extract()
    extraction = claude.extract(
        EXTRACT_SYSTEM.format(brief=brief),
        f"{_entity_block(entity, lookup_date)}\n\n{_snippet_block(snippets)}\n\n{_site_block(site)}"
        + (f"\n\n{_known_block(known)}\nThese are recorded separately; do not enter them again or note their absence."
           if known else "")
        + f"\n\nResearch notes:\n{notes or '(none)'}",
        Extraction, spend)
    if extraction is None:
        return ResearchResult(sources=[], linkedin=LinkedInEvidence(), events=[], notes="Extraction failed.",
                              research_notes=notes)
    events, event_notes = material_events(extraction.events, claude.policy)
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
        events=events, complexities=[c.description for c in extraction.complexities
                                            if c.kind in ENTITY_CHANGING - {"subsidiary"}],
        subsidiary_questions=[c.description for c in extraction.complexities if c.kind == "subsidiary"],
        scope_notes=[c.description for c in extraction.complexities if c.kind not in ENTITY_CHANGING],
        notes=" ".join([extraction.notes, *event_notes]).strip(), research_notes=notes)


def to_source(x: XSource) -> Source:
    return Source(
        url=x.url, tier=x.tier, value=x.value, qualifier=x.qualifier, basis=x.basis, scope=x.scope,
        excerpt=x.excerpt, location=_location(x), as_of_date=x.as_of_date or x.as_of_estimate,
        as_of_estimated=x.as_of_date is None and x.as_of_estimate is not None,
        as_of_basis=(x.as_of_estimate_basis or "context in the source")
        if x.as_of_date is None and x.as_of_estimate is not None else None,
        published_date=x.published_date,
        modified_date=x.modified_date, restates=x.restates, predates_change=x.predates_change,
        document_type=_document_type(x.document_type),
        contractors_included=x.contractors_included or None,
        separately_reported={c.category: c.count for c in x.separately_reported} or None,
        notes=[x.note] if x.note else [],
    )


def _document_type(value: str | None) -> str | None:
    """Research's free-text document type, normalized to a taxonomy key (unknown values are inferred later)."""
    from .taxonomy import DOCUMENT_TYPES

    if not value:
        return None
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    key = {"10_k": "10-K", "20_f": "20-F", "40_f": "40-F", "form990": "form_990", "990": "form_990"}.get(key, key)
    return key if key in DOCUMENT_TYPES else None


def _location(x: XSource) -> Location:
    is_pdf = ".pdf" in x.url.lower()
    notes = []
    if not x.page_number:
        notes.append("PDF page number not identified." if is_pdf else "Web page: no page numbers.")
    if not x.section:
        notes.append("Section not identified.")
    return Location(section=x.section, page=x.page_number,
                    page_basis=("pdf" if is_pdf else "printed") if x.page_number else None,
                    context=x.context or x.excerpt, deep_link=text_fragment_link(x.url, x.excerpt) if x.excerpt else None,
                    note=" ".join(notes) or "Located by the research step.")


def dedupe(sources: list[Source]) -> list[Source]:
    """Drop repeats of the same figure from the same URL."""
    seen, out = set(), []
    for s in sources:
        key = (s.url, s.value, s.qualifier, s.as_of_date, s.scope)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out
