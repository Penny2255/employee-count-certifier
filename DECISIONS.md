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

## Hosting (code ready; you create the Render service)

### D33. Claude connector access is OAuth sign-in by access code; a bearer header is also accepted
- **What:** Claude's documentation says a fixed bearer-token header ("Request headers") is a beta feature, limited to some organizations, set by an organization Owner, and shared by the whole organization. Most accounts can't send a per-user header. So the server also runs a minimal OAuth authorization server:
  - Claude registers itself automatically (Dynamic Client Registration)
  - Claude sends the person to `/oauth/login`, where they enter their access code
  - a valid code yields tokens tied to that person's name: a 1-hour access token and a 30-day rotating refresh token, both stored hashed
  - PKCE, discovery, `/register`, `/token` and `/revoke` are served by the MCP SDK

  A raw access code is still accepted as `Authorization: Bearer ecc_…`, for the web page, the API and organizations that have request headers.
- **Why:** this is the only way that works per person in every Claude plan and app. Revoking a code also kills that person's OAuth tokens immediately, because every token lookup checks the code is still active.
- **Alternatives:**
  - bearer header only: works for few organizations
  - token in the URL: the docs forbid it, and it leaks into logs
  - a third-party identity provider: more setup than you asked for

### D34. Access codes are stored as hashes in an environment variable
- **What:** `CERTIFIER_ACCESS_CODES` holds `name:sha256` entries. `certifier-access new NAME` prints a code (shown once) plus the entry to add. To revoke, delete the entry or add the name to `CERTIFIER_REVOKED`, then redeploy.
- **Why:** no database of secrets, nothing sensitive in git, and Render's dashboard is the only admin console needed. Codes use a recognisable `ecc_` prefix with 192 bits of randomness, and are compared in constant time.

### D35. Spend controls
- **What:**
  - **Per person:** 20 new lookups a day (UTC). A subsidiary lookup that also certifies its parent counts as 2. Cache hits are free.
  - **Global cap:** $10 a day, checked before each new lookup and entity search. One lookup already in progress can go past it by up to the $0.50 per-lookup budget.
  - **Errors:** plain messages saying which limit was hit and when it resets. They return HTTP 429 on the web, and a tool error the Claude app shows. A first version wrapped them in a generic "Error executing tool"; a test caught it.
- **Local use:** Claude Desktop over stdio, with no signed-in person, has no limits and no cache, as before.

### D36. A 30-day cache per entity, with refresh
- **What:** the cache key is the normalized name, the website host, and the CIK and parent CIK. It stores the full lookup result, so the card and record rebuild exactly. A cached result carries a note: "Cached certification from <date>; ask for a refresh…". Refresh is a tool parameter and a web button.
- **Why:** most repeat questions are for the same companies, so the cache cuts cost the most.

### D37. One service, with the MCP app mounted at the root
- **What:** FastAPI serves `/`, `/api/*`, `/cards/*`, `/oauth/login` and `/health`. The MCP Starlette app is mounted at `/` behind them, so OAuth discovery (`/.well-known/…`) and `/mcp` sit at the origin root, where Claude looks for them. The MCP transport is stateless, so restarts don't break sessions. DNS-rebinding protection is off, because it's meant for unauthenticated local servers and every request here is authenticated. Token audience checking is off too: every token this server issues is only for this server, and an exact-URL comparison risked spurious 401s.

### D38. Render setup
- **What:** `render.yaml` uses the **Starter** plan with a 1 GB disk at `/var/data`, about $7–8 a month.
- **Why:** the free plan sleeps (the first request after idle takes about a minute and can time out the Claude app), and has no persistent disk. Without one, the cache, the daily counts and Claude sign-ins reset on every deploy. DEPLOY.md explains how to run on the free plan with those trade-offs.
- **Also:** uv installs exactly the locked versions, and Python is pinned to 3.12.10.

### D39. Hosted cards are served from `/cards/<file>`
- **What:** in hosted mode the MCP tool returns `card_url` (`PUBLIC_BASE_URL` plus `/cards/…`) instead of a path on the server's disk. File names are checked against a strict pattern.
- **Why:** remote users can't open a server path. The in-chat card still renders from the tool result.

