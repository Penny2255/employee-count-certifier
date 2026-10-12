# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Engine tweaks: URL dates, post-date changes by anchor tier, directional guidance, scope notes."""

from datetime import date

from certifier import certify
from certifier.models import Event
from certifier.record import build_record

from .conftest import LOOKUP, src

DNW_PDF = "https://www.donornetworkwest.org/wp-content/uploads/2023/03/Sponsorship_Packet_2023-FINAL-Reduced-Size.pdf"


def test_url_date_is_lowest_priority_estimate(entity):
    undated = src(3, 300, as_of=None, url=DNW_PDF)
    cert = certify(entity, [src(2, 513, as_of=date(2024, 12, 31), url="https://example.com/990"), undated],
                   lookup_date=LOOKUP)
    pdf = next(s for s in cert.sources if s.url == DNW_PDF)
    assert (pdf.as_of_date, pdf.as_of_estimated, pdf.as_of_from_url) == (date(2023, 3, 1), True, True)
    assert "URL" in pdf.as_of_basis
    # Now dated 2023-03 it is stale, so it no longer counts as a current conflict (Donor Network West).
    assert cert.flags == [] and cert.confidence_score == 3


def test_published_date_beats_url_date(entity):
    s = src(3, 300, as_of=None, published_date=date(2025, 6, 1), url=DNW_PDF)
    cert = certify(entity, [s], lookup_date=LOOKUP)
    assert cert.sources[0].as_of_date == date(2025, 6, 1) and not cert.sources[0].as_of_from_url


def test_url_dated_anchor_is_shown_as_estimated_from_url(entity):
    recent = "https://news.example.com/2025/03/team-update"  # within 24 months, so it can be the anchor
    cert = certify(entity, [src(3, 300, as_of=None, url=recent)], lookup_date=LOOKUP)
    r = build_record(cert, lookup_date=LOOKUP)
    assert r.headline.as_of_estimated_from == "url"
    assert any(f.title.startswith("As-of date estimated from the URL") for f in r.findings.items)


def test_secondary_anchor_that_says_it_predates_a_change_is_pre_adjustment(entity):
    stripe = src(6, 8_500, as_of=None, published_date=date(2025, 1, 22), url="https://news.example.com/stripe",
                 predates_change=True)
    cert = certify(entity, [stripe], lookup_date=LOOKUP)
    assert cert.pre_adjustment and cert.direction.direction == "lower"


def test_primary_anchor_is_never_pre_adjustment_even_if_source_says_so(entity):
    cert = certify(entity, [src(1, 10_000, predates_change=True)], lookup_date=LOOKUP)
    assert not cert.pre_adjustment


def test_directional_guidance_from_trend(entity):
    filings = [src(1, 30_000, as_of=date(2024, 11, 29)), src(1, 31_360, as_of=date(2025, 11, 28))]
    d = certify(entity, filings, lookup_date=LOOKUP).direction
    assert d.direction == "higher" and "30,000 to 31,360" in d.reason
    flat = [src(1, 31_000, as_of=date(2024, 11, 29)), src(1, 31_360, as_of=date(2025, 11, 28))]
    assert certify(entity, flat, lookup_date=LOOKUP).direction.direction == "in_line"


def test_directional_guidance_unknown_without_evidence(entity):
    assert certify(entity, [src(1, 10_000)], lookup_date=LOOKUP).direction.direction == "unknown"


def test_hiring_after_as_of_points_higher(entity):
    hiring = Event(description="Announced hiring of 2,000 engineers", url="https://news.example.com/h",
                   close_date=date(2026, 6, 1), kind="hiring", headcount_change=2_000)
    cert = certify(entity, [src(1, 10_000, as_of=date(2026, 1, 31))], lookup_date=LOOKUP, events=[hiring])
    assert cert.direction.direction == "higher" and cert.confidence_score == 4


def test_scope_note_is_yellow_with_no_score_impact(entity):
    cert = certify(entity, [src(1, 10_000)], lookup_date=LOOKUP, scope_notes=["Tracker estimates disagree."])
    assert cert.confidence_score == 4 and cert.flags == []
    r = build_record(cert, lookup_date=LOOKUP)
    note = next(f for f in r.findings.items if f.category == "scope")
    assert (note.status, note.score_impact) == ("yellow", 0)


def test_entity_changing_scope_question_is_still_a_red_flag(entity):
    cert = certify(entity, [src(1, 10_000)], lookup_date=LOOKUP,
                   review_flags=["Affiliated health system may or may not be included"])
    assert cert.confidence_score == 3


def test_extraction_splits_complexities_by_kind():
    from certifier.research import ENTITY_CHANGING, XComplexity
    items = [XComplexity(description="Health system may be excluded", kind="health_system"),
             XComplexity(description="Trackers disagree", kind="other")]
    assert [c.kind in ENTITY_CHANGING for c in items] == [True, False]


def test_subsidiary_question_is_a_note_when_anchored_on_a_consolidated_filing(entity):
    q = "Informatica appears to have been acquired; unclear whether its employees are included."
    cert = certify(entity, [src(1, 83_334)], lookup_date=LOOKUP, subsidiary_questions=[q])
    assert cert.confidence_score == 4 and cert.flags == []
    assert cert.scope_notes[0].startswith("Informatica") and "consolidated annual filing" in cert.scope_notes[0]


def test_subsidiary_question_is_a_flag_below_tier_1(entity):
    cert = certify(entity, [src(2, 5_000)], lookup_date=LOOKUP, subsidiary_questions=["Subsidiary may be excluded"])
    assert cert.flags == ["Complexity: Subsidiary may be excluded"] and cert.scope_notes == []


def test_one_value_indicated_range_reads_as_about(entity):
    newer = src(7, 438, as_of=date(2026, 3, 1), url="https://www.zoominfo.com/c/x")
    d = certify(entity, [src(2, 513, as_of=date(2024, 12, 31)), newer], lookup_date=LOOKUP).direction
    assert d.direction == "lower" and "about 438 (2026-03-01)" in d.reason
