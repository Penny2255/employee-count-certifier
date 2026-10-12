# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Careers and About pages (the Mortenson case): "10,000+ team members" on /careers is a whole-company headcount."""

from certifier.sources import website
from certifier.sources.website import _links, stat_snippets
from certifier.taxonomy import classify

from .conftest import src

TILES = """<div class="stat-card"><p>12</p><p>regional offices across the US</p></div>
<div class="stat-card"><p>10,000+</p><p>team members</p></div>
<div class="stat-card"><p>35</p><p>best workplace awards (last 5 years)</p></div>"""


def test_a_plus_tile_keeps_its_plus_and_never_borrows_the_next_tiles_number():
    figures = [s.split(" (")[0] for s in stat_snippets(TILES)]
    assert figures == ["10,000+ Team members"]


def test_homepage_links_to_careers_and_about_pages_are_followed(monkeypatch):
    home = '<a href="/about">About</a><a href="/careers">Careers</a><a href="https://other.com/careers">x</a><a href="/projects">P</a>'
    assert _links(home, "https://www.mortenson.com") == ["https://www.mortenson.com/about", "https://www.mortenson.com/careers"]
    pages = {"https://www.mortenson.com": home, "https://www.mortenson.com/careers": TILES}
    monkeypatch.setattr(website, "_get", lambda url, ua: pages.get(url))
    found = website.website_snippets("https://www.mortenson.com")
    assert [(s.figure, s.url) for s in found] == [("10,000+ Team members", "https://www.mortenson.com/careers")]


def test_a_careers_page_is_its_own_source_type():
    careers = src(4, 10_000, as_of=None, url="https://www.mortenson.com/careers")
    assert classify(careers) == ("Company Website", "Website: Careers Page")
    labelled = careers.model_copy(update={"document_type": "website_other"})
    assert classify(labelled)[1] == "Website: Careers Page"  # the URL wins over a generic label