### Open issues (hosting)
- **Not deployed or tested in the real Claude app.** The OAuth flow, MCP over HTTP, limits and cache are tested end to end with a test client, and a real `uvicorn` run answered `/health`, the page, the 401 sign-in challenge and discovery correctly. The real Claude sign-in can only be tested once the service is on Render.
- **Single instance only.** SQLite on one disk suits one Render instance. Scaling out would need Postgres.
- **No admin page.** Today's spend shows on `/health`. Per-person usage is only in the SQLite file.

## Hosted experience: GTM Data Certifier (2026-10-11)

### D40. Taglines
Three candidates:
1. **"Deep sweeps. Certified answers."** (chosen)
2. "Every headcount, sourced and scored."
3. "From public record to certified fact."

- **Why the first:** it carries both halves of the principle. "Deep sweeps" is the fun part, the expedition. "Certified answers" is the sober result. It's short enough for the hero and the browser tab. It lives in one constant (`web.TAGLINE`), so swapping it is a one-line change.

### D41. The brand mark is recreated, not supplied
- **What:** `assets/brand/hyperloop-logo.png` and `hyperloop-mark-small.png` weren't in the repository. `scripts/brand_assets.py` redraws the mark from the lockup PDF:
  - a rounded loop, blue across the top and right, green across the bottom and left
  - a center dot
  - brand colors navy #0A2545, loop blue #599AF5, loop green #3FCF8E

  It writes the SVG, both PNGs and the favicon.
- **On the page:** the header, hero and About panel use the SVG inline, with the dot drawn in the text color, so it stays visible in dark mode.
- **To use the official files:** drop them into `assets/brand/` under the same names; the favicon and the PNG routes serve them as is.

### D42. One page, three static files, no framework
- **What:** `index.html`, `app.css` and `app.js` under `src/certifier/static/`. The server joins them into one stylesheet and one script:
  - `/static/app.css` is the brand tokens, the app styles and the card styles
  - `/static/app.js` is the card renderer and the app
- **Why:** the card renderer is shared with the saved cards and the Claude in-chat card, so the web result is the same card everywhere. That meets "one CSS file, no heavy frameworks".
- **Theme:** follows the device, with a manual toggle remembered in the browser. Animations stop under `prefers-reduced-motion`.

### D43. Progress is real, streamed with server-sent events
- **What:** `POST /api/lookup` returns `text/event-stream` with `start`, `progress` (one per stage), `result` or `error` events, plus a keep-alive comment every 10 seconds. The service calls `progress(stage, message)` as each real step starts:
  1. resolve
  2. SEC and official filings
  3. web sweep
  4. corroboration
  5. scoring
  6. certified
