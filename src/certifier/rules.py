"""Deterministic policy rules from SPEC.md. Pure functions, no I/O."""

from __future__ import annotations

import calendar
import math
from datetime import date
from typing import NamedTuple

from .models import Adjustment, LinkedInCheck, LinkedInEvidence, Qualifier, Source
from .policy import Policy

# --- Recency -----------------------------------------------------------------


def within_months(d: date, lookup_date: date, months: int) -> bool:
    """True if `d` is no more than `months` calendar months before `lookup_date`."""
    total = lookup_date.year * 12 + lookup_date.month - 1 - months
    year, month = divmod(total, 12)
    day = min(lookup_date.day, calendar.monthrange(year, month + 1)[1])
    return d >= date(year, month + 1, day)


def is_stale(source: Source, lookup_date: date, policy: Policy) -> bool:
    """Dated (as-of, else published) and older than the stale window. Undated is never stale."""
    ref = source.recency_date
    return ref is not None and not within_months(ref, lookup_date, policy.recency.stale_after_months)


def relative_diff(value: int, reference: int) -> float:
    if reference == 0:
        return 0.0 if value == 0 else math.inf
    return abs(value - reference) / reference


# --- Counting rules ----------------------------------------------------------


def apply_counting_rules(source: Source) -> tuple[int, list[Adjustment]]:
    """Apply counting rule 1 (worker types) to one source; return value and log."""
    log: list[Adjustment] = []
    value = source.value
    if source.components:
        total = sum(source.components.values())
        parts = ", ".join(f"{k} {v:,}" for k, v in source.components.items())
        log.append(Adjustment(source_url=source.url, source_figure=value, change=total - value,
                              reason=f"Summed separately reported worker types ({parts})", result=total))
        value = total
    if source.contractors_included:
        new = value - source.contractors_included
        log.append(Adjustment(source_url=source.url, source_figure=value, change=-source.contractors_included,
                              reason=f"Subtracted {source.contractors_included:,} independent contractors "
                                     "included in the reported figure", result=new))
        value = new
    for category, count in (source.separately_reported or {}).items():
        log.append(Adjustment(source_url=source.url, source_figure=value, change=0, result=value,
                              reason=f"Noted, not added: {category} ({count:,}) reported separately from the "
                                     "formal total, whose definition is accepted as stated"))
    return value, log


# --- Selection ---------------------------------------------------------------


def _rank_key(source: Source) -> tuple:
    """Lower sorts first: higher tier, then newer date (dated before undated)."""
    ref = source.recency_date
    return (source.tier, ref is None, -(ref.toordinal() if ref else 0))


def specificity(source: Source) -> tuple[bool, int]:
    """Higher is more specific: headcount before FTE, exact before qualified, then more significant
    digits (112,234 > 110,000)."""
    return source.basis == "headcount", source.qualifier == "exact", len(str(source.value).rstrip("0"))


def in_line(specific: Source, general: Source, policy: Policy) -> bool:
    """True if a more specific figure is consistent with a rounded or qualified statement of the same count."""
    if relative_diff(specific.value, general.value) > policy.agreement.corroborates_within:
        return False
    if specific.basis == "headcount" and general.basis == "fte":
        return specific.value >= general.value  # headcount can't be below FTE
    if general.qualifier == "more_than":
        return specific.value >= general.value
    if general.qualifier == "up_to":
        return specific.value <= general.value
    return True


class Pick(NamedTuple):
    source: Source | None
    notes: list[str]
    flags: list[str]
    inconsistent: list[Source]  # more specific figures not in line with the headline


