"""GTM Data Certifier, hosted: web experience + JSON API + MCP over Streamable HTTP, on one engine.

    uvicorn certifier.web:app            # or: certifier-mcp --http

Routes
  GET  /                         the app (home, confirm, expedition, result; panels)
  GET  /static/app.css|app.js    one stylesheet, one script (brand tokens + card renderer included)
  GET  /assets/brand/{file}      logo, mark, favicon
  GET  /health                   {"status": "ok"} only
  GET  /admin/status             spend and configuration (access code required)
  POST /api/find                 matching entities (access code)
  POST /api/lookup               certify one confirmed entity; streams progress as server-sent events
  GET  /api/lookups/{id}         a stored result; /export?format=json|summary_csv|sources_csv; POST /rating
  GET  /cards/{file}             saved company cards (used by the Claude connector)
  GET/POST /oauth/login          access-code sign-in for the Claude custom connector (OAuth)
  /mcp, /.well-known/*, /authorize, /token, /register, /revoke   MCP and OAuth, served by the MCP SDK

Configuration comes only from environment variables (see DEPLOY.md).
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anthropic
import anyio
from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from . import hosted
from . import server as mcp_server
from .access import AccessCodes
from .card import CARD_CSS, CARD_JS, TOKENS_CSS, save_card
from .config import load_env
from .entity import find_entities
from .export import sources_csv, summary_csv
from .llm import Claude, Spend
from .models import Entity
from .oauth import SCOPE, AccessCodeOAuthProvider
from .policy import default_policy
from .record import record_from_lookup
from .service import STAGES, LookupResult, lookup
from .store import Store, data_dir

log = logging.getLogger("certifier.web")

STATIC = Path(__file__).resolve().parent / "static"
BRAND = Path(__file__).resolve().parents[2] / "assets" / "brand"
CARD_NAME = re.compile(r"^[a-z0-9-]+\.html$")
BRAND_FILES = {"hyperloop-logo.png", "hyperloop-mark-small.png", "hyperloop-mark.svg", "favicon.png"}
CONFIG_ERROR = "Service configuration issue, please try again later."
GENERIC_ERROR = "Something went wrong on our side. Please try again in a moment."
TAGLINE = "Deep sweeps. Certified answers."
RATINGS = {"great", "good", "okay", "off"}


class StartupError(SystemExit):
    """Configuration problem at startup, explained in plain words."""


class FindRequest(BaseModel):
    query: str


class LookupRequest(BaseModel):
    name: str
    website: str | None = None
    hq: str | None = None
    cik: int | None = None
    legal_parent: str | None = None
    parent_cik: int | None = None
    relationship_to_parent: str | None = None
    query: str | None = None  # what the person typed, for the review queue
    refresh: bool = False


class RatingRequest(BaseModel):
    rating: str
    comment: str | None = None


def validate_base_url(value: str | None) -> str:
    """PUBLIC_BASE_URL must be a full https URL (http is allowed only for localhost development)."""
    if not value:
        raise StartupError("PUBLIC_BASE_URL is not set. Set it to the service's full address, for example "
                           "https://your-service.onrender.com (no trailing slash).")
    parts = urlsplit(value.strip())
    local = parts.hostname in ("localhost", "127.0.0.1")
    if not parts.netloc or parts.scheme not in ("https", "http") or (parts.scheme == "http" and not local) \
            or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise StartupError(f"PUBLIC_BASE_URL must be a full https address such as https://your-service.onrender.com "
                           f"(got {value!r}). Use only the scheme and host, with no path.")
    return value.strip().rstrip("/")


def _is_config_error(exc: BaseException) -> bool:
    return isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError))


def _query_fields(q: str) -> tuple[str, str | None]:
    """"Company name or website": a domain-looking query becomes the website hint."""
    q = q.strip()
    if re.fullmatch(r"(https?://)?(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", q, re.I):
        host = urlsplit(q if "://" in q else f"https://{q}").hostname or q
        name = host.removeprefix("www.").split(".")[0]
        return name, f"https://{host}"
    return q, None


def create_app() -> FastAPI:
    load_env()
    base_url = validate_base_url(os.environ.get("PUBLIC_BASE_URL"))
    demo = os.environ.get("CERTIFIER_DEMO") == "1"
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
    policy_version = default_policy().policy_version
    css = TOKENS_CSS + (STATIC / "app.css").read_text(encoding="utf-8") + CARD_CSS
    js = CARD_JS + (STATIC / "app.js").read_text(encoding="utf-8")
    index_html = ((STATIC / "index.html").read_text(encoding="utf-8")
                  .replace("__POLICY_VERSION__", html.escape(policy_version)).replace("__TAGLINE__", TAGLINE)
                  .replace("__DEMO__", "true" if demo else "false"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="GTM Data Certifier", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def subject_for(authorization: str | None) -> str:
        token = (authorization or "")[7:].strip() if (authorization or "").lower().startswith("bearer ") else ""
        access = await provider.load_access_token(token) if token else None
        if access is None or not access.subject:
            raise HTTPException(401, "Enter a valid access code.")
        return access.subject

    # --- errors: always JSON the page can show -----------------------------------------------

    @app.exception_handler(hosted.LimitExceeded)
    async def _limit(_: Request, exc: hosted.LimitExceeded):
        return JSONResponse({"error": str(exc)}, status_code=429)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        if _is_config_error(exc):
            log.error("Anthropic API rejected the key (check ANTHROPIC_API_KEY): %s", exc)
            return JSONResponse({"error": CONFIG_ERROR}, status_code=503)
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": GENERIC_ERROR}, status_code=500)

    # --- pages and assets --------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return index_html

    @app.get("/static/app.css")
    async def app_css():
        return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=300"})

    @app.get("/static/app.js")
    async def app_js():
        return Response(js, media_type="text/javascript", headers={"Cache-Control": "public, max-age=300"})

    @app.get("/assets/brand/{name}")
    async def brand(name: str):
        if name not in BRAND_FILES or not (BRAND / name).is_file():
            raise HTTPException(404, "Not found.")
        return FileResponse(BRAND / name, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(BRAND / "favicon.png", media_type="image/png")

    # --- status --------------------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/admin/status")
    async def admin_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        await subject_for(authorization)
        return {"status": "ok", "policy_version": policy_version, "public_base_url": base_url,
                "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "sec_user_agent_set": bool(os.environ.get("SEC_USER_AGENT")),
                "access_codes_configured": len(codes.entries()), "spend_today_usd": round(store.spend_today(), 2),
                "daily_usd_cap": controls.daily_usd_cap, "daily_lookups_per_code": controls.daily_lookups,
                "cache_days": controls.cache_days}

    # --- find and certify --------------------------------------------------------------------

    @app.post("/api/find")
    async def api_find(req: FindRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        subject = await subject_for(authorization)
        name, website = _query_fields(req.query)
        if not name:
            raise HTTPException(400, "Enter a company name or website.")
        controls.check_spend()
        policy = default_policy()
        spend = Spend(policy)
        try:
            candidates = await anyio.to_thread.run_sync(lambda: find_entities(name, website, Claude(policy), spend))
        except Exception as e:
            if _is_config_error(e):
                log.error("Anthropic API rejected the key (check ANTHROPIC_API_KEY): %s", e)
                raise HTTPException(503, CONFIG_ERROR) from None
            raise
        hosted.charge(subject, controls, spend.usd)
        return {"candidates": [c.model_dump(mode="json") for c in candidates]}

    @app.post("/api/lookup")
    async def api_lookup(req: LookupRequest, authorization: str | None = Header(default=None)):
        subject = await subject_for(authorization)
        entity = Entity(name=req.name, website=req.website, hq=req.hq, legal_parent=req.legal_parent,
                        relationship_to_parent=req.relationship_to_parent)
        job = hosted.Job(entity, cik=req.cik, parent_cik=req.parent_cik)  # single lookups only
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def progress(stage: str, message: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("progress", {"stage": stage, "message": message}))

        def work() -> hosted.Outcome:
            run = lambda e, **kw: lookup(e, progress=progress, **kw)
            return hosted.run_lookups([job], run, subject=subject, controls=controls, refresh=req.refresh)[0]

        async def events():
            task = asyncio.create_task(asyncio.to_thread(work))
            yield _sse("start", {"stages": list(STAGES), "name": entity.name})
            getter: asyncio.Future | None = None
            while True:  # wake on the next progress event or the end of the lookup, whichever comes first
                getter = getter or asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, task}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    kind, payload = getter.result()
                    getter = None
                    yield _sse(kind, payload)
                elif task in done:
                    getter.cancel()
                    while not queue.empty():
                        kind, payload = queue.get_nowait()
                        yield _sse(kind, payload)
                    break
                else:
                    yield ": keep-alive\n\n"
            try:
                outcome = task.result()
            except hosted.LimitExceeded as e:
                yield _sse("error", {"message": str(e), "kind": "limit"})
                return
            except Exception as e:  # never a raw stack trace or a 500 page in the stream
                if _is_config_error(e):
                    log.error("Anthropic API rejected the key (check ANTHROPIC_API_KEY): %s", e)
                    yield _sse("error", {"message": CONFIG_ERROR, "kind": "config"})
                else:
                    log.exception("Lookup failed for %s", entity.name)
                    yield _sse("error", {"message": GENERIC_ERROR, "kind": "server"})
                return
            if outcome.cached:
                for stage in STAGES:
                    yield _sse("progress", {"stage": stage, "message": "From the certification cache"})
            yield _sse("result", _store_result(store, subject, req.query or req.name, outcome))

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- stored results, exports and ratings -------------------------------------------------

    async def stored(query_id: str, authorization: str | None) -> dict:
        await subject_for(authorization)
        row = store.get_query(query_id) if re.fullmatch(r"[0-9a-f]{32}", query_id) else None
        if row is None:
            raise HTTPException(404, "That lookup wasn't found. Run the search again.")
        return row

    @app.get("/api/lookups/{query_id}")
    async def get_lookup(query_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        row = await stored(query_id, authorization)
        record = json.loads(row["record"])
        return {"query_id": query_id, "cached": bool(row["cached"]), "certified_on": _certified_on(record),
                "record": record}

    @app.get("/api/lookups/{query_id}/export")
    async def export(query_id: str, format: str = "json", authorization: str | None = Header(default=None)):
        row = await stored(query_id, authorization)
        record = json.loads(row["record"])
        slug = re.sub(r"[^a-z0-9]+", "-", record["entity"]["name"].lower()).strip("-") or "certification"
        if format == "json":
            body, media, name = json.dumps(record, indent=2, ensure_ascii=False), "application/json", f"{slug}.json"
        elif format == "summary_csv":
            body, media, name = summary_csv([record]), "text/csv", f"{slug}-summary.csv"
        elif format == "sources_csv":
            body, media, name = sources_csv([record]), "text/csv", f"{slug}-sources.csv"
        else:
            raise HTTPException(400, "Unknown export format.")
        return Response(body, media_type=f"{media}; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/lookups/{query_id}/rating")
    async def rate(query_id: str, req: RatingRequest, authorization: str | None = Header(default=None)):
        await stored(query_id, authorization)
        subject = await subject_for(authorization)
        rating = req.rating.strip().lower()
        if rating not in RATINGS:
            raise HTTPException(400, "Choose Great, Good, Okay or Off.")
        store.save_rating(query_id, subject, rating, (req.comment or "").strip()[:2000])
        return {"ok": True}

    @app.get("/cards/{name}")
    async def card(name: str):
        path = data_dir() / "cards" / name
        if not CARD_NAME.match(name) or not path.is_file():
            raise HTTPException(404, "Card not found.")
        return FileResponse(path, media_type="text/html")

    # --- demo data for screenshots (CERTIFIER_DEMO=1 only) ----------------------------------

    if demo:
        fixtures = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "lookups"

        @app.get("/demo/record/{slug}")
        async def demo_record(slug: str) -> dict[str, Any]:
            path = fixtures / f"{slug}.json"
            if not re.fullmatch(r"[a-z0-9-]+", slug) or not path.is_file():
                raise HTTPException(404, "No demo record.")
            result = LookupResult.model_validate_json(path.read_text(encoding="utf-8"))
            record = json.loads(record_from_lookup(result).model_dump_json())
            return {"query_id": "demo", "cached": slug == "stripe", "certified_on": _certified_on(record),
                    "record": record}

    # --- OAuth sign-in page for the Claude connector ----------------------------------------

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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _certified_on(record: dict) -> str:
    m = record["methodology"]
    return (m.get("run_at") or m.get("lookup_date") or "")[:10]


def _store_result(store: Store, subject: str, query: str, outcome: hosted.Outcome) -> dict[str, Any]:
    record = record_from_lookup(outcome.result)
    record_json = record.model_dump_json()
    query_id = uuid.uuid4().hex
    store.save_query(query_id, subject, query, record.entity.name, record.headline.count, record.confidence.score,
                     outcome.cached, 0.0 if outcome.cached else outcome.result.cost_usd, record_json)
    try:
        save_card([record], data_dir() / "cards")
    except OSError:
        pass
    data = json.loads(record_json)
    return {"query_id": query_id, "cached": outcome.cached,
            "certified_on": (outcome.cached_at.date().isoformat() if outcome.cached and outcome.cached_at
                             else _certified_on(data)),
            "record": data}


def _login_page(request_id: str, error: str | None = None, expired: bool = False) -> str:
    form = "" if expired else f"""
      <form method="post" action="/oauth/login">
        <input type="hidden" name="request" value="{html.escape(request_id)}">
        <label for="code">Access code</label>
        <input id="code" name="access_code" type="password" autocomplete="off" required placeholder="ecc_…" autofocus>
        <button type="submit" class="primary">Connect to Claude</button>
      </form>"""
    err = f'<p class="error" role="alert">✕ {html.escape(error, quote=False)}</p>' if error else ""
    return LOGIN_HTML.replace("__BODY__", err + form)


LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect · GTM Data Certifier</title>
<link rel="icon" href="/assets/brand/favicon.png"><link rel="stylesheet" href="/static/app.css"></head>
<body><main class="page narrow"><section class="panel-card">
<img src="/assets/brand/hyperloop-mark-small.png" alt="Human in the Hyperloop" width="56" height="56">
<h1>Connect Claude to GTM Data Certifier</h1>
<p class="muted">Enter the access code you were given. It links this Claude connection to you, for your daily lookup limit.</p>
__BODY__
</section></main></body></html>"""


try:
    app = create_app() if os.environ.get("CERTIFIER_NO_APP") != "1" else None
except StartupError as e:  # a plain message in the deploy log, not a stack trace
    raise SystemExit(f"GTM Data Certifier can't start: {e}") from None
