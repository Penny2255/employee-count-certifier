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


class Source(BaseModel):
    """One candidate figure found during research."""

    url: str
    tier: int = Field(ge=1, le=9)
    value: int = Field(ge=0)
    qualifier: Qualifier = "exact"
    excerpt: str = ""
    as_of_date: date | None = None
    published_date: date | None = None
    scope: Scope = "global"
    basis: Basis = "headcount"  # fte = full-time equivalents, kept as stated
    # Counting-rule inputs: contractors included in `value`, or a per-worker-type breakdown.
    contractors_included: int | None = None
    components: dict[str, int] | None = None
    # Categories a formal report lists outside its stated total (e.g., IPEDS graduate assistants):
    # logged, never added.
    separately_reported: dict[str, int] | None = None
    # Set by the engine.
    role: SourceRole | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def undated(self) -> bool:
        return self.as_of_date is None

    @property
    def recency_date(self) -> date | None:
        return self.as_of_date or self.published_date


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
    policy_tier: int | None
    as_of_date: date | None
    sources: list[Source]
    linkedin_check: LinkedInCheck
    adjustments: list[Adjustment]
    flags: list[str]
    rationale: str
    trend: list[dict] = Field(default_factory=list)
    forecast: dict | None = None
    policy_version: str