def best_of(sources: list[Source], policy: Policy) -> Pick:
    """Best source by tier and date; among peers with the same tier and date, the most specific
    figure that is in line with every less specific one ("more than 110,000" -> 112,234)."""
    if not sources:
        return Pick(None, [], [], [])
    top = min(_rank_key(s) for s in sources)
    same_rank = [s for s in sources if _rank_key(s) == top]
    # A global total is at least as large as any part of it, so restatements of the total cluster
    # near the largest figure; much smaller figures in the same document are other quantities.
    largest = max(s.value for s in same_rank)
    peers = sorted((s for s in same_rank if relative_diff(s.value, largest) <= policy.agreement.conflict_above),
                   key=specificity, reverse=True)
    ignored = len(same_rank) - len(peers)
    for i, candidate in enumerate(peers):
        # Only rounder figures close enough to be a restatement of the same count are checked;
        # unrelated figures in the same document ("9,000 employees were let go") are not.
        general = [g for g in peers[i + 1:] if specificity(g) < specificity(candidate)
                   and relative_diff(g.value, candidate.value) <= policy.agreement.conflict_above]
        if all(in_line(candidate, g, policy) for g in general):
            break
    notes, flags = [], []
    if ignored:
        notes.append(f"{ignored} much smaller figure(s) with the same tier and date treated as other "
                     f"quantities, not restatements of the {candidate.value:,} total.")
    skipped = peers[:i]
    # A headcount out of line with an FTE figure is expected (part-time staff): note it, keep the FTE.
    other_basis = [s for s in skipped if s.basis != candidate.basis]
    same_basis = [s for s in skipped if s.basis == candidate.basis]
    notes.extend(f"{s.basis} figure {s.value:,} ({s.url}) is not in line with the {candidate.basis} figure "
                 f"{candidate.value:,}; the {candidate.basis} figure was kept." for s in other_basis)
    flags.extend(f"Detailed figure {s.value:,} ({s.url}) is not in line with the {candidate.qualifier} "
                 f"statement {candidate.value:,}; the statement was used. Review." for s in same_basis)
    if not skipped and general:
        notes.append(f"More specific figure {candidate.value:,} ({candidate.basis}) preferred over "
                     + ", ".join(f"{g.qualifier} {g.value:,} ({g.basis})" for g in general) + " for the same date.")
    return Pick(candidate, notes, flags, same_basis)


class Selection(NamedTuple):
    selected: Source | None       # source that sets the value; None when deriving or nothing found
    derive_from: list[Source]     # tier 7-9 sources to derive from when no tier 1-6 source applies
    notes: list[str]
    flags: list[str] = []
    inconsistent: list[Source] = []


def select_source(sources: list[Source], lookup_date: date, policy: Policy) -> Selection:
    """Pick the source that sets the certified value, applying the exception and recency rules."""
    notes: list[str] = []
    eligible = [s for s in sources if s.scope == "global"]
    for scope in ("partial", "broader"):
        n = sum(s.scope == scope for s in sources)
        if n:
            notes.append(f"{n} {scope}-scope source(s) used as supporting evidence only.")

    def of_class(*classes: str) -> list[Source]:
        return [s for s in eligible if policy.tier_class(s.tier) in classes]

    primaries = of_class("primary")
    secondaries = [s for s in of_class("secondary") if not is_stale(s, lookup_date, policy)]
    tertiaries = [s for s in of_class("tertiary", "unranked") if not is_stale(s, lookup_date, policy)]

    def chosen(pick: Pick) -> Selection:
        return Selection(pick.source, [], notes + pick.notes, pick.flags, pick.inconsistent)

    pick = best_of(primaries, policy)
    primary = pick.source
    if primary and is_stale(primary, lookup_date, policy):
        newer = [s for s in secondaries if s.as_of_date and s.as_of_date > primary.recency_date]
        if newer:
            override = best_of(newer, policy)
            notes.append(f"Tier {primary.tier} source is older than {policy.recency.stale_after_months} months; "
                         f"newer tier {override.source.tier} source overrides it.")
            return chosen(override)
        notes.append(f"Tier {primary.tier} source is older than {policy.recency.stale_after_months} months, "
                     "but no newer dated secondary source exists to override it.")
    if primary:
        return chosen(pick)
    if secondaries:
        return chosen(best_of(secondaries, policy))
    if tertiaries:
        notes.append("No tier 1-6 source found; value derived from tier 7-9 evidence.")
        return Selection(None, tertiaries, notes)
    return Selection(None, [], notes + ["No usable source found."])


