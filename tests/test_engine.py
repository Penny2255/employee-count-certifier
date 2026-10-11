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
        "policy_tier", "as_of_date", "sources", "linkedin_check", "adjustments", "flags", "rationale",
        "trend", "forecast", "policy_version"}
    assert data["policy_version"] == "0.2"
    assert data["as_of_date"] == "2025-12-31"
    assert Certification.model_validate(data) == cert


def test_rationale_explains_choice(entity):
    cert = certify(entity, [src(1, 10_000), src(4, 10_500, as_of=None)], lookup_date=LOOKUP)
    assert "tier 1" in cert.rationale
    assert "1 corroborating source" in cert.rationale
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
