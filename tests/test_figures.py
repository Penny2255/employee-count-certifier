# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
import pytest

from certifier.figures import Figure, parse_figure

# Real excerpts from the proposed golden set filings (SPEC.md).
GOLDEN_EXCERPTS = [
    ("As of November 28, 2025, we employed 31,360 people, of which 50% were in the United States",
     Figure(31_360, "exact")),
    ("As of September 27, 2025, we employed approximately 133,000 team members globally.",
     Figure(133_000, "approximately")),
    ("The SAP Group has a global presence and employed more than 110,000 people as at December 31, 2025.",
     Figure(110_000, "more_than")),
    ("reducing the number of employees to 69,505 by year-end equal to 10% reduction",
     Figure(69_505, "exact")),
    ("Novo Nordisk employs more than 69,500 employees in around 80 countries",
     Figure(69_500, "more_than")),
    ("FPL had approximately 9,400 employees as of December 31, 2025",
     Figure(9_400, "approximately")),
    ("NEE and its subsidiaries, with employees totaling approximately 17,400 as of December 31, 2025",
     Figure(17_400, "approximately")),
    ("At the end of 2026, we employed 355,000 employees worldwide.", Figure(355_000, "exact")),
]


@pytest.mark.parametrize("text,expected", GOLDEN_EXCERPTS)
def test_golden_excerpts(text, expected):
    assert parse_figure(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("with more than 4,500 employees across the globe", Figure(4_500, "more_than")),
    ("over 5,000 employees", Figure(5_000, "more_than")),
    ("approximately 5,000 employees", Figure(5_000, "approximately")),
    ("about 5,000 staff", Figure(5_000, "approximately")),
    ("nearly 5,000 workers", Figure(5_000, "approximately")),
    ("up to 5,000 seasonal workers", Figure(5_000, "up_to")),
    ("no more than 5,000 employees", Figure(5_000, "up_to")),
    ("approximately 2.1 million associates", Figure(2_100_000, "approximately")),
    ("a workforce of 12,400 people", Figure(12_400, "exact")),
    ("we had 850 full-time employees", Figure(850, "exact")),
])
def test_qualifiers_and_units(text, expected):
    assert parse_figure(text) == expected


@pytest.mark.parametrize("text", [
    "Revenue grew 12% to $4,388 million in 2025.",
    "As of December 31, 2025.",
    "Founded in 1998, the company is headquartered in Austin.",
    "Employees purchased 1.1 million shares at an average price of $321.93.",
    "",
])
def test_no_headcount(text):
    assert parse_figure(text) is None
