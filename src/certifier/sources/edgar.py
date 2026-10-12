"""SEC EDGAR: tier 1 annual filings (10-K, 20-F, 40-F) for U.S.-listed companies.

Finds a company, pulls its recent annual filings, and returns the employee-related
snippets from each. A heuristic extractor turns snippets into tier 1 sources; the
Claude extraction step (extract.py) reads the same snippets more carefully.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from ..config import sec_user_agent

ANNUAL_FORMS = ("10-K", "20-F", "40-F")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

Fetch = Callable[[str], str]


@dataclass(frozen=True)
class Company:
    cik: int
    name: str
    ticker: str | None = None


@dataclass(frozen=True)
class Filing:
    company: Company
    form: str
    filed: date
    period: date | None
    url: str


@dataclass
class Snippet:
    filing: Filing
    text: str


@dataclass
class Edgar:
    """Minimal EDGAR client. `fetch` is injectable for offline tests."""

    user_agent: str | None = None
    fetch: Fetch | None = None
    min_interval: float = 0.15  # SEC asks for no more than 10 requests per second
    _cache: dict[str, str] = field(default_factory=dict)
    _last: float = 0.0

    def _get(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]
        if self.fetch is not None:
            body = self.fetch(url)
        else:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent or sec_user_agent(),
                                                       "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError:  # older filings are often Windows-1252
                body = raw.decode("cp1252", "replace")
            self._last = time.monotonic()
        self._cache[url] = body
        return body

    def find_companies(self, query: str, limit: int = 5) -> list[Company]:
        """Exact ticker match first, then companies whose name contains every query word."""
        rows = json.loads(self._get(TICKERS_URL)).values()
        companies = [Company(cik=int(r["cik_str"]), name=r["title"], ticker=r["ticker"]) for r in rows]
        q = query.strip().upper()
        exact = [c for c in companies if c.ticker == q]
        words = re.findall(r"[A-Z0-9&]+", q)
        by_name = [c for c in companies if c not in exact and words
                   and all(re.search(rf"\b{re.escape(w)}\b", c.name.upper()) for w in words)]
        seen, out = set(), []
        for c in exact + sorted(by_name, key=lambda c: len(c.name)):
            if c.cik not in seen:
                seen.add(c.cik)
                out.append(c)
        return out[:limit]

    def company(self, cik: int) -> Company:
        sub = json.loads(self._get(SUBMISSIONS_URL.format(cik=cik)))
        return Company(cik=cik, name=sub["name"], ticker=(sub.get("tickers") or [None])[0])

    def annual_filings(self, company: Company, limit: int = 5) -> list[Filing]:
        """Most recent annual filings, newest first (amendments excluded). Frequent filers' older 10-Ks drop
        out of the "recent" list (about the last 1,000 filings), so the older pages are read when needed."""
        sub = json.loads(self._get(SUBMISSIONS_URL.format(cik=company.cik)))
        pages = [sub["filings"]["recent"]]
        older = [f["name"] for f in sub["filings"].get("files", [])]
        out: list[Filing] = []
        while pages:
            page = pages.pop(0)
            for i, form in enumerate(page["form"]):
                if form not in ANNUAL_FORMS:
                    continue
                accession = page["accessionNumber"][i].replace("-", "")
                url = ARCHIVE_URL.format(cik=company.cik, accession=accession, document=page["primaryDocument"][i])
                period = page["reportDate"][i]
                out.append(Filing(company, form, date.fromisoformat(page["filingDate"][i]),
                                  date.fromisoformat(period) if period else None, url))
                if len(out) == limit:
                    return out
            if not pages and older:
                pages.append(json.loads(self._get(SUBMISSIONS_FILE_URL.format(name=older.pop(0)))))
        return out

    def filing_text(self, filing: Filing) -> str:
        return html_to_text(self._get(filing.url))

    def snippets(self, filing: Filing, max_snippets: int = 80) -> list[Snippet]:
        return [Snippet(filing, s) for s in employee_snippets(self.filing_text(filing), max_snippets)]


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", ". ", raw)  # block ends act as sentence breaks
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"(\.\s*){2,}", ". ", text)


_KEYWORDS = re.compile(r"\b(employ(?:ed|ees|s)?|workforce|headcount|team members|teammates|associates|"
                       r"full[- ]time[- ]equivalents?|FTEs?|personnel|staff)\b", re.I)
_HAS_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*(?:million|thousand)", re.I)


def employee_snippets(text: str, max_snippets: int = 80) -> list[str]:
    """Sentences that mention workers and contain a number, in document order, de-duplicated."""
    out, seen = [], set()
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])", text):
        if len(sentence) > 600:
            m = _KEYWORDS.search(sentence)
            if not m:
                continue
            sentence = sentence[max(0, m.start() - 300): m.end() + 300]
        if _KEYWORDS.search(sentence) and _HAS_NUMBER.search(sentence):
            key = sentence.strip().lower()
            if key not in seen:
                seen.add(key)
                out.append(sentence.strip())
                if len(out) == max_snippets:
                    break
    return out
