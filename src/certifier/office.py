# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Slide and document downloads of a certification record: a 5-slide PowerPoint deck (light or dark, in the
GTM Data Certifier brand) and a Word document with the supporting detail. Built from the record JSON only,
so they match the card exactly."""

from __future__ import annotations

import io
import math
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Pt as DPt
from docx.shared import RGBColor as DRGB
from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from .notice import COPYRIGHT, OWNER_LINE

BRAND = Path(__file__).resolve().parents[2] / "assets" / "brand"
LOGO = BRAND / "hyperloop-logo.png"
LOGO_OUTLINE = BRAND / "hyperloop-mark-outline.png"   # the loop for dark backgrounds
LINKEDIN_CARD = BRAND / "linkedin-card.png"           # Matthew Beltrano's LinkedIn profile card
SITE_URL = "https://employee-count-certifier.onrender.com"
CLOSING_LINE = "AI shouldn't just replicate what humans do. It should elevate human needs and outcomes."
DISCLAIMER = "Certified under policy v{v} from public sources. Verify before contractual use."
CREDIT_URL = "https://www.linkedin.com/in/matthewbeltrano/"
BOTTOM = {"ready": "Ready to use.", "usable": "Usable.", "directional": "Directional only."}

THEMES = {
    "light": {"bg": "F5F7FB", "card": "FFFFFF", "text": "0A2545", "muted": "4B5D75", "line": "DCE3EC", "soft": "EEF3F9",
              "accent": "1F5FBF", "blue": "599AF5", "green": "17794A", "green_bg": "E3F6EC", "yellow": "845500",
              "yellow_bg": "FDF3DC", "red": "B42318", "red_bg": "FDEBE9", "brand_green": "3FCF8E"},
    "dark": {"bg": "06182F", "card": "0D2440", "text": "EAF2FF", "muted": "A7B8CF", "line": "1E3A5C", "soft": "12304F",
             "accent": "A8E3FF", "blue": "599AF5", "green": "6FE0A8", "green_bg": "0F3324", "yellow": "F2C35B",
             "yellow_bg": "33280F", "red": "FF9A90", "red_bg": "3A1A18", "brand_green": "3FCF8E"},
}
QUAL = {"exact": "", "approximately": "approx. ", "more_than": "more than ", "up_to": "up to "}
DIRECTION = {"higher": "↑ Likely higher", "lower": "↓ Likely lower", "in_line": "→ Likely in line",
             "unknown": "· Direction unclear"}


def _num(n) -> str:
    return "–" if n is None else f"{int(n):,}"


def _band(score: int) -> str:
    return "ready" if score >= 4 else "usable" if score == 3 else "directional"


def _source_label(p: dict) -> str:
    if not p.get("source_type"):
        return f"Tier {p.get('tier')}"
    return f"Tier {p['tier']} · {p['source_category']} · {p['source_type']}"


def _line_in_source(p: dict) -> str:
    loc = p.get("location") or {}
    return " · ".join(x for x in (loc.get("section"), loc.get("page_label")) if x)


def _short(text: str, count, limit: int = 170) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    i = text.find(_num(count)) if count is not None else -1
    if i < 0:
        return text[: limit - 10].rsplit(" ", 1)[0] + "…"
    a, b = max(0, i - 70), min(len(text), i + 100)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def _facts(r: dict) -> list[tuple[str, str]]:
    h, c, p, e = r["headline"], r["confidence"], r["primary_source"], r["entity"]
    rng = h.get("range")
    rows = [("Employees", (QUAL.get(h.get("qualifier") or "exact", "") + _num(h.get("count"))) if h.get("count") is not None
             else "Not certified"),
            ("Our range", f"{_num(rng[0])}–{_num(rng[1])}" if rng and rng[0] != rng[1] else "Exact figure"),
            ("As of", (h.get("as_of_date") or "undated") + (" (estimated)" if h.get("as_of_estimated") else "")),
            ("Confidence", f"{c['score']}/5 · {c['level']}")]
    if p.get("source_id"):
        rows += [("Key source", _source_label(p)), ("Line in source", _line_in_source(p))]
        if p.get("excerpt"):
            rows.append(("Excerpt", "“" + _short(p["excerpt"], h.get("count")) + "”"))
    if h.get("direction"):
        rows.append(("Direction", DIRECTION.get(h["direction"], h["direction"])))
    if h.get("next_update_note"):
        rows.append(("Next update", h["next_update_note"]))
    if e.get("address"):
        rows.append(("HQ address", e["address"]))
    return rows


def _trend(r: dict) -> tuple[list[dict], list[dict]]:
    items = r["trend"]["items"]
    return [t for t in items if not t["estimated"]], [t for t in items if t["estimated"]]


# --- PowerPoint -----------------------------------------------------------------------------------

TAGLINE = "Giving you transparency & trust to take real action"
TONE = {"ready": "green", "usable": "yellow", "directional": "red"}
NO_STYLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # PowerPoint's "No Style, No Grid" table style
HISTORY_YEARS, FORECAST_YEARS = 4, 3  # at least 3 years back and 3 ahead


def deck(record: dict, theme: str = "light", logo: bytes | None = None, site_url: str | None = None) -> bytes:
    """Five slides: the answer, trend and forecast, why you can trust this, sources, and a thank-you. Text that can
    run long sits in table cells or a single text frame, which grow with their content, so nothing overlaps. Every
    slide names the company (with its `logo`, when given) and links to the hosted site."""
    t = THEMES.get(theme, THEMES["light"])
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    r = record
    h, c, p, e = r["headline"], r["confidence"], r["primary_source"], r["entity"]
    band = _band(c["score"])
    tone = TONE[band]
    certified_on = (r["methodology"].get("run_at") or r["methodology"].get("lookup_date") or "")[:10]
    total = 5
    site_url = (site_url or SITE_URL).rstrip("/")
    site_label = site_url.split("://", 1)[-1]

    def rgb(key):
        return RGBColor.from_string(t.get(key, key))

    def rect(s, x, y, w, hh, fill, shape=MSO_SHAPE.RECTANGLE, line=None, radius=None):
        b = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(hh))
        if radius is not None:
            b.adjustments[0] = radius
        b.fill.solid()
        b.fill.fore_color.rgb = rgb(fill)
        if line:
            b.line.color.rgb, b.line.width = rgb(line), Pt(0.75)
        else:
            b.line.fill.background()
        b.shadow.inherit = False
        return b

    def text(s, x, y, w, hh, value, size, color="text", bold=False, align=None, italic=False):
        box = _text(s, Inches(x), Inches(y), Inches(w), Inches(hh), value, size, rgb(color), bold=bold, align=align)
        box.text_frame.paragraphs[0].runs[0].font.italic = italic
        return box

    def slide(n: int, title: str, kicker: str):
        s = prs.slides.add_slide(blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = rgb("bg")
        # Brand band: logo chip, product name and tagline, step and slide title, the loop-gradient rule.
        rect(s, 0.45, 0.32, 0.95, 0.55, "FFFFFF", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.22)
        if LOGO.is_file():
            s.shapes.add_picture(str(LOGO), Inches(0.52), Inches(0.40), height=Inches(0.39))
        text(s, 1.58, 0.30, 5.6, 0.32, "GTM Data Certifier", 14, bold=True)
        text(s, 1.58, 0.60, 5.6, 0.28, TAGLINE, 10, "muted", italic=True)
        text(s, 8.3, 0.27, 4.58, 0.24, f"{n:02d} / {total:02d}  ·  {kicker.upper()}", 9, "brand_green", bold=True, align=PP_ALIGN.RIGHT)
        text(s, 8.3, 0.50, 4.58, 0.45, title, 22, bold=True, align=PP_ALIGN.RIGHT)
        company_chip(s)
        rect(s, 0.45, 1.04, 4.6, 0.045, "brand_green")
        rect(s, 5.05, 1.04, 7.833, 0.045, "blue")
        # Footer: a hairline, the certification line on the left, the credit and notice on the right.
        rect(s, 0.45, 6.93, 12.433, 0.01, "line")
        text(s, 0.45, 6.99, 7.6, 0.24, f"{e['name']} · certified on {certified_on} · "
             + DISCLAIMER.format(v=r["methodology"]["policy_version"]), 8, "muted")
        site = text(s, 0.45, 7.2, 7.6, 0.24, "Certify another organization: ", 8, "muted")
        run = site.text_frame.paragraphs[0].add_run()
        run.text, run.font.size, run.font.bold, run.font.name = site_label + " ↗", Pt(8), True, "Segoe UI"
        run.font.color.rgb = rgb("accent")
        run.hyperlink.address = site_url
        credit = text(s, 8.1, 7.1, 4.78, 0.26, "Designed and created by ", 8.5, "muted", align=PP_ALIGN.RIGHT)
        para = credit.text_frame.paragraphs[0]
        for txt, url in (("Matthew Beltrano", CREDIT_URL), (" & Claude Code · © 2026 · Proprietary", None)):
            run = para.add_run()
            run.text = txt
            run.font.size, run.font.name = Pt(8.5), "Segoe UI"
            run.font.color.rgb = rgb("accent" if url else "muted")
            if url:
                run.hyperlink.address = url
        return s

    def company_chip(s):
        """The organization being certified, with its logo, in the header of every slide."""
        chip = rect(s, 5.15, 0.34, 3.0, 0.52, "soft", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
        x = 5.3
        if logo:
            try:
                s.shapes.add_picture(io.BytesIO(logo), Inches(5.27), Inches(0.42), height=Inches(0.36))
                x = 5.72
            except Exception:  # an unreadable image never breaks the deck
                pass
        frame(chip, [(0, [(_clip(e["name"], 30), 11.5, True, "text", False, None)])], anchor=MSO_ANCHOR.MIDDLE, margin=0)
        chip.text_frame.margin_left = Inches(x - 5.15)
        chip.text_frame.margin_right = Inches(0.12)
        chip.text_frame.word_wrap = False

    def table(s, x, y, w, rows: int, cols: int, widths, row_h=0.36):
        shape = s.shapes.add_table(rows, cols, Inches(x), Inches(y), Inches(w), Inches(row_h * rows))
        tbl = shape.table
        tbl.first_row = tbl.horz_banding = False
        style = shape._element.graphic.graphicData.tbl.tblPr.find(qn("a:tableStyleId"))
        if style is not None:
            style.text = NO_STYLE
        for i, wd in enumerate(widths):
            tbl.columns[i].width = Inches(wd)
        for row in tbl.rows:
            row.height = Inches(row_h)
        return tbl

    def cell(cl, runs, fill="card", align=PP_ALIGN.LEFT, rule=True, top=False):
        """`runs`: (text, size, bold, color[, italic]) tuples; a "\n" text starts a new paragraph."""
        _rule(cl, t["line"] if rule else None)
        cl.fill.solid()
        cl.fill.fore_color.rgb = rgb(fill)
        cl.margin_left = cl.margin_right = Inches(0.1)
        cl.margin_top = cl.margin_bottom = Inches(0.05)
        cl.vertical_anchor = MSO_ANCHOR.TOP if top else MSO_ANCHOR.MIDDLE
        tf = cl.text_frame
        tf.clear()
        tf.word_wrap = True
        para = tf.paragraphs[0]
        para.alignment = align
        for value, size, bold, color, *rest in runs:
            if value == "\n":
                para = tf.add_paragraph()
                para.alignment = align
                continue
            run = para.add_run()
            run.text = str(value)
            run.font.size, run.font.bold, run.font.name = Pt(size), bold, "Segoe UI"
            run.font.italic = bool(rest and rest[0])
            run.font.color.rgb = rgb(color)

    def frame(shape, paragraphs, anchor=MSO_ANCHOR.TOP, margin=0.22):
        """Paragraphs of runs inside one shape: (space_before, [(text, size, bold, color, italic, link)])."""
        tf = shape.text_frame
        tf.clear()
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Inches(margin)
        tf.margin_top = tf.margin_bottom = Inches(0.14)
        for i, (space, runs) in enumerate(paragraphs):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = PP_ALIGN.LEFT
            para.space_before = Pt(space)
            for value, size, bold, color, italic, url in runs:
                run = para.add_run()
                run.text = value
                run.font.size, run.font.bold, run.font.italic, run.font.name = Pt(size), bold, italic, "Segoe UI"
                run.font.color.rgb = rgb(color)
                if url:
                    run.hyperlink.address = url

    # 1. The answer ------------------------------------------------------------------------------
    s = slide(1, "The answer", "Certified employee count")
    name = e["name"]
    text(s, 0.55, 1.28, 7.3, 0.6, name, 26 if len(name) <= 30 else 22 if len(name) <= 44 else 18, bold=True)
    text(s, 0.55, 1.86, 7.3, 0.3, " · ".join(x for x in (e.get("website"), e.get("relationship")) if x), 11, "muted")
    rect(s, 0.55, 2.3, 7.3, 1.85, "card", MSO_SHAPE.ROUNDED_RECTANGLE, line="line", radius=0.08)
    rect(s, 0.55, 2.42, 0.07, 1.61, "brand_green")
    count = (QUAL.get(h.get("qualifier") or "exact", "") + _num(h["count"])) if h.get("count") is not None else "Not certified"
    text(s, 0.88, 2.36, 5.0, 0.95, count, 54 if len(count) <= 9 else 40, bold=True)
    text(s, 0.92, 3.3, 5.0, 0.3, ("full-time equivalents" if h.get("count_basis") == "fte" else "employees") + " · "
         + ("as of " + h["as_of_date"] if h.get("as_of_date") else "undated")
         + (" (estimated)" if h.get("as_of_estimated") else ""), 12, "muted")
    for i in range(5):  # the confidence meter, as on the card
        rect(s, 0.92 + i * 0.4, 3.75, 0.32, 0.12, "brand_green" if i < c["score"] else "line", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    text(s, 3.0, 3.66, 2.9, 0.3, f"{c['score']}/5 · {c['level']}", 11, bold=True)
    _seal(s, 5.98, 2.3, 1.78, c["score"], t)
    bl = rect(s, 0.55, 4.35, 7.3, 0.62, tone + "_bg", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.18)
    frame(bl, [(0, [({"ready": "✓  ", "usable": "!  ", "directional": "✕  "}[band], 14, True, tone, False, None),
                    ("Bottom line: ", 14, True, tone, False, None), (h.get("bottom_line") or "", 14, False, tone, False, None)])],
          anchor=MSO_ANCHOR.MIDDLE)
    if h.get("story"):  # "Our take" in the speaker notes, for whoever presents the slides
        s.notes_slide.notes_text_frame.text = "Our take: " + h["story"]
    ks_top = 5.1
    if h.get("peer_note"):
        rare = h.get("peer_level") == "rare"
        note = rect(s, 0.55, 5.03, 7.3, 0.42, "green_bg" if rare else "soft", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.3)
        frame(note, [(0, [("✦ " if rare else "◆ ", 11, True, "green" if rare else "accent", False, None),
                          ((f"Rare for a private company: a {c['score']}/5 without public filings. Worth celebrating."
                            if rare else "Strong for a private company: 3/5 is about as good as it gets without public "
                            "filings; 4-5 is rare."), 10, rare, "green" if rare else "text", False, None)])],
              anchor=MSO_ANCHOR.MIDDLE, margin=0.16)
        ks_top = 5.55
    ks = rect(s, 0.55, ks_top, 7.3, 6.82 - ks_top, "soft", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    if p.get("source_id"):
        loc = p.get("location") or {}
        paras = [(0, [("KEY SOURCE", 9, True, "muted", False, None)]),
                 (2, [(_source_label(p), 13, True, "text", False, None)])]
        if p.get("excerpt"):
            paras.append((4, [("“" + _excerpt(p["excerpt"], h.get("count")) + "”", 11, False, "text", True, None)]))
        paras.append((4, [("Open the source at the quote ↗", 10.5, True, "accent", False, loc.get("deep_link") or p["url"]),
                          (("  ·  " + _line_in_source(p)) if _line_in_source(p) else "", 10, False, "muted", False, None)]))
        frame(ks, paras)
    else:
        frame(ks, [(0, [("KEY SOURCE", 9, True, "muted", False, None)]),
                   (2, [(p.get("none_reason") or "No key source.", 12, False, "text", False, None)])])
    rect(s, 8.15, 1.28, 4.73, 5.47, "card", MSO_SHAPE.ROUNDED_RECTANGLE, line="line", radius=0.05)
    text(s, 8.42, 1.46, 4.2, 0.26, "AT A GLANCE", 9, "muted", bold=True)
    facts = [f for f in _facts(r) if f[0] not in ("Employees", "Confidence", "Key source", "Excerpt")]
    tbl = table(s, 8.32, 1.78, 4.4, len(facts), 2, (1.3, 3.1), row_h=0.42)
    for i, (label, value) in enumerate(facts):
        last_row = i == len(facts) - 1
        cell(tbl.cell(i, 0), [(label.upper(), 8.5, True, "muted")], rule=not last_row, top=True)
        cell(tbl.cell(i, 1), [(value, 11.5, False, "text")], rule=not last_row, top=True)

    # 2. Trend and forecast ------------------------------------------------------------------------
    s = slide(2, "Trend and forecast", "History and outlook")
    reported, forecast = _trend(r)
    top = 1.3
    if h.get("direction"):
        d = rect(s, 0.55, top, 12.33, 0.62, "soft", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.18)
        frame(d, [(0, [(DIRECTION.get(h["direction"], "") + "  ·  ", 12, True, "text", False, None),
                       (_short(h.get("direction_reason") or "", None, 190), 11.5, False, "text", False, None)])], anchor=MSO_ANCHOR.MIDDLE)
        top += 0.8
    if reported:
        _trend_chart(s, reported, forecast, t, 0.55, top, 8.5, 6.2 - top, c["score"])
        legend = [("●", "blue", "Reported"), ("◌", "muted", "Historical estimate" if any(p.get("historical") for p in reported) else None),
                  ("◯", "blue", "Forecast (estimate)" if forecast else None),
                  ("┅", "muted", "Forecast range" if forecast else None), ("✕", "muted", "No reported figure")]
        box = text(s, 0.65, 6.3, 8.4, 0.28, "", 10, "muted")
        para = box.text_frame.paragraphs[0]
        para.runs[0].text = ""
        for sym, color, label in legend:
            if not label:
                continue
            for value, col, bold in ((sym + " ", color, True), (label + "      ", "muted", False)):
                run = para.add_run()
                run.text, run.font.size, run.font.bold, run.font.name = value, Pt(10), bold, "Segoe UI"
                run.font.color.rgb = rgb(col)
        if forecast:
            why = forecast[-1].get("rationale") or ""
            note = ("Best-guess forecast (short history): " + why.split(": ", 1)[-1].split(", with a range")[0]
                    .replace(", since LinkedIn over-represents office staff", "").replace(" carried forward, at most ±3%", "")
                    + "; the range widens each year."
                    if why.startswith("Best-guess") else
                    "The forecast carries the reported trend forward from the latest figure; an estimate, not a reported figure.")
            if any(p.get("historical") for p in reported):
                note += " est. = historical estimate, shown for direction, not certified."
            text(s, 0.65, 6.58, 8.4, 0.28, note, 9, "muted", italic=True)
        last = reported[-1]
        first = reported[0]
        f = forecast[-1] if forecast else None
        years = int(last["as_of_date"][:4]) - int(first["as_of_date"][:4])
        change = (last["value"] - first["value"]) / first["value"] if first["value"] and years else None
        since_estimate = bool(first.get("historical"))
        level_word = ("CERTIFIED" if c["score"] >= 4 else "SUPPORTED" if c["score"] == 3 else "ESTIMATED" if c["score"] == 2
                      else "UNVERIFIED")
        stats = [(level_word, _num(last["value"]), ("as of " + last["as_of_date"]) if h.get("as_of_date")
                  else "undated source · shown at " + last["as_of_date"], "brand_green"),
                 (f"FORECAST {f['as_of_date'][:4]}" if f else "FORECAST", "≈" + _num(round_forecast(f["value"])) if f else "No forecast",
                  f"range {_num(round_forecast(f['low']))}–{_num(round_forecast(f['high']))}" if f else "needs 3 reported years", "blue"),
                 ((f"CHANGE SINCE {first['as_of_date'][:4]} (EST.)" if since_estimate else
                   f"CHANGE OVER {years} YEAR{'S' if years != 1 else ''}") if change is not None else "CHANGE",
                  f"{change:+.1%}" if change is not None else "–",
                  f"{_num(first['value'])} → {_num(last['value'])}" if change is not None else "one reported year", "accent")]
        gap = (6.2 - top - 3 * 1.2) / 2
        for i, (label, value, sub, stripe) in enumerate(stats):
            y = top + i * (1.2 + gap)
            box = rect(s, 9.3, y, 3.58, 1.2, "card", MSO_SHAPE.ROUNDED_RECTANGLE, line="line", radius=0.08)
            rect(s, 9.3, y + 0.14, 0.07, 0.92, stripe)
            frame(box, [(0, [(label, 9, True, "muted", False, None)]), (1, [(value, 22, True, "text", False, None)]),
                        (0, [(sub, 10, False, "muted", False, None)])], anchor=MSO_ANCHOR.MIDDLE, margin=0.3)
    else:
        text(s, 0.55, top + 0.2, 12, 0.5, r["trend"].get("none_reason") or "No trend available.", 14, "muted")

    # 3. Why you can trust this -----------------------------------------------------------------------
    s = slide(3, "Why you can trust this", "Evidence and checks")
    corr = sum(1 for x in r["sources"]["items"] if x["role"] == "corroborates")
    adj = sum(1 for a in r["adjustments"]["items"] if a.get("change"))
    red = sum(1 for f in r["findings"]["items"] if f["status"] == "red")
    key_sub = _clip(p.get("source_type") or p.get("tier_name") or "", 26) if p.get("source_id") else None
    tiles = [("KEY SOURCE", f"Tier {p['tier']}" if p.get("source_id") else "none", "blue", key_sub),
             ("AS OF", h.get("as_of_date") or "undated", "blue", "estimated" if h.get("as_of_estimated") else None),
             ("CONFIRMATIONS", str(corr), "brand_green" if corr else "line", "independent sources"),
             ("ADJUSTMENTS", str(adj), "blue", "to the count"), ("NEEDS ATTENTION", str(red), "red" if red else "brand_green",
                                                                  "red findings" if red else "nothing red")]
    for i, (label, value, stripe, sub_text) in enumerate(tiles):
        x = 0.55 + i * 2.5
        tile = rect(s, x, 1.3, 2.33, 1.0, "soft", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
        rect(s, x, 1.42, 0.06, 0.76, stripe)
        paras = [(0, [(label, 8.5, True, "muted", False, None)]), (1, [(value, 16, True, "text", False, None)])]
        if sub_text:
            paras.append((0, [(sub_text, 9.5, False, "muted", False, None)]))
        frame(tile, paras, anchor=MSO_ANCHOR.MIDDLE, margin=0.22)
    groups = [(g, title, [f for f in r["findings"]["items"] if f.get("group") == g])
              for g, title in (("affects", "Affects the answer"), ("worth_knowing", "Worth knowing"))]
    budget, rows = 6, []
    for g, title, items in groups:
        take = items[: max(0, min(len(items), budget - (1 if g == "affects" and groups[1][2] else 0)))]
        budget -= len(take)
        if take:
            rows.append(("head", title))
            rows += [("item", f) for f in take]
    shown = sum(1 for kind, _ in rows if kind == "item")
    if rows:
        tbl = table(s, 0.55, 2.55, 12.33, len(rows), 3, (0.45, 9.55, 2.33), row_h=0.4)
        for i, (kind, item) in enumerate(rows):
            if kind == "head":
                tbl.cell(i, 0).merge(tbl.cell(i, 2))
                cell(tbl.cell(i, 0), [(item.upper(), 9, True, "muted")], fill="bg", rule=False)
                continue
            sym = {"green": ("✓", "green"), "yellow": ("!", "yellow"), "red": ("✕", "red")}[item["status"]]
            cell(tbl.cell(i, 0), [(sym[0], 14, True, sym[1])], align=PP_ALIGN.CENTER)
            cell(tbl.cell(i, 1), [(_clip(item["title"], 95), 12, True, "text"),
                                  ("  —  " + _clip(item.get("so_what", ""), 110), 10.5, False, "muted")])
            cell(tbl.cell(i, 2), [(item.get("impact", ""), 10, False, "muted")], align=PP_ALIGN.RIGHT)
    hidden = len(r["findings"]["items"]) - shown
    if hidden > 0:
        text(s, 0.55, 6.55, 12.33, 0.28, f"+{hidden} more finding{'s' if hidden != 1 else ''} on the card and in the Word document.",
             10, "muted", italic=True)

    # 4. Sources -------------------------------------------------------------------------------------
    s = slide(4, "Sources", "Every source considered")
    items = r["sources"]["items"]
    rows = items[:10]
    tbl = table(s, 0.55, 1.3, 12.33, len(rows) + 1, 5, (0.55, 5.6, 1.6, 1.45, 3.13), row_h=0.4)
    for j, head in enumerate(("ID", "Source", "Value", "As of", "Status")):
        cell(tbl.cell(0, j), [(head.upper(), 9, True, "muted")], fill="soft", rule=False,
             align=PP_ALIGN.RIGHT if j == 2 else PP_ALIGN.LEFT)
    for i, x in enumerate(rows, start=1):
        key = x["role"] == "selected"
        status = _status(x, p)
        color = "green" if x["used"] else "accent" if status.startswith("Prior") else "muted"
        mark = "◆ " if key else "✓ " if x["used"] else "↺ " if status.startswith("Prior") else "○ "
        fill = "green_bg" if key else "card"
        cell(tbl.cell(i, 0), [(x["id"], 10.5, key, "muted")], fill=fill)
        cell(tbl.cell(i, 1), [(f"Tier {x['tier']}  ", 10.5, True, "accent"),
                              (_clip(x.get("source_type") or x["tier_name"], 60), 11, key, "text")], fill=fill)
        cell(tbl.cell(i, 2), [(QUAL.get(x["qualifier"], "") + _num(x["value"]), 11, key, "text")], fill=fill, align=PP_ALIGN.RIGHT)
        cell(tbl.cell(i, 3), [(x.get("as_of_date") or "undated", 10.5, False, "text" if x.get("as_of_date") else "muted")], fill=fill)
        cell(tbl.cell(i, 4), [(mark + status, 10.5, key or x["used"], color)], fill=fill)
    m = r["methodology"]
    more = len(items) - len(rows)
    text(s, 0.55, min(6.3, 1.45 + 0.42 * (len(rows) + 1)), 12.33, 0.55,
         f"{len(items)} sources found, {sum(1 for x in items if x['used'])} used"
         + (f" ({more} more listed on the card and in the Word document)" if more > 0 else "") + ". "
         f"Method: {m['method']} · policy {m['policy_version']} · record {m['record_version']}. "
         "The policy ranks every source by tier, recency and independence; the AI gathers evidence but never "
         "chooses the answer.", 10.5, "muted")

    _thank_you(prs, blank, e["name"], site_url, site_label)
    _brand_links(prs, t["accent"])
    out = io.BytesIO()
    prs.core_properties.author, prs.core_properties.comments = "Matthew Beltrano", COPYRIGHT
    prs.save(out)
    return out.getvalue()


def _thank_you(prs, layout, company: str, site_url: str, site_label: str) -> None:
    """The closing slide, always in the dark brand colours (like the Hyperloop deck's): thank you, the closing line,
    the loop, Matthew's LinkedIn card (linked to the profile) and the way back to the hosted site."""
    t = THEMES["dark"]
    rgb = lambda key: RGBColor.from_string(t.get(key, key))  # noqa: E731
    s = prs.slides.add_slide(layout)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor.from_string("0B2545")

    def say(x, y, w, h, value, size, color, bold=False, italic=False, align=None, link=None):
        box = _text(s, Inches(x), Inches(y), Inches(w), Inches(h), value, size, rgb(color), bold=bold, align=align)
        run = box.text_frame.paragraphs[0].runs[0]
        run.font.italic = italic
        if link:
            run.hyperlink.address = link
        return box

    say(0.75, 2.0, 6.0, 1.1, "Thank you.", 54, "text", bold=True)
    say(0.78, 3.15, 5.6, 0.9, CLOSING_LINE, 17, "accent")
    if LOGO_OUTLINE.is_file():
        s.shapes.add_picture(str(LOGO_OUTLINE), Inches(0.72), Inches(4.3), height=Inches(0.95))
    elif LOGO.is_file():
        s.shapes.add_picture(str(LOGO), Inches(0.72), Inches(4.3), height=Inches(0.7))
    say(2.85, 4.45, 3.9, 0.3, "GTM Data Certifier", 14, "text", bold=True)
    say(2.85, 4.78, 3.9, 0.3, "Giving you transparency & trust to take real action", 10.5, "muted", italic=True)
    if LINKEDIN_CARD.is_file():
        card = s.shapes.add_picture(str(LINKEDIN_CARD), Inches(6.55), Inches(2.25), width=Inches(6.0))
        card.click_action.hyperlink.address = CREDIT_URL
    else:
        say(6.55, 2.6, 6.0, 0.4, "Matthew Beltrano", 22, "text", bold=True, link=CREDIT_URL)
    # Two calls to action under the card: the profile and the hosted site.
    for i, (label, url) in enumerate((("Connect on LinkedIn ↗", CREDIT_URL), ("Try GTM Data Certifier ↗", site_url))):
        pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.55 + i * 2.65), Inches(4.5),
                                  Inches(2.45 if i == 0 else 3.35), Inches(0.52))
        pill.adjustments[0] = 0.5
        pill.fill.solid()
        pill.fill.fore_color.rgb = RGBColor.from_string("0A66C2" if i == 0 else "3FCF8E")
        pill.line.fill.background()
        pill.shadow.inherit = False
        tf = pill.text_frame
        tf.clear()
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = tf.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER
        run = para.add_run()
        run.text = label
        run.font.size, run.font.bold, run.font.name = Pt(12), True, "Segoe UI"
        run.font.color.rgb = RGBColor.from_string("FFFFFF" if i == 0 else "06182F")
        pill.click_action.hyperlink.address = url  # the whole button is the link (linked text would be recoloured)
    note = say(6.58, 5.2, 6.0, 0.3, f"{_clip(company, 28)} today. Any organization next, in about a minute: ", 10.5, "muted")
    run = note.text_frame.paragraphs[0].add_run()
    run.text, run.font.size, run.font.bold, run.font.name = site_label, Pt(10.5), True, "Segoe UI"
    run.font.color.rgb = rgb("accent")
    run.hyperlink.address = site_url
    rule = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(6.55), Inches(12.13), Inches(0.01))
    rule.fill.solid()
    rule.fill.fore_color.rgb = rgb("line")
    rule.line.fill.background()
    say(0.75, 6.78, 6.5, 0.35, "Designing for the Human in the Hyperloop", 13, "text", bold=True)
    say(7.0, 6.82, 5.73, 0.3, "GTM DATA CERTIFIER  ·  © 2026 MATTHEW BELTRANO", 11, "accent", bold=True, align=PP_ALIGN.RIGHT)


