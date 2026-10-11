"""Hosted service: web page + JSON API + MCP over Streamable HTTP, on one engine.

    uvicorn certifier.web:app            # or: certifier-mcp --http

Routes
  GET  /health              status (no secrets)
  GET  /                    search page: access code, company search, confirmation, company card
  POST /api/find            candidates for a name (bearer access code)
  POST /api/certify         certify a confirmed entity (bearer access code; cached 30 days)
  GET  /cards/{file}        saved company cards
  GET/POST /oauth/login     access-code sign-in for the Claude custom connector (OAuth)
  /mcp                      MCP endpoint (OAuth token or bearer access code)
  /.well-known/*, /authorize, /token, /register, /revoke   OAuth, served by the MCP SDK

Configuration comes only from environment variables (see DEPLOY.md).
"""

from __future__ import annotations

import html
import os
import re
from contextlib import asynccontextmanager
from typing import Any

import anyio
from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from . import hosted
from . import server as mcp_server
from .access import AccessCodes
from .card import save_card
from .config import load_env
from .entity import find_entities
from .llm import Claude, Spend
from .models import Entity
from .oauth import SCOPE, AccessCodeOAuthProvider
from .policy import default_policy
from .record import record_from_lookup
from .service import lookup
from .store import Store, data_dir

CARD_NAME = re.compile(r"^[a-z0-9-]+\.html$")


class FindRequest(BaseModel):
    name: str
    website: str | None = None


class CertifyRequest(BaseModel):
    name: str
    website: str | None = None
    hq: str | None = None
    cik: int | None = None
    legal_parent: str | None = None
    parent_website: str | None = None
    parent_cik: int | None = None
    relationship_to_parent: str | None = None
    include_parent: bool = True
    refresh: bool = False