# --- Range -------------------------------------------------------------------


def qualifier_range(value: int, qualifier: Qualifier, policy: Policy) -> tuple[int, int]:
    low, high = policy.range_bands[qualifier]
    return round(value * (1 + low)), round(value * (1 + high))


# --- LinkedIn ----------------------------------------------------------------


def implied_headcount(member_count: int, profile: str, policy: Policy) -> tuple[int, int]:
    lo_ratio, hi_ratio = policy.linkedin.profiles[profile].members_per_employee
    return math.floor(member_count / hi_ratio), math.ceil(member_count / lo_ratio)


def linkedin_check(value: int | None, evidence: LinkedInEvidence | None, policy: Policy) -> LinkedInCheck:
    evidence = evidence or LinkedInEvidence()
    profile = evidence.workforce_profile or policy.linkedin.default_profile
    size_agrees = (None if value is None or evidence.size_range is None
                   else evidence.size_range[0] <= value <= evidence.size_range[1])
    base = dict(member_count=evidence.member_count, size_range=evidence.size_range,
                workforce_profile=profile, size_range_agrees=size_agrees)
    if evidence.member_count is None:
        return LinkedInCheck(**base, implied_range=None, status="not_available",
                             note="No LinkedIn member count found.")
    implied = implied_headcount(evidence.member_count, profile, policy)
    if value is None:
        return LinkedInCheck(**base, implied_range=implied, status="not_available",
                             note="No certified value to check.")
    if value < evidence.member_count:
        status, note = "flag", f"Certified value {value:,} is below the LinkedIn member count {evidence.member_count:,}."
    elif not implied[0] <= value <= implied[1]:
        status, note = "flag", (f"Certified value {value:,} is outside the implied range "
                                f"{implied[0]:,}-{implied[1]:,} for a {profile} workforce.")
    else:
        status, note = "pass", f"Certified value is within the implied range {implied[0]:,}-{implied[1]:,}."
    return LinkedInCheck(**base, implied_range=implied, status=status, note=note)


# --- Growth adjustment -------------------------------------------------------


def round_significant(value: float, digits: int) -> int:
    if value <= 0:
        return 0
    return int(round(value, digits - 1 - int(math.floor(math.log10(value)))))


class GrowthEstimate(NamedTuple):
    value: int
    range: tuple[int, int]
    reason: str
    used_linkedin: bool


