# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Deterministic policy rules from SPEC.md. Pure functions, no I/O."""

from __future__ import annotations

import calendar
import math
import re
from datetime import date, timedelta
from typing import NamedTuple
from urllib.parse import urlsplit

from .models import Adjustment, LinkedInCheck, LinkedInEvidence, Qualifier, ScoreStep, Source, TrendPoint
from .policy import Policy

# --- Recency -----------------------------------------------------------------


def within_months(d: date, lookup_date: date, months: int) -> bool:
    """True if `d` is no more than `months` calendar months before `lookup_date`."""
    total = lookup_date.year * 12 + lookup_date.month - 1 - months
    year, month = divmod(total, 12)
    day = min(lookup_date.day, calendar.monthrange(year, month + 1)[1])
    return d >= date(year, month + 1, day)


def next_release_due(source: Source, policy: Policy) -> date | None:
    """When the next release of a lagging official source (e.g. IPEDS) is expected, if it is one."""
    lag = policy.recency.latest_release_current.get(source.document_type or "")
    if lag is None or source.as_of_date is None:
        return None
    return source.as_of_date + timedelta(days=lag)


def latest_release_current(source: Source, lookup_date: date, policy: Policy) -> bool:
    """The latest available release of a lagging official source counts as current until the next is due."""
    due = next_release_due(source, policy)
    return due is not None and lookup_date <= due + timedelta(days=policy.recency.latest_release_grace_days)


def is_stale(source: Source, lookup_date: date, policy: Policy) -> bool:
    """Dated (as-of, else published) and older than the stale window. Undated is never stale, and neither
    is the latest release of a lagging official source."""
    ref = source.recency_date
    return (ref is not None and not within_months(ref, lookup_date, policy.recency.stale_after_months)
            and not latest_release_current(source, lookup_date, policy))


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
    eligible = [s for s in sources if s.scope == "global" and not s.corroboration_only]
    mirrors = sum(s.corroboration_only for s in sources)
    if mirrors:
        notes.append(f"{mirrors} mirror(s) of tier 1 documents used as corroboration only.")
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


def _round_step(value: float) -> int:
    return 10 if value < 2_000 else 25 if value < 20_000 else 100 if value < 500_000 else 1_000


def confidence_range(value: int, score: int, qualifier: Qualifier | None, direction: str | None, floor: int | None,
                     policy: Policy) -> tuple[int, int]:
    """The one range we give: centred on the certified number and as wide as the confidence warrants. "More than"
    extends only upward, "up to" only downward; the likely direction widens its side by half; a supported floor
    keeps the low end up. Bounds are rounded outward to a step that suits the size (10s, 25s, 100s, 1,000s)."""
    w = policy.range_width_by_score.get(score, 0.5)
    lo_w, hi_w = w, w
    if qualifier == "more_than":
        lo_w, hi_w = 0.0, 2 * w
    elif qualifier == "up_to":
        lo_w, hi_w = 2 * w, 0.0
    if direction == "lower":
        lo_w *= 1.5
    elif direction == "higher":
        hi_w *= 1.5
    step = _round_step(value)
    lo = math.floor(value * (1 - lo_w) / step) * step if lo_w else value
    hi = math.ceil(value * (1 + hi_w) / step) * step if hi_w else value
    if floor is not None and floor < value:  # a supported floor: the range sits symmetrically between it and our number
        lo = floor
        hi = min(hi, math.ceil((value + (value - floor)) / step) * step)
    return max(0, min(lo, value)), max(hi, value)


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
                workforce_profile=profile, size_range_agrees=size_agrees,
                growth_1y=evidence.growth_1y, growth_2y=evidence.growth_2y, open_roles=evidence.open_roles)
    if evidence.member_count is None:
        return LinkedInCheck(**base, implied_range=None, status="not_available",
                             note="No LinkedIn member count found.")
    members = evidence.member_count
    implied = implied_headcount(members, profile, policy)
    if value is None:
        return LinkedInCheck(**base, implied_range=implied, status="not_available",
                             note="No certified value to check.")
    # The member count is a flag, not a floor: members may exceed the count by the profile's
    # tolerance (lingering profiles of former employees and contractors).
    tolerance = policy.linkedin.member_overage_tolerance.get(profile, 0.0)
    low = math.ceil(members / (1 + tolerance)) if tolerance > 0 else implied[0]
    pass_range = (min(low, implied[0]), implied[1])
    over = members / value - 1 if value else math.inf
    gap = over if value < members else (value / pass_range[1] - 1 if value > pass_range[1] else 0.0)
    if pass_range[0] <= value <= pass_range[1]:
        status = "pass"
        note = (f"Pass: LinkedIn shows {members:,} members, {over:.0%} above the certified {value:,}, within the "
                f"{tolerance:.0%} tolerance for a {profile.replace('_', '-')} workforce." if value < members else
                f"Pass: certified {value:,} is within the range {pass_range[0]:,}-{pass_range[1]:,} implied by "
                f"{members:,} LinkedIn members for a {profile.replace('_', '-')} workforce.")
    elif value < members:
        status = "flag"
        note = (f"Flag: LinkedIn shows {members:,} members, {over:.0%} above the certified {value:,}; more than "
                f"the {tolerance:.0%} tolerance for a {profile.replace('_', '-')} workforce.")
    else:
        status = "flag"
        side = "below" if value < pass_range[0] else "above"
        note = (f"Flag: certified {value:,} is {side} the range {pass_range[0]:,}-{pass_range[1]:,} implied by "
                f"{members:,} LinkedIn members for a {profile.replace('_', '-')} workforce.")
    return LinkedInCheck(**base, implied_range=pass_range, status=status, note=note, gap=round(gap, 3))