def create_app() -> FastAPI:
    load_env()
    base_url = (os.environ.get("PUBLIC_BASE_URL") or "http://localhost:8000").rstrip("/")
    store = Store()
    codes = AccessCodes()
    controls = hosted.Controls.from_env(store)
    provider = AccessCodeOAuthProvider(store, codes, base_url)
    mcp = mcp_server.create_server(
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=base_url, resource_server_url=f"{base_url}/mcp", validate_token_resource=False,
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE],
                                                                  default_scopes=[SCOPE]),
            revocation_options=RevocationOptions(enabled=True)))
    mcp_server.configure_hosting(controls, base_url)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True,
        # Authenticated public service: DNS-rebinding protection is for unauthenticated local servers.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Employee Count Certifier", lifespan=lifespan, docs_url=None, redoc_url=None)

    async def subject_for(authorization: str | None) -> str:
        token = (authorization or "")[7:].strip() if (authorization or "").lower().startswith("bearer ") else ""
        access = await provider.load_access_token(token) if token else None
        if access is None or not access.subject:
            raise HTTPException(401, "Enter a valid access code.")
        return access.subject

    @app.exception_handler(hosted.LimitExceeded)
    async def _limit(_: Request, exc: hosted.LimitExceeded):
        return JSONResponse({"error": str(exc)}, status_code=429)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "policy_version": default_policy().policy_version,
                "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "sec_user_agent_set": bool(os.environ.get("SEC_USER_AGENT")),
                "access_codes_configured": len(codes.entries()), "public_base_url": base_url,
                "spend_today_usd": round(store.spend_today(), 2), "daily_usd_cap": controls.daily_usd_cap}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_HTML

    @app.post("/api/find")
    async def api_find(req: FindRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        subject = await subject_for(authorization)
        controls.check_spend()
        policy = default_policy()
        spend = Spend(policy)
        candidates = await anyio.to_thread.run_sync(lambda: find_entities(req.name, req.website, Claude(policy), spend))
        hosted.charge(subject, controls, spend.usd)
        return {"candidates": [c.model_dump(mode="json") for c in candidates]}

    @app.post("/api/certify")
    async def api_certify(req: CertifyRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        subject = await subject_for(authorization)
        entity = Entity(name=req.name, website=req.website, hq=req.hq, legal_parent=req.legal_parent,
                        relationship_to_parent=req.relationship_to_parent)
        jobs = [hosted.Job(entity, cik=req.cik, parent_cik=req.parent_cik)]
        if req.include_parent and req.legal_parent:
            jobs.append(hosted.Job(Entity(name=req.legal_parent, website=req.parent_website), cik=req.parent_cik))
        run = lambda e, **kw: lookup(e, **kw)
        outcomes = await anyio.to_thread.run_sync(
            lambda: hosted.run_lookups(jobs, run, subject=subject, controls=controls, refresh=req.refresh))
        records = [record_from_lookup(o.result) for o in outcomes]
        path = save_card(records, data_dir() / "cards")
        return {"card_url": f"/cards/{path.name}",
                "results": [{"summary": mcp_server._summary(o.result.certification), "cached": o.cached,
                             "cached_at": o.cached_at.isoformat() if o.cached_at else None,
                             "record": r.model_dump(mode="json")} for o, r in zip(outcomes, records)]}

    @app.get("/cards/{name}")
    async def card(name: str):
        path = data_dir() / "cards" / name
        if not CARD_NAME.match(name) or not path.is_file():
            raise HTTPException(404, "Card not found.")
        return FileResponse(path, media_type="text/html")

    @app.get("/oauth/login", response_class=HTMLResponse)
    async def login_form(request: str = "") -> str:
        if not provider.pending(request):
            return _login_page(request, "This sign-in link has expired. Start again from the Claude app.", expired=True)
        return _login_page(request)

    @app.post("/oauth/login")
    async def login_submit(request: str = Form(""), access_code: str = Form("")):
        redirect = provider.complete_login(request, access_code)
        if redirect is None:
            expired = provider.pending(request) is None
            return HTMLResponse(_login_page(request, "That link has expired. Start again from the Claude app."
                                            if expired else "That access code isn't valid. Check it and try again.",
                                            expired=expired), status_code=400)
        return RedirectResponse(redirect, status_code=302)

    app.mount("/", mcp_app)  # /mcp and the OAuth endpoints
    return app


def _login_page(request_id: str, error: str | None = None, expired: bool = False) -> str:
    form = "" if expired else f"""
      <form method="post" action="/oauth/login">
        <input type="hidden" name="request" value="{html.escape(request_id)}">
        <label for="code">Access code</label>
        <input id="code" name="access_code" type="password" autocomplete="off" required placeholder="ecc_…" autofocus>
        <button type="submit">Connect to Claude</button>
      </form>"""
    err = f'<p class="err" role="alert">✕ {html.escape(error, quote=False)}</p>' if error else ""
    return LOGIN_HTML.replace("__BODY__", err + form)


_STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1a1d23; --muted:#5b6270; --line:#e3e6eb; --accent:#3b5bdb; --red:#b42318; }
@media (prefers-color-scheme: dark) { :root { --bg:#111317; --card:#1a1d23; --text:#e8eaee; --muted:#a0a7b4;
  --line:#2c313a; --accent:#8ea6ff; --red:#ff8a80; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 16px; display: grid; gap: 16px; }
.panel { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
h1 { font-size:20px; margin:0 0 4px; } .muted { color:var(--muted); } .small { font-size:13px; }
label { display:block; font-size:13px; color:var(--muted); margin:8px 0 4px; }
input { width:100%; font:inherit; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--text); }
button { font:inherit; padding:8px 14px; border-radius:8px; border:1px solid var(--accent); background:var(--accent); color:#fff; cursor:pointer; margin-top:10px; }
button.secondary { background:transparent; color:var(--accent); }
.err { color:var(--red); font-weight:600; }
"""

LOGIN_HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect · Employee Count Certifier</title>
<style>{_STYLE}</style></head><body><main><div class="panel">
<h1>Connect Claude to Employee Count Certifier</h1>
<p class="muted small">Enter the access code you were given. It links this Claude connection to you, for your daily lookup limit.</p>
__BODY__
</div></main></body></html>"""

INDEX_HTML = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Employee Count Certifier</title>
<style>{_STYLE}
.cand {{ border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin-top:8px; }}
.row {{ display:flex; gap:10px; flex-wrap:wrap; align-items:end; }} .row > div {{ flex:1 1 220px; }}
iframe {{ width:100%; border:0; min-height:1200px; background:transparent; }}
</style></head><body><main>
<div class="panel">
  <h1>Employee Count Certifier</h1>
  <p class="muted small">Certified global employee counts with sources, page references and a confidence score.</p>
  <label for="code">Access code</label>
  <input id="code" type="password" autocomplete="off" placeholder="ecc_…">
  <div class="row">
    <div><label for="name">Company or organization</label><input id="name" placeholder="e.g. Salesforce"></div>
    <div><label for="site">Website (optional)</label><input id="site" placeholder="e.g. salesforce.com"></div>
  </div>
  <button id="find">Search</button>
  <p id="status" class="small muted" role="status"></p>
  <div id="cands"></div>
</div>
<iframe id="card" title="Company card" hidden></iframe>
</main>
<script>
(function () {{
  var $ = function (id) {{ return document.getElementById(id); }};
  try {{ $("code").value = sessionStorage.getItem("ecc_code") || ""; }} catch (e) {{}}
  function say(msg, isErr) {{ $("status").textContent = msg; $("status").className = "small " + (isErr ? "err" : "muted"); }}
  function api(path, body) {{
    var code = $("code").value.trim();
    try {{ sessionStorage.setItem("ecc_code", code); }} catch (e) {{}}
    return fetch(path, {{ method: "POST", headers: {{ "Content-Type": "application/json", "Authorization": "Bearer " + code }},
      body: JSON.stringify(body) }}).then(function (r) {{
        return r.json().then(function (d) {{ if (!r.ok) throw new Error(d.error || ("Error " + r.status)); return d; }});
      }});
  }}
  function el(tag, text, cls) {{ var n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; }}
  $("find").addEventListener("click", function () {{
    if (!$("name").value.trim()) return say("Enter a company name.", true);
    say("Searching…"); $("cands").textContent = "";
    api("/api/find", {{ name: $("name").value.trim(), website: $("site").value.trim() || null }}).then(function (d) {{
      if (!d.candidates.length) return say("No matching organization found. Try adding the website.", true);
      say("Which organization do you mean?");
      d.candidates.forEach(function (c) {{
        var box = el("div", null, "cand");
        box.appendChild(el("strong", c.name));
        box.appendChild(el("div", [c.website, c.hq, c.org_type ? c.org_type.replace("_", " ") : null].filter(Boolean).join(" · "), "small muted"));
        box.appendChild(el("div", c.description, "small"));
        if (c.is_subsidiary && c.legal_parent) box.appendChild(el("div", "Part of " + c.legal_parent + " (the parent is certified too)", "small muted"));
        var go = el("button", "Certify this one"), fresh = el("button", "Certify (fresh lookup)", "secondary");
        [[go, false], [fresh, true]].forEach(function (pair) {{
          pair[0].addEventListener("click", function () {{ certify(c, pair[1]); }});
          box.appendChild(pair[0]); box.appendChild(document.createTextNode(" "));
        }});
        $("cands").appendChild(box);
      }});
    }}).catch(function (e) {{ say(e.message, true); }});
  }});
  function certify(c, refresh) {{
    say("Certifying " + c.name + "… this takes 30-90 seconds for a new lookup.");
    api("/api/certify", {{ name: c.name, website: c.website, hq: c.hq, cik: c.cik, legal_parent: c.legal_parent,
      parent_website: c.parent_website, parent_cik: c.parent_cik, refresh: refresh }}).then(function (d) {{
      var cached = d.results.some(function (r) {{ return r.cached; }});
      say(d.results.map(function (r) {{ return r.summary; }}).join(" ") + (cached ? " (cached result)" : ""));
      $("card").hidden = false; $("card").src = d.card_url;
    }}).catch(function (e) {{ say(e.message, true); }});
  }}
}})();
</script></body></html>"""


app = create_app() if os.environ.get("CERTIFIER_NO_APP") != "1" else None
