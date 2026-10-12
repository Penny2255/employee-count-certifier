# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
from datetime import date

from certifier import LinkedInEvidence, certify

from .conftest import LOOKUP, src


def score(entity, *sources, **kw):
    return certify(entity, list(sources), lookup_date=LOOKUP, **kw)


# --- Primary sources (user decision: single recent tier 1-2 = 4; plus agreement = 5) ---

def test_single_recent_primary_is_certified_4(entity):
    cert = score(entity, src(1, 10_000, as_of=date(2025, 12, 31)))
    assert (cert.confidence_score, cert.confidence_level) == (4, "Certified")


def test_tier2_recent_is_certified_4(entity):
    assert score(entity, src(2, 10_000, as_of=date(2025, 6, 30))).confidence_score == 4


def test_recent_primary_plus_agreeing_source_is_5(entity):
    newsroom = src(3, 9_800, qualifier="more_than", as_of=date(2026, 1, 15), excerpt="over 9,800 employees")
    cert = score(entity, src(1, 10_000), newsroom)
    assert (cert.confidence_score, cert.confidence_level) == (5, "Certified, corroborated")
    assert [s.role for s in cert.sources] == ["selected", "corroborates"]


def test_corroboration_can_come_from_any_tier(entity):
    assert score(entity, src(1, 10_000), src(4, 11_400, as_of=date(2026, 2, 1))).confidence_score == 5


# --- Corroboration must be independent and near the same as-of date ---

def test_prior_year_filing_does_not_corroborate(entity):
    cert = score(entity, src(1, 10_000), src(1, 9_200, as_of=date(2024, 12, 31)))
    assert cert.confidence_score == 4
    assert cert.sources[1].role == "supporting"
    assert "more than 9 months" in cert.sources[1].notes[-1]


def test_restatement_of_the_same_figure_does_not_corroborate(entity):
    wikipedia = src(9, 10_000, as_of=date(2025, 12, 31), url="https://en.wikipedia.org/wiki/Example")
    flagged = src(9, 10_050, as_of=date(2025, 12, 31), url="https://bullfincher.io/example", restates=True)
    cert = score(entity, src(1, 10_000), wikipedia, flagged)
    assert cert.confidence_score == 4
    assert [s.role for s in cert.sources] == ["selected", "supporting", "supporting"]


def test_same_document_does_not_corroborate(entity):
    headline = src(1, 9_900, qualifier="more_than", url="https://example.com/10k#overview")
    cert = score(entity, src(1, 9_950, url="https://example.com/10k#employees"), headline)
    assert cert.confidence_score == 4


def test_undated_source_cannot_corroborate_but_can_conflict(entity):
    assert score(entity, src(1, 10_000), src(4, 10_100, as_of=None)).confidence_score == 4
    assert score(entity, src(1, 10_000), src(4, 20_000, as_of=None)).confidence_score == 3


def test_anchor_with_no_date_gets_no_corroboration_bonus(entity):
    # A website tile with no date at all: nearness can't be established, so no +1.
    cert = score(entity, src(4, 1_500, as_of=None), src(6, 1_550, as_of=date(2026, 7, 1)))
    assert cert.confidence_score == 2
    assert "no as-of date" in cert.sources[1].role_reason


# --- Score breakdown ---

def test_breakdown_explains_each_step(entity):
    newsroom = src(3, 9_800, qualifier="more_than", as_of=date(2026, 1, 15), url="https://example.com/news",
                   excerpt="over 9,800 employees")
    cert = score(entity, src(1, 10_000), newsroom)
    steps = [(s.points, s.reason) for s in cert.confidence_breakdown]
    assert steps[0] == (4, "base 4: tier 1 primary source")
    assert steps[1][0] == 1 and "example.com 'over 9,800 employees'" in steps[1][1]
    assert steps[2] == (0, "no deductions")
    assert sum(p for p, _ in steps) == cert.confidence_score == 5


def test_breakdown_lists_deductions_and_floor(entity):
    cert = score(entity, src(9, 1_000, as_of=None), event_flags=["merger", "spinoff"])
    assert [s.points for s in cert.confidence_breakdown] == [1, 0, 0]
    assert "minimum of 1" in cert.confidence_breakdown[1].reason


# --- Events are judged against the as-of date ---

def test_event_closed_before_as_of_is_noted_not_penalized(entity):
    from certifier.models import Event
    informatica = Event(description="Acquisition of Informatica", close_date=date(2025, 11, 18))
    cert = score(entity, src(1, 10_000, as_of=date(2026, 1, 31)), events=[informatica])
    assert cert.confidence_score == 4 and cert.flags == []
    assert "not penalized" in cert.rationale


def test_event_after_as_of_lowers_confidence_for_secondary_anchor(entity):
    from certifier.models import Event
    deal = Event(description="Acquisition of Target Co", close_date=date(2026, 5, 1), url="https://example.com/pr")
    cert = score(entity, src(4, 10_000, as_of=date(2026, 1, 31)), events=[deal])
    assert cert.confidence_score == 1  # base 2 - 1 for the event
    assert cert.flags[0].startswith("Event-driven: Acquisition of Target Co, 2026-05-01, after")
    assert cert.pre_adjustment


def test_event_after_as_of_never_changes_a_primary_anchor(entity):
    from certifier.models import Event
    deal = Event(description="Acquisition of Target Co", close_date=date(2026, 5, 1), url="https://example.com/pr")
    cert = score(entity, src(1, 10_000, as_of=date(2026, 1, 31)), events=[deal])
    assert (cert.confidence_score, cert.pre_adjustment, cert.flags) == (4, False, [])
    assert cert.events[0].after_as_of and "stands as reported" in cert.events[0].reason
    assert cert.direction.direction == "higher"


