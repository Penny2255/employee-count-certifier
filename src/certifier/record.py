# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Standardized certification record (SPEC.md: Certification record).

Every lookup returns the same sections in the same order, even when empty (with an explicit
`none_reason`). Every source tier, use or exclusion, adjustment, score change and finding
carries a plain-English rationale; the models refuse to build without one. The shape is flat
and export-ready (JSON now; CSV, Excel and slides later).
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date, datetime, timedelta
from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ValidationError, model_validator

from . import rules, taxonomy
from .models import Basis, Certification, CountType, Entity, Qualifier, Source
from .policy import Policy, default_policy

RECORD_VERSION = "1.2"
T = TypeVar("T")


def _one_sentence(text: str) -> str:
    text = " ".join(text.split())
    if len(text) < 12 or not re.search(r"[A-Za-z]{3}", text):
        raise ValueError("a rationale (at least one plain-English sentence) is required")
    return text


def _two_sentences(text: str) -> str:
    text = _one_sentence(text)
    if len(re.findall(r"[.!?](?:\s|$)", text)) < 2:
        raise ValueError("a finding rationale needs 2-3 sentences: what we found, why it matters, what we did")
    return text


Rationale = Annotated[str, AfterValidator(_one_sentence)]
FindingRationale = Annotated[str, AfterValidator(_two_sentences)]
Status = Literal["green", "yellow", "red"]
Category = Literal["provenance", "recency", "corroboration", "scope", "linkedin", "event", "definition", "data_gap"]
Group = Literal["affects", "worth_knowing", "background"]
GROUP_TITLES = {"affects": "Affects the answer", "worth_knowing": "Worth knowing", "background": "Background"}


class Section(BaseModel, Generic[T]):
    """A list section. Empty is allowed only with a reason."""

    items: list[T]
    none_reason: str | None = None

    @model_validator(mode="after")
    def _explained(self):
        if not self.items and not (self.none_reason or "").strip():
            raise ValueError("an empty section needs a none_reason")
        return self


class EntitySection(BaseModel):
    name: str
    website: str | None
    hq: str | None
    address: str | None = None  # registered headquarters address, else the confirmed HQ location
    address_source: str | None = None
    legal_parent: str | None
    relationship: str


class IndicatedRangeRow(BaseModel):
    """Newer tier 7-9 data that diverges from an old certified figure: context, never the value."""

    low: int
    high: int
    earliest: date
    latest: date
    source_ids: list[str]
    rationale: Rationale


class Headline(BaseModel):
    count: int | None
    qualifier: Qualifier | None
    range: tuple[int, int] | None
    count_type: CountType | None
    count_basis: Basis | None
    as_of_date: date | None
    as_of_estimated: bool = False
    as_of_estimated_from: Literal["context", "url"] | None = None
    adjustment_status: Literal["current", "pre-adjustment"] = "current"
    known_changes: list[str] = []  # changes that took effect after the as-of date
    indicated_current_range: IndicatedRangeRow | None = None
    direction: Literal["higher", "lower", "in_line", "unknown"] | None = None
    direction_reason: str | None = None
    bottom_line: str  # one line mapped to confidence: ready to use / usable / directional only
    # Private companies (no public filing found) rarely publish a well-supported headcount: 3/5 is a strong
    # result for them and 4-5 is rare. "strong" or "rare" when it applies, with the sentence to show.
    peer_level: Literal["strong", "rare"] | None = None
    peer_note: str | None = None
    # "Our take": a short, plain-English account of the answer, the evidence, the outlook and the confidence,
    # written from this record's own facts (no number appears that the record doesn't hold), and the sources
    # worth opening.
    story: str | None = None
    story_sources: list[str] = []
    next_expected_update: date | None = None  # e.g. when the next 10-K is due
    next_update_note: str | None = None
    none_reason: str | None = None

    @model_validator(mode="after")
    def _explained(self):
        if self.count is None and not (self.none_reason or "").strip():
            raise ValueError("a headline without a count needs a none_reason")
        return self


class BreakdownLine(BaseModel):
    points: int
    rationale: Rationale
    finding_id: str


class ConfidenceSection(BaseModel):
    score: int
    level: str
    breakdown: list[BreakdownLine]
    arithmetic: str  # e.g. "4 + 1 - 0 = 5"

    @model_validator(mode="after")
    def _sums(self):
        if sum(line.points for line in self.breakdown) != self.score:
            raise ValueError("confidence breakdown must sum to the score")
        return self


class LocationRow(BaseModel):
    """Where the figure sits in its document. Missing section or page must be explained in `note`."""

    section: str | None
    page: str | None
    page_basis: str | None
    page_label: str  # e.g. "printed page 10", "page 22 of the HTML filing", "Form 990 page 1", "no page numbers"
    detailed_excerpt: str  # the verbatim passage around the figure
    deep_link: str | None
    note: str | None

    @model_validator(mode="after")
    def _explained(self):
        if not self.detailed_excerpt.strip():
            raise ValueError("a detailed excerpt is required")
        if (self.section is None or self.page is None) and not (self.note or "").strip():
            raise ValueError("a missing section or page number needs a note saying why")
        return self


def _http(url: str | None) -> str | None:
    if url is not None and not re.match(r"https?://\S+", url):
        raise ValueError("a source URL (http or https) is required")
    return url


def _source_type(text: str) -> str:
    if not text.strip():
        raise ValueError("every source needs a source_type")
    return text


class PrimarySource(BaseModel):
    source_id: str | None
    tier: int | None
    tier_name: str | None
    source_category: str | None = None
    source_type: str | None = None
    source_type_info: str | None = None  # "What is this source?" from source_glossary.yaml
    url: str | None
    accession: str | None
    excerpt: str | None
    excerpt_missing_reason: str | None = None
    location: LocationRow | None
    as_of_date: date | None
    published_date: date | None
    modified_date: date | None
    tier_rationale: str | None
    none_reason: str | None = None

    @model_validator(mode="after")
    def _explained(self):
        if self.source_id is None:
            if not (self.none_reason or "").strip():
                raise ValueError("a missing primary source needs a none_reason")
            return self
        _one_sentence(self.tier_rationale or "")
        if not (self.url or "").strip():
            raise ValueError("the primary source needs a URL")
        if not (self.source_category and self.source_type):
            raise ValueError("the primary source needs a source_category and source_type")
        _http(self.url)
        if not (self.excerpt or "").strip() and not (self.excerpt_missing_reason or "").strip():
            raise ValueError("the primary source needs a verbatim excerpt, or a reason none was captured")
        if self.location is None:
            raise ValueError("the primary source needs a location (section, page, detailed excerpt)")
        return self


class Finding(BaseModel):
    """Plain-English headline, an impact chip and a one-sentence "so what"; expand for the rest."""

    id: str
    group: Group
    category: Category
    status: Status
    title: str
    impact: str  # chip: "Lowered confidence by 1", "Adjusted count -1,100", "No effect on the answer"
    so_what: Rationale  # one sentence telling the reader whether to act
    rationale: FindingRationale
    evidence: list[str]
    score_impact: int

    @model_validator(mode="after")
    def _guides(self):
        if not self.impact.strip():
            raise ValueError("every finding needs an impact")
        if re.search(r"(complexity flag|Complexity:|Flag:)", self.title + " " + self.so_what):
            raise ValueError("finding headlines must be plain language (no internal flag names)")
        if self.score_impact and self.group != "affects":
            raise ValueError("a finding that changed the confidence belongs in 'Affects the answer'")
        return self


class SourceRow(BaseModel):
    id: str
    tier: int
    tier_name: str
    source_category: Literal[taxonomy.CATEGORIES]  # type: ignore[valid-type]
    source_type: Annotated[str, AfterValidator(_source_type)]
    source_type_info: str
    value: int
    qualifier: Qualifier
    basis: Basis
    scope: str
    as_of_date: date | None
    published_date: date | None
    modified_date: date | None
    url: Annotated[str, AfterValidator(_http)]
    excerpt: str
    location: LocationRow
    role: str
    used: bool
    tier_rationale: Rationale
    use_rationale: Rationale
    notes: list[str]


