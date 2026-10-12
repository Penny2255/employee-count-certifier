# employee-count-certifier

Certified global employee counts for any organization. The count follows a documented source policy: source tiers 1–9, recency rules, corroboration and a 0–5 confidence score. Results come with the source excerpt, date, rationale and confidence. The tool runs as an MCP server for the Claude app. See [SPEC.md](SPEC.md) for the policy, and [policy.yaml](policy.yaml) for every tunable value.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and Python 3.12.
2. Create `.env` in the repo root (it's gitignored) with:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   SEC_USER_AGENT=Your Name your.email@example.com
   ```
3. `uv sync`

## Use in Claude Desktop

Add this to `claude_desktop_config.json` (on Windows: `%APPDATA%\Claude\`), then restart Claude Desktop:

```json
{
  "mcpServers": {
    "employee-count-certifier": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\employee-count-certifier", "run", "certifier-mcp"]
    }
  }
}
```

Then ask, for example, "What's the certified employee count for Adobe?" Claude confirms the organization with you first, then certifies it. If the organization is a subsidiary, its parent is certified too. A lookup takes 30–90 seconds and typically costs $0.10–$0.20.

## How it works

1. **Entity confirmation:** `find_entity` lists the matching organizations for you to pick from.
2. **Structured sources:**
   - SEC EDGAR (10-K, 20-F and 40-F, tier 1)
   - Form 990 via ProPublica (tier 2)
   - the organization's own website (tier 4)
3. **Research:** Claude searches the web for the other tiers and extracts every figure with its quote, date and scope.
4. **Engine:** the deterministic rules in `src/certifier/` choose the value, apply the counting rules and score confidence.

## Hosted service (Claude app + web page)

The same engine also runs as one web service, **GTM Data Certifier** by Human in the Hyperloop ("Deep sweeps. Certified answers."). It has three parts:
- a web app at `/`: search, confirm the organization, watch the expedition (live progress in one of five themes), then the certified card with downloads and a rating
- an MCP endpoint at `/mcp` for the Claude app's custom connectors, with an in-chat company card
- a JSON API

Access is by per-person access codes, created with `uv run certifier-access new NAME`. The service allows 10 new lookups per code per day, a $10 daily dollar cap and a shared 90-day cache. See [DEPLOY.md](DEPLOY.md) for step-by-step Render setup, and [docs/screenshots/](docs/screenshots/) for every screen.

```
PUBLIC_BASE_URL=http://localhost:8000 uv run uvicorn certifier.web:app --port 8000   # run the hosted service locally
CERTIFIER_DEMO=1 ...                                  # also enables ?demo=home|confirm|expedition|result|how for screenshots
```

## Development

```
uv run pytest                          # offline tests
RUN_LIVE=1 uv run pytest tests/test_live_edgar.py   # live SEC EDGAR golden set
```

Worked examples live in `examples/` as one YAML file per case, and each one is also a regression test. Flagged lookups are appended to `logs/review_queue.jsonl` for review.
