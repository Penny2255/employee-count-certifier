# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Company card and MCP App wiring, using recorded live lookups (no API calls)."""

import asyncio
import json
import re
from pathlib import Path

import pytest

from certifier import card
from certifier.record import record_errors, record_from_lookup
from certifier.service import LookupResult

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "lookups").glob("*.json"))


def load(path: Path) -> LookupResult:
    return LookupResult.model_validate_json(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_recorded_lookups_build_valid_records(path):
    record = record_from_lookup(load(path))
    data = json.loads(record.model_dump_json())
    assert record_errors(data) == []
    assert data["methodology"]["models"] and data["methodology"]["run_at"]
    assert all(s["use_rationale"] and s["tier_rationale"] for s in data["sources"]["items"])


def test_fixture_set_covers_the_four_requested_lookups():
    assert {p.stem for p in FIXTURES} == {"salesforce", "gong", "donor-network-west", "uc-davis", "stripe"}


def test_salesforce_fixture_reads_sec_gov():
    record = record_from_lookup(load(next(p for p in FIXTURES if p.stem == "salesforce")))
    assert record.headline.count == 83_334
    assert record.primary_source.url.startswith("https://www.sec.gov/") and record.primary_source.accession


def test_card_is_self_contained_and_embeds_the_record():
    record = record_from_lookup(load(FIXTURES[0]))
    html = card.render_card([record])
    assert not re.search(r"""<(?:script|link|img|iframe)[^>]+(?:src|href)=["']?https?:""", html, re.I)
    assert "@import" not in html and "fetch(" not in html
    embedded = re.search(r'<script type="application/json" id="record-data">(.*?)</script>', html, re.S).group(1)
    assert json.loads(embedded)["records"][0]["entity"]["name"] == record.entity.name


def test_hostile_excerpt_cannot_break_out_of_the_data_block():
    record = record_from_lookup(load(FIXTURES[0]))
    record.sources.items[0].excerpt = '</script><script>alert("x")</script><!--'
    html = card.render_card([record])
    assert html.count("</script>") == 2  # only the template's own closing tags
    assert "\\u003c/script>\\u003cscript>alert" in html  # escaped inside the JSON block
    data_block = html.split('id="record-data">')[1].split("</script>")[0]
    assert json.loads(data_block)["records"][0]["sources"]["items"][0]["excerpt"].startswith("</script>")


def test_status_is_never_color_alone():
    html = card.app_html()
    assert '"✓", "Green"' in html and '"!", "Yellow"' in html and '"✕", "Red"' in html


def test_app_html_waits_for_host_data():
    html = card.app_html()
    assert '<script type="application/json" id="record-data">null</script>' in html
    assert "ui/initialize" in html and "ui/notifications/initialized" in html


def test_save_card_writes_one_file(tmp_path):
    path = card.save_card([record_from_lookup(load(p)) for p in FIXTURES[:2]], tmp_path)
    assert path.parent == tmp_path and path.suffix == ".html" and path.stat().st_size > 10_000


# --- MCP server ---------------------------------------------------------------------------------

def test_server_binds_certify_to_the_card_resource():
    from certifier.server import server

    async def check():
        tools = {t.name: t for t in await server.list_tools()}
        meta = tools["certify_employee_count"].meta
        resources = {str(r.uri): r for r in await server.list_resources()}
        return meta, resources

    meta, resources = asyncio.run(check())
    assert meta["ui"]["resourceUri"] == card.APP_URI
    assert card.APP_URI in resources


def test_certify_tool_returns_records_and_card_path(monkeypatch, tmp_path):
    from certifier import server

    fixture = load(next(p for p in FIXTURES if p.stem == "salesforce"))
    monkeypatch.setattr(server, "lookup", lambda entity, **kw: fixture)
    monkeypatch.setattr(card, "OUTPUTS_DIR", tmp_path)
    out = asyncio.run(server.certify_employee_count(name="Salesforce, Inc.", website="https://www.salesforce.com"))
    assert record_errors(out["entity"]["record"]) == []
    assert out["entity"]["summary"].startswith("Salesforce, Inc.: 83,334 employees")
    assert Path(out["card_path"]).exists() and Path(out["card_path"]).parent == tmp_path
