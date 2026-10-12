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
  --bg: #F5F7FB; --card: #FFFFFF; --text: #0A2545; --muted: #4B5D75; --line: #E3E9F1; --soft: #F1F5FA;
  --accent: #1F5FBF; --accent-soft: #E6EFFD; --meter: #2F74D9; --focus: #2F74D9;
  --primary-bg: #0A2545; --primary-text: #FFFFFF;
  --green: #17794A; --green-bg: #E3F6EC; --yellow: #845500; --yellow-bg: #FDF3DC; --red: #B42318; --red-bg: #FDEBE9;
  --radius: 18px; --gap: 16px; --shadow: 0 1px 2px rgba(10, 37, 69, .04), 0 10px 30px rgba(10, 37, 69, .06);
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
.cert .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); }
.cert .block { padding: 20px 24px; border-top: 1px solid var(--line); }
.cert .block:first-child { border-top: 0; }
.cert h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -.01em; }
.cert .org-head { display: flex; align-items: center; gap: 12px; }
.cert .org-head h1 { margin: 0; }
.cert .org-logo { display: inline-grid; place-items: center; width: 40px; height: 40px; flex: none; border-radius: 10px;
  background: var(--soft); border: 1px solid var(--line); font-weight: 800; color: var(--muted); }
.cert .org-logo img { width: 28px; height: 28px; border-radius: 6px; }
.cert h2 { font-size: 15px; color: var(--text); margin: 0; font-weight: 700; letter-spacing: -.005em; }
.cert .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
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
.cert .meter span { width: 22px; height: 8px; border-radius: 999px; background: var(--line); }
.cert .meter span.on { background: linear-gradient(90deg, var(--loop-blue), var(--loop-green)); animation: cert-fill .35s ease-out both;
  animation-delay: calc(var(--i) * 90ms + 200ms); }
.cert details { border-top: 1px solid var(--line); }
.cert details:first-of-type { border-top: 0; }
.cert summary { cursor: pointer; list-style: none; padding: 10px 0; display: flex; gap: 8px; align-items: baseline; }
.cert summary > span:last-child { flex: 1 1 auto; min-width: 0; }
.cert .section > summary, .cert summary.wrap { flex-wrap: wrap; row-gap: 4px; }
.cert summary::-webkit-details-marker { display: none; }
.cert summary::before { content: "▸"; color: var(--muted); font-size: 12px; width: 10px; flex: none; }
.cert details[open] > summary::before { content: "▾"; }
.cert summary:focus-visible, .cert a:focus-visible, .cert button:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; border-radius: 4px; }
.cert .section > summary { padding: 0; align-items: center; }
.cert details.section > summary::before, .cert details.log-row > summary::before { content: none; }
.cert .section > summary::after { content: "\203A"; margin-left: auto; color: var(--muted); font-size: 20px; line-height: 1; transition: transform .2s; }
.cert .section[open] > summary::after { transform: rotate(90deg); }
.cert .ico { display: inline-grid; place-items: center; width: 30px; height: 30px; flex: none; border-radius: 9px; background: var(--accent-soft); color: var(--accent); }
.cert .ico svg { width: 18px; height: 18px; }
.cert .block-title { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
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
.cert svg.chart .pt-label { font-size: 12px; fill: var(--text); font-weight: 700; paint-order: stroke; stroke: var(--card); stroke-width: 3px; }
.cert svg.chart .pt-key { font-size: 13px; }
.cert svg.chart .pt-note { font-size: 10.5px; fill: var(--muted); font-weight: 600; }
.cert svg.chart .ir-label { fill: var(--green); }
.cert .legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 6px; }
.cert .lg { display: inline-block; width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; border-radius: 50%; }
.cert .lg.solid { background: var(--meter); }
.cert .lg.hollow { border: 2.5px solid var(--meter); background: var(--card); box-shadow: 14px 0 0 -2px rgba(89, 154, 245, .25); }
.cert .lg.key { background: var(--meter); box-shadow: 0 0 0 3px var(--loop-green); }
.cert svg.chart .pt-est { fill: var(--muted); }
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
/* Answer: count + stamp, bottom line, label/value facts */
.cert .answer { background: linear-gradient(180deg, var(--soft), var(--card) 60%); }
.cert .hero-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.cert .hero-num .count { font-size: 52px; }
.cert .facts { display: grid; margin: 14px 0 0; border-top: 1px solid var(--line); }
.cert .fact { display: grid; grid-template-columns: 132px 1fr; gap: 12px; padding: 7px 2px; border-bottom: 1px solid var(--line); font-size: 14px; align-items: baseline; }
.cert .fact dt { color: var(--muted); font-weight: 600; font-size: 13px; }
.cert .fact dd { margin: 0; overflow-wrap: anywhere; }
.cert .conf-val { display: inline-flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }
.cert .dir { font-weight: 600; }
.cert q.excerpt { font-style: italic; color: var(--text); }
.cert q.excerpt::before { content: "“"; } .cert q.excerpt::after { content: "”"; }
.cert .dir.lower { color: var(--yellow); }
.cert .dir.higher { color: var(--green); }
.cert .seal { position: relative; flex: none; width: 112px; height: 112px; border-radius: 50%; display: grid; place-content: center; text-align: center;
  border: 3px double currentColor; transform: rotate(-8deg); animation: cert-stamp .55s cubic-bezier(.2, 1.4, .4, 1) .35s both; }
