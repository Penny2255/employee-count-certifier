# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Turn research candidates into a certification record (SPEC.md: Selection and corroboration)."""

from __future__ import annotations

from datetime import date

from . import rules
import re

from .models import (Adjustment, Certification, Direction, Entity, Event, EventOutcome, LinkedInEvidence, ScoreStep,
                     Source)

_URL_DATE = re.compile(r"/((?:19|20)\d{2})/(0[1-9]|1[0-2])(?:/(0[1-9]|[12]\d|3[01]))?(?=/|$|[?#])")
from .policy import Policy, default_policy


def certify(entity: Entity, sources: list[Source], linkedin: LinkedInEvidence | None = None,
            lookup_date: date | None = None, event_flags: list[str] | None = None,
            policy: Policy | None = None, review_flags: list[str] | None = None,
            events: list[Event] | None = None, scope_notes: list[str] | None = None,
            subsidiary_questions: list[str] | None = None) -> Certification:
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
        # A Corporate Fact Sheet is primary (tier 2); with no date at all it drops to tier 3.
        if s.document_type == "fact_sheet":
            dated = s.as_of_date is not None or s.latest_published is not None
            tier = policy.fact_sheet.tier if dated else policy.fact_sheet.undated_tier
            if not dated:
                s.notes.append(f"Corporate fact sheet with no date: ranked tier {tier} instead of "
                               f"{policy.fact_sheet.tier}, because its age can't be judged.")
            s.tier = tier
        # An undated figure gets an as-of date estimated from its publication date (research may
        # already have estimated one from wording such as "as of early 2025").
        if s.as_of_date is None and s.latest_published is not None:
            s.as_of_date, s.as_of_estimated = s.latest_published, True
            s.as_of_basis = s.as_of_basis or f"publication date {s.latest_published.isoformat()}"
        # Lowest priority: a date in the URL path (e.g. /2023/03/), for undated sources only.
        if s.as_of_date is None:
            m = _URL_DATE.search(s.url)
            if m:
                s.as_of_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
                s.as_of_estimated, s.as_of_from_url = True, True
                s.as_of_basis = f"the date in the URL ({m.group(0)}), not the reported text"
        # A source can't report a headcount as of a date after it was published (or after today).
        latest_possible = min(d for d in (s.latest_published, lookup_date) if d is not None)
        if s.as_of_estimated and s.as_of_date is not None and s.as_of_date > latest_possible:
            s.notes.append(f"Estimated as-of {s.as_of_date.isoformat()} is after the source's publication date; "
                           f"capped at {latest_possible.isoformat()}.")
            s.as_of_date = latest_possible
        if s.as_of_estimated:
            s.notes.append(f"As-of date estimated from {s.as_of_basis or 'context'}.")
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

    _restore_annual_series(sources, policy)
    selection = rules.select_source(sources, lookup_date, policy)
    selected, derivation, growth = selection.selected, None, None
    notes = list(selection.notes)
    linkedin = linkedin or LinkedInEvidence()
    flags.extend(selection.flags)
    # A consolidated annual filing (tier 1) counts every subsidiary owned at its as-of date, so a question
    # about whether a subsidiary is included can't change the entity counted: a note, not a flag.
    scope_notes = list(scope_notes or [])
    if selected is not None and selected.tier == 1:
        scope_notes += [f"{q} (The consolidated annual filing includes subsidiaries owned at its as-of date.)"
                        for q in subsidiary_questions or []]
    else:
        flags += [f"Complexity: {q}" for q in subsidiary_questions or []]
    # One root cause, one penalty: an open entity scope question (e.g. an affiliated health system) explains
    # a LinkedIn figure above the certified count, so that gap is linked to it instead of penalized again.
    scope_flags = [f for f in flags if f.startswith("Complexity:")]
    explained: list[tuple[str, str]] = []
    if selected is not None and selected.document_type in policy.recency.latest_release_current \
            and rules.latest_release_current(selected, lookup_date, policy):
        due = rules.next_release_due(selected, policy)
        selected.notes.append(f"Latest release: as of {selected.as_of_date.isoformat()}; treated as current for "
                              f"recency until the next release is due (around {due.strftime('%B %Y')}).")
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
        # LinkedIn's size band is often stale (Anthropic: "501-1K" beside 5,756 members): it counts only when there's
        # no member count, or when the member count actually falls inside it.
        band = linkedin.size_range
        if band and (not linkedin.member_count or band[0] <= linkedin.member_count <= band[1] * 1.5):
            inputs.append(("LinkedIn size range midpoint", round(sum(band) / 2)))
        elif band:
            notes.append(f"LinkedIn's size band ({band[0]:,}-{band[1]:,}) is left out: its {linkedin.member_count:,} "
                         "members put it well above that band, so the band is out of date.")
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

    # A fast-growing white-collar organization: LinkedIn members are mostly real (if a little inflated), so a weak
    # estimate below 75% of members moves to the middle of that floor and the member count. Only for an estimate
    # from data providers or a tier 4-6 anchor: a filing or company-published document (tiers 1-3) stands.
    signal = rules.growth_signal(linkedin, policy)
    history_growth = None
    if value is not None and as_of is not None and linkedin.growth_1y is None and linkedin.growth_2y is None:
        older = [s for s in sources if s.as_of_date and s.scope == "global" and s.value > 0 and not s.corroboration_only
                 and 270 < (as_of - s.as_of_date).days <= 365.25 * 4 and 0.1 <= s.value / value <= 5]
        if older:
            first = min(older, key=lambda s: s.as_of_date)
            years = (as_of - first.as_of_date).days / 365.25
            history_growth = (value / first.value) ** (1 / years) - 1
            if not signal and (linkedin.workforce_profile or policy.linkedin.default_profile) == "white_collar" \
                    and linkedin.member_count and history_growth >= policy.linkedin.growth_signal_1y:
                signal = (f"its dated sources show about {history_growth:+.0%} a year since {first.as_of_date.year} "
                          f"({first.value:,} then)")
    current_primary = (selected is not None and policy.tier_class(selected.tier) == "primary" and as_of is not None
                       and (rules.within_months(as_of, lookup_date, policy.recency.certified_max_age_months)
                            or rules.latest_release_current(selected, lookup_date, policy)))
    linkedin_floor_used = False
    supported_floor = None
    weak_anchor = selected is None or selected.tier >= 4  # data providers, website, LinkedIn description, news
    if signal and value is not None and not current_primary and weak_anchor:
        members, lp = linkedin.member_count, policy.linkedin
        # Very strong, sustained growth leans further forward: a higher floor, an estimate near the member count,
        # and a tighter range (LinkedIn lags hiring at this pace, so the total is less inflated than usual).
        strong = ((linkedin.growth_1y is not None and linkedin.growth_1y >= lp.growth_strong_1y)
                  or (history_growth is not None and history_growth >= lp.growth_strong_1y))
        share = lp.growth_strong_floor_share if strong else lp.growth_floor_share
        floor = round(members * share)
        target = (rules.round_significant(members * lp.growth_strong_point_share, 3) if strong
                  else rules.round_significant((floor + members) / 2, 3))
        if value < target if strong else value < floor:
            high = round(members * lp.growth_strong_high_share) if strong else max(members, value_range[1] if value_range else members)
            adjustments.append(Adjustment(
                source_url="(LinkedIn growth floor)", source_figure=value, change=target - value, result=target,
                reason=f"{signal}, so at least {share:.0%} of its {members:,} LinkedIn members are taken to be current "
                       f"employees (a floor of {floor:,}); " + (
                           f"growth this strong is real hiring, so the estimate leans to {lp.growth_strong_point_share:.0%} "
                           f"of members ({floor:,}-{high:,})." if strong else
                           f"moved to the middle of {floor:,}-{members:,}.")))
            notes.append(f"LinkedIn growth floor: {value:,} moved to {target:,} ({signal}).")
            value, qualifier, count_type = target, "approximately", "estimated"
            value_range = (floor, high)
            linkedin_floor_used = True
            supported_floor = floor

    # Events lower confidence only when they closed after the as-of date (the figure can't include them).
    event_outcomes: list[EventOutcome] = []
    primary_anchor = selected is not None and policy.tier_class(selected.tier) == "primary"
    for e in events or []:
        where = f" ({e.url})" if e.url else ""
        if e.headcount_change is not None and value:  # a stated change is judged against the certified value
            e = e.model_copy(update={"material": abs(e.headcount_change) / value > policy.agreement.corroborates_within})
        after = e.close_date is not None and as_of is not None and e.close_date > as_of
        if after and primary_anchor:
            # A tier 1-2 figure stands as reported: no relabel, no score change; an awareness note only.
            effect = "" if e.headcount_change is None else f" (stated change {e.headcount_change:+,})"
            event_outcomes.append(EventOutcome(
                description=e.description, url=e.url, close_date=e.close_date, penalized=False, after_as_of=True,
                headcount_change=e.headcount_change,
                reason=(f"Took effect {e.close_date.isoformat()}, after the {as_of.isoformat()} as-of date{effect}. "
                        f"The tier {selected.tier} figure stands as reported; this is noted for awareness and in the "
                        "directional guidance.")))
            continue
        if after:
            effect = "" if e.headcount_change is None else f" (stated change {e.headcount_change:+,})"
            if e.material:
                reason = (f"Took effect {e.close_date.isoformat()}, after the {as_of.isoformat()} as-of date, so the "
                          f"certified figure cannot include it{effect}; the figure is labelled pre-adjustment and "
                          "confidence is lowered one level.")
                flags.append(f"Event-driven: {e.description}, {e.close_date.isoformat()}, after the "
                             f"{as_of.isoformat()} as-of date{where}")
            else:
                reason = (f"Took effect {e.close_date.isoformat()}, after the {as_of.isoformat()} as-of date{effect}; "
                          "the figure is labelled pre-adjustment. The change is small, so confidence is unchanged.")
            event_outcomes.append(EventOutcome(description=e.description, url=e.url, close_date=e.close_date,
                                               penalized=e.material, after_as_of=True,
                                               headcount_change=e.headcount_change, reason=reason))
        else:
            when = (f"closed {e.close_date.isoformat()}, on or before the as-of date" if e.close_date and as_of
                    else "close date or as-of date unknown")
            notes.append(f"Event noted, not penalized ({when}): {e.description}{where}.")
            reason = (f"Closed {e.close_date.isoformat()}, on or before the {as_of.isoformat()} as-of date, so the "
                      "figure already reflects it; noted, not penalized." if e.close_date and as_of else
                      "The close date or the as-of date is unknown, so it cannot be shown to postdate the figure; "
                      "noted, not penalized.")
            event_outcomes.append(EventOutcome(description=e.description, url=e.url, close_date=e.close_date,
                                               penalized=False, headcount_change=e.headcount_change, reason=reason))

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
                    flag = (f"Conflict: tier {s.tier} source ({s.url}) reports {effective[id(s)]:,}, "
                            f"{diff:.0%} from the certified value.")
                    if scope_flags and _is_linkedin(s) and effective[id(s)] > value:
                        explained.append((flag, scope_flags[0]))
                        s.role_reason = (f"Disagrees by {diff:.0%}, most likely for the same reason as the open scope "
                                         "question (it counts more of the organization); counted once, there.")
                    else:
                        flags.append(flag)
                        s.role_reason = f"Disagrees with the certified value by {diff:.0%}; flagged as a conflict."
                else:
                    s.role_reason = (f"Disagrees by {diff:.0%}, but a tier {s.tier} or stale source never lowers "
                                     "confidence; recorded only.")
            else:
                s.role = "supporting"
                s.role_reason = (f"Within {diff:.0%} of the certified value: closer than a conflict, not close enough "
                                 "to corroborate; context only.")

    li = rules.linkedin_check(value, linkedin, policy)
    linkedin_was_input = ((growth is not None and growth.used_linkedin) or linkedin_floor_used
                          or (derivation is not None and linkedin.member_count is not None))
    if li.status == "flag":
        current_filing = (selected is not None and policy.tier_class(selected.tier) == "primary"
                          and selected.as_of_date is not None
                          and (rules.within_months(selected.as_of_date, lookup_date, policy.recency.certified_max_age_months)
                               or rules.latest_release_current(selected, lookup_date, policy)))
        if linkedin_was_input:
            notes.append(f"LinkedIn check not applied as a penalty because LinkedIn was an input. {li.note}")
        elif scope_flags and value is not None and (linkedin.member_count or 0) > value:
            explained.append((f"LinkedIn: {li.note}", scope_flags[0]))
        elif current_filing:
            li = li.model_copy(update={"not_penalized": f"The key source is a current tier {selected.tier} filing, which "
                                                         "a LinkedIn member count doesn't overrule"})
        elif (li.gap or 0) < policy.linkedin.penalty_gap:
            li = li.model_copy(update={"not_penalized": f"The gap ({li.gap:.0%}) is under the "
                                                         f"{policy.linkedin.penalty_gap:.0%} that lowers confidence; "
                                                         "member counts often include former staff and contractors"})
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
    direction = _direction(selected, value, event_outcomes, sources, effective, lookup_date, policy, growth is not None)
    if value is not None:  # the one range we give, centred on our number and as wide as the confidence warrants
        value_range = rules.confidence_range(value, score, qualifier, direction.direction if direction else None,
                                             supported_floor, policy)

    return Certification(
        entity=entity, certified_count=value, count_type=count_type, qualifier=qualifier,
        count_basis=None if value is None else (selected.basis if selected is not None else "headcount"),
        range=value_range, confidence_score=score, confidence_level=policy.confidence_levels[score],
        confidence_breakdown=steps, policy_tier=policy_tier, as_of_date=as_of,
        as_of_estimated=bool(selected is not None and selected.as_of_estimated),
        as_of_from_url=bool(selected is not None and selected.as_of_from_url),
        pre_adjustment=not primary_anchor and (any(o.after_as_of for o in event_outcomes)
                                               or bool(selected is not None and selected.predates_change)),
        direction=direction,
        scope_notes=scope_notes, explained_flags=explained,
        indicated_range=rules.indicated_range(selected, value, sources, lookup_date, policy) if growth is None else None,
        sources=_explain_unassigned(sources, value), linkedin_check=li, adjustments=adjustments, flags=flags,
        events=event_outcomes,
        rationale=_rationale(selected, derivation, value, len(corroborators), notes, flags, score, policy),
        trend=rules.trend_points(selected, sources, effective) if selected is not None and growth is None else [],
        policy_version=policy.policy_version,
    )


