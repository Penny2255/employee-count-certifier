# Deploying GTM Data Certifier on Render

This guide puts the certifier online so you, and people you choose, can use it from:
- **the Claude app** (web, desktop or mobile) as a custom connector, with the company card shown inside the chat
- **a web page** with a search box

It assumes no prior Render experience and takes about 20 minutes.

**What you'll end up with:** one Render web service at `https://<your-service>.onrender.com`, serving:
- `/`: the web page (company search, confirmation, the expedition, then the company card)
- `/mcp`: the endpoint the Claude app connects to
- `/health`: a minimal liveness check (`{"status":"ok"}`) for Render
- `/admin`: today's spend, lookups, cache hits, visitors, limit hits and the latest ratings (admin code)
- `/admin/status`: configuration (admin code)

It runs as an **open beta**: anyone with the link can search, with no sign-up and no code. Every lookup spends
money on your Anthropic API key, so spending is capped:
- Each **visitor** has **$2 a day** of lookup spend (about 10 new lookups), keyed on a hashed IP address.
- The whole service stops making new lookups at **$5 a day** across everyone, website and Claude connector combined.
- Before each lookup the per-lookup maximum ($0.50) is reserved against both, and the unused part is released when it
  finishes, so neither cap is ever exceeded. Both reset at **midnight Pacific**.
- Cached results (shared, **90 days**) and the eight **sample results** are free and never count.
- One lookup at a time per visitor, and at most **10 requests a minute** per IP.
- Your **admin code** bypasses all of this.

---

## What you need first

1. **The code on GitHub.** The repository `Penny2255/employee-count-certifier` is already pushed, with this guide on the `main` branch.
2. **An Anthropic API key.** Create one in the Claude Console (console.anthropic.com) under **API keys**. It starts with `sk-ant-`. Use a fresh key for the hosted service, so you can revoke it separately from your local one.
3. **An SEC contact string**, for example `Your Name you@example.com`. The SEC requires contact information on automated requests.
4. **A Render account**: sign up at render.com. Signing in with GitHub is easiest.

**Cost:** the blueprint uses Render's **Starter** plan with a 1 GB disk, about $7–8 a month. You pay Anthropic API usage separately: roughly $0.10–0.20 per new lookup, capped at $5 a day by default. See [Running on the free plan](#running-on-the-free-plan) for the trade-offs of not paying for Render.

---

## Step 1: Create your admin code (on your computer)

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

For the configuration, call `/admin/status` with your admin code (from a terminal), or open `/admin` in a browser:

```bash
curl -H "Authorization: Bearer ecc_YOUR_CODE" https://<your-service>.onrender.com/admin/status
```

You should see something like:

```json
{"status": "ok", "policy_version": "0.2", "public_base_url": "https://<your-service>.onrender.com",
 "anthropic_key_set": true, "sec_user_agent_set": true, "admin_codes_configured": 1,
 "spend_today_usd": 0.0, "daily_usd_cap": 5.0, "visitor_usd_per_day": 2.0, "cache_days": 90}
```

Check that:
- `anthropic_key_set` and `sec_user_agent_set` are `true`
- `admin_codes_configured` matches the number of admin codes you added
- `public_base_url` is your real URL

---

## Step 5: Try the web page

1. Open `https://<your-service>.onrender.com/`. No code is needed; under the search box you'll see "About 10 searches left today".
2. Click a **sample result** to see a finished certification instantly, for free.
3. Type a company (e.g. `Salesforce`) and click **Certify employees**. Choose the right organization, then **Certify**. A new lookup takes 30–90 seconds.
4. Searching again for the same company returns the cached certification instantly, for free. **Refresh** runs a new lookup and counts against the allowance.
5. Open `https://<your-service>.onrender.com/admin` and enter your **admin code** (it's remembered in that browser). Your searches from that browser now bypass the limits too.

### Check the client IP (once, after the first deploy)

The allowances key on the visitor's IP, read from the `X-Forwarded-For` header Render's proxy adds. On `/admin`, the
**Proxy check** shows your own IP as the service sees it, with the last part masked. If it isn't your IP (compare with
any "what is my IP" site), change `CERTIFIER_PROXY_HOPS`: it's the number of proxies between the visitor and the
service, counted from the right of `X-Forwarded-For` (default 1).

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
5. Click **Add**, then **Connect**. A browser page from your service opens, titled *"Connect Claude to GTM Data Certifier"*. Click **Continue as beta guest**. (To connect as admin, open **Have an admin code?** and enter it.)
6. In a chat, click **+** → **Connectors** and make sure the certifier is turned on. Then ask, for example: *"What's the certified employee count for Salesforce?"* Claude confirms the company with you, then shows the company card in the chat.

