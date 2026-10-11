"""EDGAR client and heuristic extraction, offline with a fake fetcher (real filing excerpts)."""

import json
from datetime import date

from certifier import Entity, certify
from certifier.heuristic import best_per_filing, snippet_sources
from certifier.sources.edgar import Company, Edgar, Filing, Snippet, employee_snippets, html_to_text

from .conftest import LOOKUP

TICKERS = {"0": {"cik_str": 753308, "ticker": "NEE", "title": "NEXTERA ENERGY INC"},
           "1": {"cik_str": 1000184, "ticker": "SAP", "title": "SAP SE"},
           "2": {"cik_str": 99, "ticker": "NEEX", "title": "NEXTERA SOMETHING ELSE CORP"}}
SUBMISSIONS = {"name": "NEXTERA ENERGY INC", "tickers": ["NEE"], "filings": {"recent": {
    "form": ["8-K", "10-K", "10-K/A", "10-K"],
    "accessionNumber": ["0000-26-1", "0000753308-26-000015", "0000-25-9", "0000753308-25-000010"],
    "primaryDocument": ["x.htm", "nee-20251231.htm", "y.htm", "nee-20241231.htm"],
    "filingDate": ["2026-03-01", "2026-02-13", "2025-06-01", "2025-02-14"],
    "reportDate": ["", "2025-12-31", "2024-12-31", "2024-12-31"]}}}
NEE_HTML = """<html><body><p>Revenue grew 12% to $4,388 million in 2025.</p>
<p>NEE and its subsidiaries, with employees totaling approximately 17,400 as of December 31, 2025, continue to
develop enterprise-wide initiatives.</p>
<div>FPL HUMAN CAPITAL</div><p>FPL had approximately 9,400 employees as of December 31, 2025, with approximately
30% of these employees represented by the International Brotherhood of Electrical Workers (IBEW).</p>
<p>NEER had approximately 7,900 employees as of December 31, 2025.</p></body></html>"""


def fake_fetch(url):
    if url.endswith("company_tickers.json"):
        return json.dumps(TICKERS)
    if "submissions" in url:
        return json.dumps(SUBMISSIONS)
    return NEE_HTML


def test_find_companies_ticker_first_then_name():
    edgar = Edgar(fetch=fake_fetch)
    assert [c.ticker for c in edgar.find_companies("nee")] == ["NEE"]
    assert [c.ticker for c in edgar.find_companies("NextEra")] == ["NEE", "NEEX"]
    assert edgar.find_companies("zzz unknown") == []


def test_annual_filings_newest_first_without_amendments():
    edgar = Edgar(fetch=fake_fetch)
    filings = edgar.annual_filings(Company(753308, "NEXTERA ENERGY INC", "NEE"), limit=3)
    assert [(f.form, f.period) for f in filings] == [("10-K", date(2025, 12, 31)), ("10-K", date(2024, 12, 31))]
    assert filings[0].url.endswith("/753308/000075330826000015/nee-20251231.htm")


def test_snippets_keep_employee_sentences_with_numbers():
    text = html_to_text(NEE_HTML)
    snippets = employee_snippets(text)
    assert any("17,400" in s for s in snippets)
    assert not any("4,388" in s for s in snippets)


FILING = Filing(Company(753308, "NEXTERA ENERGY INC", "NEE"), "10-K", date(2026, 2, 13), date(2025, 12, 31),
                "https://www.sec.gov/nee-10k")


def test_subsidiary_and_union_clauses_are_partial():
    edgar = Edgar(fetch=fake_fetch)
    sources = snippet_sources(edgar.snippets(FILING))
    scopes = {s.value: s.scope for s in sources}
    assert scopes[17_400] == "global"
    assert scopes[9_400] == "partial"   # "FPL had ..." is a subsidiary
    assert scopes[7_900] == "partial"   # "NEER had ..."
    assert all(s.as_of_date == date(2025, 12, 31) for s in sources)


def test_best_per_filing_picks_group_total():
    edgar = Edgar(fetch=fake_fetch)
    [best] = best_per_filing(edgar.snippets(FILING))
    assert (best.value, best.qualifier) == (17_400, "approximately")


def snip(text, period=date(2025, 12, 31), company=Company(1, "NOVO NORDISK A S", "NVO")):
    return Snippet(Filing(company, "20-F", date(2026, 2, 4), period, "https://www.sec.gov/nvo-20f"), text)


def test_novo_exact_figure_beats_rounded_and_ignores_layoffs():
    snippets = [
        snip("Headquartered in Denmark, Novo Nordisk employs more than 69,500 employees in around 80 countries."),
        snip("As part of the transformation around 9,000 employees were let go globally."),
        snip("Novo Nordisk's research and development organisation is comprising more than 10,000 employees."),
        snip("reducing the number of employees to 69,505 by year-end equal to 10% reduction."),
    ]
    [best] = best_per_filing(snippets)
    assert (best.value, best.qualifier) == (69_505, "exact")


def test_department_fte_figure_is_partial():
    s = snip("At the end of 2025, our total full-time equivalent (FTE) headcount in development was 37,965.",
             company=Company(2, "SAP SE", "SAP"))
    [source] = snippet_sources([s])
    assert source.scope == "partial" and source.basis == "fte"


def test_as_of_from_text_else_period():
    [a] = snippet_sources([snip("As of November 28, 2025, we employed 31,360 people.")])
    assert a.as_of_date == date(2025, 11, 28)
    [b] = snippet_sources([snip("At the end of 2026, we employed 355,000 employees worldwide.", period=date(2026, 8, 30))])
    assert b.as_of_date == date(2026, 8, 30)


def test_prior_filings_corroborate():
    snippets = [snip("we employed 31,360 people.", period=date(2025, 11, 28)),
                Snippet(Filing(Company(1, "ADOBE INC.", "ADBE"), "10-K", date(2025, 1, 15), date(2024, 11, 29),
                               "https://www.sec.gov/adbe-2024"), "we employed 30,709 people.")]
    cert = certify(Entity(name="Adobe"), best_per_filing(snippets), lookup_date=LOOKUP)
    assert (cert.certified_count, cert.confidence_score) == (31_360, 5)
