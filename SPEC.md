# Employee Count Certifier — MVP Spec

Policy version: 0.2 · Owner: Matt Beltrano · Oct 2026

## Purpose and MVP scope

The tool returns a certified global employee count for one company: the number, the policy tier it came from, the source excerpt and date, a rationale, and a confidence level. It runs as a remote MCP server (usable from the Claude app) and as a web page, both calling one engine.

**MVP (build first):**

- Single-company lookup, with entity confirmation before research
- Tiers 1–6 and publicly visible tier 7–9 data (see feasibility flags)
- JSON certification output
- Local MCP server, then remote MCP server

**Later:** web page, Excel and slide exports, trend and forecast, batch upload of territory lists, example library.

## Source hierarchy

The engine always takes the highest-ranked available source, except where an exception rule applies. Tier 1 is highest.

| Tier | Class | Source | Requirement | Examples |
| --- | --- | --- | --- | --- |
| 1 | Primary | 10-K or annual financial report | Formal, dated, company-published | 10-K Item 1 "Human Capital" or "Employees": "As of [date], we employed X people" |
| 2 | Primary | Non-financial annual or regulatory report | Formal, dated, company-published | Private-company annual report; university IPEDS staff filing; nonprofit IRS Form 990 |
| 3 | Secondary | Formal press release or company-published document | Company-published; dated by the release | "About [Company]" boilerplate, or a headcount stated in the release body |
| 4 | Secondary | Company website description | Traceable to the company; often undated | About Us / Company pages, preferred over deep or hidden pages |
| 5 | Secondary | LinkedIn company description | Company-set text, not member count; often undated | "with more than 4,500 employees across the globe" |
| 6 | Secondary | Reputable third-party article quoting an executive | Named executive, reputable outlet | Financial Times, New York Times, recognized industry publication |
| 7 | Tertiary | Best-of-breed data enrichment providers | Global or regional market leader | ZoomInfo, Dun & Bradstreet, Apollo; Firmable (AU/NZ) |
| 8 | Tertiary | Specialty sources | Reputable data representation and sourcing | Crunchbase, PitchBook, Reuters, Bloomberg, S&P Global, or similar |
| 9 | Unranked | Other data providers and non-reputable news | None; supporting evidence only | Any source not in tiers 1–8 |

**Class definitions:**

- **Primary:** formal, dated, and published by the company itself.
- **Secondary:** verifiable back to the company, but less frequent, more generalized, and often without a clear as-of date.
- **Tertiary:** third-party enrichment providers and data aggregators.
- **Unranked:** any other provider or news source.

## Counting rules

The target is one number: global headcount of the whole legal organization, all worker types included.

1. **Worker types.** Include full-time, part-time, seasonal, contingent, and any other defined worker type the company counts. Exclude independent contractors who are not formal employees. Test: a worker on the company's books or payroll, directly or through a contingent supplier, counts; one not on its books does not. When a source includes contractors and states their number, subtract it. If the source gives no breakdown, assume the stated figure is the full count. If it reports types separately and gives no total, sum them.

   **Formally reported totals are accepted as stated.** When a formal report states a total under a standard definition (IPEDS "Total all staff", Form 990 line 5, a 10-K headcount), certify that total. Don't add categories it reports separately (e.g., IPEDS graduate assistants). Log them as notes with their count. The same definition applies across all reporting entities, which keeps results consistent and comparable. An entity that relies heavily on such workers usually includes them in its own total.
2. **Geography.** Use the global count, not a single country or region.
3. **Entity scope.** Include all wholly controlled subsidiaries under the legal parent. Exclude partially owned entities. Assume a reported figure covers the full group unless the source says otherwise.
4. **Qualified figures.** For "more than 5,000", "over 5,000" or "approximately 5,000", record the reported value as 5,000 and store the qualifier (`more_than`, `approximately`, `up_to`). Only the calculation, estimate and forecast logic may adjust it.
5. **Value types.** Every value is flagged as `reported` (taken as posted), `calculated` (derived from minimally sufficient sources), or `estimated` (best-effort inference from thin evidence, e.g., comparison to similar organizations; forecasts also fall here).

