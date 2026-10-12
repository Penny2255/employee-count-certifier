"""CSV exports of a certification record: one clean summary row per entity, plus one row per source."""

from __future__ import annotations

import csv
import io

SUMMARY_FIELDS = [
    "entity_name", "website", "hq", "legal_parent", "certified_count", "qualifier", "count_basis", "count_type",
    "range_low", "range_high", "as_of_date", "as_of_estimated", "as_of_estimated_from", "adjustment_status",
    "confidence_score", "confidence_level", "confidence_arithmetic", "key_source_url", "key_source_tier",
    "key_source_section", "key_source_page", "key_source_excerpt", "indicated_range_low", "indicated_range_high",
    "direction", "direction_reason", "certified_on", "policy_version", "method",
]
SOURCE_FIELDS = [
    "entity_name", "source_id", "tier", "tier_name", "value", "qualifier", "basis", "scope", "as_of_date",
    "published_date", "used", "role", "url", "section", "page", "excerpt", "use_rationale", "tier_rationale",
]


def _csv(fields: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "" if v is None else v for k, v in row.items()})
    return buf.getvalue()


def summary_row(record: dict) -> dict:
    h, c, p, m, e = record["headline"], record["confidence"], record["primary_source"], record["methodology"], record["entity"]
    loc = p.get("location") or {}
    ir = h.get("indicated_current_range") or {}
    rng = h.get("range") or [None, None]
    return {
        "entity_name": e["name"], "website": e.get("website"), "hq": e.get("hq"), "legal_parent": e.get("legal_parent"),
        "certified_count": h.get("count"), "qualifier": h.get("qualifier"), "count_basis": h.get("count_basis"),
        "count_type": h.get("count_type"), "range_low": rng[0], "range_high": rng[1], "as_of_date": h.get("as_of_date"),
        "as_of_estimated": h.get("as_of_estimated"), "as_of_estimated_from": h.get("as_of_estimated_from"),
        "adjustment_status": h.get("adjustment_status"), "confidence_score": c["score"], "confidence_level": c["level"],
        "confidence_arithmetic": c.get("arithmetic"), "key_source_url": p.get("url"), "key_source_tier": p.get("tier"),
        "key_source_section": loc.get("section"), "key_source_page": loc.get("page_label"),
        "key_source_excerpt": p.get("excerpt"), "indicated_range_low": ir.get("low"), "indicated_range_high": ir.get("high"),
        "direction": h.get("direction"), "direction_reason": h.get("direction_reason"),
        "certified_on": (m.get("run_at") or m.get("lookup_date") or "")[:10], "policy_version": m.get("policy_version"),
        "method": m.get("method"),
    }


def source_rows(record: dict) -> list[dict]:
    name = record["entity"]["name"]
    out = []
    for s in record["sources"]["items"]:
        loc = s.get("location") or {}
        out.append({"entity_name": name, "source_id": s["id"], "tier": s["tier"], "tier_name": s["tier_name"],
                    "value": s["value"], "qualifier": s["qualifier"], "basis": s["basis"], "scope": s["scope"],
                    "as_of_date": s.get("as_of_date"), "published_date": s.get("published_date"), "used": s["used"],
                    "role": s["role"], "url": s["url"], "section": loc.get("section"), "page": loc.get("page_label"),
                    "excerpt": s.get("excerpt"), "use_rationale": s["use_rationale"], "tier_rationale": s["tier_rationale"]})
    return out


def summary_csv(records: list[dict]) -> str:
    return _csv(SUMMARY_FIELDS, [summary_row(r) for r in records])


def sources_csv(records: list[dict]) -> str:
    return _csv(SOURCE_FIELDS, [row for r in records for row in source_rows(r)])
