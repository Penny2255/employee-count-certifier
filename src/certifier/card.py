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
.cert svg.spark { width: 100%; max-width: 420px; height: 90px; display: block; }
.cert button { font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--primary-bg);
  background: var(--primary-bg); color: var(--primary-text); cursor: pointer; }
.cert button.secondary { background: transparent; color: var(--text); border-color: var(--line); }
.cert footer.block { font-size: 13px; color: var(--muted); }
.cert :target { scroll-margin-top: 12px; }
.cert .flash { animation: cert-flash 1.2s ease-out; }
@keyframes cert-flash { from { background: var(--accent-soft); } to { background: transparent; } }
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
  function section(title, summaryExtra, bodyNodes, open) {
    var d = el("details", { cls: "section" }, [el("summary", null, [el("h2", { text: title }), summaryExtra ? el("span", { cls: "muted small", text: summaryExtra }) : null])]);
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
    var d = t.closest("details.section"); if (d) d.open = true;
    if (t.tagName === "DETAILS") t.open = true;
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

  function headline(r) {
    var h = r.headline, c = r.confidence, k = r.__k;
    var top;
    if (h.count == null) {
      top = el("div", null, [el("div", { cls: "count", text: "Not certified" }), none(h.none_reason)]);
    } else {
      var basis = h.count_basis === "fte" ? "full-time equivalents" : "employees";
      top = el("div", null, [
        el("div", null, [QUAL[h.qualifier] ? el("span", { cls: "qual", text: QUAL[h.qualifier] }) : null, el("span", { cls: "count", text: num(h.count) })]),
        el("div", { cls: "row small" }, [el("span", { text: basis }),
          h.range && h.range[0] !== h.range[1] ? el("span", { cls: "muted", text: "range " + num(h.range[0]) + "–" + num(h.range[1]) }) : null,
          el("span", { cls: "muted", text: asOfText(h) }),
          h.count_type ? el("span", { cls: "badge accent", text: h.count_type }) : null,
          h.adjustment_status === "pre-adjustment" ? el("span", { cls: "badge warn", text: "! pre-adjustment" }) : null])
      ]);
    }
    var meter = el("span", { cls: "meter", role: "img", "aria-label": "Confidence " + c.score + " of 5" });
    for (var i = 1; i <= 5; i++) meter.appendChild(el("span", { cls: i <= c.score ? "on" : "" }));
    var table = el("table", { cls: "lines" });
    c.breakdown.forEach(function (line) {
      table.appendChild(el("tr", null, [el("td", { cls: "pts", text: (line.points > 0 && line !== c.breakdown[0] ? "+" : "") + line.points }),
        el("td", null, [line.rationale + " ", chip(line.finding_id, k + "-")])]));
    });
    table.appendChild(el("tr", { cls: "total" }, [el("td", { cls: "pts", text: String(c.score) }), el("td", { text: "= " + c.arithmetic })]));
    var conf = el("details", null, [el("summary", { cls: "wrap" }, [el("span", null, [meter]), el("strong", { text: "Confidence " + c.score + "/5 · " + c.level }),
      el("span", { cls: "muted small", text: "score breakdown" })]), table]);
    var extra = [];
    if (h.known_changes && h.known_changes.length) {
      extra.push(el("div", { cls: "row small", style: "margin-top:6px" }, [el("span", { cls: "muted", text: "Known change after the as-of date:" }),
        el("span", { text: h.known_changes.join("; ") })]));
    }
    if (h.indicated_current_range) {
      var ir = h.indicated_current_range;
      extra.push(el("div", { cls: "indicated", title: ir.rationale }, [
        el("strong", { text: "Indicated current range " + num(ir.low) + "–" + num(ir.high) }),
        el("span", { cls: "muted small", text: " · newer data-provider figures, " + ir.earliest.slice(0, 7) + (ir.latest !== ir.earliest ? " to " + ir.latest.slice(0, 7) : "") + " · context only, not certified" })]));
    }
    var p = r.primary_source;
    var src = p && p.source_id ? el("div", { cls: "row small muted where" }, [el("span", { text: "Key source: " + where(p.url, p.location) })]) : null;
    return el("div", { cls: "block" }, [top].concat(extra).concat([src, el("div", { style: "margin-top:12px" }, [conf])]).filter(Boolean));
  }

  function primary(r) {
    var p = r.primary_source;
    if (!p.source_id) return section("Key Source", "none", [none(p.none_reason)], true);
    var loc = p.location;
    return section("Key Source", "tier " + p.tier + " · " + (loc.section ? loc.section + " · " : "") + loc.page_label, [
      el("div", { cls: "row" }, [el("span", { cls: "badge accent", text: "Tier " + p.tier }), el("span", { cls: "small", text: p.tier_name })]),
      el("p", { cls: "small muted", style: "margin:8px 0 0", text: "Detailed excerpt (the exact quote is highlighted):" }),
      passage(loc, p.excerpt),
      p.excerpt_missing_reason ? el("p", { cls: "small muted", text: p.excerpt_missing_reason }) : null,
      kv(locationPairs(p.url, loc).concat([["Accession", p.accession], ["As of", p.as_of_date], ["Published", p.published_date],
          ["Modified", p.modified_date], ["Why this tier", p.tier_rationale]]))
    ].filter(Boolean), true);
  }

  function findings(r) {
    var items = r.findings.items, k = r.__k;
    if (!items.length) return section("Findings", "none", [none(r.findings.none_reason)]);
    var counts = { red: 0, yellow: 0, green: 0 };
    items.forEach(function (f) { counts[f.status]++; });
    var nodes = [];
    ["red", "yellow", "green"].forEach(function (s) {
      var group = items.filter(function (f) { return f.status === s; });
      if (!group.length) return;
      nodes.push(el("p", { cls: "group-title", text: STATUS[s][1] + " (" + group.length + ")" }));
      group.forEach(function (f) {
        var impact = f.score_impact ? (f.score_impact > 0 ? "+" : "") + f.score_impact + " to score" : "no score change";
        var ev = el("div", { cls: "row small" }, [el("span", { cls: "muted", text: "Evidence:" })]);
        if (f.evidence.length) f.evidence.forEach(function (id) { ev.appendChild(chip(id, k + "-")); }); else ev.appendChild(el("span", { cls: "muted", text: "none cited" }));
        nodes.push(el("details", { id: k + "-" + f.id }, [
          el("summary", null, [status(f.status), el("span", { text: f.title })]),
          el("div", { cls: "body" }, [el("p", { style: "margin:0 0 6px", text: f.rationale }), ev,
            el("p", { cls: "muted small", style: "margin:4px 0 0", text: f.id + " · " + f.category.replace("_", " ") + " · " + impact })])
        ]));
      });
    });
    var summary = ["red", "yellow", "green"].filter(function (s) { return counts[s]; }).map(function (s) { return counts[s] + " " + STATUS[s][1].toLowerCase(); }).join(", ");
    return section("Findings", summary, nodes, counts.red > 0);
  }

  function sources(r) {
    var items = r.sources.items, k = r.__k;
    if (!items.length) return section("Sources", "none", [none(r.sources.none_reason)]);
    var used = items.filter(function (s) { return s.used; }).length;
    var nodes = [el("div", { cls: "src-sum src-head" }, [el("span", { text: "ID" }), el("span", { text: "Tier" }), el("span", { text: "Value · source" }),
      el("span", { cls: "date", text: "As of" }), el("span", { text: "Status" })])];
    items.forEach(function (s) {
      nodes.push(el("details", { id: k + "-" + s.id }, [
        el("summary", null, [el("span", { cls: "src-sum" }, [el("span", { cls: "muted", text: s.id }), el("span", { cls: "badge", text: "Tier " + s.tier }),
          el("span", { cls: "host" }, [el("strong", { text: (QUAL[s.qualifier] ? QUAL[s.qualifier] + " " : "") + num(s.value) }), " · " + host(s.url)]),
          el("span", { cls: "date muted small", text: s.as_of_date || "undated" }),
          el("span", { cls: "badge" + (s.used ? " accent" : ""), text: s.used ? "Used" : "Excluded" })])]),
        el("div", { cls: "body" }, [passage(s.location, s.excerpt),
          kv([["Role", ROLE[s.role] || s.role], ["Why used / excluded", s.use_rationale], ["Why this tier", s.tier_rationale]]
              .concat(locationPairs(s.url, s.location))
              .concat([["Scope / basis", s.scope + " · " + s.basis], ["Published", s.published_date], ["Modified", s.modified_date],
                       ["Notes", s.notes.length ? s.notes.join(" ") : null]]))])
      ]));
    });
    return section("Sources", items.length + " found, " + used + " used", nodes);
  }

  function adjustments(r) {
    var items = r.adjustments.items;
    if (!items.length) return section("Adjustments", "none", [none(r.adjustments.none_reason)]);
    return section("Adjustments", items.length + " logged", items.map(function (a) {
      var change = a.change ? (a.change > 0 ? "+" : "") + num(a.change) : "note";
      return el("details", null, [el("summary", null, [el("span", { cls: "badge", text: change }),
        el("span", { text: a.source_figure != null ? num(a.source_figure) + " → " + num(a.result) : num(a.result) })]),
        el("div", { cls: "body" }, [el("p", { style: "margin:0", text: a.rationale })])]);
    }));
  }

  function sparkline(points) {
    var W = 420, H = 90, P = 14;
    var vals = [];
    points.forEach(function (p) { vals.push(p.value); if (p.low != null) vals.push(p.low); if (p.high != null) vals.push(p.high); });
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals), span = (max - min) || 1;
    var x = function (i) { return points.length === 1 ? W / 2 : P + i * (W - 2 * P) / (points.length - 1); };
    var y = function (v) { return H - P - (v - min) / span * (H - 2 * P); };
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.setAttribute("class", "spark"); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Trend: " + points.map(function (p) { return p.as_of_date.slice(0, 4) + " " + num(p.value) + (p.estimated ? " (estimated)" : ""); }).join(", "));
    function add(tag, attrs) { var n = document.createElementNS(ns, tag); for (var a in attrs) n.setAttribute(a, attrs[a]); svg.appendChild(n); return n; }
    for (var i = 1; i < points.length; i++) {
      add("line", { x1: x(i - 1), y1: y(points[i - 1].value), x2: x(i), y2: y(points[i].value), stroke: "var(--meter)", "stroke-width": 2,
        "stroke-dasharray": points[i].estimated ? "5 4" : "" });
    }
    points.forEach(function (p, i) {
      if (p.estimated && p.low != null) add("line", { x1: x(i), y1: y(p.low), x2: x(i), y2: y(p.high), stroke: "var(--muted)", "stroke-width": 1.5 });
      add("circle", { cx: x(i), cy: y(p.value), r: 4, fill: p.estimated ? "var(--card)" : "var(--meter)", stroke: "var(--meter)", "stroke-width": 2 });
    });
    return svg;
  }

  function trend(r) {
    var items = r.trend.items, h = r.headline;
    var nodes = [];
    if (h.direction) nodes.push(el("p", { cls: "direction" }, [el("strong", { text: DIRECTION[h.direction] || h.direction }), " · " + (h.direction_reason || "")]));
    if (items.length) {
      var list = el("div", { cls: "row small" });
      items.forEach(function (p) { list.appendChild(el("span", { title: p.rationale, text: p.as_of_date + ": " + num(p.value) + (p.estimated ? " (estimated" + (p.low != null ? ", " + num(p.low) + "–" + num(p.high) : "") + ")" : "") })); });
      nodes.push(sparkline(items), list,
        el("p", { cls: "muted small", text: "Solid points are reported; a hollow point on a dashed line is an estimate, not a reported figure." }));
    } else {
      nodes.push(none(r.trend.none_reason));
    }
    var extra = (items.length ? items.length + " points" : "no points") + (h.direction ? " · " + (DIRECTION[h.direction] || "").replace(/^\S+ /, "").toLowerCase() : "");
    return section("Trend and direction", extra, nodes);
  }

  function events(r) {
    var items = r.events.items, li = r.linkedin_check, k = r.__k;
    var nodes = items.length ? items.map(function (e) {
      return el("details", null, [el("summary", null, [el("span", { cls: "badge", text: e.penalized ? "Lowered confidence" : "Noted" }),
        el("span", { text: e.description + (e.close_date ? " (" + e.close_date + ")" : "") })]),
        el("div", { cls: "body" }, [el("p", { style: "margin:0", text: e.rationale }), e.url ? link(e.url, host(e.url)) : null].filter(Boolean))]);
    }) : [none(r.events.none_reason)];
    nodes.push(el("p", { cls: "group-title", text: "LinkedIn check" }));
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
        header(r), headline(r), primary(r), findings(r), sources(r), adjustments(r), trend(r), events(r), footer(r, records, opts)]));
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