class AdjustmentRow(BaseModel):
    id: str
    source_id: str | None
    source_figure: int | None
    change: int
    result: int | None
    rationale: Rationale


class TrendRow(BaseModel):
    as_of_date: date
    value: int
    tier: int | None
    url: str | None
    estimated: bool
    low: int | None = None
    high: int | None = None
    rationale: Rationale
    # An older company-voice statement (tier 1-6) shown for context when the reported history is short: it shapes
    # the trend and the forecast, but it is never certified.
    historical: bool = False


class LinkedInSection(BaseModel):
    source_category: str = "Company Social Profile"
    source_type: str = "LinkedIn: Member Count"
    source_type_info: str = ""
    status: str
    member_count: int | None
    size_range: tuple[int, int] | None
    workforce_profile: str
    pass_range: tuple[int, int] | None
    finding_id: str
    rationale: Rationale
    growth_1y: float | None = None
    growth_2y: float | None = None
    open_roles: int | None = None


class EventRow(BaseModel):
    description: str
    url: str | None
    close_date: date | None
    penalized: bool
    rationale: Rationale


class Methodology(BaseModel):
    policy_version: str
    record_version: str
    method: str
    models: dict[str, str]
    cost_usd: float
    web_searches: int
    web_fetches: int
    run_at: datetime | None
    duration_s: float | None
    lookup_date: date
    queries: list[str]
    notes: list[str]


class CertificationRecord(BaseModel):
    """Sections in display order. Field order is the JSON order."""

    entity: EntitySection
    headline: Headline
    confidence: ConfidenceSection
    primary_source: PrimarySource
    findings: Section[Finding]
    sources: Section[SourceRow]
    adjustments: Section[AdjustmentRow]
    trend: Section[TrendRow]
    linkedin_check: LinkedInSection
    events: Section[EventRow]
    methodology: Methodology

    @model_validator(mode="after")
    def _links(self):
        finding_ids = {f.id for f in self.findings.items}
        source_ids = {s.id for s in self.sources.items}
        for line in self.confidence.breakdown:
            if line.finding_id not in finding_ids:
                raise ValueError(f"breakdown line links to unknown finding {line.finding_id}")
        if self.linkedin_check.finding_id not in finding_ids:
            raise ValueError("linkedin_check links to an unknown finding")
        for f in self.findings.items:
            if not set(f.evidence) <= source_ids:
                raise ValueError(f"finding {f.id} cites unknown sources {set(f.evidence) - source_ids}")
        if self.primary_source.source_id and self.primary_source.source_id not in source_ids:
            raise ValueError("primary source id not among sources")
        return self


def record_errors(data: dict) -> list[str]:
    """Validation problems for a record dict (empty if valid)."""
    try:
        CertificationRecord.model_validate(data)
    except ValidationError as e:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
    return []


# --- Building a record from a certification ---------------------------------------------------

_ACCESSION = re.compile(r"/(\d{10})-?(\d{2})-?(\d{6})(?:/|$|[?#])")


def accession_of(url: str) -> str | None:
    m = _ACCESSION.search(url) if "sec.gov" in url else None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")


def _labels(s: Source) -> dict[str, str]:
    category, kind = taxonomy.classify(s)
    return {"source_category": category, "source_type": kind, "source_type_info": taxonomy.explain(kind)}


def tier_rationale(s: Source, entity: Entity, policy: Policy) -> str:
    name = policy.tiers[s.tier].name
    cls = policy.tier_class(s.tier)
    if s.tier == 1:
        acc = accession_of(s.url)
        if acc:
            return f"Tier 1 ({name}): an SEC filing read from sec.gov, accession {acc}."
        if not s.corroboration_only:
            return f"Tier 1 ({name}): an annual report hosted on the organization's own site ({_host(s.url)})."
        return (f"Labelled tier 1 ({name}) but hosted on {_host(s.url)}, not sec.gov or the organization's site, "
                "so it is treated as a mirror.")
    if "propublica.org" in s.url:
        return f"Tier 2 ({name}): an IRS Form 990 filed by the organization, read via ProPublica."
    kind = taxonomy.classify(s)[1]
    if kind == "Corporate Fact Sheet":
        dated = "dated" if s.tier == policy.fact_sheet.tier else "undated, so one tier lower"
        return f"Tier {s.tier} ({name}, {cls}): the organization's own Corporate Fact Sheet ({dated}), on {_host(s.url)}."
    return f"Tier {s.tier} ({name}, {cls}): {kind}, published by {_host(s.url)}."


def _first_sentence(text: str, limit: int = 110) -> str:
    sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].rstrip(".")
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?")) else text + "."


_BASIS_LABEL = {"printed": "printed page {p}", "html_page": "page {p} of the HTML filing", "pdf": "PDF page {p}",
                "form": "Form page {p}"}


def location_row(s: Source) -> LocationRow:
    loc = s.location
    if loc is None:
        return LocationRow(section=None, page=None, page_basis=None, page_label="not captured",
                           detailed_excerpt=s.excerpt or f"(No verbatim text captured; the source states {s.value:,}.)",
                           deep_link=None, note="Section and page were not captured for this source.")
    if loc.page:
        label = _BASIS_LABEL.get(loc.page_basis or "printed", "page {p}").format(p=loc.page)
    else:
        label = "no page numbers" if "no page numbers" in (loc.note or "").lower() else "page not identified"
    return LocationRow(section=loc.section, page=loc.page, page_basis=loc.page_basis, page_label=label,
                       detailed_excerpt=loc.context or s.excerpt or f"(No verbatim text captured; the source states "
                                                                     f"{s.value:,}.)",
                       deep_link=loc.deep_link, note=loc.note)


class _Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(self, category: str, status: str, title: str, rationale: str, evidence: list[str] | None = None,
            impact: int = 0, *, group: str, so_what: str, chip: str | None = None) -> str:
        fid = f"F{len(self.items) + 1}"
        title = _plain(title)
        title = title[:1].upper() + title[1:]
        if chip is None:
            chip = (f"Lowered confidence by {-impact}" if impact < 0 else f"Raised confidence by {impact}" if impact > 0
                    else "No effect on the answer")
        self.items.append(Finding(id=fid, group=group, category=category, status=status, title=title, impact=chip,
                                  so_what=_sentence(so_what), rationale=_plain(rationale), evidence=evidence or [],
                                  score_impact=impact))
        return fid


_FLAG_CATEGORY = (("Conflict:", "corroboration"), ("LinkedIn:", "linkedin"), ("Event-driven:", "event"),
                  ("Complexity:", "scope"), ("Detailed figure", "definition"))
_HEALTH = re.compile(r"health system|health care system|medical center|hospital", re.I)
_HEALTH_SO_WHAT = ("The campus figure likely excludes health-system staff, so the full-organization count is likely "
                   "higher; use the campus figure only if that's the organization you mean")
_FLAG_SO_WHAT = {
    "corroboration": "Look at the conflicting source before updating records",
    "linkedin": "Check whether the LinkedIn count includes former staff or contractors before relying on the figure",
    "event": "Expect today's headcount to differ; recheck once the change has settled",
    "scope": "Confirm which organization you mean before using the figure",
    "definition": "Check the more detailed figure before relying on the headline number",
    "data_gap": "Review this before relying on the figure",
}
# Internal wording rewritten for sales and RevOps readers.
_PLAIN = ((r"\bFlag:\s*", ""), (r"\bComplexity:\s*", ""), (r"\bcomplexity flags?\b", "scope question"),
          (r"\b[Tt]racker estimates\b", "data-provider estimates"), (r"\b[Tt]rackers\b", "data providers"),
          (r"\bnear-date\b", "similar-date"), (r"\bthe 15% tolerance\b", "the 15% allowance"))


def _plain(text: str) -> str:
    for pattern, repl in _PLAIN:
        text = re.sub(pattern, repl, text)
    return text


def _type_of(s: Source) -> str:
    return taxonomy.classify(s)[1]


