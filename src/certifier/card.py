# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
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

from .notice import OWNER_LINE, ROBOTS_META
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
.cert .section > summary { cursor: pointer; border-radius: 10px; margin: -6px -8px; padding: 6px 8px; transition: background .15s; }
.cert .section > summary:hover { background: var(--soft); }
.cert .section > summary::after { content: "View details \25BE"; margin-left: auto; flex: none; font-size: 12px; font-weight: 700; color: var(--accent);
  padding: 3px 10px; border-radius: 999px; border: 1px solid var(--line); background: var(--card); white-space: nowrap; }
.cert .section > summary:hover::after { border-color: var(--loop-blue); }
.cert .section[open] > summary::after { content: "Hide \25B4"; color: var(--muted); }
.cert .section[open] > summary { margin-bottom: 2px; }
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
.cert .trust-strip.journey { grid-template-columns: repeat(5, minmax(0, 1fr)) minmax(0, .9fr); gap: 14px; }
.cert .journey .trust-item { position: relative; display: grid; align-content: start; gap: 3px; padding: 9px 10px 10px; border-width: 1px;
  border-top-width: 4px; cursor: pointer; }
.cert .journey .trust-item:not(:first-child)::before { content: "\203A"; position: absolute; left: -12px; top: 50%; transform: translateY(-50%);
  color: var(--muted); font-size: 16px; font-weight: 700; }
