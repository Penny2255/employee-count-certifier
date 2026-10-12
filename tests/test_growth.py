# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
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


def test_linkedin_within_tolerance_after_adjustment(entity):
    cert = run(entity, src(4, 1_500, as_of=None))
    assert cert.linkedin_check.status == "pass"  # 2,137 members is 7% above 2,000: within tolerance
    assert cert.flags == []


def test_linkedin_flag_not_penalized_when_linkedin_was_an_input(entity):
    far = GROWING.model_copy(update={"member_count": 5_000})  # adjusts to 4,100; members 22% above
    cert = run(entity, src(4, 1_500, as_of=None), far)
    assert cert.linkedin_check.status == "flag"
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


def test_recent_agreeing_data_providers_act_as_signal(entity):
    # Gong live run: website 1,500 (undated); Revelio 2,101, LeadIQ 2,600, Tracxn 2,672 (2026).
    sources = [src(4, 1_500, as_of=None, url="https://gong.io/about"),
               src(7, 2_101, as_of=date(2026, 3, 1), url="https://revelio"),
               src(9, 2_600, as_of=date(2026, 8, 1), url="https://leadiq"),
               src(9, 2_672, as_of=date(2026, 8, 26), url="https://tracxn")]
    cert = certify(entity, sources, lookup_date=LOOKUP)
    assert (cert.certified_count, cert.range, cert.count_type) == (2_200, (1_500, 2_700), "estimated")
    assert cert.confidence_score == 3
    assert "data-provider figures" in cert.adjustments[-1].reason


def test_outlier_provider_and_agreeing_member_count(entity):
    # Gong live run 2: an outlier provider figure must not block the signal, and the LinkedIn
    # member count (2,592, no growth visible) joins it instead of penalizing the result.
    sources = [src(4, 1_500, as_of=None, url="https://gong.io/about"),
               src(7, 2_101, as_of=date(2026, 3, 1), url="https://revelio"),
               src(9, 2_600, as_of=date(2026, 8, 1), url="https://leadiq"),
               src(9, 2_672, as_of=date(2026, 8, 26), url="https://tracxn"),
               src(9, 1_100, as_of=date(2026, 5, 1), url="https://builtin")]
    li = LinkedInEvidence(member_count=2_592, size_range=(1_001, 5_000), workforce_profile="white_collar")
    cert = certify(entity, sources, linkedin=li, lookup_date=LOOKUP)
    assert cert.certified_count == 2_200
    assert cert.confidence_score == 3
    assert cert.flags == []
    assert "LinkedIn member count (2,592)" in cert.adjustments[-1].reason


def test_single_or_disagreeing_data_providers_are_not_a_signal(entity):
    one = [src(4, 1_500, as_of=None), src(7, 2_400, as_of=date(2026, 8, 1))]
    assert certify(entity, one, lookup_date=LOOKUP).certified_count == 1_500
    split = [src(4, 1_500, as_of=None), src(7, 1_800, as_of=date(2026, 8, 1), url="a"),
             src(8, 4_000, as_of=date(2026, 8, 1), url="b")]
    assert certify(entity, split, lookup_date=LOOKUP).certified_count == 1_500


def test_needs_member_gap(entity):
    close = GROWING.model_copy(update={"member_count": 1_650})
    assert run(entity, src(4, 1_500, as_of=None), close).certified_count == 1_500
