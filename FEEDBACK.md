# Feedback backlog

Running backlog of feedback from reviews. Each item shows its status and where it was addressed.

## Card

- [x] **Rename the "Primary source" section header.** It clashed with the primary source tier class. Renamed to **"Key Source"** (2026-10-11).
- [ ] **More expressive visuals (next design pass, not yet):**
  - company logo in the header
  - livelier icons and wording
  - growth vs. shrinking shown visually: trend arrow, color and wording ("growing", "shrinking")
  - confidence shown emotionally:
    - at score 4–5, a celebratory "big confirmed discovery" style
    - at score 0–2, a "tough one, handle with care" style
  - keep the rationale prominent, and never show status by color alone

## Scoring defects from the Stripe run (2026-10-11)

Stripe was certified at 8,500 with confidence 2; it should have been about 0–1, or adjusted. Fixed on 2026-10-11 (see DECISIONS.md D27–D31):

- [x] **Undated anchor:** an as-of date is now estimated from context (article date, "as of early 2025"), stored with `as_of_estimated: true`, and every recency rule applies to it.
- [x] **Corroboration:** "near the as-of date" is measured from the anchor's estimated date. An anchor with no date at all gets no corroboration bonus. The same rule applies to every source.
- [x] **Recency penalty:** it applies whenever the anchor's age exceeds the policy window, including estimated dates. The recency finding's score impact matches the deduction.
- [x] **Known adjustments:** a known change after the as-of date (e.g. announced layoffs) labels the figure "pre-adjustment" in the headline.
- [x] **Newer data:** newer tertiary series (e.g. quarterly Revelio) that diverge from an old figure are shown as an "Indicated current range" alongside the certified figure, without overriding policy.