def _pct(x: float) -> str:
    """Percent with a decimal below 1% (0.4%, not 0%)."""
    return f"{x:.1%}" if x < 0.01 else f"{x:.0%}"


_KIND_SIGN = {"layoff": -1, "spinoff": -1, "hiring": 1, "acquisition": 1, "merger": 1}


def _direction(selected: Source | None, value: int | None, outcomes: list[EventOutcome], sources: list[Source],
               effective: dict[int, int], lookup_date: date, policy: Policy, grown: bool) -> Direction | None:
    """Is the true current headcount likely higher, lower or in line with the certified figure?"""
    if value is None:
        return None
    after = [o for o in outcomes if o.after_as_of]
    if after:
        net = sum(o.headcount_change or 0 for o in after)
        signs = {(-1 if (o.headcount_change or 0) < 0 else 1) if o.headcount_change else
                 _KIND_SIGN.get(_kind_of(o.description), 0) for o in after}
        sign = (-1 if net < 0 else 1) if net else (signs.pop() if len(signs) == 1 else 0)
        what = "; ".join(f"{_short(o.description)} ({o.close_date.isoformat()}"
                         + (f", {o.headcount_change:+,})" if o.headcount_change is not None else ")") for o in after)
        if sign:
            size = "somewhat " if net == 0 or abs(net) / value <= policy.agreement.corroborates_within else ""
            word = "lower" if sign < 0 else "higher"
            return Direction(direction=word, reason=f"Likely {size}{word} than reported because of a change after the as-of date: {what}.")
        return Direction(direction="unknown", reason=f"Changes after the as-of date point both ways: {what}.")
    if selected is not None and selected.predates_change:
        return Direction(direction="lower", reason="Likely lower than reported: the source says the figure predates "
                                                   "a change it describes.")
    ir = rules.indicated_range(selected, value, sources, lookup_date, policy) if not grown else None
    if ir is not None:
        mid = (ir.low + ir.high) / 2
        word = "higher" if mid > value else "lower"
        span = f"about {ir.low:,}" if ir.low == ir.high else f"{ir.low:,}-{ir.high:,}"
        when = (ir.earliest.isoformat() if ir.earliest == ir.latest
                else f"{ir.earliest.isoformat()} to {ir.latest.isoformat()}")
        return Direction(direction=word, reason=f"Likely {word}: newer data-provider figures put headcount at "
                                                f"{span} ({when}).")
    if selected is not None and selected.as_of_date is not None:
        prior = sorted((s for s in sources if s is not selected and s.tier == selected.tier and s.scope == "global"
                        and s.basis == selected.basis and s.as_of_date and s.as_of_date < selected.as_of_date
                        and not s.corroboration_only), key=lambda s: s.as_of_date)
        if prior:
            last = effective[id(prior[-1])]
            change = (value - last) / last if last else 0
            if abs(change) < 0.03:
                return Direction(direction="in_line", reason=f"Likely in line: the prior figure was {last:,} "
                                                              f"({change:+.0%}), and no later change is known.")
            word = "higher" if change > 0 else "lower"
            return Direction(direction=word, reason=f"Possibly {word} now if the recent trend continued ({last:,} to "
                                                    f"{value:,}, {change:+.0%}); no later change is known.")
    return Direction(direction="unknown", reason="No newer evidence to say whether the figure has moved since its "
                                                 "as-of date.")


