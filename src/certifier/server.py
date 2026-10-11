"""MCP server (build step 5): the Claude app calls these tools to confirm an entity and certify its
global employee count. Run locally over stdio for Claude Desktop; the same server can be served
over streamable HTTP for remote use (step 6)."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import anyio
from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer

from .card import APP_URI, app_html, save_card
from .entity import find_entities
from .llm import Claude, Spend
from .models import Certification, Entity
from .policy import default_policy
from .record import record_from_lookup
from .service import LookupResult, lookup
from .sources.edgar import Edgar

INSTRUCTIONS = """Employee Count Certifier returns a certified global employee count for an organization,
following a documented source policy (tiers 1-9, recency, corroboration, confidence 0-5).

Workflow:
1. Call find_entity with the organization name (and website if known).
2. Show the candidates to the user (name, website, description, HQ, and the global parent if it is a
   subsidiary) and ask which one they mean. Do not certify until the user confirms.
3. Call certify_employee_count with the confirmed entity's details from find_entity. By default the
   parent is certified too when the entity is a subsidiary.
4. The result renders as an interactive company card where the host supports MCP Apps; it is also saved
   as an HTML file (card_path). Present: the certified count with its qualifier, confidence level and
   score breakdown, the primary source excerpt with its link and date, and any red or yellow findings.
   Say plainly when confidence is low and why.
A lookup takes about 30-90 seconds."""

# MCP Apps: certify_employee_count renders as an interactive card (DECISIONS.md D1-D3).
apps = Apps()
apps.add_html_resource(APP_URI, app_html(), name="Company card", title="Employee count certification",
                       description="Certified employee count with confidence, findings and sources")


def _summary(cert: Certification) -> str:
    if cert.certified_count is None:
        return f"{cert.entity.name}: no usable source found (confidence 0, Unattained)."
    qualifier = {"exact": "", "approximately": "approximately ", "more_than": "more than ", "up_to": "up to "}
    basis = " full-time equivalents" if cert.count_basis == "fte" else " employees"
    selected = next((s for s in cert.sources if s.role == "selected"), None)
    source = (f"tier {cert.policy_tier} source" + (f" ({selected.url})" if selected else "")
              + (f", as of {cert.as_of_date.isoformat()}" if cert.as_of_date else ", undated"))
    return (f"{cert.entity.name}: {qualifier[cert.qualifier or 'exact']}{cert.certified_count:,}{basis} "
            f"({cert.count_type}); confidence {cert.confidence_score} ({cert.confidence_level}); {source}.")


def _result(r: LookupResult, record) -> dict[str, Any]:
    return {"summary": _summary(r.certification), "record": record.model_dump(mode="json")}


async def find_entity(name: str, website: str | None = None) -> dict[str, Any]:
    """Find the organization(s) matching a name, for the user to confirm before certifying.

    Args:
        name: Organization name as the user gave it.
        website: The organization's website, if the user knows it (improves matching).
    """
    policy = default_policy()
    spend = Spend(policy)
    candidates = await anyio.to_thread.run_sync(lambda: find_entities(name, website, Claude(policy), spend))
    return {"candidates": [c.model_dump(mode="json") for c in candidates], "cost_usd": round(spend.usd, 4),
            "next_step": "Ask the user to confirm which organization they mean (and note any global parent) "
                         "before calling certify_employee_count."}


@apps.tool(resource_uri=APP_URI)
async def certify_employee_count(name: str, website: str | None = None, hq: str | None = None,
                                 cik: int | None = None, ticker: str | None = None, legal_parent: str | None = None,
                                 parent_website: str | None = None, parent_cik: int | None = None,
                                 relationship_to_parent: str | None = None,
                                 include_parent: bool = True) -> dict[str, Any]:
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
    """
    entity = Entity(name=name, website=website, hq=hq, legal_parent=legal_parent,
                    relationship_to_parent=relationship_to_parent)
    if cik is None and ticker:
        cik = _cik_for_ticker(ticker)
    jobs = [lambda: lookup(entity, cik=cik, parent_cik=parent_cik)]
    if include_parent and legal_parent:
        parent = Entity(name=legal_parent, website=parent_website)
        jobs.append(lambda: lookup(parent, cik=parent_cik))

    def run_all() -> list[LookupResult]:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return list(pool.map(lambda job: job(), jobs))

    results = await anyio.to_thread.run_sync(run_all)
    records = [record_from_lookup(r) for r in results]
    out: dict[str, Any] = {"entity": _result(results[0], records[0])}
    if len(results) > 1:
        out["parent"] = _result(results[1], records[1])
    try:
        out["card_path"] = str(save_card(records))
    except OSError as e:  # the card file is a convenience; never fail the lookup over it
        out["card_path"] = None
        out["card_error"] = str(e)
    out["policy_version"] = default_policy().policy_version
    return out


server = MCPServer("Employee Count Certifier", instructions=INSTRUCTIONS, extensions=[apps])
server.tool()(find_entity)


def _cik_for_ticker(ticker: str) -> int | None:
    try:
        return next((c.cik for c in Edgar().find_companies(ticker, limit=1) if c.ticker == ticker.upper()), None)
    except Exception:
        return None


def main() -> None:
    transport = "streamable-http" if "--http" in sys.argv else "stdio"
    server.run(transport=transport)


if __name__ == "__main__":
    main()
