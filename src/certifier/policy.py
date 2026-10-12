"""Load policy.yaml into a typed Policy object."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "policy.yaml"


class TierInfo(BaseModel):
    cls: str = Field(alias="class")
    name: str


class Models(BaseModel):
    research: str
    extraction: str


class Budget(BaseModel):
    max_cost_usd_per_lookup: float
    max_web_searches_per_entity: int
    max_web_searches_when_sec_filer: int = 4
    max_web_fetches_per_entity: int = 4
    fetch_max_content_tokens: int = 12000
    effort: str = "medium"
    max_continuations: int = 3
    web_search_tool: str = "web_search_20250305"
    web_fetch_tool: str = "web_fetch_20250910"


class ModelPrice(BaseModel):
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float


class Pricing(BaseModel):
    models: dict[str, ModelPrice]
    web_search_per_1000: float


class Recency(BaseModel):
    certified_max_age_months: int
    stale_after_months: int


class Agreement(BaseModel):
    corroborates_within: float
    conflict_above: float
    corroboration_window_months: int = 9


class IndicatedRangePolicy(BaseModel):
    min_anchor_age_months: int = 12  # only for certified figures at least this old
    max_source_age_months: int = 12  # newer figures dated within this window of the lookup
    min_newer_by_months: int = 3  # and at least this much newer than the anchor
    min_divergence: float = 0.05  # and their mean differs from the certified value by at least this


class Provenance(BaseModel):
    sec_hosts: list[str] = ["sec.gov"]


class LinkedInProfile(BaseModel):
    members_per_employee: tuple[float, float]


class LinkedInPolicy(BaseModel):
    default_profile: str
    profiles: dict[str, LinkedInProfile]
    member_overage_tolerance: dict[str, float] = {}


class GrowthAdjustment(BaseModel):
    applies_to_tiers: list[int]
    min_age_months: dict[str, int]  # by tier class
    min_member_gap: float
    min_growth: float
    weight_toward_members: float
    round_to_significant: int
    confidence: int
    min_tertiary_sources: int = 2
    tertiary_max_age_months: int = 12


class FactSheetRule(BaseModel):
    """A company's official Corporate Fact Sheet is primary: tier 2, or tier 3 when it has no date at all."""

    tier: int = 2
    undated_tier: int = 3


class Policy(BaseModel):
    policy_version: str
    models: Models
    budget: Budget
    pricing: Pricing
    tiers: dict[int, TierInfo]
    recency: Recency
    agreement: Agreement
    provenance: Provenance = Provenance()
    indicated_range: IndicatedRangePolicy = IndicatedRangePolicy()
    fact_sheet: FactSheetRule = FactSheetRule()
    confidence_levels: dict[int, str]
    range_bands: dict[str, tuple[float, float]]
    qualifier_phrases: dict[str, list[str]]
    growth_adjustment: GrowthAdjustment
    research_guidelines: list[str] = []
    linkedin: LinkedInPolicy

    def tier_class(self, tier: int) -> str:
        return self.tiers[tier].cls


def load_policy(path: str | os.PathLike | None = None) -> Policy:
    path = Path(path or os.environ.get("CERTIFIER_POLICY") or DEFAULT_POLICY_PATH)
    with open(path, encoding="utf-8") as f:
        return Policy.model_validate(yaml.safe_load(f))


@lru_cache(maxsize=1)
def default_policy() -> Policy:
    return load_policy()
