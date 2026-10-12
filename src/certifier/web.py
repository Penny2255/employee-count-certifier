# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""GTM Data Certifier, hosted: web experience + JSON API + MCP over Streamable HTTP, on one engine.

    uvicorn certifier.web:app            # or: certifier-mcp --http

Routes
  GET  /                         the app (home, confirm, expedition, result; panels)
  GET  /static/app.css|app.js    one stylesheet, one script (brand tokens + card renderer included)
  GET  /assets/brand/{file}      logo, mark, favicon
  GET  /health                   {"status": "ok"} only
  GET  /admin, /api/admin/summary   today's spend, lookups, cache hits, visitors, limit hits, ratings (admin code)
  GET  /admin/status             configuration (admin code)
  GET  /api/allowance            approximate searches left today (open beta)
  GET  /api/samples[/{slug}]     pre-certified sample results (free)
  POST /api/find                 matching entities
  POST /api/lookup               certify one confirmed entity; streams progress as server-sent events
  GET  /api/lookups/{id}         a stored result; /export?format=json|summary_csv|sources_csv|pptx|docx[&theme=dark]; POST /rating
  GET  /cards/{file}             saved company cards (used by the Claude connector)
  GET  /logos/{host}.png         company logos, fetched once server-side and cached (no third-party calls from browsers)
  GET/POST /oauth/login          connector sign-in: "Continue as beta guest", or an admin code

