"""MCP server: the Claude app calls these tools to confirm an entity and certify its global
employee count.

- Local (Claude Desktop over stdio): `certifier-mcp`. No sign-in, no limits, no cache.
- Hosted (Streamable HTTP at /mcp): created by `certifier.web` with OAuth sign-in by access code,
  per-user daily limits, a global daily dollar cap, and a 30-day certification cache.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

import anyio
from mcp.server.apps import Apps
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent

from . import hosted
from .card import APP_URI, app_html, save_card
from .entity import find_entities
from .llm import Claude, Spend
from .models import Certification, Entity
from .policy import default_policy
from .record import record_from_lookup
from .service import lookup
from .sources.edgar import Edgar
from .store import data_dir

INSTRUCTIONS = """Employee Count Certifier returns a certified global employee count for an organization,
following a documented source policy (tiers 1-9, recency, corroboration, confidence 0-5).

Workflow:
1. Call find_entity with the organization name (and website if known).
2. Show the candidates to the user (name, website, description, HQ, and the global parent if it is a
   subsidiary) and ask which one they mean. Do not certify until the user confirms.
3. Call certify_employee_count with the confirmed entity's details from find_entity. By default the
   parent is certified too when the entity is a subsidiary. Results are cached for 30 days on the hosted
   service; pass refresh=true only when the user asks for a fresh lookup.
4. The result renders as an interactive company card where the host supports MCP Apps (card_url or
   card_path also links to it). Present: the certified count with its qualifier, as-of date (say when it
   is estimated or pre-adjustment), confidence and score breakdown, the key source excerpt with its link,
   section and page, any indicated current range, and red or yellow findings. Say plainly when
   confidence is low and why.
