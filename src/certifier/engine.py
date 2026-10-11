"""Turn research candidates into a certification record (SPEC.md: Selection and corroboration)."""

from __future__ import annotations

from datetime import date

from . import rules
from .models import Adjustment, Certification, Entity, LinkedInEvidence, Source
from .policy import Policy, default_policy


def certify(entity: Entity, sources: list[Source], linkedin: LinkedInEvidence | None = None,
            lookup_date: date | None = None, event_flags: list[str] | None = None,
            policy: Policy | None = None) -> Certification:
    policy = policy or default_policy()
    lookup_date = lookup_date or date.today()
    sources = [s.model_copy(deep=True) for s in sources]
    adjustments: list[Adjustment] = []
    flags: list[str] = [f"Event-driven: {f}" for f in event_flags or []]

    effective: dict[int, int] = {}
    for s in sources:
        effective[id(s)], log = rules.apply_counting_rules(s)
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

    if selected is not None:
        selected.role = "selected"
        value = effective[id(selected)]
        qualifier = selected.qualifier
        count_type = "reported" if value == selected.value else "calculated"
        value_range = rules.qualifier_range(value, qualifier, policy)
        policy_tier, as_of = selected.tier, selected.as_of_date
        growth = rules.growth_adjustment(selected, value, linkedin, lookup_date, policy)
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
        value, qualifier, count_type = derivation.value, "approximately", derivation.count_type
        value_range = derivation.range
        policy_tier = min(s.tier for s in selection.derive_from)
        as_of = max((s.as_of_date for s in selection.derive_from if s.as_of_date), default=None)
        adjustments.append(Adjustment(
            source_url="(derived)", source_figure=None, change=0, result=value,
            reason="Mean of " + "; ".join(f"{label} = {v:,}" for label, v in inputs)))
    else:
        value = qualifier = count_type = value_range = policy_tier = as_of = None

    # Corroboration and conflicts against the certified value.
    corroborations = 0
    if value is not None:
        for s in sources:
            if s.role is not None:
                continue
            diff = rules.relative_diff(effective[id(s)], value)
            if s.scope == "broader":
                s.role = "supporting"
                delta = effective[id(s)] - value
                adjustments.append(Adjustment(
                    source_url=s.url, source_figure=effective[id(s)], change=0, result=value,
                    reason=f"Notable: figure includes bodies outside the entity (e.g., a school system): "
                           f"{effective[id(s)]:,} vs. certified {value:,}, variance {delta:+,} ({delta / value:+.0%})."))
                continue
            if s.scope == "partial" or (selected is not None and s.url == selected.url):
                s.role = "supporting"
                continue
            if selected is not None and s.basis != selected.basis and diff > policy.agreement.corroborates_within:
                s.role = "supporting"  # FTE vs. headcount gaps are expected, not conflicts
                s.notes.append(f"{s.basis} basis differs from the certified {selected.basis} figure.")
                continue
            if diff <= policy.agreement.corroborates_within:
                s.role = "corroborates"
                corroborations += 1
            elif diff > policy.agreement.conflict_above:
                s.role = "conflicts"
                if policy.tier_class(s.tier) in ("primary", "secondary") and not rules.is_stale(s, lookup_date, policy):
                    flags.append(f"Conflict: tier {s.tier} source ({s.url}) reports {effective[id(s)]:,}, "
                                 f"{diff:.0%} from the certified value.")
            else:
                s.role = "supporting"

    li = rules.linkedin_check(value, linkedin, policy)
    linkedin_was_input = growth is not None or (derivation is not None and linkedin.member_count is not None)
    if li.status == "flag":
        if linkedin_was_input:
            notes.append(f"LinkedIn check not applied as a penalty because LinkedIn was an input: {li.note}")
        else:
            flags.append(f"LinkedIn: {li.note}")

    base = (policy.growth_adjustment.confidence if growth is not None
            else rules.base_confidence(selected, derivation, corroborations, lookup_date, policy))
    score = rules.apply_flags(base, len(flags))

    return Certification(
        entity=entity, certified_count=value, count_type=count_type, qualifier=qualifier,
        count_basis=None if value is None else (selected.basis if selected is not None else "headcount"),
        range=value_range, confidence_score=score, confidence_level=policy.confidence_levels[score],
        policy_tier=policy_tier, as_of_date=as_of, sources=sources, linkedin_check=li,
        adjustments=adjustments, flags=flags,
        rationale=_rationale(selected, derivation, value, corroborations, notes, flags, score, policy),
        policy_version=policy.policy_version,
    )


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
        parts.append(f"{corroborations} corroborating source(s) within "
                     f"{policy.agreement.corroborates_within:.0%}.")
    parts.extend(flags)
    parts.append(f"Confidence {score} ({policy.confidence_levels[score]}).")
    return " ".join(parts)
