# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Proprietary notices: the owner line on every output, the robots policy for every response, and the terms page."""

from __future__ import annotations

COPYRIGHT = "© 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source."
OWNER_LINE = ("© 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. "
              "No permission is granted to copy, clone, scrape, reproduce, modify, distribute or use this software, "
              "its policy, data or outputs to train AI models, except as expressly authorized in writing by "
              "Matthew Beltrano.")
# One sentence for places that must stay short (the MCP server's instructions and tool descriptions).
SHORT_NOTICE = ("Proprietary service © 2026 Matthew Beltrano: its outputs may not be scraped, redistributed or used "
                "to train AI models.")
FOOTER_LINE = "© 2026 Matthew Beltrano · Proprietary · Not open source"
LINKEDIN = "https://www.linkedin.com/in/matthewbeltrano/"

ROBOTS = "noindex, nofollow, noarchive, noai, noimageai"
ROBOTS_META = f'<meta name="robots" content="{ROBOTS}">'

AI_CRAWLERS = ("GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-Web", "anthropic-ai", "CCBot",
               "Google-Extended", "PerplexityBot", "Perplexity-User", "Bytespider", "Amazonbot", "Applebot-Extended",
               "meta-externalagent", "FacebookBot", "cohere-ai", "cohere-training-data-crawler", "Diffbot",
               "omgili", "ImagesiftBot", "YouBot", "AI2Bot", "Timpibot")
ROBOTS_TXT = ("# © 2026 Matthew Beltrano. Proprietary. No crawling, scraping or use for AI training.\n"
              + "".join(f"User-agent: {bot}\nDisallow: /\n\n" for bot in AI_CRAWLERS)
              + "User-agent: *\nDisallow: /\n")

TERMS_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
{ROBOTS_META}
<title>Terms of use · GTM Data Certifier</title>
<link rel="icon" href="/assets/brand/favicon.png">
<style>
:root {{ --bg: #f6f8fb; --card: #ffffff; --text: #0a2545; --muted: #4a5d75; --line: #dbe3ee; --accent: #1f6fd1; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #0b1626; --card: #11213a; --text: #e8eef7; --muted: #a9b8cc;
  --line: #22385a; --accent: #7fb2ff; }} }}
body {{ margin: 0; background: var(--bg); color: var(--text); font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 32px 16px 48px; }}
article {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 24px 28px; }}
h1 {{ margin: 0 0 4px; font-size: 26px; }}
h2 {{ font-size: 17px; margin: 22px 0 6px; }}
p, li {{ color: var(--text); }}
.muted {{ color: var(--muted); font-size: 14px; }}
a {{ color: var(--accent); }}
footer {{ text-align: center; color: var(--muted); font-size: 13px; margin-top: 20px; }}
</style>
</head>
<body>
<main>
<article>
<h1>Terms of use</h1>
<p class="muted">GTM Data Certifier · open beta · last updated 12 October 2026</p>

<h2>1. Beta access is for evaluation</h2>
<p>You may use this site and its Claude connector to look up and evaluate certified employee counts during the open
beta. Access can change, be limited or end at any time, and daily allowances apply.</p>

<h2>2. What you may not do</h2>
<ul>
<li>Scrape, crawl, harvest or make automated or bulk queries against the site, its API or its connector.</li>
<li>Copy, reverse engineer, decompile or try to extract the source code, source policy, scoring rules or prompts.</li>
<li>Use the site, its outputs or its methodology to build, train or improve a competing product or service.</li>
<li>Use the site, its outputs, its policy or its data to train, fine-tune or evaluate AI models.</li>
<li>Resell, redistribute or republish outputs in bulk, or remove the notices on them.</li>
</ul>

<h2>3. Results are provided as is</h2>
<p>Certifications are built from public sources (filings, registers, official websites and other published data)
and scored under a documented policy. They can be wrong or out of date. They are provided as is, without warranty
of any kind; verify them before contractual or financial use. Third-party sources remain their owners' property.</p>

<h2>4. All rights reserved</h2>
<p>{OWNER_LINE}</p>
<p>The software is not open source, and no licence is granted by making the site or its repository available. For
permission, contact <a href="{LINKEDIN}" target="_blank" rel="noopener noreferrer">Matthew Beltrano on LinkedIn</a>.</p>

<p class="muted"><a href="/">Back to GTM Data Certifier</a></p>
</article>
<footer>{FOOTER_LINE}</footer>
</main>
</body>
</html>
"""
