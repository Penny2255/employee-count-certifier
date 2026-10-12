# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Standardized certification record: schema, section order, and the rationale rule (golden set)."""

import json
from datetime import date

import pytest

from certifier import Entity, certify
from certifier.examples import load_examples
from certifier.models import Event, LinkedInEvidence
from certifier.record import CertificationRecord, build_record, record_errors

from .conftest import LOOKUP, src

SECTIONS = ["entity", "headline", "confidence", "primary_source", "findings", "sources", "adjustments", "trend",
            "linkedin_check", "events", "methodology"]
EXAMPLES = load_examples()


def golden_record(ex) -> dict:
    cert = certify(ex.entity, ex.sources, linkedin=ex.linkedin, lookup_date=ex.lookup_date,
                   event_flags=ex.event_flags)
    return json.loads(build_record(cert, lookup_date=ex.lookup_date).model_dump_json())


@pytest.fixture(params=EXAMPLES, ids=[e.path.stem for e in EXAMPLES])
def record(request) -> dict:
    return golden_record(request.param)


# --- Schema on the golden set ---------------------------------------------------------------

def test_sections_present_in_order(record):
    assert list(record) == SECTIONS
    assert record_errors(record) == []


def test_empty_sections_say_why(record):
    for name in ("findings", "sources", "adjustments", "trend", "events"):
        section = record[name]
        assert section["items"] or section["none_reason"], name


def test_every_source_explains_tier_and_use(record):
    for row in record["sources"]["items"]:
        assert row["tier_rationale"].strip() and row["use_rationale"].strip(), row["id"]


def test_every_adjustment_and_event_has_rationale(record):
    assert all(a["rationale"].strip() for a in record["adjustments"]["items"])
    assert all(e["rationale"].strip() for e in record["events"]["items"])


def test_breakdown_sums_and_links_to_findings(record):
    conf = record["confidence"]
    assert sum(line["points"] for line in conf["breakdown"]) == conf["score"]
    finding_ids = {f["id"] for f in record["findings"]["items"]}
    assert all(line["finding_id"] in finding_ids for line in conf["breakdown"])
    assert conf["arithmetic"].endswith(f"= {conf['score']}")


def test_findings_are_well_formed(record):
    source_ids = {s["id"] for s in record["sources"]["items"]}
    for f in record["findings"]["items"]:
        assert f["status"] in ("green", "yellow", "red")
        assert f["title"] and "\n" not in f["title"]
        assert set(f["evidence"]) <= source_ids
        assert f["rationale"].count(". ") + f["rationale"].endswith(".") >= 2


def test_primary_source_matches_headline(record):
    primary = record["primary_source"]
    if record["headline"]["count"] is None:
        assert primary["none_reason"]
    elif primary["source_id"]:
        row = next(s for s in record["sources"]["items"] if s["id"] == primary["source_id"])
        assert row["role"] == "selected" and primary["tier_rationale"]


# --- The rationale rule fails validation when anything is missing ------------------------------

@pytest.fixture
def adobe() -> dict:
    return golden_record(next(e for e in EXAMPLES if e.path.stem == "adobe"))


def test_missing_source_rationale_fails(adobe):
    adobe["sources"]["items"][0]["use_rationale"] = " "
    assert any("sources.items.0.use_rationale" in e for e in record_errors(adobe))


def test_missing_tier_rationale_fails(adobe):
    adobe["sources"]["items"][0]["tier_rationale"] = ""
    assert record_errors(adobe)


def test_missing_score_line_rationale_fails(adobe):
    adobe["confidence"]["breakdown"][0]["rationale"] = ""
    assert record_errors(adobe)


def test_one_sentence_finding_rationale_fails(adobe):
    adobe["findings"]["items"][0]["rationale"] = "Too short to explain anything."
    assert record_errors(adobe)


def test_breakdown_that_does_not_sum_fails(adobe):
    adobe["confidence"]["score"] = 5
    assert any("sum" in e for e in record_errors(adobe))


