"""Hosted service: web API, access codes, OAuth sign-in for the Claude connector, MCP over HTTP,
spend controls and caching. Lookups are replaced with a recorded fixture (no API calls)."""

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import anthropic
import pytest

os.environ.setdefault("CERTIFIER_NO_APP", "1")  # don't build the module-level app at import

from fastapi.testclient import TestClient  # noqa: E402

from certifier import access, web  # noqa: E402
from certifier.service import LookupResult  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "lookups" / "salesforce.json"
CODE = "ecc_" + "t" * 32
OTHER = "ecc_" + "o" * 32
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CERTIFIER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CERTIFIER_ACCESS_CODES", f"alice:{access.hash_code(CODE)},bob:{access.hash_code(OTHER)}")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost")
    monkeypatch.delenv("CERTIFIER_REVOKED", raising=False)
    calls = []

    def fake_lookup(entity, progress=None, **kw):
        calls.append(entity.name)
        for stage in ("resolve", "filings", "sweep", "corroborate", "score", "certified"):
            if progress:
                progress(stage, stage)
        result = LookupResult.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
        return result.model_copy(update={"certification": result.certification.model_copy(update={"entity": entity})})

    monkeypatch.setattr(web, "lookup", fake_lookup)
    yield calls
    from certifier import server as mcp_server
    mcp_server.configure_hosting(None, None)  # hosted settings are module-level; reset for other tests


@pytest.fixture
def client(env):
    with TestClient(web.create_app(), base_url="http://localhost", follow_redirects=False) as c:
        yield c


def auth(code=CODE):
    return {"Authorization": f"Bearer {code}"}


# --- helpers -----------------------------------------------------------------------------------

def stream(client, body, code=CODE):
    """POST /api/lookup and parse the server-sent events into (event, data) pairs."""
    r = client.post("/api/lookup", json=body, headers=auth(code))
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.status_code, [("http-error", r.json())]
    events = []
    for block in r.text.split("\n\n"):
        ev = next((line[6:].strip() for line in block.splitlines() if line.startswith("event:")), None)
        data = next((line[5:].strip() for line in block.splitlines() if line.startswith("data:")), None)
        if ev and data:
            events.append((ev, json.loads(data)))
    return r.status_code, events


def result_of(events):
    return next(d for e, d in events if e == "result")


SF = {"name": "Salesforce, Inc.", "website": "https://www.salesforce.com", "query": "Salesforce"}


# --- health, admin status and access codes ------------------------------------------------------

