# Decisions: standardized record and company card

Decisions made while building the `feature/company-card` branch, most consequential first within each part. Each entry gives what was decided, why, and the alternatives considered.

## Card delivery

### D1. Render the card inside Claude Desktop as an MCP App, and also save an HTML file every time
- **What:** `certify_employee_count` is bound to a `ui://employee-count-certifier/card` resource through the MCP Apps extension (`mcp.server.apps`). Each lookup also writes a self-contained HTML card to `outputs/`, and the tool result returns its path.
- **Why:** Anthropic's documentation says Claude Desktop renders MCP Apps, including for local servers configured in `claude_desktop_config.json`. The mcp 2.x SDK ships the server side. I can't watch Claude Desktop render from this environment, so the saved file guarantees there's always a working card.
- **Alternatives:**
  - HTML file only: safe, but it ignores the interactive route you asked to use.
  - MCP App only: no fallback if rendering fails.

### D2. Write the in-chat message bridge inline instead of loading the ext-apps SDK from a CDN
- **What:** about 30 lines of inline JavaScript do the handshake: send `ui/initialize`, send `ui/notifications/initialized`, render from any host message carrying `structuredContent` (which covers `ui/notifications/tool-result`), and report size with `ui/notifications/size-changed`.
- **Why:** the brief requires one file with inline CSS and JS and no external calls. The official example loads its client from unpkg.com, which would also need a CSP exception.
- **Alternatives:** load `@modelcontextprotocol/ext-apps` from unpkg with a `resourceDomains` CSP entry, or bundle it.
- **Risk:** I hand-wrote the protocol from partial spec text, and the bridge isn't tested inside Claude Desktop. It sends both naming variants the spec shows for initialize parameters. If the inline card doesn't appear, the HTML file still works.

### D3. One template, two data paths
- **What:** the same HTML template renders a record either embedded as JSON (the saved file) or pushed by the host (MCP App). JavaScript builds the DOM from the record.
- **Why:** one renderer means the in-chat card and the saved file never drift apart.
- **Alternatives:** render HTML in Python for files and JavaScript for the app. That means two renderers to keep in sync.

## Record shape

### D4. List sections are objects with `items` and `none_reason`
- **What:** `findings`, `sources`, `adjustments`, `trend` and `events` are each `{items: [...], none_reason}`. Single-object sections (`headline`, `primary_source`) carry their own `none_reason` when empty.
- **Why:** this meets "every section present even when empty, with an explicit none reason" without special cases. Validation fails on an empty list with no reason.
- **Alternatives:** bare lists plus a separate map of empty reasons. That's easier to read but easier to get out of sync.

### D5. Findings are generated deterministically from the engine's output, not by Claude
- **What:** `record.build_record` derives every finding from the certification: the base score, provenance, mirrors, corroboration, each confidence flag, LinkedIn, events, scope, qualifier/FTE/adjustments, and budget notes.
- **Why:** the result is reproducible, free, testable offline, and always consistent with the score. Each score line maps to exactly one finding.
- **Alternatives:** ask Claude to write findings. That would read more naturally but costs money, varies between runs, and can contradict the engine.

### D6. Rationale rules are enforced by the models themselves
- **What:**
  - Every tier rationale, use/exclusion rationale, adjustment, score line, event and LinkedIn check needs at least one plain-English sentence (12 or more characters, with real words).
  - Finding rationales need two or more sentences.
  - The confidence breakdown must sum to the score, and every breakdown line, LinkedIn check and evidence ID must point to an existing finding or source.

  A record that breaks any of these can't be built or loaded.
- **Why:** "fail validation if any is missing" is enforced at construction time, not only in tests.
- **Alternatives:** a separate linter run in tests only. That's weaker, because a bad record could still be returned to a user.

### D7. Engine change: every source records `role_reason`, and events record `EventOutcome`
- **What:** the engine sets a one-sentence reason wherever it assigns a role (selected, corroborates, excluded and why), and records whether each event was penalized and why.
- **Why:** the reasons exist only at decision time inside the engine. Reconstructing them later would be guesswork. No policy rule changed.
- **Alternatives:** infer reasons in the record builder from roles and notes. That's fragile.