def private_company_note(cert: Certification) -> tuple[str | None, str | None]:
    """Context for a private company: no tier 1-2 source (annual report, regulatory filing, Form 990, IPEDS) was
    found, so the evidence is what the company chose to publish plus third parties."""
    if cert.certified_count is None or any(s.tier in (1, 2) for s in cert.sources):
        return None, None
    score = cert.confidence_score
    if score >= 4:
        return "rare", (f"Rare for a private company: without public filings, a {score}/5 this well supported is "
                        "uncommon. Worth celebrating.")
    if score == 3:
        return "strong", ("A strong result for a private company: without public filings, 3/5 is about as good as it "
                          "usually gets, and 4-5 is rare.")
    return None, None


def bottom_line(score: int, count: int | None) -> str:
    if count is None:
        return "No certified figure. No usable public source was found."
    if score >= 4:
        return "Ready to use. Strong, current primary source."
    if score == 3:
        return "Usable. Note the range and the as-of date."
    return "Directional only. Verify before updating records."


# Typical lag from the as-of date to the next edition, in days (fiscal year plus filing time).
_NEXT_EDITION = {"10-K": (365 + 60, "10-K"), "20-F": (365 + 120, "20-F"), "40-F": (365 + 90, "40-F"),
                 "sec_filing": (365 + 90, "annual SEC filing"), "annual_report": (365 + 90, "annual report"),
                 "acfr": (365 + 180, "ACFR"), "form_990": (365 + 320, "Form 990"), "ipeds": (365 + 400, "IPEDS release")}


def next_update(selected: Source | None, lookup_date: date,
                policy: Policy | None = None) -> tuple[date | None, str | None]:
    """When a newer edition of the key source is expected (e.g. the next 10-K)."""
    if selected is None or selected.as_of_date is None:
        return None, None
    kind = selected.document_type if selected.document_type in taxonomy.DOCUMENT_TYPES else \
        taxonomy.infer_document_type(selected)
    if kind not in _NEXT_EDITION:
        return None, "This kind of source has no fixed publishing schedule."
    lag, name = _NEXT_EDITION[kind]
    lag = (policy or default_policy()).recency.latest_release_current.get(kind, lag)  # one source of truth
    expected = selected.as_of_date + timedelta(days=lag)
    while expected < lookup_date - timedelta(days=365):  # several editions behind: the next one still due
        expected += timedelta(days=365)
    when = expected.strftime("%B %Y")
    if expected <= lookup_date:
        return expected, f"A newer {name} was expected around {when} and may already be out; Refresh to check."
    return expected, f"Next {name} expected around {when}."