**Transparency.** Every adjustment is logged with the source figure, what was added or subtracted, why, and the resulting value. Example: "10-K reports 12,400 including 1,100 independent contractors → 11,300 certified." Nuances found in a source (definition used, excluded regions, seasonal peak vs. year-end) are recorded the same way, even when no adjustment is made.

## Selection and corroboration

The highest available tier sets the certified value; other sources only corroborate it, bound it, or fill gaps.

1. Search all tiers, top down. Collect every candidate with its URL, tier, as-of date, excerpt and qualifier.
2. Target 2–3 corroborating sources. These may be the same tier (e.g., three years of 10-Ks) or different tiers.
3. The certified value is the highest-tier candidate. Exceptions apply only under the rules below.
4. If the best source is tier 7 or lower, derive a value instead of picking one: combine all tertiary sources, the LinkedIn member count, the LinkedIn size range, and their averages and spread. Flag the result `calculated` when sources are minimally sufficient, otherwise `estimated`.
5. Run the LinkedIn sanity check (next section) on every result.
6. Assign a confidence level and a range.

**Exception and recency rules:**

- A secondary source (tiers 3–6) may override a primary source (tiers 1–2) only when the primary source is more than 24 months old.
- A tertiary or lower source (tiers 7–9) never overrides a primary source. It rarely overrides a secondary source; normally it only moves a secondary value toward a calculated or validated figure.
- Dated secondary and tertiary sources older than 24 months are supporting evidence only. Undated sources are allowed but noted as undated.
- Only a dated secondary source with a newer as-of date may override a stale primary source. An undated secondary source cannot show that it's newer, so it doesn't override.
- Within a tier, the newest as-of date wins. Dated beats undated.
- **Prefer the more specific figure when it's in line.** When sources share a tier and as-of date, the most specific figure wins: exact before qualified, then more significant digits (112,234 before "more than 110,000"; "approximately 112,200" before "over 100,000"). It must be in line with every rounder statement: within 15%, at or above X for "more than X", and at or below X for "up to X". The rounder statement then corroborates it. If the detailed figure isn't in line, the headline statement is used, the detailed figure is recorded as a conflict, and the result is flagged for review. Examples: SAP, Novo Nordisk.
- Ages are measured from the as-of date to the lookup date. A source with no as-of date uses its published date for recency but is still marked undated.
- Figures for one region or a partial scope never set the certified value. They are recorded as supporting evidence only.
- Figures with a broader scope (covering bodies outside the entity, such as a city figure that includes the school system) never set the value either. They are logged as notable with the variance from the certified value.

**Growth adjustment (examples: Gong, Donor Network West).** A figure is treated as outdated when LinkedIn shows the organization has outgrown it, provided it is one of these:
- a tier 3–6 figure that is undated or more than 12 months old
- a tier 2 figure more than 18 months old, because Form 990 and IPEDS lag

Tier 1 is never adjusted. That takes both of these:
- The member count exceeds the figure by at least 15%.
- LinkedIn headcount growth is at least 10%: the one-year figure, or the two-year figure if the one-year is missing.

The value is then moved conservatively toward the member count: stated + 75% × (members − stated), rounded to two significant digits. The range runs from the stated figure to the midpoint of the LinkedIn implied range. The result is `estimated` with qualifier `approximately`, and scores Supported (3). Gong: the website says 1,500, LinkedIn has 2,137 members and shows 27% one-year growth, so the result is ~2,000 with a range of 1,500–2,300. All parameters are in `policy.yaml` under `growth_adjustment`. Open: applying the same logic to declining headcount, and using an organization's own filing trend (e.g., successive 990s) as the growth signal when no LinkedIn data exists.

**Confidence levels:**