### D8. The base score is itself a finding, and the "no deductions" line links to it
- **What:** the first breakdown line ("base 4: tier 1, as-of within 18 months") links to a recency finding with `score_impact` 0. A trailing "+0 no deductions" line links to the same finding.
- **Why:** every line must link to a finding, and the base score needs an explanation of its own.
- **Alternatives:** drop the zero line. The arithmetic would then show less clearly that nothing was deducted.

### D9. Finding status thresholds
- **What:**
  - **Green:** the finding supports the figure, or the base score is 4 or more.
  - **Yellow:** a caveat with no score impact, or a base score of 2–3.
  - **Red:** any flag that lowered confidence, or a base score of 0–1.
- **Why:** this follows your rule: red means it lowers confidence or needs human review. Conservative: every penalizing flag is red, even when the minimum score of 1 absorbed it.

### D10. The trend forecast follows the existing spec rule
- **What:** the forecast is a linear trend over at least 3 same-basis points, one year ahead. Its range comes from the variation in year-over-year changes. It's marked `estimated: true`.
- **Why:** SPEC.md already defines this rule (later phase). The card asks for a forecast point marked "estimated". The forecast appears only in `trend`, never in the headline.
- **Alternatives:** leave the forecast out until the later phase.

### D11. IDs
- **What:** sources are `S1…`, findings `F1…`, adjustments `A1…`, numbered in record order.
- **Why:** short, stable within a record, and readable in a CSV export.

## Card design

### D12. What's open by default
- **What:**
  - **Always visible:** the header, the headline and the confidence meter.
  - **Open by default:** the primary source; the findings section opens itself when there are red findings.
  - **Collapsed:** the score breakdown, sources, adjustments, trend, and events and LinkedIn. Every row inside them expands on click.
  - **For reviewing:** `#expand-all` on the URL opens everything.
- **Why:** the brief asked for collapsed-by-default with drill-down. Red findings need attention, so they shouldn't hide.
- **Alternatives:** everything collapsed, which hides red findings; everything open, which is too long to scan.

### D13. Accessibility and safety
- **What:**
  - **Status:** always an icon, a word and a color (✓ Green / ! Yellow / ✕ Red). The confidence meter has an `aria-label`. Expanding uses native `<details>`, so it works by keyboard and without scripts.
  - **Color and theme:** one accent color (blue). Light and dark mode follow the system, or the host's theme inside Claude.
  - **Safety:** the DOM is built only with `textContent`, links are limited to http(s), and every `<` in the embedded JSON is escaped as `\u003c`.
- **Why:** source excerpts are third-party text, so the card treats them as untrusted. A test with a hostile excerpt caught an escaping bug during the build: the first version wrote `<\!--`, which isn't valid JSON.

### D14. Download JSON plus a Copy JSON fallback
- **What:** "Download JSON" saves the record from the page; "Copy JSON" copies it to the clipboard.
- **Why:** inside Claude's sandboxed frame a download may be blocked. The spec mentions a host `ui/download-file` method, but I couldn't confirm its parameters, so I didn't use it.
- **Alternatives:** call `ui/download-file` blind.

### D15. Visual checks used headless Microsoft Edge
- **What:** I checked each layout with headless Edge screenshots: collapsed, expanded, dark mode, and 375px width through an iframe (headless windows have a minimum width).
- **Why:** Node isn't installed, and I didn't want to drive your own browser.
- **Fixes this found:** a meaningless "range 83,334–83,334" for exact figures, a clipped summary line at phone width, red-finding titles wrapping under their badges, and "within 0%" (now "0.4%").

## Testing, spend and scope

### D16. Live spend: one recorded run per requested lookup ($0.46 total)
- **What:** Salesforce, Gong, Donor Network West and UC Davis each ran live once. The full results are saved in `tests/fixtures/lookups/`. Tests, cards and the MCP tool test all reuse these recordings; the MCP tool test stubs the lookup with the Salesforce fixture.
- **Why:** this stays far under the $3 cap and makes the cards and tests reproducible. The live EDGAR golden set is free.
- **Alternatives:** live calls inside the tests, which costs money and gives different results on each run.

### D17. Cards are built from the recordings with `certifier-card`
- **What:** `python -m certifier.card LOOKUP.json …` (or the `certifier-card` command) writes one card per saved lookup to `outputs/`. The four cards are committed.
- **Why:** you can regenerate the cards for free after design changes, and review them on the branch.

