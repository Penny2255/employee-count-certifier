"""Open beta: per-visitor and global allowances with reservations, Pacific-midnight reset, free cached
and sample results, connector tokens bound to the sign-in IP, admin bypass, and fair-use limits."""

import os
import threading
from datetime import datetime, timezone

import pytest

os.environ.setdefault("CERTIFIER_NO_APP", "1")  # don't build the module-level app at import

from fastapi.testclient import TestClient  # noqa: E402

from certifier import hosted, web  # noqa: E402
from certifier.store import Store  # noqa: E402

from .test_web import INIT, SF, _mcp, _oauth_token, auth, client, env, result_of, stream  # noqa: F401

VISITOR = "You've reached today's beta limit. Back tomorrow."
RESERVE = 0.50  # reserved per lookup (policy max_cost_usd_per_lookup)


def fixture_cost():
    from certifier.service import LookupResult

    from .test_web import FIXTURE
    return LookupResult.model_validate_json(FIXTURE.read_text(encoding="utf-8")).cost_usd


def allowed(cap):
    """Lookups that fit under `cap` when each reserves RESERVE and then spends the fixture's cost."""
    n = 0
    while n * fixture_cost() + RESERVE <= cap + 1e-9:
        n += 1
    return n
GLOBAL = "Beta capacity reached for today. Back tomorrow."


def company(n):
    return {"name": f"Company {n}", "website": f"https://company{n}.example", "query": f"Company {n}"}


def error_of(events):
    return next((d for e, d in events if e == "error"), None)


def beta_client(monkeypatch, **env_values):
    for k, v in env_values.items():
        monkeypatch.setenv(k, v)
    return TestClient(web.create_app(), base_url="http://localhost", follow_redirects=False)


# --- per-visitor and global caps -------------------------------------------------------------------

def test_per_visitor_cap_with_plain_message_and_remaining_searches(env, monkeypatch):
    with beta_client(monkeypatch, CERTIFIER_VISITOR_USD_PER_DAY="1.0") as c:
        assert c.get("/api/allowance", headers=auth(None)).json()["searches_left"] == 5  # $1.00 / ~$0.20
        for n in range(allowed(1.0)):  # each reserves $0.50, then spends only the fixture's cost
            assert result_of(stream(c, company(n), code=None)[1])
        _, events = stream(c, company(99), code=None)
        assert error_of(events) == {"message": VISITOR, "kind": "limit"}
        left = c.get("/api/allowance", headers=auth(None)).json()
        assert left["searches_left"] == 0 and left["message"] == VISITOR
        assert result_of(stream(c, company(99), code=None, ip="198.51.100.99")[1])  # another visitor is unaffected


def test_global_cap_across_visitors(env, monkeypatch):
    with beta_client(monkeypatch, CERTIFIER_DAILY_USD_CAP="0.9") as c:
        for n in range(allowed(0.9)):  # one lookup per visitor, all drawing on the global cap
            assert result_of(stream(c, company(n), code=None, ip=f"198.51.100.{n}")[1])
        _, events = stream(c, company(50), code=None, ip="198.51.100.50")
        assert error_of(events)["message"] == GLOBAL


def test_reservations_never_exceed_a_cap_under_concurrency(tmp_path):
    store = Store(tmp_path / "s.sqlite3")
    results = []
    barrier = threading.Barrier(8)

    def go(i):
        barrier.wait()
        results.append(store.reserve(f"v:{i}", 0.5, 2.0, 1.6))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(None) == 3 and results.count("global") == 5  # 3 x 0.50 <= 1.60 < 4 x 0.50
    assert store.used("v:0")[1] == pytest.approx(1.5)