_SEC_FILER = re.compile(r"sec\.gov/Archives/edgar/data/(\d+)/", re.I)


def _restore_annual_series(sources: list[Source], policy: Policy) -> None:
    """A filer's annual SEC figures form one whole-company series. When one year is marked partial but is
    within the corroboration threshold of the same filer's whole-company figure for another year, the
    "partial" reading came from a breakdown that follows the total (e.g. "..., 121,000 in the U.S. and
    102,000 internationally"), so it is restored to whole-company. Real partial figures are far smaller."""
    series: dict[str, list[Source]] = {}
    for s in sources:
        m = _SEC_FILER.search(s.url) if s.tier == 1 else None
        if m:
            series.setdefault(m.group(1), []).append(s)
    for filings in series.values():
        whole = [s for s in filings if s.scope == "global"]
        for s in filings:
            if s.scope != "partial":
                continue
            near = [w for w in whole if w.as_of_date != s.as_of_date
                    and rules.relative_diff(s.value, w.value) <= policy.agreement.corroborates_within]
            if near:
                ref = max(near, key=lambda w: w.as_of_date or date.min)
                s.scope = "global"
                s.notes.append(f"Restored to whole-company: within {rules.relative_diff(s.value, ref.value):.0%} of the "
                               f"same filer's whole-company figure ({ref.value:,}, as of {ref.as_of_date}); the "
                               "breakdown after the total doesn't narrow it.")


def _is_linkedin(s: Source) -> bool:
    return s.tier == 5 or "linkedin.com" in s.url.lower()


def _short(description: str, limit: int = 90) -> str:
    """First sentence of an event description, trimmed for a one-line reason."""
    first = description.split(". ")[0].rstrip(".")
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


def _kind_of(description: str) -> str:
    d = description.lower()
    for kind, words in (("layoff", ("layoff", "laid off", "cut", "reduction")), ("hiring", ("hiring", "hire")),
                        ("spinoff", ("spinoff", "spin-off", "spun off")), ("acquisition", ("acquisition", "acquired")),
                        ("merger", ("merger", "merged"))):
        if any(w in d for w in words):
            return kind
    return "other"


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