def growth_signal(evidence: LinkedInEvidence | None, policy: Policy) -> str | None:
    """Why a white-collar organization is clearly growing (LinkedIn growth or open roles), or None."""
    if evidence is None or not evidence.member_count:
        return None
    if (evidence.workforce_profile or policy.linkedin.default_profile) != "white_collar":
        return None
    lp = policy.linkedin
    if evidence.growth_1y is not None and evidence.growth_1y >= lp.growth_signal_1y:
        return f"LinkedIn shows {evidence.growth_1y:+.0%} headcount growth over a year"
    if evidence.growth_2y is not None and evidence.growth_2y >= lp.growth_signal_2y:
        return f"LinkedIn shows {evidence.growth_2y:+.0%} headcount growth over two years"
    if evidence.open_roles and evidence.open_roles >= lp.growth_signal_open_roles * evidence.member_count:
        return f"{evidence.open_roles:,} open roles, {evidence.open_roles / evidence.member_count:.0%} of LinkedIn members"
    return None


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
    if latest_release_current(source, lookup_date, policy):  # the latest official release is current: no lag to correct
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


def source_label(source: Source) -> str:
    """Short human label: host plus a snippet of the quote."""
    host = (urlsplit(source.url).hostname or source.url).removeprefix("www.")
    quote = " ".join(source.excerpt.split())[:60]
    return f"{host} '{quote}'" if quote else host


