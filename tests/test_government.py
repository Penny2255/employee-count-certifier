"""Public-sector rules (Livermore): FTE figures kept as stated; school systems excluded but logged."""

from datetime import date

from certifier import LinkedInEvidence, certify, parse_figure
from certifier.figures import Figure

from .conftest import LOOKUP, src


def test_parse_fte():
    text = "The City, with 499 full-time equivalent employees, provides a wide range of services"
    assert parse_figure(text) == Figure(499, "exact", "fte")
    assert parse_figure("approximately 1,200 FTEs") == Figure(1_200, "approximately", "fte")
    assert parse_figure("we employed 31,360 people").basis == "headcount"
    assert parse_figure("After 2020, we employed 500 people").basis == "headcount"


def test_fte_certified_as_stated(entity):
    cert = certify(entity, [src(1, 499, basis="fte")], lookup_date=LOOKUP)
    assert (cert.certified_count, cert.count_basis, cert.count_type) == (499, "fte", "reported")
    assert "full-time equivalents, kept as stated" in cert.rationale


def test_fte_never_growth_adjusted(entity):
    growing = LinkedInEvidence(member_count=900, growth_1y=0.30, workforce_profile="mixed")
    cert = certify(entity, [src(4, 499, as_of=None, basis="fte")], linkedin=growing, lookup_date=LOOKUP)
    assert cert.certified_count == 499


def test_headcount_in_line_replaces_fte_same_tier_and_date(entity):
    fte = src(1, 499, basis="fte", url="https://example.com/x/fte")
    headcount = src(1, 541, url="https://example.com/x/headcount")  # +8%: in line
    cert = certify(entity, [fte, headcount], lookup_date=LOOKUP)
    assert (cert.certified_count, cert.count_basis) == (541, "headcount")


def test_headcount_far_from_fte_keeps_fte_without_flag(entity):
    fte = src(1, 499, basis="fte", url="https://example.com/x/fte")
    headcount = src(1, 700, url="https://example.com/x/headcount")  # +40%: not strong enough to replace FTE
    cert = certify(entity, [fte, headcount], lookup_date=LOOKUP)
    assert (cert.certified_count, cert.count_basis) == (499, "fte")
    assert cert.flags == []
    assert cert.confidence_score == 4


def test_lower_tier_headcount_does_not_replace_fte(entity):
    cert = certify(entity, [src(1, 499, basis="fte"), src(4, 520, as_of=None)], lookup_date=LOOKUP)
    assert cert.count_basis == "fte"


def test_school_system_figure_logged_with_variance_not_used(entity):
    city = src(1, 499, basis="fte", url="https://example.com/x/acfr")
    with_schools = src(2, 1_850, scope="broader", url="https://example.com/x/budget-incl-schools")
    cert = certify(entity, [city, with_schools], lookup_date=LOOKUP)
    assert cert.certified_count == 499
    assert cert.sources[1].role == "supporting"
    note = cert.adjustments[-1]
    assert note.change == 0 and "school system" in note.reason and "+1,351" in note.reason
    assert cert.flags == [] and cert.confidence_score == 4


def test_broader_scope_never_selected(entity):
    cert = certify(entity, [src(2, 1_850, scope="broader")], lookup_date=LOOKUP)
    assert cert.certified_count is None and cert.confidence_score == 0
