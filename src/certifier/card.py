"""Company card: the certification record rendered for people.

One renderer (CARD_JS, exposing `window.GTMCard.render`) serves three routes:
- a saved, self-contained HTML file (record embedded as JSON; no external calls);
- an MCP App (ui:// resource) in Claude, which receives the record from the host;
- the hosted web page, which loads the same renderer and styles.
Styles use the GTM Data Certifier brand tokens (TOKENS_CSS) and are scoped under `.cert`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .record import CertificationRecord

OUTPUTS_DIR = Path(__file__).resolve().parents[2] / "outputs"
APP_URI = "ui://employee-count-certifier/card"

# Brand tokens (Human in the Hyperloop): navy, loop blue, loop green, sky. Light follows a soft near-white
# background, dark is navy-based. `data-theme` on <html> overrides the device setting.
TOKENS_CSS = r"""
:root {
  --navy: #0A2545; --loop-blue: #599AF5; --loop-green: #3FCF8E; --sky: #A8E3FF;
  --bg: #F6F8FB; --card: #FFFFFF; --text: #0A2545; --muted: #4B5D75; --line: #DCE3EC; --soft: #EFF3F8;
  --accent: #1F5FBF; --accent-soft: #E6EFFD; --meter: #2F74D9; --focus: #2F74D9;
  --primary-bg: #0A2545; --primary-text: #FFFFFF;
  --green: #17794A; --green-bg: #E3F6EC; --yellow: #845500; --yellow-bg: #FDF3DC; --red: #B42318; --red-bg: #FDEBE9;
  --radius: 12px; --gap: 16px;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #06182F; --card: #0D2440; --text: #EAF2FF; --muted: #A7B8CF; --line: #1E3A5C; --soft: #12304F;
    --accent: #A8E3FF; --accent-soft: #16365C; --meter: #599AF5; --focus: #A8E3FF;
    --primary-bg: #3FCF8E; --primary-text: #0A2545;
    --green: #6FE0A8; --green-bg: #0F3324; --yellow: #F2C35B; --yellow-bg: #33280F; --red: #FF9A90; --red-bg: #3A1A18;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #06182F; --card: #0D2440; --text: #EAF2FF; --muted: #A7B8CF; --line: #1E3A5C; --soft: #12304F;
  --accent: #A8E3FF; --accent-soft: #16365C; --meter: #599AF5; --focus: #A8E3FF;
  --primary-bg: #3FCF8E; --primary-text: #0A2545;
  --green: #6FE0A8; --green-bg: #0F3324; --yellow: #F2C35B; --yellow-bg: #33280F; --red: #FF9A90; --red-bg: #3A1A18;
  color-scheme: dark;
}
"""

CARD_CSS = r"""
.cert { display: grid; gap: var(--gap); }
.cert .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
.cert .block { padding: var(--gap) calc(var(--gap) + 4px); border-top: 1px solid var(--line); }
.cert .block:first-child { border-top: 0; }
.cert h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -.01em; }
.cert h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin: 0; font-weight: 700; }
.cert a { color: var(--accent); overflow-wrap: anywhere; }
.cert .muted { color: var(--muted); }
.cert .small { font-size: 13px; }
.cert .row { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: baseline; }
.cert .badge { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 999px; font-size: 12px;
  font-weight: 600; background: var(--soft); color: var(--muted); border: 1px solid var(--line); white-space: nowrap; }
.cert .badge.accent { background: var(--accent-soft); color: var(--text); border-color: transparent; }
.cert .badge.warn { background: var(--yellow-bg); color: var(--yellow); border-color: transparent; }
.cert .count { font-size: 44px; font-weight: 750; letter-spacing: -.02em; line-height: 1.1; font-variant-numeric: tabular-nums; }
.cert .qual { font-size: 18px; font-weight: 600; color: var(--muted); margin-right: 6px; }
.cert .meter { display: inline-flex; gap: 4px; vertical-align: middle; }
.cert .meter span { width: 26px; height: 10px; border-radius: 3px; background: var(--line); }
.cert .meter span.on { background: var(--meter); }
.cert details { border-top: 1px solid var(--line); }
.cert details:first-of-type { border-top: 0; }
.cert summary { cursor: pointer; list-style: none; padding: 10px 0; display: flex; gap: 8px; align-items: baseline; }
.cert summary > span:last-child { flex: 1 1 auto; min-width: 0; }
.cert .section > summary, .cert summary.wrap { flex-wrap: wrap; row-gap: 4px; }
.cert summary::-webkit-details-marker { display: none; }
.cert summary::before { content: "▸"; color: var(--muted); font-size: 12px; width: 10px; flex: none; }
.cert details[open] > summary::before { content: "▾"; }
.cert summary:focus-visible, .cert a:focus-visible, .cert button:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; border-radius: 4px; }
.cert .section > summary { padding: 0; }
.cert .section > summary h2 { display: inline; }
.cert .section[open] > summary { margin-bottom: 8px; }
.cert .body { padding: 0 0 12px 18px; }
.cert .status { display: inline-flex; gap: 4px; align-items: center; font-size: 12px; font-weight: 700; padding: 1px 8px;
  border-radius: 999px; white-space: nowrap; flex: none; }
.cert .status.green { color: var(--green); background: var(--green-bg); }
.cert .status.yellow { color: var(--yellow); background: var(--yellow-bg); }
.cert .status.red { color: var(--red); background: var(--red-bg); }
.cert .group-title { margin: 12px 0 0; font-size: 13px; font-weight: 600; color: var(--muted); }
.cert .indicated { margin-top: 8px; padding: 6px 10px; border: 1px dashed var(--line); border-radius: 8px; font-size: 14px; }
.cert .direction { margin: 0 0 10px; padding: 8px 12px; background: var(--soft); border-radius: 8px; font-size: 14px; }
.cert mark { background: var(--accent-soft); color: inherit; padding: 0 2px; border-radius: 3px; font-weight: 600; }
.cert .where { margin-top: 6px; }
.cert blockquote { margin: 8px 0; padding: 8px 12px; border-left: 3px solid var(--loop-blue); background: var(--soft);
  border-radius: 0 6px 6px 0; }