A new lookup takes about 30-90 seconds. If a daily limit is reached, tell the user the message as given."""

# Set by certifier.web when running as the hosted service.
_controls: hosted.Controls | None = None
_public_base_url: str | None = None


def configure_hosting(controls: hosted.Controls | None, public_base_url: str | None) -> None:
    global _controls, _public_base_url
    _controls, _public_base_url = controls, (public_base_url or "").rstrip("/") or None


def _who() -> hosted.Who | None:
    """The beta guest (bound to their sign-in IP) or admin behind this request; None for local use."""
    token = get_access_token()
    if token is None or _controls is None:
        return None
    return _controls.resolve(token.subject)


def _plain_error(message: str) -> Any:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


@contextmanager
def _local_spend() -> Iterator[Spend]:
    yield Spend(default_policy())


def _summary(cert: Certification) -> str:
    if cert.certified_count is None:
        return f"{cert.entity.name}: no usable source found (confidence 0, Unattained)."
    qualifier = {"exact": "", "approximately": "approximately ", "more_than": "more than ", "up_to": "up to "}
    basis = " full-time equivalents" if cert.count_basis == "fte" else " employees"
    selected = next((s for s in cert.sources if s.role == "selected"), None)
    as_of = (f", as of {cert.as_of_date.isoformat()}" + (" (estimated)" if cert.as_of_estimated else "")
             if cert.as_of_date else ", undated")
    source = f"tier {cert.policy_tier} source" + (f" ({selected.url})" if selected else "") + as_of
    extra = " Pre-adjustment: changes after the as-of date are known." if cert.pre_adjustment else ""
    return (f"{cert.entity.name}: {qualifier[cert.qualifier or 'exact']}{cert.certified_count:,}{basis} "
            f"({cert.count_type}); confidence {cert.confidence_score} ({cert.confidence_level}); {source}.{extra}")


def _result(o: hosted.Outcome, record) -> dict[str, Any]:
    out = {"summary": _summary(o.result.certification), "record": record.model_dump(mode="json")}
    if o.cached:
        out["cached_at"] = o.cached_at.isoformat() if o.cached_at else None
    return out


async def find_entity(name: str, website: str | None = None) -> dict[str, Any]:
    """Find the organization(s) matching a name, for the user to confirm before certifying.

    Args:
        name: Organization name as the user gave it.
        website: The organization's website, if the user knows it (improves matching).
    """
    who = _who()
    policy = default_policy()
    try:
        with (_controls.metered(who, hosted.FIND_RESERVE_USD) if _controls else _local_spend()) as spend:
            candidates = await anyio.to_thread.run_sync(lambda: find_entities(name, website, Claude(policy), spend))
    except hosted.LimitExceeded as e:  # plain-language beta message, shown as is
        return _plain_error(str(e))  # the beta message as is, without the SDK's tool-error prefix
    return {"candidates": [c.model_dump(mode="json") for c in candidates], "cost_usd": round(spend.usd, 4),
            "next_step": "Ask the user to confirm which organization they mean (and note any global parent) "
                         "before calling certify_employee_count."}


async def certify_employee_count(name: str, website: str | None = None, hq: str | None = None,
                                 cik: int | None = None, ticker: str | None = None, legal_parent: str | None = None,
                                 parent_website: str | None = None, parent_cik: int | None = None,
                                 relationship_to_parent: str | None = None, include_parent: bool = True,
                                 refresh: bool = False) -> dict[str, Any]:
    """Certify the global employee count of a user-confirmed organization (and its parent).

    Args:
        name: Confirmed organization name.
        website: Organization website.
        hq: Headquarters location.
        cik: SEC CIK if the organization files with the SEC (from find_entity). Always pass it when
            known: tier 1 filings are then read from SEC EDGAR directly.
        ticker: U.S. stock ticker, used to find the CIK when `cik` is not given.
        legal_parent: Ultimate global parent, if the organization is a subsidiary, campus or affiliate.
        parent_website: Parent's website.
        parent_cik: Parent's SEC CIK, if any.
        relationship_to_parent: e.g. "wholly owned subsidiary".
        include_parent: Also certify the parent (default true when a parent is given).
        refresh: Run a new lookup even if a cached certification exists (hosted service only).
    """
    entity = Entity(name=name, website=website, hq=hq, legal_parent=legal_parent,
                    relationship_to_parent=relationship_to_parent)
    if cik is None and ticker:
        cik = _cik_for_ticker(ticker)
    jobs = [hosted.Job(entity, cik=cik, parent_cik=parent_cik)]
    if include_parent and legal_parent:
        jobs.append(hosted.Job(Entity(name=legal_parent, website=parent_website), cik=parent_cik))

    who = _who()
    run = lambda e, **kw: lookup(e, **kw)  # resolves the module-level `lookup` at call time (tests replace it)
    try:
        outcomes = await anyio.to_thread.run_sync(
            lambda: hosted.run_lookups(jobs, run, who=who, controls=_controls, refresh=refresh))
    except hosted.LimitExceeded as e:  # shown to the user as is
        return _plain_error(str(e))  # the beta message as is, without the SDK's tool-error prefix
    records = [record_from_lookup(o.result) for o in outcomes]
    out: dict[str, Any] = {"entity": _result(outcomes[0], records[0])}
    if len(outcomes) > 1:
        out["parent"] = _result(outcomes[1], records[1])
    try:
        if _public_base_url:
            path = save_card(records, data_dir() / "cards")
            out["card_url"] = f"{_public_base_url}/cards/{path.name}"
        else:
            out["card_path"] = str(save_card(records))
    except OSError as e:  # the card file is a convenience; never fail the lookup over it
        out["card_error"] = str(e)
    out["policy_version"] = default_policy().policy_version
    return out


def _cik_for_ticker(ticker: str) -> int | None:
    try:
        return next((c.cik for c in Edgar().find_companies(ticker, limit=1) if c.ticker == ticker.upper()), None)
    except Exception:
        return None


def create_server(**auth_kwargs: Any) -> MCPServer:
    """A server with the card app and both tools. `auth_kwargs` (auth_server_provider, auth) turn on
    OAuth for the hosted service."""
    apps = Apps()
    apps.add_html_resource(APP_URI, app_html(), name="Company card", title="Employee count certification",
                           description="Certified employee count with confidence, findings and sources")
    apps.tool(resource_uri=APP_URI)(certify_employee_count)
    mcp = MCPServer("Employee Count Certifier", instructions=INSTRUCTIONS, extensions=[apps], **auth_kwargs)
    mcp.tool()(find_entity)
    return mcp


server = create_server()  # local stdio server for Claude Desktop


def main() -> None:
    if "--http" in sys.argv:  # hosted mode: web app + MCP over Streamable HTTP
        import uvicorn

        uvicorn.run("certifier.web:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
