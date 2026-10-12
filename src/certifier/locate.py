# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Locate a quoted figure inside its document: section, page number, a detailed verbatim passage,
and a deep link that scrolls to the quote.

SEC filings are split at their page breaks; the printed page number is read from each page's
footer, and the section from the nearest preceding ITEM heading and sub-heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote as urlquote

from .models import Location, Source
from .sources.edgar import Edgar, html_to_text

_PAGE_BREAK = re.compile(r"<[^>]+(?:page-break-(?:before|after)\s*:\s*always|break-(?:before|after)\s*:\s*page)[^>]*>",
                         re.I)
_ITEM = re.compile(r"\bITEM[\s ​.]*(\d{1,2}[A-D]?)\b[\s ​.:–-]*([A-Z][A-Z ,’'&()–-]{2,70}?)(?=\s*\.|\s{2}|$)")
_SUBHEADING = re.compile(
    r"(?:^|\.\s)((?:Human Capital(?: Management| Resources)?|Our (?:People|Employees|Workforce)|People(?: and Culture)?|"
    r"Employees(?: and Labor Relations)?|Workforce(?: Metrics| Composition)?|Headcount(?: and Personnel Expense)?|"
    r"Team Members))\s?\.\s")  # a heading is its own block: "Human Capital Management ." then new text
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])")
_SUBHEADING_WINDOW = 6000


@dataclass
class Page:
    index: int  # 1-based position in the HTML filing
    printed: str | None  # page number printed in the footer, if any
    text: str


def filing_pages(raw_html: str) -> list[Page]:
    pages = []
    for i, part in enumerate(_PAGE_BREAK.split(raw_html)):
        text = html_to_text(part).strip()
        if text:
            pages.append(Page(index=len(pages) + 1, printed=_printed_number(text), text=text))
    return pages


def _printed_number(text: str) -> str | None:
    """Footer page number: a small number (or roman numeral) at the very end of the page."""
    tail = re.sub(r"[\s.​]+$", "", text[-60:])
    m = re.search(r"(?:^|\s)(\d{1,3}|[ivxlc]{1,6}|[A-Z]-\d{1,3})$", tail)
    if not m or re.fullmatch(r"(19|20)\d\d", m.group(1)):
        return None
    return m.group(1)


def _norm(text: str) -> str:
    text = text.replace("​", "").replace("’", "'").replace("“", '"').replace("”", '"').replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _find(pages: list[Page], quote: str, value: int | None) -> tuple[int, int] | None:
    """(page position, char offset) of the quote, else of the figure near an employment word."""
    key = _norm(quote)[:80]
    if len(key) >= 20:
        for p_i, p in enumerate(pages):
            k = _norm(p.text).find(key)
            if k >= 0:
                return p_i, _offset_in(p.text, key, k)
    if value is not None:
        figure = f"{value:,}"
        for p_i, p in enumerate(pages):
            for m in re.finditer(re.escape(figure), p.text):
                window = p.text[max(0, m.start() - 150): m.end() + 150].lower()
                if re.search(r"employ|workforce|headcount|team members|people|staff", window):
                    return p_i, m.start()
    return None


def _offset_in(text: str, key: str, norm_offset: int) -> int:
    """Map an offset in normalized text back to the original (approximate is fine for context)."""
    ratio = len(text) / max(1, len(_norm(text)))
    return int(norm_offset * ratio)


def _context(text: str, offset: int, quote: str) -> str:
    """The sentence containing the offset plus one sentence on each side, verbatim."""
    spans, start = [], 0
    for m in _SENTENCES.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    i = next((n for n, (a, b) in enumerate(spans) if a <= offset < b + 1), 0)
    a = spans[max(0, i - 1)][0]
    b = spans[min(len(spans) - 1, i + 1)][1]
    passage = re.sub(r"\s+", " ", text[a:b].replace("​", "")).strip(" .")
    if len(passage) > 900:  # keep it readable: centre on the quote
        center = passage.lower().find(_norm(quote)[:40]) if quote else -1
        center = center if center >= 0 else len(passage) // 2
        passage = "…" + passage[max(0, center - 400): center + 500].strip() + "…"
    return passage + ("." if not passage.endswith(("…", ".", "!", "?")) else "")


def _section(pages: list[Page], p_i: int, offset: int) -> str | None:
    before = " ".join(p.text for p in pages[:p_i]) + " " + pages[p_i].text[:offset]
    item = None
    for m in _ITEM.finditer(before):
        item = f"Item {m.group(1)}. {_heading_case(m.group(2).strip(' .–-'))}"
    sub = None
    for m in _SUBHEADING.finditer(before[-_SUBHEADING_WINDOW:]):
        sub = m.group(1)
    if item and sub:
        return f"{item} › {sub}"
    return item or sub


_SMALL = {"and", "of", "the", "for", "on", "in", "to", "a", "an", "or", "by", "at"}


def _heading_case(text: str) -> str:
    """ITEM headings are upper case; title-case them but keep short acronyms (SAP) and small words."""
    words = []
    for i, w in enumerate(text.split()):
        low = w.lower()
        if i and low in _SMALL:
            words.append(low)
        elif len(w) <= 3 and w.isalpha() and w.isupper() and low not in _SMALL:
            words.append(w)
        else:
            words.append(w[:1].upper() + w[1:].lower())
    return " ".join(words)


def text_fragment_link(url: str, quote: str) -> str | None:
    """A URL that scrolls to (and highlights) the quote in browsers that support text fragments."""
    words = re.sub(r"\s+", " ", quote.replace("​", "")).strip().split(" ")
    if len(words) < 4:
        return None
    enc = lambda s: urlquote(s, safe="").replace("-", "%2D")
    if len(words) <= 10:
        frag = enc(" ".join(words))
    else:
        frag = enc(" ".join(words[:5])) + "," + enc(" ".join(words[-3:]))
    return f"{url.split('#')[0]}#:~:text={frag}"


def edgar_location(edgar: Edgar, source: Source) -> Location | None:
    """Locate a sec.gov filing quote: printed page, Item and sub-heading, detailed passage."""
    try:
        pages = filing_pages(edgar._get(source.url.split("#")[0]))
    except Exception:
        return None
    found = _find(pages, source.excerpt, source.value)
    if found is None:
        return None
    p_i, offset = found
    page = pages[p_i]
    context = _context(page.text, offset, source.excerpt)
    section = _section(pages, p_i, offset)
    if page.printed:
        page_no, basis = page.printed, "printed"
        note = f"Printed page {page.printed} (page {page.index} of {len(pages)} in the HTML filing)."
    else:
        page_no, basis = str(page.index), "html_page"
        note = f"No printed page number on this page; it is page {page.index} of {len(pages)} in the HTML filing."
    if section is None:
        note += " No section heading was identified before the quote."
    return Location(section=section, page=page_no, page_basis=basis, context=context,
                    deep_link=text_fragment_link(source.url, source.excerpt), note=note)


def locate_sources(sources: list[Source], edgar: Edgar | None = None) -> list[Source]:
    """Fill in locations for sec.gov sources from the filing itself (authoritative over any
    location the research step reported), and add a 'not captured' note where nothing is known."""
    out = []
    for s in sources:
        s = s.model_copy(deep=True)
        if "sec.gov/Archives/edgar/data/" in s.url and edgar is not None:
            loc = edgar_location(edgar, s)
            if loc is not None:
                s.location = loc
        if s.location is None:
            s.location = Location(context=s.excerpt, deep_link=text_fragment_link(s.url, s.excerpt) if s.excerpt else None,
                                  note="Section and page were not captured for this source.")
        out.append(s)
    return out