.cert .lines { width: 100%; border-collapse: collapse; font-size: 14px; }
.cert .lines td { padding: 6px 4px; border-top: 1px solid var(--line); vertical-align: top; }
.cert .lines td.pts { width: 48px; font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; }
.cert .lines tr.total td { font-weight: 700; }
.cert .src-sum { display: grid; grid-template-columns: 38px 64px 1fr 96px 92px; gap: 8px; width: 100%; align-items: baseline;
  font-variant-numeric: tabular-nums; }
.cert .src-head { padding: 0 0 6px 18px; font-size: 12px; color: var(--muted); font-weight: 600; }
.cert .src-sum .host { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cert .chip { font-size: 12px; padding: 0 6px; border-radius: 4px; background: var(--soft); border: 1px solid var(--line);
  color: var(--text); text-decoration: none; }
.cert .kv { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; font-size: 14px; }
.cert .kv dt { color: var(--muted); }
.cert .kv dd { margin: 0; overflow-wrap: anywhere; }
.cert .answer-grid { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: flex-end; justify-content: space-between; }
.cert .conf-box { display: grid; gap: 4px; justify-items: start; padding: 10px 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--soft); }
.cert .bottom-line { display: flex; gap: 10px; align-items: flex-start; margin: 14px 0 8px; padding: 10px 14px; border-radius: 10px; font-size: 15px; }
.cert .bottom-line .bl-icon { font-weight: 800; }
.cert .bottom-line.ready { background: var(--green-bg); color: var(--green); }
.cert .bottom-line.usable { background: var(--yellow-bg); color: var(--yellow); }
.cert .bottom-line.directional { background: var(--red-bg); color: var(--red); }
.cert .answer-actions { margin-top: 12px; align-items: center; }
.cert .answer-actions .breakdown { border: 0; }
.cert .answer-actions .breakdown > summary { padding: 4px 0; color: var(--accent); font-size: 14px; }
.cert .answer-actions .breakdown[open] { flex-basis: 100%; }
.cert .trust h2, .cert .trend-block h2 { margin-bottom: 10px; }
.cert .trust-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.cert .trust-item { display: grid; gap: 2px; text-align: left; background: var(--soft); color: var(--text); border: 1px solid var(--line);
  border-radius: 10px; padding: 8px 10px; font-size: 14px; }
.cert .trust-item:hover { border-color: var(--loop-blue); }
.cert .trust-item .t-label { font-size: 12px; color: var(--muted); }
.cert .trust-item.good strong { color: var(--green); }
.cert .trust-item.bad strong { color: var(--red); }
.cert .chart-wrap { width: 100%; }
.cert svg.chart { width: 100%; height: auto; display: block; overflow: visible; }
.cert svg.chart .axis { font-size: 11px; fill: var(--muted); }
.cert svg.chart .axis-title { font-size: 11px; fill: var(--muted); font-weight: 600; }
.cert svg.chart .pt-label { font-size: 12px; fill: var(--text); font-weight: 600; }
.cert svg.chart .ir-label { fill: var(--green); }
.cert .legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 6px; }
.cert .lg { display: inline-block; width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; border-radius: 50%; }
.cert .lg.solid { background: var(--meter); }
.cert .lg.hollow { border: 2.5px solid var(--meter); background: var(--card); box-shadow: 14px 0 0 -2px rgba(89, 154, 245, .25); }
.cert .lg.box { border-radius: 2px; border: 1px dashed var(--loop-green); background: rgba(63, 207, 142, .18); }
.cert .next-update { margin: 10px 0 0; }
.cert .direction.lower strong, .cert .direction.higher strong { color: var(--text); }
.cert .label-row { gap: 6px 10px; }
.cert details.what { border: 0; margin: 4px 0; }
.cert details.what > summary { padding: 2px 0; font-size: 13px; color: var(--accent); }
.cert details.what > summary::before { content: none; }
.cert details.what .info { display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid currentColor;
  font-size: 11px; font-weight: 800; font-style: italic; }
.cert details.what p { margin: 2px 0 8px; padding: 8px 12px; background: var(--soft); border-radius: 8px; font-size: 14px; }
.cert .finding > summary { align-items: flex-start; }
.cert .f-main { display: grid; gap: 2px; }
.cert .f-title { font-weight: 600; }
.cert .impact { justify-self: start; font-size: 12px; font-weight: 700; padding: 0 8px; border-radius: 999px; background: var(--soft); color: var(--muted); border: 1px solid var(--line); }
.cert .impact.down { color: var(--red); background: var(--red-bg); border-color: transparent; }
.cert .impact.up { color: var(--green); background: var(--green-bg); border-color: transparent; }
.cert .impact.set { color: var(--text); background: var(--accent-soft); border-color: transparent; }
.cert .so-what { font-size: 14px; color: var(--muted); }
.cert .bg-group { margin-top: 8px; }
.cert .bg-group > summary .group-title { margin: 0; }
.cert button { font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--primary-bg);
  background: var(--primary-bg); color: var(--primary-text); cursor: pointer; }