def test_event_without_close_date_is_noted(entity):
    from certifier.models import Event
    cert = score(entity, src(1, 10_000), events=[Event(description="Rumored merger")])
    assert cert.confidence_score == 4


def test_disagreeing_tertiary_does_not_corroborate(entity):
    assert score(entity, src(1, 10_000), src(7, 12_000, as_of=date(2026, 9, 1))).confidence_score == 4


def test_partial_scope_does_not_corroborate(entity):
    assert score(entity, src(1, 10_000), src(1, 9_800, scope="partial", url="https://example.com/x/us")).confidence_score == 4


def test_18_month_boundary(entity):
    assert score(entity, src(1, 10_000, as_of=date(2025, 4, 11))).confidence_score == 4   # 18 months
    assert score(entity, src(1, 10_000, as_of=date(2025, 4, 10))).confidence_score == 3   # just over


def test_older_primary_is_supported_even_with_corroboration(entity):
    assert score(entity, src(1, 10_000, as_of=date(2024, 6, 30)),
                 src(1, 9_800, as_of=date(2023, 6, 30))).confidence_score == 3


def test_undated_primary_gets_an_estimated_as_of_from_its_publication_date(entity):
    cert = score(entity, src(2, 10_000, as_of=None, published_date=date(2026, 3, 1)))
    assert (cert.as_of_date, cert.as_of_estimated, cert.confidence_score) == (date(2026, 3, 1), True, 4)


def test_primary_with_no_date_at_all_is_supported(entity):
    cert = score(entity, src(2, 10_000, as_of=None))
    assert cert.confidence_score == 3
    assert cert.confidence_breakdown[1].reason == "recency: tier 2 source has no as-of date"


# --- Secondary sources ---

def test_tier3_is_supported(entity):
    assert score(entity, src(3, 10_000)).confidence_score == 3
    assert score(entity, src(3, 10_000), src(4, 10_100, as_of=None)).confidence_score == 3


def test_tier4_to_6_needs_corroboration(entity):
    assert score(entity, src(5, 4_500, as_of=None, qualifier="more_than")).confidence_score == 2
    assert score(entity, src(5, 4_500, as_of=date(2026, 5, 1)), src(6, 4_800, as_of=date(2026, 6, 1))).confidence_score == 3


# --- Tertiary derivation ---

def test_two_agreeing_tertiary_sources_are_calculated_2(entity):
    cert = score(entity, src(7, 1_000, as_of=date(2026, 6, 1)), src(8, 1_100, as_of=date(2026, 5, 1)))
    assert cert.certified_count == 1_050
    assert cert.count_type == "calculated"
    assert cert.range == (1_000, 1_100)
    assert cert.policy_tier == 7
    assert cert.confidence_score == 2
    assert all(s.role == "derived_input" for s in cert.sources)


def test_single_tertiary_source_is_estimated_1(entity):
    cert = score(entity, src(9, 1_000, as_of=None))
    assert (cert.count_type, cert.confidence_score, cert.confidence_level) == ("estimated", 1, "Unverified")


def test_tertiary_disagreeing_over_30pct_is_1(entity):
    cert = score(entity, src(7, 1_000, as_of=None), src(8, 2_000, as_of=None))
    assert (cert.count_type, cert.confidence_score) == ("estimated", 1)


def test_linkedin_inputs_join_derivation(entity):
    cert = score(entity, src(7, 1_000, as_of=None),
                 linkedin=LinkedInEvidence(member_count=900, workforce_profile="white_collar"))
    assert cert.count_type == "calculated"
    assert "LinkedIn member count implied" in cert.adjustments[-1].reason


# --- Flags and floor ---

def test_tier1_to_6_conflict_lowers_one_level(entity):
    cert = score(entity, src(1, 10_000), src(4, 20_000, as_of=None))
    assert cert.confidence_score == 3
    assert cert.sources[1].role == "conflicts"
    assert any(f.startswith("Conflict") for f in cert.flags)


def test_tertiary_conflict_is_recorded_not_penalized(entity):
    cert = score(entity, src(1, 10_000), src(7, 20_000, as_of=date(2026, 9, 1)))
    assert cert.confidence_score == 4
    assert cert.sources[1].role == "conflicts"
    assert cert.flags == []


def test_detailed_figure_not_in_line_is_flagged_not_corroborating(entity):
    cert = score(entity, src(1, 110_000, qualifier="more_than", url="https://example.com/x/20f"),
                 src(1, 105_000, url="https://example.com/x/table"))
    assert cert.certified_count == 110_000
    assert [s.role for s in cert.sources] == ["selected", "conflicts"]
    assert cert.confidence_score == 3  # Certified (4), lowered one level by the review flag


def test_event_flag_lowers_one_level(entity):
    cert = score(entity, src(1, 10_000), event_flags=["Acquired by Parent Co in 2026"])
    assert cert.confidence_score == 3
    assert cert.flags == ["Event-driven: Acquired by Parent Co in 2026"]


def test_flags_never_drop_below_1(entity):
    cert = score(entity, src(9, 1_000, as_of=None), event_flags=["merger", "spinoff"])
    assert cert.confidence_score == 1


def test_nothing_found_is_unattained(entity):
    cert = score(entity, linkedin=LinkedInEvidence(member_count=500))
    assert (cert.certified_count, cert.confidence_score, cert.confidence_level) == (None, 0, "Unattained")