def test_health_is_minimal(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_admin_status_requires_a_code_and_has_no_secrets(client):
    assert client.get("/admin/status").status_code == 401
    body = client.get("/admin/status", headers=auth()).json()
    assert body["access_codes_configured"] == 2 and body["daily_lookups_per_code"] == 10 and body["cache_days"] == 90
    assert "sk-ant" not in json.dumps(body) and CODE not in json.dumps(body)


def test_api_requires_a_valid_access_code(client):
    assert client.post("/api/lookup", json=SF).status_code == 401
    r = client.post("/api/lookup", json=SF, headers=auth("ecc_wrong"))
    assert r.status_code == 401 and r.json()["error"] == "Enter a valid access code."


def test_revoked_code_is_refused(client, monkeypatch):
    monkeypatch.setenv("CERTIFIER_REVOKED", "alice")
    assert client.post("/api/lookup", json=SF, headers=auth()).status_code == 401


def test_access_code_cli_round_trip():
    code = access.new_code()
    codes = access.AccessCodes({"CERTIFIER_ACCESS_CODES": f"carol:{access.hash_code(code)}"})
    assert codes.verify(code) == "carol" and codes.verify(code + "x") is None


# --- pages and assets ---------------------------------------------------------------------------

def test_page_and_single_css_and_js(client):
    page = client.get("/")
    assert page.status_code == 200 and "GTM Data Certifier" in page.text and "Deep sweeps. Certified answers." in page.text
    assert "Matthew Beltrano" in page.text and "linkedin.com/in/matthewbeltrano" in page.text
    assert "Certified under policy v0.2 from public sources. Verify before contractual use." in page.text
    css = client.get("/static/app.css").text
    assert "--loop-blue: #599AF5" in css and ".cert .card" in css and "prefers-reduced-motion" in css
    js = client.get("/static/app.js").text
    assert "window.GTMCard" in js and "Deep Sea Dive" in js and "Frontier Voyage" in js
    assert client.get("/assets/brand/hyperloop-mark-small.png").status_code == 200
    assert client.get("/assets/brand/../../.env").status_code == 404
    assert client.get("/favicon.ico").status_code == 200


def test_query_fields_treat_domains_as_websites():
    assert web._query_fields("stripe.com") == ("stripe", "https://stripe.com")
    assert web._query_fields("https://www.salesforce.com/") == ("salesforce", "https://www.salesforce.com")
    assert web._query_fields("Donor Network West") == ("Donor Network West", None)


# --- streamed lookup, stored results, exports and ratings ----------------------------------------

def test_lookup_streams_real_stages_then_the_result(client, env):
    status, events = stream(client, SF)
    assert status == 200
    names = [e for e, _ in events]
    assert names[0] == "start" and names[-1] == "result"
    assert [d["stage"] for e, d in events if e == "progress"] == ["resolve", "filings", "sweep", "corroborate", "score",
                                                                 "certified"]
    res = result_of(events)
    assert res["record"]["headline"]["count"] == 83_334 and res["cached"] is False and env == ["Salesforce, Inc."]
    stored = client.get(f"/api/lookups/{res['query_id']}", headers=auth()).json()
    assert stored["record"]["entity"]["name"] == "Salesforce, Inc."


def test_exports(client):
    qid = result_of(stream(client, SF)[1])["query_id"]
    j = client.get(f"/api/lookups/{qid}/export?format=json", headers=auth())
    assert j.status_code == 200 and json.loads(j.text)["headline"]["count"] == 83_334
    summary = client.get(f"/api/lookups/{qid}/export?format=summary_csv", headers=auth())
    lines = summary.text.strip().splitlines()
    assert lines[0].startswith("entity_name,website") and len(lines) == 2 and "83334" in lines[1]
    assert 'filename="salesforce-inc-summary.csv"' in summary.headers["content-disposition"]
    sources = client.get(f"/api/lookups/{qid}/export?format=sources_csv", headers=auth()).text.strip().splitlines()
    assert sources[0].startswith("entity_name,source_id,tier") and len(sources) > 2
    assert client.get(f"/api/lookups/{qid}/export?format=xls", headers=auth()).status_code == 400


def test_rating_is_stored_with_the_query(client):
    qid = result_of(stream(client, SF)[1])["query_id"]
    assert client.post(f"/api/lookups/{qid}/rating", json={"rating": "Great", "comment": "Spot on"},
                       headers=auth()).json() == {"ok": True}
    assert client.post(f"/api/lookups/{qid}/rating", json={"rating": "meh"}, headers=auth()).status_code == 400
    rows = web.Store().ratings()
    assert rows[0]["rating"] == "great" and rows[0]["comment"] == "Spot on" and rows[0]["query"] == "Salesforce"
    assert rows[0]["subject"] == "alice"


def test_cache_then_refresh(client, env):
    stream(client, SF)
    second = result_of(stream(client, SF)[1])
    assert second["cached"] is True and len(env) == 1 and second["certified_on"]
    assert "Cached certification" in second["record"]["methodology"]["notes"][0]
    stream(client, {**SF, "refresh": True})
    assert len(env) == 2


def test_per_code_daily_limit_and_friendly_message(env, monkeypatch):
    monkeypatch.setenv("CERTIFIER_DAILY_LOOKUPS_PER_USER", "1")
    with TestClient(web.create_app(), base_url="http://localhost") as c:
        assert result_of(stream(c, {"name": "A Corp"})[1])
        _, events = stream(c, {"name": "B Corp"})
        err = next(d for e, d in events if e == "error")
        assert err["kind"] == "limit" and "1 of your 1 new lookups today" in err["message"]
        assert result_of(stream(c, {"name": "A Corp"})[1])["cached"] is True  # cached: free
        assert result_of(stream(c, {"name": "B Corp"}, OTHER)[1])  # per code


def test_refresh_counts_against_the_limit(env, monkeypatch):
    monkeypatch.setenv("CERTIFIER_DAILY_LOOKUPS_PER_USER", "1")
    with TestClient(web.create_app(), base_url="http://localhost") as c:
        stream(c, {"name": "A Corp"})
        _, events = stream(c, {"name": "A Corp", "refresh": True})
        assert next(d for e, d in events if e == "error")["kind"] == "limit"


def test_global_daily_dollar_cap(env, monkeypatch):
    monkeypatch.setenv("CERTIFIER_DAILY_USD_CAP", "0.05")
    with TestClient(web.create_app(), base_url="http://localhost") as c:
        assert result_of(stream(c, {"name": "A Corp"})[1])  # spends ~$0.17
        _, events = stream(c, {"name": "B Corp"}, OTHER)
        assert "spending cap" in next(d for e, d in events if e == "error")["message"]


def test_card_paths_are_validated(client):
    assert client.get("/cards/..%2F..%2Fsecret.html").status_code == 404
    assert client.get("/cards/nope.html").status_code == 404


# --- hardening ----------------------------------------------------------------------------------

def _auth_error():
    import httpx2
    return anthropic.AuthenticationError("invalid x-api-key", response=httpx2.Response(
        401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")), body=None)


def test_anthropic_auth_error_in_lookup_is_a_plain_message(client, monkeypatch, caplog):
    def broken(entity, **kw):
        raise _auth_error()
    monkeypatch.setattr(web, "lookup", broken)
    _, events = stream(client, SF)
    err = next(d for e, d in events if e == "error")
    assert err == {"message": "Service configuration issue, please try again later.", "kind": "config"}
    assert any("ANTHROPIC_API_KEY" in r.getMessage() for r in caplog.records)


def test_anthropic_auth_error_in_find_is_json_503(client, monkeypatch):
    def broken(*a, **kw):
        raise _auth_error()
    monkeypatch.setattr(web, "find_entities", broken)
    r = client.post("/api/find", json={"query": "Stripe"}, headers=auth())
    assert r.status_code == 503 and r.json() == {"error": "Service configuration issue, please try again later."}


def test_unexpected_errors_are_json(env, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(web, "find_entities", broken)
    with TestClient(web.create_app(), base_url="http://localhost", raise_server_exceptions=False) as c:
        r = c.post("/api/find", json={"query": "Stripe"}, headers=auth())
        assert r.status_code == 500 and r.json()["error"].startswith("Something went wrong")
        assert "boom" not in r.text


@pytest.mark.parametrize("value", [None, "", "onrender.com", "http://my-service.onrender.com",
                                   "https://x.onrender.com/mcp", "ftp://x.com"])
def test_public_base_url_must_be_a_full_https_url(value):
    with pytest.raises(web.StartupError):
        web.validate_base_url(value)


def test_public_base_url_accepts_https_and_localhost():
    assert web.validate_base_url("https://x.onrender.com/") == "https://x.onrender.com"
    assert web.validate_base_url("http://localhost:8000") == "http://localhost:8000"


# --- OAuth sign-in for the Claude connector, then MCP over HTTP ----------------------------------

def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _oauth_token(client) -> dict:
    reg = client.post("/register", json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none",
                                          "grant_types": ["authorization_code", "refresh_token"],
                                          "response_types": ["code"], "client_name": "Claude"})
    assert reg.status_code in (200, 201), reg.text
    client_id = reg.json()["client_id"]
    verifier, challenge = _pkce()
    r = client.get("/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
                                         "code_challenge": challenge, "code_challenge_method": "S256",
                                         "state": "xyz", "scope": "certify"})
    assert r.status_code == 302, r.text
    login = urlsplit(r.headers["location"])
    assert login.path == "/oauth/login"
    request_id = parse_qs(login.query)["request"][0]
    assert "Access code" in client.get(f"/oauth/login?request={request_id}").text

    bad = client.post("/oauth/login", data={"request": request_id, "access_code": "ecc_nope"})
    assert bad.status_code == 400 and "isn't valid" in bad.text
    ok = client.post("/oauth/login", data={"request": request_id, "access_code": CODE})
    assert ok.status_code == 302
    back = urlsplit(ok.headers["location"])
    q = parse_qs(back.query)
    assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT and q["state"] == ["xyz"]

    tok = client.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": REDIRECT,
                                      "client_id": client_id, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    return {**tok.json(), "client_id": client_id}


def _mcp(client, token, method, params=None, id_=1):
    r = client.post("/mcp", headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
                                      "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18"},
                    json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
    if r.status_code != 200:
        return r.status_code, r.text
    text = r.text
    if text.lstrip().startswith("event:") or "data:" in text:
        text = next(line[5:] for line in text.splitlines() if line.startswith("data:"))
    return r.status_code, json.loads(text)


INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}


def test_discovery_metadata(client):
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200 and r.json()["authorization_servers"][0].startswith("http://localhost")
    assert client.get("/.well-known/oauth-authorization-server").json()["registration_endpoint"].endswith("/register")


def test_mcp_requires_auth_with_resource_metadata_pointer(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT},
                    headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401 and "resource_metadata" in r.headers.get("www-authenticate", "")


def test_oauth_flow_then_mcp_tools(client):
    tok = _oauth_token(client)
    status, init = _mcp(client, tok["access_token"], "initialize", INIT)
    assert status == 200 and init["result"]["serverInfo"]["name"] == "Employee Count Certifier"
    status, tools = _mcp(client, tok["access_token"], "tools/list", {}, 2)
    names = {t["name"]: t for t in tools["result"]["tools"]}
    assert names["certify_employee_count"]["_meta"]["ui"]["resourceUri"] == "ui://employee-count-certifier/card"
    assert "refresh" in names["certify_employee_count"]["inputSchema"]["properties"]


def test_oauth_refresh_rotates_and_revocation_ends_access(client, monkeypatch):
    tok = _oauth_token(client)
    r = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                    "client_id": tok["client_id"]})
    assert r.status_code == 200 and r.json()["access_token"] != tok["access_token"]
    monkeypatch.setenv("CERTIFIER_REVOKED", "alice")
    status, _ = _mcp(client, r.json()["access_token"], "initialize", INIT)
    assert status == 401


