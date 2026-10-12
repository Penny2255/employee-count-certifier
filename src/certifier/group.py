# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Multi-entity results (SPEC.md: Entity groups). Example: a university (IPEDS), its health
system, and a grand total across both. Each entity is certified on its own; this module picks
which entry is the primary reported metric and builds an estimated grand total when needed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .models import Adjustment, Certification, Entity, LinkedInCheck
from .policy import Policy, default_policy

GroupRole = Literal["grand_total", "institution", "affiliate"]


class GroupEntry(BaseModel):
    role: GroupRole
    primary: bool
    certification: Certification


class GroupResult(BaseModel):
    primary_role: GroupRole
    entries: list[GroupEntry]
    rationale: str


def _estimated_total(parent_name: str, parts: list[Certification], policy: Policy) -> Certification:
    """Sum of the parts: estimated, one confidence level below the weakest part (floor 1)."""
    value = sum(p.certified_count for p in parts)
    low = sum(p.range[0] for p in parts)
    high = sum(p.range[1] for p in parts)
    score = max(1, min(p.confidence_score for p in parts) - 1)
    breakdown = " + ".join(f"{p.entity.name} {p.certified_count:,}" for p in parts)
    return Certification(
        entity=Entity(name=f"{parent_name} (grand total)"), certified_count=value, count_type="estimated",
        qualifier="approximately", count_basis="headcount", range=(low, high), confidence_score=score,
        confidence_level=policy.confidence_levels[score], policy_tier=max(p.policy_tier for p in parts),
        as_of_date=min((p.as_of_date for p in parts if p.as_of_date), default=None),
        sources=[s for p in parts for s in p.sources],
        linkedin_check=LinkedInCheck(member_count=None, size_range=None, workforce_profile="mixed",
                                     implied_range=None, size_range_agrees=None, status="not_available",
                                     note="Not checked for a summed total."),
        adjustments=[Adjustment(source_url="(sum of entities)", source_figure=None, change=0, result=value,
                                reason=f"Grand total estimated as the sum of separately certified entities: "
                                       f"{breakdown}. Sources differ in date and definition.")],
        flags=[], policy_version=policy.policy_version,
        rationale=f"Estimated as the sum of known entities ({breakdown}); confidence is one level below "
                  f"the weakest part. Other affiliated entities may exist.",
    )


def certify_group(parent_name: str, institution: Certification, affiliates: list[Certification],
                  grand_total: Certification | None = None, wholly_owned_proven: bool = False,
                  policy: Policy | None = None) -> GroupResult:
    """Choose the primary metric for an institution with affiliated entities.

    The grand total is primary only when it comes from a tier 1-2 source as reported and the
    institution is proven to wholly own the affiliates. Otherwise the institution's own count is
    primary and the grand total (stated, or estimated from the parts) is secondary.
    """
    policy = policy or default_policy()
    total_is_primary = (
        grand_total is not None and wholly_owned_proven and grand_total.policy_tier is not None
        and policy.tier_class(grand_total.policy_tier) == "primary" and grand_total.count_type == "reported"
    )
    if grand_total is None and affiliates and all(c.certified_count is not None for c in [institution, *affiliates]):
        grand_total = _estimated_total(parent_name, [institution, *affiliates], policy)

    entries = []
    if grand_total is not None:
        entries.append(GroupEntry(role="grand_total", primary=total_is_primary, certification=grand_total))
    entries.append(GroupEntry(role="institution", primary=not total_is_primary, certification=institution))
    entries += [GroupEntry(role="affiliate", primary=False, certification=a) for a in affiliates]

    if total_is_primary:
        why = ("The grand total comes from a primary source and the institution is proven to wholly own "
               "its affiliates, so the grand total is the primary metric.")
    elif grand_total is None:
        why = "No affiliate or grand total figures found; the institution's own count is the primary metric."
    else:
        reason = ("ownership of the affiliates is not proven" if not wholly_owned_proven
                  else "the grand total is not from a primary reported source")
        why = (f"The institution's own count ({institution.entity.name}) is the primary metric because {reason}; "
               "the grand total is reported as a secondary figure.")
    return GroupResult(primary_role="grand_total" if total_is_primary else "institution", entries=entries,
                       rationale=why)
