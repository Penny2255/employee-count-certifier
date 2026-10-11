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
