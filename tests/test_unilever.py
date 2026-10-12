# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Unilever FY2025: the total-organisation figure must win. The 20-F states it as a stat tile ("96,000 people who
work for Unilever") and in Total Headcount tables (96,092), both of which arrive as one-cell fragments; the only
full sentence with a figure is a wellness programme's reach ("more than 59,000 employees")."""

import re
from datetime import date

from certifier import certify
from certifier.figures import parse_figure
from certifier.heuristic import best_per_filing, snippet_sources
from certifier.models import Entity
from certifier.record import TrendRow, _forecast
from certifier.sources.edgar import Company, Filing, Snippet, employee_snippets, html_to_text

from .conftest import src

UL_HTML = """<html><body>
<div>PEOPLE</div><div>Global talent</div><div>Global talent pool</div><div>Employee satisfaction</div>
<div>96,000</div><div>people who</div><div>work for Unilever</div><div>84 %</div><div>satisfied with Unilever</div>
<p>Unilever’s global Healthier U initiative now reaches more than 59,000 employees across 56 countries and is
delivering independently validated gains in overall health, quality of life and reduced time away from work.</p>
<p>The productivity programme is being implemented with care for the 7,500 mostly office-based employees whose roles
are impacted.</p>
<table><tr><td>Employee headcount by geography</td><td>2025</td><td>2024</td></tr>
<tr><td>Asia Pacific Africa</td><td>49,891</td><td>58,026</td></tr>
<tr><td>The Americas</td><td>29,315</td><td>37,304</td></tr>
<tr><td>Europe</td><td>16,886</td><td>24,710</td></tr>
<tr><td>Total Headcount (a)</td><td>96,092</td><td>120,040</td></tr></table>
<div>4</div><div>Employees</div><div>4A</div><div>STAFF AND MANAGEMENT COSTS</div><div>Wages and salaries</div><div>( 5,433 )</div>
<p>Option A was used to calculate the pay and benefits of the 25th percentile, median and 75th percentile UK employees.</p>
</body></html>"""
FILING = Filing(company=Company(cik=217410, name="UNILEVER PLC", ticker="UL"), form="20-F",
                filed=date(2026, 3, 10), period=date(2025, 12, 31),
                url="https://www.sec.gov/Archives/edgar/data/217410/000021741026000007/ul-20251231.htm")


def snippets():
    return [Snippet(FILING, t) for t in employee_snippets(html_to_text(UL_HTML))]


def test_tables_and_stat_tiles_reach_extraction_as_one_snippet():
    texts = [s.text for s in snippets()]
    assert any(re.search(r"Total Headcount \(a\)\W+96,092\W+120,040", t) for t in texts)
    assert any("96,000" in t and "work for Unilever" in t for t in texts)


def test_programme_reach_and_restructuring_counts_are_not_the_workforce():
    values = {s.value: s.scope for s in snippet_sources(snippets())}
    assert 59_000 not in values and 7_500 not in values
    assert values[96_092] == "global" and values[96_000] == "global"
    assert 4 not in values and 75 not in values  # a note number, a percentile


def test_the_filing_certifies_its_total_headcount():
    [pick] = best_per_filing(snippets())
    assert (pick.value, pick.as_of_date) == (96_092, date(2025, 12, 31))


def test_note_numbers_ordinals_and_zero_are_not_headcounts():
    assert parse_figure("4 · Employees · 4A") is None
    assert parse_figure("the 75th percentile UK employees") is None
    assert parse_figure("Board 5 7 0 employees") is None or parse_figure("Board 5 7 0 employees").value != 0


def test_trend_leaves_out_implausible_prior_years_and_takes_each_years_total():
    def sec(value, year):
        return src(1, value, as_of=date(year, 12, 31), document_type="20-F",
                   url=f"https://www.sec.gov/Archives/edgar/data/217410/0000217410{year % 100:02d}000007/ul-{year}1231.htm")
    sources = [sec(96_092, 2025), sec(120_040, 2024), sec(44_313, 2024), sec(75, 2023), sec(127_000, 2022),
               sec(148_000, 2021)]
    cert = certify(Entity(name="Unilever PLC"), sources, lookup_date=date(2026, 10, 12))
    assert cert.certified_count == 96_092
    assert [(p.as_of_date.year, p.value) for p in cert.trend] == [(2021, 148_000), (2022, 127_000), (2024, 120_040),
                                                                  (2025, 96_092)]


def test_forecast_after_a_divestment_never_goes_negative():
    years = [(2021, 148_000), (2022, 127_000), (2023, 128_000), (2024, 120_040), (2025, 96_092)]
    rows = [TrendRow(as_of_date=date(y, 12, 31), value=v, tier=1, url=None, estimated=False, rationale="Reported in the annual filing.") for y, v in years]
    forecast = _forecast(rows)
    assert len(forecast) == 4
    assert all(0 < f.low <= f.value <= f.high for f in forecast)
    assert forecast[-1].value >= round(96_092 * 0.85 ** 4)  # at most 15% a year down


