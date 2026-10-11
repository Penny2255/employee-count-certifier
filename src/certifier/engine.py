"""Turn research candidates into a certification record (SPEC.md: Selection and corroboration)."""

from __future__ import annotations

from datetime import date

from . import rules
from .models import Adjustment, Certification, Entity, Event, EventOutcome, LinkedInEvidence, ScoreStep, Source
from .policy import Policy, default_policy


def certify(entity: Entity, sources: list[Source], linkedin: LinkedInEvidence | None = None,
            lookup_date: date | None = None, event_flags: list[str] | None = None,
            policy: Policy | None = None, review_flags: list[str] | None = None,
            events: list[Event] | None = None) -> Certification:
    """`event_flags` are pre-judged event flags that always lower confidence; `events` are dated
    events judged here against the selected source's as-of date."""
    policy = policy or default_policy()
    lookup_date = lookup_date or date.today()
    sources = [s.model_copy(deep=True) for s in sources]
    adjustments: list[Adjustment] = []
    flags: list[str] = [f"Event-driven: {f}" for f in event_flags or []]
    flags += [f"Complexity: {f}" for f in review_flags or []]  # scope issues needing human review

    effective: dict[int, int] = {}
    for s in sources:
        effective[id(s)], log = rules.apply_counting_rules(s)
        if s.tier == 1 and not rules.is_tier1_provenance(s, entity.website, policy):
            s.corroboration_only = True
            s.notes.append("Mirror of a tier 1 document (not sec.gov with an accession number, nor the "
                           "organization's own site): corroboration only.")
        if s.undated:
            s.notes.append("Undated source.")
        if rules.is_stale(s, lookup_date, policy):
            s.notes.append(f"Older than {policy.recency.stale_after_months} months.")
        if s.scope == "partial":
            s.notes.append("Partial or regional scope; supporting evidence only.")
        adjustments.extend(log)

    selection = rules.select_source(sources, lookup_date, policy)
    selected, derivation, growth = selection.selected, None, None
    notes = list(selection.notes)
    linkedin = linkedin or LinkedInEvidence()
    flags.extend(selection.flags)
    for s in selection.inconsistent:
        s.role = "conflicts"  # a detailed figure out of line with the headline never corroborates it
        s.role_reason = ("A more detailed figure not in line with the headline statement for the same date; "
                         "flagged for review.")

    if selected is not None:
        selected.role = "selected"
        selected.role_reason = (f"Highest-ranked eligible source: tier {selected.tier}, "
                                + (f"as of {selected.as_of_date.isoformat()}" if selected.as_of_date else "undated")
                                + ("; the most specific figure in line with the rounder statements."
                                   if any("More specific figure" in n for n in selection.notes) else "."))
        value = effective[id(selected)]
        qualifier = selected.qualifier
        count_type = "reported" if value == selected.value else "calculated"
        value_range = rules.qualifier_range(value, qualifier, policy)
        policy_tier, as_of = selected.tier, selected.as_of_date
        tertiary = [s for s in sources if policy.tier_class(s.tier) in ("tertiary", "unranked")]
        growth = rules.growth_adjustment(selected, value, linkedin, lookup_date, policy, tertiary=tertiary)
        if growth is not None:
            adjustments.append(Adjustment(source_url=selected.url, source_figure=value,
                                          change=growth.value - value, reason=growth.reason, result=growth.value))
            notes.append(f"Growth-adjusted from {value:,} to {growth.value:,}.")
            value, qualifier, count_type, value_range = growth.value, "approximately", "estimated", growth.range
    elif selection.derive_from:
        inputs = [(f"tier {s.tier}: {s.url}", effective[id(s)]) for s in selection.derive_from]
        if linkedin.member_count:
            profile = linkedin.workforce_profile or policy.linkedin.default_profile
            lo, hi = rules.implied_headcount(linkedin.member_count, profile, policy)
            inputs.append((f"LinkedIn member count implied ({profile})", round((lo + hi) / 2)))
        if linkedin.size_range:
            inputs.append(("LinkedIn size range midpoint", round(sum(linkedin.size_range) / 2)))
        derivation = rules.derive_value(inputs, policy)
        for s in selection.derive_from:
            s.role = "derived_input"
            s.role_reason = "No tier 1-6 source exists, so this tier 7-9 figure is an input to the derived value."
        value, qualifier, count_type = derivation.value, "approximately", derivation.count_type
        value_range = derivation.range
        policy_tier = min(s.tier for s in selection.derive_from)
        as_of = max((s.as_of_date for s in selection.derive_from if s.as_of_date), default=None)
        adjustments.append(Adjustment(
            source_url="(derived)", source_figure=None, change=0, result=value,
            reason="Mean of " + "; ".join(f"{label} = {v:,}" for label, v in inputs)))
    else:
        value = qualifier = count_type = value_range = policy_tier = as_of = None

    # Events lower confidence only when they closed after the as-of date (the figure can't include them).
    event_outcomes: list[EventOutcome] = []
    for e in events or []:
        where = f" ({e.url})" if e.url else ""
        if e.close_date is not None and as_of is not None and e.close_date > as_of:
            reason = (f"Closed {e.close_date.isoformat()}, after the {as_of.isoformat()} as-of date, so the "
                      "certified figure cannot include it; confidence lowered one level.")
            flags.append(f"Event-driven: {e.description}, closed {e.close_date.isoformat()}, after the "
                         f"{as_of.isoformat()} as-of date{where}")
            event_outcomes.append(EventOutcome(description=e.description, url=e.url, close_date=e.close_date,
                                               penalized=True, reason=reason))
        else:
            when = (f"closed {e.close_date.isoformat()}, on or before the as-of date" if e.close_date and as_of
                    else "close date or as-of date unknown")
            notes.append(f"Event noted, not penalized ({when}): {e.description}{where}.")
            reason = (f"Closed {e.close_date.isoformat()}, on or before the {as_of.isoformat()} as-of date, so the "
                      "figure already reflects it; noted, not penalized." if e.close_date and as_of else
                      "The close date or the as-of date is unknown, so it cannot be shown to postdate the figure; "
                      "noted, not penalized.")
            event_outcomes.append(EventOutcome(description=e.description, url=e.url, close_date=e.close_date,
                                               penalized=False, reason=reason))

    # Corroboration: independent sources near the same as-of date that agree within the threshold.
    corroborators: list[Source] = []
    if value is not None:
        for s in sources:
            if s.role is not None:
                continue
            diff = rules.relative_diff(effective[id(s)], value)
            if s.scope == "broader":
                s.role = "supporting"
                delta = effective[id(s)] - value
                s.role_reason = (f"Covers bodies outside the entity (variance {delta:+,} vs. the certified value); "
                                 "logged as notable, never used as the value.")
                adjustments.append(Adjustment(
                    source_url=s.url, source_figure=effective[id(s)], change=0, result=value,
                    reason=f"Notable: figure includes bodies outside the entity (e.g., a school system): "
                           f"{effective[id(s)]:,} vs. certified {value:,}, variance {delta:+,} ({delta / value:+.0%})."))
                continue
            if s.scope == "partial":
                s.role = "supporting"
                s.role_reason = "Covers only part of the organization (a region, segment or subsidiary); context only."
                continue
            if selected is not None and s.basis != selected.basis and diff > policy.agreement.corroborates_within:
                s.role = "supporting"  # FTE vs. headcount gaps are expected, not conflicts
                s.notes.append(f"{s.basis} basis differs from the certified {selected.basis} figure.")
                s.role_reason = (f"Counts {s.basis} while the certified figure counts {selected.basis}, so a gap is "
                                 "expected; context only.")
                continue
            dep = (rules.independence(s, selected, effective[id(s)], effective[id(selected)], lookup_date, policy)
                   if selected is not None else None)
            if dep is not None:
                s.notes.append(f"Not counted as corroboration: {dep.reason}.")
                # Undated sources can't corroborate but can still conflict; other periods and
                # restatements of the same evidence do neither.
                if dep.kind != "undated" or diff <= policy.agreement.conflict_above:
                    s.role = "supporting"
                    s.role_reason = f"Not counted as corroboration: {dep.reason}."
                    continue
            if diff <= policy.agreement.corroborates_within:
                s.role = "corroborates"
                s.role_reason = (f"Independent source near the same date, within {_pct(diff)} of the certified value "
                                 f"(threshold {policy.agreement.corroborates_within:.0%}).")
                corroborators.append(s)
            elif diff > policy.agreement.conflict_above:
                s.role = "conflicts"
                if policy.tier_class(s.tier) in ("primary", "secondary") and not rules.is_stale(s, lookup_date, policy):
                    flags.append(f"Conflict: tier {s.tier} source ({s.url}) reports {effective[id(s)]:,}, "
                                 f"{diff:.0%} from the certified value.")
                    s.role_reason = f"Disagrees with the certified value by {diff:.0%}; flagged as a conflict."
                else:
                    s.role_reason = (f"Disagrees by {diff:.0%}, but a tier {s.tier} or stale source never lowers "
                                     "confidence; recorded only.")
            else:
                s.role = "supporting"
                s.role_reason = (f"Within {diff:.0%} of the certified value: closer than a conflict, not close enough "
                                 "to corroborate; context only.")

    li = rules.linkedin_check(value, linkedin, policy)
    linkedin_was_input = ((growth is not None and growth.used_linkedin)
                          or (derivation is not None and linkedin.member_count is not None))
    if li.status == "flag":
        if linkedin_was_input:
            notes.append(f"LinkedIn check not applied as a penalty because LinkedIn was an input. {li.note}")
        else:
            flags.append(f"LinkedIn: {li.note}")

    if growth is not None:
        steps = [ScoreStep(points=policy.growth_adjustment.confidence,
                                 reason=f"base {policy.growth_adjustment.confidence}: growth-adjusted estimate "
                                        f"from a tier {selected.tier} figure and a current signal")]
    else:
        steps = rules.confidence_steps(selected, derivation, corroborators, lookup_date, policy)
    steps += rules.flag_steps(sum(st.points for st in steps), flags)
    score = sum(st.points for st in steps)

    return Certification(
        entity=entity, certified_count=value, count_type=count_type, qualifier=qualifier,
        count_basis=None if value is None else (selected.basis if selected is not None else "headcount"),
        range=value_range, confidence_score=score, confidence_level=policy.confidence_levels[score],
        confidence_breakdown=steps, policy_tier=policy_tier, as_of_date=as_of,
        sources=_explain_unassigned(sources, value), linkedin_check=li, adjustments=adjustments, flags=flags,
        events=event_outcomes,
        rationale=_rationale(selected, derivation, value, len(corroborators), notes, flags, score, policy),
        trend=rules.trend_points(selected, sources, effective) if selected is not None and growth is None else [],
        policy_version=policy.policy_version,
    )


