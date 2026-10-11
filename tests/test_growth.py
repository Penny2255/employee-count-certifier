"""Growth adjustment: outdated secondary figures moved toward a growing LinkedIn member count (Gong)."""

from datetime import date

from certifier import LinkedInEvidence, certify
from certifier.rules import round_significant

from .conftest import LOOKUP, src

GROWING = LinkedInEvidence(member_count=2_137, size_range=(1_001, 5_000), workforce_profile="white_collar",
                           growth_1y=0.27, growth_2y=0.60)


def run(entity, source, linkedin=GROWING):
    return certify(entity, [source], linkedin=linkedin, lookup_date=LOOKUP)


def test_round_significant():
    assert round_significant(1_978, 2) == 2_000
    assert round_significant(2_312, 2) == 2_300
    assert round_significant(45_678, 2) == 46_000


def test_undated_website_figure_is_growth_adjusted(entity):
    cert = run(entity, src(4, 1_500, as_of=None))
    assert cert.certified_count == 2_000
    assert (cert.count_type, cert.qualifier, cert.range) == ("estimated", "approximately", (1_500, 2_300))
    assert cert.confidence_score == 3
    assert cert.adjustments[-1].source_figure == 1_500 and cert.adjustments[-1].result == 2_000
    assert "27% growth" in cert.adjustments[-1].reason


def test_linkedin_flag_not_penalized_when_linkedin_was_an_input(entity):
    cert = run(entity, src(4, 1_500, as_of=None))
    assert cert.linkedin_check.status == "flag"  # 2,000 is below 2,137 members: still reported
    assert cert.flags == []
    assert "LinkedIn was an input" in cert.rationale


def test_recent_dated_secondary_not_adjusted(entity):
    cert = run(entity, src(3, 1_500, as_of=date(2026, 6, 1)))
    assert cert.certified_count == 1_500


def test_old_dated_secondary_is_adjusted(entity):
    assert run(entity, src(3, 1_500, as_of=date(2025, 6, 1))).certified_count == 2_000


def test_tier1_never_growth_adjusted(entity):
    assert run(entity, src(1, 1_500, as_of=None)).certified_count == 1_500
    assert run(entity, src(1, 1_500, as_of=date(2023, 12, 31))).certified_count == 1_500


def test_lagging_tier2_filing_adjusted_once_older_than_18_months(entity):
    # Form 990 for calendar 2024, looked up Oct 2026 (21 months): no longer Certified, may be moved.
    cert = run(entity, src(2, 1_500, as_of=date(2024, 12, 31)))
    assert cert.certified_count == 2_000
    assert (cert.policy_tier, cert.count_type, cert.confidence_score) == (2, "estimated", 3)


def test_recent_tier2_filing_not_adjusted(entity):
    # 15 months old: still Certified, so it is left alone.
    assert run(entity, src(2, 1_500, as_of=date(2025, 6, 30))).certified_count == 1_500


def test_needs_growth_signal(entity):
    flat = GROWING.model_copy(update={"growth_1y": 0.02, "growth_2y": 0.05})
    assert run(entity, src(4, 1_500, as_of=None), flat).certified_count == 1_500
    unknown = GROWING.model_copy(update={"growth_1y": None, "growth_2y": None})
    assert run(entity, src(4, 1_500, as_of=None), unknown).certified_count == 1_500


def test_falls_back_to_two_year_growth(entity):
    two_year_only = GROWING.model_copy(update={"growth_1y": None})
    assert run(entity, src(4, 1_500, as_of=None), two_year_only).certified_count == 2_000


def test_needs_member_gap(entity):
    close = GROWING.model_copy(update={"member_count": 1_650})
    assert run(entity, src(4, 1_500, as_of=None), close).certified_count == 1_500