.cert button.secondary { background: transparent; color: var(--text); border-color: var(--line); }
.cert footer.block { font-size: 13px; color: var(--muted); }
.cert :target { scroll-margin-top: 12px; }
.cert .flash { animation: cert-flash 1.2s ease-out; }
@keyframes cert-flash { from { background: var(--accent-soft); } to { background: transparent; } }
@media (max-width: 760px) { .cert .trust-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) {
  .cert .count { font-size: 34px; }
  .cert .src-sum { grid-template-columns: 34px 56px 1fr 80px; }
  .cert .src-sum .date, .cert .src-head .date { display: none; }
}
@media (prefers-reduced-motion: reduce) { .cert .flash { animation: none; } }
"""

CARD_JS = r"""
(function () {
  "use strict";
  var STATUS = { green: ["✓", "Green"], yellow: ["!", "Yellow"], red: ["✕", "Red"] };
  var QUAL = { exact: "", approximately: "approx.", more_than: "more than", up_to: "up to" };
  var ROLE = { selected: "Used: key source", corroborates: "Used: corroborates", derived_input: "Used: derived",
               supporting: "Excluded", conflicts: "Excluded: conflicts" };
  var DIRECTION = { higher: "↑ Likely higher", lower: "↓ Likely lower", in_line: "→ Likely in line", unknown: "· Direction unclear" };

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (attrs[k] == null) continue;
      if (k === "text") n.textContent = attrs[k]; else if (k === "cls") n.className = attrs[k]; else n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function link(url, label) {
    if (!url || !/^https?:\/\//i.test(url)) return el("span", { text: label || url || "" });
    return el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: label || url });
  }
  function host(url) { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return url || ""; } }
  function num(n) { return n == null ? "–" : Number(n).toLocaleString("en-US"); }
  function status(s) { var t = STATUS[s] || ["?", s]; return el("span", { cls: "status " + s, title: t[1] }, [t[0] + " " + t[1]]); }
  function section(title, summaryExtra, bodyNodes, open, id) {
    var d = el("details", { cls: "section", id: id }, [el("summary", null, [el("h2", { text: title }), summaryExtra ? el("span", { cls: "muted small", text: summaryExtra }) : null])]);
    if (open) d.open = true;
    bodyNodes.forEach(function (b) { d.appendChild(b); });
    return el("div", { cls: "block" }, [d]);
  }
  function none(reason) { return el("p", { cls: "muted small", text: reason || "None." }); }
  function kv(pairs) {
    var dl = el("dl", { cls: "kv" });
    pairs.forEach(function (p) { if (p[1] != null && p[1] !== "") { dl.appendChild(el("dt", { text: p[0] })); dl.appendChild(el("dd", null, [p[1]])); } });
    return dl;
  }
  function jump(id) {
    var t = document.getElementById(id);
    if (!t) return;
    for (var d = t; d; d = d.parentElement ? d.parentElement.closest("details") : null) if (d.tagName === "DETAILS") d.open = true;
    t.scrollIntoView({ behavior: "smooth", block: "center" });
    t.classList.remove("flash"); void t.offsetWidth; t.classList.add("flash");
  }
  function chip(id, prefix) {
    var a = el("a", { cls: "chip", href: "#" + prefix + id, text: id });
    a.addEventListener("click", function (e) { e.preventDefault(); jump(prefix + id); });
    return a;
  }
  function passage(loc, quote) {
    var text = (loc && loc.detailed_excerpt) || quote || "";
    var q = (quote || "").trim(), bq = el("blockquote");
    var i = q ? text.indexOf(q) : -1;
    if (i < 0 && q.length > 30) i = text.indexOf(q.slice(0, 30));
    if (i < 0) { bq.appendChild(document.createTextNode("“" + text + "”")); return bq; }
    var end = text.indexOf(q) === i ? i + q.length : i + 30;
    bq.appendChild(document.createTextNode("“" + text.slice(0, i)));
    bq.appendChild(el("mark", { text: text.slice(i, end) }));
    bq.appendChild(document.createTextNode(text.slice(end) + "”"));
    return bq;
  }
  function where(url, loc) {
    var parts = [host(url)];
    if (loc && loc.section) parts.push(loc.section);
    if (loc && loc.page_label) parts.push(loc.page_label);
    return parts.join(" · ");
  }
  function locationPairs(url, loc) {
    return [["Section", loc.section || "not identified"], ["Page", loc.page_label],
            ["Link", el("span", null, [link(url, host(url)), loc.deep_link ? " · " : null,
              loc.deep_link ? link(loc.deep_link, "open at the quote") : null])],
            ["Location note", loc.note]];
  }
  function asOfText(h) {
    if (!h.as_of_date) return "undated";
    var est = h.as_of_estimated ? (h.as_of_estimated_from === "url" ? " (estimated from URL)" : " (estimated)") : "";
    return "as of " + h.as_of_date + est;
  }

  function header(r) {
    var e = r.entity;
    return el("div", { cls: "block" }, [
      el("h1", { text: e.name }),
      el("div", { cls: "row small muted" }, [e.website ? link(e.website, host(e.website)) : null, e.hq ? el("span", { text: e.hq }) : null,
        el("span", { text: e.relationship })])
    ]);
  }

  function band(score) { return score >= 4 ? "ready" : score === 3 ? "usable" : "directional"; }
  function sourceLabel(s) {
    if (!s || !s.source_type) return "Tier " + (s && s.tier);
    return "Tier " + s.tier + " · " + s.source_category + " · " + s.source_type;
  }
  function labelRow(s) {
    return el("div", { cls: "row label-row" }, [el("span", { cls: "badge accent", text: "Tier " + s.tier }),
      el("strong", { cls: "small", text: s.source_category || s.tier_name }), s.source_type ? el("span", { cls: "small", text: s.source_type }) : null]);
  }
  function whatIsThis(s) {
    if (!s || !s.source_type_info) return null;
    return el("details", { cls: "what" }, [el("summary", null, [el("span", { cls: "info", "aria-hidden": "true", text: "i" }),
      el("span", { text: "What is this?" })]), el("p", { text: s.source_type_info })]);
  }

  // One clean, pasteable block for a CRM field or note.
  function crmText(r) {
    var h = r.headline, c = r.confidence, p = r.primary_source;
    var corr = r.sources.items.filter(function (s) { return s.role === "corroborates"; }).length;
    var why = h.count == null ? (h.none_reason || "No usable public source.") :
      (p.source_type ? p.source_type : "Derived from data providers") + (h.as_of_date ? " as of " + h.as_of_date : "") +
      "; " + corr + " independent confirmation" + (corr === 1 ? "" : "s") + "; " + h.bottom_line;
    return [
      r.entity.name + " · certified employee count",
      "Employees: " + (h.count == null ? "not certified" : (QUAL[h.qualifier] ? QUAL[h.qualifier] + " " : "") + num(h.count)) +
        (h.range && h.range[0] !== h.range[1] ? " (range " + num(h.range[0]) + "–" + num(h.range[1]) + ")" : ""),
      "As of: " + (h.as_of_date || "undated") + (h.as_of_estimated ? " (estimated)" : ""),
      "Confidence: " + c.score + "/5 (" + c.level + ")",
      "Source: " + (p.url ? sourceLabel(p) + " · " + p.url : "none"),
      "Rationale: " + why,
      "Certified by GTM Data Certifier, policy v" + r.methodology.policy_version + ", " + (r.methodology.run_at || r.methodology.lookup_date || "").slice(0, 10)
    ].join("\n");
  }
  function copyText(text, button, label) {
    var done = function () { button.textContent = "Copied"; setTimeout(function () { button.textContent = label; }, 1600); };
    function fallback() { var t = el("textarea"); t.value = text; document.body.appendChild(t); t.select(); try { document.execCommand("copy"); done(); } catch (e) {} t.remove(); }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }

  function answer(r) {
    var h = r.headline, c = r.confidence, k = r.__k, p = r.primary_source;
    var nodes = [];
    var meter = el("span", { cls: "meter", role: "img", "aria-label": "Confidence " + c.score + " of 5" });
    for (var i = 1; i <= 5; i++) meter.appendChild(el("span", { cls: i <= c.score ? "on" : "" }));
    if (h.count == null) {
      nodes.push(el("div", { cls: "count", text: "Not certified" }));
    } else {
      var basis = h.count_basis === "fte" ? "full-time equivalents" : "employees";
      nodes.push(el("div", { cls: "answer-grid" }, [
        el("div", null, [
          el("div", null, [QUAL[h.qualifier] ? el("span", { cls: "qual", text: QUAL[h.qualifier] }) : null, el("span", { cls: "count", text: num(h.count) })]),
          el("div", { cls: "row small" }, [el("span", { text: basis }),
            h.range && h.range[0] !== h.range[1] ? el("span", { cls: "muted", text: "range " + num(h.range[0]) + "–" + num(h.range[1]) }) : null,
            el("span", { cls: "muted", text: asOfText(h) }),
            h.count_type ? el("span", { cls: "badge accent", text: h.count_type }) : null,
            h.adjustment_status === "pre-adjustment" ? el("span", { cls: "badge warn", text: "! pre-adjustment" }) : null])]),
        el("div", { cls: "conf-box" }, [meter, el("strong", { text: "Confidence " + c.score + "/5" }), el("span", { cls: "small", text: c.level })])
      ]));
    }
    var b = band(c.score);
    nodes.push(el("p", { cls: "bottom-line " + b }, [el("span", { cls: "bl-icon", "aria-hidden": "true", text: b === "ready" ? "✓" : b === "usable" ? "!" : "✕" }),
      el("span", null, [el("strong", { text: "Bottom line: " }), h.bottom_line || ""])]));
    if (p && p.source_id) nodes.push(el("div", { cls: "row small where" }, [el("span", { cls: "muted", text: "Key source:" }),
      el("span", { text: sourceLabel(p) + " · " + where(p.url, p.location) })]));
    if (h.known_changes && h.known_changes.length) {
      nodes.push(el("div", { cls: "row small", style: "margin-top:6px" }, [el("span", { cls: "muted", text: "Known change after the as-of date:" }),
        el("span", { text: h.known_changes.join("; ") })]));
    }
    if (h.indicated_current_range) {
      var ir = h.indicated_current_range;
      nodes.push(el("div", { cls: "indicated", title: ir.rationale }, [
        el("strong", { text: "Indicated current range " + (ir.low === ir.high ? "about " + num(ir.low) : num(ir.low) + "–" + num(ir.high)) }),
        el("span", { cls: "muted small", text: " · newer data-provider figures, " + ir.earliest.slice(0, 7) + (ir.latest !== ir.earliest ? " to " + ir.latest.slice(0, 7) : "") + " · context only, not certified" })]));
    }
    var table = el("table", { cls: "lines" });
    c.breakdown.forEach(function (line) {
      table.appendChild(el("tr", null, [el("td", { cls: "pts", text: (line.points > 0 && line !== c.breakdown[0] ? "+" : "") + line.points }),
        el("td", null, [line.rationale + " ", chip(line.finding_id, k + "-")])]));
    });
    table.appendChild(el("tr", { cls: "total" }, [el("td", { cls: "pts", text: String(c.score) }), el("td", { text: "= " + c.arithmetic })]));
    var crm = el("button", { type: "button", cls: "crm", text: "Copy for CRM" });
    crm.addEventListener("click", function () { copyText(crmText(r), crm, "Copy for CRM"); });
    nodes.push(el("div", { cls: "row answer-actions" }, [crm,
      el("details", { cls: "breakdown" }, [el("summary", null, [el("span", { text: "How the score adds up" })]), table])]));
    return el("div", { cls: "block answer" }, nodes);
  }

  // "Why you can trust this": five facts, each opening its detail.
  function trust(r) {
    var k = r.__k, p = r.primary_source, h = r.headline;
    var corr = r.sources.items.filter(function (s) { return s.role === "corroborates"; });
    var corrFinding = r.findings.items.filter(function (f) { return f.category === "corroboration"; })[0];
    var adj = r.adjustments.items.filter(function (a) { return a.change; }).length;
    var attention = r.findings.items.filter(function (f) { return f.status === "red"; }).length;
    function item(label, value, target, tone) {
      var b = el("button", { type: "button", cls: "trust-item" + (tone ? " " + tone : "") }, [el("span", { cls: "t-label", text: label }), el("strong", { text: value })]);
      b.addEventListener("click", function () { jump(target); });
      return b;
    }
    return el("div", { cls: "block trust", role: "group", "aria-label": "Why you can trust this" }, [
      el("h2", { text: "Why you can trust this" }),
      el("div", { cls: "trust-strip" }, [
        item("Key source", p && p.source_id ? "Tier " + p.tier + " · " + (p.source_type || p.tier_name) : "none", k + "-key"),
        item("As of", h.as_of_date ? h.as_of_date + (h.as_of_estimated ? " (est.)" : "") : "undated", k + "-key"),
        item("Independent confirmations", String(corr.length), corrFinding ? k + "-" + corrFinding.id : k + "-sources", corr.length ? "good" : ""),
        item("Adjustments to the count", String(adj), k + "-adjustments"),
        item("Needs attention", String(attention), k + "-findings", attention ? "bad" : "good")])]);
  }

  // Trend and forecast: reported points solid, estimates hollow, forecast as a shaded band, indicated range as a box.
  function chart(r) {
    var h = r.headline, items = r.trend.items.slice(), ir = h.indicated_current_range;
    if (!items.length && h.count != null && h.as_of_date) items = [{ as_of_date: h.as_of_date, value: h.count, estimated: false }];
    if (!items.length && !ir) return null;
    // Drawn at roughly the on-screen width, so labels stay readable on phones.
    var W = Math.max(320, Math.min(640, (document.documentElement.clientWidth || 640) - 72));
    var H = W < 480 ? 230 : 240, L = W < 480 ? 52 : 64, R = 20, T = 30, B = 40, ns = "http://www.w3.org/2000/svg";
    var t = function (d) { return new Date(d + "T00:00:00Z").getTime(); };
    var xs = items.map(function (p) { return t(p.as_of_date); }), vals = [];
    items.forEach(function (p) { vals.push(p.value); if (p.low != null) { vals.push(p.low); vals.push(p.high); } });
    if (ir) { xs.push(t(ir.earliest), t(ir.latest)); vals.push(ir.low, ir.high); }
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), day = 864e5;
    if (x1 - x0 < 300 * day) { x0 -= 180 * day; x1 += 180 * day; }
    var pad = (x1 - x0) * 0.06; x0 -= pad; x1 += pad;
    var v0 = Math.min.apply(null, vals), v1 = Math.max.apply(null, vals);
    var vpad = (v1 - v0) * 0.15 || Math.max(1, v1 * 0.08); v0 = Math.max(0, v0 - vpad); v1 += vpad;
    var step = Math.pow(10, Math.floor(Math.log10((v1 - v0) / 3))); [1, 2, 5, 10].some(function (m) { if ((v1 - v0) / (step * m) <= 4) { step *= m; return true; } });
    var X = function (ms) { return L + (ms - x0) / (x1 - x0) * (W - L - R); };
    var Y = function (v) { return T + (1 - (v - v0) / (v1 - v0)) * (H - T - B); };
    var svgEl = document.createElementNS(ns, "svg");
    svgEl.setAttribute("viewBox", "0 0 " + W + " " + H); svgEl.setAttribute("class", "chart"); svgEl.setAttribute("role", "img");
    svgEl.setAttribute("aria-label", "Headcount over time: " + items.map(function (p) { return p.as_of_date + " " + num(p.value) + (p.estimated ? " (forecast, " + num(p.low) + " to " + num(p.high) + ")" : " (reported)"); }).join("; ") +
      (ir ? "; indicated current range " + num(ir.low) + " to " + num(ir.high) : ""));
    function add(tag, attrs, text) { var n = document.createElementNS(ns, tag); for (var a in attrs) n.setAttribute(a, attrs[a]); if (text != null) n.textContent = text; svgEl.appendChild(n); return n; }
    for (var v = Math.ceil(v0 / step) * step; v <= v1; v += step) {
      add("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "var(--line)", "stroke-width": 1 });
      add("text", { x: L - 8, y: Y(v) + 4, "text-anchor": "end", "class": "axis" }, num(Math.round(v)));
    }
    var y0 = new Date(x0).getUTCFullYear(), y1 = new Date(x1).getUTCFullYear(), every = Math.max(1, Math.ceil((y1 - y0 + 1) / 7));
    for (var yr = y0; yr <= y1 + 1; yr += every) {
      var ms = Date.UTC(yr, 0, 1); if (ms < x0 || ms > x1) continue;
      add("line", { x1: X(ms), x2: X(ms), y1: H - B, y2: H - B + 5, stroke: "var(--muted)" });
      add("text", { x: X(ms), y: H - B + 18, "text-anchor": "middle", "class": "axis" }, String(yr));
    }
    add("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, stroke: "var(--muted)", "stroke-width": 1 });
    add("text", { x: 4, y: 12, "class": "axis-title", "text-anchor": "start" }, "Employees");
    add("text", { x: L + (W - L - R) / 2, y: H - 4, "class": "axis-title", "text-anchor": "middle" }, "As-of date");
    if (ir) {
      var rx = X(t(ir.earliest)), rw = Math.max(16, X(t(ir.latest)) - rx), rh = Math.max(10, Y(ir.low) - Y(ir.high));
      var ry = Y(ir.high) - (rh === 10 ? 5 - (Y(ir.low) - Y(ir.high)) / 2 : 0);
      add("rect", { x: rx - (rw === 16 ? 8 : 0), y: ry, width: rw, height: rh, fill: "var(--loop-green)", "fill-opacity": .25,
        stroke: "var(--loop-green)", "stroke-width": 1.5, "stroke-dasharray": "4 3", rx: 2 });
      add("text", { x: rx + (rw === 16 ? 0 : rw / 2), y: ry - 6, "text-anchor": "middle", "class": "pt-label ir-label" },
        ir.low === ir.high ? "≈" + num(ir.low) : num(ir.low) + "–" + num(ir.high));
    }
    var reported = items.filter(function (p) { return !p.estimated; }), last = reported[reported.length - 1];
    items.filter(function (p) { return p.estimated && p.low != null; }).forEach(function (f) {
      if (last) add("polygon", { points: [X(t(last.as_of_date)), Y(last.value), X(t(f.as_of_date)), Y(f.high), X(t(f.as_of_date)), Y(f.low)].join(" "),
        fill: "var(--loop-blue)", "fill-opacity": .18 });
      if (last) add("line", { x1: X(t(last.as_of_date)), y1: Y(last.value), x2: X(t(f.as_of_date)), y2: Y(f.value), stroke: "var(--meter)", "stroke-width": 2, "stroke-dasharray": "5 4" });
    });
    for (var i = 1; i < reported.length; i++) add("line", { x1: X(t(reported[i - 1].as_of_date)), y1: Y(reported[i - 1].value), x2: X(t(reported[i].as_of_date)), y2: Y(reported[i].value), stroke: "var(--meter)", "stroke-width": 2.5 });
    items.forEach(function (p) {
      add("circle", { cx: X(t(p.as_of_date)), cy: Y(p.value), r: 5, fill: p.estimated ? "var(--card)" : "var(--meter)", stroke: "var(--meter)", "stroke-width": 2.5 });
      add("text", { x: X(t(p.as_of_date)), y: Y(p.value) - 10, "text-anchor": "middle", "class": "pt-label" }, num(p.value));
    });
    return svgEl;
  }

  function trendBlock(r) {
    var h = r.headline, items = r.trend.items, nodes = [el("h2", { text: "Trend and forecast" })];
    if (h.direction) nodes.push(el("p", { cls: "direction " + h.direction }, [el("strong", { text: DIRECTION[h.direction] || h.direction }), " · " + (h.direction_reason || "")]));
    var svgEl = chart(r);
    if (svgEl) {
      nodes.push(el("div", { cls: "chart-wrap" }, [svgEl]));
      nodes.push(el("div", { cls: "legend small muted" }, [el("span", null, [el("i", { cls: "lg solid" }), "Reported"]),
        items.some(function (p) { return p.estimated; }) ? el("span", null, [el("i", { cls: "lg hollow" }), "Estimated (forecast) with shaded range"]) : null,
        h.indicated_current_range ? el("span", null, [el("i", { cls: "lg box" }), "Indicated current range (context only)"]) : null]));
    } else {
      nodes.push(none(r.trend.none_reason));
    }
    if (h.next_update_note) nodes.push(el("p", { cls: "small next-update" }, [el("strong", { text: "Next update: " }), h.next_update_note]));
    return el("div", { cls: "block trend-block", id: r.__k + "-trend" }, nodes);
  }

  function primary(r) {
    var p = r.primary_source, k = r.__k;
    if (!p.source_id) return section("Key Source", "none", [none(p.none_reason)], true, k + "-key");
    var loc = p.location;
    return section("Key Source", sourceLabel(p) + " · " + (loc.section ? loc.section + " · " : "") + loc.page_label, [
      labelRow(p), whatIsThis(p),
      el("p", { cls: "small muted", style: "margin:8px 0 0", text: "Detailed excerpt (the exact quote is highlighted):" }),
      passage(loc, p.excerpt),
      p.excerpt_missing_reason ? el("p", { cls: "small muted", text: p.excerpt_missing_reason }) : null,
      kv(locationPairs(p.url, loc).concat([["Accession", p.accession], ["As of", p.as_of_date], ["Published", p.published_date],
          ["Modified", p.modified_date], ["Why this tier", p.tier_rationale]]))
    ].filter(Boolean), false, k + "-key");
  }

  var GROUPS = [["affects", "Affects the answer"], ["worth_knowing", "Worth knowing"], ["background", "Background"]];
  function findingNode(f, k) {
    var group = f.group || (f.score_impact ? "affects" : "worth_knowing");
    var impact = f.impact || (f.score_impact ? (f.score_impact > 0 ? "Raised" : "Lowered") + " confidence by " + Math.abs(f.score_impact) : "No effect on the answer");
    var tone = /^Lowered/.test(impact) ? "down" : /^Raised|^Chose/.test(impact) ? "up" : /^Adjusted|^Sets/.test(impact) ? "set" : "none";
    var ev = el("div", { cls: "row small" }, [el("span", { cls: "muted", text: "Evidence:" })]);
    if (f.evidence.length) f.evidence.forEach(function (id) { ev.appendChild(chip(id, k + "-")); }); else ev.appendChild(el("span", { cls: "muted", text: "none cited" }));
    return el("details", { id: k + "-" + f.id, cls: "finding " + group }, [
      el("summary", null, [status(f.status), el("span", { cls: "f-main" }, [
        el("span", { cls: "f-title", text: f.title }), " ", el("span", { cls: "impact " + tone, text: impact }),
        f.so_what ? el("span", { cls: "so-what", text: "So what: " + f.so_what }) : null])]),
      el("div", { cls: "body" }, [el("p", { style: "margin:0 0 6px", text: f.rationale }), ev,
        el("p", { cls: "muted small", style: "margin:4px 0 0", text: f.id + " · " + f.category.replace("_", " ") })])
    ]);
  }
  function findings(r) {
    var items = r.findings.items, k = r.__k;
    if (!items.length) return section("Findings", "none", [none(r.findings.none_reason)], true, k + "-findings");
    var nodes = [], counts = [];
    GROUPS.forEach(function (g) {
      var list = items.filter(function (f) { return (f.group || (f.score_impact ? "affects" : "worth_knowing")) === g[0]; });
      if (!list.length) return;
      counts.push(list.length + " " + g[1].toLowerCase());
      if (g[0] === "background") {
        nodes.push(el("details", { cls: "bg-group" }, [el("summary", null, [el("span", { cls: "group-title", text: g[1] + " (" + list.length + ")" }),
          el("span", { cls: "muted small", text: "technical detail" })])].concat(list.map(function (f) { return findingNode(f, k); }))));
      } else {
        nodes.push(el("p", { cls: "group-title", text: g[1] + " (" + list.length + ")" }));
        list.forEach(function (f) { nodes.push(findingNode(f, k)); });
      }
    });
    return section("Findings", counts.join(" · "), nodes, true, k + "-findings");
  }

  function sources(r) {
    var items = r.sources.items, k = r.__k;
    if (!items.length) return section("Sources", "none", [none(r.sources.none_reason)], false, k + "-sources");
    var used = items.filter(function (s) { return s.used; }).length;
    var nodes = [el("div", { cls: "src-sum src-head" }, [el("span", { text: "ID" }), el("span", { text: "Tier" }), el("span", { text: "Value · source type" }),
      el("span", { cls: "date", text: "As of" }), el("span", { text: "Status" })])];
    items.forEach(function (s) {
      nodes.push(el("details", { id: k + "-" + s.id }, [
        el("summary", null, [el("span", { cls: "src-sum" }, [el("span", { cls: "muted", text: s.id }), el("span", { cls: "badge", text: "Tier " + s.tier }),
          el("span", { cls: "host" }, [el("strong", { text: (QUAL[s.qualifier] ? QUAL[s.qualifier] + " " : "") + num(s.value) }), " · " + (s.source_type || host(s.url))]),
          el("span", { cls: "date muted small", text: s.as_of_date || "undated" }),
          el("span", { cls: "badge" + (s.used ? " accent" : ""), text: s.used ? "Used" : "Excluded" })])]),
        el("div", { cls: "body" }, [labelRow(s), whatIsThis(s), passage(s.location, s.excerpt),
          kv([["Role", ROLE[s.role] || s.role], ["Why used / excluded", s.use_rationale], ["Why this tier", s.tier_rationale]]
              .concat(locationPairs(s.url, s.location))
              .concat([["Scope / basis", s.scope + " · " + s.basis], ["Published", s.published_date], ["Modified", s.modified_date],
                       ["Notes", s.notes.length ? s.notes.join(" ") : null]]))].filter(Boolean))
      ]));
    });
    return section("Sources", items.length + " found, " + used + " used", nodes, false, k + "-sources");
  }

  function adjustments(r) {
    var items = r.adjustments.items, k = r.__k;
    if (!items.length) return section("Adjustments", "none", [none(r.adjustments.none_reason)], false, k + "-adjustments");
    return section("Adjustments", items.length + " logged", items.map(function (a) {
      var change = a.change ? (a.change > 0 ? "+" : "") + num(a.change) : "note";
      return el("details", null, [el("summary", null, [el("span", { cls: "badge", text: change }),
        el("span", { text: a.source_figure != null ? num(a.source_figure) + " → " + num(a.result) : num(a.result) })]),
        el("div", { cls: "body" }, [el("p", { style: "margin:0", text: a.rationale })])]);
    }), false, k + "-adjustments");
  }

  function events(r) {
    var items = r.events.items, li = r.linkedin_check, k = r.__k;
    var nodes = items.length ? items.map(function (e) {
      return el("details", null, [el("summary", null, [el("span", { cls: "badge", text: e.penalized ? "Lowered confidence" : "Noted" }),
        el("span", { text: e.description + (e.close_date ? " (" + e.close_date + ")" : "") })]),
        el("div", { cls: "body" }, [el("p", { style: "margin:0", text: e.rationale }), e.url ? link(e.url, host(e.url)) : null].filter(Boolean))]);
    }) : [none(r.events.none_reason)];
    nodes.push(el("p", { cls: "group-title", text: "LinkedIn check" }));
    if (li.source_type) nodes.push(el("div", { cls: "row small" }, [el("strong", { text: li.source_category }), el("span", { text: li.source_type })]));
    if (li.source_type_info) nodes.push(whatIsThis(li));
    nodes.push(el("p", { cls: "small", style: "margin:4px 0" }, [li.rationale + " ", chip(li.finding_id, k + "-")]));
    return section("Events and LinkedIn", (items.length ? items.length + " event(s)" : "no events") + " · LinkedIn " + li.status.replace("_", " "), nodes);
  }

  function footer(r, all, opts) {
    var m = r.methodology;
    var models = Object.keys(m.models || {}).map(function (k) { return k + ": " + m.models[k]; }).join(", ");
    var parts = [kv([["Method", m.method], ["Models", models || "none (rule-based)"], ["Policy version", m.policy_version + " · record " + m.record_version],
          ["Cost", "$" + Number(m.cost_usd).toFixed(2) + " · " + m.web_searches + " searches, " + m.web_fetches + " fetches"],
          ["Run", (m.run_at ? m.run_at.replace("T", " ").slice(0, 19) + " UTC" : m.lookup_date) + (m.duration_s != null ? " · " + m.duration_s + " s" : "")]])];
    if (opts.actions) {
      var dl = el("button", { type: "button", text: "Download JSON" });
      dl.addEventListener("click", function () { download(all); });
      var cp = el("button", { type: "button", cls: "secondary", text: "Copy JSON" });
      cp.addEventListener("click", function () { copy(all, cp); });
      parts.push(el("div", { cls: "row", style: "margin-top:12px" }, [dl, cp]));
    }
    return el("footer", { cls: "block" }, parts);
  }

  function json(all) { return JSON.stringify(all.length === 1 ? all[0] : all, function (k, v) { return k === "__k" ? undefined : v; }, 2); }
  function download(all) {
    var name = (all[0].entity.name || "certification").replace(/[^a-z0-9]+/gi, "-").toLowerCase() + ".json";
    try {
      var url = URL.createObjectURL(new Blob([json(all)], { type: "application/json" }));
      var a = el("a", { href: url, download: name }); document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
    } catch (e) { alert("Download is blocked here; use Copy JSON instead."); }
  }
  function copy(all, button) {
    var text = json(all), done = function () { button.textContent = "Copied"; setTimeout(function () { button.textContent = "Copy JSON"; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
    function fallback() { var t = el("textarea"); t.value = text; document.body.appendChild(t); t.select(); try { document.execCommand("copy"); done(); } catch (e) {} t.remove(); }
  }

  function toRecords(data) {
    if (!data) return [];
    if (data.result && !data.headline && !data.entity) data = data.result;  // structured output wrapper
    if (Array.isArray(data.records)) return data.records;
    if (data.headline && data.entity) return [data];
    var out = [];
    ["entity", "parent"].forEach(function (key) { var d = data[key]; if (d && d.record) out.push(d.record); });
    return out;
  }

  function render(root, data, opts) {
    opts = opts || {};
    var records = toRecords(data);
    root.textContent = "";
    if (!records.length) { root.appendChild(el("p", { cls: "muted", text: "No certification record in this result." })); return records; }
    records.forEach(function (r, i) {
      r.__k = "r" + i;
      root.appendChild(el("article", { cls: "card", "aria-label": "Certification for " + r.entity.name }, [
        header(r), answer(r), trust(r), trendBlock(r), findings(r), primary(r), sources(r), adjustments(r), events(r),
        footer(r, records, opts)]));
    });
    if (location.hash === "#expand-all") Array.prototype.forEach.call(root.querySelectorAll("details"), function (d) { d.open = true; });
    if (opts.onRender) opts.onRender(records);
    return records;
  }

  window.GTMCard = { render: render, toRecords: toRecords };
})();
"""

# Boot for the standalone file and the MCP App: render embedded data, or data pushed by the host.
BOOT_JS = r"""
(function () {
  "use strict";
  var root = document.getElementById("root");
  var nextId = 1, pending = {}, inFrame = window.parent && window.parent !== window;
  function post(msg) { try { window.parent.postMessage(msg, "*"); } catch (e) {} }
  function request(method, params) { var id = nextId++; post({ jsonrpc: "2.0", id: id, method: method, params: params });
    return new Promise(function (resolve) { pending[id] = resolve; setTimeout(function () { resolve(null); }, 4000); }); }
  function notify(method, params) { post({ jsonrpc: "2.0", method: method, params: params || {} }); }
  function applyTheme(ctx) { if (ctx && (ctx.theme === "dark" || ctx.theme === "light")) document.documentElement.setAttribute("data-theme", ctx.theme); }
  function reportSize() { if (inFrame) notify("ui/notifications/size-changed", { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }); }
  function show(data) {
    var records = window.GTMCard.render(root, data, { actions: true, onRender: reportSize });
    if (records.length) document.title = records.map(function (r) { return r.entity.name; }).join(" + ") + " · GTM Data Certifier";
  }
  window.addEventListener("message", function (event) {
    var m = event.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id != null && pending[m.id]) { pending[m.id](m.result); delete pending[m.id]; return; }
    var p = m.params || {};
    if (m.method === "ui/notifications/host-context-changed") applyTheme(p.hostContext || p);
    var result = p.structuredContent ? p : (p.result && p.result.structuredContent ? p.result : null);
    if (result) show(result.structuredContent);
  });
  var embedded = null;
  try { embedded = JSON.parse(document.getElementById("record-data").textContent); } catch (e) {}
  if (embedded) show(embedded);
  if (inFrame) {
    request("ui/initialize", { protocolVersion: "2025-06-18", appInfo: { name: "GTM Data Certifier card", version: "1.0.0" },
      clientInfo: { name: "GTM Data Certifier card", version: "1.0.0" }, appCapabilities: {}, capabilities: {} })
      .then(function (res) { if (res) applyTheme(res.hostContext); notify("ui/notifications/initialized", {}); reportSize(); });
    if (window.ResizeObserver) new ResizeObserver(reportSize).observe(document.body);
  }
})();
"""

_STANDALONE_BASE_CSS = r"""
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: var(--gap); }
"""

TEMPLATE = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
    "<meta name=\"color-scheme\" content=\"light dark\">\n<title>__TITLE__</title>\n<style>"
    + TOKENS_CSS + _STANDALONE_BASE_CSS + CARD_CSS
    + "</style>\n</head>\n<body>\n<main id=\"root\" class=\"cert\"><p class=\"muted\">Waiting for the certification…</p></main>\n"
    "<script type=\"application/json\" id=\"record-data\">__DATA__</script>\n<script>"
    + CARD_JS + BOOT_JS + "</script>\n</body>\n</html>\n"
)


def _embed(data) -> str:
    """JSON safe to place inside a <script> element."""
    return json.dumps(data, ensure_ascii=False, default=str).replace("<", "\\u003c")  # can't close or comment the block


def render_card(records: list[CertificationRecord]) -> str:
    """A standalone card file for one lookup (the entity, plus its parent when certified)."""
    payload = {"records": [json.loads(r.model_dump_json()) for r in records]}
    title = " + ".join(r.entity.name for r in records) + " · GTM Data Certifier"
    return TEMPLATE.replace("__TITLE__", _html_escape(title)).replace("__DATA__", _embed(payload))


def app_html() -> str:
    """The MCP App resource: same template, no embedded data (the host sends the tool result)."""
    return TEMPLATE.replace("__TITLE__", "GTM Data Certifier").replace("__DATA__", "null")


def save_card(records: list[CertificationRecord], directory: Path | None = None) -> Path:
    directory = directory or OUTPUTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", records[0].entity.name.lower()).strip("-") or "certification"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = directory / f"{slug}-{stamp}.html"
    path.write_text(render_card(records), encoding="utf-8")
    return path


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    """certifier-card LOOKUP.json [...]: build a card per saved lookup result (no API calls)."""
    import sys

    from .record import record_from_lookup
    from .service import LookupResult

    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        sys.exit("usage: certifier-card LOOKUP.json [LOOKUP.json ...]")
    for p in paths:
        result = LookupResult.model_validate_json(p.read_text(encoding="utf-8"))
        print(save_card([record_from_lookup(result)]))


if __name__ == "__main__":
    main()