def confidence_steps(selected: Source | None, derivation: Derivation | None, corroborators: list[Source],
                     lookup_date: date, policy: Policy) -> list[ScoreStep]:
    """The base score and the corroboration bonus, each with its reason (SPEC.md confidence table)."""
    if selected is None:
        if derivation is None:
            return [ScoreStep(points=0, reason="base 0: no usable source")]
        if derivation.count_type == "calculated":
            return [ScoreStep(points=2, reason="base 2: calculated from agreeing tier 7-9 inputs")]
        return [ScoreStep(points=1, reason="base 1: estimated from a single or disagreeing tier 7-9 input")]
    months = policy.recency.certified_max_age_months
    cls = policy.tier_class(selected.tier)
    as_of = selected.as_of_date
    est = " (estimated)" if selected.as_of_estimated else ""
    recent = as_of is not None and (within_months(as_of, lookup_date, months)
                                    or latest_release_current(selected, lookup_date, policy))

    if cls == "primary":
        steps = [ScoreStep(points=4, reason=f"base 4: tier {selected.tier} primary source")]
    elif selected.tier == 3:
        steps = [ScoreStep(points=3, reason="base 3: tier 3 company-published document")]
    else:
        steps = [ScoreStep(points=2, reason=f"base 2: tier {selected.tier} secondary source")]

    # Recency: one level off whenever the anchor is older than the window, estimated dates included.
    if as_of is None and cls == "primary":
        steps.append(ScoreStep(points=-1, reason=f"recency: tier {selected.tier} source has no as-of date"))
    elif as_of is not None and not recent:
        steps.append(ScoreStep(points=-1, reason=f"recency: as of {as_of.isoformat()}{est} is older than "
                                                 f"{months} months"))

    # Corroboration bonus (confidence table): tier 1-2 only when recent; never for tier 3; tier 4-6 yes.
    if corroborators and as_of is not None and (selected.tier >= 4 or (cls == "primary" and recent)):
        steps.append(ScoreStep(points=1, reason="corroborated by " + "; ".join(source_label(s) for s in corroborators)))
    return steps


