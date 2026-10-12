"""Source labels (category + type), the glossary, the Corporate Fact Sheet policy and guided findings."""

import json
from datetime import date
from pathlib import Path

import pytest

from certifier import certify, taxonomy
from certifier.record import bottom_line, build_record, record_from_lookup
from certifier.service import LookupResult

from .conftest import LOOKUP, src

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "lookups").glob("*.json"))


# --- every source maps to exactly one category and type ---------------------------------------

@pytest.mark.parametrize("document_type", [None, *taxonomy.DOCUMENT_TYPES])
@pytest.mark.parametrize("tier", range(1, 10))
def test_every_source_the_engine_can_produce_has_a_category_and_type(document_type, tier):
    for url in ("https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm",
                "https://projects.propublica.org/nonprofits/organizations/1/2/full", "https://nces.ed.gov/ipeds/x",
                "https://www.linkedin.com/company/x", "https://www.example.com/", "https://www.example.com/careers",
                "https://www.zoominfo.com/c/x", "https://www.reuters.com/x", "https://unknown-site.io/x"):
        category, kind = taxonomy.classify(src(tier, 100, url=url, document_type=document_type))
        assert category in taxonomy.CATEGORIES and kind.strip()
        assert taxonomy.explain(kind), f"no glossary entry for {kind}"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_every_fixture_source_is_labelled_in_the_record(path):
    record = record_from_lookup(LookupResult.model_validate_json(path.read_text(encoding="utf-8")))
    for row in record.sources.items:
        assert row.source_category in taxonomy.CATEGORIES and row.source_type and row.source_type_info
    if record.primary_source.source_id:
        assert record.primary_source.source_category and record.primary_source.source_type


def test_examples_of_labels():
    def label(**kw):
        return taxonomy.classify(src(kw.pop("tier"), 100, **kw))
    assert label(tier=1, url="https://www.sec.gov/Archives/edgar/data/1/2/a.htm", document_type="10-K") == \
        ("Financial Filing", "10-K")
    assert label(tier=2, url="https://projects.propublica.org/nonprofits/organizations/1/2/full") == \
        ("Official Company Report", "IRS Form 990")
    assert label(tier=4, url="https://www.gong.io/about-us/") == ("Company Website", "Website: About Us")
    assert label(tier=5, url="https://www.linkedin.com/company/gong") == \
        ("Company Social Profile", "LinkedIn: Company Description")
    assert label(tier=6, url="https://www.paymentsdive.com/news/stripe") == \
        ("News (Executive Quote)", "News: Payments Dive")
    assert label(tier=7, url="https://www.reveliolabs.com/companies/stripe") == \
        ("Data Provider", "Data Provider: Revelio Labs")
    assert label(tier=8, url="https://pitchbook.com/profiles/x") == \
        ("Specialty Data & Financial Media", "Data Provider: PitchBook")
    assert label(tier=9, url="https://stockanalysis.com/stocks/crm/employees/") == \
        ("Other", "Data Provider: Stock Analysis")


def test_glossary_is_editable_yaml_with_strong_explanations():
    g = taxonomy.glossary()
    assert set(g["categories"]) == set(taxonomy.CATEGORIES)
    for name, text in g["types"].items():
        sentences = [s for s in " ".join(text.split()).split(". ") if s]
        assert 2 <= len(sentences) <= 4, name
    assert "Tier 1" in taxonomy.explain("10-K") and taxonomy.explain("News: Reuters") == taxonomy.explain("News")


# --- Corporate Fact Sheet policy -----------------------------------------------------------------

def fact_sheet(**kw):
    kw.setdefault("as_of", date(2026, 3, 31))
    return src(3, 12_400, url="https://www.example.com/company-facts.pdf", document_type="fact_sheet", **kw)


def test_fact_sheet_beats_press_release_and_website(entity):
    press = src(3, 12_000, as_of=date(2026, 6, 1), url="https://www.example.com/news/release",
                document_type="press_release")
    site = src(4, 13_000, as_of=None, url="https://www.example.com/about")
    cert = certify(entity, [press, site, fact_sheet()], lookup_date=LOOKUP)
    chosen = next(s for s in cert.sources if s.role == "selected")
    assert chosen.document_type == "fact_sheet" and chosen.tier == 2 and cert.certified_count == 12_400
    row = next(r for r in build_record(cert, lookup_date=LOOKUP).sources.items if r.value == 12_400)
    assert (row.source_category, row.source_type) == ("Official Company Report", "Corporate Fact Sheet")


def test_fact_sheet_ranks_behind_the_10k(entity):
    tenk = src(1, 12_100, as_of=date(2026, 1, 31), url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/a.htm",
               document_type="10-K")
    cert = certify(entity, [fact_sheet(), tenk], lookup_date=LOOKUP)
    assert cert.certified_count == 12_100


def test_undated_fact_sheet_drops_to_tier_3_with_a_note(entity):
    cert = certify(entity, [fact_sheet(as_of=None)], lookup_date=LOOKUP)
    s = cert.sources[0]
    assert s.tier == 3 and any("no date" in n for n in s.notes)
    assert "undated" in build_record(cert, lookup_date=LOOKUP).sources.items[0].tier_rationale


# --- guided findings -----------------------------------------------------------------------------

@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_every_finding_has_a_group_impact_and_so_what_in_plain_language(path):
    record = record_from_lookup(LookupResult.model_validate_json(path.read_text(encoding="utf-8")))
    for f in record.findings.items:
        assert f.group in ("affects", "worth_knowing", "background") and f.impact and f.so_what.endswith(".")
        assert "Complexity" not in f.title and not f.title.startswith("Flag") and "tracker" not in f.title.lower()
        if f.score_impact:
            assert f.group == "affects" and "confidence" in f.impact
    # The chips that changed the confidence explain the score.
    assert sum(f.score_impact for f in record.findings.items if f.group == "affects") == \
        sum(line.points for line in record.confidence.breakdown[1:])


def test_bottom_line_maps_to_confidence():
    assert bottom_line(5, 1).startswith("Ready to use") and bottom_line(4, 1).startswith("Ready to use")
    assert bottom_line(3, 1).startswith("Usable") and bottom_line(2, 1).startswith("Directional only")
    assert bottom_line(0, None).startswith("No certified figure")


def test_record_json_carries_labels_for_export():
    data = json.loads(build_record(certify_one(), lookup_date=LOOKUP).model_dump_json())
    assert {"source_category", "source_type", "source_type_info"} <= set(data["sources"]["items"][0])
    assert data["linkedin_check"]["source_type"] == "LinkedIn: Member Count"


def certify_one():
    from certifier.models import Entity
    return certify(Entity(name="Acme"), [src(4, 900, url="https://acme.example/about")], lookup_date=LOOKUP)
