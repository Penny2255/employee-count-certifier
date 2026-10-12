# Deploying GTM Data Certifier on Render

This guide puts the certifier online so you, and people you choose, can use it from:
- **the Claude app** (web, desktop or mobile) as a custom connector, with the company card shown inside the chat
- **a web page** with a search box

It assumes no prior Render experience and takes about 20 minutes.

**What you'll end up with:** one Render web service at `https://<your-service>.onrender.com`, serving:
- `/`: the web page (access code, company search, confirmation, then the company card)
- `/mcp`: the endpoint the Claude app connects to
- `/health`: a minimal liveness check (`{"status":"ok"}`) for Render
- `/admin/status`: configuration and today's spend, for holders of an access code

Every lookup spends money on your Anthropic API key, so the service is locked behind **access codes**:
- Each person gets their own code, and you can revoke any of them.
- Each person gets **10 new lookups a day**. Cached results are free; **Refresh** counts as a new lookup.
- The whole service stops making new lookups once it reaches **$10 of API spend in a day**.
- Each certification is cached for **90 days** and shared: anyone looking up the same organization gets it free.

---

## What you need first

1. **The code on GitHub.** The repository `Penny2255/employee-count-certifier` is already pushed, with this guide on the `main` branch.
2. **An Anthropic API key.** Create one in the Claude Console (console.anthropic.com) under **API keys**. It starts with `sk-ant-`. Use a fresh key for the hosted service, so you can revoke it separately from your local one.
3. **An SEC contact string**, for example `Your Name you@example.com`. The SEC requires contact information on automated requests.
4. **A Render account**: sign up at render.com. Signing in with GitHub is easiest.

**Cost:** the blueprint uses Render's **Starter** plan with a 1 GB disk, about $7–8 a month. You pay Anthropic API usage separately: roughly $0.10–0.20 per new lookup, capped at $10 a day by default. See [Running on the free plan](#running-on-the-free-plan) for the trade-offs of not paying for Render.

---

## Step 1: Create your first access code (on your computer)

In the project folder, run:

```
uv run certifier-access new matt
```

Use any short name instead of `matt`; it appears in usage records. The command prints two things:

```
Access code for matt (give this to them; it is shown only once):

  ecc_Xy3...                      <- the CODE: keep it private, like a password

Add this entry to CERTIFIER_ACCESS_CODES on the server (comma-separated with any others):

  matt:5f2c...e91                 <- the ENTRY: goes into Render (it's a hash, not the code)
```

Save both somewhere safe, such as a password manager. The server never stores the code itself, only its hash.

---

## Step 2: Create the service on Render

1. In the Render dashboard, click **New** → **Blueprint**.
2. Connect your GitHub account if asked, then pick the `employee-count-certifier` repository.
3. Render reads `render.yaml` and shows one web service, `employee-count-certifier`. It asks you to fill in four values:

   | Variable | What to enter |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | your `sk-ant-…` key |
   | `SEC_USER_AGENT` | e.g. `Your Name you@example.com` |
   | `CERTIFIER_ACCESS_CODES` | the **entry** from step 1, e.g. `matt:5f2c…e91` |
   | `PUBLIC_BASE_URL` | leave a placeholder such as `https://example.com` for now; you'll fix it in step 3 |

4. Click **Apply**. Render builds and starts the service, which takes a few minutes the first time. Follow progress under the service's **Logs** tab.

---

## Step 3: Set the public URL

1. On the service page, copy its URL from the top, e.g. `https://employee-count-certifier-ab12.onrender.com`.
2. Go to **Environment**, edit `PUBLIC_BASE_URL`, and paste the URL exactly: with `https://` and **no trailing slash**.
3. Click **Save, rebuild, and deploy**. This URL has to be right for Claude's sign-in to work.

---

## Step 4: Check the service

Open `https://<your-service>.onrender.com/health` in a browser. It shows only `{"status":"ok"}`, so it reveals nothing about the setup.

For the details, call `/admin/status` with your access code (from a terminal):

```bash
curl -H "Authorization: Bearer ecc_YOUR_CODE" https://<your-service>.onrender.com/admin/status
```

You should see something like:

```json
{"status": "ok", "policy_version": "0.2", "anthropic_key_set": true, "sec_user_agent_set": true,
 "access_codes_configured": 1, "public_base_url": "https://<your-service>.onrender.com",
 "spend_today_usd": 0.0, "daily_usd_cap": 10.0, "daily_lookups_per_code": 10, "cache_days": 90}
```

Check that:
- `anthropic_key_set` and `sec_user_agent_set` are `true`
- `access_codes_configured` matches the number of people you added
- `public_base_url` is your real URL

---

## Step 5: Try the web page

1. Open `https://<your-service>.onrender.com/`.
2. Paste your **access code** (`ecc_…`), type a company (e.g. `Salesforce`), and click **Search**.
3. Choose the right organization, then click **Certify this one**. A new lookup takes 30–90 seconds, and the company card appears below.
4. Searching again for the same company returns the cached card instantly, for free. **Certify (fresh lookup)** forces a new lookup.

---

## Step 6: Add it to the Claude app

### On a Free, Pro or Max plan (your own account)