### D18. No policy rules changed
- **What:** confidence, selection and corroboration rules are untouched. The engine now only records reasons for decisions it already made. Where a choice touched policy, I took the conservative option:
  - every penalizing flag shows as red, even when the minimum score of 1 absorbed it
  - a derived value gets no "primary source"; a reason explains the derivation instead of crowning one data provider
  - the forecast never appears in the headline
- **Why:** the guardrail limits changes to SPEC.md policy rules.

### D19. "Used" means selected, corroborating or a derivation input
- **What:** every other source shows as "Excluded", with its reason (restatement, other period, partial scope, mirror, conflict…).
- **Why:** this gives the binary used/excluded column you asked for, while the row's reason keeps the nuance.

### D20. The running Claude Desktop server was left alone
- **What:** Claude Desktop was running the MCP server during this work, which locked `certifier-mcp.exe`. I didn't stop it.
- **Effect:**
  - The in-chat card appears only after you restart Claude Desktop.
  - The new `certifier-card` command installs on the next `uv sync`. Until then, `python -m certifier.card` works.

## Source location: URL, detailed excerpt, section and page (record v1.1)

### D21. SEC quotes are located in the filing itself, not by the model
- **What:** for every sec.gov source, `locate.py` re-reads the filing and finds the quote, or the figure next to an employment word, along with its page, its ITEM heading and sub-heading, and the passage around it. This overrides any location the research step reported.
- **Why:** the filing is the authoritative copy, it costs nothing (EDGAR is free and already fetched), and the model can misremember page numbers.
- **Alternatives:** trust the extraction's section and page for every source.

### D22. Show the printed page number, labelled; fall back to the page's position in the HTML filing
- **What:**
  - **Printed:** the page number is read from the page footer (e.g. "printed page 10").
  - **Fallback:** when a page has no printed number, the label says "page 22 of the HTML filing", and the note explains why.
  - **Both:** the note always gives both numbers, e.g. "Printed page 10 (page 11 of 101 in the HTML filing)".
