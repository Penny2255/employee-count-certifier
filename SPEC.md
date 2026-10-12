<sub>© 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See [LICENSE](LICENSE).</sub>

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
| 2 | Primary | Corporate fact sheet, or non-financial annual or regulatory report | Formal, dated, company-published (an undated fact sheet drops to tier 3) | The company's official Corporate Fact Sheet or "company facts" page/PDF; private-company annual report; university IPEDS staff filing; nonprofit IRS Form 990 |
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

**Tier 1 provenance.** A tier 1 figure must come from the filing itself:
- **SEC filings:** a sec.gov URL with an accession number in it.
- **Company-hosted reports:** the organization's own website (e.g., SAP's Integrated Report, a city's ACFR), where no accession number exists.

Copies on other sites (Quartr, aggregators) are mirrors. They can corroborate, but they never set the value. Any organization with an SEC CIK gets its 10-K, 20-F or 40-F from EDGAR directly. If the caller doesn't pass a CIK, the service resolves it from the ticker or from a unique exact name match in SEC's company list. Example: the Salesforce run that read 83,334 from a Quartr mirror.

**Exception and recency rules:**

- A secondary source (tiers 3–6) may override a primary source (tiers 1–2) only when the primary source is more than 24 months old.
- A tertiary or lower source (tiers 7–9) never overrides a primary source. It rarely overrides a secondary source; normally it only moves a secondary value toward a calculated or validated figure.
- Dated secondary and tertiary sources older than 24 months are supporting evidence only. Undated sources are allowed but noted as undated.
- Only a dated secondary source with a newer as-of date may override a stale primary source. An undated secondary source cannot show that it's newer, so it doesn't override.
- Within a tier, the newest as-of date wins. Dated beats undated.
- **Prefer the more specific figure when it's in line.** When sources share a tier and as-of date, the most specific figure wins: exact before qualified, then more significant digits (112,234 before "more than 110,000"; "approximately 112,200" before "over 100,000"). It must be in line with every rounder statement: within 15%, at or above X for "more than X", and at or below X for "up to X". The rounder statement then corroborates it. If the detailed figure isn't in line, the headline statement is used, the detailed figure is recorded as a conflict, and the result is flagged for review. Examples: SAP, Novo Nordisk.
- Ages are measured from the as-of date to the lookup date.
- **Estimated as-of dates.** When a source states no as-of date, one is estimated from context and stored with `as_of_estimated: true`. The estimate comes first from wording found by research ("as of early 2025" → 2025-02-15), otherwise from the publication date, or the modified date when that is later. The estimate is never later than the source's publication date or the lookup date. Every recency rule uses the estimate. A source with no basis for an estimate stays undated.
- Figures for one region or a partial scope never set the certified value. They are recorded as supporting evidence only.
- Figures with a broader scope (covering bodies outside the entity, such as a city figure that includes the school system) never set the value either. They are logged as notable with the variance from the certified value.

**Growth adjustment (examples: Gong, Donor Network West).** A selected figure is treated as outdated, and moved toward a current signal, when current evidence shows the organization has outgrown it. Only these figures qualify:
- a tier 3–6 figure that is undated or more than 12 months old
- a tier 2 figure more than 18 months old, because Form 990 and IPEDS lag

Tier 1 and FTE figures are never adjusted.

The current signal is the first of these two that applies:

1. **LinkedIn growth.** The LinkedIn member count exceeds the figure by at least 15%, and LinkedIn headcount growth is at least 10% (the one-year figure, or the two-year figure if the one-year is missing). The target is the member count. The range runs from the stated figure to the midpoint of the LinkedIn implied range.
2. **Data-provider consensus.** LinkedIn growth figures are rarely public, so this is the usual signal. It needs at least 2 tier 7–9 figures, dated within the last 12 months, within 30% of their median. Figures outside that band are outliers and are ignored. Every figure in the band must exceed the stated figure by at least 15%. A LinkedIn member count within 30% of the same median joins the band as an input. The target is the band's mean. The range runs from the stated figure to the highest figure in the band.

