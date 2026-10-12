# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
from datetime import date
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


def test_members_within_the_allowance_pass(entity):
    li = LinkedInEvidence(member_count=12_000, workforce_profile="white_collar")  # 20% above: lingering profiles
    cert = certify(entity, [src(1, 10_000)], linkedin=li, lookup_date=LOOKUP)
    assert cert.linkedin_check.status == "pass" and not cert.flags


def test_a_large_gap_against_an_older_source_is_flagged_not_floored(entity):
    li = LinkedInEvidence(member_count=25_000, workforce_profile="white_collar")  # 150% above
    cert = certify(entity, [src(1, 10_000, as_of=date(2024, 1, 31))], linkedin=li, lookup_date=LOOKUP)
    assert cert.certified_count == 10_000          # value is kept, not raised to the member count
    assert cert.linkedin_check.status == "flag" and cert.linkedin_check.not_penalized is None
    assert "150% above the certified 10,000; more than the 30% tolerance" in cert.linkedin_check.note
    assert any(f.startswith("LinkedIn") for f in cert.flags)
    assert cert.confidence_score == 2              # 4, -1 recency, -1 LinkedIn


def test_a_current_filing_is_not_overruled_by_linkedin(entity):
    li = LinkedInEvidence(member_count=25_000, workforce_profile="white_collar")
    cert = certify(entity, [src(1, 10_000)], linkedin=li, lookup_date=LOOKUP)
    assert cert.linkedin_check.status == "flag" and "current tier 1 filing" in cert.linkedin_check.not_penalized
    assert not cert.flags and cert.confidence_score == 4


def test_a_moderate_gap_is_worth_knowing_without_a_penalty(entity):
    li = LinkedInEvidence(member_count=16_000, workforce_profile="white_collar")  # 60% above, under the 100% gap
    cert = certify(entity, [src(4, 10_000, as_of=None)], linkedin=li, lookup_date=LOOKUP)
    assert cert.linkedin_check.status == "flag" and "under the 100%" in cert.linkedin_check.not_penalized
    assert not any(f.startswith("LinkedIn") for f in cert.flags)


def test_above_implied_range_is_flag(policy):
    check = linkedin_check(30_000, LinkedInEvidence(member_count=9_500, workforce_profile="white_collar"), policy)
    assert check.status == "flag"
    assert check.note.startswith("Flag: certified 30,000 is above the range")


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


def test_members_within_tolerance_above_count_is_pass(entity):
    # Salesforce run: 87,523 members vs 83,334 certified (+5%), white-collar: a pass, not a floor.
    li = LinkedInEvidence(member_count=87_523, workforce_profile="white_collar")
    cert = certify(entity, [src(1, 83_334)], linkedin=li, lookup_date=LOOKUP)
    assert cert.linkedin_check.status == "pass"
    assert cert.linkedin_check.note.startswith("Pass: LinkedIn shows 87,523 members, 5% above")
    assert cert.flags == [] and cert.confidence_score == 4


def test_status_and_note_always_agree(policy):
    for members in (5_000, 9_000, 10_000, 11_000, 11_600, 30_000):
        for profile in ("white_collar", "mixed", "blue_collar"):
            check = linkedin_check(10_000, LinkedInEvidence(member_count=members, workforce_profile=profile), policy)
            assert check.note.lower().startswith(check.status), (members, profile, check.note)