.cert .journey .t-top { display: flex; gap: 6px; align-items: center; }
.cert .journey .t-sym { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 800;
  color: #fff; flex: none; }
.cert .journey strong { font-size: 14px; line-height: 1.3; overflow-wrap: anywhere; }
.cert .journey .t-effect { font-size: 12px; font-weight: 600; }
.cert .t-run { position: relative; display: block; height: 6px; margin-top: 4px; border-radius: 999px; background: var(--line); }
.cert .t-run i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; background: linear-gradient(90deg, var(--loop-green), var(--loop-blue)); }
.cert .t-run b { position: absolute; right: 0; top: 8px; font-size: 10.5px; color: var(--muted); }
.cert .journey .trust-item { padding-bottom: 20px; }
.cert .journey .strong { border-top-color: var(--loop-green); background: var(--green-bg); }
.cert .journey .strong .t-sym { background: var(--green); }
.cert .journey .strong .t-effect { color: var(--green); }
.cert .journey .neutral { border-top-color: var(--loop-blue); }
.cert .journey .neutral .t-sym { background: var(--loop-blue); }
.cert .journey .neutral .t-effect { color: var(--muted); }
.cert .journey .weak { border-top-color: #F2C35B; background: var(--yellow-bg); }
.cert .journey .weak .t-sym { background: #D99A1E; }
.cert .journey .weak .t-effect { color: var(--yellow); }
.cert .journey .harmful { border-top-color: var(--red); background: var(--red-bg); }
.cert .journey .harmful .t-sym { background: var(--red); }
.cert .journey .harmful .t-effect { color: var(--red); }
.cert .trust-land { display: grid; align-content: center; justify-items: center; gap: 2px; text-align: center; border-radius: 14px; padding: 10px;
  border: 2px solid var(--line); position: relative; }
.cert .trust-land::before { content: "="; position: absolute; left: -12px; top: 50%; transform: translateY(-50%); color: var(--muted); font-weight: 800; }
.cert .trust-land strong { font-size: 26px; line-height: 1.1; }
.cert .trust-land .t-label { font-size: 11px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.cert .trust-land .t-effect { font-size: 12px; font-weight: 600; }
.cert .trust-land.ready { border-color: var(--loop-green); background: var(--green-bg); color: var(--green); }
.cert .trust-land.usable { border-color: #F2C35B; background: var(--yellow-bg); color: var(--yellow); }
.cert .trust-land.directional { border-color: var(--red); background: var(--red-bg); color: var(--red); }
.cert .drill-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 12px 24px 4px; border-top: 1px solid var(--line); }
.cert .drill-lbl { font-size: 11px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin-right: 4px; }
.cert .drill-btn { font: inherit; font-size: 12.5px; font-weight: 600; padding: 4px 11px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--card); color: var(--accent); cursor: pointer; }
.cert .drill-btn:hover { border-color: var(--loop-blue); background: var(--soft); }
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
.cert .lg.hollow { border: 2.5px solid var(--meter); background: var(--card); box-shadow: 14px 0 0 -2px rgba(89, 154, 245, .25); margin-right: 20px; }
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
.cert .fact dt { color: var(--muted); font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
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
.cert .dl-menu { position: relative; border: 0; }
/* Each section animates in and so forms its own stacking layer; lift the blocks that hold a menu above the next one. */
.cert .card > .answer, .cert .card > footer { position: relative; z-index: 3; }
.cert .dl-menu > summary.dl-button { display: inline-flex; gap: 8px; align-items: center; padding: 7px 14px; border-radius: 10px;
  background: var(--primary-bg); color: var(--primary-text); font-weight: 700; font-size: 14px; cursor: pointer; }
.cert details.dl-menu > summary::before, .cert details.dl-menu[open] > summary::before { content: none; }
.cert .dl-menu[open] .dl-caret { transform: rotate(180deg); }
.cert .dl-items { position: absolute; z-index: 20; top: calc(100% + 6px); left: 0; min-width: 270px; display: grid; gap: 2px; padding: 6px;
  background: var(--card); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 12px 32px rgba(10, 37, 69, .18); }
.cert .dl-items button { display: grid; gap: 1px; text-align: left; background: transparent; color: var(--text); border: 0;
  padding: 7px 10px; border-radius: 8px; font-size: 14px; font-weight: 600; }
.cert .dl-items button:hover, .cert .dl-items button:focus-visible { background: var(--soft); }
.cert .dl-hint { font-size: 12px; font-weight: 500; color: var(--muted); }
.cert .dl-label { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.cert .dl-more { color: var(--muted); font-size: 16px; line-height: 1; }
.cert .dl-items button.dl-disabled { opacity: .45; cursor: not-allowed; }
.cert .dl-items button.dl-disabled:hover { background: transparent; }
.cert .dl-items.step2 { min-width: 300px; gap: 8px; padding: 10px; }
.cert .dl-choices { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.cert .dl-items .dl-choice { display: grid; justify-items: center; gap: 4px; padding: 8px; border: 2px solid var(--line); border-radius: 10px;
  text-align: center; }
.cert .dl-items .dl-choice.on { border-color: var(--loop-green); background: var(--soft); box-shadow: 0 0 0 3px rgba(63, 207, 142, .18); }
.cert .dl-choice-label { font-weight: 700; font-size: 14px; }
.cert .dl-step-actions { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.cert .dl-items .dl-back { color: var(--accent); font-weight: 600; font-size: 13px; padding: 6px 8px; }
.cert .dl-items .dl-go { display: inline-block; background: var(--primary-bg); color: var(--primary-text); font-weight: 700; padding: 7px 16px; }
.cert .dl-items .dl-go:hover { background: var(--primary-bg); filter: brightness(1.08); }
.cert .dl-thumb { position: relative; display: block; width: 116px; height: 66px; border-radius: 6px; overflow: hidden; border: 1px solid var(--line); }
.cert .dl-thumb.light { background: #F5F7FB; }
.cert .dl-thumb.dark { background: #06182F; }
.cert .dl-thumb i { position: absolute; display: block; border-radius: 2px; }
.cert .dl-thumb .t-head { left: 7px; top: 6px; width: 30px; height: 6px; background: #3FCF8E; }
.cert .dl-thumb .t-rule { left: 7px; right: 7px; top: 15px; height: 2px; background: linear-gradient(90deg, #3FCF8E 37%, #599AF5 37%); }
.cert .dl-thumb .t-num { left: 7px; top: 23px; width: 40px; height: 11px; }
.cert .dl-thumb.light .t-num { background: #0A2545; }
.cert .dl-thumb.dark .t-num { background: #EAF2FF; }
.cert .dl-thumb .t-seal { left: 52px; top: 21px; width: 15px; height: 15px; border-radius: 50%; background: conic-gradient(#3FCF8E, #599AF5, #3FCF8E); }
.cert .dl-thumb .t-line { left: 7px; top: 41px; width: 58px; height: 4px; }
.cert .dl-thumb .t-line.short { top: 49px; width: 40px; }
.cert .dl-thumb.light .t-line { background: #C9D3E0; }
.cert .dl-thumb.dark .t-line { background: #2A4468; }
.cert .dl-thumb .t-panel { right: 7px; top: 21px; width: 36px; height: 36px; border-radius: 4px; }
.cert .dl-thumb.light .t-panel { background: #FFFFFF; border: 1px solid #DCE3EC; }
.cert .dl-thumb.dark .t-panel { background: #0D2440; border: 1px solid #1E3A5C; }
.cert .dl-group { margin: 6px 10px 2px; font-size: 11px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.cert .footer-actions { margin-top: 12px; }
.cert .our-take { margin: -4px 0 12px; padding: 9px 14px; border-left: 3px solid var(--loop-blue); border-radius: 0 10px 10px 0;
  background: var(--soft); font-size: 14px; line-height: 1.5; }
.cert .our-take p { margin: 0; }
.cert .take-label { font-size: 11px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--accent); margin-right: 4px; }
.cert .take-crm { font-weight: 600; }
.cert .take-crm:empty { display: none; }
.cert .take-look { margin-top: 4px !important; font-size: 12.5px; color: var(--muted); }
.cert .take-src { font: inherit; font-size: 12px; font-weight: 700; padding: 0 7px; margin-left: 4px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--card); color: var(--accent); cursor: pointer; }
.cert .peer-note { position: relative; display: flex; gap: 8px; align-items: flex-start; margin: -4px 0 12px; padding: 8px 12px;
  border-radius: 10px; font-size: 13.5px; overflow: hidden; }
.cert .peer-note.strong { background: var(--soft); color: var(--text); }
.cert .peer-note.strong .peer-ico { color: var(--accent); }
.cert .peer-note.rare { background: linear-gradient(90deg, rgba(63, 207, 142, .18), rgba(89, 154, 245, .18)); color: var(--text);
  border: 1px solid var(--loop-green); }
.cert .peer-note.rare .peer-ico { color: #D99A1E; font-size: 16px; animation: cert-twinkle 1.8s ease-in-out infinite; }
.cert .confetti i { position: absolute; top: -6px; width: 6px; height: 9px; border-radius: 1px; opacity: 0;
  animation: cert-confetti 1.6s ease-out .3s 2 forwards; }
.cert .confetti i:nth-child(1) { left: 8%; background: #3FCF8E; }
.cert .confetti i:nth-child(2) { left: 24%; background: #599AF5; animation-delay: .45s; }
.cert .confetti i:nth-child(3) { left: 41%; background: #F2C35B; animation-delay: .35s; }
.cert .confetti i:nth-child(4) { left: 59%; background: #3FCF8E; animation-delay: .55s; }
.cert .confetti i:nth-child(5) { left: 76%; background: #599AF5; animation-delay: .4s; }
.cert .confetti i:nth-child(6) { left: 92%; background: #F2C35B; animation-delay: .5s; }
@keyframes cert-confetti { 0% { opacity: 0; transform: translateY(0) rotate(0); } 15% { opacity: 1; }
  100% { opacity: 0; transform: translateY(46px) rotate(220deg); } }
@keyframes cert-twinkle { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .55; transform: scale(.85); } }
.cert .owner-notice { margin: 12px 0 0; font-size: 11px; line-height: 1.45; color: var(--muted); }
.cert .footer-actions .dl-items { top: auto; bottom: calc(100% + 6px); }
.cert .crm-inline { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 3px 4px 3px 10px;
  border: 1px solid var(--line); border-radius: 12px; background: var(--soft); }
.cert .crm-lbl { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 800; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); }
.cert .crm-lbl svg { width: 15px; height: 15px; }
.cert .crm-inline input { width: 118px; font: inherit; font-size: 14px; padding: 5px 9px; border-radius: 8px; border: 1px solid var(--line);
  background: var(--card); color: var(--text); }
.cert .crm-inline .crm-go { padding: 6px 14px; font-size: 13.5px; font-weight: 700; border-radius: 8px; border: 0; cursor: pointer;
  background: var(--accent); color: var(--card); box-shadow: 0 1px 2px rgba(10, 37, 69, .25); }
.cert .crm-inline .crm-go:hover { filter: brightness(1.1); }
.cert .crm-inline .crm-go:focus-visible { outline: 2px solid var(--loop-green); outline-offset: 2px; }
.cert .trust .breakdown { margin-top: 12px; border-top: 1px solid var(--line); padding-top: 8px; }
.cert .trust .breakdown > summary { color: var(--accent); font-size: 14px; font-weight: 600; cursor: pointer; }
.cert .crm-out:empty { display: none; }
.cert .crm-out { margin-top: 8px; }
.cert .crm-verdict { margin: 0; padding: 8px 12px; border-radius: 10px; font-size: 13.5px; }
.cert .crm-verdict.keep { background: var(--green-bg); color: var(--green); }
.cert .crm-verdict.strong { background: var(--red-bg); color: var(--red); }
.cert .crm-verdict.moderate { background: var(--yellow-bg); color: var(--yellow); }
.cert .crm-verdict.light { background: var(--soft); color: var(--text); }
.cert .crm-copy { font-weight: 700; text-decoration: underline; color: inherit; padding: 0; font-size: inherit; background: none; border: 0; }
.cert .crm-see { opacity: .8; }
.cert .legend .lg.hist { border: 2px dashed var(--muted); background: var(--card); }
.cert .chart .pt-faint { opacity: .55; font-weight: 600; font-size: 11.5px; }
.cert .chart .pt-cert { font-size: 10.5px; font-weight: 800; letter-spacing: .08em; fill: var(--green); }
.cert .chart .gap-label { font-size: 11px; fill: var(--muted); font-style: italic; }
.cert .chart .ov-label { font-size: 11.5px; font-weight: 700; }
.cert .legend .lg.gap { width: auto; height: auto; border: 0; background: none; color: var(--muted); font-style: normal; font-weight: 700; font-size: 11px; }
.cert .legend .lg.range { background: rgba(63, 207, 142, .14); border: 1px dashed var(--loop-green); border-radius: 2px; }
.cert .legend .lg.range.strong { background: rgba(63, 207, 142, .38); border-style: solid; }
.cert .legend .lg.crm { height: 0; border-radius: 0; border: 0; border-top: 2px dashed #E8833A; background: none; }
.cert .legend .lg.target { background: none; border: 2px solid #E8833A; border-radius: 50%; }
.cert .hint { display: inline-flex; align-items: center; gap: 6px; margin-left: 8px; padding: 2px 10px 2px 8px; border-radius: 999px;
  font-size: 12px; font-weight: 700; color: var(--accent); background: var(--accent-soft); white-space: nowrap; }
.cert .hint i { width: 8px; height: 8px; border-radius: 50%; background: var(--loop-green); animation: cert-ping 1.6s ease-out infinite; }
.cert .src-sum .hint { grid-column: 3 / -1; justify-self: start; margin: 2px 0 0; }
.cert summary > .hint:last-child { flex: none; }
@keyframes cert-ping { 0% { box-shadow: 0 0 0 0 rgba(63, 207, 142, .6); } 100% { box-shadow: 0 0 0 9px rgba(63, 207, 142, 0); } }
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
.cert .log-text { min-width: 0; font-size: 14px; text-wrap: balance; }  /* one line, or two even lines */
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
  .cert .drill-bar { padding: 10px 16px 2px; }
}
@media (max-width: 760px) { .cert .trust-strip, .cert .trust-strip.journey { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .cert .journey .trust-item:not(:first-child)::before, .cert .trust-land::before { content: none; }
  .cert .section > summary::after { content: "Open \25BE"; }
  .cert .section[open] > summary::after { content: "Hide \25B4"; } }
@media (max-width: 560px) {
  .cert .count { font-size: 34px; }
  .cert .src-sum { grid-template-columns: 34px 56px 1fr 80px; }
  .cert .src-sum .date, .cert .src-head .date { display: none; }
}
/* Phones: denser, smaller type so less wraps */
@media (max-width: 560px) {
  .cert { --gap: 12px; font-size: 14px; }
  .cert .block { padding: 14px 14px; }
  .cert .drill-bar { padding: 10px 14px 2px; }
  .cert .trust .block-title .muted { display: none; }
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
  .cert .flash, .cert .card > .block, .cert .card > footer, .cert .meter span.on, .cert .seal, .cert .hint i,
  .cert .peer-note .peer-ico, .cert .confetti i { animation: none; }
  .cert .spark { display: none; }
}
"""

CARD_JS = r"""
(function () {
  "use strict";
  var OWNER_LINE = __OWNER_LINE__;
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
    score: '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/>',
    method: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    key: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 13l2 2 3-4"/>',
    findings: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1.2"/><circle cx="4.5" cy="12" r="1.2"/><circle cx="4.5" cy="18" r="1.2"/>',
    sources: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    adjust: '<path d="M5 4v16M12 4v16M19 4v16"/><circle cx="5" cy="9" r="2"/><circle cx="12" cy="15" r="2"/><circle cx="19" cy="7" r="2"/>',
    events: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    trend: '<path d="M3 20h18"/><path d="M4 16l5-6 4 3 7-8"/><path d="M16 5h4v4"/>',
    trust: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    compare: '<path d="M4 8h14l-3.5-3.5"/><path d="M20 16H6l3.5 3.5"/>'
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

  // ---------- Download menu: Copy for CRM, JSON, CSVs, PowerPoint (light/dark), Word ----------
  function pageTheme() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t === "light" || t === "dark") return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function exportUrl(r, opts, format, theme) {
    var links = r.__links;
    if (links) return links[format === "pptx" ? "pptx_" + theme : format] || null;
    return opts && opts.exportUrl ? opts.exportUrl(format, theme) : null;
  }
  function openUrl(url) {
    if (window.GTMCard.openLink) { window.GTMCard.openLink(url); return; }
    var a = el("a", { href: url, download: "", target: "_blank", rel: "noopener" });
    document.body.appendChild(a); a.click(); a.remove();
  }
  // A short list; PowerPoint and CSV open a second step to pick the theme (with previews) or the file.
  function slidePreview(theme) {
    return el("span", { cls: "dl-thumb " + theme, "aria-hidden": "true" }, [
      el("i", { cls: "t-head" }), el("i", { cls: "t-rule" }), el("i", { cls: "t-num" }), el("i", { cls: "t-seal" }),
      el("i", { cls: "t-line" }), el("i", { cls: "t-line short" }), el("i", { cls: "t-panel" })]);
  }
  function downloadMenu(r, opts) {
    var menu = el("details", { cls: "dl-menu" });
    menu.appendChild(el("summary", { cls: "dl-button", "aria-label": "Download or copy this certification" },
      [el("span", { cls: "dl-ico", "aria-hidden": "true", text: "⤓" }), el("span", { text: "Download" }),
        el("span", { cls: "dl-caret", "aria-hidden": "true", text: "▾" })]));
    var list = el("div", { cls: "dl-items", role: "menu" });
    var has = exportUrl(r, opts, "json") != null;
    function close() { menu.open = false; }
    function item(text, hint, fn, more) {
      var b = el("button", { type: "button", role: "menuitem" }, [el("span", { cls: "dl-label" }, [text, more ? el("span", { cls: "dl-more", "aria-hidden": "true", text: "›" }) : null]),
        hint ? el("span", { cls: "dl-hint", text: hint }) : null]);
      if (fn) b.addEventListener("click", function (e) { e.stopPropagation(); fn(b); });
      return b;
    }
    // Step 2: a small chooser in place of the list, with Back and Download.
    function chooser(title, options, preselect, onGo) {
      var picked = preselect, tiles = [];
      var go = el("button", { type: "button", cls: "dl-go", text: "Download" });
      var back = el("button", { type: "button", cls: "dl-back", text: "‹ Back" });
      var grid = el("div", { cls: "dl-choices", role: "radiogroup", "aria-label": title });
      options.forEach(function (o) {
        var tile = el("button", { type: "button", role: "radio", cls: "dl-choice" }, [o.preview || null,
          el("span", { cls: "dl-choice-label", text: o.label }), o.hint ? el("span", { cls: "dl-hint", text: o.hint }) : null]);
        tile.addEventListener("click", function (e) { e.stopPropagation(); picked = o.value; paint(); });
        tile.__value = o.value;
        tiles.push(tile);
        grid.appendChild(tile);
      });
      function paint() { tiles.forEach(function (t) { var on = t.__value === picked; t.classList.toggle("on", on); t.setAttribute("aria-checked", on ? "true" : "false"); }); }
      paint();
      back.addEventListener("click", function (e) { e.stopPropagation(); showList(); });
      go.addEventListener("click", function (e) { e.stopPropagation(); onGo(picked); close(); });
      list.textContent = "";
      list.classList.add("step2");
      list.appendChild(el("p", { cls: "dl-group", text: title }));
      list.appendChild(grid);
      list.appendChild(el("div", { cls: "dl-step-actions" }, [back, go]));
      (tiles.filter(function (t) { return t.__value === picked; })[0] || go).focus();
    }
    function showList() {
      list.textContent = "";
      list.classList.remove("step2");
      if (has) {
        list.appendChild(item("PowerPoint", "5 slides · light or dark", function () {
          chooser("PowerPoint · pick a theme", [
            { value: "light", label: "Light", hint: pageTheme() === "light" ? "matches this view" : null, preview: slidePreview("light") },
            { value: "dark", label: "Dark", hint: pageTheme() === "dark" ? "matches this view" : null, preview: slidePreview("dark") }],
            pageTheme(), function (t) { openUrl(exportUrl(r, opts, "pptx", t)); });
        }, true));
        list.appendChild(item("CSV", "summary or sources", function () {
          chooser("CSV · pick a file", [
            { value: "summary_csv", label: "Summary", hint: "one row" },
            { value: "sources_csv", label: "Sources", hint: "one row per source" }],
            "summary_csv", function (f) { openUrl(exportUrl(r, opts, f)); });
        }, true));
        list.appendChild(item("JSON", "the full certification record", function () { openUrl(exportUrl(r, opts, "json")); close(); }));
      } else {
        list.appendChild(item("JSON", "the full certification record", function () { download([r]); close(); }));
      }
      list.appendChild(item("Copy for CRM", "count, date, confidence, source", function (b) {
        copyText(crmText(r), b.querySelector(".dl-label"), "Copy for CRM");
      }));
      var word = item("Word document", "coming soon", null);
      word.disabled = true;
      word.setAttribute("aria-disabled", "true");
      word.classList.add("dl-disabled");
      list.appendChild(word);
    }
    showList();
    menu.appendChild(list);
    menu.addEventListener("toggle", function () { if (!menu.open) showList(); });
    document.addEventListener("click", function (e) { if (menu.open && !menu.contains(e.target)) menu.open = false; });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); } });
    return menu;
  }

  // Private companies: 3/5 is strong and 4-5 is rare, so say so (and celebrate a rare one).
  function peerNote(h) {
    if (!h.peer_note) return null;
    var rare = h.peer_level === "rare";
    return el("p", { cls: "peer-note " + (rare ? "rare" : "strong") }, [
      el("span", { cls: "peer-ico", "aria-hidden": "true", text: rare ? "✦" : "◆" }),
      el("span", null, [el("strong", { text: rare ? "Rare for a private company · " : "Strong for a private company · " }),
        h.peer_note.replace(/^(Rare|A strong result) for a private company: /, "")]),
      rare ? el("span", { cls: "confetti", "aria-hidden": "true" }, [el("i"), el("i"), el("i"), el("i"), el("i"), el("i")]) : null]);
  }

  // "Our take": the answer in a few plain sentences, with the sources worth opening. A CRM comparison adds a line.
  function ourTake(r) {
    var h = r.headline, k = r.__k;
    if (!h.story) return null;
    var crm = el("span", { cls: "take-crm" });
    r.__takeCrm = crm;
    var look = (h.story_sources || []).map(function (id) {
      var b = el("button", { type: "button", cls: "take-src", text: id, title: "Open source " + id });
      b.addEventListener("click", function () { jump(k + "-" + id); });
      return b;
    });
    return el("div", { cls: "our-take" }, [
      el("p", null, [el("strong", { cls: "take-label", text: "Our take " }), h.story, " ", crm]),
      look.length ? el("p", { cls: "take-look" }, ["Worth a look: "].concat(look)) : null]);
  }

  function answer(r, opts) {
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
      ["Certified range", range],
      ["As of", h.as_of_date ? h.as_of_date + (h.as_of_estimated ? (h.as_of_estimated_from === "url" ? " (estimated from URL)" : " (estimated)") : "") : "undated"],
      ["Confidence", conf],
      ["HQ address", r.entity.address ? el("span", null, [r.entity.address,
        r.entity.address_source ? el("span", { cls: "muted small", text: " · " + r.entity.address_source.replace(/ \(.*\)$/, "") }) : null]) : null],
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

    var crm = h.count != null ? crmCheck(r) : null;
    return el("div", { cls: "block answer " + b }, [
      el("div", { cls: "hero-row" }, [hero, seal(c)]),
      bottom, peerNote(h), ourTake(r), facts,
      el("div", { cls: "row answer-actions" }, [downloadMenu(r, opts), crm ? crm.form : null]),
      crm ? crm.out : null]);
  }

  // "Why you can trust this": five facts, each opening its detail.
  // "Why you can trust this" as a journey, left to right: where the score started (the key source), what recency,
  // independent confirmations, adjustments and red flags each did to it, and where it landed. Each card is coloured
  // by its effect: strong (green ✓), neutral (blue), weak (amber !) or harmful (red ✕).
  function scoreSteps(c) {
    var base = c.breakdown.length ? c.breakdown[0].points : c.score, recency = 0, corr = 0, flags = 0;
    c.breakdown.slice(1).forEach(function (l) {
      var t = (l.rationale || "").toLowerCase();
      if (t.indexOf("recency") === 0) recency += l.points;
      else if (t.indexOf("corroborat") === 0) corr += l.points;
      else flags += l.points;
    });
    return { base: base, recency: recency, corr: corr, flags: flags };
  }
  function trust(r) {
    var k = r.__k, p = r.primary_source, h = r.headline, c = r.confidence, st = scoreSteps(c);
    var corr = r.sources.items.filter(function (s) { return s.role === "corroborates"; });
    var corrFinding = r.findings.items.filter(function (f) { return f.category === "corroboration"; })[0];
    var adj = r.adjustments.items.filter(function (a) { return a.change; }).length;
    var attention = r.findings.items.filter(function (f) { return f.status === "red"; }).length;
    var clamp = function (v) { return Math.max(0, Math.min(5, v)); };
    var s1 = clamp(st.base), s2 = clamp(s1 + st.recency), s3 = clamp(s2 + st.corr), s5 = c.score;
    var TONE_SYM = { strong: "✓", neutral: "◆", weak: "!", harmful: "✕" };
    function card(label, value, effect, tone, running, target) {
      var b = el("button", { type: "button", cls: "trust-item " + tone, title: "Open the detail" }, [
        el("span", { cls: "t-top" }, [el("span", { cls: "t-sym", "aria-hidden": "true", text: TONE_SYM[tone] }), el("span", { cls: "t-label", text: label })]),
        el("strong", { text: value }),
        el("span", { cls: "t-effect", text: effect }),
        el("span", { cls: "t-run", "aria-label": "Score so far " + running + " of 5" }, [el("i", { style: "width:" + running * 20 + "%" }), el("b", { text: running + "/5" })])]);
      b.addEventListener("click", function () { jump(target); });
      return b;
    }
    var baseTone = st.base >= 4 ? "strong" : st.base === 3 ? "neutral" : st.base === 2 ? "weak" : "harmful";
    var keyValue = p && p.source_id ? "Tier " + p.tier + " · " + (p.source_type || p.tier_name) : "No single source";
    var asOf = h.as_of_date ? h.as_of_date + (h.as_of_estimated ? " (est.)" : "") : "undated";
    var landed = el("div", { cls: "trust-land " + band(c.score), role: "img", "aria-label": "Landed at " + c.score + " of 5, " + c.level }, [
      el("span", { cls: "t-label", text: "Where we landed" }), el("strong", { text: c.score + "/5" }), el("span", { cls: "t-effect", text: c.level })]);
    return el("div", { cls: "block trust", role: "group", "aria-label": "Why you can trust this" }, [
      el("div", { cls: "block-title" }, [icon("trust"), el("h2", { text: "Why you can trust this" }),
        el("span", { cls: "muted small", text: "· read left to right: where the score started, what moved it, where it landed" })]),
      el("div", { cls: "trust-strip journey" }, [
        card("Key source", keyValue, "starts at " + st.base + "/5", baseTone, s1, k + "-key"),
        card("As of", asOf, st.recency < 0 ? "−" + (-st.recency) + " · older than the window" : h.as_of_date ? "current · no change" : "undated · no change",
          st.recency < 0 ? "weak" : h.as_of_date && !h.as_of_estimated ? "strong" : "neutral", s2, k + "-key"),
        card("Independent confirmations", String(corr.length), st.corr > 0 ? "+" + st.corr + " · confirmed" : "no change · single-sourced",
          st.corr > 0 ? "strong" : "neutral", s3, corrFinding ? k + "-" + corrFinding.id : k + "-sources"),
        card("Adjustments to the count", String(adj), adj ? "the figure moved · no score change" : "none needed",
          adj ? "neutral" : "strong", s3, k + "-adjustments"),
        card("Needs attention", String(attention), st.flags < 0 ? "−" + (-st.flags) + " · see findings"
          : attention ? "no further effect · already at the minimum" : "nothing red",
          st.flags < 0 ? "harmful" : attention ? "weak" : "strong", s5, k + "-findings"),
        landed])]);
  }

  function scoreSection(r) {
    var k = r.__k, c = r.confidence, table = el("table", { cls: "lines" });
    c.breakdown.forEach(function (line) {
      table.appendChild(el("tr", null, [el("td", { cls: "pts", text: (line.points > 0 && line !== c.breakdown[0] ? "+" : "") + line.points }),
        el("td", null, [line.rationale + " ", chip(line.finding_id, k + "-")])]));
    });
    table.appendChild(el("tr", { cls: "total" }, [el("td", { cls: "pts", text: String(c.score) }), el("td", { text: "= " + c.arithmetic })]));
    return section("How the score adds up", c.score + "/5 = " + c.arithmetic, [table], false, k + "-score", "score");
  }

  // Drill controls: open the sections one level, or everything; close everything. The download menu is left alone.
  function drillBar(root) {
    var all = function () { return Array.prototype.filter.call(root.querySelectorAll("details"), function (d) { return !d.closest(".dl-menu"); }); };
    function btn(text, fn) { var b = el("button", { type: "button", cls: "drill-btn", text: text }); b.addEventListener("click", fn); return b; }
    return el("div", { cls: "drill-bar", role: "toolbar", "aria-label": "Expand or collapse the details" }, [
      el("span", { cls: "drill-lbl", text: "Drill into the evidence" }),
      btn("Expand one level", function () { root.querySelectorAll("details.section").forEach(function (d) { d.open = true; }); }),
      btn("Expand all", function () { all().forEach(function (d) { d.open = true; }); }),
      btn("Collapse all", function () { all().forEach(function (d) { d.open = false; }); })]);
  }

  // Trend and forecast. The chart spans at least three years back and three ahead (wider when the data reaches
  // further): a year with no
  // reported figure is an ✕ on a dotted line, so every chart reads the same. A CRM comparison adds the
  // recommended range (a soft band) and the CRM's number (an orange dashed line).
  var HISTORY_YEARS = 4, FORECAST_YEARS = 3, CRM_COLOR = "#E8833A";  // 3 years back and 3 ahead at least
  // Forecast labels are rounded to a step that suits the size: 10s, 25s, 100s, and 1,000s only for the largest.
  function roundForecast(v) {
    var step = v < 2000 ? 10 : v < 20000 ? 25 : v < 500000 ? 100 : 1000;
    return Math.round(v / step) * step;
  }
  function yearDate(year, md) { return year + (md === "-02-29" ? "-02-28" : md); }
  function chart(r, overlay) {
    var h = r.headline, items = r.trend.items.slice(), ir = h.indicated_current_range;
    if (!items.length && h.count != null && h.as_of_date) items = [{ as_of_date: h.as_of_date, value: h.count, estimated: false }];
    if (!items.length && !ir) return null;
    // Drawn at roughly the on-screen width, so labels stay readable on phones.
    var W = Math.max(320, Math.min(640, (document.documentElement.clientWidth || 640) - 72));
    var H = W < 480 ? 236 : 250, L = W < 480 ? 52 : 64, R = 20, T = 30, B = 40, ns = "http://www.w3.org/2000/svg";
    var t = function (d) { return new Date(d + "T00:00:00Z").getTime(); };
    var reported = items.filter(function (p) { return !p.estimated; }), last = reported[reported.length - 1];
    var future = items.filter(function (p) { return p.estimated && p.low != null; });

    // Placeholder years: missing history years (and the forecast, when there isn't one).
    var gaps = [];
    if (last) {
      var md = last.as_of_date.slice(4), lastYear = +last.as_of_date.slice(0, 4), have = {};
      reported.forEach(function (p) { have[+p.as_of_date.slice(0, 4)] = true; });
      // Five years back, or further when a historical estimate reaches further.
      var fromYear = Math.min(lastYear - HISTORY_YEARS + 1, +reported[0].as_of_date.slice(0, 4));
      for (var gy = fromYear; gy < lastYear; gy++) if (!have[gy]) gaps.push({ as_of_date: yearDate(gy, md), kind: "history" });
      if (!future.length) for (gy = lastYear + 1; gy <= lastYear + FORECAST_YEARS; gy++) gaps.push({ as_of_date: yearDate(gy, md), kind: "forecast" });
      gaps.forEach(function (g) {  // on the line between its neighbours, or level with the nearest figure
        var ms = t(g.as_of_date), prev = null, next = null;
        reported.forEach(function (p) { var pm = t(p.as_of_date); if (pm < ms) prev = p; else if (!next && pm > ms) next = p; });
        if (prev && next) {
          var f = (ms - t(prev.as_of_date)) / (t(next.as_of_date) - t(prev.as_of_date));
          g.value = prev.value + f * (next.value - prev.value);
        } else g.value = (prev || next).value;
      });
    }

    var xs = items.map(function (p) { return t(p.as_of_date); }).concat(gaps.map(function (g) { return t(g.as_of_date); })), vals = [];
    items.forEach(function (p) { vals.push(p.value); if (p.low != null) { vals.push(p.low); vals.push(p.high); } });
    if (ir) { xs.push(t(ir.earliest), t(ir.latest)); vals.push(ir.low, ir.high); }
    // The CRM overlay joins the scale only when it's near the data; a far-off number is pinned to the edge.
    var crmPinned = null;
    if (overlay) {
      vals.push(overlay.lo, overlay.hi);
      var span0 = Math.max.apply(null, vals) - Math.min.apply(null, vals) || Math.max.apply(null, vals) * 0.1;
      if (overlay.crm > Math.max.apply(null, vals) + span0 * 0.8) crmPinned = "above";
      else if (overlay.crm < Math.min.apply(null, vals) - span0 * 0.8) crmPinned = "below";
      else vals.push(overlay.crm);
    }
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), day = 864e5;
    if (x1 - x0 < 300 * day) { x0 -= 180 * day; x1 += 180 * day; }
    var pad = (x1 - x0) * 0.05; x0 -= pad; x1 += pad;
    var v0 = Math.min.apply(null, vals), v1 = Math.max.apply(null, vals);
    var vpad = (v1 - v0) * 0.15 || Math.max(1, v1 * 0.08); v0 = Math.max(0, v0 - vpad); v1 += vpad;
    var step = Math.pow(10, Math.floor(Math.log10((v1 - v0) / 3))); [1, 2, 5, 10].some(function (m) { if ((v1 - v0) / (step * m) <= 4) { step *= m; return true; } });
    var X = function (ms) { return L + (ms - x0) / (x1 - x0) * (W - L - R); };
    var Y = function (v) { return T + (1 - (v - v0) / (v1 - v0)) * (H - T - B); };
    var gid = "area-" + (r.__k || "r0");
    var svgEl = document.createElementNS(ns, "svg");
    svgEl.setAttribute("viewBox", "0 0 " + W + " " + H); svgEl.setAttribute("class", "chart"); svgEl.setAttribute("role", "img");
    svgEl.setAttribute("aria-label", "Headcount over time: " + items.map(function (p) { return p.as_of_date + " " + num(p.value) + (p.estimated ? " (forecast, " + num(p.low) + " to " + num(p.high) + ")" : " (reported)"); }).join("; ") +
      (gaps.length ? "; no reported figure for " + gaps.map(function (g) { return g.as_of_date.slice(0, 4); }).join(", ") : "") +
      (ir ? "; indicated current range " + num(ir.low) + " to " + num(ir.high) : "") +
      (overlay ? "; your CRM " + num(overlay.crm) + ", recommended range " + num(overlay.lo) + " to " + num(overlay.hi) : ""));
    svgEl.__gaps = gaps.length;
    function add(tag, attrs, text) { var n = document.createElementNS(ns, tag); for (var a in attrs) n.setAttribute(a, attrs[a]); if (text != null) n.textContent = text; svgEl.appendChild(n); return n; }
    for (var v = Math.ceil(v0 / step) * step; v <= v1; v += step) {
      add("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "var(--line)", "stroke-width": 1 });
      add("text", { x: L - 8, y: Y(v) + 4, "text-anchor": "end", "class": "axis" }, num(Math.round(v)));
    }
    var y0 = new Date(x0).getUTCFullYear(), y1 = new Date(x1).getUTCFullYear(), every = Math.max(1, Math.ceil((y1 - y0 + 1) / (W < 480 ? 5 : 10)));
    for (var yr = y0; yr <= y1 + 1; yr += every) {
      var ms = Date.UTC(yr, 0, 1); if (ms < x0 || ms > x1) continue;
      add("line", { x1: X(ms), x2: X(ms), y1: H - B, y2: H - B + 5, stroke: "var(--muted)" });
      add("text", { x: X(ms), y: H - B + 18, "text-anchor": "middle", "class": "axis" }, String(yr));
    }
    add("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, stroke: "var(--muted)", "stroke-width": 1 });
    add("text", { x: 4, y: 12, "class": "axis-title", "text-anchor": "start" }, "Employees");
    add("text", { x: L + (W - L - R) / 2, y: H - 4, "class": "axis-title", "text-anchor": "middle" }, "As-of date");
    if (overlay && overlay.xlo != null && overlay.xhi > overlay.xlo) {  // the certified range: a firmer band
      add("rect", { x: L, y: Y(overlay.xhi), width: W - L - R, height: Math.max(2, Y(overlay.xlo) - Y(overlay.xhi)), fill: "var(--loop-green)",
        "fill-opacity": .16, "class": "ov-cert" });
    }
    if (overlay) {  // the acceptable range: a soft band behind everything else
      add("rect", { x: L, y: Y(overlay.hi), width: W - L - R, height: Math.max(2, Y(overlay.lo) - Y(overlay.hi)), fill: "var(--loop-green)", "fill-opacity": .12, "class": "ov-band" });
      [overlay.lo, overlay.hi].forEach(function (b) {
        add("line", { x1: L, x2: W - R, y1: Y(b), y2: Y(b), stroke: "var(--loop-green)", "stroke-width": 1, "stroke-opacity": .7, "stroke-dasharray": "2 4" });
      });
    }
    if (ir) {
      var rx = X(t(ir.earliest)), rw = Math.max(16, X(t(ir.latest)) - rx), rh = Math.max(10, Y(ir.low) - Y(ir.high));
      var ry = Y(ir.high) - (rh === 10 ? 5 - (Y(ir.low) - Y(ir.high)) / 2 : 0);
      add("rect", { x: rx - (rw === 16 ? 8 : 0), y: ry, width: rw, height: rh, fill: "var(--loop-green)", "fill-opacity": .25,
        stroke: "var(--loop-green)", "stroke-width": 1.5, "stroke-dasharray": "4 3", rx: 2 });
      add("text", { x: rx + (rw === 16 ? 0 : rw / 2), y: ry - 6, "text-anchor": "middle", "class": "pt-label ir-label" },
        ir.low === ir.high ? "≈" + num(ir.low) : num(ir.low) + "–" + num(ir.high));
    }
    var pts = reported.map(function (p) { return [X(t(p.as_of_date)), Y(p.value)]; });
    if (!svgEl.querySelector("defs")) {
      var defs = document.createElementNS(ns, "defs");
      defs.innerHTML = '<linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--loop-blue)" stop-opacity=".28"/>' +
        '<stop offset="1" stop-color="var(--loop-blue)" stop-opacity="0"/></linearGradient>';
      svgEl.insertBefore(defs, svgEl.firstChild);
    }
    // Reported years in runs; a missing year breaks the run and is bridged by a dotted line.
    var runs = [[]], gapAt = gaps.filter(function (g) { return g.kind === "history"; }).map(function (g) { return t(g.as_of_date); });
    reported.forEach(function (p, i) {
      var prev = reported[i - 1];
      if (i && (p.historical || prev.historical || gapAt.some(function (gm) { return gm > t(prev.as_of_date) && gm < t(p.as_of_date); }))) runs.push([]);
      runs[runs.length - 1].push(pts[i]);
    });
    runs.forEach(function (run) {
      if (run.length < 2) return;
      var line = smooth(run);
      add("path", { d: line + " L " + run[run.length - 1][0] + " " + (H - B) + " L " + run[0][0] + " " + (H - B) + " Z", fill: "url(#" + gid + ")", stroke: "none" });
      add("path", { d: line, fill: "none", stroke: "var(--meter)", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" });
    });
    if (gaps.length || reported.some(function (p) { return p.historical; })) {
      var chain = gaps.map(function (g) { return { ms: t(g.as_of_date), y: Y(g.value), gap: g }; })
        .concat(reported.map(function (p, i) { return { ms: t(p.as_of_date), y: pts[i][1], hist: p.historical }; }))
        .sort(function (a, b) { return a.ms - b.ms; });
      for (var ci = 1; ci < chain.length; ci++) {
        var a0 = chain[ci - 1], a1 = chain[ci];
        if (!a1.gap && !a0.gap && !a1.hist && !a0.hist) continue;  // reported to reported is drawn above
        add("line", { x1: X(chain[ci - 1].ms), y1: chain[ci - 1].y, x2: X(chain[ci].ms), y2: chain[ci].y, stroke: "var(--muted)",
          "stroke-width": 1.5, "stroke-dasharray": "1.5 5", "stroke-linecap": "round", "class": "gap-line" });
      }
      var labelled = {};
      gaps.forEach(function (g) {
        var gx = X(t(g.as_of_date)), gyy = Y(g.value), s = 4;
        add("path", { d: "M " + (gx - s) + " " + (gyy - s) + " L " + (gx + s) + " " + (gyy + s) + " M " + (gx + s) + " " + (gyy - s) + " L " + (gx - s) + " " + (gyy + s),
          stroke: "var(--muted)", "stroke-width": 2, "stroke-linecap": "round", fill: "none", "class": "gap-x" });
        if (labelled[g.kind] || (g.kind === "history" && reported.some(function (p) { return p.historical; }))) return;
        labelled[g.kind] = true;
        add("text", { x: gx, y: gyy + 18, "text-anchor": g.kind === "forecast" ? "middle" : "middle", "class": "gap-label" },
          g.kind === "forecast" ? "no forecast" : "no data");
      });
    }
    if (last && future.length) {  // one widening band and a dashed line across the forecast years
      var start = [X(t(last.as_of_date)), Y(last.value)];
      var hi = [start].concat(future.map(function (f) { return [X(t(f.as_of_date)), Y(f.high)]; }));
      var lo = [start].concat(future.map(function (f) { return [X(t(f.as_of_date)), Y(f.low)]; }));
      var band = smooth(hi) + " L " + lo[lo.length - 1][0] + " " + lo[lo.length - 1][1] +
        smooth(lo.slice().reverse()).replace(/^M [^C]+/, "") + " Z";
      add("path", { d: band, fill: "var(--loop-blue)", "fill-opacity": .14, stroke: "none" });
      add("path", { d: smooth([start].concat(future.map(function (f) { return [X(t(f.as_of_date)), Y(f.value)]; }))), fill: "none",
        stroke: "var(--meter)", "stroke-width": 2.5, "stroke-dasharray": "6 5", "stroke-linecap": "round" });
    }
    if (overlay) {  // the CRM's number: a dashed orange line, or an edge marker when it's far off the scale
      var cy0 = crmPinned === "above" ? T - 8 : crmPinned === "below" ? H - B - 4 : Y(overlay.crm);
      add("line", { x1: L, x2: W - R, y1: cy0, y2: cy0, stroke: CRM_COLOR, "stroke-width": 2, "stroke-dasharray": "7 5", "class": "ov-crm" });
      var crmText = "Your CRM " + num(overlay.crm) + (crmPinned ? (crmPinned === "above" ? " ↑ off scale" : " ↓ off scale") : "");
      var lastPt = pts.length ? pts[pts.length - 1] : null;
      // The label goes at whichever end of the line is clearer of the data (and its labels), on the clear side.
      var ends = [items[0], items[items.length - 1]].map(function (q) { return Y(q.value); });
      var right = Math.abs(cy0 - ends[1]) > Math.abs(cy0 - ends[0]), near = ends[right ? 1 : 0];
      var above = crmPinned ? crmPinned === "below" : cy0 < near;
      add("text", { x: right ? W - R - 4 : L + 6, y: above ? cy0 - 6 : cy0 + 15, "text-anchor": right ? "end" : "start",
        "class": "ov-label", fill: CRM_COLOR }, crmText);
      if (overlay.target != null && overlay.target !== r.headline.count && lastPt) {  // a suggestion other than the certified figure: a ring on its date
        add("circle", { cx: lastPt[0], cy: Y(overlay.target), r: 9, fill: "none", stroke: CRM_COLOR, "stroke-width": 2, "class": "ov-target" });
      }
    }
    var finalForecast = future.length ? future[future.length - 1] : null;
    items.forEach(function (p, i) {
      var cx = X(t(p.as_of_date)), cy = Y(p.value), isLast = p === last;
      if (p.historical) {  // a historical estimate: hollow, muted, labelled as an estimate with its year
        add("circle", { cx: cx, cy: cy, r: 5, fill: "var(--card)", stroke: "var(--muted)", "stroke-width": 2.5, "stroke-dasharray": "3 2", "class": "hist-pt" });
        add("text", { x: cx, y: cy - 12, "text-anchor": i === 0 ? "start" : "middle", "class": "pt-label pt-faint hist-label" }, "≈" + num(p.value) + " est.");
        return;
      }
      if (isLast) {  // the certified figure: a soft halo and a guide down to its as-of date
        add("line", { x1: cx, x2: cx, y1: cy + 12, y2: H - B, stroke: "var(--loop-green)", "stroke-width": 1.5, "stroke-dasharray": "2 4", "class": "cert-guide" });
        add("circle", { cx: cx, cy: cy, r: 11, fill: "var(--loop-green)", "fill-opacity": .22 });
      }
      add("circle", { cx: cx, cy: cy, r: isLast ? 6.5 : (p.estimated ? 4 : 5), fill: p.estimated ? "var(--card)" : "var(--meter)", stroke: isLast ? "var(--loop-green)" : "var(--meter)", "stroke-width": isLast ? 3 : 2.5 });
      // Values only on the chart; the certified point and the forecast range are named in the legend. The
      // forecast label sits below its point so it never collides with the certified label above.
      // Forecast labels sit on the open side of the line: rising, the yearly ones below and the final one above;
      // falling, the reverse. So none of them meets the certified caption or each other.
      var rising = finalForecast && last && finalForecast.value >= last.value;
      var below = p.estimated ? (p === finalForecast ? !rising : rising) : false;
      if (W < 480 && p.estimated && p !== finalForecast) return;  // phones: only the final forecast year
      if (p.estimated && p !== finalForecast && future.length > 1) {  // tight spacing: every other year, counting back from the final
        var gapPx = Math.abs(X(t(future[1].as_of_date)) - X(t(future[0].as_of_date)));
        if (gapPx < 56 && (future.length - 1 - future.indexOf(p)) % 2 === 1) return;
      }
      if (W < 480 && !p.estimated && !isLast && i !== 0) return;  // phones: first, certified and final forecast only
      var first = i === 0 && !gaps.some(function (g) { return g.kind === "history" && t(g.as_of_date) < t(p.as_of_date); });
      add("text", { x: cx, y: below ? cy + 20 : cy - (isLast ? 16 : 11),
        "text-anchor": first && items.length > 1 ? "start" : (i === items.length - 1 && !gaps.some(function (g) { return g.kind === "forecast"; }) ? "end" : "middle"),
        "class": "pt-label" + (isLast ? " pt-key" : "") + (p.estimated ? " pt-est" + (p === finalForecast ? "" : " pt-faint") : "") },
        p.estimated ? "≈" + num(roundForecast(p.value)) : num(p.value));
      if (isLast) add("text", { x: cx, y: cy - 34 < T - 8 ? cy + 28 : cy - 34, "text-anchor": first && items.length > 1 ? "start" : "middle", "class": "pt-cert" }, "✓ CERTIFIED");
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

  function legend(r, svgEl, overlay) {
    var h = r.headline, fcs = r.trend.items.filter(function (p) { return p.estimated; }), fc = fcs[fcs.length - 1];
    return el("div", { cls: "legend small muted" }, [el("span", null, [el("i", { cls: "lg solid" }), "Reported"]),
      el("span", null, [el("i", { cls: "lg key" }), "Certified figure"]),
      fc ? el("span", null, [el("i", { cls: "lg hollow" }), "Forecast " + (fcs.length > 1 ? "to " : "") + fc.as_of_date.slice(0, 4) + ": ≈" + num(roundForecast(fc.value)) +
        (fc.low != null ? " (range " + num(roundForecast(fc.low)) + "–" + num(roundForecast(fc.high)) + ")" : "")]) : null,
      svgEl.__gaps ? el("span", null, [el("i", { cls: "lg gap", text: "✕" }), "No reported figure"]) : null,
      r.trend.items.some(function (p) { return p.historical; }) ? el("span", null, [el("i", { cls: "lg hist" }),
        "Historical estimate (older statement, not certified)"]) : null,
      h.indicated_current_range ? el("span", null, [el("i", { cls: "lg box" }), "Indicated current range (context only)"]) : null,
      overlay && overlay.xhi > overlay.xlo ? el("span", null, [el("i", { cls: "lg range strong" }), "Certified range " + num(overlay.xlo) + "–" + num(overlay.xhi)]) : null,
      overlay ? el("span", null, [el("i", { cls: "lg range" }), "Acceptable for your CRM " + num(overlay.lo) + "–" + num(overlay.hi)]) : null,
      overlay ? el("span", null, [el("i", { cls: "lg crm" }), "Your CRM " + num(overlay.crm)]) : null,
      overlay && overlay.target != null ? (overlay.target === h.count ? el("span", null, [el("i", { cls: "lg key" }), "Suggested: the certified figure"])
        : el("span", null, [el("i", { cls: "lg target" }), "Suggested " + num(overlay.target)])) : null]);
  }

  function trendBlock(r) {
    var h = r.headline, nodes = [el("div", { cls: "block-title" }, [icon("trend"), el("h2", { text: "Trend and forecast" })])];
    if (h.direction) nodes.push(el("p", { cls: "direction " + h.direction }, [el("strong", { text: DIRECTION[h.direction] || h.direction }), " · " + (h.direction_reason || "")]));
    var svgEl = chart(r);
    if (svgEl) {
      var wrap = el("div", { cls: "chart-wrap" }, [svgEl]), key = legend(r, svgEl);
      nodes.push(wrap, key);
      // The CRM compare redraws the chart with its overlays (or without, when cleared).
      r.__redraw = function (overlay) {
        var next = chart(r, overlay), nextKey = legend(r, next, overlay);
        wrap.replaceChild(next, wrap.firstChild);
        key.parentNode.replaceChild(nextKey, key); key = nextKey;
      };
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

  // Guided drill-in hints: shown until opened once (remembered per browser).
  function seen(key) { try { return localStorage.getItem("gtm_hint_" + key) === "1"; } catch (e) { return false; } }
  function markSeen(key) { try { localStorage.setItem("gtm_hint_" + key, "1"); } catch (e) {} }
  function hint(text) { return el("span", { cls: "hint", role: "note" }, [el("i", { "aria-hidden": "true" }), text]); }
  function guide(details, key, text, summary) {
    if (seen(key)) return;
    var h = hint(text);
    (summary || details.querySelector("summary")).appendChild(h);
    details.addEventListener("toggle", function () { if (details.open) { markSeen(key); h.remove(); } });
  }

  // ---------- Compare with your CRM (optional): bumper-car recommendation ----------
  // The certified figure sits in a lane whose bumpers narrow as confidence rises. A CRM number inside the lane is
  // fine; outside it, we suggest moving it in, pushing harder (toward the certified figure itself) the higher the
  // confidence, and harder still when the move agrees with the likely direction since the as-of date.
  var CRM_TOLERANCE = { 5: 0.05, 4: 0.08, 3: 0.15, 2: 0.25, 1: 0.40 };
  var CRM_STRENGTH = { strong: "Update recommended", moderate: "Consider updating", light: "Optional: review" };
  function parseCount(text) {
    var m = String(text || "").trim().toLowerCase().replace(/[,\s]/g, "").match(/^(\d+(?:\.\d+)?)(k|m)?$/);
    if (!m) return null;
    var v = parseFloat(m[1]) * (m[2] === "k" ? 1e3 : m[2] === "m" ? 1e6 : 1);
    return v > 0 ? Math.round(v) : null;
  }
  // Two ranges, one story: the certified range (X) is what we stand behind; the acceptable range (Y) is wider,
  // as wide as the confidence warrants, for leaving a CRM number alone. Outside Y we suggest moving into X (its
  // nearest edge), and at the very least to Y's edge. When the likely direction since the as-of date points toward
  // your number, we suggest only Y's edge.
  function crmAdvice(r, v) {
    var h = r.headline, c = h.count, score = r.confidence.score, t = CRM_TOLERANCE[score];
    if (c == null || !t) return { kind: "none", text: "There's no certified figure to compare against." };
    var xlo = h.range ? h.range[0] : c, xhi = h.range ? h.range[1] : c;
    var lo = Math.min(xlo, c * (1 - t)), hi = Math.max(xhi, c * (1 + t));
    if (h.direction === "lower") lo -= c * t / 2;  // the true figure has likely moved down: widen the lower side
    if (h.direction === "higher") hi += c * t / 2;
    lo = Math.round(lo); hi = Math.round(hi);
    var band = { lo: lo, hi: hi, certified: c, xlo: xlo, xhi: xhi };
    var xText = xlo === xhi ? num(c) : num(xlo) + "–" + num(xhi);
    if (v >= lo && v <= hi) {
      var inX = v >= xlo && v <= xhi;
      return { kind: "keep", band: band, label: "Keep your number",
        text: num(v) + " is inside the " + score + "/5 acceptable range (" + num(lo) + "–" + num(hi) + ")" +
          (inX ? " and the certified range. No change needed." : ". No change needed; the certified range is " + xText + ".") };
    }
    var above = v > hi, edge = above ? hi : lo, off = above ? (v - hi) / hi : (lo - v) / lo;
    var agrees = (above && h.direction === "lower") || (!above && h.direction === "higher");
    var against = (above && h.direction === "higher") || (!above && h.direction === "lower");
    var target = above ? xhi : xlo;
    var strength = score >= 4 ? "strong" : score === 3 ? "moderate" : "light";
    if (agrees) strength = strength === "light" ? "moderate" : "strong";
    if (against) {
      target = edge;  // the true figure may have moved your way: the acceptable range's edge is enough
      if (strength === "strong" && score < 5) strength = "moderate";
    }
    var why = agrees ? " The recent direction agrees." : against ? " Only to the acceptable range: the figure has likely moved " +
      (h.direction === "higher" ? "up" : "down") + " since." : "";
    return { kind: strength, band: band, target: target, minimum: edge, label: CRM_STRENGTH[strength],
      text: num(v) + " is " + Math.round(off * 100) + "% " + (above ? "above" : "below") + " the " + score + "/5 acceptable range (" +
        num(lo) + "–" + num(hi) + "). Suggest " + num(target) + (target === edge ? "." : (xlo === xhi ? ", the certified figure" :
        ", the edge of the certified range " + xText) + " (at least " + num(edge) + ").") + why };
  }

  // Compact: an inline box beside Download. The verdict appears below it, and the chart above gains the
  // recommended range and the CRM's number.
  function crmCheck(r) {
    var k = r.__k, input = el("input", { type: "text", inputmode: "numeric", autocomplete: "off", id: k + "-crm-input",
      placeholder: "e.g. 95,000", "aria-label": "Your CRM employee count" });
    var go = el("button", { type: "submit", cls: "crm-go", text: "Compare →" }), out = el("div", { cls: "crm-out", "aria-live": "polite" });
    var form = el("form", { cls: "crm-inline", id: k + "-crm" }, [el("label", { "for": k + "-crm-input", cls: "crm-lbl" }, [icon("compare"), "Compare with your CRM"]), input, go]);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      out.textContent = "";
      if (r.__takeCrm) r.__takeCrm.textContent = "";
      if (!input.value.trim()) { if (r.__redraw) r.__redraw(null); return; }
      var v = parseCount(input.value);
      if (v == null) { out.appendChild(el("p", { cls: "small muted", text: "Enter a number, for example 95,000 or 95k." })); return; }
      var adv = crmAdvice(r, v);
      if (adv.kind === "none") { out.appendChild(el("p", { cls: "small muted", text: adv.text })); return; }
      var parts = [el("strong", { text: adv.label }), " · " + adv.text];
      if (adv.target) {
        var cp = el("button", { type: "button", cls: "link crm-copy", text: "Copy " + num(adv.target) });
        cp.addEventListener("click", function () { copyText(String(adv.target), cp, "Copy " + num(adv.target)); });
        parts.push(" ", cp);
      }
      if (r.__redraw) parts.push(el("span", { cls: "crm-see", text: " Shown on the chart above." }));
      out.appendChild(el("p", { cls: "crm-verdict " + adv.kind }, parts));
      if (r.__takeCrm) r.__takeCrm.textContent = adv.kind === "keep"
        ? "Your CRM's " + num(v) + " is within the acceptable range, so it can stay."
        : "Your CRM's " + num(v) + " is " + (v > adv.band.hi ? "above" : "below") + " the acceptable range (" + num(adv.band.lo) + "–" +
          num(adv.band.hi) + "); we'd update it to " + num(adv.target) +
          (adv.minimum != null && adv.minimum !== adv.target ? " (at least " + num(adv.minimum) + ")" : "") + ".";
      if (r.__redraw) r.__redraw({ crm: v, lo: adv.band.lo, hi: adv.band.hi, xlo: adv.band.xlo, xhi: adv.band.xhi,
        target: adv.target != null ? adv.target : null });
    });
    return { form: form, out: out };
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
    var block = section("Sources", items.length + " found, " + used + " used", nodes, false, k + "-sources", "sources");
    guide(block.querySelector("details.section"), "sources", "Drill in: see every source");
    // Inside, point at the source that differs most from the certified figure (never the key source).
    var count = r.headline.count, best = null, gap = -1, key = r.primary_source || {};
    items.forEach(function (s) {
      if (s.role === "selected" || count == null) return;
      // Skip the key source's own earlier editions (trend points): point at a genuinely different source.
      if (s.tier === key.tier && s.source_type === key.source_type && s.as_of_date && key.as_of_date && s.as_of_date < key.as_of_date) return;
      var d = Math.abs(s.value - count) / Math.max(1, count);
      if (d > gap) { gap = d; best = s; }
    });
    if (best && gap > 0.01) {
      var row = block.querySelector("#" + k + "-" + best.id);
      if (row) guide(row, "source-row", best.used ? "Different figure: why it still counts" : "Different figure: why it wasn't used",
        row.querySelector("summary .src-sum"));
    }
    return block;
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
    var block = section("Events and LinkedIn", (items.length ? items.length + " event(s)" : "no events") + " · LinkedIn " + li.status.replace("_", " "), nodes,
      false, null, "events");
    if (items.length) guide(block.querySelector("details.section"), "events",
      items.length === 1 ? "1 event: see what changed" : items.length + " events: see what changed");
    return block;
  }

  function footer(r, all, opts) {
    var m = r.methodology;
    var models = Object.keys(m.models || {}).map(function (k) { return k + ": " + m.models[k]; }).join(", ");
    var method = section("Method and models", m.method + " · $" + Number(m.cost_usd).toFixed(2) + (m.duration_s != null ? " · " + m.duration_s + " s" : ""), [
      kv([["Method", m.method], ["Models", models || "none (rule-based)"], ["Policy version", m.policy_version + " · record " + m.record_version],
          ["Cost", "$" + Number(m.cost_usd).toFixed(2) + " · " + m.web_searches + " searches, " + m.web_fetches + " fetches"],
          ["Run", (m.run_at ? m.run_at.replace("T", " ").slice(0, 19) + " UTC" : m.lookup_date) + (m.duration_s != null ? " · " + m.duration_s + " s" : "")]])],
      false, r.__k + "-method", "method");
    var parts = [method.firstChild];
    parts.push(el("div", { cls: "row footer-actions" }, [downloadMenu(r, opts)]));
    parts.push(el("p", { cls: "owner-notice", text: OWNER_LINE }));
    return el("footer", { cls: "block" }, parts);
  }

  function json(all) {
    var body = all.length === 1 ? Object.assign({ notice: OWNER_LINE }, all[0]) : { notice: OWNER_LINE, records: all };
    return JSON.stringify(body, function (k, v) { return k === "__k" || k === "__links" ? undefined : v; }, 2);
  }
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
    ["entity", "parent"].forEach(function (key) {
      var d = data[key];
      if (d && d.record) { if (d.downloads) d.record.__links = d.downloads; out.push(d.record); }
    });
    return out;
  }

  function render(root, data, opts) {
    opts = opts || {};
    var records = toRecords(data);
    root.textContent = "";
    if (!records.length) { root.appendChild(el("p", { cls: "muted", text: "No certification record in this result." })); return records; }
    records.forEach(function (r, i) {
      r.__k = "r" + i;
      var score = scoreSection(r);
      var art = el("article", { cls: "card", "aria-label": "Certification for " + r.entity.name }, [
        header(r, opts), answer(r, opts), trendBlock(r), trust(r), score, findings(r), primary(r), sources(r), adjustments(r), events(r),
        footer(r, records, opts)]);
      art.insertBefore(drillBar(art), score);
      root.appendChild(art);
    });
    if (location.hash === "#expand-all") Array.prototype.forEach.call(root.querySelectorAll("details"), function (d) { d.open = true; });
    if (opts.onRender) opts.onRender(records);
    return records;
  }

  window.GTMCard = { render: render, toRecords: toRecords, crmAdvice: crmAdvice, parseCount: parseCount, roundForecast: roundForecast };
})();
"""

# Boot for the standalone file and the MCP App: render embedded data, or data pushed by the host.
CARD_JS = CARD_JS.replace("__OWNER_LINE__", json.dumps(OWNER_LINE, ensure_ascii=False))

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
  window.GTMCard.openLink = inFrame ? function (url) {
    request("ui/open-link", { url: url }).then(function (res) { if (!res || res.isError) window.open(url, "_blank", "noopener"); });
  } : null;
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
    "<meta name=\"color-scheme\" content=\"light dark\">\n" + ROBOTS_META + "\n<title>__TITLE__</title>\n<style>"
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