def _build_findings(cert: Certification, policy: Policy, ids: dict[int, str], by_url: dict[str, str],
                    selected: Source | None, notes: list[str] | None, lookup_date: date):
    findings = _Findings()

    # Base score.
    base_step = cert.confidence_breakdown[0] if cert.confidence_breakdown else None
    base_points = base_step.points if base_step else cert.confidence_score
    if selected is not None:
        what = (f"a tier {selected.tier} source ({policy.tiers[selected.tier].name}) "
                + (f"dated {selected.as_of_date.isoformat()}" if selected.as_of_date else "with no as-of date"))
        source_words = f"{_type_of(selected)} (Tier {selected.tier})"
    elif cert.certified_count is not None:
        what = "tier 7-9 data-provider figures combined into a derived value"
        source_words = "data-provider figures combined"
    else:
        what = "no usable source"
        source_words = "no usable source"
    base_so_what = ("A strong starting point; the items below only fine-tune it" if base_points >= 4 else
                    "A moderate starting point; check the items below before relying on the figure" if base_points >= 2
                    else "A weak starting point; treat the figure as a lead, not a fact")
    base_id = findings.add(
        "recency" if selected is not None else "data_gap",
        "green" if base_points >= 4 else "yellow" if base_points >= 2 else "red",
        f"Starting confidence {base_points} of 5 from the key source: {source_words}",
        f"The certified figure rests on {what}. Under the policy's confidence table this sets a base score of "
        f"{base_points}. The lines below add to or subtract from it.",
        [ids[id(selected)]] if selected is not None else [], 0,
        group="affects", so_what=base_so_what, chip=f"Sets starting confidence: {base_points} of 5")

    # Provenance of the selected source, and mirrors.
    if selected is not None:
        acc = accession_of(selected.url)
        if selected.tier == 1:
            title = f"Read from sec.gov (accession {acc})" if acc else f"Read from the organization's site ({_host(selected.url)})"
            why = ("The figure comes straight from the filing on sec.gov, not a copy." if acc else
                   "The figure comes from the annual report on the organization's own website, not a copy.")
        else:
            title = f"Published by {_host(selected.url)}"
            why = f"The figure was read where it was published ({_host(selected.url)})."
        findings.add("provenance", "green" if selected.tier <= 3 else "yellow", title,
                     f"{why} Tier {selected.tier} is the highest tier available for this organization. "
                     "No action was needed.", [ids[id(selected)]],
                     group="background", so_what="No action needed: the figure was read from the original publication")
    mirrors = [s for s in cert.sources if s.corroboration_only]
    if mirrors:
        findings.add("provenance", "yellow", f"{len(mirrors)} copy(ies) of a filing used only as support",
                     "Copies of a filing hosted outside sec.gov and the organization's site were found. Copies can "
                     "drift from the original, so policy lets them corroborate but never set the value.",
                     [ids[id(s)] for s in mirrors],
                     group="background", so_what="No action needed; copies only support the figure")

    # Corroboration.
    corroborators = [s for s in cert.sources if s.role == "corroborates"]
    corr_step = next((st for st in cert.confidence_breakdown if st.reason.startswith("corroborated by")), None)
    if corroborators:
        corr_id = findings.add(
            "corroboration", "green",
            f"Confirmed by {len(corroborators)} independent source(s) from around the same date",
            "Independent sources dated near the same as-of date agree within "
            f"{policy.agreement.corroborates_within:.0%}. "
            + ("This raises confidence one level." if corr_step else
               "It does not change the score for this tier and recency, but it supports the figure."),
            [ids[id(s)] for s in corroborators], 1 if corr_step else 0,
            group="affects" if corr_step else "worth_knowing",
            so_what="Independent agreement makes the figure safer to use")
    elif cert.certified_count is not None:
        excluded = [s for s in cert.sources if s.role_reason.startswith("Not counted as corroboration")]
        corr_id = findings.add(
            "corroboration", "yellow", "No independent source from around the same date confirms it",
            "No independent source dated near the certified figure's as-of date agreed with it. "
            + (f"{len(excluded)} source(s) were set aside as restatements, the same document, or a different "
               "period. " if excluded else "")
            + "The score stays at its base; an independent near-date source would raise it.",
            [ids[id(s)] for s in excluded],
            group="worth_knowing",
            so_what="Treat the figure as single-sourced; a second independent source would raise confidence")
    else:
        corr_id = base_id

    # Flags (each lowers confidence one level unless the floor was reached).
    flag_ids: dict[str, str] = {}
    flag_steps = {st.reason.split(" (no change: minimum")[0]: st for st in cert.confidence_breakdown[1:]
                  if not st.reason.startswith("corroborated by") and st.reason != "no deductions"}
    for flag in cert.flags:
        category = next((c for prefix, c in _FLAG_CATEGORY if flag.startswith(prefix)), "data_gap")
        step = flag_steps.get(flag)
        impact = step.points if step else -1
        body = flag.split(":", 1)[1].strip() if flag.split(":", 1)[0] in ("Conflict", "LinkedIn", "Event-driven", "Complexity") else flag
        evidence = [sid for url, sid in by_url.items() if url in flag]
        flag_ids[flag] = findings.add(
            category, "red", _first_sentence(re.sub(r"\s*\(https?://[^)]*\)", "", _plain(body)), limit=90),
            f"{_sentence(body)} Policy lowers confidence one level for this"
            + (", but the score was already at its minimum of 1." if impact == 0 else ".")
            + " A reviewer should check it before relying on the figure.", evidence, impact,
            group="affects" if impact else "worth_knowing",
            so_what=(_HEALTH_SO_WHAT if category == "scope" and _HEALTH.search(body) else _FLAG_SO_WHAT[category]),
            chip=None if impact else "No further effect (confidence already at its minimum)")

    # Gaps explained by an open scope question: linked to it, recorded without a second penalty.
    explained_ids: dict[str, str] = {}
    for flag, cause in cert.explained_flags:
        category = next((c for prefix, c in _FLAG_CATEGORY if flag.startswith(prefix)), "data_gap")
        body = flag.split(":", 1)[1].strip()
        cause_id = flag_ids.get(cause)
        evidence = [sid for url, sid in by_url.items() if url in flag]
        cause_title = _first_sentence(_plain(cause.split(":", 1)[1].strip()), limit=70)
        explained_ids[flag] = findings.add(
            category, "yellow", _first_sentence(re.sub(r"\s*\(https?://[^)]*\)", "", _plain(body)), limit=90),
            f"{_sentence(body)} The gap is most likely the same root cause as the open scope question"
            f"{f' ({cause_id})' if cause_id else ''}: {cause_title}. Policy applies one penalty per root cause, so the "
            "scope finding carries it and this one is recorded without one.", evidence, 0,
            group="worth_knowing", chip=f"No extra penalty (same cause as {cause_id})" if cause_id else
            "No extra penalty (same cause as the scope question)",
            so_what="No separate action: once the scope question is settled, this gap is explained")
        if cause_id:
            scope = next(f for f in findings.items if f.id == cause_id)
            scope.rationale += f" Related: {explained_ids[flag]} shows the same gap from LinkedIn; it isn't penalized again."

    # LinkedIn.
    li = cert.linkedin_check
    li_flag = next((f for f in cert.flags if f.startswith("LinkedIn:")), None)
    li_explained = next((f for f, _ in cert.explained_flags if f.startswith("LinkedIn:")), None)
    if li_flag:
        li_id = flag_ids[li_flag]
    elif li_explained:
        li_id = explained_ids[li_explained]
    elif li.status == "pass":
        li_id = findings.add("linkedin", "green", "LinkedIn member count is consistent",
                             f"{_sentence(li.note.removeprefix('Pass: '))} The member count is a sanity check, never "
                             "a floor. No action was needed.",
                             group="background", so_what="No action needed; LinkedIn agrees with the figure")
    elif li.status == "flag" and li.not_penalized:
        li_id = findings.add("linkedin", "yellow", "LinkedIn member count differs; not penalized",
                             f"{_sentence(li.note.removeprefix('Flag: '))} {_sentence(li.not_penalized)}",
                             group="worth_knowing", so_what="No action needed; worth a look if the gap matters to you")
    elif li.status == "flag":
        li_id = findings.add("linkedin", "yellow", "LinkedIn differs, but LinkedIn was used to estimate the figure",
                             f"{_sentence(li.note.removeprefix('Flag: '))} LinkedIn data was already used to estimate "
                             "the value, so it is not an independent check. It was reported but not penalized.",
                             group="worth_knowing", so_what="Keep in mind the figure partly rests on LinkedIn")
    else:
        li_id = findings.add("linkedin", "yellow", "LinkedIn member count not available",
                             "No LinkedIn member count was visible in public search results. The sanity check could "
                             "not run, so confidence is unchanged.",
                             group="background", so_what="No action needed; the other checks still apply")

    # Events that were noted but not penalized (penalized ones are red findings via their flag).
    direction = cert.direction.direction if cert.direction else "unknown"
    for e in cert.events:
        if not e.penalized:
            when = e.close_date.isoformat() if e.close_date else "date unknown"
            if e.after_as_of:
                title = f"Change after the as-of date ({when}): {e.description}"
                so_what = (f"Today's headcount is likely {direction} than the certified figure; factor that in if "
                           "timing matters" if direction in ("higher", "lower") else
                           "Today's headcount may differ from the certified figure")
            elif e.close_date:
                title = f"Earlier change ({when}): {e.description}"
                so_what = "It happened before the figure's as-of date, so the figure already reflects it; no action needed"
            else:
                title = f"Change with no known date: {e.description}"
                so_what = "Its timing is unknown, so it may or may not be reflected in the figure"
            findings.add("event", "yellow", _first_sentence(title),
                         f"{e.reason} Policy lowers confidence only for material changes that take effect after the "
                         "as-of date.", [by_url[e.url]] if e.url in by_url else [],
                         group="worth_knowing", so_what=so_what)

    # Recency: an estimated as-of date, and the recency deduction.
    recency_id = None
    if selected is not None and selected.as_of_from_url:
        findings.add("recency", "yellow", f"As-of date estimated from the URL: {selected.as_of_date.isoformat()}",
                     f"The source states no date, so the as-of date comes from {selected.as_of_basis}. It is the "
                     "weakest kind of estimate; every recency rule uses it.", [ids[id(selected)]],
                     group="worth_knowing", so_what="Treat the as-of date as approximate")
    elif selected is not None and selected.as_of_estimated:
        findings.add("recency", "yellow", f"As-of date estimated: {selected.as_of_date.isoformat()}",
                     f"The source gives no as-of date, so it was estimated from {selected.as_of_basis or 'context'}. "
                     "Every recency rule uses the estimated date.", [ids[id(selected)]],
                     group="worth_knowing", so_what="Treat the as-of date as approximate")
    if selected is not None and rules.latest_release_current(selected, lookup_date, policy):
        due = rules.next_release_due(selected, policy)
        kind = _type_of(selected)
        findings.add("recency", "green", f"Latest {kind} release, as of {selected.as_of_date.isoformat()}",
                     f"{kind} is published well after its as-of date, so this is the newest figure available. Policy "
                     f"treats the latest release as current for recency until the next is due, around "
                     f"{due.strftime('%B %Y')}.", [ids[id(selected)]],
                     group="worth_knowing", chip="Counted as current (no recency penalty)",
                     so_what=f"Treat it as current; recheck after {due.strftime('%B %Y')}, when the next release is due")
    for note in cert.scope_notes:
        findings.add("scope", "yellow", _first_sentence(note, limit=90),
                     f"{_sentence(note)} It cannot change which entity is counted, so it is noted without a score "
                     "change.", group="worth_knowing",
                     so_what="No action needed; it doesn't change which organization is counted")
    recency_step = next((st for st in cert.confidence_breakdown if st.reason.startswith("recency:")), None)
    if recency_step is not None:
        recency_id = findings.add(
            "recency", "red", _first_sentence(recency_step.reason.removeprefix("recency: ").capitalize()),
            f"{_sentence(recency_step.reason.removeprefix('recency: ').capitalize())} Policy lowers confidence one "
            "level when the source is older than the window, because headcount may have changed since.",
            [ids[id(selected)]] if selected is not None else [], recency_step.points,
            group="affects" if recency_step.points else "worth_knowing",
            so_what=f"The figure is over {policy.recency.certified_max_age_months} months old; expect today's "
                    "headcount to differ",
            chip=None if recency_step.points else "No further effect (confidence already at its minimum)")

    # Newer data indicating a different current headcount.
    ir = cert.indicated_range
    indicated_row = None
    if ir is not None:
        ir_ids = [by_url[u] for u in ir.urls if u in by_url]
        indicated_row = IndicatedRangeRow(low=ir.low, high=ir.high, earliest=ir.earliest, latest=ir.latest,
                                          source_ids=ir_ids, rationale=ir.reason)
        findings.add("data_gap", "yellow",
                     f"Newer data indicates {f'about {ir.low:,}' if ir.low == ir.high else f'{ir.low:,}–{ir.high:,}'}",
                     ir.reason, ir_ids, group="worth_knowing",
                     so_what="Use the range as a sense-check of today's size, not as the certified figure")

    # Scope.
    partial = [s for s in cert.sources if s.scope == "partial"]
    broader = [s for s in cert.sources if s.scope == "broader"]
    if partial:
        findings.add("scope", "yellow", f"{len(partial)} figure(s) for only part of the organization set aside",
                     "Some figures cover only a region, segment or subsidiary. The certified count is for the whole "
                     "organization, so these are context only.", [ids[id(s)] for s in partial],
                     group="background", so_what="No action needed; only whole-organization figures are used")
    if broader:
        findings.add("scope", "yellow", f"{len(broader)} figure(s) include bodies outside the entity",
                     "Some figures also count bodies outside the entity, such as a school system. They are logged "
                     "with their variance and never used as the value.", [ids[id(s)] for s in broader],
                     group="background", so_what="No action needed; those figures are never used as the answer")

    # Definition: qualifier, basis, adjustments, specificity, source nuances.
    if selected is not None and cert.qualifier and cert.qualifier != "exact" and cert.count_type == "reported":
        words = {"more_than": "more than", "approximately": "approximately", "up_to": "up to"}[cert.qualifier]
        findings.add("definition", "yellow", f"Stated as '{words} {cert.certified_count:,}'",
                     f"The source gives a qualified figure, '{words} {cert.certified_count:,}'. Policy records the "
                     "stated number with its qualifier and widens the range instead of guessing.", [ids[id(selected)]],
                     group="worth_knowing", so_what="Use the range rather than the exact number if precision matters")
    if cert.count_basis == "fte":
        findings.add("definition", "yellow", "Full-time equivalents, not headcount",
                     "The source counts full-time equivalents rather than people. Policy keeps the FTE figure as "
                     "stated and never estimates it upward.", [ids[id(selected)]] if selected is not None else [],
                     group="worth_knowing",
                     so_what="If you need a count of people, expect it to be higher than the FTE figure")
    if selected is not None and any("More specific figure" in n for n in cert.rationale.split(". ")):
        findings.add("definition", "green", "Most specific figure chosen",
                     "A rounder statement and a more detailed figure for the same date were both found. The detailed "
                     "figure is in line with the rounder one, so it was used.", [ids[id(selected)]],
                     group="affects", so_what="No action needed; the more precise figure is used",
                     chip="Chose the more detailed figure")
    for adj in cert.adjustments:
        if adj.change:
            findings.add("definition", "yellow", _first_sentence(f"Adjusted {adj.source_figure:,} → {adj.result:,}"),
                         f"{_sentence(adj.reason)} The adjustment is logged with its inputs.",
                         [by_url[adj.source_url]] if adj.source_url in by_url else [],
                         group="affects", chip=f"Adjusted count {adj.change:+,}".replace("-", "−"),
                         so_what="The certified figure differs from the source's number for the reason given")
    if selected is not None:
        own = [n for n in selected.notes if not n.startswith(("Undated source", "Older than", "Partial or regional",
                                                              "Mirror of", "Not counted", "Latest release"))]
        if own:
            findings.add("definition", "yellow", "How the source defines its count",
                         f"{_sentence(' '.join(own))} It is recorded for transparency; the figure is used as stated.",
                         [ids[id(selected)]], group="worth_knowing",
                         so_what="Read the note if your definition of an employee differs")

    # Data gaps from the run.
    for n in notes or []:
        if "budget" in n.lower() and "reached" in n.lower():
            findings.add("data_gap", "yellow", "Research budget reached",
                         f"{_sentence(n)} Remaining tiers were not searched, so corroboration may be incomplete.",
                         group="background", so_what="Corroboration may be incomplete; Refresh later for a fuller check")

    return findings, base_step, base_id, corr_id, flag_ids, recency_id, li_id, indicated_row