1. In Claude (claude.ai or the desktop app), go to **Customize** → **Connectors**.
2. Click **Add custom connector**.
3. Enter a name, e.g. `Employee Count Certifier`, and the **MCP server URL**: `https://<your-service>.onrender.com/mcp`. Include `/mcp` at the end.
4. If the dialog asks for authentication settings, choose:
   - **Authentication:** **Sign in now**
   - **OAuth client:** **Register automatically**
   - Leave any client ID or secret fields empty.
5. Click **Add**, then **Connect**. A browser page from your service opens, titled *"Connect Claude to Employee Count Certifier"*. Paste your **access code** and click **Connect to Claude**.
6. In a chat, click **+** → **Connectors** and make sure the certifier is turned on. Then ask, for example: *"What's the certified employee count for Salesforce?"* Claude confirms the company with you, then shows the company card in the chat.

The Free plan allows one custom connector.

### On a Team or Enterprise plan

An **Owner** adds the connector once, at **Organization settings** → **Connectors** → **Add** → **Custom**, using the same URL. Each member then goes to **Customize** → **Connectors**, finds it (labelled **Custom**), clicks **Connect**, and enters **their own** access code.

### If your organization has "Request headers" (beta)

Some organizations can add a fixed header instead of signing in. Choose **No sign-in**, then under **Request headers** add `authorization` with the value `Bearer ecc_…`, including the word `Bearer` and the space. This shares one code across the whole organization, so per-person sign-in above is usually better.

### Your local Claude Desktop setup keeps working

The local server in `claude_desktop_config.json` still runs on your computer, with no limits. You can keep both, or remove the local one once the hosted connector works.

---

## Sharing access with another person

1. Create a code for them: `uv run certifier-access new alex`.
2. In Render → **Environment**, edit `CERTIFIER_ACCESS_CODES` and add their **entry** after yours, separated by a comma: `matt:5f2c…e91,alex:9ab0…c44`
3. Click **Save, rebuild, and deploy**. `/admin/status` should now show `access_codes_configured: 2`.
4. Send them, privately:
   - the web page URL `https://<your-service>.onrender.com/`
   - the connector URL `https://<your-service>.onrender.com/mcp`
   - their access code
   - step 6 of this guide

**To revoke someone,** use either method, then save and redeploy:
- delete their entry from `CERTIFIER_ACCESS_CODES`
- or add their name to a `CERTIFIER_REVOKED` variable (comma-separated)

Their web access and their Claude connection stop working immediately.

---

## Spend controls

| Variable | Default | Meaning |
| --- | --- | --- |
| `CERTIFIER_DAILY_LOOKUPS_PER_USER` | `10` | New (uncached) lookups per access code per day (UTC). **Refresh** counts. A subsidiary lookup also certifies its parent, which counts as 2. |
| `CERTIFIER_DAILY_USD_CAP` | `10` | Total API spend across everyone per day. When reached, new lookups stop until midnight UTC; cached results still work. |
| `CERTIFIER_CACHE_DAYS` | `90` | How long a certification is reused (by anyone) before a new lookup runs. The page shows "Certified on [date]" with a Refresh button. |

When a limit is hit, the person sees a plain message saying which limit was reached and when it resets. `/admin/status` shows today's spend.

The dollar cap is checked before each lookup, so one lookup in progress can take spend slightly past it, by up to about $0.50.

---

## Running on the free plan

To avoid Render costs, edit `render.yaml` before creating the Blueprint:
- set `plan: free`
- delete the `disk:` block
- set `CERTIFIER_DATA_DIR` to `/tmp/certifier-data`

**Trade-offs:**
- The service sleeps after about 15 minutes idle, and the first request then takes about a minute. The Claude app may time out on that request; just retry.
- The cache, daily usage counts and Claude sign-ins are lost on every deploy or restart. People may need to reconnect in Claude, and the daily limits reset early.

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The service **won't start**, and the log says `PUBLIC_BASE_URL` | It must be a full `https://` URL with no path, such as `https://<your-service>.onrender.com`. The service checks this at startup and refuses to run otherwise. (Local development may use `http://localhost:8000`.) |
| Claude says it **couldn't reach the MCP server** | The URL ends in `/mcp`. `/health` loads in a browser. `PUBLIC_BASE_URL` exactly matches the service URL (https, no trailing slash). |
| A lookup says **"Service configuration issue, please try again later"** | The Anthropic key is missing, wrong or revoked. The Render log names the problem (never the key). |
| The sign-in page says the **link expired** | Start again from **Connect** in Claude. Links last 15 minutes. |
| **"That access code isn't valid"** | The code is pasted whole (starts with `ecc_`). Its entry is in `CERTIFIER_ACCESS_CODES` and the service was redeployed. |
| The web page shows **"Enter a valid access code"** | Same checks as above. |
| A lookup **fails or is slow** | Render **Logs**. Also check that the Anthropic key has credit and `/admin/status` shows `anthropic_key_set: true`. |
| The card doesn't appear **in the chat** | The tool result includes `card_url`. Open it in a browser, since the same card is saved on the server. |

Logs never contain access codes or API keys. Secrets come only from Render's environment variables.