.cert .seal::before { content: ""; position: absolute; inset: 7px; border-radius: 50%; border: 1px dashed currentColor; opacity: .5; }
.cert .seal.ready { color: var(--green); background: var(--green-bg); }
.cert .seal.usable { color: var(--yellow); background: var(--yellow-bg); }
.cert .seal.directional { color: var(--red); background: var(--red-bg); }
.cert .seal-word { font-weight: 800; font-size: 13px; letter-spacing: .08em; text-transform: uppercase; }
.cert .seal-score { font-weight: 800; font-size: 22px; line-height: 1.1; }
.cert .seal-brand { font-size: 7.5px; letter-spacing: .1em; text-transform: uppercase; opacity: .8; }
.cert .spark { position: absolute; left: 50%; top: 50%; width: 7px; height: 7px; margin: -3.5px; border-radius: 50%; opacity: 0;
  background: var(--loop-green); animation: cert-spark .9s ease-out .8s both; }
.cert .spark.s1, .cert .spark.s3, .cert .spark.s5, .cert .spark.s7 { background: var(--loop-blue); }
.cert .spark.s0 { --a: 0deg; } .cert .spark.s1 { --a: 45deg; } .cert .spark.s2 { --a: 90deg; } .cert .spark.s3 { --a: 135deg; }
.cert .spark.s4 { --a: 180deg; } .cert .spark.s5 { --a: 225deg; } .cert .spark.s6 { --a: 270deg; } .cert .spark.s7 { --a: 315deg; }
.cert .crm { display: inline-flex; gap: 6px; align-items: center; }
.cert .trust-item { border-radius: 14px; }
.cert .t-sym { font-size: 15px; color: var(--accent); line-height: 1; }
/* Findings: one line per item */
.cert .log-head { margin: 14px 0 6px; font-size: 13px; font-weight: 700; color: var(--muted); }
.cert .log { border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
.cert .log-row { border-top: 1px solid var(--line); }
.cert .log-row:first-child { border-top: 0; }
.cert .log-row > summary { display: grid; grid-template-columns: 22px 1fr auto; gap: 10px; align-items: baseline; padding: 8px 12px; }
.cert .log-row > summary:hover, .cert .log-row[open] > summary { background: var(--soft); }
.cert .sym { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; font-size: 11px; font-weight: 800; align-self: center; }
.cert .sym.green { color: var(--green); background: var(--green-bg); }
.cert .sym.yellow { color: var(--yellow); background: var(--yellow-bg); }
.cert .sym.red { color: var(--red); background: var(--red-bg); }
.cert .log-text { min-width: 0; font-size: 14px; }
.cert .log-text .f-title { font-weight: 600; }
.cert .log-text .so-what { color: var(--muted); }
.cert .log-row .impact { white-space: nowrap; align-self: center; }
.cert .log-body { padding: 4px 14px 10px 44px; font-size: 14px; }
.cert .log-body p { margin: 0 0 6px; }
.cert .bg-group { border: 0; }
.cert .bg-group > summary { padding: 6px 0 0; }
/* Gentle entrance, once */
.cert .card > .block, .cert .card > footer { animation: cert-rise .45s ease-out both; }
.cert .card > :nth-child(2) { animation-delay: .05s; }
.cert .card > :nth-child(3) { animation-delay: .12s; }
.cert .card > :nth-child(4) { animation-delay: .19s; }
.cert .card > :nth-child(5) { animation-delay: .26s; }
.cert .card > :nth-child(n+6) { animation-delay: .32s; }
@keyframes cert-rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes cert-fill { from { transform: scaleX(0); transform-origin: left; } to { transform: scaleX(1); transform-origin: left; } }
@keyframes cert-stamp { from { opacity: 0; transform: rotate(-24deg) scale(1.6); } to { opacity: 1; transform: rotate(-8deg) scale(1); } }
@keyframes cert-spark { 0% { opacity: 1; transform: rotate(var(--a)) translateY(0); } 100% { opacity: 0; transform: rotate(var(--a)) translateY(-78px); } }
@media (max-width: 560px) {
  .cert .fact { grid-template-columns: 92px 1fr; gap: 10px; }
  .cert .hero-num .count { font-size: 40px; }
  .cert .seal { width: 88px; height: 88px; }
  .cert .seal-score { font-size: 18px; }
  .cert .seal-brand { display: none; }
  .cert .log-row > summary { grid-template-columns: 22px 1fr; }
  .cert .log-row .impact { grid-column: 2; justify-self: start; }
  .cert .block { padding: 16px; }
}
@media (max-width: 760px) { .cert .trust-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) {
  .cert .count { font-size: 34px; }
  .cert .src-sum { grid-template-columns: 34px 56px 1fr 80px; }
  .cert .src-sum .date, .cert .src-head .date { display: none; }
}
/* Phones: denser, smaller type so less wraps */
@media (max-width: 560px) {
  .cert { --gap: 12px; font-size: 14px; }
  .cert .block { padding: 14px 14px; }
  .cert h1 { font-size: 19px; }
  .cert h2 { font-size: 14px; }
  .cert .ico { width: 26px; height: 26px; } .cert .ico svg { width: 16px; height: 16px; }
  .cert .hero-num .count { font-size: 36px; }
  .cert .seal { width: 74px; height: 74px; border-width: 2px; }
  .cert .seal-word { font-size: 10px; letter-spacing: .05em; } .cert .seal-score { font-size: 16px; }
  .cert .bottom-line { font-size: 13.5px; padding: 8px 10px; margin: 10px 0 6px; }
  .cert .fact { grid-template-columns: 84px 1fr; gap: 8px; font-size: 13px; padding: 6px 0; }
  .cert .fact dt { font-size: 12px; }
  .cert .trust-strip { gap: 6px; }
  .cert .trust-item { padding: 6px 8px; font-size: 13px; border-radius: 10px; }
  .cert .trust-item .t-label { font-size: 11px; }
  .cert .log-row > summary { padding: 7px 8px; gap: 8px; }
  .cert .log-text { font-size: 13px; }
  .cert .impact { font-size: 11px; }
  .cert .direction, .cert .indicated { font-size: 13px; padding: 6px 10px; }
  .cert .legend { font-size: 12px; }
  .cert .kv { font-size: 13px; }
  .cert .src-sum { grid-template-columns: 30px 50px 1fr 72px; gap: 6px; font-size: 13px; }
  .cert blockquote { padding: 6px 10px; font-size: 13.5px; }
  .cert button { font-size: 13px; padding: 6px 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .cert .flash, .cert .card > .block, .cert .card > footer, .cert .meter span.on, .cert .seal { animation: none; }
  .cert .spark { display: none; }
}
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
  // Line icons (24px grid, stroked with currentColor). Static strings only.
  var ICONS = {
    key: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 13l2 2 3-4"/>',
    findings: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1.2"/><circle cx="4.5" cy="12" r="1.2"/><circle cx="4.5" cy="18" r="1.2"/>',
    sources: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    adjust: '<path d="M5 4v16M12 4v16M19 4v16"/><circle cx="5" cy="9" r="2"/><circle cx="12" cy="15" r="2"/><circle cx="19" cy="7" r="2"/>',
    events: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    trend: '<path d="M3 20h18"/><path d="M4 16l5-6 4 3 7-8"/><path d="M16 5h4v4"/>',
    trust: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>'
  };
  function icon(name, cls) {
    var span = el("span", { cls: "ico" + (cls ? " " + cls : ""), "aria-hidden": "true" });
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || "") + "</svg>";
    return span;
  }
  function section(title, summaryExtra, bodyNodes, open, id, iconName) {
    var d = el("details", { cls: "section", id: id }, [el("summary", null, [iconName ? icon(iconName) : null, el("h2", { text: title }),
      summaryExtra ? el("span", { cls: "muted small", text: summaryExtra }) : null])]);
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

  function header(r, opts) {
    var e = r.entity, src = opts && opts.logo ? opts.logo(e.website) : null;
    var mark = null;
    if (src) {
      mark = el("span", { cls: "org-logo", "aria-hidden": "true", text: (e.name || "?").slice(0, 1).toUpperCase() });
      var img = el("img", { src: src, alt: "", width: "28", height: "28" });
      img.addEventListener("load", function () { if (img.naturalWidth > 1) { mark.textContent = ""; mark.appendChild(img); } });
    }
    return el("div", { cls: "block" }, [
      el("div", { cls: "org-head" }, [mark, el("h1", { text: e.name })]),
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

  var LEVEL_WORD = { 5: "Certified", 4: "Certified", 3: "Supported", 2: "Estimated", 1: "Unverified", 0: "Unattained" };
  function calm() { return document.documentElement.classList.contains("still") || window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  // The headline number ticks up once; the final value is always what's in the DOM text for copy and screen readers.
  function countUp(node, target) {
    node.textContent = num(target);
    if (calm() || !window.requestAnimationFrame || target < 10) return;
    var start = null, dur = 900;
    node.setAttribute("aria-label", num(target));
    function step(ts) {
      if (start === null) start = ts;
      var t = Math.min(1, (ts - start) / dur), eased = 1 - Math.pow(1 - t, 3);
      node.textContent = num(Math.round(target * eased));
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  function seal(c) {
    var b = band(c.score);
    var stamp = el("div", { cls: "seal " + b, "aria-hidden": "true" }, [
      el("span", { cls: "seal-word", text: LEVEL_WORD[c.score] || c.level }),
      el("span", { cls: "seal-score", text: c.score + "/5" }),
      el("span", { cls: "seal-brand", text: "GTM Data Certifier" })]);
    if (b === "ready") for (var i = 0; i < 8; i++) stamp.appendChild(el("i", { cls: "spark s" + i }));
    return stamp;
  }
  // A short excerpt for the header: the sentence around the figure, trimmed (the full passage is below).
  function shortQuote(text, count) {
    text = (text || "").replace(/\s+/g, " ").trim();
    if (text.length <= 170) return text;
    var i = count != null ? text.indexOf(num(count)) : -1;
    if (i < 0 && count != null) i = text.indexOf(String(count));
    if (i < 0) return text.slice(0, 160).replace(/\s\S*$/, "") + "…";
    var a = Math.max(0, i - 70), b = Math.min(text.length, i + 100);
    return (a > 0 ? "…" : "") + text.slice(a, b).replace(/^\S*\s/, a > 0 ? "" : "$&").replace(/\s\S*$/, b < text.length ? "" : "$&") + (b < text.length ? "…" : "");
  }
  function factRows(rows) {
    var dl = el("dl", { cls: "facts" });
    rows.forEach(function (row) {
      if (row[1] == null || row[1] === "") return;
      dl.appendChild(el("div", { cls: "fact" + (row[2] ? " " + row[2] : "") }, [el("dt", { text: row[0] }), el("dd", null, [row[1]])]));
    });
    return dl;
  }

  function answer(r) {
    var h = r.headline, c = r.confidence, k = r.__k, p = r.primary_source;
    var meter = el("span", { cls: "meter", role: "img", "aria-label": "Confidence " + c.score + " of 5" });
    for (var i = 1; i <= 5; i++) meter.appendChild(el("span", { cls: i <= c.score ? "on" : "", style: "--i:" + i }));
    var hero;
    if (h.count == null) {
      hero = el("div", { cls: "hero-num" }, [el("div", { cls: "count", text: "Not certified" })]);
    } else {
      var countEl = el("span", { cls: "count" });
      countUp(countEl, h.count);
      hero = el("div", { cls: "hero-num" }, [
        el("div", null, [QUAL[h.qualifier] ? el("span", { cls: "qual", text: QUAL[h.qualifier] }) : null, countEl]),
        el("div", { cls: "small muted", text: (h.count_basis === "fte" ? "full-time equivalents" : "employees") + " · " + asOfText(h) })]);
    }
    var b = band(c.score);
    var bottom = el("p", { cls: "bottom-line " + b }, [el("span", { cls: "bl-icon", "aria-hidden": "true", text: b === "ready" ? "✓" : b === "usable" ? "!" : "✕" }),
      el("span", null, [el("strong", { text: "Bottom line: " }), h.bottom_line || ""])]);

    var range = h.range && h.range[0] !== h.range[1] ? num(h.range[0]) + "–" + num(h.range[1]) : (h.count != null ? "Exact figure" : null);
    var conf = el("span", { cls: "conf-val" }, [meter, el("strong", { text: c.score + "/5" }), el("span", { cls: "muted", text: c.level })]);
    var countVal = h.count == null ? null : el("span", null, [(QUAL[h.qualifier] ? QUAL[h.qualifier] + " " : "") + num(h.count) + " ",
      h.count_type ? el("span", { cls: "badge accent", text: h.count_type }) : null,
      h.adjustment_status === "pre-adjustment" ? el("span", { cls: "badge warn", title: "A known change took effect after the as-of date; the figure isn't adjusted.", text: "! pre-adjustment" }) : null]);
    var ir = h.indicated_current_range;
    var dirShort = h.direction ? (DIRECTION[h.direction] || h.direction) : null;
    var facts = factRows([
      ["Employees", countVal],
      ["Range", range],
      ["As of", h.as_of_date ? h.as_of_date + (h.as_of_estimated ? (h.as_of_estimated_from === "url" ? " (estimated from URL)" : " (estimated)") : "") : "undated"],
      ["Confidence", conf],
      ["Key source", p && p.source_id ? sourceLabel(p) : (p && p.none_reason)],
      ["Source link", p && p.source_id ? el("span", null, [link(p.url, host(p.url)),
        p.location.deep_link ? " · " : null, p.location.deep_link ? link(p.location.deep_link, "open at the quote ↗") : null]) : null],
      ["Line in source", p && p.source_id ? (p.location.section ? p.location.section + " · " : "") + p.location.page_label : null],
      ["Excerpt", p && p.source_id && p.excerpt ? el("q", { cls: "excerpt", text: shortQuote(p.excerpt, h.count) }) : null],
      ["Direction", dirShort ? el("span", { cls: "dir " + h.direction, text: dirShort }) : null],
      ["Known change", h.known_changes && h.known_changes.length ? h.known_changes.join("; ") : null, "wide"],
      ["Newer data", ir ? (ir.low === ir.high ? "about " + num(ir.low) : num(ir.low) + "–" + num(ir.high)) + " (" + ir.earliest.slice(0, 7) + (ir.latest !== ir.earliest ? " to " + ir.latest.slice(0, 7) : "") + ") · context only, not certified" : null],
      ["Next update", h.next_update_note]
    ]);

    var table = el("table", { cls: "lines" });
    c.breakdown.forEach(function (line) {
      table.appendChild(el("tr", null, [el("td", { cls: "pts", text: (line.points > 0 && line !== c.breakdown[0] ? "+" : "") + line.points }),
        el("td", null, [line.rationale + " ", chip(line.finding_id, k + "-")])]));
    });
    table.appendChild(el("tr", { cls: "total" }, [el("td", { cls: "pts", text: String(c.score) }), el("td", { text: "= " + c.arithmetic })]));
    var crm = el("button", { type: "button", cls: "crm" }, ["⧉ Copy for CRM"]);
    crm.addEventListener("click", function () { copyText(crmText(r), crm, "⧉ Copy for CRM"); });
    return el("div", { cls: "block answer " + b }, [
      el("div", { cls: "hero-row" }, [hero, seal(c)]),
      bottom, facts,
      el("div", { cls: "row answer-actions" }, [crm,
        el("details", { cls: "breakdown" }, [el("summary", null, [el("span", { text: "How the score adds up" })]), table])])]);
  }

  // "Why you can trust this": five facts, each opening its detail.
  function trust(r) {
    var k = r.__k, p = r.primary_source, h = r.headline;
    var corr = r.sources.items.filter(function (s) { return s.role === "corroborates"; });
    var corrFinding = r.findings.items.filter(function (f) { return f.category === "corroboration"; })[0];
    var adj = r.adjustments.items.filter(function (a) { return a.change; }).length;
    var attention = r.findings.items.filter(function (f) { return f.status === "red"; }).length;
    function item(label, value, target, tone, sym) {
      var b = el("button", { type: "button", cls: "trust-item" + (tone ? " " + tone : "") }, [el("span", { cls: "t-sym", "aria-hidden": "true", text: sym }),
        el("span", { cls: "t-label", text: label }), el("strong", { text: value })]);
      b.addEventListener("click", function () { jump(target); });
      return b;
    }
    return el("div", { cls: "block trust", role: "group", "aria-label": "Why you can trust this" }, [
      el("div", { cls: "block-title" }, [icon("trust"), el("h2", { text: "Why you can trust this" })]),
      el("div", { cls: "trust-strip" }, [
        item("Key source", p && p.source_id ? "Tier " + p.tier + " · " + (p.source_type || p.tier_name) : "none", k + "-key", "", "◆"),
        item("As of", h.as_of_date ? h.as_of_date + (h.as_of_estimated ? " (est.)" : "") : "undated", k + "-key", "", "◷"),
        item("Independent confirmations", String(corr.length), corrFinding ? k + "-" + corrFinding.id : k + "-sources", corr.length ? "good" : "", "⇄"),
        item("Adjustments to the count", String(adj), k + "-adjustments", "", "±"),
        item("Needs attention", String(attention), k + "-findings", attention ? "bad" : "good", attention ? "⚑" : "✓")])]);
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
    var gid = "area-" + (r.__k || "r0");
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
    var pts = reported.map(function (p) { return [X(t(p.as_of_date)), Y(p.value)]; });
    if (!svgEl.querySelector("defs")) {
      var defs = document.createElementNS(ns, "defs");
      defs.innerHTML = '<linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--loop-blue)" stop-opacity=".28"/>' +
        '<stop offset="1" stop-color="var(--loop-blue)" stop-opacity="0"/></linearGradient>';
      svgEl.insertBefore(defs, svgEl.firstChild);
    }
    if (pts.length > 1) {  // soft area under a smooth (monotone) line through the reported points
      var line = smooth(pts);
      add("path", { d: line + " L " + pts[pts.length - 1][0] + " " + (H - B) + " L " + pts[0][0] + " " + (H - B) + " Z", fill: "url(#" + gid + ")", stroke: "none" });
      add("path", { d: line, fill: "none", stroke: "var(--meter)", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" });
    }
    items.filter(function (p) { return p.estimated && p.low != null; }).forEach(function (f) {
      if (!last) return;
      var lx = X(t(last.as_of_date)), ly = Y(last.value), fx = X(t(f.as_of_date)), mid = (lx + fx) / 2;
      add("path", { d: "M " + lx + " " + ly + " Q " + mid + " " + ly + " " + fx + " " + Y(f.high) + " L " + fx + " " + Y(f.low) + " Q " + mid + " " + ly + " " + lx + " " + ly + " Z",
        fill: "var(--loop-blue)", "fill-opacity": .16 });
      add("path", { d: "M " + lx + " " + ly + " Q " + mid + " " + (ly + Y(f.value)) / 2 + " " + fx + " " + Y(f.value), fill: "none", stroke: "var(--meter)",
        "stroke-width": 2.5, "stroke-dasharray": "6 5", "stroke-linecap": "round" });
    });
    items.forEach(function (p, i) {
      var cx = X(t(p.as_of_date)), cy = Y(p.value), isLast = p === last;
      if (isLast) add("circle", { cx: cx, cy: cy, r: 11, fill: "var(--loop-green)", "fill-opacity": .22 });
      add("circle", { cx: cx, cy: cy, r: isLast ? 6.5 : 5, fill: p.estimated ? "var(--card)" : "var(--meter)", stroke: isLast ? "var(--loop-green)" : "var(--meter)", "stroke-width": isLast ? 3 : 2.5 });
      // Values only on the chart; the certified point and the forecast range are named in the legend. The
      // forecast label sits below its point so it never collides with the certified label above.
      var below = !!p.estimated;
      add("text", { x: cx, y: below ? cy + 20 : cy - (isLast ? 16 : 11),
        "text-anchor": i === 0 && items.length > 1 ? "start" : (i === items.length - 1 ? "end" : "middle"),
        "class": "pt-label" + (isLast ? " pt-key" : "") + (p.estimated ? " pt-est" : "") }, num(p.value));
    });
    return svgEl;
  }

  // Monotone cubic (Fritsch-Carlson) through points sorted by x: smooth, with no overshoot between points.
  function smooth(pts) {
    var n = pts.length, d = [], m = [];
    for (var i = 0; i < n - 1; i++) d.push((pts[i + 1][1] - pts[i][1]) / ((pts[i + 1][0] - pts[i][0]) || 1));
    m[0] = d[0]; m[n - 1] = d[n - 2];
    for (i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
    for (i = 0; i < n - 1; i++) {
      if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
      var a = m[i] / d[i], b = m[i + 1] / d[i], h = a * a + b * b;
      if (h > 9) { var tau = 3 / Math.sqrt(h); m[i] = tau * a * d[i]; m[i + 1] = tau * b * d[i]; }
    }
    var path = "M " + pts[0][0] + " " + pts[0][1];
    for (i = 0; i < n - 1; i++) {
      var dx = (pts[i + 1][0] - pts[i][0]) / 3;
      path += " C " + (pts[i][0] + dx) + " " + (pts[i][1] + m[i] * dx) + " " + (pts[i + 1][0] - dx) + " " + (pts[i + 1][1] - m[i + 1] * dx) +
        " " + pts[i + 1][0] + " " + pts[i + 1][1];
    }
    return path;
  }

  function trendBlock(r) {
    var h = r.headline, items = r.trend.items, nodes = [el("div", { cls: "block-title" }, [icon("trend"), el("h2", { text: "Trend and forecast" })])];
    if (h.direction) nodes.push(el("p", { cls: "direction " + h.direction }, [el("strong", { text: DIRECTION[h.direction] || h.direction }), " · " + (h.direction_reason || "")]));
    var svgEl = chart(r);
    if (svgEl) {
      nodes.push(el("div", { cls: "chart-wrap" }, [svgEl]));
      var fc = items.filter(function (p) { return p.estimated; })[0];
      nodes.push(el("div", { cls: "legend small muted" }, [el("span", null, [el("i", { cls: "lg solid" }), "Reported"]),
        el("span", null, [el("i", { cls: "lg key" }), "Certified figure"]),
        fc ? el("span", null, [el("i", { cls: "lg hollow" }), "Forecast " + fc.as_of_date.slice(0, 4) + ": " + num(fc.value) +
          (fc.low != null ? " (range " + num(fc.low) + "–" + num(fc.high) + ")" : "")]) : null,
        h.indicated_current_range ? el("span", null, [el("i", { cls: "lg box" }), "Indicated current range (context only)"]) : null]));
    } else {
      nodes.push(none(r.trend.none_reason));
    }
    return el("div", { cls: "block trend-block", id: r.__k + "-trend" }, nodes);
  }

  function primary(r) {
    var p = r.primary_source, k = r.__k;
    if (!p.source_id) return section("Key Source", "none", [none(p.none_reason)], true, k + "-key", "key");
    var loc = p.location;
    return section("Key Source", sourceLabel(p) + " · " + (loc.section ? loc.section + " · " : "") + loc.page_label, [
      labelRow(p), whatIsThis(p),
      el("p", { cls: "small muted", style: "margin:8px 0 0", text: "Detailed excerpt (the exact quote is highlighted):" }),
      passage(loc, p.excerpt),
      p.excerpt_missing_reason ? el("p", { cls: "small muted", text: p.excerpt_missing_reason }) : null,
      kv(locationPairs(p.url, loc).concat([["Accession", p.accession], ["As of", p.as_of_date], ["Published", p.published_date],
          ["Modified", p.modified_date], ["Why this tier", p.tier_rationale]]))
    ].filter(Boolean), false, k + "-key", "key");
  }

  var GROUPS = [["affects", "Affects the answer", "◆"], ["worth_knowing", "Worth knowing", "●"], ["background", "Background", "○"]];
  // Short chip text for the log; the full wording stays in the tooltip.
  function shortImpact(text) {
    var m;
    if ((m = /^Lowered confidence by (\d+)/.exec(text))) return "−" + m[1] + " confidence";
    if ((m = /^Raised confidence by (\d+)/.exec(text))) return "+" + m[1] + " confidence";
    if ((m = /^Sets starting confidence: (\d) of 5/.exec(text))) return "base " + m[1] + "/5";
    if ((m = /^Adjusted count (.+)/.exec(text))) return "count " + m[1];
    if (/^No further effect/.test(text)) return "no effect (at floor)";
    if (/^No effect/.test(text)) return "no effect";
    if (/^Chose/.test(text)) return "chose detail";
    return text;
  }
  function findingNode(f, k) {
    var group = f.group || (f.score_impact ? "affects" : "worth_knowing");
    var impact = f.impact || (f.score_impact ? (f.score_impact > 0 ? "Raised" : "Lowered") + " confidence by " + Math.abs(f.score_impact) : "No effect on the answer");
    var tone = /^Lowered/.test(impact) ? "down" : /^Raised|^Chose/.test(impact) ? "up" : /^Adjusted|^Sets/.test(impact) ? "set" : "none";
    var sym = STATUS[f.status] || ["?", f.status];
    var ev = el("div", { cls: "row small" }, [el("span", { cls: "muted", text: "Evidence:" })]);
    if (f.evidence.length) f.evidence.forEach(function (id) { ev.appendChild(chip(id, k + "-")); }); else ev.appendChild(el("span", { cls: "muted", text: "none cited" }));
    return el("details", { id: k + "-" + f.id, cls: "log-row " + f.status + " " + group }, [
      el("summary", null, [
        el("span", { cls: "sym " + f.status, title: sym[1] }, [el("span", { "aria-hidden": "true", text: sym[0] }), el("span", { cls: "sr-only", text: sym[1] + ":" })]),
        el("span", { cls: "log-text" }, [el("span", { cls: "f-title", text: f.title }),
          f.so_what ? el("span", { cls: "so-what", text: " — " + f.so_what }) : null]),
        el("span", { cls: "impact " + tone, title: impact, text: shortImpact(impact) })]),
      el("div", { cls: "log-body" }, [el("p", { text: f.rationale }), ev,
        el("p", { cls: "muted small", text: f.id + " · " + f.category.replace("_", " ") + " · " + impact })])
    ]);
  }
  function findings(r) {
    var items = r.findings.items, k = r.__k;
    if (!items.length) return section("Findings", "none", [none(r.findings.none_reason)], true, k + "-findings", "findings");
    var nodes = [], counts = [];
    GROUPS.forEach(function (g) {
      var list = items.filter(function (f) { return (f.group || (f.score_impact ? "affects" : "worth_knowing")) === g[0]; });
      if (!list.length) return;
      counts.push(list.length + " " + g[1].toLowerCase());
      var log = el("div", { cls: "log" }, list.map(function (f) { return findingNode(f, k); }));
      if (g[0] === "background") {
        nodes.push(el("details", { cls: "bg-group" }, [el("summary", null, [el("span", { cls: "log-head", text: g[2] + " " + g[1] + " · " + list.length }),
          el("span", { cls: "muted small", text: "technical detail" })]), log]));
      } else {
        nodes.push(el("p", { cls: "log-head", text: g[2] + " " + g[1] + " · " + list.length }), log);
      }
    });
    return section("Findings", counts.join(" · "), nodes, true, k + "-findings", "findings");
  }

  function sources(r) {
    var items = r.sources.items, k = r.__k;
    if (!items.length) return section("Sources", "none", [none(r.sources.none_reason)], false, k + "-sources", "sources");
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
    return section("Sources", items.length + " found, " + used + " used", nodes, false, k + "-sources", "sources");
  }

  function adjustments(r) {
    var items = r.adjustments.items, k = r.__k;
    if (!items.length) return section("Adjustments", "none", [none(r.adjustments.none_reason)], false, k + "-adjustments", "adjust");
    return section("Adjustments", items.length + " logged", items.map(function (a) {
      var change = a.change ? (a.change > 0 ? "+" : "") + num(a.change) : "note";
      return el("details", null, [el("summary", null, [el("span", { cls: "badge", text: change }),
        el("span", { text: a.source_figure != null ? num(a.source_figure) + " → " + num(a.result) : num(a.result) })]),
        el("div", { cls: "body" }, [el("p", { style: "margin:0", text: a.rationale })])]);
    }), false, k + "-adjustments", "adjust");
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
    return section("Events and LinkedIn", (items.length ? items.length + " event(s)" : "no events") + " · LinkedIn " + li.status.replace("_", " "), nodes,
      false, null, "events");
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
        header(r, opts), answer(r), trendBlock(r), trust(r), findings(r), primary(r), sources(r), adjustments(r), events(r),
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