Open beta: no codes for visitors. Allowances are keyed on a hashed client IP (see hosted.py); admin
codes (CERTIFIER_ACCESS_CODES) bypass them. Max 10 API requests a minute per IP.
  /mcp, /.well-known/*, /authorize, /token, /register, /revoke   MCP and OAuth, served by the MCP SDK

Configuration comes only from environment variables (see DEPLOY.md).
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
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

from . import hosted, office, taxonomy
from . import server as mcp_server
from .access import AccessCodes
from .card import CARD_CSS, CARD_JS, TOKENS_CSS, save_card
from .notice import OWNER_LINE, ROBOTS, ROBOTS_META, ROBOTS_TXT, TERMS_HTML
from .config import load_env
from .entity import find_entities
from .export import sources_csv, summary_csv
from .llm import Claude, Spend
from .models import Entity
from .oauth import SCOPE, BetaOAuthProvider
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
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
SAMPLES = ("salesforce", "stripe", "adobe", "gong", "workday", "donor-network-west", "nextera-energy", "uc-davis")
RATE_LIMITED = "Too many requests. Please wait a minute and try again."
PNG_SIGNATURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
LOGO_HOST = re.compile(r"(?:[a-z0-9-]{1,63}\.){1,4}[a-z]{2,24}")
# Not rate limited: static files and health checks (page loads, Render), and the MCP/OAuth endpoints, whose
# requests all arrive from Anthropic's servers (the connector is limited per guest by its allowance instead).
RATE_EXEMPT = ("/health", "/static/", "/assets/", "/favicon.ico", "/cards/", "/logos/", "/mcp", "/.well-known/", "/authorize",
               "/token", "/register", "/revoke", "/robots.txt", "/terms")


def client_ip(request: Request) -> str:
    """The real client IP behind Render's proxy: the entry CERTIFIER_PROXY_HOPS from the right of
    X-Forwarded-For (proxies append; entries further left are client-supplied and can't be trusted)."""
    try:
        hops = int(os.environ.get("CERTIFIER_PROXY_HOPS", "1") or 1)
    except ValueError:
        hops = 1
    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if hops > 0 and len(chain) >= hops:
        return chain[-hops]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Sliding one-minute window per key (in memory; one instance)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            if len(self.hits) > 50_000:  # forget idle keys
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                    del self.hits[k]
            return True


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
    provider = BetaOAuthProvider(store, codes, base_url)
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
                  .replace("__DEMO__", "true" if demo else "false")
                  .replace("__GLOSSARY__", taxonomy.glossary_html())
                  .replace("__MCP_URL__", html.escape(base_url + "/mcp")).replace("__ROBOTS_META__", ROBOTS_META))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="GTM Data Certifier", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    limiter = RateLimiter(int(_env_int("CERTIFIER_RATE_LIMIT_PER_MIN", 10)))

    def admin_name(authorization: str | None) -> str | None:
        token = (authorization or "")[7:].strip() if (authorization or "").lower().startswith("bearer ") else ""
        return codes.verify(token) if token else None

    def who_for(request: Request, authorization: str | None) -> hosted.Who:
        """An admin (valid admin code) or a beta visitor (today's bucket for their hashed IP)."""
        name = admin_name(authorization)
        if name:
            return hosted.Who("admin:" + name, admin=True)
        return controls.visitor(controls.ip_key(client_ip(request)))

    def require_admin(authorization: str | None) -> str:
        name = admin_name(authorization)
        if not name:
            raise HTTPException(401, "Enter a valid admin code.")
        return name

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        path = request.url.path
        if not path.startswith(RATE_EXEMPT) and not admin_name(request.headers.get("authorization")):
            key = hashlib.sha256(client_ip(request).encode()).hexdigest()  # kept in memory for a minute only
            if not limiter.allow(key):
                return JSONResponse({"error": RATE_LIMITED}, status_code=429)
        return await call_next(request)

    # Declared after rate_limit, so it wraps it: every response, including 429s, /mcp and the API, says no
    # indexing, archiving or AI use.
    @app.middleware("http")
    async def robots_header(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = ROBOTS
        return response

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

    @app.get("/robots.txt")
    async def robots_txt():
        return Response(ROBOTS_TXT, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/terms", response_class=HTMLResponse)
    async def terms() -> str:
        return TERMS_HTML

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
        require_admin(authorization)
        return {"status": "ok", "policy_version": policy_version, "public_base_url": base_url,
                "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "sec_user_agent_set": bool(os.environ.get("SEC_USER_AGENT")),
                "admin_codes_configured": len(codes.entries()), "spend_today_usd": round(store.spend_today(), 2),
                "daily_usd_cap": controls.daily_usd_cap, "visitor_usd_per_day": controls.visitor_usd,
                "cache_days": controls.cache_days}

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page() -> str:
        return ADMIN_HTML

    @app.get("/api/admin/summary")
    async def admin_summary(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        name = require_admin(authorization)
        chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        seen = client_ip(request)
        return {"admin": name, "today": store.summary_today(), "daily_usd_cap": controls.daily_usd_cap,
                "visitor_usd_per_day": controls.visitor_usd,
                "ratings": [{k: r.get(k) for k in ("created_at", "rating", "comment", "query", "entity_name",
                                                   "certified_count", "confidence")} for r in store.ratings(20)],
                # To check the proxy setting: your own request, with the last part of the IP masked.
                "proxy": {"x_forwarded_for_entries": len(chain), "proxy_hops": os.environ.get("CERTIFIER_PROXY_HOPS", "1"),
                          "your_ip_as_seen": re.sub(r"[^.:]+$", "x", seen)}}

    @app.get("/api/allowance")
    async def allowance(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        who = who_for(request, authorization)
        left = controls.searches_left(who)
        return {"admin": who.admin, "searches_left": left,
                "message": None if left is None or left > 0 else
                (hosted.GLOBAL_LIMIT if store.used(who.bucket)[1] + controls.lookup_reserve_usd > controls.daily_usd_cap
                 else hosted.VISITOR_LIMIT)}

    # --- sample results (free) ----------------------------------------------------------------

    def sample(slug: str) -> dict[str, Any]:
        path = SAMPLES_DIR / f"{slug}.json"
        if slug not in SAMPLES or not path.is_file():
            raise HTTPException(404, "No such sample.")
        result = LookupResult.model_validate_json(path.read_text(encoding="utf-8"))
        record = json.loads(record_from_lookup(result).model_dump_json())
        return {"query_id": "sample-" + slug, "sample": True, "cached": True, "certified_on": _certified_on(record),
                "record": record}

    @app.get("/api/samples")
    async def samples() -> dict[str, Any]:
        out = []
        for slug in SAMPLES:
            if (SAMPLES_DIR / f"{slug}.json").is_file():
                rec = sample(slug)["record"]
                out.append({"slug": slug, "name": rec["entity"]["name"], "website": rec["entity"]["website"],
                            "count": rec["headline"]["count"], "qualifier": rec["headline"]["qualifier"],
                            "score": rec["confidence"]["score"], "level": rec["confidence"]["level"],
                            "certified_on": _certified_on(rec)})
        return {"samples": out}

    @app.get("/api/samples/{slug}")
    async def get_sample(slug: str) -> dict[str, Any]:
        return sample(slug)

    # --- find and certify --------------------------------------------------------------------

    @app.post("/api/find")
    async def api_find(req: FindRequest, request: Request,
                       authorization: str | None = Header(default=None)) -> dict[str, Any]:
        who = who_for(request, authorization)
        name, website = _query_fields(req.query)
        if not name:
            raise HTTPException(400, "Enter a company name or website.")
        policy = default_policy()
        try:
            with controls.metered(who, hosted.FIND_RESERVE_USD) as spend:
                candidates = await anyio.to_thread.run_sync(lambda: find_entities(name, website, Claude(policy), spend))
        except hosted.LimitExceeded:
            raise
        except Exception as e:
            if _is_config_error(e):
                log.error("Anthropic API rejected the key (check ANTHROPIC_API_KEY): %s", e)
                raise HTTPException(503, CONFIG_ERROR) from None
            raise
        return {"candidates": [c.model_dump(mode="json") for c in candidates],
                "searches_left": controls.searches_left(who)}

    @app.post("/api/lookup")
    async def api_lookup(req: LookupRequest, request: Request, authorization: str | None = Header(default=None)):
        who = who_for(request, authorization)
        entity = Entity(name=req.name, website=req.website, hq=req.hq, legal_parent=req.legal_parent,
                        relationship_to_parent=req.relationship_to_parent)
        job = hosted.Job(entity, cik=req.cik, parent_cik=req.parent_cik)  # single lookups only
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def progress(stage: str, message: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("progress", {"stage": stage, "message": message}))

        def work() -> hosted.Outcome:
            run = lambda e, **kw: lookup(e, progress=progress, **kw)
            return hosted.run_lookups([job], run, who=who, controls=controls, refresh=req.refresh)[0]

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
                yield _sse("error", {"message": str(e), "kind": e.kind})
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
            yield _sse("result", {**_store_result(store, who.bucket, req.query or req.name, outcome),
                                  "searches_left": controls.searches_left(who)})

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- stored results, exports and ratings -------------------------------------------------

    async def stored(query_id: str) -> dict:
        if query_id.startswith("sample-"):
            data = sample(query_id[7:])
            return {"record": json.dumps(data["record"]), "cached": True}
        row = store.get_query(query_id) if re.fullmatch(r"[0-9a-f]{32}", query_id) else None
        if row is None:
            raise HTTPException(404, "That lookup wasn't found. Run the search again.")
        return row

    @app.get("/api/lookups/{query_id}")
    async def get_lookup(query_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        row = await stored(query_id)
        record = json.loads(row["record"])
        return {"query_id": query_id, "cached": bool(row["cached"]), "certified_on": _certified_on(record),
                "record": record}

    @app.get("/api/lookups/{query_id}/export")
    async def export(query_id: str, format: str = "json", theme: str = "light"):
        row = await stored(query_id)
        record = json.loads(row["record"])
        slug = re.sub(r"[^a-z0-9]+", "-", record["entity"]["name"].lower()).strip("-") or "certification"
        if format in ("pptx", "docx"):  # slides (light or dark) and the full Word document
            if format == "pptx":
                theme = theme if theme in ("light", "dark") else "light"
                logo = await anyio.to_thread.run_sync(lambda: _company_logo(record))
                data = await anyio.to_thread.run_sync(lambda: office.deck(record, theme, logo=logo, site_url=base_url))
                media, name = "application/vnd.openxmlformats-officedocument.presentationml.presentation",                     f"{slug}-certification-{theme}.pptx"
            else:
                data = await anyio.to_thread.run_sync(lambda: office.document(record))
                media, name = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",                     f"{slug}-certification.docx"
            return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
        if format == "json":
            body, media, name = (json.dumps({"notice": OWNER_LINE, **record}, indent=2, ensure_ascii=False),
                                 "application/json", f"{slug}.json")
        elif format == "summary_csv":
            body, media, name = summary_csv([record]), "text/csv", f"{slug}-summary.csv"
        elif format == "sources_csv":
            body, media, name = sources_csv([record]), "text/csv", f"{slug}-sources.csv"
        else:
            raise HTTPException(400, "Unknown export format.")
        return Response(body, media_type=f"{media}; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/lookups/{query_id}/rating")
    async def rate(query_id: str, req: RatingRequest, request: Request,
                   authorization: str | None = Header(default=None)):
        await stored(query_id)
        subject = who_for(request, authorization).bucket
        rating = req.rating.strip().lower()
        if rating not in RATINGS:
            raise HTTPException(400, "Choose Great, Good, Okay or Off.")
        store.save_rating(query_id, subject, rating, (req.comment or "").strip()[:2000])
        return {"ok": True}

    @app.get("/logos/{name}")
    async def logo(name: str):
        host = name.removesuffix(".png").lower()
        if not LOGO_HOST.fullmatch(host):
            raise HTTPException(404, "No logo.")
        path = data_dir() / "logos" / f"{host}.png"
        if not path.is_file():
            data = await anyio.to_thread.run_sync(lambda: _fetch_logo(host))
            if data is None:
                raise HTTPException(404, "No logo.")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})

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
        if demo and request == "demo":  # screenshots only
            return _login_page(request)
        if not provider.pending(request):
            return _login_page(request, "This sign-in link has expired. Start again from the Claude app.", expired=True)
        return _login_page(request)

    @app.post("/oauth/login")
    async def login_submit(http: Request, request: str = Form(""), access_code: str = Form(""),
                           mode: str = Form("guest")):
        if mode == "admin":
            redirect = provider.complete_login(request, access_code)
        else:  # this page runs in the person's own browser: bind the connector to its hashed IP
            redirect = provider.complete_guest(request, controls.ip_key(client_ip(http)))
        if redirect is None:
            expired = provider.pending(request) is None
            return HTMLResponse(_login_page(request, "That link has expired. Start again from the Claude app."
                                            if expired else "That admin code isn't valid. Check it, or continue as a "
                                            "beta guest.", expired=expired), status_code=400)
        return RedirectResponse(redirect, status_code=302)

    app.mount("/", mcp_app)  # /mcp and the OAuth endpoints
    return app


def _company_logo(record: dict) -> bytes | None:
    """The organization's logo for the slides: the cached icon for its website, fetched once if needed."""
    website = record["entity"].get("website") or ""
    host = (urlsplit(website if "://" in website else "https://" + website).hostname or "").removeprefix("www.")
    if not website or not LOGO_HOST.fullmatch(host):
        return None
    path = data_dir() / "logos" / f"{host}.png"
    if path.is_file():
        return path.read_bytes()
    data = _fetch_logo(host)
    if data:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return data


def _fetch_logo(host: str) -> bytes | None:
    """A 128px icon for a company's site via Google's favicon service; None when there isn't one."""
    import urllib.request
    url = f"https://www.google.com/s2/favicons?domain={host}&sz=128"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "GTM Data Certifier"}),
                                    timeout=8) as r:
            data = r.read(200_000)
            return data if r.status == 200 and data.startswith(PNG_SIGNATURE) else None
    except Exception:
        return None


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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _login_page(request_id: str, error: str | None = None, expired: bool = False) -> str:
    rid = html.escape(request_id)
    form = "" if expired else f"""
      <form method="post" action="/oauth/login">
        <input type="hidden" name="request" value="{rid}">
        <input type="hidden" name="mode" value="guest">
        <button type="submit" class="primary wide" autofocus>Continue as beta guest</button>
      </form>
      <p class="small muted">Open beta: about 10 new lookups a day, shared with the website from this network.
        Cached and sample results are free.</p>
      <details class="admin-code"><summary class="small">Have an admin code?</summary>
        <form method="post" action="/oauth/login">
          <input type="hidden" name="request" value="{rid}">
          <input type="hidden" name="mode" value="admin">
          <label for="code" class="small">Admin code</label>
          <div class="code-row"><input id="code" name="access_code" type="password" autocomplete="off" required
            placeholder="ecc_…"><button type="submit" class="secondary">Connect</button></div>
        </form>
      </details>"""
    err = f'<p class="error" role="alert">✕ {html.escape(error, quote=False)}</p>' if error else ""
    return LOGIN_HTML.replace("__BODY__", err + form)


LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect · GTM Data Certifier</title>
<meta name="robots" content="noindex, nofollow, noarchive, noai, noimageai">
<link rel="icon" href="/assets/brand/favicon.png"><link rel="stylesheet" href="/static/app.css"></head>
<body><main class="page narrow"><section class="panel-card">
<img src="/assets/brand/hyperloop-mark-small.png" alt="Human in the Hyperloop" width="56" height="56">
<h1>Connect Claude to GTM Data Certifier</h1>
<p class="muted">GTM Data Certifier is in open beta. Continue as a guest to add it to Claude; no sign-up needed.</p>
__BODY__
</section></main></body></html>"""


ADMIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Admin · GTM Data Certifier</title>
<meta name="robots" content="noindex, nofollow, noarchive, noai, noimageai">
<link rel="icon" href="/assets/brand/favicon.png"><link rel="stylesheet" href="/static/app.css"></head>
<body><main class="page admin">
<h1 class="view-title">Beta admin</h1>
<form id="admin-form" class="code-form" hidden><p class="small">Enter your admin code. It's remembered in this browser.</p>
<div class="code-row"><label class="sr-only" for="code">Admin code</label><input id="code" type="password" autocomplete="off"
 placeholder="ecc_…" required><button class="primary" type="submit">Open</button></div></form>
<p id="admin-status" class="status-line" role="status" aria-live="polite"></p>
<section id="admin-body" hidden>
<p class="muted small" id="admin-day"></p>
<div class="stat-grid" id="stats"></div>
<h2>Latest ratings</h2><div class="table-wrap"><table class="admin-table" id="ratings"></table></div>
<h2>Proxy check</h2><p class="small muted" id="proxy"></p>
<p><a href="/">Back to GTM Data Certifier</a></p>
</section></main>
<script>
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function code() { try { return localStorage.getItem("gtm_code") ? JSON.parse(localStorage.getItem("gtm_code")) : ""; } catch (e) { return ""; } }
  function cell(tag, text) { var n = document.createElement(tag); n.textContent = text == null ? "" : String(text); return n; }
  function stat(label, value) { var d = document.createElement("div"); d.className = "stat"; d.appendChild(cell("span", label)); d.appendChild(cell("strong", value)); return d; }
  function load() {
    fetch("/api/admin/summary", { headers: { "Authorization": "Bearer " + code() } }).then(function (r) {
      return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || "Not allowed."); return d; });
    }).then(function (d) {
      $("admin-form").hidden = true; $("admin-body").hidden = false; $("admin-status").textContent = "";
      var t = d.today, stats = $("stats"); stats.textContent = "";
      $("admin-day").textContent = "Today (Pacific): " + t.day + " · signed in as " + d.admin;
      stats.appendChild(stat("Spend today", "$" + Number(t.spent).toFixed(2) + " of $" + Number(d.daily_usd_cap).toFixed(2)));
      stats.appendChild(stat("Reserved now", "$" + Number(t.reserved).toFixed(2)));
      stats.appendChild(stat("New lookups", t.lookups));
      stats.appendChild(stat("Cache hits", t.cache_hits));
      stats.appendChild(stat("Distinct visitors", t.visitors));
      stats.appendChild(stat("Limit hits", t.limit_hits));
      var table = $("ratings"); table.textContent = "";
      var head = document.createElement("tr"); ["When", "Rating", "Comment", "Search", "Organization", "Count", "Conf."].forEach(function (h) { head.appendChild(cell("th", h)); });
      table.appendChild(head);
      d.ratings.forEach(function (r) {
        var tr = document.createElement("tr");
        [r.created_at, r.rating, r.comment, r.query, r.entity_name, r.certified_count, r.confidence].forEach(function (v) { tr.appendChild(cell("td", v)); });
        table.appendChild(tr);
      });
      if (!d.ratings.length) { var tr = document.createElement("tr"); var td = cell("td", "No ratings yet."); td.colSpan = 7; tr.appendChild(td); table.appendChild(tr); }
      $("proxy").textContent = "X-Forwarded-For entries on your request: " + d.proxy.x_forwarded_for_entries +
        " · CERTIFIER_PROXY_HOPS = " + d.proxy.proxy_hops + " · your IP as seen: " + d.proxy.your_ip_as_seen +
        ". If this isn't your own IP, adjust CERTIFIER_PROXY_HOPS.";
    }).catch(function (err) { $("admin-form").hidden = false; $("admin-status").textContent = code() ? err.message : ""; });
  }
  $("admin-form").addEventListener("submit", function (e) {
    e.preventDefault();
    try { localStorage.setItem("gtm_code", JSON.stringify($("code").value.trim())); } catch (err) {}
    $("code").value = ""; load();
  });
  load();
})();
</script></body></html>"""


try:
    app = create_app() if os.environ.get("CERTIFIER_NO_APP") != "1" else None
except StartupError as e:  # a plain message in the deploy log, not a stack trace
    raise SystemExit(f"GTM Data Certifier can't start: {e}") from None
