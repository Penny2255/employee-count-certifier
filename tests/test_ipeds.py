# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""IPEDS reader: College Navigator match by exact name, then "Total all staff (excludes graduate
assistants)" from the institution profile's Human Resources data (recorded responses, no network)."""

from datetime import date
from pathlib import Path

from certifier import taxonomy
from certifier.models import Entity
from certifier.service import ipeds_sources
from certifier.sources.ipeds import IPEDS

FIX = Path(__file__).parent / "fixtures" / "ipeds"


def fake_fetch(url, headers):
    if "collegenavigator" in url:
        return (FIX / "navigator-uc-davis.html").read_text(encoding="utf-8")
    if "/api/subject/13" in url:
        assert "unitId=110644" in url and headers.get("Accept") == "application/json"
        return (FIX / "hr-110644.json").read_text(encoding="utf-8")
    return "<html></html>"  # the profile page (sets cookies)


def test_uc_davis_total_all_staff_fall_2024():
    ipeds = IPEDS(fetch=fake_fetch)
    inst = ipeds.find("University of California-Davis")
    assert (inst.unitid, inst.location) == ("110644", "Davis, California")
    s = ipeds.staff_source(inst)
    assert (s.value, s.tier, s.as_of_date) == (15_029, 2, date(2024, 11, 1))
    assert s.url == "https://nces.ed.gov/ipeds/institution-profile/110644"
    assert s.excerpt == "All staff (excludes graduate assistants): Total 15,029 (Fall 2024)"
    assert s.separately_reported == {"graduate assistants": 4_795}  # logged, never added
    assert "Human Resources" in s.location.section and "Fall 2024" in s.location.section
    assert taxonomy.classify(s) == ("Official Company Report", "IPEDS Filing")


def test_no_match_without_an_exact_name():
    assert IPEDS(fetch=fake_fetch).find("UC Davis Health Sciences Campus") is None


def test_only_colleges_are_looked_up_and_outages_are_noted():
    calls = []

    class Spy(IPEDS):
        def find(self, name):
            calls.append(name)
            raise OSError("timeout")

    notes = []
    assert ipeds_sources(Entity(name="Salesforce, Inc.", website="https://www.salesforce.com"), notes, Spy()) == []
    assert calls == []
    assert ipeds_sources(Entity(name="University of California-Davis", website="https://www.ucdavis.edu"), notes,
                         Spy()) == []
    assert calls == ["University of California-Davis"] and notes == ["IPEDS unavailable: timeout"]
