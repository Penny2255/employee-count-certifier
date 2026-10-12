"""ProPublica Nonprofit Explorer: Form 990 Part I line 5 (tier 2) for U.S. nonprofits.

Line 5 is "Total number of individuals employed in calendar year <YYYY>" (the W-3 count). The API
has no employee field, so the figure is read from each filing's full-text rendering.
"""

from __future__ import annotations

import gzip
import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from ..models import Location, Source

BASE = "https://projects.propublica.org/nonprofits"
_LINE5 = re.compile(r"individuals employed in calendar year (\d{4}).{0,80}?\.\s*5\s+([\d,]+)", re.I)
_SIGNED = re.compile(r"Preparer's signature\s+Date\s+(\d{4}-\d{2}-\d{2})", re.I)


@dataclass
class Nonprofit:
    ein: int
    name: str
    city: str | None
    state: str | None


@dataclass
class ProPublica:
    user_agent: str = "employee-count-certifier (research tool)"
    fetch: Callable[[str], str] | None = None
    _last: float = 0.0
    _cache: dict[str, str] = field(default_factory=dict)

    def _get(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        if self.fetch is not None:
            body = self.fetch(url)
        else:
            wait = 0.5 - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":  # newer filings are served gzipped regardless of Accept-Encoding
                raw = gzip.decompress(raw)
            body = raw.decode("utf-8", "replace")
            self._last = time.monotonic()
        self._cache[url] = body
        return body

    def search(self, name: str) -> list[Nonprofit]:
        data = json.loads(self._get(f"{BASE}/api/v2/search.json?q={urllib.parse.quote(name)}"))
        return [Nonprofit(int(o["ein"]), o["name"], o.get("city"), o.get("state")) for o in data.get("organizations", [])]

    def exact_match(self, name: str) -> Nonprofit | None:
        """Only an exact (case- and punctuation-insensitive) name match; never a guess."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
        matches = [n for n in self.search(name) if norm(n.name) == norm(name)]
        return matches[0] if len(matches) == 1 else None

    def line5_sources(self, ein: int, limit: int = 3) -> list[Source]:
        """Form 990 line 5 from the most recent filings, newest first."""
        page = self._get(f"{BASE}/organizations/{ein}")
        object_ids = sorted(set(re.findall(rf"/organizations/{ein}/(\d{{18}})/full", page)), reverse=True)
        out = []
        for oid in object_ids:
            text = _text(self._get(f"{BASE}/full_text/{oid}/IRS990"))
            m = _LINE5.search(text)
            if not m:
                continue
            year, count = int(m.group(1)), int(m.group(2).replace(",", ""))
            signed = _SIGNED.search(text)
            start = text.rfind("5 Total number", 0, m.end())
            start = start if start >= 0 else max(0, m.start() - 40)
            end = text.find("7a ", m.end())
            passage = re.sub(r"\s+", " ", text[start: end if 0 < end - m.end() < 400 else m.end() + 160]).strip()
            out.append(Source(
                url=f"{BASE}/organizations/{ein}/{oid}/full", tier=2, value=count, qualifier="exact",
                document_type="form_990", publisher="ProPublica Nonprofit Explorer",
                excerpt=re.sub(r"\s+", " ", text[_line_start(text, m): m.end()]).strip(),
                as_of_date=date(year, 12, 31),
                published_date=date.fromisoformat(signed.group(1)) if signed else None,
                location=Location(
                    section="Form 990 › Part I (Summary) › line 5",
                    page="1", page_basis="form", context="…" + passage + "…",
                    note=f"Line 5 is the total number of individuals employed in calendar year {year} (cross-referenced "
                         f"to Part V, line 2a), on page 1 of the IRS Form 990 as filed; shown on ProPublica's "
                         "full-filing view."),
                notes=["W-3 count of everyone paid during the calendar year; can exceed point-in-time headcount."]))
            if len(out) == limit:
                break
        return out


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def _line_start(text: str, m: re.Match) -> int:
    """Start of line 5's own wording ("Total number of individuals employed ...")."""
    start = text.rfind("Total number", max(0, m.start() - 60), m.end())
    return start if start >= 0 else m.start()
