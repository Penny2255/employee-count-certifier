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
