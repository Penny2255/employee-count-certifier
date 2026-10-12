# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Scoring fixes from the Stripe run: estimated as-of dates, corroboration measured from the anchor,
recency penalty for every tier, known changes after the as-of date, and the indicated current range."""

from datetime import date

from certifier import certify
from certifier.models import Event, LinkedInEvidence
from certifier.record import build_record

from .conftest import LOOKUP, src

ARTICLE = "https://www.paymentsdive.com/news/stripe-employees-workforce-cuts-additions/737935/"


def stripe_sources():
    # Tier 6: a spokesperson quoted in an article published January 2025, with no stated as-of date.
    anchor = src(6, 8_500, as_of=None, published_date=date(2025, 1, 22), url=ARTICLE,
                 excerpt="Stripe has about 8,500 employees, a spokesperson said.")
    revelio_q1 = src(7, 9_383, qualifier="approximately", as_of=date(2026, 3, 1), url="https://www.reveliolabs.com/q1")
    pitchbook = src(8, 10_000, qualifier="approximately", as_of=date(2026, 6, 30), url="https://pitchbook.com/stripe")
    return [anchor, revelio_q1, pitchbook]


def test_rule1_undated_anchor_gets_estimated_as_of():
    cert = certify(_stripe(), stripe_sources(), lookup_date=LOOKUP)
    assert (cert.as_of_date, cert.as_of_estimated) == (date(2025, 1, 22), True)
    anchor = next(s for s in cert.sources if s.role == "selected")
    assert anchor.as_of_basis == "publication date 2025-01-22"


def test_rule1_research_estimate_is_kept():
    from certifier.research import XSource, to_source
    x = XSource(url=ARTICLE, tier=6, value=8_500, qualifier="approximately", basis="headcount", scope="global",
                as_of_date=None, as_of_estimate=date(2025, 2, 15), as_of_estimate_basis="says 'as of early 2025'",
                published_date=date(2025, 3, 1), modified_date=None, restates=False, predates_change=False,
                excerpt="about 8,500 employees",
                context="about 8,500 employees", section=None, page_number=None, contractors_included=None,
                separately_reported=[], note="", document_type="News")
    s = to_source(x)
    assert s.document_type == "news"
    assert (s.as_of_date, s.as_of_estimated, s.as_of_basis) == (date(2025, 2, 15), True, "says 'as of early 2025'")


def test_rule2_corroboration_measured_from_estimated_anchor_date():
    cert = certify(_stripe(), stripe_sources(), lookup_date=LOOKUP)
    # Revelio (Mar 2026) is 13 months from the anchor's estimated Jan 2025 date: not near, no bonus.
    assert not [s for s in cert.sources if s.role == "corroborates"]
    assert all("corroborated" not in st.reason for st in cert.confidence_breakdown)


def test_rule2_anchor_with_no_date_gets_no_bonus_for_any_source():
    sources = [src(4, 1_500, as_of=None, url="https://example.com/about"),
               src(6, 1_520, as_of=date(2026, 9, 1), url="https://news.example.com/a"),
               src(7, 1_480, as_of=date(2026, 9, 1), url="https://data.example.com/b")]
    cert = certify(_stripe(), sources, lookup_date=LOOKUP)
    assert cert.confidence_score == 2
    assert all("no as-of date" in s.role_reason for s in cert.sources if s.role != "selected")


def test_rule3_recency_penalty_for_old_secondary_anchor_and_stripe_scores_1():
    li = LinkedInEvidence(member_count=16_924, workforce_profile="white_collar")
    cert = certify(_stripe(), stripe_sources(), linkedin=li, lookup_date=LOOKUP)
    reasons = [(st.points, st.reason) for st in cert.confidence_breakdown]
    assert reasons[0] == (2, "base 2: tier 6 secondary source")
    assert reasons[1] == (-1, "recency: as of 2025-01-22 (estimated) is older than 18 months")
    assert cert.confidence_score == 1


def test_rule3_recency_finding_score_impact_matches():
    r = build_record(certify(_stripe(), stripe_sources(), lookup_date=LOOKUP), lookup_date=LOOKUP)
    line = next(l for l in r.confidence.breakdown if l.rationale.startswith("recency:"))
    finding = next(f for f in r.findings.items if f.id == line.finding_id)
    assert (finding.category, finding.status, finding.score_impact, line.points) == ("recency", "red", -1, -1)


def test_rule3_old_primary_still_scores_3(entity):
    assert certify(entity, [src(1, 10_000, as_of=date(2024, 6, 30))], lookup_date=LOOKUP).confidence_score == 3


def test_rule4_known_change_after_as_of_labels_pre_adjustment():
    layoff = Event(description="Stripe cut about 300 jobs", url="https://news.example.com/cuts",
                   close_date=date(2025, 3, 1), kind="layoff", headcount_change=-300, material=False)
    cert = certify(_stripe(), stripe_sources(), lookup_date=LOOKUP, events=[layoff])
    assert cert.pre_adjustment and not [f for f in cert.flags if f.startswith("Event")]
    r = build_record(cert, lookup_date=LOOKUP)
    assert r.headline.adjustment_status == "pre-adjustment"
    assert r.headline.known_changes == ["Stripe cut about 300 jobs (2025-03-01, -300)"]


def test_rule4_material_change_after_as_of_lowers_confidence_for_secondary_anchor(entity):
    deal = Event(description="Merger with Target Co", url="https://news.example.com/deal", close_date=date(2026, 5, 1),
                 kind="merger", material=True)
    cert = certify(entity, [src(3, 10_000, as_of=date(2026, 1, 31))], lookup_date=LOOKUP, events=[deal])
    assert cert.pre_adjustment and cert.confidence_score == 2


def test_rule4_change_before_as_of_is_not_pre_adjustment():
    earlier = Event(description="Layoff", url="https://news.example.com/x", close_date=date(2024, 11, 1), kind="layoff")
    cert = certify(_stripe(), stripe_sources(), lookup_date=LOOKUP, events=[earlier])
    assert not cert.pre_adjustment


def test_rule5_indicated_current_range_from_newer_providers():
    cert = certify(_stripe(), stripe_sources(), lookup_date=LOOKUP)
    assert cert.certified_count == 8_500  # never overridden
    ir = cert.indicated_range
    assert (ir.low, ir.high, ir.earliest, ir.latest) == (9_383, 10_000, date(2026, 3, 1), date(2026, 6, 30))
    r = build_record(cert, lookup_date=LOOKUP)
    assert r.headline.indicated_current_range.low == 9_383
    assert any(f.title.startswith("Newer data indicates") for f in r.findings.items)


def test_rule5_no_range_when_anchor_is_recent_or_data_agrees(entity):
    recent = [src(6, 8_500, as_of=date(2026, 6, 1)), src(7, 9_400, as_of=date(2026, 9, 1), url="https://r")]
    assert certify(entity, recent, lookup_date=LOOKUP).indicated_range is None
    agrees = [src(6, 8_500, as_of=date(2024, 12, 1)), src(7, 8_600, as_of=date(2026, 9, 1), url="https://r")]
    assert certify(entity, agrees, lookup_date=LOOKUP).indicated_range is None


def _stripe():
    from certifier import Entity
    return Entity(name="Stripe, Inc.", website="https://stripe.com")


def test_estimated_as_of_never_after_publication(entity):
    future = src(6, 10_000, as_of=None, published_date=date(2025, 1, 22), url="https://news.example.com/plan")
    future = future.model_copy(update={"as_of_date": date(2025, 12, 31), "as_of_estimated": True,
                                       "as_of_basis": "target for end of 2025"})
    cert = certify(entity, [future], lookup_date=LOOKUP)
    assert cert.as_of_date == date(2025, 1, 22)
    assert any("capped" in n for n in cert.sources[0].notes)


def test_stated_small_change_is_not_material(entity):
    # Salesforce rerun: about 1,000 layoffs after the as-of date against 83,334 (1.2%).
    layoffs = Event(description="February 2026 layoffs", url="https://news.example.com/l", close_date=date(2026, 2, 1),
                    kind="layoff", headcount_change=-1_000, material=True)
    cert = certify(entity, [src(1, 83_334, as_of=date(2026, 1, 31))], lookup_date=LOOKUP, events=[layoffs])
    # A tier 1 figure stands: no relabel, no penalty; the change only feeds the directional guidance.
    assert not cert.pre_adjustment and cert.confidence_score == 4 and cert.flags == []
    assert cert.direction.direction == "lower"
    assert cert.direction.reason == "Likely somewhat lower than reported because of a change after the as-of date: February 2026 layoffs (2026-02-01, -1,000)."


def test_indicated_range_leaves_out_outliers():
    sources = stripe_sources() + [src(9, 16_918, as_of=date(2026, 5, 1), url="https://leadiq.com/stripe"),
                                  src(9, 8_000, as_of=date(2026, 4, 1), url="https://datanyze.com/stripe")]
    ir = certify(_stripe(), sources, lookup_date=LOOKUP).indicated_range
    assert (ir.low, ir.high) == (8_000, 10_000)
    assert "1 outlier(s) left out" in ir.reason
