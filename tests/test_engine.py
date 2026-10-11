"""Engine output shape and bookkeeping. Golden-set cases live in examples/ (test_examples.py)."""

import json
from datetime import date

from certifier import Certification, certify

from .conftest import LOOKUP, src


def test_record_has_every_spec_field_and_serializes(entity):
    cert = certify(entity, [src(1, 10_000, excerpt="we employed 10,000 people")], lookup_date=LOOKUP)
    data = json.loads(cert.model_dump_json())
    assert set(data) == {
        "entity", "certified_count", "count_type", "qualifier", "count_basis", "range", "confidence_score", "confidence_level",
        "confidence_breakdown",
        "policy_tier", "as_of_date", "as_of_estimated", "as_of_from_url", "pre_adjustment", "direction", "scope_notes",
        "indicated_range", "sources", "linkedin_check", "adjustments", "flags", "events", "rationale",
        "trend", "forecast", "policy_version"}
    assert data["policy_version"] == "0.2"
    assert data["as_of_date"] == "2025-12-31"
    assert Certification.model_validate(data) == cert


def test_rationale_explains_choice(entity):
    cert = certify(entity, [src(1, 10_000), src(4, 10_500, as_of=date(2026, 3, 1))], lookup_date=LOOKUP)
    assert "tier 1" in cert.rationale
    assert "1 independent corroborating source" in cert.rationale
    assert "Confidence 5 (Certified, corroborated)" in cert.rationale


def test_undated_and_stale_sources_are_noted(entity):
    cert = certify(entity, [src(1, 10_000), src(4, 10_500, as_of=None), src(3, 9_000, as_of=date(2022, 1, 1))],
                   lookup_date=LOOKUP)
    assert "Undated source." in cert.sources[1].notes
    assert any("Older than 24 months" in n for n in cert.sources[2].notes)


def test_inputs_not_mutated(entity):
    original = src(1, 10_000)
    certify(entity, [original], lookup_date=LOOKUP)
    assert original.role is None and original.notes == []


# --- Provenance: tier 1 must be sec.gov (with accession) or the organization's own site ---

SEC = "https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm"


def test_mirror_of_10k_is_corroboration_only():
    from certifier import Entity
    sf = Entity(name="Salesforce, Inc.", website="https://www.salesforce.com")
    quartr = src(1, 83_334, as_of=date(2026, 1, 31), url="https://quartr.com/companies/salesforce/10-k-2026")
    edgar = src(1, 83_334, as_of=date(2026, 1, 31), url=SEC)
    cert = certify(sf, [quartr, edgar], lookup_date=LOOKUP)
    assert [s.url for s in cert.sources if s.role == "selected"] == [SEC]
    assert cert.sources[0].corroboration_only and "Mirror" in cert.sources[0].notes[0]


def test_mirror_alone_never_sets_the_value():
    from certifier import Entity
    sf = Entity(name="Salesforce, Inc.", website="https://www.salesforce.com")
    cert = certify(sf, [src(1, 83_334, as_of=date(2026, 1, 31), url="https://quartr.com/x")], lookup_date=LOOKUP)
    assert cert.certified_count is None


def test_sec_url_needs_an_accession_number_and_company_site_qualifies():
    from certifier import Entity
    from certifier.policy import default_policy
    from certifier.rules import is_tier1_provenance
    p = default_policy()
    assert is_tier1_provenance(src(1, 1, url=SEC), None, p)
    assert not is_tier1_provenance(src(1, 1, url="https://www.sec.gov/cgi-bin/browse-edgar?CIK=CRM"), None, p)
    assert is_tier1_provenance(src(1, 1, url="https://investor.salesforce.com/annual-report.pdf"), "salesforce.com", p)
    assert is_tier1_provenance(src(1, 1, url="https://www.sap.com/integrated-reports/2025/en.html"), "https://www.sap.com", p)
    assert not is_tier1_provenance(src(1, 1, url="https://quartr.com/x"), "https://www.salesforce.com", p)


# --- Trend from prior-year filings ---

def test_trend_from_prior_year_filings_oldest_first(entity):
    filings = [src(1, 29_945, as_of=date(2023, 12, 1)), src(1, 30_709, as_of=date(2024, 11, 29)),
               src(1, 31_360, as_of=date(2025, 11, 28)), src(4, 31_000, as_of=None)]
    cert = certify(entity, filings, lookup_date=LOOKUP)
    assert [(t.as_of_date.year, t.value) for t in cert.trend] == [(2023, 29_945), (2024, 30_709), (2025, 31_360)]
    assert all(t.tier == 1 for t in cert.trend)


# --- Dates: modified date counts when later than the publish date ---

def test_modified_date_used_when_later_than_published():
    from certifier import Source
    s = Source(url="u", tier=4, value=1, published_date=date(2023, 1, 1), modified_date=date(2026, 6, 1))
    assert s.recency_date == date(2026, 6, 1)
    older = Source(url="u", tier=4, value=1, published_date=date(2026, 6, 1), modified_date=date(2023, 1, 1))
    assert older.recency_date == date(2026, 6, 1)


def test_recently_modified_page_is_not_stale(entity):
    page = src(3, 1_000, as_of=None, published_date=date(2022, 1, 1), modified_date=date(2026, 5, 1))
    cert = certify(entity, [page], lookup_date=LOOKUP)
    assert cert.certified_count == 1_000