| Score | Level | Rule |
| --- | --- | --- |
| 5 | Certified, corroborated | Meets Certified, and at least one other source agrees within 15% |
| 4 | Certified | A single tier 1–2 source whose as-of date (not the release date) is within 18 months |
| 3 | Supported | Tier 1–2 with an as-of date older than 18 months or undated; tier 3 with or without corroboration; or tier 4–6 with corroboration within 15% |
| 2 | Estimated | Tier 4–6 without corroboration, or best evidence is tier 7–9 from two or more sources within 30% of each other |
| 1 | Unverified | One tier 7–9 source only, or tier 7–9 sources disagree by more than 30% |
| 0 | Unattained | No usable source found |

**Confidence adjustments** (each lowers the score one level, never below 1):

- The LinkedIn check flags the certified value (see below).
- A non-stale tier 1–6 source disagrees with the certified value by more than 30%. Tier 7–9 sources that disagree with a tier 1–6 value are recorded but do not lower confidence.
- An event-driven case (merger, acquisition, spinoff) is flagged.

**Corroboration** means any other source, of any tier and including an earlier filing of the same type, whose value is within 15% of the certified value. Stale and undated sources may corroborate. Regional or partial-scope figures may not.

## LinkedIn sanity check

The LinkedIn member count is a flag, not a hard floor. The true headcount is usually at or above it; how far above depends on how white-collar the workforce is. Member counts include former employees who haven't updated their profiles, contractors, and mis-tagged profiles, so a certified value below the member count is flagged, never rejected or overridden.

| Workforce profile | Members as % of true headcount | Implied true headcount |
| --- | --- | --- |
| White-collar (e.g., software) | 90–95% | member count × 1.05–1.11 |
| Mixed | 50–90% | member count × 1.1–2 |
| Blue-collar (e.g., manufacturing) | 25–50% | member count × 2–4 |

- Default ratio: 0.3–1.0 LinkedIn members per employee, set by industry classification and white- vs. blue-collar mix. Calibrate it against public companies whose 10-K headcount is known, and keep it in a config table tuned over time.
- The LinkedIn size range (e.g., "5,001–10,000") is company-set evidence, but often stale. It counts as one corroborating data point, never the certified value.
- The check returns a status:
  - `pass`: the certified value is inside the implied range.
  - `flag`: the value is below the member count or outside the implied range. Confidence drops one level.
  - `not_available`: no member count was found. Confidence is unchanged.
- The size range is recorded as agreeing or not. It never changes the status.
- When LinkedIn was an input to the value (growth adjustment or tier 7–9 derivation), a `flag` is still reported but does not lower confidence, because LinkedIn isn't an independent check in that case.
- LinkedIn Insights headcount growth (6 months, 1 year, 2 years) is captured when visible. It drives the growth adjustment, and later the trend.
- Workforce profile is `white_collar`, `mixed`, or `blue_collar`. The default is `mixed` when the industry is unknown.

## Entity validation

No research runs until the user confirms which entity they mean.

1. User provides a company name and, ideally, its website URL.
2. Engine resolves candidates and shows each with logo, website, a one-line description, and HQ location.
3. If the company looks like a subsidiary, or several entities match, the engine also shows the global parent and asks which one the user wants.
4. User confirms. The engine processes the confirmed entity **and** its global parent, and returns both certifications.

In the Claude app, Claude asks the confirmation question in chat. On the web page, it is a confirmation screen before results.

### Entity groups (example: university and health system)

Some organizations report their parts separately. A university files IPEDS for the school only, while its health system and other affiliates report elsewhere. Treat these like a parent and its subsidiaries, and return a separate, clearly labelled entry for each figure found:

| Entry | Role | Source |
| --- | --- | --- |
| Grand total | All known entities (school, health system, others) | An aggregate figure if one is published; otherwise the sum of the parts, marked `estimated` |
| Institution | The school itself | IPEDS |
| Affiliate | Each affiliate, e.g., the health system | Its own source |

