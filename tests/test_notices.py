# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Proprietary notices: robots.txt, the robots meta tag and X-Robots-Tag header on every route, the terms page,
and the owner line on the card, CSV and JSON outputs and in the MCP server's instructions and tools."""

import json

from certifier import card, server
from certifier.notice import AI_CRAWLERS, OWNER_LINE, ROBOTS, SHORT_NOTICE

from .test_downloads import record
from .test_web import SF, auth, client, env, result_of, stream  # noqa: F401

META = '<meta name="robots" content="noindex, nofollow, noarchive, noai, noimageai">'
ROUTES = [("get", "/"), ("get", "/terms"), ("get", "/robots.txt"), ("get", "/health"), ("get", "/api/samples"),
          ("get", "/static/app.js"), ("get", "/oauth/login"), ("get", "/admin"), ("get", "/no-such-page"),
          ("get", "/.well-known/oauth-authorization-server"), ("post", "/mcp"), ("get", "/api/lookups/nope")]


def test_robots_txt_disallows_everyone_and_names_ai_crawlers(client):
    text = client.get("/robots.txt").text
    assert text.rstrip().endswith("User-agent: *\nDisallow: /")
    for bot in ("GPTBot", "ChatGPT-User", "ClaudeBot", "anthropic-ai", "CCBot", "Google-Extended", "PerplexityBot",
                "Bytespider", "Amazonbot", "Applebot-Extended", "meta-externalagent", "cohere-ai"):
        assert bot in AI_CRAWLERS and f"User-agent: {bot}\nDisallow: /" in text


def test_every_response_carries_the_robots_header(client):
    for method, path in ROUTES:
        res = getattr(client, method)(path)
        assert res.headers.get("x-robots-tag") == ROBOTS, (path, res.status_code)


def test_every_page_carries_the_robots_meta_tag(client):
    for path in ("/", "/terms", "/oauth/login", "/admin"):
        assert META in client.get(path).text, path
    assert META in card.app_html()  # the card served to Claude; the saved card is checked below


def test_terms_page_and_footer_link(client):
    terms = client.get("/terms")
    assert terms.status_code == 200
    for words in ("Beta access is for evaluation", "Scrape, crawl", "train, fine-tune", "provided as is",
                  "All rights reserved", OWNER_LINE):
        assert words in terms.text
    home = client.get("/").text
    assert '<a class="owner-notice" href="/terms">© 2026 Matthew Beltrano · Proprietary · Not open source</a>' in home
    assert 'data-open="dlg-privacy">Privacy</button>' in home and '<a class="link" href="/terms">Terms</a>' in home


def test_card_csv_and_json_carry_the_owner_line(client, tmp_path):
    from certifier.record import CertificationRecord
    saved = card.render_card([CertificationRecord.model_validate(record())])
    assert META in saved and json.dumps(OWNER_LINE, ensure_ascii=False) in saved and "owner-notice" in saved
    qid = result_of(stream(client, SF)[1])["query_id"]
    exported = json.loads(client.get(f"/api/lookups/{qid}/export?format=json", headers=auth()).text)
    assert exported["notice"] == OWNER_LINE and exported["headline"]["count"] == 83_334
    for fmt in ("summary_csv", "sources_csv"):
        last = client.get(f"/api/lookups/{qid}/export?format={fmt}", headers=auth()).text.strip().splitlines()[-1]
        assert last == '"# ' + OWNER_LINE + '"'


def test_mcp_server_carries_a_one_sentence_notice_and_the_90_day_cache():
    assert SHORT_NOTICE.count(". ") == 0 and SHORT_NOTICE.endswith(".")
    assert SHORT_NOTICE in server.INSTRUCTIONS and "cached for 90 days" in server.INSTRUCTIONS
    assert "30 days" not in server.INSTRUCTIONS and "30-day" not in server.__doc__
    for tool in (server.find_entity, server.certify_employee_count):
        assert tool.__doc__.count(SHORT_NOTICE) == 1