def test_bearer_access_code_works_for_mcp_directly(client):
    status, init = _mcp(client, CODE, "initialize", INIT)
    assert status == 200 and "result" in init


def test_mcp_certify_tool_over_http_applies_cache_and_limits(client, env, monkeypatch):
    from certifier import server as mcp_server
    monkeypatch.setattr(mcp_server, "lookup", web.lookup)  # the same recorded fixture
    args = {"name": "Salesforce, Inc.", "website": "https://www.salesforce.com"}
    _mcp(client, CODE, "initialize", INIT)
    status, first = _mcp(client, CODE, "tools/call", {"name": "certify_employee_count", "arguments": args}, 3)
    assert status == 200, first
    sc = first["result"]["structuredContent"]
    sc = sc.get("result", sc)
    assert sc["entity"]["record"]["headline"]["count"] == 83_334 and sc["card_url"].startswith("http://localhost/cards/")
    status, again = _mcp(client, CODE, "tools/call", {"name": "certify_employee_count", "arguments": args}, 4)
    sc2 = again["result"]["structuredContent"]
    assert "cached_at" in sc2.get("result", sc2)["entity"] and len(env) == 1

    monkeypatch.setenv("CERTIFIER_DAILY_LOOKUPS_PER_USER", "1")
    mcp_server._controls.daily_lookups = 1
    status, limited = _mcp(client, CODE, "tools/call",
                           {"name": "certify_employee_count", "arguments": {"name": "Another Corp"}}, 5)
    assert limited["result"]["isError"] is True
    assert "new lookups today" in limited["result"]["content"][0]["text"]