**Which entry is the primary metric:**
- The grand total is primary only when it comes from a tier 1–2 source as reported *and* there is proof the institution wholly owns the affiliates. This is rare, because such institutions often publish no consolidated annual report.
- Otherwise the institution's own count (IPEDS) is primary, and the grand total is a secondary entry. A summed grand total scores one level below its weakest part (minimum 1). Its rationale lists the parts and notes that their dates and definitions differ and that other affiliates may exist.
- The group rationale explains which entry is primary and why, so users see the nuance.

`certify_group` in `src/certifier/group.py` implements this. Finding the affiliates and the ownership proof is part of entity resolution (build step 4).

## Certification output

Every lookup returns one certification record per entity, in this shape. Field names are what the build uses.

| Field | Type | Meaning |
| --- | --- | --- |
| `entity` | object | Name, website, HQ, legal parent, relationship to parent |
| `certified_count` | integer | The certified global headcount |
| `count_type` | enum | `reported`, `calculated`, or `estimated` |
| `qualifier` | enum | `exact`, `more_than`, `approximately`, `up_to` |
| `count_basis` | enum | `headcount` or `fte` (full-time equivalents, kept as stated) |
| `range` | [int, int] | Low and high plausible headcount |
| `confidence_score` | integer 0–5 | Score from the confidence table |
| `confidence_level` | enum | `Certified, corroborated`, `Certified`, `Supported`, `Estimated`, `Unverified`, `Unattained` |
| `policy_tier` | integer 1–9 | Tier of the source that set the value |
| `as_of_date` | date or null | Date the source states the count applies to |
| `sources[]` | list | Every source used: URL, tier, as-of date, published date, verbatim excerpt, value, qualifier |
| `linkedin_check` | object | Member count, size range, workforce profile, implied range, status (`pass`, `flag`, `not_available`) |
| `flags[]` | list | Conditions that lowered confidence or need review (LinkedIn, conflict, event-driven) |
| `adjustments[]` | list | Adjustment and nuance log: source figure, change, reason, result |
| `rationale` | text | Why this value, tier and confidence were chosen |
| `trend[]` | list | Up to 5 dated values, oldest to newest (later phase) |
| `forecast` | object | Next-period value, method, range (later phase) |
| `policy_version` | string | Version of this policy used, for audit |

## Export formats (later phase)

After each result, the user sees both export options and picks one or both.

| Export | Formats | Contents |
| --- | --- | --- |
| Data | CSV, Excel (.xlsx) | One row per entity with every schema field; a Sources sheet with one row per source; a Trend sheet; in batch mode, one row per account |
| Summary | Slides (.pptx, opens in Google Slides), document (.docx or PDF, opens in Google Docs) | One summary page per entity: headline count and confidence, tier, source excerpt and date, rationale, adjustment log, trend chart |

**Design standard for slides and docs:** one consistent template; headline number and confidence badge first; source excerpt shown as a quote with link and date; trend as a chart, not a table; plain fonts and one accent color. Structure comes first: every page answers the same questions in the same order.

**Google formats:** the MVP produces .pptx and .docx, which open directly in Google Slides and Docs. Creating native Google files in the user's Drive requires Google sign-in (OAuth) and is a later phase.

## Trend and forecast (later phase)

The trend shows up to five dated values ending at the current one; the forecast adds a sixth, labeled as an estimate.

- **Trend:** only same-basis dated values (e.g., consecutive 10-Ks). Mixed-tier points are shown but marked.
- **Forecast:** requires at least 3 dated points. Method is a linear trend over the available points, with a range from the historical year-over-year variation. Always flagged `estimated`.
- **Next update date:** for public companies, the expected next 10-K filing date from the fiscal year end.

## Example library (started)

Worked examples improve the engine by being fed into its prompt as references, not by retraining the model. Each example is one YAML file in `examples/`, recording: the case, the confirmed entity, the lookup date, the sources found (tier, URL, as-of date, verbatim excerpt), the expected result (value, qualifier, tier, confidence, and optionally which source is selected), and the lesson it teaches. Tags (`tier-1`, `20-F`, `specificity`, ...) make cases searchable.

