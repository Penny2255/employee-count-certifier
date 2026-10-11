from certifier import LinkedInEvidence, certify
from certifier.rules import implied_headcount, linkedin_check

from .conftest import LOOKUP, src


def test_implied_ranges_match_spec(policy):
    assert implied_headcount(9_500, "white_collar", policy) == (10_000, 10_556)   # x1.05-1.11
    assert implied_headcount(5_000, "mixed", policy) == (5_555, 10_000)          # x1.1-2
    assert implied_headcount(2_500, "blue_collar", policy) == (5_000, 10_000)    # x2-4


def test_no_member_count_is_not_available(policy):
    check = linkedin_check(10_000, None, policy)
    assert check.status == "not_available"
    assert check.implied_range is None
    assert check.workforce_profile == "mixed"  # default profile


def test_not_available_leaves_confidence_unchanged(entity):
    cert = certify(entity, [src(1, 10_000)], lookup_date=LOOKUP)
    assert cert.linkedin_check.status == "not_available"
    assert cert.confidence_score == 4


def test_pass_inside_implied_range(policy):
    check = linkedin_check(10_200, LinkedInEvidence(member_count=9_500, workforce_profile="white_collar"), policy)
    assert check.status == "pass"


def test_below_member_count_is_flag_not_floor(entity):
    li = LinkedInEvidence(member_count=12_000, workforce_profile="white_collar")
    cert = certify(entity, [src(1, 10_000)], linkedin=li, lookup_date=LOOKUP)
    assert cert.certified_count == 10_000          # value is kept, not raised to the member count
    assert cert.linkedin_check.status == "flag"
    assert "below the LinkedIn member count" in cert.linkedin_check.note
    assert cert.confidence_score == 3              # Certified (4) lowered one level
    assert any(f.startswith("LinkedIn") for f in cert.flags)


def test_above_implied_range_is_flag(policy):
    check = linkedin_check(30_000, LinkedInEvidence(member_count=9_500, workforce_profile="white_collar"), policy)
    assert check.status == "flag"
    assert "outside the implied range" in check.note


def test_blue_collar_gap_passes(policy):
    # Tyson-like: 133,000 employees, few on LinkedIn.
    check = linkedin_check(133_000, LinkedInEvidence(member_count=45_000, workforce_profile="blue_collar"), policy)
    assert check.status == "pass"


def test_size_range_recorded_but_never_changes_status(policy):
    li = LinkedInEvidence(member_count=9_500, size_range=(5_001, 10_000), workforce_profile="white_collar")
    check = linkedin_check(10_200, li, policy)
    assert check.size_range_agrees is False
    assert check.status == "pass"
    assert linkedin_check(9_000, LinkedInEvidence(size_range=(5_001, 10_000)), policy).size_range_agrees is True