The value moves 75% of the way from the stated figure to the target, rounded to two significant digits. The result is `estimated` with qualifier `approximately`, and scores Supported (3). The adjustment log records the stated figure, the signal used and its inputs.

This is the "normally only moves a secondary value toward a calculated figure" exception for tertiary sources. A data-provider figure never replaces the selected value directly; it only informs the adjustment. When LinkedIn is one of the inputs, a LinkedIn check flag is reported but doesn't lower confidence, because LinkedIn isn't an independent check in that case.

Examples:
- **Gong, by LinkedIn growth (user's reference):** the website says 1,500; LinkedIn shows 2,137 members and 27% one-year growth. Result: about 2,000, range 1,500–2,300.
- **Gong, by consensus (live run, 2026-10-11):** the website says 1,500 (undated). Revelio shows 2,101 (Mar 2026), LeadIQ 2,600 (Aug 2026) and Tracxn 2,672 (Aug 2026); LinkedIn has 2,592 members. Built In's 1,100 is outside the band and ignored. The target is the mean, 2,491, so the result is about 2,200, range 1,500–2,700, Supported (3).

All parameters are in `policy.yaml` under `growth_adjustment`.

Open:
- the same logic for shrinking headcount
- an organization's own filing trend (e.g., successive 990s) as a third signal

**Confidence levels:**

| Score | Level | Rule |
| --- | --- | --- |
| 5 | Certified, corroborated | Meets Certified, and at least one other source agrees within 15% |
| 4 | Certified | A single tier 1–2 source whose as-of date (not the release date) is within 18 months |
| 3 | Supported | Tier 1–2 with an as-of date older than 18 months or undated; tier 3 with or without corroboration; or tier 4–6 with corroboration within 15% |
| 2 | Estimated | Tier 4–6 without corroboration, or best evidence is tier 7–9 from two or more sources within 30% of each other |
| 1 | Unverified | One tier 7–9 source only, or tier 7–9 sources disagree by more than 30% |
| 0 | Unattained | No usable source found |

**Confidence breakdown.** Every record carries `confidence_breakdown`, the steps that sum to the score. Example: `+4 base 4: tier 1, as-of within 18 months`, `+1 corroborated by reveliolabs.com '…87,829…'`, `+0 no deductions`.

**How the score is built.** The breakdown runs base → recency → corroboration → flags:
- **Base:** 4 for tier 1–2, 3 for tier 3, and 2 for tiers 4–6. Derived tier 7–9 values score 2 when calculated and 1 when estimated.
- **Recency (−1):** applies whenever the certified figure's as-of date, estimated or not, is older than 18 months (`recency.certified_max_age_months`). An undated tier 1–2 source also loses one level.
- **Corroboration (+1):**
  - tier 1–2 only when the figure is recent
  - never for tier 3
  - tier 4–6 always
  - never when the certified figure has no as-of date at all

These steps reproduce the confidence table above. The new effect is that tier 3–6 figures now lose a level when old, which is how Stripe went from 2 to 1.

**Confidence adjustments** (each lowers the score one level, never below 1):

- The LinkedIn check flags the certified value (see below).
- A non-stale tier 1–6 source disagrees with the certified value by more than 30%. Tier 7–9 sources that disagree with a tier 1–6 value are recorded but do not lower confidence.
- A merger, acquisition or spinoff that closed *after* the certified figure's as-of date, so the figure can't include it. An event that closed on or before the as-of date, or whose close date is unknown, is noted but not penalized. Example: Salesforce's Informatica acquisition closed on 2025-11-18, before the 10-K's as-of date of 2026-01-31.

**Corroboration** means an *independent* source, of any tier, near the same as-of date, whose value is within 15% of the certified value. These don't count:
- **The same document:** for example, a filing's overview restating its own employee section.
- **Restatements:** for example, Wikipedia, Bullfincher or StockAnalysis repeating the 10-K's figure. This covers any source marked as restating, and any other source with the identical value and as-of date.
- **Other periods:** sources dated more than 9 months from the certified figure's as-of date (`agreement.corroboration_window_months`), such as prior-year 10-Ks. These feed `trend[]` instead.
- **Undated sources:** they can't corroborate, but they can still conflict.
- **Partial or regional figures.**

Nearness is measured from the certified figure's as-of date, estimated or not, and the same check applies to every source. When the certified figure has no as-of date at all, no source can corroborate it, so there's no bonus.

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
  - `pass`: the certified value is inside the implied range. The low end of that range allows members to exceed the count by the profile's tolerance (`linkedin.member_overage_tolerance`: 15% for white-collar, 0% otherwise), because profiles of former employees and contractors linger. Example: Salesforce has 87,523 members against 83,334 certified (+5%), which passes.
  - `flag`: the value is outside that range. Confidence drops one level.
  - The note always starts with the status ("Pass: …" or "Flag: …"), so the two can't disagree.
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

## Certification record (v1.2)

Every lookup returns one standardized record per entity (`src/certifier/record.py`). It has the same 11 sections, always in this order, even when a section is empty. List sections are `{items: [...], none_reason}`, and an empty one must say why. `headline` and `primary_source` carry their own `none_reason` when empty. The shape is flat and export-ready (JSON now; CSV, Excel and slides later).

| # | Section | Contents |
| --- | --- | --- |
| 1 | `entity` | Name, website, HQ, legal parent, relationship in words |
| 2 | `headline` | `count`, `qualifier`, `range`, `count_type`, `count_basis`, `as_of_date`, `as_of_estimated`, `as_of_estimated_from` (`context`, `url` or null), `adjustment_status` (`current` or `pre-adjustment`), `known_changes[]`, `indicated_current_range`, `direction` (`higher`, `lower`, `in_line`, `unknown`), `direction_reason`, `bottom_line`, `next_expected_update`, `next_update_note` |
| 3 | `confidence` | `score` (0–5), `level`, `breakdown[]`, `arithmetic` (e.g., "4 + 1 + 0 = 5") |
| 4 | `primary_source` | Source ID, tier and tier name, `source_category`, `source_type`, `source_type_info`, URL, SEC accession (if any), verbatim `excerpt`, `location`, as-of/published/modified dates, `tier_rationale` |
| 5 | `findings` | Green/yellow/red findings (below) |
| 6 | `sources` | Every source: ID (`S1…`), tier, `source_category`, `source_type`, `source_type_info`, value, qualifier, basis, scope, dates, URL, excerpt, `location`, role, `used`, `tier_rationale`, `use_rationale` |
| 7 | `adjustments` | ID (`A1…`), source ID, source figure, change, result, `rationale` |
| 8 | `trend` | Reported same-basis points (oldest to newest), plus a forecast point marked `estimated` with a low–high range when there are at least 3 points (see Trend and forecast) |
| 9 | `linkedin_check` | Status, member count, size range, workforce profile, pass range, linked finding, `rationale` |
| 10 | `events` | Mergers, acquisitions and spinoffs: description, URL, close date, `penalized`, `rationale` |
| 11 | `methodology` | Policy version, record version, method, models, cost, web searches and fetches, run timestamp, duration, lookup date, queries, notes |

**Source labels (v1.2).** Every source has a `source_category` and a `source_type`, shown as "Tier 1 · Financial Filing · 10-K".

- **Categories:** Financial Filing; Official Company Report; Company Publication; Company Website; Company Social Profile; News (Executive Quote); Data Provider; Specialty Data & Financial Media; Other.
- **Types:**
  - filings and reports: 10-K, 20-F, 40-F, SEC Annual Filing, Annual Report, Annual Comprehensive Financial Report (ACFR), Corporate Fact Sheet, IRS Form 990, IPEDS Filing, Non-Financial Annual Report
  - company publications and pages: Press Release, Company Document, Website: About Us, Website: Other Page, LinkedIn: Company Description, LinkedIn: Member Count
  - third parties: News: [outlet], Data Provider: [provider], Web Page: [site]

The mapping is deterministic (`src/certifier/taxonomy.py`). `source_type_info` is the plain-English explanation from `source_glossary.yaml`, which is editable without code changes.

**Bottom line.** The bottom line is mapped to confidence:
- 4–5: "Ready to use. Strong, current primary source."
- 3: "Usable. Note the range and the as-of date."
- 0–2: "Directional only. Verify before updating records."

`next_expected_update` is when the next edition of the key source is due: its as-of date plus the typical filing lag.

**Findings.** Each finding has an `id` (`F1…`), a `group` (`affects`, `worth_knowing`, `background`), an `impact` chip (e.g. "Lowered confidence by 1", "Adjusted count −1,100", "No effect on the answer"), a one-sentence `so_what`, a `category` (`provenance`, `recency`, `corroboration`, `scope`, `linkedin`, `event`, `definition`, `data_gap`), a `status`, a one-line `title`, a `rationale`, `evidence` (source IDs) and a `score_impact` (e.g., −1 or 0). The rationale is 2–3 plain-English sentences: what we found, why it matters, and what we did about it.
- **Green:** supports the certified figure.
- **Yellow:** a caveat or nuance, with minor or no score impact.
- **Red:** lowers confidence or needs human review.

Findings are generated by rule from the engine's output, not by an LLM. That makes them reproducible and keeps them consistent with the score.

**Rationale rule.** Each of these must carry a rationale of at least one plain-English sentence:
- every source's tier assignment
- every source's use or exclusion
- every adjustment
- every score line
- every event
- the LinkedIn check

Finding rationales need at least two sentences. The confidence breakdown must sum to the score. Every breakdown line, and the LinkedIn check, links to a finding, and every evidence ID must exist among the sources. A record that breaks any of these fails validation and can't be built or loaded.

**Lagging official releases.** For source types listed in `policy.yaml` → `recency.latest_release_current` (today:
IPEDS), the latest available release counts as current until the next release is due (as-of date plus the listed
days, plus a 60-day grace). Until then it takes no recency penalty, is never stale, keeps the corroboration bonus, and
gets no growth adjustment (there is no lag to correct). A green "Latest … release" finding gives its as-of term and
when the next release is expected. After that date the normal recency rules apply. Form 990 is not on the list.

**One root cause, one penalty.** When an entity scope question is open (for example an affiliated health system that
the figure may exclude) and a LinkedIn source (the company description, tier 5, or the member count) reports more than
the certified figure, the gap is attributed to the scope question. It's recorded in `explained_flags` and shown as a
linked finding with "No extra penalty (same cause as F#)"; the scope finding keeps its penalty and lists the related
finding. A LinkedIn figure below the certified count, or one with no open scope question, is still penalized as before.
For a health-system scope question, the "so what" says the campus figure likely excludes health-system staff, so the
full-organization count is likely higher.

**Known changes and newer data.**
- **Known changes:** a confirmed change that took effect after the as-of date, such as layoffs, an acquisition or a spinoff, is listed in `known_changes`. The figure itself is never adjusted. Bids, proposals and rumors are not changes. What else happens depends on the anchor's tier:
  - **Tier 1–2 anchor (filings, annual reports):** never relabelled and never penalized. The change is a yellow note, and `direction` gives guidance, e.g. "Likely somewhat lower than reported because of [event] ([date], [size])".
  - **Tier 3 or lower anchor:** labelled `pre-adjustment`. A material change, more than 15% or of unknown size, also lowers confidence one level under the event rule. A source that says its own figure predates a change it describes (`predates_change`) is also labelled `pre-adjustment`.
- **Direction:** every record says whether the true current headcount is likely higher, lower, in line or unknown, with a one-line reason. It's derived in this order:
  1. changes after the as-of date
  2. a source saying it predates a change
  3. the indicated current range
  4. the prior same-tier trend: under 3% means "in line"
  5. otherwise "unknown"

  The card shows it in "Trend and direction" with an arrow and words.
- **As-of date from the URL:** the lowest-priority estimate. Only when a source states no date, has no date in context and no publication date, a `/YYYY/MM/` path segment sets an estimated as-of date, shown as "(estimated from URL)".
- **Scope notes:** a scope question only lowers confidence when it could change which entity is counted:
  - an affiliated health system, joint venture or affiliate: a red flag
  - a subsidiary when the anchor is not a tier-1 consolidated filing: a red flag
  - anything else is a yellow `scope` finding with no score impact, including data disagreements, tracker coverage, and subsidiaries already included in a consolidated filing
- **Indicated current range:** newer tier 7–9 figures that diverge from an old certified figure are shown as an `indicated_current_range`, marked context only. This applies when:
  - the certified figure is at least 12 months old
  - the newer figures are dated at least 3 months after it and within the last 12 months
  - outliers more than 30% from the median are left out
  - the remaining figures' mean differs from the certified figure by at least 5%

  The range never replaces the certified value.

**Location.** Every source, and the primary source, carries a `location`:
- `section`: where the figure sits, e.g. "Item 1. Business › Human Capital Management" or "Form 990 › Part I (Summary) › line 5"
- `page` and `page_label`: e.g. "printed page 10", "page 22 of the HTML filing", "Form page 1", "PDF page 5", or "no page numbers"
- `detailed_excerpt`: the verbatim passage around the figure, usually the quote's sentence plus one on each side; the card highlights the exact quote inside it
- `deep_link`: a URL with a `#:~:text=` fragment that scrolls to the quote in browsers that support it
- `note`: how the location was found, or why the section or page is unknown

How each kind of source is located:
- **SEC filings:** the filing is split at its page breaks. The printed page number comes from the page footer, with the page's position in the HTML filing as a fallback. The section comes from the nearest preceding ITEM heading and sub-heading. This is read from the filing itself and overrides anything the research step reported.
- **Form 990:** Part I, line 5, on page 1 of the return.
- **Company websites:** the page and its statistics, rewritten as readable "Label: value" pairs. Web pages have no page numbers.
- **Other pages and PDFs found by research:** the section heading and page number come from extraction.

**Location rule.**
- Every source needs an http(s) URL and a detailed excerpt.
- A missing section or page needs a `note` saying why.
- The primary source needs a location, and either its verbatim quote or an explicit `excerpt_missing_reason`.

A record that breaks any of these fails validation.

**Card.** Each record renders as a company card (`src/certifier/card.py`): a self-contained HTML file saved under `outputs/`, and an MCP App (`ui://employee-count-certifier/card`) in hosts that support MCP Apps. Status always shows an icon and a label with its color (✓ Green, ! Yellow, ✕ Red).

### Engine certification (internal)

The engine's `Certification` object, which the record is built from, has these fields:

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
| `confidence_breakdown[]` | list | The base score and each adjustment, with points and reason, summing to `confidence_score` |
| `policy_tier` | integer 1–9 | Tier of the source that set the value |
| `as_of_date` | date or null | Date the source states the count applies to |
| `as_of_estimated`, `as_of_from_url` | boolean | The as-of date is estimated (from context, publication date or, last, the URL) |
| `pre_adjustment` | boolean | A known change took effect after the as-of date (tier 3+ anchors only) |
| `direction` | object | `direction` (`higher`, `lower`, `in_line`, `unknown`) and `reason` |
| `scope_notes[]` | list | Scope remarks that can't change the entity counted (no score impact) |
| `explained_flags[]` | list | LinkedIn gaps explained by an open scope question: (flag, the scope flag it shares a cause with); no penalty of their own |
| `indicated_range` | object or null | Newer tier 7–9 figures shown as context, never certified |
| `sources[]` | list | Every source: URL, tier, as-of/published/modified dates, verbatim excerpt, value, qualifier, role and `role_reason` |
| `linkedin_check` | object | Member count, size range, workforce profile, implied range, status (`pass`, `flag`, `not_available`) |
| `flags[]` | list | Conditions that lowered confidence or need review (LinkedIn, conflict, event-driven) |
| `adjustments[]` | list | Adjustment and nuance log: source figure, change, reason, result |
| `rationale` | text | Why this value, tier and confidence were chosen |
| `trend[]` | list | Up to 5 dated values with the same tier and basis (e.g., consecutive 10-Ks), oldest to newest, ending at the certified figure |
| `events[]` | list | Each event with its close date, whether it was penalized, and why |
| `forecast` | object | Not used: the forecast is a `trend` point marked `estimated` in the record |
| `policy_version` | string | Version of this policy used, for audit |

## Hosted experience (GTM Data Certifier)

The web app at `/` is a single page (`src/certifier/static/`), branded GTM Data Certifier by Human in the Hyperloop. Principle: radically simple; fun in the process, sober results.

- **Home:** a search box, three example chips, and recent lookups (last 10, in this browser only). The access code is asked for only when needed, then remembered in the browser.
- **Confirm:** entity cards ("Which one do you mean?"). One lookup covers one organization.
- **Expedition:** live progress over the real stages (resolve, SEC and official filings, web sweep, corroboration, scoring, certified), streamed as server-sent events, in one of five themes: Deep Sea Dive, Treasure Map, Galaxy Star-Gazing, Detective's Clues, Frontier Voyage.
- **Result:** the certification card, with "Key Source". A cached result shows "Certified on [date]" and a Refresh button. Downloads: JSON (record v1.1), summary CSV, sources CSV. "How did we do?" (Great, Good, Okay or Off, plus a comment) is stored with the query.
- **Panels:** How certification works (the source hierarchy, confidence scale and principles, without thresholds or prompts), About, Privacy.
- **Rules (open beta):**
  - no codes for visitors; single lookups only
  - each visitor has $2 a day of lookup spend, keyed on a daily-salted hash of their IP and shown as "About N searches left today"; a $5 daily hard cap across everyone
  - the per-lookup maximum is reserved against both before each lookup and the unused part released, so neither cap is exceeded; days reset at midnight Pacific
  - a shared 90-day cache and eight sample results, all free; Refresh counts as a new lookup
  - one lookup in progress per visitor; 10 API requests a minute per IP
  - the Claude connector signs in with "Continue as beta guest" and shares the allowance of the IP it signed in from
  - admin codes bypass the limits and open `/admin` (spend, lookups, cache hits, visitors, limit hits, ratings)
  - queries, results and ratings are stored for quality review
- **Endpoints:** `/health` returns only `{"status":"ok"}`. `/admin/status` (access code required) shows configuration and spend. Every error is JSON. `PUBLIC_BASE_URL` is validated at startup.
- **Accessibility:** works with a keyboard and a screen reader, status is never shown by color alone, motion stops under `prefers-reduced-motion`, and light and dark themes follow the device, with a toggle.

Screenshots of every screen are in `docs/screenshots/`.

## Export formats (later phase)

After each result, the user sees both export options and picks one or both.

| Export | Formats | Contents |
| --- | --- | --- |
| Data | CSV, Excel (.xlsx) | One row per entity with every schema field; a Sources sheet with one row per source; a Trend sheet; in batch mode, one row per account |
| Summary | Slides (.pptx, opens in Google Slides), document (.docx or PDF, opens in Google Docs) | One summary page per entity: headline count and confidence, tier, source excerpt and date, rationale, adjustment log, trend chart |

**Design standard for slides and docs:** one consistent template; headline number and confidence badge first; source excerpt shown as a quote with link and date; trend as a chart, not a table; plain fonts and one accent color. Structure comes first: every page answers the same questions in the same order.

**Google formats:** the MVP produces .pptx and .docx, which open directly in Google Slides and Docs. Creating native Google files in the user's Drive requires Google sign-in (OAuth) and is a later phase.

## Trend and forecast

The trend shows up to five reported values ending at the certified one, then a four-year forecast, each forecast
point labeled as an estimate.

- **Trend:** same-tier, same-basis dated values, such as consecutive 10-Ks. Five annual filings are read from SEC EDGAR
  (including EDGAR's older submission pages) and five years of Form 990s. Research is asked for the prior 3–4 years
  from the same kind of source for organizations without filings.
- **Forecast:** needs at least 3 reported points. It's a linear trend projected 4 years ahead. The range starts from the
  historical year-over-year variation and widens with the square root of the years ahead. Always flagged `estimated`.
- **Chart:** a smooth monotone line with value labels, the certified point ringed, and a dashed forecast inside a
  widening shaded band. On phones only the first, certified and final forecast points are labeled.
- **Next update date:** when the next edition of the key source is expected (e.g. the next 10-K).

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

1. **Rule engine (offline). Done.** `uv` project, `policy.yaml`, data models, and the deterministic rules: qualified-figure parsing, counting adjustments, recency, selection and exceptions, tertiary derivation, LinkedIn check, confidence, range, and the certification record. No network calls and no LLM.
2. **SEC EDGAR tier 1 fetcher. Done.** The three latest 10-K, 20-F or 40-F filings, with employee snippets. The prior years corroborate. All six golden companies match live (`RUN_LIVE=1`).
3. **Research and extraction for tiers 2–9. Done.** There are two Claude calls (`claude-sonnet-5-5`): research with web search and fetch, then structured extraction. There are also direct fetchers for the company website (stat tiles) and Form 990 (ProPublica). Spend is tracked against the budget, and server-side refusal fallbacks are on.
4. **Entity resolution and confirmation. Done.** Candidates with website, description, HQ, type, ticker → CIK, and global parent. A subsidiary without its own filings uses its parent's combined filing.
5. **Local MCP server. Done.** An `MCPServer` (mcp 2.x) over stdio with `find_entity` and `certify_employee_count`, registered in Claude Desktop as `employee-count-certifier`.
6. **Hosted service. Ready to deploy (Render).** One FastAPI service (`certifier.web`) serves:
   - the web page (search, entity confirmation, company card)
   - a JSON API
   - the MCP server over Streamable HTTP at `/mcp`

   Local Claude Desktop keeps using stdio. Access works by per-user **access codes**, stored as SHA-256 hashes in `CERTIFIER_ACCESS_CODES`; a code is revoked by removing its entry or listing its name in `CERTIFIER_REVOKED`. A code is accepted in two ways:
   - as a bearer header, for the web page, the API, and organizations that have Claude's request-headers feature
   - through a built-in OAuth sign-in for the Claude custom connector: Claude registers itself automatically, the person enters their access code, and tokens are tied to that person

   Spend controls:
   - a per-user limit of 20 new lookups a day
   - a global daily cap of $10
   - certifications cached per entity for 30 days, with a refresh option

   Secrets come only from environment variables. Also provided: `/health`, `render.yaml` and `DEPLOY.md`.

**Live results (2026-10-11):**

| Lookup | Result | Confidence | Cost | Time |
| --- | --- | --- | --- | --- |
| Adobe (SEC) | 31,360 (10-K) | 4–5 | $0.15 | 45 s |
| FPL (subsidiary) + NextEra | 9,400 + 17,400 (NEE 10-K) | 5 + 5 | $0.19 | 47 s |
| Donor Network West (990) | 513 (Form 990, 2024) | 3 | $0.09 | 44 s |
| Gong (private) | ~2,200 growth-adjusted from the website's 1,500, range 1,500–2,700 | 3 | $0.12 | 29 s |
| UC Davis (university) | more than 25,000 (includes health system), flagged | 1 | $0.14 | 34 s |

**Known gaps (v1):**
- **IPEDS fetcher.** The NCES Human Resources API returns server errors, so universities rely on web research. That finds campus-plus-health figures, not IPEDS. This is the top follow-up.
- **Research variance.** Web search results vary between runs. Basic search tools are set in `policy.yaml`, because the dynamic-filtering versions used up searches without returning results.
- **Complex cases are logged, not solved.** Lookups with conflicts, events or complexities are appended to `logs/review_queue.jsonl` for review and future examples. The entity-group logic (`group.py`) isn't wired into lookups yet.

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