The Free plan allows one custom connector.

### On a Team or Enterprise plan

An **Owner** adds the connector once, at **Organization settings** → **Connectors** → **Add** → **Custom**, using the same URL. Each member then goes to **Customize** → **Connectors**, finds it (labelled **Custom**), clicks **Connect**, and continues as a beta guest.

A guest connection draws on the same daily allowance as the website from the network where they signed in (the sign-in page runs in their own browser, so its IP is recorded as a keyed hash and bound to the connection). Reconnecting from the same network doesn't reset the allowance.

### If your organization has "Request headers" (beta)

Some organizations can add a fixed header instead of signing in. Choose **No sign-in**, then under **Request headers** add `authorization` with the value `Bearer ecc_…` (an admin code), including the word `Bearer` and the space. This gives everyone in the organization admin access with no limits, so use it only for your own organization.

### Your local Claude Desktop setup keeps working

The local server in `claude_desktop_config.json` still runs on your computer, with no limits. You can keep both, or remove the local one once the hosted connector works.

---

## Sharing it

Send the web page URL `https://<your-service>.onrender.com/` (and, for Claude, the connector URL ending in `/mcp`).
No codes are needed.

**More admins:** create a code with `uv run certifier-access new alex` and add its entry to `CERTIFIER_ACCESS_CODES`
(comma-separated: `matt:5f2c…e91,alex:9ab0…c44`), then save and redeploy. To revoke one, delete its entry or add the name
to `CERTIFIER_REVOKED`; its connector sign-ins stop working immediately.

---

## Beta limits

| Variable | Default | Meaning |
| --- | --- | --- |
| `CERTIFIER_VISITOR_USD_PER_DAY` | `2` | Lookup spend per visitor per day (website and their Claude connection together). Shown to visitors as "About N searches left today", never in dollars. |
| `CERTIFIER_DAILY_USD_CAP` | `5` | Hard cap on spend across everyone per day. |
| `CERTIFIER_CACHE_DAYS` | `90` | How long a certification is reused (by anyone) before a new lookup runs. Cached results are free. |
| `CERTIFIER_RATE_LIMIT_PER_MIN` | `10` | API requests per minute per IP (page assets, health checks and the connector endpoints aren't counted). |
| `CERTIFIER_PROXY_HOPS` | `1` | Proxies in front of the service, for reading the client IP from `X-Forwarded-For` (see Step 5). |
| `CERTIFIER_HASH_SECRET` | generated | Optional: the secret for keyed IP hashes. If unset, one is generated and kept in the service's database. |

How the caps work:
- Before each lookup the maximum a lookup can cost ($0.50, `max_cost_usd_per_lookup` in `policy.yaml`) is reserved against
  both the visitor's and the global allowance; when it finishes or fails, only what it actually cost is kept. So neither
  cap is ever exceeded, even with lookups running at the same time.
- Days run from midnight to midnight **Pacific** (America/Los_Angeles).
- Messages: *"You've reached today's beta limit. Back tomorrow."* and *"Beta capacity reached for today. Back tomorrow."*
  Cached and sample results keep working either way.

**Privacy:** the IP address itself is never stored. It's turned into a keyed hash (server secret), then salted with a
random value that changes every day to make the allowance key; earlier days' salts are deleted. Queries, results and
ratings are stored for quality review.

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
| **"That admin code isn't valid"** | The code is pasted whole (starts with `ecc_`). Its entry is in `CERTIFIER_ACCESS_CODES` and the service was redeployed. |
| Everyone shares one allowance, or visitors hit the limit at once | The client IP isn't being read correctly. Check `/admin` → Proxy check and adjust `CERTIFIER_PROXY_HOPS`. |
| **"Too many requests"** | More than 10 API requests a minute from one IP. Wait a minute. Raise `CERTIFIER_RATE_LIMIT_PER_MIN` if it's too strict. |
| A lookup **fails or is slow** | Render **Logs**. Also check that the Anthropic key has credit and `/admin/status` shows `anthropic_key_set: true`. |
| The card doesn't appear **in the chat** | The tool result includes `card_url`. Open it in a browser, since the same card is saved on the server. |

Logs never contain admin codes, IP addresses or API keys. Secrets come only from Render's environment variables.
