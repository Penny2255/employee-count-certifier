"""Data models for sources, LinkedIn evidence and the certification record (SPEC.md)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Qualifier = Literal["exact", "more_than", "approximately", "up_to"]
CountType = Literal["reported", "calculated", "estimated"]
# partial: one region or segment. broader: also covers bodies outside the entity (e.g., a school system).
Scope = Literal["global", "partial", "broader"]
Basis = Literal["headcount", "fte"]
WorkforceProfile = Literal["white_collar", "mixed", "blue_collar"]
LinkedInStatus = Literal["pass", "flag", "not_available"]
SourceRole = Literal["selected", "derived_input", "corroborates", "conflicts", "supporting"]


PageBasis = Literal["printed", "html_page", "pdf", "form"]


class Location(BaseModel):
    """Where in the document the figure appears, with a detailed verbatim passage."""

    section: str | None = None  # e.g. "Item 1. Business › Human Capital Management"
    page: str | None = None  # page number as shown, e.g. "10"
    page_basis: PageBasis | None = None  # printed page, position in the HTML filing, PDF page, or form page
    context: str = ""  # detailed excerpt: the quote with the sentences around it, verbatim
    deep_link: str | None = None  # URL that scrolls to the quote (text fragment), where supported
    note: str | None = None  # how it was located, or why the section or page is unknown


class Source(BaseModel):
    """One candidate figure found during research."""

    url: str
    tier: int = Field(ge=1, le=9)
    value: int = Field(ge=0)
    qualifier: Qualifier = "exact"
    excerpt: str = ""
    location: Location | None = None
    as_of_date: date | None = None
    published_date: date | None = None
    modified_date: date | None = None  # last-updated date, when the page shows one
    scope: Scope = "global"
    basis: Basis = "headcount"  # fte = full-time equivalents, kept as stated
    # Counting-rule inputs: contractors included in `value`, or a per-worker-type breakdown.
    contractors_included: int | None = None
    components: dict[str, int] | None = None
    # Categories a formal report lists outside its stated total (e.g., IPEDS graduate assistants):
    # logged, never added.
    separately_reported: dict[str, int] | None = None
    # True when the source repeats another source's figure (Wikipedia or an aggregator quoting the
    # 10-K): it is not independent evidence and never corroborates.
    restates: bool = False
    # Set by the engine.
    corroboration_only: bool = False  # e.g. a mirror of a tier 1 filing: may corroborate, never selected
    role: SourceRole | None = None
    role_reason: str = ""  # one sentence: why the source was used or excluded
    notes: list[str] = Field(default_factory=list)

    @property
    def undated(self) -> bool:
        return self.as_of_date is None

    @property
    def latest_published(self) -> date | None:
        """Publish date, or the modified date when the page was updated later."""
        dates = [d for d in (self.published_date, self.modified_date) if d is not None]
        return max(dates) if dates else None

    @property
    def recency_date(self) -> date | None:
        return self.as_of_date or self.latest_published


class Adjustment(BaseModel):
    source_url: str
    source_figure: int | None
    change: int = 0
    reason: str
    result: int | None


class LinkedInEvidence(BaseModel):
    member_count: int | None = None
    size_range: tuple[int, int] | None = None
    workforce_profile: WorkforceProfile | None = None
    # Headcount growth from the LinkedIn Insights tab, as fractions (0.27 = 27%).
    growth_6m: float | None = None
    growth_1y: float | None = None
    growth_2y: float | None = None


class LinkedInCheck(BaseModel):
    member_count: int | None
    size_range: tuple[int, int] | None
    workforce_profile: WorkforceProfile
    implied_range: tuple[int, int] | None
    size_range_agrees: bool | None
    status: LinkedInStatus
    note: str


class Event(BaseModel):
    """A merger, acquisition or spinoff. It lowers confidence only when it closed after the
    selected source's as-of date, so the figure can't include it."""

    description: str
    url: str | None = None
    close_date: date | None = None


class EventOutcome(BaseModel):
    description: str
    url: str | None
    close_date: date | None
    penalized: bool
    reason: str


class ScoreStep(BaseModel):
    points: int  # the base score for the first step, then +/- adjustments
    reason: str


class TrendPoint(BaseModel):
    as_of_date: date
    value: int
    tier: int
    url: str


class Entity(BaseModel):
    name: str
    website: str | None = None
    hq: str | None = None
    legal_parent: str | None = None
    relationship_to_parent: str | None = None


class Certification(BaseModel):
    entity: Entity
    certified_count: int | None
    count_type: CountType | None
    qualifier: Qualifier | None
    count_basis: Basis | None = None
    range: tuple[int, int] | None
    confidence_score: int = Field(ge=0, le=5)
    confidence_level: str
    confidence_breakdown: list[ScoreStep] = Field(default_factory=list)
    policy_tier: int | None
    as_of_date: date | None
    sources: list[Source]
    linkedin_check: LinkedInCheck
    adjustments: list[Adjustment]
    flags: list[str]
    events: list[EventOutcome] = Field(default_factory=list)
    rationale: str
    trend: list[TrendPoint] = Field(default_factory=list)  # oldest to newest, same tier and basis
    forecast: dict | None = None
    policy_version: str
