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
    cert = score(entity, src(1, 10_000), src(1, 9_200, as_of=date(2024, 12, 31)))
    assert (cert.confidence_score, cert.confidence_level) == (5, "Certified, corroborated")
    assert [s.role for s in cert.sources] == ["selected", "corroborates"]


def test_corroboration_can_come_from_any_tier(entity):
    assert score(entity, src(1, 10_000), src(4, 11_400, as_of=None)).confidence_score == 5


def test_disagreeing_tertiary_does_not_corroborate(entity):
    assert score(entity, src(1, 10_000), src(7, 12_000, as_of=date(2026, 9, 1))).confidence_score == 4


def test_partial_scope_does_not_corroborate(entity):
    assert score(entity, src(1, 10_000), src(1, 9_800, scope="partial", url="https://x/us")).confidence_score == 4


def test_18_month_boundary(entity):
    assert score(entity, src(1, 10_000, as_of=date(2025, 4, 11))).confidence_score == 4   # 18 months
    assert score(entity, src(1, 10_000, as_of=date(2025, 4, 10))).confidence_score == 3   # just over


def test_older_primary_is_supported_even_with_corroboration(entity):
    assert score(entity, src(1, 10_000, as_of=date(2024, 6, 30)),
                 src(1, 9_800, as_of=date(2023, 6, 30))).confidence_score == 3


def test_undated_primary_is_supported(entity):
    assert score(entity, src(2, 10_000, as_of=None, published_date=date(2026, 3, 1))).confidence_score == 3


# --- Secondary sources ---

def test_tier3_is_supported(entity):
    assert score(entity, src(3, 10_000)).confidence_score == 3
    assert score(entity, src(3, 10_000), src(4, 10_100, as_of=None)).confidence_score == 3


def test_tier4_to_6_needs_corroboration(entity):
    assert score(entity, src(5, 4_500, as_of=None, qualifier="more_than")).confidence_score == 2
    assert score(entity, src(5, 4_500, as_of=None), src(6, 4_800)).confidence_score == 3


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
    cert = score(entity, src(1, 110_000, qualifier="more_than", url="https://x/20f"),
                 src(1, 105_000, url="https://x/table"))
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