- **Why:** readers cite printed page numbers. The HTML position keeps the location findable when a filing prints none (Novo Nordisk's 20-F, for example).

### D23. Jump-to-quote links use text fragments
- **What:** `deep_link` is the source URL plus `#:~:text=<start>,<end>`. Commas and hyphens are percent-encoded. No link is made for quotes under 4 words, which are too short to be unique.
- **Why:** this jumps to and highlights the exact quote in Chromium-based browsers; other browsers just open the page. No server or index is needed.
- **Alternatives:** page anchors, which SEC filings don't provide consistently.

### D24. Form 990 and website locations are fixed by the source type
- **What:**
  - **Form 990:** "Form 990 › Part I (Summary) › line 5", Form page 1. The verbatim quote is line 5's own text, and the passage runs through line 6.
  - **Websites:** stat tiles are rewritten as readable pairs ("Statistics shown on the page: Customers: 5,000; Employees: 1,500.") instead of raw page data, and say "no page numbers".
- **Why:** these locations are known from how the source is structured, so guessing isn't needed. A raw-data passage would be unreadable.

### D25. The primary source may lack a verbatim quote only with an explicit reason
- **What:** validation requires either the quote or `excerpt_missing_reason`. Today only SAP's golden example uses the reason, because sap.com blocks automated reading.
- **Why:** this is the conservative choice. It never invents text, and it never fails a real record silently.

### D26. Re-recorded the four live lookups so the fixtures carry locations captured end to end
- **What:** all four were re-recorded ($0.47), then Gong and Donor Network West again after the readable-tile and Form 990 fixes ($0.22). That's $0.69 for this request and $1.15 on the branch in total. The Form 990 entries in Donor Network West's fixture were later refreshed from ProPublica for free, to pick up the shorter section name and the verbatim line-5 quote.
- **Why:** this proves the whole pipeline captures locations, rather than patching old fixtures.

### Open issue: a dated URL path isn't used as a date
Donor Network West scores 2 because a 2023 sponsorship PDF reporting 300 people came back from research with no date, so it counted as a non-stale conflict. Its URL contains `/wp-content/uploads/2023/03/`. Inferring a published date from such paths would fix this, but it's a policy change, so it's logged rather than made.

## Scoring fixes from the Stripe run

Stripe had been certified at 8,500 with confidence 2. It's now 8,500 with confidence 1, plus an indicated current range of 8,198–10,000.

### D27. Estimating an as-of date when the source gives none
- **What:** when a source has no as-of date, one is estimated and stored with `as_of_estimated: true`. Every recency rule uses it. The estimate comes from:
  - research's estimate from wording ("as of early 2025"), if available
  - otherwise the publication date, or the modified date when that's later
- **The cap:** the estimate is never later than the source's publication date or the lookup date. The Stripe rerun caught research dating a "10,000 by end of 2025" target to 2025-12-31.
- **Why:** an article reports headcount as of roughly when it was written. Leaving the date out let an old figure pass as current.
- **Alternatives:** use the lookup date, which is how the bug happened; or never estimate, which would leave Stripe undated.

### D28. The corroboration window is centred on the anchor's as-of date; an undated anchor gets no bonus
- **What:** before, an undated anchor was "presumed current" and measured against the lookup date. That's how March 2026 Revelio data corroborated a January 2025 statement. Now the window centres on the anchor's as-of date (estimated or not). If there's still no date, no source can corroborate it.
- **Effect:** Gong's website tile (no date at all) can no longer gain a bonus. Gong's score didn't change, because its growth-adjusted path doesn't use one.

### D29. Recency is now its own −1 line, for every tier
- **What:** the breakdown now runs base → recency → corroboration → flags.
  - **Base:** 4 for tier 1–2, 3 for tier 3, 2 for tiers 4–6.
  - **Recency:** −1 when the anchor is older than 18 months, estimated dates included. Undated tier 1–2 sources also lose a level, as before.
  - **Corroboration:** +1 is unchanged from the confidence table: tier 1–2 only when recent, never tier 3, always tier 4–6.
- **Why:** you asked for recency to apply whenever the window is exceeded, with the finding's score impact matching the deduction. Old tier 1–2 sources still land on 3, exactly as before. Only tier 3–6 scores change: they now lose a level when old.
- **Alternatives:** a separate 24-month window for secondary sources. Rejected: the 18-month window is the policy's existing certified window.
- **Not penalized:** an anchor with no date at all and no basis to estimate one, like Gong's website tile. Its age can't be measured, and it already loses the corroboration bonus.

### D30. Known changes label the figure "pre-adjustment"; the number isn't adjusted
- **What:** any confirmed change that took effect after the as-of date (layoffs, acquisitions, spinoffs) sets `adjustment_status: pre-adjustment` and is listed in `known_changes`. A material change (over 15%, or of unknown size) also lowers confidence one level, under the existing event rule. When the headcount change is stated, the engine judges materiality itself against the certified value. That way Salesforce's layoffs of about 1,000 (1.2%) aren't penalized.
- **Why this option:** announced cuts often differ from what actually happens, and timing is uncertain. Subtracting an announced number would publish a figure no source states. Labelling it keeps the certified figure true to its source while still warning the reader.
- **Also:** bids, proposals and rumors are excluded. The Stripe rerun had flagged a reported Stripe–Advent bid for PayPal.

### D31. Indicated current range
- **What:** shown when:
  - the anchor is at least 12 months old
  - newer tier 7–9 figures are dated at least 3 months after it and within the last 12 months
  - outliers more than 30% from the median are dropped (as in the growth signal)
  - the remaining figures' mean differs from the certified figure by at least 5%
- **Placement:** it appears next to the count, marked "context only, not certified", with a yellow finding. It's never shown when the growth adjustment has already moved the value.
- **Why 5%:** you named quarterly Revelio diverging from Stripe's old figure. That gap was about 10%, under the 15% corroboration threshold, so a stricter cut-off would have hidden exactly the case you asked about. All four thresholds are in `policy.yaml`.

### D32. Card header renamed to "Key Source"
Done now rather than in the design pass, since it's a one-word change. It's logged in FEEDBACK.md.

### Open issue: overuse of complexity flags
In the Stripe rerun, research listed data disagreements as "complexity" flags ("tracker estimates disagree"). The extraction instructions say complexity is for entity-scope ambiguity only. It didn't change Stripe's result, since the score was at its minimum, but tightening this further would make the findings cleaner.
