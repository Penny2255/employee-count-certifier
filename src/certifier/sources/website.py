# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Company website (tier 4): read the organization's own About pages for headcount statements,
including stat tiles whose numbers live in embedded page data ("1,500" + "Employees")."""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

ABOUT_PATHS = ("", "/about", "/about/", "/about-us", "/company", "/company/about", "/en/about")
_NUM = r"(?<![\d,.])(\d{1,3}(?:,\d{3})+|\d{2,7})(?![\d,])\+?"
_WORKERS = r"(employees|team members|teammates|people|staff|associates|colleagues|workers)"
# Number then label within a short span of markup/JSON, or label then number. The filler may not
# cross a JSON object boundary ({ or }), so one stat tile's number never pairs with another's label.
_FILLER = r"(?:<[^>]+>|[\s\"',:\[\]\\]|value|description|label|text|suffix|prefix|null|true|false|animateNumber){0,40}?"
_TILE = re.compile(rf"{_NUM}[^0-9<>{{}}]{{0,8}}{_FILLER}{_WORKERS}\b", re.I)
_TILE_REV = re.compile(rf"\b{_WORKERS}\b{_FILLER}{_NUM}", re.I)


@dataclass
class PageSnippet:
    url: str
    text: str  # "1,500 Employees (page context: ...)"

    @property
    def figure(self) -> str:
        return self.text.split(" (page context:")[0]

    @property
    def context(self) -> str:
        return self.text.split("(page context: ", 1)[-1].rstrip(")")

    @property
    def readable_context(self) -> str:
        """Stat tiles as 'Label: value' pairs when the page stores them as data; otherwise the cleaned text."""
        return readable_tiles(self.context) or self.context


def _get(url: str, user_agent: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if "html" not in (r.headers.get("Content-Type") or "html"):
                return None
            return r.read(3_000_000).decode("utf-8", "replace")
    except Exception:
        return None


def stat_snippets(raw: str) -> list[str]:
    """Readable snippets like '1,500 Employees' from page HTML or embedded JSON."""
    raw = html.unescape(raw.replace('\\"', '"'))
    out = []
    for pattern, number_first in ((_TILE, True), (_TILE_REV, False)):
        for m in pattern.finditer(raw):
            number, label = (m.group(1), m.group(2)) if number_first else (m.group(2), m.group(1))
            if re.fullmatch(r"(19|20)\d\d", number.replace(",", "")):
                continue  # a year, not a count
            snippet = f"{number} {label.capitalize()}"
            context = re.sub(r"<[^>]+>|[{}\[\]\"\\]", " ", raw[max(0, m.start() - 120): m.end() + 120])
            out.append(f"{snippet} (page context: {re.sub(r'\s+', ' ', context).strip()[:240]})")
    seen, unique = set(), []
    for s in out:
        key = s.split(" (")[0].lower()
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:10]


_PAIR = re.compile(r"description\W+([A-Za-z][A-Za-z &]{1,30}?)\W+(?:(?:prefix|suffix)\W+\w*\W+){0,2}value\W+([\d,]+\+?)"
                   r"|value\W+([\d,]+\+?)\W+(?:animateNumber\W+\w+\W+)?description\W+([A-Za-z][A-Za-z &]{1,30}?)", re.I)


def readable_tiles(context: str) -> str | None:
    pairs = []
    for m in _PAIR.finditer(context):
        label, value = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        item = f"{label.strip().capitalize()}: {value}"
        if item not in pairs:
            pairs.append(item)
    return ("Statistics shown on the page: " + "; ".join(pairs) + ".") if pairs else None


def website_snippets(website: str, user_agent: str = "Mozilla/5.0 (compatible; employee-count-certifier)",
                     max_pages: int = 4) -> list[PageSnippet]:
    """Stat snippets from the homepage and common About pages of the organization's own site."""
    if not website:
        return []
    if not website.startswith("http"):
        website = "https://" + website
    base = urllib.parse.urlsplit(website)
    root = f"{base.scheme}://{base.netloc}"
    out, fetched = [], 0
    for path in ABOUT_PATHS:
        if fetched >= max_pages:
            break
        url = root + path
        raw = _get(url, user_agent)
        if raw is None:
            continue
        fetched += 1
        out += [PageSnippet(url, s) for s in stat_snippets(raw)]
    seen, unique = set(), []
    for snip in out:  # the same tile often appears on several pages
        key = snip.text.split(" (")[0].lower()
        if key not in seen:
            seen.add(key)
            unique.append(snip)
    return unique