def build_record(cert: Certification, policy: Policy | None = None, *, method: str = "engine",
                 models: dict[str, str] | None = None, cost_usd: float = 0.0, web_searches: int = 0,
                 web_fetches: int = 0, run_at: datetime | None = None, duration_s: float | None = None,
                 lookup_date: date | None = None, queries: list[str] | None = None,
                 notes: list[str] | None = None) -> CertificationRecord:
    policy = policy or default_policy()
    lookup_date = lookup_date or (run_at.date() if run_at else date.today())
    ids = {id(s): f"S{i + 1}" for i, s in enumerate(cert.sources)}
    by_url = {s.url: ids[id(s)] for s in cert.sources}
    selected = next((s for s in cert.sources if s.role == "selected"), None)
    findings, base_step, base_id, corr_id, flag_ids, recency_id, li_id, indicated_row = _build_findings(
        cert, policy, ids, by_url, selected, notes, lookup_date)
    li = cert.linkedin_check

    # Confidence breakdown, each line linked to a finding.
    lines = []
    for st in cert.confidence_breakdown:
        if st is base_step or st.reason == "no deductions":
            fid = base_id
        elif st.reason.startswith("corroborated by"):
            fid = corr_id
        elif st.reason.startswith("recency:") and recency_id:
            fid = recency_id
        else:
            fid = flag_ids.get(st.reason.split(" (no change: minimum")[0], base_id)
        lines.append(BreakdownLine(points=st.points, rationale=_sentence(st.reason), finding_id=fid))
    if not lines:
        lines = [BreakdownLine(points=cert.confidence_score, rationale="Base score from the confidence table.",
                               finding_id=base_id)]
    arithmetic = " ".join(f"{'+' if i and l.points >= 0 else '-' if l.points < 0 else ''} {abs(l.points)}".strip()
                          for i, l in enumerate(lines)) + f" = {cert.confidence_score}"

    # Sources.
    source_rows = [SourceRow(
        id=ids[id(s)], tier=s.tier, tier_name=policy.tiers[s.tier].name, **_labels(s), value=s.value,
        qualifier=s.qualifier,
        basis=s.basis, scope=s.scope, as_of_date=s.as_of_date, published_date=s.published_date,
        modified_date=s.modified_date, url=s.url, excerpt=s.excerpt, location=location_row(s),
        role=s.role or "supporting",
        used=s.role in ("selected", "corroborates", "derived_input"),
        tier_rationale=tier_rationale(s, cert.entity, policy),
        use_rationale=s.role_reason or "Recorded as context; not compared against the certified value.",
        notes=[n for n in s.notes if n not in s.role_reason and not n.startswith(("Not counted", "Mirror of"))])
        for s in cert.sources]

    upcoming = next_update(selected, lookup_date, policy)

    # Primary source.
    if selected is not None:
        primary = PrimarySource(
            source_id=ids[id(selected)], tier=selected.tier, tier_name=policy.tiers[selected.tier].name,
            **_labels(selected), url=selected.url, accession=accession_of(selected.url), excerpt=selected.excerpt,
            excerpt_missing_reason=None if selected.excerpt.strip() else "No verbatim excerpt was captured for this source.",
            location=location_row(selected),
            as_of_date=selected.as_of_date, published_date=selected.published_date,
            modified_date=selected.modified_date, tier_rationale=tier_rationale(selected, cert.entity, policy))
    else:
        primary = PrimarySource(
            source_id=None, tier=None, tier_name=None, url=None, accession=None, excerpt=None, location=None,
            as_of_date=None,
            published_date=None, modified_date=None, tier_rationale=None,
            none_reason=("The value was derived from tier 7-9 inputs, so no single source sets it."
                         if cert.certified_count is not None else "No usable source was found."))

    # Adjustments.
    adjustment_rows = [AdjustmentRow(id=f"A{i + 1}", source_id=by_url.get(a.source_url), source_figure=a.source_figure,
                                     change=a.change, result=a.result, rationale=_sentence(a.reason))
                       for i, a in enumerate(cert.adjustments)]

    # Trend, plus a forecast point when there are enough same-basis points (SPEC.md: Trend and forecast).
    trend_rows = [TrendRow(as_of_date=p.as_of_date, value=p.value, tier=p.tier, url=p.url, estimated=False,
                           rationale=f"Reported in a tier {p.tier} source as of {p.as_of_date.isoformat()}.")
                  for p in cert.trend]
    if not trend_rows and cert.certified_count is not None:  # still chart the certified figure on its own
        when = cert.as_of_date or lookup_date
        trend_rows = [TrendRow(as_of_date=when, value=cert.certified_count, tier=cert.policy_tier, url=None, estimated=False,
                               rationale=(f"The certified figure as of {when.isoformat()}; no other dated figures of the same "
                                          "kind were found." if cert.as_of_date else
                                          f"The certified figure, shown at the certification date ({when.isoformat()}) "
                                          "because its source is undated."))]
    if 0 < len(trend_rows) < 3 and cert.certified_count:
        trend_rows = _history(cert, trend_rows, notes or [], lookup_date) + trend_rows
    reported_only = [t for t in trend_rows if not t.historical]
    trend_rows += (_forecast(trend_rows) if len(reported_only) >= 3 and len(reported_only) == len(trend_rows)
                   else _short_forecast(trend_rows, cert.linkedin_check))

    events = [EventRow(description=e.description, url=e.url, close_date=e.close_date, penalized=e.penalized,
                       rationale=e.reason) for e in cert.events]

    entity = cert.entity
    relationship = (f"{entity.relationship_to_parent or 'Part'} of {entity.legal_parent}" if entity.legal_parent
                    else "Not known to be part of a larger organization")
    record = CertificationRecord(
        entity=EntitySection(name=entity.name, website=entity.website, hq=entity.hq,
                             address=entity.address or entity.hq,
                             address_source=entity.address_source or ("Confirmed headquarters location (city)"
                                                                      if entity.hq else None),
                             legal_parent=entity.legal_parent, relationship=relationship),
        headline=Headline(count=cert.certified_count, qualifier=cert.qualifier, range=_our_range(cert, policy),
                          count_type=cert.count_type, count_basis=cert.count_basis, as_of_date=cert.as_of_date,
                          as_of_estimated=cert.as_of_estimated,
                          as_of_estimated_from=("url" if cert.as_of_from_url else "context") if cert.as_of_estimated
                          else None,
                          direction=cert.direction.direction if cert.direction else None,
                          direction_reason=cert.direction.reason if cert.direction else None,
                          adjustment_status="pre-adjustment" if cert.pre_adjustment else "current",
                          known_changes=[f"{e.description} ({e.close_date.isoformat()}"
                                         + (f", {e.headcount_change:+,}" if e.headcount_change is not None else "") + ")"
                                         for e in cert.events if e.after_as_of and e.close_date],
                          indicated_current_range=indicated_row,
                          bottom_line=bottom_line(cert.confidence_score, cert.certified_count),
                          peer_level=private_company_note(cert)[0], peer_note=private_company_note(cert)[1],
                          next_expected_update=upcoming[0], next_update_note=upcoming[1],
                          none_reason=None if cert.certified_count is not None else "No usable source was found."),
        confidence=ConfidenceSection(score=cert.confidence_score, level=cert.confidence_level, breakdown=lines,
                                     arithmetic=arithmetic),
        primary_source=primary,
        findings=Section[Finding](items=findings.items),
        sources=Section[SourceRow](items=source_rows, none_reason=None if source_rows else "No sources were found."),
        adjustments=Section[AdjustmentRow](
            items=adjustment_rows,
            none_reason=None if adjustment_rows else "The figure was used as stated; no adjustments were needed."),
        trend=Section[TrendRow](
            items=trend_rows,
            none_reason=None if trend_rows else "Fewer than two dated figures of the same tier and basis were found."),
        linkedin_check=LinkedInSection(source_type_info=taxonomy.explain("LinkedIn: Member Count"), status=li.status, member_count=li.member_count, size_range=li.size_range,
                                       workforce_profile=li.workforce_profile, pass_range=li.implied_range,
                                       finding_id=li_id, rationale=li.note, growth_1y=li.growth_1y,
                                       growth_2y=li.growth_2y, open_roles=li.open_roles),
        events=Section[EventRow](items=events, none_reason=None if events else
                                 "No merger, acquisition or spinoff affecting headcount was confirmed."),
        methodology=Methodology(policy_version=cert.policy_version, record_version=RECORD_VERSION, method=method,
                                models=models or {}, cost_usd=cost_usd, web_searches=web_searches,
                                web_fetches=web_fetches, run_at=run_at, duration_s=duration_s, lookup_date=lookup_date,
                                queries=queries or [], notes=notes or []),
    )
    record.headline.story, record.headline.story_sources = our_take(record)
    return record