def round_forecast(value) -> int:
    """Forecasts are estimates: round them to a step that suits their size (10s, 25s, 100s; 1,000s only when large)."""
    step = 10 if value < 2_000 else 25 if value < 20_000 else 100 if value < 500_000 else 1_000
    return int(round(value / step) * step)


def _excerpt(text: str, count, limit: int = 300) -> str:
    """The exact excerpt; when it's long, a verbatim window around the figure that keeps its "as of" phrase."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    i = text.find(_num(count)) if count is not None else -1
    i = i if i >= 0 else 0
    a = max(0, i - 140)
    as_of = max(text.lower().rfind("as of", 0, i + 1), text.lower().rfind("as at", 0, i + 1))
    if as_of >= 0 and i - as_of < 220:
        a = min(a, as_of)
    b = min(len(text), a + limit)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


# Seal grades by confidence score: (grade, gradient from, gradient to, ink).
GRADES = {5: ("PLATINUM", "3FCF8E", "599AF5", "17794A"), 4: ("GOLD", "F7D774", "D99A1E", "8A5A00"),
          3: ("SILVER", "DDE4EE", "9AA8BC", "4B5D75"), 2: ("BRONZE", "E8B48A", "A86A3D", "6E3F1C"),
          1: ("PROVISIONAL", "F4B4AC", "C2463A", "8E1F14"), 0: ("NOT CERTIFIED", "C9D1DC", "8A97A8", "4B5D75")}


def _seal(s, x: float, y: float, size: float, score: int, t: dict) -> None:
    """A certification seal: a scalloped rosette in the grade's colours, an inner ring, and
    "GTM Data Certifier · stars · score · grade · Hyperloop grade" set inside. Tilted slightly, like a stamp."""
    grade, c1, c2, ink = GRADES.get(score, GRADES[0])
    if t["bg"] < "8":  # dark theme: lighter ink reads better on the dark centre
        ink = {"PLATINUM": "6FE0A8", "GOLD": "F2C35B", "SILVER": "C9D3E0", "BRONZE": "E8B48A",
               "PROVISIONAL": "FF9A90", "NOT CERTIFIED": "A7B8CF"}[grade]
    tilt = -8

    def grad(shape, angle=45):
        shape.fill.gradient()
        shape.fill.gradient_angle = angle
        stops = shape.fill.gradient_stops
        stops[0].color.rgb, stops[1].color.rgb = RGBColor.from_string(c1), RGBColor.from_string(c2)
        shape.line.fill.background()
        shape.shadow.inherit = False

    rosette = s.shapes.add_shape(MSO_SHAPE.STAR_32_POINT, Inches(x), Inches(y), Inches(size), Inches(size))
    rosette.adjustments[0] = 0.44
    rosette.rotation = tilt
    grad(rosette)
    inset = size * 0.12
    centre = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + inset), Inches(y + inset), Inches(size - 2 * inset),
                                Inches(size - 2 * inset))
    centre.fill.solid()
    centre.fill.fore_color.rgb = RGBColor.from_string(t["card"])
    centre.line.color.rgb, centre.line.width = RGBColor.from_string(c2), Pt(2.25)
    centre.shadow.inherit = False
    inner = size * 0.19
    ring = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + inner), Inches(y + inner), Inches(size - 2 * inner),
                              Inches(size - 2 * inner))
    ring.fill.background()
    ring.line.color.rgb, ring.line.width, ring.line.dash_style = RGBColor.from_string(ink), Pt(0.75), MSO_LINE_DASH_STYLE.ROUND_DOT
    ring.shadow.inherit = False
    box = s.shapes.add_textbox(Inches(x + inner), Inches(y + inner), Inches(size - 2 * inner), Inches(size - 2 * inner))
    box.rotation = tilt
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    lines = [("GTM DATA CERTIFIER", 6, True, ink), ("★" * score + "☆" * (5 - score), 9, False, ink),
             (f"{score}/5", 22, True, t["text"]), (grade, 8.5, True, ink), ("HYPERLOOP GRADE", 5.5, True, t["muted"])]
    for n, (value, size_pt, bold, color) in enumerate(lines):
        para = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
        para.alignment = PP_ALIGN.CENTER
        para.space_before = Pt(0)
        para.line_spacing = 0.95
        run = para.add_run()
        run.text = value
        run.font.size, run.font.bold, run.font.name = Pt(size_pt), bold, "Segoe UI"
        run.font.color.rgb = RGBColor.from_string(color)


def _clip(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _nice_step(span: float) -> float:
    raw = max(span, 1) / 4
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def _trend_chart(s, reported: list[dict], forecast: list[dict], t: dict, x, y, w, hh, score: int = 5) -> None:
    """A native, editable line chart over a fixed nine years (five reported, four forecast). Years without a
    reported figure (and a missing forecast) are ✕ markers on a dotted line, as on the card."""
    rgb = lambda key: RGBColor.from_string(t[key])  # noqa: E731
    last = reported[-1]
    ly = int(last["as_of_date"][:4])
    # Five years back, or further when a historical estimate reaches further.
    n_hist = max(HISTORY_YEARS, ly - int(reported[0]["as_of_date"][:4]) + 1)
    fc_years = max(FORECAST_YEARS, len(forecast))
    years = list(range(ly - n_hist + 1, ly + fc_years + 1))
    rep = {int(p["as_of_date"][:4]): p["value"] for p in reported if not p.get("historical") and int(p["as_of_date"][:4]) in years}
    hist = {int(p["as_of_date"][:4]): p["value"] for p in reported if p.get("historical") and int(p["as_of_date"][:4]) in years}
    anchors = {**hist, **rep}
    fc = {int(p["as_of_date"][:4]): p for p in forecast}
    known = sorted(anchors)

    def held(year):  # a placeholder sits on the line between its neighbours, or level with the nearest figure
        prev = max((k for k in known if k < year), default=None)
        nxt = min((k for k in known if k > year), default=None)
        if prev is not None and nxt is not None:
            return anchors[prev] + (anchors[nxt] - anchors[prev]) * (year - prev) / (nxt - prev)
        return anchors[prev if prev is not None else nxt]

    gaps = [yr for yr in years[:n_hist] if yr not in anchors] + ([] if fc else years[n_hist:])
    placeholder: list[float | None] = [None] * len(years)
    for i, yr in enumerate(years):
        if yr in gaps:
            placeholder[i] = held(yr)
            for j in (i - 1, i + 1):  # reach the neighbouring reported point so the dotted line connects
                if 0 <= j < len(years) and years[j] in anchors:
                    placeholder[j] = anchors[years[j]]
    data = CategoryChartData()
    data.categories = [str(yr) for yr in years]
    series_spec = [("No reported figure", placeholder)]
    if hist:
        # Historical estimates joined to the first reported figure by a dotted line.
        first_rep = min(rep) if rep else None
        series_spec.append(("Historical estimate", [hist.get(yr, rep.get(yr) if yr == first_rep else None) for yr in years]))
    if fc:
        lead = [None] * (n_hist - 1) + [last["value"]]
        series_spec += [("Forecast high", lead + [fc[yr]["high"] if yr in fc else None for yr in years[n_hist:]]),
                        ("Forecast low", lead + [fc[yr]["low"] if yr in fc else None for yr in years[n_hist:]]),
                        ("Forecast", lead + [fc[yr]["value"] if yr in fc else None for yr in years[n_hist:]])]
    series_spec.append(("Reported", [rep.get(yr) for yr in years]))
    for name, values in series_spec:
        data.add_series(name, values)
    frame = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(x), Inches(y), Inches(w), Inches(hh), data)
    ch = frame.chart
    ch.has_title = False
    ch.has_legend = False
    ch.font.size, ch.font.name, ch.font.color.rgb = Pt(10.5), "Segoe UI", rgb("muted")
    vals = [v for _, values in series_spec for v in values if v is not None]
    lo, hi = min(vals), max(vals)
    step = _nice_step((hi - lo) or hi * 0.2)
    va = ch.value_axis
    va.minimum_scale = max(0, math.floor((lo - step * 0.6) / step) * step)
    va.maximum_scale = math.ceil((hi + step * 0.6) / step) * step
    va.major_unit = step
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = rgb("line")
    va.tick_labels.number_format, va.tick_labels.number_format_is_linked = "#,##0", False
    va.format.line.fill.background()
    ch.category_axis.format.line.color.rgb = rgb("line")
    for axis in (va, ch.category_axis):
        axis.tick_labels.font.size, axis.tick_labels.font.color.rgb = Pt(10.5), rgb("muted")
    final = len(years) - 1
    for series in ch.plots[0].series:
        series.smooth = series.name in ("Reported", "Forecast", "Forecast high", "Forecast low")
        line = series.format.line
        marker = series.marker
        if series.name == "No reported figure":
            line.width, line.color.rgb, line.dash_style = Pt(1.5), rgb("muted"), MSO_LINE_DASH_STYLE.ROUND_DOT
            marker.style, marker.size = XL_MARKER_STYLE.X, 9
            marker.format.line.color.rgb = rgb("muted")
            for i, yr in enumerate(years):
                if placeholder[i] is not None and yr not in gaps:
                    series.points[i].marker.style = XL_MARKER_STYLE.NONE
        elif series.name in ("Forecast high", "Forecast low"):
            line.width, line.color.rgb, line.dash_style = Pt(1), rgb("blue"), MSO_LINE_DASH_STYLE.SQUARE_DOT
            marker.style = XL_MARKER_STYLE.NONE
        elif series.name == "Historical estimate":  # hollow, muted, "≈7,000 est."; never certified
            line.width, line.color.rgb, line.dash_style = Pt(1.5), rgb("muted"), MSO_LINE_DASH_STYLE.ROUND_DOT
            marker.style, marker.size = XL_MARKER_STYLE.CIRCLE, 9
            marker.format.fill.solid()
            marker.format.fill.fore_color.rgb = rgb("card")
            marker.format.line.color.rgb, marker.format.line.width = rgb("muted"), Pt(2)
            for i, yr in enumerate(years):
                if yr not in hist and yr in rep:
                    series.points[i].marker.style = XL_MARKER_STYLE.NONE  # the reported point draws itself
                if yr in hist:
                    dl = series.points[i].data_label
                    dl.position = XL_LABEL_POSITION.ABOVE
                    dl.text_frame.text = "≈" + _num(hist[yr]) + " est."
                    run = dl.text_frame.paragraphs[0].runs[0]
                    run.font.size, run.font.italic, run.font.color.rgb = Pt(10), True, rgb("muted")
        else:
            reported_series = series.name == "Reported"
            line.width, line.color.rgb = Pt(3.25 if reported_series else 2.5), rgb("blue")
            if not reported_series:
                line.dash_style = MSO_LINE_DASH_STYLE.DASH
            marker.style, marker.size = XL_MARKER_STYLE.CIRCLE, 9 if reported_series else 8
            marker.format.fill.solid()
            marker.format.fill.fore_color.rgb = rgb("blue" if reported_series else "card")
            marker.format.line.color.rgb = rgb("blue")
            for i, yr in enumerate(years):
                label_it = (reported_series and yr in rep) or (not reported_series and yr in fc)
                if not label_it:
                    continue
                dl = series.points[i].data_label
                dl.position = XL_LABEL_POSITION.ABOVE if reported_series else XL_LABEL_POSITION.BELOW
                tf = dl.text_frame
                if reported_series and yr == ly:  # the certified figure, named with its confidence level
                    word, tone = (("✓ CERTIFIED", "green") if score >= 4 else ("◆ SUPPORTED", "yellow") if score == 3
                                  else ("! ESTIMATED", "yellow") if score == 2 else ("⚠ UNVERIFIED", "red"))
                    tf.text = word
                    head = tf.paragraphs[0].runs[0]
                    head.font.size, head.font.bold, head.font.color.rgb = Pt(8.5), True, rgb(tone)
                    para = tf.add_paragraph()
                    run = para.add_run()
                    run.text = _num(rep[yr])
                    run.font.size, run.font.bold, run.font.color.rgb = Pt(13), True, rgb(tone)
                    continue
                tf.text = _num(rep[yr]) if reported_series else "≈" + _num(round_forecast(fc[yr]["value"]))
                run = tf.paragraphs[0].runs[0]
                run.font.size, run.font.bold = Pt(11 if reported_series else 10), reported_series
                run.font.color.rgb = rgb("text" if reported_series else "muted")
            if reported_series and ly in rep:  # the certified point: a green ring
                pt = series.points[years.index(ly)]
                pt.marker.size = 12
                pt.marker.format.fill.solid()
                pt.marker.format.fill.fore_color.rgb = rgb("blue")
                pt.marker.format.line.color.rgb, pt.marker.format.line.width = rgb("brand_green"), Pt(3)


def _rule(cell, color: str | None) -> None:
    """A hairline under the cell (or none), and no other borders. Borders precede the fill in the XML."""
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        for old in tcPr.findall(qn(tag)):
            tcPr.remove(old)
    for i, tag in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
        visible = tag == "a:lnB" and color
        ln = etree.Element(qn(tag), w="9525" if visible else "0")
        if visible:
            fill = etree.SubElement(ln, qn("a:solidFill"))
            etree.SubElement(fill, qn("a:srgbClr"), val=color)
        else:
            etree.SubElement(ln, qn("a:noFill"))
        tcPr.insert(i, ln)


def _status(x: dict, primary: dict) -> str:
    if x["role"] == "selected":
        return "Used: key source"
    if x["used"]:
        return "Used"
    if (primary.get("source_id") and x["tier"] == primary.get("tier") and x.get("as_of_date")
            and primary.get("as_of_date") and x["as_of_date"] < primary["as_of_date"]):
        return "Prior year · trend"
    return "Excluded"


def _brand_links(prs, color: str) -> None:
    """Links take the theme's hyperlink colour, not the run colour: set it to the brand accent so links
    read on both light and dark slides."""
    import re as _re

    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    theme = prs.slide_master.part.part_related_by(RT.THEME)
    xml = theme.blob.decode("utf-8")
    for tag in ("hlink", "folHlink"):
        xml = _re.sub(rf"<a:{tag}>.*?</a:{tag}>", f'<a:{tag}><a:srgbClr val="{color}"/></a:{tag}>', xml, flags=_re.S)
    theme._blob = xml.encode("utf-8")


def _text(slide, x, y, w, h, text, size, color, bold=False, align=None):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    para = tf.paragraphs[0]
    if align is not None:
        para.alignment = align
    run = para.add_run()
    run.text = text
    run.font.size, run.font.bold, run.font.color.rgb = Pt(size), bold, color
    run.font.name = "Segoe UI"
    return box


# --- Word -------------------------------------------------------------------------------------------

def document(record: dict) -> bytes:
    """The full certification as a Word document: answer, facts, trend, findings, key source, sources,
    adjustments, events and LinkedIn, method."""
    r = record
    h, c, p, e, m = r["headline"], r["confidence"], r["primary_source"], r["entity"], r["methodology"]
    doc = Document()
    navy, blue, muted = DRGB(0x0A, 0x25, 0x45), DRGB(0x1F, 0x5F, 0xBF), DRGB(0x4B, 0x5D, 0x75)
    style = doc.styles["Normal"]
    style.font.name, style.font.size = "Segoe UI", DPt(10.5)
    for level in (1, 2):
        hs = doc.styles[f"Heading {level}"]
        hs.font.name, hs.font.color.rgb = "Segoe UI", navy if level == 1 else blue

    if LOGO.is_file():
        doc.add_picture(str(LOGO), height=DPt(28))
    head = doc.add_paragraph()
    run = head.add_run("GTM Data Certifier · Certified employee count")
    run.font.size, run.font.color.rgb, run.bold = DPt(9), muted, True
    doc.add_heading(e["name"], level=1)
    count = (QUAL.get(h.get("qualifier") or "exact", "") + _num(h["count"])) if h.get("count") is not None else "Not certified"
    para = doc.add_paragraph()
    run = para.add_run(count + " employees")
    run.bold, run.font.size, run.font.color.rgb = True, DPt(24), navy
    para = doc.add_paragraph()
    run = para.add_run(f"Confidence {c['score']}/5 · {c['level']} — Bottom line: {h.get('bottom_line') or ''}")
    run.bold, run.font.color.rgb = True, {"ready": DRGB(0x17, 0x79, 0x4A), "usable": DRGB(0x84, 0x55, 0x00),
                                          "directional": DRGB(0xB4, 0x23, 0x18)}[_band(c["score"])]
    if h.get("story"):
        take = doc.add_paragraph()
        label = take.add_run("Our take: ")
        label.bold = True
        take.add_run(h["story"])

    _kv_table(doc, _facts(r) + ([("Source link", (p.get("location") or {}).get("deep_link") or p["url"])]
                                if p.get("source_id") else []), muted)

    doc.add_heading("Trend and forecast", level=2)
    if h.get("direction"):
        doc.add_paragraph(f"{DIRECTION.get(h['direction'], '')}: {h.get('direction_reason') or ''}")
    reported, forecast = _trend(r)
    if reported:
        tbl = doc.add_table(rows=1, cols=3)
        tbl.style = "Light List Accent 1"
        for j, head_text in enumerate(("Year (as of)", "Employees", "Kind")):
            tbl.rows[0].cells[j].text = head_text
        trend_table = tbl
        for x in reported + forecast:
            cells = tbl.add_row().cells
            cells[0].text = x["as_of_date"]
            cells[1].text = _num(x["value"]) + (f" (range {_num(x['low'])}–{_num(x['high'])})" if x["estimated"] else "")
            cells[2].text = "Forecast (estimate)" if x["estimated"] else f"Reported, tier {x.get('tier')}"
        _widths(trend_table, (1.25, 2.85, 2.4))
    else:
        doc.add_paragraph(r["trend"].get("none_reason") or "No trend available.")

    doc.add_heading("Findings", level=2)
    for group, title in (("affects", "Affects the answer"), ("worth_knowing", "Worth knowing"), ("background", "Background")):
        items = [f for f in r["findings"]["items"] if f.get("group") == group]
        if not items:
            continue
        para = doc.add_paragraph()
        run = para.add_run(title.upper())
        run.bold, run.font.size, run.font.color.rgb = True, DPt(9), muted
        for f in items:
            item = doc.add_paragraph(style="List Bullet")
            run = item.add_run(f"{f['title']} ")
            run.bold = True
            run = item.add_run(f"[{f.get('impact', '')}] ")
            run.font.color.rgb = muted
            item.add_run(f"So what: {f.get('so_what', '')} ")
            run = item.add_run(f["rationale"])
            run.font.color.rgb, run.font.size = muted, DPt(9.5)

    if p.get("source_id"):
        doc.add_heading("Key source", level=2)
        loc = p.get("location") or {}
        _kv_table(doc, [("Source", _source_label(p)), ("Link", p["url"]), ("Section", loc.get("section") or "not identified"),
                        ("Page", loc.get("page_label") or ""), ("As of", p.get("as_of_date") or "undated"),
                        ("Why this tier", p.get("tier_rationale") or "")], muted)
        quote = doc.add_paragraph()
        run = quote.add_run("“" + (loc.get("detailed_excerpt") or p.get("excerpt") or "") + "”")
        run.italic = True

    doc.add_heading("Sources", level=2)
    tbl = doc.add_table(rows=1, cols=5)
    tbl.style = "Light List Accent 1"
    for j, head_text in enumerate(("ID", "Source", "Value", "As of", "Status")):
        tbl.rows[0].cells[j].text = head_text
    for x in r["sources"]["items"]:
        cells = tbl.add_row().cells
        cells[0].text = x["id"]
        cells[1].text = ""
        para = cells[1].paragraphs[0]
        run = para.add_run(f"Tier {x['tier']} · {x.get('source_type') or x['tier_name']}")
        run.bold = True
        run = para.add_run("\n" + x["url"])
        run.font.size, run.font.color.rgb = DPt(8.5), blue
        run = para.add_run("\n" + x["use_rationale"])
        run.font.size, run.font.color.rgb = DPt(8.5), muted
        cells[2].text = QUAL.get(x["qualifier"], "") + _num(x["value"])
        cells[3].text = x.get("as_of_date") or "undated"
        cells[4].text = _status(x, p)
    _widths(tbl, (0.4, 3.45, 0.8, 0.95, 0.9))

    if r["adjustments"]["items"]:
        doc.add_heading("Adjustments", level=2)
        for a in r["adjustments"]["items"]:
            doc.add_paragraph(a["rationale"], style="List Bullet")
    doc.add_heading("Events and LinkedIn", level=2)
    for ev in r["events"]["items"]:
        doc.add_paragraph(f"{ev['description']} ({ev.get('close_date') or 'date unknown'}): {ev['rationale']}",
                          style="List Bullet")
    if not r["events"]["items"]:
        doc.add_paragraph(r["events"].get("none_reason") or "No events.")
    doc.add_paragraph(f"LinkedIn check: {r['linkedin_check']['rationale']}")

    doc.add_heading("How it was certified", level=2)
    models = ", ".join(f"{k}: {v}" for k, v in (m.get("models") or {}).items()) or "rule-based"
    doc.add_paragraph(f"Method {m['method']} · models {models} · policy {m['policy_version']} · record "
                      f"{m['record_version']} · run {(m.get('run_at') or m.get('lookup_date') or '')[:19]}.")
    note = doc.add_paragraph()
    run = note.add_run(DISCLAIMER.format(v=m["policy_version"]))
    run.font.color.rgb, run.font.size = muted, DPt(9)
    credit = doc.add_paragraph()
    run = credit.add_run("Designed and created by ")
    run.font.color.rgb, run.font.size = muted, DPt(9)
    _hyperlink(credit, "Matthew Beltrano", CREDIT_URL)
    run = credit.add_run(" & Claude Code · A Human in the Hyperloop project.")
    run.font.color.rgb, run.font.size = muted, DPt(9)
    notice = doc.add_paragraph()
    run = notice.add_run(OWNER_LINE)
    run.font.color.rgb, run.font.size = muted, DPt(8)
    doc.core_properties.author, doc.core_properties.comments = "Matthew Beltrano", COPYRIGHT
    for t in doc.tables:
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _hyperlink(paragraph, text: str, url: str) -> None:
    """A clickable, underlined link in a Word paragraph (python-docx has no direct API for this)."""
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    rel = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rel)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    for tag, val in (("w:color", "1F5FBF"), ("w:u", "single"), ("w:sz", "18")):
        el = OxmlElement(tag)
        el.set(qn("w:val"), val)
        props.append(el)
    run.append(props)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def _kv_table(doc, rows, muted):
    tbl = doc.add_table(rows=0, cols=2)
    tbl.style = "Table Grid"
    for label, value in rows:
        cells = tbl.add_row().cells
        cells[0].text = ""
        run = cells[0].paragraphs[0].add_run(label.upper())
        run.bold, run.font.size, run.font.color.rgb = True, DPt(8.5), muted
        cells[1].text = str(value or "")
    _widths(tbl, (1.45, 5.05))


def _widths(tbl, inches) -> None:
    """Word ignores column widths unless every cell has one and autofit is off."""
    from docx.shared import Inches as DInches
    tbl.autofit = False
    for row in tbl.rows:
        for cell, w in zip(row.cells, inches):
            cell.width = DInches(w)