def test_unlinked_breakdown_line_fails(adobe):
    adobe["confidence"]["breakdown"][0]["finding_id"] = "F99"
    assert record_errors(adobe)


def test_empty_section_without_reason_fails(adobe):
    adobe["events"] = {"items": [], "none_reason": None}
    assert record_errors(adobe)


# --- Specific behaviours ----------------------------------------------------------------------

SEC = "https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm"


def salesforce_record():
    sf = Entity(name="Salesforce, Inc.", website="https://www.salesforce.com")
    sources = [src(1, 83_334, as_of=date(2026, 1, 31), url=SEC, excerpt="we employed 83,334 people"),
               src(1, 83_334, as_of=date(2026, 1, 31), url="https://quartr.com/x"),
               src(3, 83_000, qualifier="more_than", as_of=date(2026, 3, 1), url="https://www.salesforce.com/news/x",
                   excerpt="over 83,000 employees"),
               src(1, 76_453, as_of=date(2025, 1, 31), url=SEC.replace("26000060", "25000006")),
               src(1, 72_682, as_of=date(2024, 1, 31), url=SEC.replace("26000060", "24000005"))]
    cert = certify(sf, sources, lookup_date=LOOKUP,
                   linkedin=LinkedInEvidence(member_count=87_523, workforce_profile="white_collar"),
                   events=[Event(description="Acquisition of Informatica", close_date=date(2025, 11, 18))])
    return build_record(cert, lookup_date=LOOKUP)


def test_salesforce_record_end_to_end():
    r = salesforce_record()
    assert (r.headline.count, r.confidence.score, r.confidence.arithmetic) == (83_334, 5, "4 + 1 + 0 = 5")
    assert r.primary_source.accession == "0001108524-26-000060"
    statuses = {f.title: f.status for f in r.findings.items}
    assert statuses["Read from sec.gov (accession 0001108524-26-000060)"] == "green"
    assert statuses["1 copy(ies) of a filing used only as support"] == "yellow"
    assert statuses["LinkedIn member count is consistent"] == "green"
    groups = {f.title: f.group for f in r.findings.items}
    assert groups["LinkedIn member count is consistent"] == "background"
    assert groups["Starting confidence 4 of 5 from the key source: SEC Annual Filing (Tier 1)"] == "affects"
    assert r.headline.bottom_line == "Ready to use. Strong, current primary source."
    assert r.headline.next_expected_update == date(2027, 5, 1) and "expected around May 2027" in r.headline.next_update_note
    assert [(e.penalized, e.description) for e in r.events.items] == [(False, "Acquisition of Informatica")]
    mirror = next(s for s in r.sources.items if "quartr" in s.url)
    assert not mirror.used and "mirror" in mirror.tier_rationale


def test_four_year_forecast_marked_estimated_with_a_widening_range():
    trend = salesforce_record().trend.items
    assert [t.estimated for t in trend] == [False, False, False, True, True, True, True]
    forecast = [t for t in trend if t.estimated]
    assert [t.as_of_date.year for t in forecast] == [2027, 2028, 2029, 2030]
    assert all(t.low <= t.value <= t.high and "Estimated, year" in t.rationale for t in forecast)
    widths = [t.high - t.low for t in forecast]
    assert widths == sorted(widths) and widths[-1] > widths[0]


def test_red_finding_for_penalized_flag(entity):
    cert = certify(entity, [src(1, 10_000), src(4, 20_000, as_of=None)], lookup_date=LOOKUP)
    r = build_record(cert, lookup_date=LOOKUP)
    red = [f for f in r.findings.items if f.status == "red"]
    assert len(red) == 1 and red[0].category == "corroboration" and red[0].score_impact == -1
    assert any(line.finding_id == red[0].id and line.points == -1 for line in r.confidence.breakdown)


def test_no_source_record_is_complete(entity):
    r = build_record(certify(entity, [], lookup_date=LOOKUP), lookup_date=LOOKUP)
    assert r.headline.count is None and r.headline.none_reason
    assert r.primary_source.none_reason and r.sources.none_reason
    assert CertificationRecord.model_validate(r.model_dump()) == r
