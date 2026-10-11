"""Hosted service: web API, access codes, OAuth sign-in for the Claude connector, MCP over HTTP,
spend controls and caching. Lookups are replaced with a recorded fixture (no API calls)."""

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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

    def fake_lookup(entity, **kw):
        calls.append(entity.name)
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


# --- health and access codes ------------------------------------------------------------------

def test_health_reports_status_without_secrets(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["access_codes_configured"] == 2
    assert "sk-ant" not in r.text and CODE not in r.text


def test_api_requires_a_valid_access_code(client):
    assert client.post("/api/certify", json={"name": "Salesforce, Inc."}).status_code == 401
    r = client.post("/api/certify", json={"name": "Salesforce, Inc."}, headers=auth("ecc_wrong"))
    assert r.status_code == 401 and r.json()["error"] == "Enter a valid access code."


def test_revoked_code_is_refused(client, monkeypatch):
    monkeypatch.setenv("CERTIFIER_REVOKED", "alice")
    assert client.post("/api/certify", json={"name": "X"}, headers=auth()).status_code == 401


def test_access_code_cli_round_trip():
    code = access.new_code()
    codes = access.AccessCodes({"CERTIFIER_ACCESS_CODES": f"carol:{access.hash_code(code)}"})
    assert codes.verify(code) == "carol" and codes.verify(code + "x") is None


# --- web certify, cards, cache and limits -------------------------------------------------------

def test_certify_returns_records_and_a_card(client, env):
    r = client.post("/api/certify", json={"name": "Salesforce, Inc.", "website": "https://www.salesforce.com"},
                    headers=auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"][0]["record"]["headline"]["count"] == 83_334
    assert body["results"][0]["cached"] is False
    card = client.get(body["card_url"])
    assert card.status_code == 200 and "Salesforce" in card.text and env == ["Salesforce, Inc."]


def test_cache_then_refresh(client, env):
    body = {"name": "Salesforce, Inc.", "website": "https://www.salesforce.com"}
    client.post("/api/certify", json=body, headers=auth())
    second = client.post("/api/certify", json=body, headers=auth()).json()
    assert second["results"][0]["cached"] is True and len(env) == 1
    assert "Cached certification" in second["results"][0]["record"]["methodology"]["notes"][0]
    client.post("/api/certify", json={**body, "refresh": True}, headers=auth())
    assert len(env) == 2


def test_per_user_daily_limit(client, env, monkeypatch):
    monkeypatch.setenv("CERTIFIER_DAILY_LOOKUPS_PER_USER", "1")
    with TestClient(web.create_app(), base_url="http://localhost") as c:
        assert c.post("/api/certify", json={"name": "A Corp"}, headers=auth()).status_code == 200
        r = c.post("/api/certify", json={"name": "B Corp"}, headers=auth())
        assert r.status_code == 429 and "1 of your 1 new lookups today" in r.json()["error"]
        assert c.post("/api/certify", json={"name": "A Corp"}, headers=auth()).status_code == 200  # cached: free
        assert c.post("/api/certify", json={"name": "B Corp"}, headers=auth(OTHER)).status_code == 200  # per user


def test_global_daily_dollar_cap(client, env, monkeypatch):
    monkeypatch.setenv("CERTIFIER_DAILY_USD_CAP", "0.05")
    with TestClient(web.create_app(), base_url="http://localhost") as c:
        assert c.post("/api/certify", json={"name": "A Corp"}, headers=auth()).status_code == 200  # spends ~$0.17
        r = c.post("/api/certify", json={"name": "B Corp"}, headers=auth(OTHER))
        assert r.status_code == 429 and "spending cap" in r.json()["error"]


def test_card_paths_are_validated(client):
    assert client.get("/cards/..%2F..%2Fsecret.html").status_code == 404
    assert client.get("/cards/nope.html").status_code == 404


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