FORECAST_YEARS = 4


FORECAST_MAX_RATE = 0.15  # the yearly change a forecast may carry forward, either way
SHORT_SPREAD = 0.08        # a best-guess forecast's yearly range (±8%, widening) when history is short
SHORT_FORECAST_YEARS = 3   # a short history gets a shorter forecast (3 years; 4 with 3+ reported years)
GROWTH_FORECAST_CAP = 0.30 # with clear LinkedIn growth (25%+ a year), the forecast may carry up to 30% a year
LINKEDIN_WEIGHT = 0.5      # LinkedIn over-represents office staff: half of its growth carries into the forecast


HISTORY_MAX_YEARS = 10     # how far back a historical estimate may reach
HISTORY_MAX_POINTS = 3     # at most this many historical estimates
YOUNG_GROWTH = 0.30        # a young, growing organization with no history: assumed growth over the past year
HISTORICAL_WEIGHT = 0.35   # an older statement is weaker evidence: about a third of its growth carries forward
HISTORICAL_MAX_RATE = 0.03 # ...and never more than ±3% a year: older statements often count differently


def _our_range(cert: Certification, policy: Policy):
    """The one range we give, recomputed from the certification (so stored and sample results match new lookups):
    centred on the number and as wide as the confidence warrants, with a supported LinkedIn floor kept."""
    import re
    if cert.certified_count is None:
        return cert.range
    floor = None
    for a in cert.adjustments:
        m = re.search(r"a floor of ([\d,]+)", a.reason or "")
        if m and "LinkedIn members are taken" in a.reason:
            floor = int(m.group(1).replace(",", ""))
    direction = cert.direction.direction if cert.direction else None
    return rules.confidence_range(cert.certified_count, cert.confidence_score, cert.qualifier, direction, floor, policy)


def _month(d: date | None) -> str:
    return d.strftime("%b %Y") if d else "an unknown date"


def _n(v: float) -> str:
    return f"{int(round(v)):,}"