**Every example is also a regression test.** `tests/test_examples.py` runs the engine on each file and checks the expected result. Adding a case means adding a file. When a policy change breaks an existing example, either the change is wrong or the example's expected result is updated deliberately.

**How the policy grows:** a reviewed real case that teaches something new becomes an example. If it needs a new rule, the rule goes into this spec and `policy.yaml`, with a test. If it changes how research should look for sources, it goes into `research_guidelines` in `policy.yaml`.

**Coverage to build out:** examples for every tier (1–9), including private companies (tier 2), press releases (tier 3), website and LinkedIn descriptions (tiers 4–5), executive quotes (tier 6), and tertiary-only derivation (tiers 7–9), plus a blue-collar LinkedIn gap, conflicting sources, a stale primary overridden by a newer secondary, and an event-driven case.

## Open decisions and feasibility flags

**Open:**

- **Event-driven exceptions (to define later).** Mergers, acquisitions, spinoffs or other major events that make recent figures obsolete, and companies whose public description of their business is confusing or unusual. Until defined, the engine flags these cases and lowers confidence rather than guessing.

**Feasibility flags:**

- **LinkedIn data.** Scraping LinkedIn violates its terms. The MVP can use only what appears in public search results; member counts may be missing or approximate.
- **Tier 7 providers.** ZoomInfo, Dun & Bradstreet, Apollo and Firmable need paid API access. The MVP treats them as unavailable unless a license is provided.
- **SEC EDGAR.** Free, and the best tier-1 source for U.S. public companies. Requests must include a User-Agent with contact info.
- **Cost and speed.** Expect roughly 30–90 seconds and some API cost per company; batch mode multiplies both.

## Implementation decisions (v0.2)

| Area | Decision |
| --- | --- |
| Models | `claude-sonnet-5-5` for research and extraction. Set in `policy.yaml` under `models`. |
| Budget | Target under $0.50 per lookup. At most 8 web searches per entity. Both set in `policy.yaml` under `budget`. The engine stops searching and certifies with what it has once either limit is reached, and records that it did. |
| Test client | Claude Desktop with a local stdio MCP server. Fall back to Claude Code only if Desktop setup blocks progress. |
| 20-F filers | A 20-F or 40-F is a tier 1 annual financial report, the same as a 10-K. These will be common for international companies. |
| Full annual reports | A company's full annual or integrated report (e.g., SAP Integrated Report) is tier 1, alongside its regulatory filing. Research must look for both, because the regulatory filing often rounds the figure. |
| Form 990 (nonprofits) | Tier 2. The figure is Part I line 5, "individuals employed in calendar year" (W-3 count), and the as-of date is December 31 of that year. It counts everyone paid during the year, so log a turnover nuance. Returns lag 12–24 months. Prior years' line 5 gives a trend. Example: Donor Network West. |
| IPEDS (universities) | Tier 2. The figure is Human Resources "Total all staff", and the as-of date is November 1 of the fall collection. It runs about a year behind. Certify the total as stated. Graduate assistants, which IPEDS reports separately, are noted and not added. Affiliated health systems are generally excluded, so note one when found. Example: UC Davis. |
| Governments (cities, counties, states) | The annual financial report (ACFR) is tier 1. Budget documents are tier 2. Certify the government's own workers without school systems. A figure that includes schools gets scope `broader`: it's logged as notable with its variance and never used as the value. Example: City of Livermore. |
| FTE figures | When a source states full-time equivalents instead of total workers, certify the FTE figure as stated (`count_basis: fte`). Don't estimate upward, and never growth-adjust it. Only a headcount figure from the same tier and as-of date that is in line with it (at or above, within 15%) replaces it. A headcount further away is noted, not flagged, because part-time staff explain the gap. |
| Combined filings | When a parent's 10-K states subsidiary headcounts (e.g., NextEra and FPL), that figure is tier 1 for the subsidiary. |
| Range | The range comes from the qualifier band in `policy.yaml` (exact ±0%, approximately ±5%, more_than +0–10%, up_to −10–0%). Derived tier 7–9 values use the min–max of the inputs. |
| Adjusted values | A figure changed by a counting rule (contractors subtracted, worker types summed) is `calculated`, not `reported`. |
| Minimally sufficient | A derived tier 7–9 value is `calculated` when it has two or more inputs within 30% of each other, and `estimated` otherwise. LinkedIn-implied values count as inputs. |
| Event-driven cases | Not resolved automatically. The research step flags them, and the flag lowers confidence one level. |
| Tertiary overriding secondary | Not automated in the MVP. A tier 7–9 value only corroborates, or is recorded as a conflict. |
| Credentials | `ANTHROPIC_API_KEY` and `SEC_USER_AGENT` are read from `.env`. |

