"""IPEDS (U.S. Department of Education, NCES): "Total all staff (excludes graduate assistants)" for a
U.S. college or university, tier 2, read from the institution profile's Human Resources data.

- The institution's IPEDS unit ID comes from College Navigator's search (exact name match only).
- The figure comes from the profile's JSON API (Human Resources, subject 13): the table "Number of
  full- and part-time staff and graduate assistants, by primary occupational category: Fall <year>",
  row "All staff (excludes graduate assistants)", column "Total". IPEDS counts staff as of November 1
  of the fall collection, about a year behind.
- Graduate assistants are recorded as separately reported and never added (SPEC.md: universities).
"""

from __future__ import annotations

import html
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Callable

from ..models import Location, Source

BASE = "https://nces.ed.gov"
PROFILE = BASE + "/ipeds/institution-profile/{unitid}"
HR_API = BASE + "/ipeds/institution-profile/api/subject/13?unitId={unitid}"
NAVIGATOR = BASE + "/collegenavigator/?q={q}"
TOTAL_ROW = "All staff (excludes graduate assistants)"
GRAD_ROW = "Graduate Assistants"
_RESULT = re.compile(r'id=(\d{6})"><strong>([^<]+)</strong></a><br />([^<]*)')
_FALL = re.compile(r"Fall (\d{4})")


@dataclass
class Institution:
    unitid: str
    name: str
    location: str


def _norm(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", html.unescape(name).lower().replace("&", " and ")))


class IPEDS:
    def __init__(self, fetch: Callable[[str, dict], str] | None = None):
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self.fetch = fetch or self._fetch

    def _fetch(self, url: str, headers: dict) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (GTM Data Certifier)", **headers})
        with self._opener.open(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def find(self, name: str) -> Institution | None:
        """The institution whose name matches exactly (College Navigator search)."""
        page = self.fetch(NAVIGATOR.format(q=urllib.parse.quote_plus(name)), {})
        target = _norm(name)
        for unitid, found, where in _RESULT.findall(page):
            if _norm(found) == target:
                return Institution(unitid, html.unescape(found).strip(), html.unescape(where).strip())
        return None

    def staff_source(self, inst: Institution) -> Source | None:
        """Total all staff (excludes graduate assistants) from the latest fall collection."""
        profile = PROFILE.format(unitid=inst.unitid)
        self.fetch(profile, {})  # sets the session cookies the data API expects
        sections = json.loads(self.fetch(HR_API.format(unitid=inst.unitid), {"Accept": "application/json"}))
        for item in sections:
            title = (item.get("header") or {}).get("label") or ""
            if "full- and part-time staff" not in title:
                continue
            fall = _FALL.search(title)
            for table in item.get("body") or []:
                cats = {c["categoryId"]: c["label"] for c in table.get("categories", [])}
                rows = {s["label"]: {cats.get(f["categoryId"]): f.get("valueRaw") for f in s.get("fields", [])}
                        for s in table.get("series", [])}
                total = _int((rows.get(TOTAL_ROW) or {}).get("Total"))
                if total is None or not fall:
                    continue
                grads = _int((rows.get(GRAD_ROW) or {}).get("Total"))
                year = int(fall.group(1))
                quote = f"{TOTAL_ROW}: Total {total:,} (Fall {year})"
                context = (f"{title}. {TOTAL_ROW}: Total {total:,}"
                           + (f"; Graduate Assistants: Total {grads:,} (reported separately)" if grads else "") + ".")
                return Source(
                    url=profile, tier=2, value=total, qualifier="exact", excerpt=quote,
                    as_of_date=date(year, 11, 1), document_type="ipeds", publisher="NCES IPEDS",
                    separately_reported={"graduate assistants": grads} if grads else None,
                    location=Location(section=f"Human Resources › {title}", page=None, context=context,
                                      note=f"IPEDS institution profile (unit ID {inst.unitid}), Human Resources: web "
                                           "page, no page numbers. Staff are counted as of November 1 of the fall "
                                           "collection."),
                    notes=[f"IPEDS Human Resources, Fall {year} collection (as of November 1, {year})."])
        return None


def _int(value) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