- **Why POST over fetch, not `EventSource`:** the access code travels in the `Authorization` header, never in a URL.
- **Themes:** five expedition themes (Deep Sea Dive, Treasure Map, Galaxy Star-Gazing, Detective's Clues, Frontier Voyage), one picked at random per lookup. Each has its own scene, icons and stage lines. The stage names stay literal, so the fun never hides what is happening.

### D44. Stored queries, results and ratings
- **What:** every new or cached lookup is saved as a query, with the access-code name, the text typed, the entity, the full result and cached or not. "How did we do?" (Great, Good, Okay or Off, plus an optional comment) is saved against that query.
- **Recent lookups:** the last 10, kept only in the browser, as the brief asked.

### D45. Downloads: JSON plus two CSV files
- **What:**
  - **Download JSON:** the full certification record v1.1
  - **Download CSV:** one summary row
  - **Sources CSV:** one row per source, with tier, value, dates, role, section, page and URL
- **Why two CSV files:** a summary and its sources don't fit one flat table without repeating every headline field on every row.

### D46. Cache: shared, 90 days; limits: 10 a day per code
- **Supersedes:** D35's 20 a day and D36's 30 days.
- **Cache:** a certification is reused by anyone for 90 days. The result shows "Certified on [date]" with a Refresh button.
- **What counts:** cached results are free. Refresh runs a new lookup and counts against the limit.
- **Unchanged:** the $10 daily global cap.

### D47. `/health` reveals nothing; details move to `/admin/status`
- **What:** `/health` returns `{"status":"ok"}`. Configuration and spend are at `/admin/status`, which needs an access code.
- **Errors:**
  - every error returns JSON, and unexpected errors never echo internals
  - an Anthropic authentication or permission error shows "Service configuration issue, please try again later." and logs the cause, never the key
  - `PUBLIC_BASE_URL` is validated at startup: it must be https (or http for localhost) with no path, or the service refuses to start with a plain message

### D48. Demo mode for screenshots
`CERTIFIER_DEMO=1` adds `?demo=home|code|confirm|expedition|result|how`, with optional theme, stage, mode and slug parameters. Demo results are served from the saved fixtures, so screenshots cost nothing. It's off in production because the variable isn't set.

## Engine tweaks (2026-10-11)

### D49. A date in the URL is the lowest-priority as-of estimate
- **What:** only when a source has no stated date, no context estimate and no publication date, a `/YYYY/MM/` (or `/YYYY/MM/DD/`) path segment sets an estimated as-of date. The card shows "(estimated from URL)".
- **Effect:** Donor Network West's 2023 sponsorship PDF is now dated 2023-03, stale and no longer a current conflict. Score 2 → 3.

### D50. Post-date changes depend on the anchor's tier (amends D30)
- **Tier 1–2 anchors** (filings, annual reports) are never relabelled or penalized for later changes. The change appears as a yellow note, and the trend area shows directional guidance: "Likely somewhat lower than reported because of [event, date, size]".
- **Tier 3 or lower anchors:**
  - may be labelled pre-adjustment, as before
  - also when the source itself says the figure predates a change it describes (`predates_change`), as with Stripe's "8,500 before the layoffs"

### D51. Directional guidance
Every certification carries `direction`: higher, lower, in line or unknown, with a one-line reason. It's derived in this order:
1. changes after the as-of date
2. the source saying it predates a change
3. the indicated current range
4. the prior same-tier trend: under 3% is "in line"; otherwise "possibly higher or lower if the trend continued"
5. otherwise unknown

It's shown in the "Trend and direction" section with an arrow and the words, never by color alone.

### D52. Scope questions only penalize when they could change which entity is counted
- **Research's split:** research classifies each complexity. Health system, joint venture and affiliate questions stay red flags. Everything else becomes a yellow scope note with no score impact.
- **Subsidiary questions depend on the anchor:**
  - With a tier-1 consolidated filing as the anchor, they're a scope note too. A consolidated filing counts every subsidiary owned at its as-of date.
  - Below tier 1, they stay a flag.
- **Why:** in the first Salesforce rerun, the model flagged Informatica, which Salesforce acquired before the 10-K date, and cost it a point.

### D53. Reruns under the new engine (live, $0.57)

| Organization | Before | After |
| --- | --- | --- |
| Stripe | 8,500, 1/5, no label | 8,500, 1/5, **pre-adjustment** (source says the figure predates the layoffs); direction lower; tracker and LinkedIn disagreements moved from red flags to yellow scope notes |
| Salesforce | 83,334, 5/5, **pre-adjustment** | 83,334, 5/5, no label; direction "likely somewhat lower" because of the February 2026 layoffs (−1,000) |
| Donor Network West | 513, 2/5 (2023 PDF counted as a conflict) | 513, **3/5**; the PDF is dated from its URL and is stale; direction lower (a newer provider figure of about 438) |

The first Salesforce rerun scored 4/5 because of the Informatica flag. D52 fixed that, and the second rerun is the one recorded. Fixtures and the cards in `outputs/` are updated.

### Open issues (this round)
- **Not deployed.** The feature branch is pushed; main is untouched until you review the screenshots.
- **Official logo files.** D41 recreated the mark; swap in the originals if they differ.
- **Rating and spend admin page.** Data is stored, but there's no page yet (FEEDBACK.md).
- **Research is non-deterministic.** Salesforce's corroborating source and its event list varied between the two reruns. Scores were stable once D52 was in place.

## Additions: decision-ready result, source labels, fact sheets (2026-10-12)

### D54. Policy change: the Corporate Fact Sheet is a primary source (tier 2)
- **What:** a company's official Corporate Fact Sheet (a "fact sheet" or "company facts" page or PDF) is tier 2. It ranks right behind the 10-K, 20-F, 40-F and annual financial reports, alongside non-financial annual and regulatory reports, and above every website, press release, LinkedIn and third-party source.
- **No date at all:** with no as-of, publication or modified date, it drops to tier 3. The source carries a note saying why, and its tier rationale says "undated, so one tier lower".
- **Enforcement:** the engine enforces this (`policy.yaml` → `fact_sheet`), not the model. Research reports `document_type: fact_sheet`, and the engine sets the tier, whatever tier research suggested.
- **Tests:** a fact sheet beats a press release and the website; it ranks behind the 10-K; an undated fact sheet drops to tier 3.
- **Also updated:** SPEC.md and the "How certification works" panel.

### D55. Two-level source labels on every source
- **What:** every source carries a `source_category` (9 plain-English groups) and a `source_type` (exactly what it was, e.g. "10-K", "IRS Form 990", "News: Payments Dive", "Data Provider: Revelio Labs"). They appear in the record (v1.2), the JSON, both CSV files and the card, shown as "Tier 1 · Financial Filing · 10-K".
- **How:** the mapping is deterministic (`taxonomy.py`):
  - SEC sources take their form from the EDGAR filing itself, and Form 990s from the ProPublica reader
  - research reports a document type and publisher
  - anything still unknown is inferred from the tier and URL
- **Test:** fails if any combination of tier and document type, or any fixture source, lacks a category, type or explanation.
- **Additions to the list you gave:**
  - "SEC Annual Filing", for an sec.gov filing whose form wasn't recorded (older saved results)
  - "Annual Comprehensive Financial Report (ACFR)", for governments
  - "Non-Financial Annual Report" and "Company Document", for tier 2–3 documents that aren't fact sheets or press releases
  - "Web Page: [site]", for unranked pages

### D56. "What is this source?" glossary in an editable file
`source_glossary.yaml` (repo root) holds a 2–3 sentence explanation per source type, plus a one-line description per category. Each explanation says what the source is, who publishes it, how it's regulated or produced, and why it ranks where it does. The card shows it under "What is this?", and the "How certification works" panel lists the whole glossary by category. Editing the file changes both, with no code change. Typed names such as "News: Reuters" use the generic "News" entry unless an exact entry is added.

### D57. Decision-ready result, top-down
- **Answer block:**
  - the count, range, as-of date and confidence
  - the key source label
  - a **Bottom line** mapped to confidence: 4–5 "Ready to use. Strong, current primary source."; 3 "Usable. Note the range and the as-of date."; 0–2 "Directional only. Verify before updating records."; no figure "No certified figure."
  - **Copy for CRM:** a seven-line plain-text block with the count, as-of date, confidence, source label and URL, a one-line rationale, and the policy version
- **"Why you can trust this" strip:** key source and tier, as-of date, independent confirmations, adjustments to the count, and items needing attention (red findings). Each one jumps to its detail.
- **Trend and forecast:** directly below, with labelled axes, reported points solid, estimates hollow, the forecast as a shaded band and the indicated current range as a dashed box. It also shows the direction label with its reason, and the **next expected update**: from the key source's as-of date plus the typical filing lag (10-K +60 days, 20-F +120, Form 990 about +10 months, and so on), or a note that the source has no fixed schedule.
- **Below that:** findings, then the key source, sources, adjustments, and events with the LinkedIn check.

### D58. Findings grouped by what they mean for the reader
- **Groups:**
  - **Affects the answer:** changed the number or the confidence
  - **Worth knowing:** no effect on the answer
  - **Background:** technical detail, collapsed by default
- **Each finding:** a plain headline, an impact chip ("Lowered confidence by 1", "Adjusted count −1,100", "No effect on the answer", "Sets starting confidence: 2 of 5"), and a one-sentence **So what**.
- **Validation rejects a finding:**
  - with no impact or so-what
  - whose headline uses internal flag names
  - that changed confidence but isn't in "Affects the answer"
- **Jargon rewritten:** "Complexity:", "Flag:", "tracker", "near-date" and "mirror".
- **Stripe and UC Davis review:**
  - **Problem:** events showed no date, so a 2022 layoff read like a current one being ignored.
  - **Fix:** events are now titled "Earlier change (date)", "Change after the as-of date (date)" or "Change with no known date", each with its own so-what.
  - **Fix:** the direction reason reads "because of a change after the as-of date: …".
  - **Fix:** the trust strip counts only adjustments that changed the count; UC Davis showed "3" for three notes.
  - **Note:** a red finding at the score floor sits in "Worth knowing" with "No further effect (confidence already at its minimum)", because strictly it didn't change the answer. Its red status and so-what still tell the reader to check it.

### D59. Start over, discard, Back
- **Search another company:** the primary button, at the top and bottom of the result. It resets the input, candidates, progress and result, and returns to an empty search box with focus, with no reload.
- **Saving:** every completed result is saved to Recent lookups automatically. **Discard** removes it.
- **Confirm step:** has "Not the right one? Search again", which keeps the query selected.
- **Back button:** each step is a history entry. Back returns to the previous step or result. Leaving a lookup that's in progress cancels it (AbortController). A cancelled lookup isn't charged twice: the server finishes and caches it, so retrying is free.

### D60. "Powered by Claude" as text, not a logo
- **What:** "Powered by Claude · Custom-built MCP service" is a text badge in the footer and the About panel.
- **Why no logo:** a search found no published Anthropic guideline that permits third parties to use the Claude or Anthropic logo, so the default applies. The About panel explains the MCP server and how to add it in Claude: a custom connector, a URL ending in `/mcp`, and sign-in with an access code. The URL is filled in from `PUBLIC_BASE_URL`.

### D61. Drifting sample cards removed from the home page
On review the faint cards looked static (they drifted about 15 px over 26-34 seconds at a fixed faint opacity), so they read as clutter rather than motion. The home page is now the logo, tagline, search, example chips and recent lookups.

### D62. Visual round: softer card, label/value facts, a findings log, and some fun
- **Answer:**
  - the count ticks up once, and a rubber-stamp seal (Certified, Supported, Estimated, Unverified) lands beside it
  - the stamp is green, amber or red, matching the bottom line; sparkles show for 4-5
  - a facts table follows, with labels on the left and values on the right: Employees, Range, As of, Confidence, Key source, Found in, Direction, Known change, Newer data, Next update
- **Findings:** a one-line log per item, with a status symbol (check, !, x, plus screen-reader text), the headline and its so-what inline, and a short impact chip on the right ("-1 confidence", "base 4/5", "no effect"). Click a line for the full rationale and evidence.
- **Softer look:** larger radii, lighter borders and soft shadows, section headers with line icons and a chevron, and a loop-gradient confidence meter that fills in. Sections fade in once.
- **Expedition:** a hyperloop track whose pod, styled on the mark, travels the stages. The result carries the expedition's sign-off ("Surfacing with a certified answer · Deep Sea Dive"). A loop-gradient line sits under the header.
- **Motion:** every animation stops under prefers-reduced-motion. Demo screenshots render the settled state; phone screenshots use a real 390 px viewport via Playwright and the installed Edge.

### D63. Mission line
"Giving you transparency & trust to take real action" sits under the tagline on the home page and opens the About panel. It uses the accent color rather than a green-blue gradient, because loop green on white fails contrast (about 2:1).

### D64. Hotfix: extraction schema too large for the API (production outage)
- **What happened:** D55 added a 17-value `document_type` enum and an optional `publisher` to the extraction schema. The API compiles strict structured-output schemas into a grammar, and this one passed its size limit. Every new lookup failed at the extraction step with 400 "compiled grammar is too large" (the Disney report).
- **Fix:**
  - `document_type` is a plain nullable string, normalized in code
  - `publisher` is gone; it comes from the URL
  - probes against the live API showed the schema sits right at the limit: either field alone compiles, both don't
- **Guards:**
  - an offline test fails on any enum over 8 values or any optional field in the schema
  - a live test (`RUN_LIVE=1 pytest tests/test_live_schema.py`, near-zero cost) compiles the real schema; run it before shipping any schema change
- **Verified:** live with Disney: 231,000, 4/5, Tier 1 · Financial Filing · 10-K, $0.19.
- **Headroom:** there's little left. Adding extraction fields will need room made first, e.g. by turning date fields into strings.

### D65. Confirm page shows its progress; double submits can't race
"Finding '<query>'..." now shows at once, with the hyperloop pod sweeping and an elapsed timer, until the matches arrive. Then it says "Found N matches for ...". Only the latest search may render, and the same search can't start twice. Before this, Enter plus a click could show 2 matches and then replace them with 4.

### D66. The home page says it certifies employee count
Pills above the search box read **Employee count** (selected), then Revenue, Hierarchy, Industry and Address, greyed out with a "soon" tag. Clicking one says it's coming soon. The button reads "Certify employees" ("Certify" on phones, where the pills carry the meaning). Pills keep every option visible without opening a menu, which a dropdown wouldn't.

### D67. Interactive flows are now tested in a real browser
A Playwright script clicks through the demo with the installed Edge:
- Copy for CRM, the trust-strip jumps, expanding a finding and "What is this?"
- Search another company, Back, Discard and Search again
- the finding state, the soon pills, and no page errors

It found one bug: Back after "Search another company" no longer restored the result. Fixed by keeping the last result for history.

## Open beta access (2026-10-12)

### D68. No codes for visitors; allowances keyed on a hashed IP
- **What:** anyone with the link can search. The allowance key is built in two steps:
  1. a keyed hash of the client IP, an HMAC with a server secret (`CERTIFIER_HASH_SECRET`, or one generated and kept in the database)
  2. that hash, salted with a random value for the Pacific day; earlier days' salts are deleted

  The IP itself is never stored.
- **Client IP:** the entry `CERTIFIER_PROXY_HOPS` (default 1) from the right of `X-Forwarded-For`. Proxies append, so entries further left are client-supplied and can be spoofed.
- **Not verified:** how many proxies Render puts in front of the service. `/admin` shows your own IP as the service sees it, masked, so you can check after deploying and adjust.

### D69. Reservations make both caps hard
- **What:**
  - Before each lookup, the per-lookup maximum ($0.50, `max_cost_usd_per_lookup`) is reserved against the visitor's $2 and the global $5 in one locked SQLite transaction (`BEGIN IMMEDIATE`).
  - Afterwards the reservation is released and only the actual cost is kept, including a failed lookup's partial cost.
  - An entity search reserves $0.10 the same way.
  - A subsidiary plus its parent reserve together, all or nothing.
- **Why it holds:** spent plus reserved never passes either cap, even with lookups in flight at once (tested with 8 threads).
- **Engine change to make the ceiling real:**
  - **Problem:** research used to stop only after crossing $0.50, and extraction then ran on top.
  - **Fix:** research now stops at $0.20 (`research_stop_usd`), leaving room for its last turn and extraction. Typical lookups cost $0.11–0.23.

### D70. Days reset at midnight Pacific
Allowances, salts and the admin's "today" use America/Los_Angeles. `tzdata` is a dependency, so this also works on Windows.

### D71. Free content
- **Cache:** cached results never touch an allowance; they're counted as cache hits for the admin page.
- **Samples:** eight sample results live in `samples/` and are served free from the home page, labelled "Sample result, certified on [date]".
  - Salesforce, Stripe, Gong and Donor Network West are the reviewed fixtures.
  - Adobe (31,360, 4/5), Workday (21,000, 4/5), NextEra Energy (17,400, 5/5) and UC Davis were certified live in this run.
- **UC Davis:** it needed the IPEDS reader (D73) and was certified again after it was built.
- **Visibility:** visitors see "About N searches left today". The estimate is remaining dollars divided by a typical $0.20, and dollars are never shown.

### D72. Connector: guest sign-in bound to the browser's IP; admin codes
- **What:** the connector sign-in page has one button, **Continue as beta guest**. The page runs in the person's own browser, so its IP's keyed hash becomes the token subject (`ip:<hash>`). Connector lookups then draw on that IP's daily allowance, shared with the website. Reconnecting from the same IP gives the same key, so the allowance doesn't reset.
- **Admin codes:** your existing access codes became admin codes (`CERTIFIER_ACCESS_CODES`). They bypass both caps on the web, through `/admin` in the browser, and on the connector (sign-in page → "Have an admin code?").
- **Messages:** limit messages reach Claude exactly as written, returned as an error result instead of the SDK's "Error executing tool …" wrapper.
- **Privacy:** a guest token keeps the keyed hash (not the IP) for its 30-day life. The privacy note says so.

### D73. IPEDS reader (UC Davis, your example)
- **What:** for organizations that look like a college or university (by name, or a `.edu` site):
  - College Navigator's search finds the IPEDS unit ID by exact name
  - the institution profile's JSON API (Human Resources) supplies "All staff (excludes graduate assistants)", column Total, from the latest fall collection
  - it's recorded as tier 2, with an as-of date of November 1 of the fall year and graduate assistants logged as separately reported
- **UC Davis:** 15,029 (Fall 2024), unit ID 110644, with the profile URL as the source.
- **Open question (yours):** UC Davis scores 1/5 because three rules stack:
  1. recency: IPEDS runs about two years behind
  2. the UC Davis Health scope flag
  3. LinkedIn's 21,000, which likely includes UC Davis Health, counted as a conflict

  Not changed here, because it's a scoring-policy call.

### D74. Fair use
- **Concurrency:** one lookup in progress per visitor (in memory; one instance).
- **Rate limit:** 10 API requests a minute per IP, a sliding window in memory with the IP hashed.
  - **Not counted:** page assets, `/health` (Render's health checks), logos, cards, and the MCP and OAuth endpoints.
  - **Why the connector is exempt:** its requests all come from Anthropic's servers, so a per-IP limit would throttle every connector user together. The connector is held by its per-guest allowance and the one-at-a-time rule instead.
- **Admins:** exempt.

### D75. Logos and layout
- **Logos:** company logos appear on the confirm cards, the sample cards and the result header. The server fetches each one once from Google's favicon service (128 px), caches it on disk and serves it from `/logos/<host>.png`, so visitors' browsers never contact a third party.
- **Trend placement:** the trend and forecast chart moved up, directly under the answer, ahead of the trust strip.

### Open issues (beta)
- **`CERTIFIER_PROXY_HOPS` after deploy:** verify it on `/admin` → Proxy check.
- **In-memory limits:** the rate limit and the one-at-a-time rule reset on restart. That's fine for one instance; several would need a shared store.
- **Shared networks:** visitors behind one IP (an office or campus) share an allowance.
- **UC Davis scoring:** see D73.

## Scoring decisions (2026-10-12, yours)

### D76. The latest IPEDS release counts as current
- **What:** `recency.latest_release_current` in `policy.yaml` lists lagging official source types with the days from as-of
  to the next release (IPEDS: 765, so staff as of Nov 1 are superseded about 25 months later), plus a 60-day grace.
- **While it's the latest release:** no recency penalty, never stale, and it keeps the corroboration bonus. A note and a
  green finding give the as-of term and when the next release is due. The record's "Next update" uses the same number.
- **Also:** no growth adjustment for such a source. The live UC Davis rerun showed why: Revelio figures of about
  20,000–21,000 (likely including UC Davis Health) otherwise moved IPEDS's 15,029 to a 19,000 estimate. The latest
  release is current, so there's no lag to correct, and that gap belongs to the scope question.
- **Not applied to Form 990:** you described this as "the same approach as Form 990", but Form 990 has no such allowance
  today. Donor Network West still takes the recency −1 (513, 3/5). Adding `form_990: <days>` to the list would give it
  the same treatment; left for you to decide.

### D77. One root cause, one penalty
- **What:** with an open entity scope question, a LinkedIn figure (company description or member count) *above* the
  certified figure is attributed to that question. It's recorded in `explained_flags` and shown as a linked finding,
  "No extra penalty (same cause as F#)". The scope finding keeps the −1 and notes "Related: F#".
- **Still penalized:** a LinkedIn figure below the certified count, and any LinkedIn gap with no open scope question.

### D78. Health-system "so what"
The scope flag stays (−1). Its "so what" reads: "The campus figure likely excludes health-system staff, so the
full-organization count is likely higher; use the campus figure only if that's the organization you mean."

### UC Davis rerun (live, $0.12; $0.14 for the earlier run that exposed the growth issue)

| | Before | After |
| --- | --- | --- |
| Count | 15,029 (IPEDS, Fall 2024) | 15,029 (reported) |
| Score | 1/5 Unverified | **3/5 Supported** |
| Breakdown | 4 − 1 health system − 1 LinkedIn conflict − 1 recency | **4 − 1 health system** |
| LinkedIn description 21,000 and 17,847 members | penalized | linked to the health-system finding, no extra penalty |
| Bottom line | Directional only | Usable. Note the range and the as-of date. |