## Build plan

Each step ends with passing tests before the next one starts.

1. **Rule engine (offline).** `uv` project, `policy.yaml`, data models, and the deterministic rules: qualified-figure parsing, counting adjustments, recency, selection and exceptions, tertiary derivation, LinkedIn check, confidence, range, and the certification record. No network calls and no LLM.
2. **SEC EDGAR tier 1 fetcher.** Find the latest 10-K, 20-F or 40-F, extract the employee section, and run it through the engine. Tested against the golden set.
3. **Research and extraction for tiers 2–9.** Claude with web search, under the budget limits, returning candidates in the engine's schema.
4. **Entity resolution and confirmation.** Find candidates, detect the parent, and certify both entities.
5. **Local MCP server.** A FastMCP stdio server tested in Claude Desktop.
6. **Remote MCP server.**

## Golden set (confirmed 2026-10-11)

Expected values come from each company's latest annual filing, pulled on 2026-10-11, and SAP's figure comes from its Integrated Report 2025. Each row is an example file in `examples/`.

| Case | Company | Filing | As of | Expected count | Qualifier | Excerpt |
| --- | --- | --- | --- | --- | --- | --- |
| White-collar | Adobe Inc. | 10-K FY2025 | 2025-11-28 | 31,360 | exact | "As of November 28, 2025, we employed 31,360 people" |
| Blue-collar | Tyson Foods | 10-K FY2025 | 2025-09-27 | 133,000 | approximately | "we employed approximately 133,000 team members globally" |
| Qualified "more than X", detailed report wins | SAP SE | Integrated Report 2025, p. 38; 20-F FY2025 | 2025-12-31 | 112,234 | exact | Integrated Report: 112,234 (verbatim excerpt still to be captured). The 20-F says "employed more than 110,000 people as at December 31, 2025" and corroborates it. |
| 20-F foreign filer | Novo Nordisk | 20-F FY2025 | 2025-12-31 | 69,505 | exact | "reducing the number of employees to 69,505 by year-end". The same filing also says "more than 69,500", which is in line with it, so the exact figure wins. |
| Subsidiary and parent | Florida Power & Light / NextEra Energy | NEE 10-K FY2025 | 2025-12-31 | FPL 9,400; NEE 17,400 | approximately | "FPL had approximately 9,400 employees"; "NEE and its subsidiaries, with employees totaling approximately 17,400" |
| Mixed workforce, part-time included | Costco Wholesale | 10-K FY2026 | 2026-08-30 | 355,000 | exact | "At the end of 2026, we employed 355,000 employees worldwide" |

## Build rules for Claude Code

- Python, managed with `uv`. MCP server built with the official MCP Python SDK (FastMCP).
- Policy values (tiers, recency windows, thresholds, LinkedIn ratios, models, budget) live in `policy.yaml`, not hard-coded.
- Credentials read from `.env` (`ANTHROPIC_API_KEY`, `SEC_USER_AGENT`); `.env` is never committed.
- Build in small steps; write a test for each rule before moving on.
