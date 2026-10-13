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
    assert (cert.count_type, cert.qualifier, cert.range) == ("estimated", "approximately", (1_750, 2_250))
    assert cert.confidence_score == 3
    assert cert.adjustments[-1].source_figure == 1_500 and cert.adjustments[-1].result == 2_000
    assert "27% growth" in cert.adjustments[-1].reason


def test_linkedin_within_tolerance_after_adjustment(entity):
    cert = run(entity, src(4, 1_500, as_of=None))
    assert cert.linkedin_check.status == "pass"  # 2,137 members is 7% above 2,000: within tolerance
    assert cert.flags == []


def test_linkedin_flag_not_penalized_when_linkedin_was_an_input(entity):
    far = GROWING.model_copy(update={"member_count": 50_000})  # adjusts to 38,000; members 32% above
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
    assert (cert.certified_count, cert.range, cert.count_type) == (2_200, (1_925, 2_475), "estimated")
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


def test_fast_growing_white_collar_linkedin_is_a_floor_for_weak_estimates(entity):
    """Anthropic-like: data providers only, LinkedIn 5,756 members growing 121% a year. At least 75% of members are
    taken to be current employees, and the estimate moves to the middle of 4,317-5,756."""
    from certifier.models import LinkedInEvidence
    providers = [src(9, v, as_of=date(2026, 9, 1), url=f"https://provider{i}.com/x") for i, v in enumerate((2_300, 3_000, 3_500, 4_100))]
    li = LinkedInEvidence(member_count=5_756, workforce_profile="white_collar", growth_1y=1.21, growth_2y=3.70)
    cert = certify(entity, providers, linkedin=li, lookup_date=date(2026, 10, 13))
    assert (cert.certified_count, cert.range) == (5_470, (4_893, 6_050))  # very strong growth leans forward; range symmetric about the floor
    moderate = certify(entity, providers, linkedin=li.model_copy(update={"growth_1y": 0.30, "growth_2y": 0.70}),
                       lookup_date=date(2026, 10, 13))
    assert moderate.certified_count == 5_040 and moderate.range[0] == 4_317
    assert any("85% of its 5,756 LinkedIn members are taken" in a.reason for a in cert.adjustments)
    flat = certify(entity, providers, linkedin=li.model_copy(update={"growth_1y": 0.02, "growth_2y": 0.03}), lookup_date=date(2026, 10, 13))
    assert flat.certified_count == 5_040  # white-collar: the 75% floor applies against data providers even without growth


def test_the_floor_never_overrides_a_company_document_or_filing(entity):
    from certifier.models import LinkedInEvidence
    li = LinkedInEvidence(member_count=5_756, workforce_profile="white_collar", growth_1y=1.21)
    for tier in (1, 2, 3):
        cert = certify(entity, [src(tier, 3_000, as_of=date(2026, 6, 1))], linkedin=li, lookup_date=date(2026, 10, 13))
        assert cert.certified_count == 3_000, tier


def test_a_stale_linkedin_size_band_never_drags_the_range(entity):
    """Anthropic: LinkedIn's "501-1K" band beside 5,756 members made the certified range 750-6,146."""
    from certifier.models import LinkedInEvidence
    providers = [src(9, v, as_of=date(2026, 9, 1), url=f"https://provider{i}.com/x") for i, v in enumerate((2_300, 3_500, 4_100, 6_110))]
    cert = certify(entity, providers, linkedin=LinkedInEvidence(member_count=5_756, size_range=(501, 1_000), workforce_profile="white_collar"),
                   lookup_date=date(2026, 10, 13))
    assert cert.range[0] >= 2_300 and cert.range[0] <= cert.certified_count <= cert.range[1]
    assert any("size band" in n for n in cert.notes) if hasattr(cert, "notes") else True


def test_the_certified_range_is_reported_the_same_everywhere():
    import io
    import json
    import re
    from pathlib import Path

    from pptx import Presentation

    from certifier import office
    from certifier.export import summary_row
    from certifier.record import record_from_lookup
    from certifier.service import LookupResult
    for f in sorted((Path(__file__).resolve().parents[1] / "samples").glob("*.json")):
        rec = json.loads(record_from_lookup(LookupResult.model_validate_json(f.read_text(encoding="utf-8"))).model_dump_json())
        h = rec["headline"]
        lo, hi = h["range"]
        assert lo <= h["count"] <= hi, f.stem
        row = summary_row(rec)
        assert (row["range_low"], row["range_high"]) == (lo, hi), f.stem
        m = re.search(r"most likely ([\d,]+)–([\d,]+)", h["story"] or "")
        if m:
            assert (int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))) == (lo, hi), f.stem
        if lo != hi:
            prs = Presentation(io.BytesIO(office.deck(rec, "light")))
            text = " ".join(sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame)
            cells = " ".join(c.text for sh in prs.slides[0].shapes if sh.has_table for r in sh.table.rows for c in r.cells)
            assert f"{lo:,}–{hi:,}" in text + cells, f.stem


def _anthropic_oct_2026():
    """The live Anthropic result of 2026-10-13: three Fortune lines (reporter's figures), data providers, 5,680 members."""
    from certifier.models import LinkedInEvidence, Source

    def s(tier, value, when, url, notes=(), q="approximately", restates=False):
        return Source(url=url, tier=tier, value=value, qualifier=q, excerpt=f"{value:,} employees", as_of_date=when,
                      scope="global", basis="headcount", notes=list(notes), restates=restates)
    reporter = ["Reporter's statement, not a direct executive quote."]
    sources = [s(6, 2_500, date(2026, 6, 1), "https://fortune.com/a", reporter, "exact"),
               s(6, 2_500, date(2026, 2, 26), "https://dc.fortune.com/b", ["Journalist's figure, not stated by an executive."], "exact"),
               s(6, 2_500, date(2026, 8, 25), "https://fortune.com/c", ["A floor figure, probably recycled from earlier reporting."], "more_than"),
               s(7, 6_146, date(2026, 9, 26), "https://tracxn.com/anthropic"),
               s(7, 3_950, date(2026, 3, 31), "https://reveliolabs.com/anthropic"),
               s(9, 6_110, date(2026, 10, 5), "https://tipranks.com/anthropic"),
               s(9, 2_300, date(2025, 12, 15), "https://getlatka.com/anthropic", restates=True)]
    return sources, LinkedInEvidence(member_count=5_680, workforce_profile="white_collar")


def test_a_reporters_figure_never_anchors_over_linkedin(entity):
    sources, li = _anthropic_oct_2026()
    cert = certify(entity, sources, linkedin=li, lookup_date=date(2026, 10, 13))
    assert cert.certified_count >= 4_260  # at least 75% of 5,680 members, not the stale 2,500
    assert not any(f.startswith("LinkedIn") for f in cert.flags)  # LinkedIn is the anchor, not a penalty
    assert all(s.tier == 9 for s in cert.sources if "fortune.com" in s.url and "reporter" in " ".join(s.notes).lower()
               or "Journalist" in " ".join(s.notes))


def test_one_publisher_never_corroborates_itself(entity):
    from certifier.models import Source
    a = Source(url="https://fortune.com/a", tier=6, value=2_500, qualifier="exact", excerpt="x", as_of_date=date(2026, 8, 1), scope="global", basis="headcount")
    b = a.model_copy(update={"url": "https://dc.fortune.com/b", "as_of_date": date(2026, 6, 1), "value": 2_520})
    cert = certify(entity, [a, b], lookup_date=date(2026, 10, 13))
    assert not any(s.role == "corroborates" for s in cert.sources)