def indicated_range(selected: Source | None, value: int | None, sources: list[Source], lookup_date: date,
                    policy: Policy) -> "IndicatedRange | None":
    """Newer tier 7-9 figures that diverge from an old certified figure (shown, never applied)."""
    from .models import IndicatedRange
    rule = policy.indicated_range
    if selected is None or value is None or selected.as_of_date is None:
        return None
    if within_months(selected.as_of_date, lookup_date, rule.min_anchor_age_months):
        return None
    newer_floor = _add_months(selected.as_of_date, rule.min_newer_by_months)
    newer = [s for s in sources if policy.tier_class(s.tier) in ("tertiary", "unranked") and s.scope == "global"
             and s.as_of_date is not None and s.as_of_date >= newer_floor
             and within_months(s.as_of_date, lookup_date, rule.max_source_age_months)]
    if not newer:
        return None
    # Outliers (beyond the conflict threshold from the median) are left out, as for the growth signal.
    ordered = sorted(s.value for s in newer)
    median = ordered[len(ordered) // 2]
    kept = [s for s in newer if relative_diff(s.value, median) <= policy.agreement.conflict_above]
    dropped = len(newer) - len(kept)
    newer = kept
    vals = [s.value for s in newer]
    mean = sum(vals) / len(vals)
    if relative_diff(round(mean), value) < rule.min_divergence:
        return None
    dates = sorted(s.as_of_date for s in newer)
    return IndicatedRange(
        low=min(vals), high=max(vals), earliest=dates[0], latest=dates[-1], urls=[s.url for s in newer],
        reason=(f"{len(newer)} newer data-provider figure(s) dated {dates[0].isoformat()} to {dates[-1].isoformat()} "
                f"put headcount at {min(vals):,}-{max(vals):,}, {relative_diff(round(mean), value):.0%} from the "
                f"certified figure as of {selected.as_of_date.isoformat()}"
                + (f" ({dropped} outlier(s) left out)" if dropped else "")
                + ". Shown for context; policy does not let tier 7-9 data replace it."))


def _add_months(d: date, months: int) -> date:
    total = d.year * 12 + d.month - 1 + months
    year, month = divmod(total, 12)
    return date(year, month + 1, min(d.day, calendar.monthrange(year, month + 1)[1]))


def flag_steps(score: int, flags: list[str]) -> list[ScoreStep]:
    """Each flag lowers confidence one level, never below 1 (and never raises 0)."""
    if score == 0:
        return []
    steps = []
    for flag in flags:
        if score > 1:
            steps.append(ScoreStep(points=-1, reason=flag))
            score -= 1
        else:
            steps.append(ScoreStep(points=0, reason=f"{flag} (no change: minimum of 1 reached)"))
    return steps or [ScoreStep(points=0, reason="no deductions")]


def is_tier1_provenance(source: Source, entity_website: str | None, policy: Policy) -> bool:
    """Tier 1 needs the filing itself: sec.gov with an accession number in the URL, or the
    organization's own website. Copies on other sites are mirrors."""
    host = (urlsplit(source.url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in policy.provenance.sec_hosts):
        return bool(_ACCESSION.search(source.url))
    own = _site(urlsplit(entity_website if entity_website and "://" in entity_website
                         else f"https://{entity_website or ''}").hostname or "")
    return bool(own) and _site(host) == own


_ACCESSION = re.compile(r"/(\d{18}|\d{10}-\d{2}-\d{6})(?:/|$|[?#])")


def _site(host: str) -> str:
    """Registrable domain: last two labels, or three for country second-levels (example.co.uk)."""
    labels = host.lower().removeprefix("www.").split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"co", "com", "gov", "ac", "org", "net", "edu"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else ""


def same_document(a: Source, b: Source) -> bool:
    return a.url.split("#")[0] == b.url.split("#")[0]


class Dependence(NamedTuple):
    kind: str  # "dependent" (same evidence), "undated", or "far" (a different point in time)
    reason: str


def independence(candidate: Source, selected: Source, candidate_value: int, selected_value: int,
                 lookup_date: date, policy: Policy) -> Dependence | None:
    """Why `candidate` can't corroborate `selected`, or None if it is independent evidence near
    the same as-of date. An undated selected source (e.g. a website tile) is presumed current."""
    if same_document(candidate, selected):
        return Dependence("dependent", "same document")
    if candidate.restates:
        return Dependence("dependent", "restates another source's figure")
    if candidate_value == selected_value and candidate.as_of_date in (None, selected.as_of_date):
        return Dependence("dependent", "repeats the same figure (restatement)")
    ref, sel_ref = candidate.recency_date, selected.as_of_date
    if sel_ref is None:
        return Dependence("undated_anchor", "the certified figure has no as-of date, so nearness can't be "
                                            "established")
    if ref is None:
        return Dependence("undated", "undated, so not near the certified figure's as-of date")
    window = policy.agreement.corroboration_window_months
    if not (within_months(ref, sel_ref, window) and within_months(sel_ref, ref, window)):
        return Dependence("far", f"dated more than {window} months from the certified figure's as-of date")
    return None


# A prior year more than 5x away from the certified figure is a misread (a note number, a ratio, an empty
# table cell), not a trend: real workforces rarely move that far in five years.
TREND_PLAUSIBLE = 5


def trend_points(selected: Source, sources: list[Source], effective: dict[int, int], limit: int = 5) -> list[TrendPoint]:
    """Same-tier, same-basis dated figures (e.g. consecutive 10-Ks), oldest to newest, ending at
    the selected figure. Each date's figure is chosen as the headline is (the largest restated total,
    then the most specific), and implausible figures are left out."""
    if selected.as_of_date is None:
        return []
    candidates: dict[date, list[Source]] = {}
    for s in sources:
        if (s.tier == selected.tier and s.basis == selected.basis and s.scope == "global"
                and not s.corroboration_only and s.as_of_date and s.as_of_date <= selected.as_of_date
                and s.value > 0 and 1 / TREND_PLAUSIBLE <= s.value / selected.value <= TREND_PLAUSIBLE):
            candidates.setdefault(s.as_of_date, []).append(s)
    by_date: dict[date, Source] = {}
    for d, group in candidates.items():
        by_date[d] = selected if selected in group else _cluster_pick(group)
    by_date[selected.as_of_date] = selected
    points = [TrendPoint(as_of_date=d, value=effective[id(s)], tier=s.tier, url=s.url) for d, s in sorted(by_date.items())]
    return points[-limit:]


def _cluster_pick(group: list[Source]) -> Source:
    """The most specific figure among those near the largest (a total, not one of its parts)."""
    largest = max(s.value for s in group)
    near = [s for s in group if relative_diff(s.value, largest) <= 0.25]
    return max(near, key=specificity)