def test_concurrent_lookups_are_held_to_the_global_cap(env, monkeypatch):
    gate = threading.Event()

    def slow_lookup(entity, progress=None, spend=None, **kw):
        gate.wait(5)
        from .test_web import FIXTURE
        from certifier.service import LookupResult
        return LookupResult.model_validate_json(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(web, "lookup", slow_lookup)
    with beta_client(monkeypatch, CERTIFIER_DAILY_USD_CAP="1.2") as c:
        outcomes = []

        def visitor(i):
            outcomes.append(stream(c, company(i), code=None, ip=f"198.51.100.{i}")[1])

        threads = [threading.Thread(target=visitor, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        threading.Timer(1.0, gate.set).start()
        for t in threads:
            t.join()
    ok = [e for e in outcomes if any(name == "result" for name, _ in e)]
    refused = [error_of(e) for e in outcomes if error_of(e)]
    assert len(ok) == 2 and [r["message"] for r in refused] == [GLOBAL, GLOBAL]  # 2 x 0.50 <= 1.2 < 3 x 0.50


def test_reservation_is_released_and_a_failed_lookup_keeps_only_its_real_cost(tmp_path):
    controls = hosted.Controls(Store(tmp_path / "s.sqlite3"))
    who = hosted.Who("v:abc")

    def failing(entity, spend=None, **kw):
        spend.usd += 0.08
        raise RuntimeError("upstream timeout")

    with pytest.raises(RuntimeError):
        hosted.run_lookups([hosted.Job(web.Entity(name="X Corp"))], failing, who=who, controls=controls)
    summary = controls.store.summary_today()
    assert summary["reserved"] == 0 and summary["spent"] == pytest.approx(0.08) and summary["lookups"] == 0


def test_one_lookup_in_progress_per_visitor(tmp_path):
    controls = hosted.Controls(Store(tmp_path / "s.sqlite3"))
    who = hosted.Who("v:abc")
    with controls.one_at_a_time(who):
        with pytest.raises(hosted.LimitExceeded) as e:
            with controls.one_at_a_time(who):
                pass
        assert e.value.kind == "busy"
        with controls.one_at_a_time(hosted.Who("v:other")):
            pass  # another visitor isn't blocked
    with controls.one_at_a_time(who):
        pass  # released afterwards


# --- reset at midnight Pacific; daily salt -----------------------------------------------------------

def test_allowances_reset_at_midnight_pacific_not_utc(tmp_path):
    now = {"t": datetime(2026, 10, 13, 6, 30, tzinfo=timezone.utc)}  # 11:30 pm Pacific on Oct 12 (PDT)
    store = Store(tmp_path / "s.sqlite3", clock=lambda: now["t"])
    assert store.reserve("v:a", 0.5, 0.5, 5.0) is None
    assert store.reserve("v:a", 0.5, 0.5, 5.0) == "visitor"
    now["t"] = datetime(2026, 10, 13, 6, 59, tzinfo=timezone.utc)  # still Oct 12 in Pacific: no reset at UTC midnight
    assert store.today() == "2026-10-12" and store.reserve("v:a", 0.5, 0.5, 5.0) == "visitor"
    now["t"] = datetime(2026, 10, 13, 7, 1, tzinfo=timezone.utc)  # 12:01 am Pacific on Oct 13
    assert store.today() == "2026-10-13" and store.reserve("v:a", 0.5, 0.5, 5.0) is None


def test_visitor_hash_uses_a_salt_rotated_daily(tmp_path):
    now = {"t": datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)}
    controls = hosted.Controls(Store(tmp_path / "s.sqlite3", clock=lambda: now["t"]))
    key = controls.ip_key("203.0.113.7")
    assert "203.0.113.7" not in key and controls.ip_key("203.0.113.7") == key  # keyed hash, stable
    today = controls.visitor(key)
    assert controls.visitor(key) == today and controls.visitor(controls.ip_key("203.0.113.8")) != today
    now["t"] = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)
    assert controls.visitor(key) != today  # new day, new salt
    with controls.store._conn() as c:
        assert [r[0] for r in c.execute("SELECT day FROM salts")] == ["2026-10-14"]  # yesterday's salt is gone


# --- free content -------------------------------------------------------------------------------

def test_cached_and_sample_results_are_free_even_at_the_limit(env, monkeypatch):
    with beta_client(monkeypatch, CERTIFIER_VISITOR_USD_PER_DAY="0.6") as c:
        assert result_of(stream(c, SF, code=None)[1])["cached"] is False  # spent; no room for another 0.50
        assert error_of(stream(c, company(1), code=None)[1])["message"] == VISITOR
        again = result_of(stream(c, SF, code=None)[1])
        assert again["cached"] is True and len(env) == 1  # cached: free, served at the limit
        samples = c.get("/api/samples").json()["samples"]
        assert [s["slug"] for s in samples][:2] == ["salesforce", "stripe"] and len(samples) == 8
        sample = c.get("/api/samples/salesforce").json()
        assert sample["sample"] is True and sample["record"]["headline"]["count"] and sample["certified_on"]
        assert c.get("/api/lookups/sample-salesforce/export?format=summary_csv").status_code == 200
        assert c.get("/api/samples/nope").status_code == 404


# --- Claude connector -----------------------------------------------------------------------------

def test_connector_guest_token_is_bound_to_the_sign_in_ip_and_shares_its_allowance(client, env, monkeypatch):
    from certifier import server as mcp_server
    monkeypatch.setattr(mcp_server, "lookup", web.lookup)
    ip = "198.51.100.20"
    before = client.get("/api/allowance", headers=auth(None, ip)).json()["searches_left"]
    guest = _oauth_token(client, mode="guest", ip=ip)["access_token"]
    _mcp(client, guest, "initialize", INIT)
    # The connector request itself arrives from Anthropic's servers, not the person's IP.
    status, out = _mcp(client, guest, "tools/call", {"name": "certify_employee_count",
                                                      "arguments": {"name": "Connector Corp"}}, 2)
    assert status == 200 and not out["result"].get("isError")
    mine = client.get("/api/allowance", headers=auth(None, ip)).json()["searches_left"]
    other = client.get("/api/allowance", headers=auth(None, "198.51.100.21")).json()["searches_left"]
    assert mine < before and other == before  # the website visitor at that IP shares the spend
    again = _oauth_token(client, mode="guest", ip=ip)["access_token"]  # reconnecting doesn't reset it
    mcp_server._controls.visitor_usd = 0.6
    _, limited = _mcp(client, again, "tools/call", {"name": "certify_employee_count",
                                                    "arguments": {"name": "Second Corp"}}, 3)
    assert limited["result"]["isError"] is True and limited["result"]["content"][0]["text"] == VISITOR


# --- admin -----------------------------------------------------------------------------------------

def test_admin_code_bypasses_visitor_and_global_caps(env, monkeypatch):
    with beta_client(monkeypatch, CERTIFIER_VISITOR_USD_PER_DAY="0.1", CERTIFIER_DAILY_USD_CAP="0.1") as c:
        assert error_of(stream(c, company(1), code=None)[1])["message"] == VISITOR
        assert result_of(stream(c, company(1))[1])  # admin code: no limits
        assert c.get("/api/allowance", headers=auth()).json() == {"admin": True, "searches_left": None, "message": None}


def test_admin_page_and_summary(client):
    assert "Beta admin" in client.get("/admin").text
    assert client.get("/api/admin/summary", headers=auth(None)).status_code == 401
    stream(client, SF, code=None)
    stream(client, SF, code=None, ip="198.51.100.5")  # cache hit, second visitor
    rating_id = result_of(stream(client, SF, code=None)[1])["query_id"]
    client.post(f"/api/lookups/{rating_id}/rating", json={"rating": "good", "comment": "Close"}, headers=auth(None))
    d = client.get("/api/admin/summary", headers={**auth(), "X-Forwarded-For": "203.0.113.50"}).json()
    t = d["today"]
    assert t["lookups"] == 1 and t["cache_hits"] == 2 and t["visitors"] == 2 and t["spent"] == pytest.approx(fixture_cost())
    assert d["ratings"][0]["rating"] == "good" and d["ratings"][0]["entity_name"] == "Salesforce, Inc."
    assert d["proxy"]["your_ip_as_seen"] == "203.0.113.x"


def test_connector_sign_in_page_offers_guest_and_admin(client):
    page = web._login_page("abc")
    assert "Continue as beta guest" in page and "Have an admin code?" in page and 'name="mode" value="admin"' in page


# --- fair use ---------------------------------------------------------------------------------------

def test_rate_limit_per_ip(env, monkeypatch):
    with beta_client(monkeypatch, CERTIFIER_RATE_LIMIT_PER_MIN="3") as c:
        for _ in range(3):
            assert c.get("/api/allowance", headers=auth(None)).status_code == 200
        r = c.get("/api/samples", headers=auth(None))
        assert r.status_code == 429 and r.json()["error"] == "Too many requests. Please wait a minute and try again."
        assert c.get("/api/allowance", headers=auth(None, "198.51.100.77")).status_code == 200  # per IP
        assert c.get("/health", headers=auth(None)).status_code == 200  # health checks are exempt
        assert c.get("/static/app.css", headers=auth(None)).status_code == 200  # so are page assets
        assert c.get("/api/allowance", headers=auth()).status_code == 200  # admins aren't limited


@pytest.mark.parametrize("header,hops,expected", [
    ("203.0.113.7", "1", "203.0.113.7"),
    ("6.6.6.6, 203.0.113.7", "1", "203.0.113.7"),  # a spoofed left entry is ignored
    ("203.0.113.7, 10.0.0.2", "2", "203.0.113.7"),  # two trusted proxies
    ("", "1", "testclient"),
])
def test_client_ip_from_x_forwarded_for(monkeypatch, header, hops, expected):
    from starlette.requests import Request
    monkeypatch.setenv("CERTIFIER_PROXY_HOPS", hops)
    scope = {"type": "http", "headers": [(b"x-forwarded-for", header.encode())] if header else [],
             "client": ("testclient", 50000)}
    assert web.client_ip(Request(scope)) == expected


def test_results_cached_by_older_code_are_not_served(tmp_path):
    controls = hosted.Controls(Store(tmp_path / "s.sqlite3"))
    entity = web.Entity(name="Microsoft Corporation", website="https://www.microsoft.com")
    key = hosted.cache_key(entity, 789019, None)
    assert key.startswith(f"v{hosted.ENGINE_VERSION}|")
    controls.store.cache_put(key.split("|", 1)[1], "{}")  # the pre-versioning key format (e.g. a FY2025 result)
    assert controls.store.cache_get(key, 90) is None