def our_take(r: "CertificationRecord") -> tuple[str | None, list[str]]:
    """Four short sentences at most: the answer, the evidence, the outlook, the confidence. Built only from this
    record's facts, so every number traces to a source, an adjustment or the trend."""
    h, c, p, name = r.headline, r.confidence, r.primary_source, r.entity.name
    if h.count is None:
        return None, []
    sources = r.sources.items
    providers = [s for s in sources if s.tier >= 7 and s.scope == "global"]
    li = r.linkedin_check
    floor = next((a for a in r.adjustments.items if "LinkedIn members are taken" in a.rationale), None)
    history = [t for t in r.trend.items if t.historical]
    forecast = [t for t in r.trend.items if t.estimated]
    out: list[str] = []
    q = {"more_than": "more than ", "up_to": "up to ", "approximately": "about "}.get(h.qualifier, "")
    spread = (f", most likely {_n(h.range[0])}–{_n(h.range[1])}" if h.range and h.range[0] != h.range[1]
              and h.qualifier != "more_than" else "")
    if p.source_id and p.tier <= 2 and h.count_type == "reported":
        out.append(f"{name} reports {q}{_n(h.count)} employees as of {_month(h.as_of_date)}, in its {p.source_type}.")
    else:
        when = f", as of {_month(h.as_of_date)}" if h.as_of_date else " (the source is undated)"
        out.append(f"We put {name} at {q or 'about '}{_n(h.count)} employees{spread}{when}.")

    # The evidence: what the number rests on, in one sentence.
    lo_hi = (f"{_n(min(s.value for s in providers))}–{_n(max(s.value for s in providers))}" if len(providers) > 1
             else _n(providers[0].value) if providers else None)
    hiring = []
    if li.growth_1y is not None and li.growth_1y >= 0.1:
        hiring.append(f"up {li.growth_1y:.0%} in a year")
    if li.open_roles:
        hiring.append(f"{_n(li.open_roles)} open roles")
    if floor and li.member_count:
        out.append(f"It doesn't publish a headcount and data providers say {lo_hi}, but LinkedIn shows "
                   f"{_n(li.member_count)} members" + (f" ({', '.join(hiring)})" if hiring else "") +
                   f", so we count at least {_floor_share(floor.rationale)} of them as real employees.")
    elif not p.source_id and providers:
        out.append(f"It doesn't publish a headcount, so this blends {len(providers)} data provider figures ({lo_hi}), "
                   "which often draw on LinkedIn.")
    elif p.source_id and p.tier <= 2:
        agree = sum(1 for s in sources if s.role == "corroborates")
        out.append("That's the strongest kind of source" + (
            f", and {'an independent source agrees' if agree == 1 else f'{agree} independent sources agree'}."
            if agree else "; nothing independent confirms it yet."))
    elif p.source_id:
        kind, _, detail = (p.source_type or "").partition(": ")
        where = (f"the company's own {detail.lower().replace('about us', 'About page')}" if kind == "Website"
                 else f"a {detail} report quoting the company" if kind.startswith("News") and detail
                 else f"the company's {detail or kind}")
        out.append(f"It comes from {where}" + (f" (\u201c{_short_quote(p.excerpt)}\u201d)" if p.excerpt else "")
                   + (f"; data providers say {lo_hi}." if lo_hi else "."))

    # The outlook: where it came from and where it's heading.
    trend = []
    if history:
        trend.append(f"up from about {_n(history[0].value)} in {history[0].as_of_date.year}")
    change = h.known_changes[0].split(" (")[0].split(";")[0].rstrip(".") if h.known_changes else ""
    if len(change.split()) >= 4:  # a readable clause, not a bare filing reference
        trend.append("since then, " + (change if len(change) <= 90 else change[:89].rsplit(" ", 1)[0] + "…"))
    if forecast:
        f = forecast[-1]
        trend.append(f"on this trend, roughly {_n(round(f.value, -2 if f.value >= 2000 else -1))} by {f.as_of_date.year}")
    if trend:
        out.append(trend[0][0].upper() + trend[0][1:] + ("; " + "; ".join(trend[1:]) if trend[1:] else "") + ".")

    # The confidence, and what would raise it.
    if c.score >= 4:
        raise_it = "ready to use."
    elif not p.source_id:
        raise_it = "a company statement, such as an executive interview or press release with a headcount, would raise it."
    elif p.tier >= 4:
        raise_it = "a dated company document or filing would raise it."
    else:
        raise_it = h.next_update_note[0].lower() + h.next_update_note[1:] if h.next_update_note else "a newer filing would raise it."
    out.append(f"Confidence {c.score}/5: {raise_it}")

    # Worth a look: the key source, and the source that differs most from the answer.
    if not p.source_id and len(providers) > 1:  # no key source: the highest and lowest estimates
        hi_s, lo_s = max(providers, key=lambda s: s.value), min(providers, key=lambda s: s.value)
        return " ".join(out), [hi_s.id, lo_s.id]
    pointers = [p.source_id] if p.source_id else []
    others = [s for s in sources if s.id not in pointers and s.tier <= 6] or [s for s in sources if s.id not in pointers]
    if others:
        pointers.append(max(others, key=lambda s: (abs(s.value - h.count) / max(1, h.count), -s.tier)).id)
    return " ".join(out), pointers[:2]


def _floor_share(rationale: str) -> str:
    import re
    m = re.search(r"at least (\d+%)", rationale)
    return m.group(1) if m else "75%"


