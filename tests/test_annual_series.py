# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""SEC annual series: a breakdown after the total doesn't make it partial (the Microsoft FY2026 case)."""

from datetime import date

from certifier import certify
from certifier.heuristic import _describes_part
from certifier.models import Entity

from .conftest import src

MSFT_2026 = ("As of June 30, 2026, we employed approximately 223,000 people on a full-time basis, "
             "121,000 in the U.S. and 102,000 internationally.")
TODAY = date(2026, 10, 12)


def sec(value, year, scope="global", acc="000119312526323660"):
    return src(1, value, as_of=date(year, 6, 30), scope=scope, qualifier="approximately", document_type="10-K",
               url=f"https://www.sec.gov/Archives/edgar/data/789019/{acc}/msft-{year}0630.htm")


def test_total_followed_by_a_regional_breakdown_is_whole_company():
    assert _describes_part(MSFT_2026, 223_000) is False
    assert _describes_part("We had 121,000 employees in the U.S. as of June 30, 2026.", 121_000) is True
    assert _describes_part("Of our employees, 77,000 were in research and development.", 77_000) is True


def test_latest_10k_mislabelled_partial_is_restored_and_wins():
    cert = certify(Entity(name="Microsoft Corporation"),
                   [sec(223_000, 2026, scope="partial"), sec(228_000, 2025, acc="000095017025100235"),
                    sec(228_000, 2024, acc="000095017024087843")], lookup_date=TODAY)
    assert (cert.certified_count, cert.as_of_date) == (223_000, date(2026, 6, 30))
    chosen = next(s for s in cert.sources if s.role == "selected")
    assert any(n.startswith("Restored to whole-company") for n in chosen.notes)


def test_a_real_partial_figure_stays_partial():
    cert = certify(Entity(name="Microsoft Corporation"),
                   [sec(121_000, 2026, scope="partial"), sec(228_000, 2025, acc="000095017025100235")], lookup_date=TODAY)
    assert cert.certified_count == 228_000
    assert next(s for s in cert.sources if s.value == 121_000).scope == "partial"


def test_a_recruiting_campaign_figure_is_not_a_headcount():
    from certifier.heuristic import _NOT_HEADCOUNT
    assert _NOT_HEADCOUNT.search("We launched a campaign to help skill and recruit 250,000 people into the "
                                 "cybersecurity workforce by 2025.")
    assert not _NOT_HEADCOUNT.search("As of June 30, 2023, we employed approximately 221,000 people on a full-time basis.")


def test_older_annual_filings_are_read_from_edgars_older_pages():
    import json

    from certifier.sources.edgar import Company, Edgar

    def page(forms, start):
        return {"form": forms, "accessionNumber": [f"0000000000-{start + i:02d}-000001" for i in range(len(forms))],
                "primaryDocument": ["doc.htm"] * len(forms), "reportDate": [f"20{start + i}-01-31" for i in range(len(forms))],
                "filingDate": [f"20{start + i}-03-01" for i in range(len(forms))]}

    class Fake(Edgar):
        def _get(self, url):
            if url.endswith("CIK0000000001.json"):  # recent: only 3 annual filings among many Form 4s
                return json.dumps({"name": "X", "filings": {"recent": page(["4", "10-K", "4", "10-K", "10-K"], 26),
                                                            "files": [{"name": "CIK0000000001-submissions-001.json"}]}})
            return json.dumps(page(["10-K", "4", "10-K"], 10))

    filings = Fake().annual_filings(Company(cik=1, name="X", ticker=None), limit=5)
    assert len(filings) == 5 and all(f.form == "10-K" for f in filings)
