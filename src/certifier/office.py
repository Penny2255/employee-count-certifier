# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Slide and document downloads of a certification record: a 4-slide PowerPoint deck (light or dark, in the
GTM Data Certifier brand) and a Word document with the supporting detail. Built from the record JSON only,
so they match the card exactly."""

from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Pt as DPt
from docx.shared import RGBColor as DRGB
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from .notice import COPYRIGHT, OWNER_LINE

LOGO = Path(__file__).resolve().parents[2] / "assets" / "brand" / "hyperloop-logo.png"
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
            ("Range", f"{_num(rng[0])}–{_num(rng[1])}" if rng and rng[0] != rng[1] else "Exact figure"),
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

def deck(record: dict, theme: str = "light") -> bytes:
    """Four slides: the answer, trend and forecast, why you can trust this, sources."""
    t = THEMES.get(theme, THEMES["light"])
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    r = record
    h, c, p, e = r["headline"], r["confidence"], r["primary_source"], r["entity"]
    band = _band(c["score"])
    certified_on = (r["methodology"].get("run_at") or r["methodology"].get("lookup_date") or "")[:10]

    def rgb(key):
        return RGBColor.from_string(t[key])

    def slide(title: str):
        s = prs.slides.add_slide(blank)
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb("bg")
        # Brand band: logo chip, product name, slide title, and a loop-gradient rule.
        chip = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.45), Inches(0.32), Inches(0.95), Inches(0.55))
        chip.fill.solid()
        chip.fill.fore_color.rgb = RGBColor.from_string("FFFFFF")
        chip.line.fill.background()
        if LOGO.is_file():
            s.shapes.add_picture(str(LOGO), Inches(0.52), Inches(0.40), height=Inches(0.39))
        _text(s, Inches(1.55), Inches(0.28), Inches(6), Inches(0.35), "GTM Data Certifier", 13, rgb("text"), bold=True)
        _text(s, Inches(1.55), Inches(0.58), Inches(6), Inches(0.3), "Human in the Hyperloop · Certified employee count",
              10, rgb("muted"))
        _text(s, Inches(7.4), Inches(0.36), Inches(5.5), Inches(0.45), title, 18, rgb("text"), bold=True, align=PP_ALIGN.RIGHT)
        for i, (key, w) in enumerate((("brand_green", 4.6), ("blue", 7.833))):
            bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.45 + (4.6 if i else 0)), Inches(1.02),
                                     Inches(w if not i else 7.833), Emu(38100))
            bar.fill.solid()
            bar.fill.fore_color.rgb = rgb(key)
            bar.line.fill.background()
        _text(s, Inches(0.45), Inches(7.02), Inches(8.4), Inches(0.3),
              f"{e['name']} · certified on {certified_on} · " + DISCLAIMER.format(v=r["methodology"]["policy_version"]),
              9, rgb("muted"))
        credit = _text(s, Inches(8.9), Inches(7.02), Inches(4.0), Inches(0.3), "Designed and created by ", 9, rgb("muted"),
                       align=PP_ALIGN.RIGHT)
        para = credit.text_frame.paragraphs[0]
        for txt, url in (("Matthew Beltrano", CREDIT_URL), (" & Claude Code", None)):
            run = para.add_run()
            run.text = txt
            run.font.size, run.font.name = Pt(9), "Segoe UI"
            run.font.color.rgb = rgb("accent" if url else "muted")
            if url:
                run.hyperlink.address = url
        return s

    def card(s, x, y, w, hgt, fill="card"):
        box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, hgt)
        box.adjustments[0] = 0.06
        box.fill.solid()
        box.fill.fore_color.rgb = rgb(fill)
        box.line.color.rgb = rgb("line")
        box.line.width = Pt(0.75)
        box.shadow.inherit = False
        return box

    # 1. The answer
    s = slide("The answer")
    _text(s, Inches(0.55), Inches(1.3), Inches(7.6), Inches(0.6), e["name"], 26, rgb("text"), bold=True)
    sub = " · ".join(x for x in (e.get("website"), e.get("relationship")) if x)
    _text(s, Inches(0.55), Inches(1.85), Inches(7.6), Inches(0.35), sub, 11, rgb("muted"))
    count = (QUAL.get(h.get("qualifier") or "exact", "") + _num(h["count"])) if h.get("count") is not None else "Not certified"
    _text(s, Inches(0.55), Inches(2.3), Inches(5.5), Inches(1.2), count, 60, rgb("text"), bold=True)
    _text(s, Inches(0.6), Inches(3.45), Inches(5.5), Inches(0.35),
          "employees · " + ("as of " + h["as_of_date"] if h.get("as_of_date") else "undated"), 13, rgb("muted"))
    stamp = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(5.95), Inches(2.25), Inches(1.75), Inches(1.75))
    stamp.fill.solid()
    stamp.fill.fore_color.rgb = rgb({"ready": "green_bg", "usable": "yellow_bg", "directional": "red_bg"}[band])
    stamp.line.color.rgb = rgb({"ready": "green", "usable": "yellow", "directional": "red"}[band])
    stamp.line.width = Pt(3)
    stamp.rotation = -8
    tf = stamp.text_frame
    tf.clear()
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for txt, size in ((c["level"].split(",")[0].upper(), 11), (f"{c['score']}/5", 24)):
        para = tf.paragraphs[0] if not tf.paragraphs[0].runs else tf.add_paragraph()
        para.alignment = PP_ALIGN.CENTER
        run = para.add_run()
        run.text = txt
        run.font.size, run.font.bold = Pt(size), True
        run.font.color.rgb = rgb({"ready": "green", "usable": "yellow", "directional": "red"}[band])
    bl = card(s, Inches(0.55), Inches(4.05), Inches(7.15), Inches(0.75),
              fill={"ready": "green_bg", "usable": "yellow_bg", "directional": "red_bg"}[band])
    bl.line.fill.background()
    _text_in(bl, [("Bottom line: ", True), (h.get("bottom_line") or "", False)], 14,
             rgb({"ready": "green", "usable": "yellow", "directional": "red"}[band]))
    if p.get("source_id"):
        _text(s, Inches(0.55), Inches(4.95), Inches(7.15), Inches(0.3), "Key source", 10, rgb("muted"), bold=True)
        box = _text(s, Inches(0.55), Inches(5.22), Inches(7.15), Inches(0.4), _source_label(p), 13, rgb("text"), bold=True)
        para = box.text_frame.add_paragraph()
        run = para.add_run()
        run.text = "Open the source at the quote ↗"
        run.font.size, run.font.color.rgb = Pt(12), rgb("accent")
        run.hyperlink.address = (p.get("location") or {}).get("deep_link") or p["url"]
    facts = card(s, Inches(8.05), Inches(1.3), Inches(4.85), Inches(5.55))
    _facts_box(s, facts, [f for f in _facts(r) if f[0] not in ("Employees", "Confidence", "Key source")], t)

    # 2. Trend and forecast
    s = slide("Trend and forecast")
    reported, forecast = _trend(r)
    if h.get("direction"):
        d = card(s, Inches(0.55), Inches(1.3), Inches(12.35), Inches(0.62), fill="soft")
        d.line.fill.background()
        _text_in(d, [(DIRECTION.get(h["direction"], "") + " · ", True), (h.get("direction_reason") or "", False)], 12, rgb("text"))
    if reported:
        cats = [x["as_of_date"][:4] for x in reported + forecast]
        data = CategoryChartData()
        data.categories = cats
        data.add_series("Reported", [x["value"] for x in reported] + [None] * len(forecast))
        if forecast:
            data.add_series("Forecast (estimate)", [None] * (len(reported) - 1) + [reported[-1]["value"]] +
                            [x["value"] for x in forecast])
        frame = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.55), Inches(2.1), Inches(12.35), Inches(4.2), data)
        ch = frame.chart
        ch.has_legend = True
        ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
        ch.legend.font.size, ch.legend.font.color.rgb = Pt(11), rgb("muted")
        ch.font.color.rgb = rgb("muted")
        ch.value_axis.has_major_gridlines = True
        ch.value_axis.major_gridlines.format.line.color.rgb = rgb("line")
        ch.value_axis.tick_labels.number_format, ch.value_axis.tick_labels.number_format_is_linked = "#,##0", False
        ch.value_axis.format.line.fill.background()
        ch.category_axis.format.line.color.rgb = rgb("line")
        for axis in (ch.value_axis, ch.category_axis):
            axis.tick_labels.font.size, axis.tick_labels.font.color.rgb = Pt(11), rgb("muted")
        for i, series in enumerate(ch.plots[0].series):
            series.smooth = True
            series.format.line.width = Pt(3 if i == 0 else 2.25)
            series.format.line.color.rgb = rgb("blue")
            if i:
                series.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
            series.marker.style, series.marker.size = XL_MARKER_STYLE.CIRCLE, 8
            series.marker.format.fill.solid()
            series.marker.format.fill.fore_color.rgb = rgb("blue" if i == 0 else "card")
            series.marker.format.line.color.rgb = rgb("blue")
            labels = series.data_labels
            labels.show_value, labels.number_format, labels.number_format_is_linked = True, "#,##0", False
            labels.position = XL_LABEL_POSITION.ABOVE if i == 0 else XL_LABEL_POSITION.BELOW
            labels.font.size, labels.font.bold = Pt(11), i == 0
            labels.font.color.rgb = rgb("text" if i == 0 else "muted")
            if i:  # the forecast starts at the certified point, which the reported series already labels
                series.points[len(reported) - 1].data_label.text_frame.text = ""
        if forecast:
            f = forecast[-1]
            _text(s, Inches(0.55), Inches(6.38), Inches(12.35), Inches(0.35),
                  f"Forecast to {f['as_of_date'][:4]}: {_num(f['value'])} (range {_num(f['low'])}–{_num(f['high'])}). "
                  "A linear trend over the reported years; an estimate, not a reported figure.", 11, rgb("muted"))
    else:
        _text(s, Inches(0.55), Inches(2.3), Inches(12), Inches(0.5), r["trend"].get("none_reason") or "No trend available.",
              14, rgb("muted"))

    # 3. Why you can trust this
    s = slide("Why you can trust this")
    corr = sum(1 for x in r["sources"]["items"] if x["role"] == "corroborates")
    adj = sum(1 for a in r["adjustments"]["items"] if a.get("change"))
    red = sum(1 for f in r["findings"]["items"] if f["status"] == "red")
    tiles = [("Key source", f"Tier {p['tier']} · {p.get('source_type') or p.get('tier_name')}" if p.get("source_id") else "none"),
             ("As of", h.get("as_of_date") or "undated"), ("Independent confirmations", str(corr)),
             ("Adjustments to the count", str(adj)), ("Needs attention", str(red))]
    for i, (label, value) in enumerate(tiles):
        tile = card(s, Inches(0.55 + i * 2.5), Inches(1.3), Inches(2.3), Inches(1.05), fill="soft")
        _text_in(tile, [(label + "\n", False), (value, True)], 12, rgb("text"), first_size=10, first_color=rgb("muted"))
    y = 2.6
    for group, title in (("affects", "Affects the answer"), ("worth_knowing", "Worth knowing")):
        items = [f for f in r["findings"]["items"] if f.get("group") == group][: 5 if group == "affects" else 4]
        if not items:
            continue
        _text(s, Inches(0.55), Inches(y), Inches(12), Inches(0.32), title.upper(), 10, rgb("muted"), bold=True)
        y += 0.36
        for f in items:
            sym = {"green": ("✓", "green"), "yellow": ("!", "yellow"), "red": ("✕", "red")}[f["status"]]
            _text(s, Inches(0.6), Inches(y), Inches(0.35), Inches(0.36), sym[0], 13, rgb(sym[1]), bold=True)
            box = _text(s, Inches(0.95), Inches(y), Inches(9.6), Inches(0.36), f["title"], 12, rgb("text"), bold=True)
            run = box.text_frame.paragraphs[0].add_run()
            run.text = " — " + f.get("so_what", "")
            run.font.size, run.font.color.rgb, run.font.bold = Pt(11), rgb("muted"), False
            _text(s, Inches(10.7), Inches(y), Inches(2.2), Inches(0.36), f.get("impact", ""), 10, rgb("muted"),
                  align=PP_ALIGN.RIGHT)
            y += 0.42
        y += 0.15

    # 4. Sources
    s = slide("Sources")
    rows = r["sources"]["items"][:9]
    tbl = s.shapes.add_table(len(rows) + 1, 5, Inches(0.55), Inches(1.3), Inches(12.35),
                             Inches(0.42 * (len(rows) + 1))).table
    widths = (0.6, 5.6, 1.6, 1.6, 2.95)
    for i, w in enumerate(widths):
        tbl.columns[i].width = Inches(w)
    for j, head in enumerate(("ID", "Source", "Value", "As of", "Status")):
        _cell(tbl.cell(0, j), head, t, header=True)
    for i, x in enumerate(rows, start=1):
        status = _status(x, p)
        vals = (x["id"], f"Tier {x['tier']} · {x.get('source_type') or x['tier_name']}",
                QUAL.get(x["qualifier"], "") + _num(x["value"]), x.get("as_of_date") or "undated", status)
        for j, v in enumerate(vals):
            _cell(tbl.cell(i, j), v, t, bold=(x["role"] == "selected"))
    m = r["methodology"]
    _text(s, Inches(0.55), Inches(1.45 + 0.42 * (len(rows) + 1)), Inches(12.35), Inches(0.8),
          f"{len(r['sources']['items'])} sources found, {sum(1 for x in r['sources']['items'] if x['used'])} used. "
          f"Method: {m['method']} · policy {m['policy_version']} · record {m['record_version']}. "
          "The policy ranks every source by tier, recency and independence; the AI gathers evidence but never "
          "chooses the answer.", 11, rgb("muted"))

    _brand_links(prs, t["accent"])
    out = io.BytesIO()
    prs.core_properties.author, prs.core_properties.comments = "Matthew Beltrano", COPYRIGHT
    prs.save(out)
    return out.getvalue()


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


def _text_in(shape, parts, size, color, first_size=None, first_color=None):
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.18)
    para = tf.paragraphs[0]
    for i, (txt, bold) in enumerate(parts):
        run = para.add_run()
        run.text = txt
        run.font.bold = bold
        run.font.size = Pt(first_size if (i == 0 and first_size) else size)
        run.font.color.rgb = first_color if (i == 0 and first_color) else color
        run.font.name = "Segoe UI"


def _facts_box(slide, box, rows, t):
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = tf.margin_right = Inches(0.25)
    tf.margin_top = Inches(0.2)
    first = True
    for label, value in rows:
        para = tf.paragraphs[0] if first else tf.add_paragraph()
        para.alignment = PP_ALIGN.LEFT
        first = False
        run = para.add_run()
        run.text = label.upper()
        run.font.size, run.font.bold, run.font.color.rgb = Pt(9), True, RGBColor.from_string(t["muted"])
        para2 = tf.add_paragraph()
        para2.alignment = PP_ALIGN.LEFT
        run = para2.add_run()
        run.text = value
        run.font.size, run.font.color.rgb = Pt(12), RGBColor.from_string(t["text"])
        para2.space_after = Pt(8)


def _cell(cell, text, t, header=False, bold=False):
    cell.fill.solid()
    cell.fill.fore_color.rgb = RGBColor.from_string(t["soft"] if header else t["card"])
    tf = cell.text_frame
    tf.clear()
    run = tf.paragraphs[0].add_run()
    run.text = str(text)
    run.font.size = Pt(10 if header else 11)
    run.font.bold = header or bold
    run.font.color.rgb = RGBColor.from_string(t["muted"] if header else t["text"])


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