def _short_quote(text: str, limit: int = 50) -> str:
    text = " ".join((text or "").replace("·", " ").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


_DIRECTION_WORDS = re.compile(r"(growing|expanding|scaling|hiring rapidly|shrinking|downsizing|contracting|laid off|layoffs)",
                              re.I)
_FOUNDED = re.compile(r"\b(?:founded|established|launched|started|incorporated)(?: in)? ((?:19|20)\d\d)\b", re.I)


def growth_theme(cert: Certification, notes: list[str], lookup_date: date) -> tuple[str | None, str]:
    """The high-level shape of the organization, from the strongest evidence first: LinkedIn headcount growth; the
    company's own older statements; a recent founding year (research notes). ("growing" | "shrinking" | None, why)."""
    li = cert.linkedin_check
    growth = li.growth_1y if li.growth_1y is not None else (li.growth_2y / 2 if li.growth_2y is not None else None)
    if growth is not None and abs(growth) >= 0.05:
        return ("growing" if growth > 0 else "shrinking"), f"LinkedIn shows {growth:+.0%} a year"
    value, as_of = cert.certified_count, cert.as_of_date or lookup_date
    company = [s for s in cert.sources if s.tier <= 6 and s.scope == "global" and s.as_of_date and s.as_of_date.year < as_of.year
               and s.value]
    if value and company:
        first = min(company, key=lambda s: s.as_of_date)
        if first.value < value * 0.95:
            return "growing", f"the company's own figures rise from {first.value:,} in {first.as_of_date.year}"
        if first.value > value * 1.05:
            return "shrinking", f"the company's own figures fall from {first.value:,} in {first.as_of_date.year}"
    research = " ".join(notes)
    m = _DIRECTION_WORDS.search(research)
    if m:
        shrink = m.group(1).lower() in ("shrinking", "downsizing", "contracting", "laid off", "layoffs")
        return ("shrinking" if shrink else "growing"), f"research describes it as {m.group(1).lower()}"
    text = research + " " + " ".join(n for s in cert.sources for n in s.notes)
    years = [int(y) for y in _FOUNDED.findall(text) if 1900 < int(y) <= lookup_date.year]
    if years and lookup_date.year - max(years) <= 10:
        return "growing", f"founded in {max(years)}, so still building its team"
    return None, ""


def _history(cert: Certification, rows: list[TrendRow], notes: list[str] | None = None,
             lookup_date: date | None = None) -> list[TrendRow]:
    """Historical estimates for a short history, from every route, strongest first, one point per year (up to
    three): older company-voice statements (tiers 1-6); a back-cast from LinkedIn's headcount growth; older
    data-provider figures (tiers 7-9). The organization's growth theme comes first: a weak data-provider figure that
    contradicts it (above today's figure for a growing organization, below for a shrinking one) is used only when two
    or more providers agree on it. A young, growing organization with nothing else gets one assumed point a year back.
    Each is labelled with where it came from; none is certified."""
    lookup_date = lookup_date or rows[-1].as_of_date
    theme, why = growth_theme(cert, notes or [], lookup_date)
    value = cert.certified_count
    providers = _historical_points(cert, rows, 9, min_tier=7)
    if theme and value:
        def agrees(t: TrendRow) -> bool:
            return t.value < value if theme == "growing" else t.value > value

        def corroborated(t: TrendRow) -> bool:
            peers = [s for s in cert.sources if s.tier >= 7 and s.as_of_date and s.as_of_date.year == t.as_of_date.year
                     and s.value and abs(s.value - t.value) / t.value <= 0.15]
            return len({rules._publisher(s.url) for s in peers}) >= 2
        providers = [t for t in providers if agrees(t) or corroborated(t)]
    picked: dict[int, TrendRow] = {}
    for route in (_historical_points(cert, rows, 6), _linkedin_backcast(cert, rows), providers):
        for t in route:
            picked.setdefault(t.as_of_date.year, t)
        if len(picked) >= HISTORY_MAX_POINTS:
            break
    if not picked and theme == "growing" and value and not why.startswith("LinkedIn"):
        when = rows[0].as_of_date - timedelta(days=365)
        picked[when.year] = TrendRow(
            as_of_date=when, value=round(value / (1 + YOUNG_GROWTH)), tier=None, url=None, estimated=False, historical=True,
            rationale=f"Historical estimate: assumed {YOUNG_GROWTH:.0%} growth over the past year for a young, growing "
                      f"organization ({why}); not a reported figure.")
    return [picked[y] for y in sorted(picked)][-HISTORY_MAX_POINTS:]


def _historical_points(cert: Certification, rows: list[TrendRow], max_tier: int = 6, min_tier: int = 1) -> list[TrendRow]:
    """Older figures from the given tiers (1-6 company voice: filings, the company's own pages and press, LinkedIn
    description, an executive quoted in the press; 7-9 data providers) dated before the first trend point, one per
    year, plausible against the certified figure (within 5x either way). They give a short history some shape; they
    are never certified."""
    first = rows[0].as_of_date
    by_year: dict[int, Source] = {}
    for s in cert.sources:
        if (s.as_of_date is None or s.as_of_date >= first or not min_tier <= s.tier <= max_tier or s.scope != "global"
                or s.basis != "headcount"
                or s.corroboration_only or not s.value or (first - s.as_of_date).days > 365.25 * HISTORY_MAX_YEARS
                or not (0.1 if (first - s.as_of_date).days <= 365.25 * 4 else 0.2) <= s.value / cert.certified_count <= 5
                or s.as_of_date.year == first.year):
            continue
        current = by_year.get(s.as_of_date.year)
        if current is None or (s.tier, -s.as_of_date.toordinal()) < (current.tier, -current.as_of_date.toordinal()):
            by_year[s.as_of_date.year] = s
    picks = [by_year[y] for y in sorted(by_year)][-HISTORY_MAX_POINTS:]
    kind = "a data provider's figure" if min_tier >= 7 else "an older statement"
    return [TrendRow(as_of_date=s.as_of_date, value=s.value, tier=s.tier, url=s.url, estimated=False, historical=True,
                     rationale=f"Historical estimate from {kind} (tier {s.tier}) as of {s.as_of_date.isoformat()}: context "
                               "for the trend, not a certified figure.")
            for s in picks]


def _linkedin_backcast(cert: Certification, rows: list[TrendRow]) -> list[TrendRow]:
    """With LinkedIn headcount growth (1-year, and 2-year when known), estimate where the certified figure stood one
    and two years earlier: the growth on LinkedIn is real hiring even when the member total is a little inflated.
    Marked as historical estimates, never certified."""
    li = cert.linkedin_check
    if li is None or (li.growth_1y is None and li.growth_2y is None):
        return []
    last = rows[0]
    out = []
    for years, growth in ((2, li.growth_2y), (1, li.growth_1y)):
        if growth is None or growth <= -0.9:
            continue
        when = last.as_of_date - timedelta(days=round(365.25 * years))
        value = round(last.value / (1 + growth))
        out.append(TrendRow(as_of_date=when, value=value, tier=None, url=None, estimated=False, historical=True,
                            rationale=f"Historical estimate: the certified figure less LinkedIn's {growth:+.0%} "
                                      f"{years}-year headcount growth; not a reported figure."))
    return out


def _short_forecast(points: list[TrendRow], li) -> list[TrendRow]:
    """A best-guess forecast when there are fewer than 3 reported points: level, or following LinkedIn's headcount
    growth (half of it, capped) when research found it, or the change since the first point (half of it between
    reported figures; about a third since a historical estimate), capped. The range
    starts at ±8% and widens with the square root of the years ahead. Always marked as an estimate."""
    if not points:
        return []
    last = points[-1]
    growth = li.growth_1y if li is not None and li.growth_1y is not None else (
        li.growth_2y / 2 if li is not None and li.growth_2y is not None else None)
    if growth is not None:
        cap = GROWTH_FORECAST_CAP if growth >= 0.25 else FORECAST_MAX_RATE  # clear growth may carry further
        rate = max(-FORECAST_MAX_RATE, min(cap, growth * LINKEDIN_WEIGHT))
        basis = (f"half of LinkedIn's {growth:+.0%} yearly headcount growth ({rate:+.1%} a year"
                 + (", capped" if rate == cap else "") + ")")
    elif len(points) >= 2 and points[0].value:
        first = points[0]
        years = max(0.5, (last.as_of_date - first.as_of_date).days / 365.25)
        change = (last.value / first.value) ** (1 / years) - 1
        values = [p.value for p in points]
        steady = ((len(points) >= 3 and years <= 4.5) or years <= 2.5)  # several recent points, or one recent one
        steady = (steady
                  and (all(a < b for a, b in zip(values, values[1:])) or all(a > b for a, b in zip(values, values[1:]))))
        if first.historical and steady:
            cap = GROWTH_FORECAST_CAP if change >= 0.25 else FORECAST_MAX_RATE
            rate = max(-FORECAST_MAX_RATE, min(cap, change * 0.5))
            basis = (f"half the steady growth shown since {first.as_of_date.year} ({change:+.0%} a year then; "
                     f"{rate:+.1%} a year carried forward)")
        elif first.historical:
            rate = max(-HISTORICAL_MAX_RATE, min(HISTORICAL_MAX_RATE, change * HISTORICAL_WEIGHT))
            basis = (f"a gentle lean from the growth since the {first.as_of_date.year} historical estimate "
                     f"({rate:+.1%} a year carried forward, at most ±{HISTORICAL_MAX_RATE:.0%})")
        else:
            rate = max(-FORECAST_MAX_RATE, min(FORECAST_MAX_RATE, change * 0.5))
            basis = f"half the change between the reported figures ({rate:+.1%} a year)"
    else:
        rate, basis = 0.0, "level, since there is no earlier figure or growth signal"
    out = []
    for k in range(1, SHORT_FORECAST_YEARS + 1):
        when = last.as_of_date + timedelta(days=round(365.25 * k))
        value = round(last.value * (1 + rate) ** k)
        width = round(value * SHORT_SPREAD * math.sqrt(k))
        out.append(TrendRow(as_of_date=when, value=value, tier=None, url=None, estimated=True,
                            low=max(0, value - width), high=value + width,
                            rationale=f"Best-guess estimate, year {k} of {SHORT_FORECAST_YEARS}: {basis}, with a range of "
                                      f"±{SHORT_SPREAD:.0%} that widens each year; not a reported figure."))
    return out


def _forecast(points: list[TrendRow]) -> list[TrendRow]:
    """The trend over at least 3 dated points, projected FORECAST_YEARS ahead from the latest figure. The fitted
    yearly change is applied as a rate, capped at FORECAST_MAX_RATE, so a one-off drop (a divestment) can't
    project the workforce to zero. The range starts from the historical year-over-year variation and widens with
    the square root of the years ahead."""
    if len(points) < 3:
        return []
    xs = [p.as_of_date.toordinal() for p in points]
    ys = [p.value for p in points]
    slope, _ = statistics.linear_regression(xs, ys)
    last = ys[-1]
    rate = max(-FORECAST_MAX_RATE, min(FORECAST_MAX_RATE, slope * 365.25 / last))
    changes = [(b - a) / a for a, b in zip(ys, ys[1:]) if a]
    spread = max(0.04, min(statistics.pstdev(changes), FORECAST_MAX_RATE) if len(changes) > 1 else 0)
    capped = rate != slope * 365.25 / last
    out = []
    for k in range(1, FORECAST_YEARS + 1):
        when = points[-1].as_of_date + timedelta(days=round(365.25 * k))
        value = round(last * (1 + rate) ** k)
        width = round(value * spread * math.sqrt(k))
        out.append(TrendRow(as_of_date=when, value=value, tier=None, url=None, estimated=True,
                            low=max(0, value - width), high=value + width,
                            rationale=f"Estimated, year {k} of {FORECAST_YEARS}: the trend over {len(points)} reported "
                                      f"points ({rate:+.1%} a year{', capped' if capped else ''}) from the latest "
                                      "figure, with a range from their year-over-year variation that widens each "
                                      "year; not a reported figure."))
    return out


def record_from_lookup(result, policy: Policy | None = None, lookup_date: date | None = None) -> CertificationRecord:
    """Build the record for a service.LookupResult."""
    return build_record(result.certification, policy, method=result.method, models=result.models,
                        cost_usd=result.cost_usd, web_searches=result.web_searches, web_fetches=result.web_fetches,
                        run_at=result.run_at, duration_s=result.duration_s, lookup_date=lookup_date,
                        queries=result.queries, notes=result.notes)
