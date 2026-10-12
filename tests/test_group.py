# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Entity groups: university (IPEDS) + health system + grand total (SPEC.md: Entity groups)."""

from datetime import date

from certifier import Entity, certify
from certifier.group import certify_group

from .conftest import LOOKUP, src


def cert(name, *sources):
    return certify(Entity(name=name), list(sources), lookup_date=LOOKUP)


SCHOOL = cert("UC Davis (IPEDS)", src(2, 15_029, as_of=date(2024, 11, 1), url="https://x/ipeds"))
HEALTH = cert("UC Davis Health", src(3, 10_000, as_of=date(2026, 1, 1), url="https://x/health"))


def roles(result):
    return [(e.role, e.primary) for e in result.entries]


def test_institution_primary_and_grand_total_estimated_when_no_total_found():
    result = certify_group("UC Davis", SCHOOL, [HEALTH])
    assert result.primary_role == "institution"
    assert roles(result) == [("grand_total", False), ("institution", True), ("affiliate", False)]
    total = result.entries[0].certification
    assert total.certified_count == 25_029
    assert total.count_type == "estimated"
    assert total.confidence_score == 2  # weakest part (3) minus 1
    assert "UC Davis (IPEDS) 15,029 + UC Davis Health 10,000" in total.rationale


def test_primary_grand_total_wins_when_wholly_owned_is_proven():
    total = cert("UC Davis (all entities)", src(1, 26_500, as_of=date(2025, 6, 30), url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/annual-report.htm"))
    result = certify_group("UC Davis", SCHOOL, [HEALTH], grand_total=total, wholly_owned_proven=True)
    assert result.primary_role == "grand_total"
    assert roles(result)[0] == ("grand_total", True)


def test_primary_grand_total_without_ownership_proof_stays_secondary():
    total = cert("UC Davis (all entities)", src(1, 26_500, as_of=date(2025, 6, 30), url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/annual-report.htm"))
    result = certify_group("UC Davis", SCHOOL, [HEALTH], grand_total=total, wholly_owned_proven=False)
    assert result.primary_role == "institution"
    assert "ownership of the affiliates is not proven" in result.rationale


def test_secondary_source_grand_total_stays_secondary_even_if_owned():
    total = cert("UC Davis (all entities)", src(4, 26_000, as_of=None, url="https://x/about"))
    result = certify_group("UC Davis", SCHOOL, [HEALTH], grand_total=total, wholly_owned_proven=True)
    assert result.primary_role == "institution"
    assert "not from a primary reported source" in result.rationale


def test_institution_alone():
    result = certify_group("UC Davis", SCHOOL, [])
    assert roles(result) == [("institution", True)]
