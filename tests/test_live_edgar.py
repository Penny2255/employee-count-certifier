# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Live EDGAR check of the golden set. Network required: run with RUN_LIVE=1."""

import os
from datetime import date

import pytest

from certifier import Entity, certify
from certifier.heuristic import best_per_filing
from certifier.sources.edgar import Edgar

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live network test; set RUN_LIVE=1")

# EDGAR-only expectations. SAP's EDGAR figure is the 20-F's "more than 110,000"; the more
# specific 112,234 comes from its Integrated Report, found by the research step.
GOLDEN = [("ADBE", 31_360, "exact"), ("TSN", 133_000, "approximately"), ("SAP", 110_000, "more_than"),
          ("NVO", 69_505, "exact"), ("NEE", 17_400, "approximately"), ("COST", 355_000, "exact")]


@pytest.fixture(scope="module")
def edgar():
    return Edgar()


@pytest.mark.parametrize("ticker,expected,qualifier", GOLDEN, ids=[g[0] for g in GOLDEN])
def test_golden_set_from_edgar(edgar, ticker, expected, qualifier):
    company = edgar.find_companies(ticker)[0]
    snippets = [s for f in edgar.annual_filings(company, limit=3) for s in edgar.snippets(f)]
    cert = certify(Entity(name=company.name), best_per_filing(snippets), lookup_date=date(2026, 10, 11))
    assert (cert.certified_count, cert.qualifier, cert.policy_tier) == (expected, qualifier, 1)
    assert cert.confidence_score >= 4
