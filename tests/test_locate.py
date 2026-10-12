# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Source locations: section, page number, detailed excerpt and deep link (offline)."""

import json
from datetime import date
from pathlib import Path

import pytest

from certifier.locate import edgar_location, filing_pages, locate_sources, text_fragment_link
from certifier.models import Source
from certifier.record import record_errors, record_from_lookup
from certifier.service import LookupResult
from certifier.sources.edgar import Edgar
from certifier.sources.website import readable_tiles

BREAK = '<div style="page-break-after: always"></div>'
FILING = (
    "<p>Table of Contents</p><p>Item 1. Business 4</p><p>Item 1A. Risk Factors 12</p><p>i</p>" + BREAK
    + "<p>PART I</p><p>ITEM 1. BUSINESS</p><p>We make software for customers everywhere.</p><p>4</p>" + BREAK
    + "<p>Human Capital Management</p><p>We invest in our people and culture across the globe.</p>"
      "<p>As of January 31, 2026, we had 83,334 employees.</p><p>None of our U.S. employees are unionized.</p>"
      "<p>Our hiring continued in 2025.</p><p>10</p>" + BREAK
    + "<p>ITEM 1A. RISK FACTORS</p><p>Risks are described below.</p><p>2026</p>"
)
URL = "https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm"


def fake_edgar():
    return Edgar(fetch=lambda url: FILING)


def test_pages_and_printed_numbers():
    pages = filing_pages(FILING)
    assert [p.printed for p in pages] == ["i", "4", "10", None]  # a trailing year is not a page number
    assert [p.index for p in pages] == [1, 2, 3, 4]


def test_edgar_location_section_page_and_passage():
    src = Source(url=URL, tier=1, value=83_334, excerpt="As of January 31, 2026, we had 83,334 employees.")
    loc = edgar_location(fake_edgar(), src)
    assert loc.section == "Item 1. Business › Human Capital Management"
    assert (loc.page, loc.page_basis) == ("10", "printed")
    assert "We invest in our people" in loc.context and "None of our U.S. employees" in loc.context
    assert loc.deep_link.startswith(URL + "#:~:text=")
    assert "printed page 10" in loc.note.lower() or "Printed page 10" in loc.note


def test_located_by_figure_when_quote_differs():
    src = Source(url=URL, tier=1, value=83_334, excerpt="Salesforce employed 83,334 people (paraphrased)")
    assert edgar_location(fake_edgar(), src).page == "10"


def test_unprinted_page_falls_back_to_html_position():
    html = "<p>ITEM 6. DIRECTORS AND EMPLOYEES</p><p>We reduced the number of employees to 69,505 by year-end.</p>"
    src = Source(url=URL, tier=1, value=69_505, excerpt="reduced the number of employees to 69,505 by year-end")
    loc = edgar_location(Edgar(fetch=lambda u: html), src)
    assert (loc.page, loc.page_basis) == ("1", "html_page") and "No printed page number" in loc.note


def test_text_fragment_link_encodes_commas_and_hyphens():
    link = text_fragment_link("https://example.com/a#old", "reducing the number of employees to 69,505 by year-end")
    assert link == ("https://example.com/a#:~:text=reducing%20the%20number%20of%20employees%20to%2069%2C505"
                    "%20by%20year%2Dend")
    assert text_fragment_link("https://example.com", "1,500 Employees") is None  # too short to be unique


def test_unlocated_source_gets_an_explicit_note():
    [s] = locate_sources([Source(url="https://example.com/news", tier=3, value=9, excerpt="We have 9 staff now.")])
    assert s.location.note == "Section and page were not captured for this source."
    assert s.location.context == "We have 9 staff now."


def test_readable_tiles_from_embedded_page_data():
    raw = 'description : Customers , prefix :null, suffix :null, value : 5,000 , animateNumber :true, ' \
          'description : Employees , prefix :null, suffix :null, value : 1,500'
    assert readable_tiles(raw) == "Statistics shown on the page: Customers: 5,000; Employees: 1,500."


# --- Record validation ----------------------------------------------------------------------

FIXTURES = {p.stem: p for p in (Path(__file__).parent / "fixtures" / "lookups").glob("*.json")}


def record(stem: str) -> dict:
    result = LookupResult.model_validate_json(FIXTURES[stem].read_text(encoding="utf-8"))
    return json.loads(record_from_lookup(result).model_dump_json())


def test_salesforce_primary_source_location():
    p = record("salesforce")["primary_source"]
    assert p["url"].startswith("https://www.sec.gov/") and p["excerpt"]
    loc = p["location"]
    assert loc["section"] == "Item 1. Business › Human Capital Management"
    assert loc["page_label"] == "printed page 10"
    assert "83,334" in loc["detailed_excerpt"] and len(loc["detailed_excerpt"]) > len(p["excerpt"])
    assert loc["deep_link"].startswith(p["url"] + "#:~:text=")


def test_form_990_primary_source_location():
    primary = record("donor-network-west")["primary_source"]
    loc = primary["location"]
    assert loc["section"] == "Form 990 › Part I (Summary) › line 5" and loc["page_label"] == "Form page 1"
    assert primary["excerpt"] in loc["detailed_excerpt"]  # the verbatim quote can be highlighted
    assert "Part V, line 2a" in loc["note"]


def test_red_finding_titles_do_not_show_urls():
    for stem in FIXTURES:
        for f in record(stem)["findings"]["items"]:
            assert "http" not in f["title"], (stem, f["title"])


@pytest.mark.parametrize("stem", sorted(FIXTURES))
def test_every_source_has_url_passage_and_explained_location(stem):
    for s in record(stem)["sources"]["items"]:
        assert s["url"].startswith("http")
        loc = s["location"]
        assert loc["detailed_excerpt"].strip()
        if loc["section"] is None or loc["page"] is None:
            assert loc["note"], (stem, s["id"])


def test_missing_url_fails_validation():
    r = record("salesforce")
    r["sources"]["items"][0]["url"] = ""
    assert any("url" in e.lower() for e in record_errors(r))


def test_primary_without_location_fails_validation():
    r = record("salesforce")
    r["primary_source"]["location"] = None
    assert any("location" in e for e in record_errors(r))


def test_missing_page_without_note_fails_validation():
    r = record("salesforce")
    r["primary_source"]["location"]["page"] = None
    r["primary_source"]["location"]["note"] = None
    assert any("note saying why" in e for e in record_errors(r))