def _pct(x: float) -> str:
    """Percent with a decimal below 1% (0.4%, not 0%)."""
    return f"{x:.1%}" if x < 0.01 else f"{x:.0%}"


def _explain_unassigned(sources: list[Source], value: int | None) -> list[Source]:
    """Every source carries a reason, including ones nothing was compared against."""
    for s in sources:
        if s.role is None:
            s.role = "supporting"
            s.role_reason = ("No certified value was produced, so nothing was compared." if value is None else
                             "Not eligible to set the value (stale or a mirror) and not compared further.")
        if s.corroboration_only and "mirror" not in s.role_reason.lower():
            s.role_reason += " Hosted outside sec.gov and the organization's own site: a mirror, never the value."
    return sources


def _rationale(selected: Source | None, derivation: rules.Derivation | None, value: int | None,
               corroborations: int, notes: list[str], flags: list[str], score: int, policy: Policy) -> str:
    parts: list[str] = []
    if selected is not None:
        dated = f"as of {selected.as_of_date.isoformat()}" if selected.as_of_date else "undated"
        parts.append(f"Highest-ranked available source is tier {selected.tier} "
                     f"({policy.tiers[selected.tier].name}), {dated}, reporting {selected.value:,}"
                     + (" full-time equivalents, kept as stated." if selected.basis == "fte" else "."))
    elif derivation is not None:
        parts.append(f"Value {value:,} is {derivation.count_type} from {len(derivation.inputs)} tier 7-9 "
                     "and LinkedIn inputs.")
    parts.extend(notes)
    if value is not None:
        parts.append(f"{corroborations} independent corroborating source(s) within "
                     f"{policy.agreement.corroborates_within:.0%}.")
    parts.extend(flags)
    parts.append(f"Confidence {score} ({policy.confidence_levels[score]}).")
    return " ".join(parts)