def growth_adjustment(source: Source, value: int, evidence: LinkedInEvidence | None, lookup_date: date,
                      policy: Policy, tertiary: list[Source] | None = None) -> GrowthEstimate | None:
    """Move an undated or old tier 2-6 figure toward a current signal showing the organization
    has grown past it (example: Gong). The signal is the LinkedIn member count with growth, or
    else a consensus of recent tier 7-9 figures. None when the rule doesn't apply."""
    rule = policy.growth_adjustment
    if source.tier not in rule.applies_to_tiers or source.basis == "fte":  # FTE is never estimated upward
        return None
    min_age = rule.min_age_months[policy.tier_class(source.tier)]
    if source.recency_date and within_months(source.recency_date, lookup_date, min_age):
        return None
    floor = value * (1 + rule.min_member_gap)
    age = "undated" if source.recency_date is None else f"as of {source.recency_date.isoformat()}"
    rounding = f"rounded to {rule.round_to_significant} significant digits"

    def estimate_toward(target: float) -> int:
        return round_significant(value + rule.weight_toward_members * (target - value), rule.round_to_significant)

    # Signal 1: LinkedIn member count with growth.
    if evidence is not None and evidence.member_count is not None:
        growth = evidence.growth_1y if evidence.growth_1y is not None else evidence.growth_2y
        members = evidence.member_count
        if growth is not None and growth >= rule.min_growth and members >= floor:
            estimate = estimate_toward(members)
            profile = evidence.workforce_profile or policy.linkedin.default_profile
            implied = implied_headcount(members, profile, policy)
            high = max(estimate, round_significant((implied[0] + implied[1]) / 2, rule.round_to_significant))
            reason = (f"Stated {value:,} ({age}) is outdated: LinkedIn shows {members:,} members and {growth:.0%} "
                      f"growth. Moved {rule.weight_toward_members:.0%} toward the member count and {rounding}; "
                      f"range runs from the stated figure to the {profile} implied midpoint.")
            return GrowthEstimate(estimate, (value, high), reason, used_linkedin=True)

    # Signal 2: a cluster of recent tier 7-9 figures (within the conflict threshold of their median)
    # that all exceed the stated value. A LinkedIn member count in the same cluster joins it.
    recent = sorted(t.value for t in tertiary or [] if t.scope == "global" and t.recency_date is not None
                    and within_months(t.recency_date, lookup_date, rule.tertiary_max_age_months))
    if len(recent) >= rule.min_tertiary_sources:
        median = recent[len(recent) // 2]
        cluster = [n for n in recent if relative_diff(n, median) <= policy.agreement.conflict_above]
        members = evidence.member_count if evidence is not None else None
        with_members = members is not None and relative_diff(members, median) <= policy.agreement.conflict_above
        if len(cluster) >= rule.min_tertiary_sources and min(cluster) >= floor:
            inputs = cluster + ([members] if with_members else [])
            mean = sum(inputs) / len(inputs)
            estimate = estimate_toward(mean)
            high = max(estimate, round_significant(max(inputs), rule.round_to_significant))
            members_text = f" and the LinkedIn member count ({members:,})" if with_members else ""
            reason = (f"Stated {value:,} ({age}) is outdated: {len(cluster)} recent data-provider figures "
                      f"({', '.join(f'{n:,}' for n in cluster)}){members_text} agree and exceed it. Moved "
                      f"{rule.weight_toward_members:.0%} toward their mean ({mean:,.0f}) and {rounding}; range "
                      f"runs from the stated figure to the highest of these figures.")
            return GrowthEstimate(estimate, (value, high), reason, used_linkedin=with_members)
    return None


# --- Tertiary derivation -----------------------------------------------------


class Derivation(NamedTuple):
    value: int
    count_type: str  # "calculated" or "estimated"
    range: tuple[int, int]
    inputs: list[tuple[str, int]]  # (label, value)


def derive_value(values: list[tuple[str, int]], policy: Policy) -> Derivation:
    """Combine tier 7-9 values and LinkedIn-implied values (selection step 4).

    Two or more inputs within the conflict threshold of each other are minimally
    sufficient (`calculated`); anything thinner is `estimated`.
    """
    nums = [v for _, v in values]
    mean = round(sum(nums) / len(nums))
    spread = (max(nums) - min(nums)) / mean if mean else 0.0
    count_type = "calculated" if len(nums) >= 2 and spread <= policy.agreement.conflict_above else "estimated"
    return Derivation(mean, count_type, (min(nums), max(nums)), values)


# --- Confidence --------------------------------------------------------------


def base_confidence(selected: Source | None, derivation: Derivation | None, corroborations: int,
                    lookup_date: date, policy: Policy) -> int:
    if selected is None:
        if derivation is None:
            return 0
        return 2 if derivation.count_type == "calculated" else 1
    cls = policy.tier_class(selected.tier)
    if cls == "primary":
        recent = (selected.as_of_date is not None and
                  within_months(selected.as_of_date, lookup_date, policy.recency.certified_max_age_months))
        if not recent:
            return 3
        return 5 if corroborations >= 1 else 4
    if selected.tier == 3:
        return 3
    return 3 if corroborations >= 1 else 2


def apply_flags(score: int, flag_count: int) -> int:
    """Each flag lowers confidence one level, never below 1 (and never raises 0)."""
    if score == 0:
        return 0
    return max(1, score - flag_count)