def test_table_quotes_are_located_and_linked_cell_to_cell():
    from certifier.locate import _find, _printed_number, filing_pages, text_fragment_link
    pages = filing_pages('<div style="content-visibility:auto;height:595pt">Unilever Annual Report on Form 20-F 2025 . 3 . '
                         '<p>96,000</p><p>people who</p><p>work for Unilever</p></div>'
                         '<div style="content-visibility:auto;height:595pt">Unilever Annual Report on Form 20-F 2025 . 47 . '
                         '<p>Total Headcount (a)</p><p>96,092</p><p>120,040</p></div>')
    assert [p.printed for p in pages] == ["3", "47"]
    assert _find(pages, "Total Headcount (a) · 96,092 · 120,040", 96_092)[0] == 1
    url = "https://www.sec.gov/Archives/edgar/data/217410/x/ul-20251231.htm"
    assert text_fragment_link(url, "Total Headcount (a) · 96,092 · 120,040", 96_092).endswith(
        "#:~:text=Total%20Headcount%20%28a%29,96%2C092")
    assert text_fragment_link(url, "96,000 . people who . work for Unilever", 96_000).endswith("#:~:text=96%2C000,people%20who")
    assert _printed_number("Some page text that ends with a page number 12") == "12"


def test_deck_shows_placeholder_years_when_history_is_missing():
    import io
    import json as _json
    from pathlib import Path as _Path

    from pptx import Presentation

    from certifier import office
    from certifier.record import record_from_lookup
    from certifier.service import LookupResult
    raw = (_Path(__file__).resolve().parents[1] / "samples" / "stripe.json").read_text(encoding="utf-8")
    rec = _json.loads(record_from_lookup(LookupResult.model_validate_json(raw)).model_dump_json())
    prs = Presentation(io.BytesIO(office.deck(rec, "dark")))
    chart = next(sh.chart for sh in prs.slides[1].shapes if sh.has_chart)
    names = [s.name for s in chart.plots[0].series]
    assert "No reported figure" in names and len(list(chart.plots[0].categories)) == 9


def test_short_history_still_gets_a_best_guess_forecast():
    from certifier.models import LinkedInCheck
    from certifier.record import _short_forecast
    point = [TrendRow(as_of_date=date(2026, 10, 12), value=10_000, tier=4, url=None, estimated=False,
                      rationale="The certified figure, shown at the certification date.")]
    level = _short_forecast(point, None)
    assert [f.value for f in level] == [10_000] * 4 and all(f.low < f.value < f.high for f in level)
    widths = [f.high - f.low for f in level]
    assert widths == sorted(widths) and "level" in level[0].rationale
    li = LinkedInCheck(member_count=5_974, size_range=None, workforce_profile="blue_collar", implied_range=None,
                       size_range_agrees=None, status="pass", note="Pass.", growth_1y=0.19)
    grown = _short_forecast(point, li)
    assert grown[0].value == 10_950 and "half of LinkedIn's +19%" in grown[0].rationale


def test_an_undated_certified_figure_is_still_charted():
    from certifier.record import build_record
    cert = certify(Entity(name="M. A. Mortenson Company"),
                   [src(4, 10_000, as_of=None, qualifier="more_than", url="https://www.mortenson.com/careers")],
                   lookup_date=date(2026, 10, 12))
    rec = build_record(cert, lookup_date=date(2026, 10, 12))
    items = rec.trend.items
    assert items[0].as_of_date == date(2026, 10, 12) and not items[0].estimated and "undated" in items[0].rationale
    assert sum(t.estimated for t in items) == 4


def test_private_companies_get_context_for_their_score():
    from certifier.record import private_company_note
    site = [src(4, 1_500, as_of=None, url="https://www.gong.io/about")]
    three = certify(Entity(name="Gong"), site, lookup_date=date(2026, 10, 12))
    assert three.confidence_score == 2 or private_company_note(three)[0] in (None, "strong")
    strong = three.model_copy(update={"confidence_score": 3})
    rare = three.model_copy(update={"confidence_score": 4})
    assert private_company_note(strong)[0] == "strong" and "4-5 is rare" in private_company_note(strong)[1]
    assert private_company_note(rare)[0] == "rare" and "Worth celebrating" in private_company_note(rare)[1]
    filed = certify(Entity(name="Salesforce"), [src(1, 83_334)], lookup_date=date(2026, 10, 12))
    assert private_company_note(filed) == (None, None)  # a public filer gets no private-company note


def test_an_older_company_statement_becomes_a_historical_estimate_and_leans_the_forecast():
    from certifier.record import build_record
    careers = src(4, 10_000, as_of=date(2026, 8, 15), qualifier="more_than", url="https://www.mortenson.com/careers")
    ceo = src(5, 7_000, as_of=date(2019, 6, 1), url="https://www.linkedin.com/company/mortenson")
    provider = src(9, 6_500, as_of=date(2021, 3, 1), url="https://leadiq.com/c/mortenson")  # data providers never count
    cert = certify(Entity(name="M. A. Mortenson Company"), [careers, ceo, provider], lookup_date=date(2026, 10, 12))
    items = build_record(cert, lookup_date=date(2026, 10, 12)).trend.items
    history = [t for t in items if t.historical]
    assert [(t.as_of_date.year, t.value) for t in history] == [(2019, 7_000)]
    forecast = [t for t in items if t.estimated]
    yearly = (forecast[-1].value / 10_000) ** (1 / 4) - 1
    assert 0.01 < yearly <= 0.03 and "historical estimate" in forecast[0].rationale  # a gentle, capped lean
