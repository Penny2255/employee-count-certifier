# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Two-level source labels: a plain-English `source_category` and an exact `source_type`, plus the
"What is this source?" explanation from source_glossary.yaml (editable without code changes).

Every source the engine can produce maps to exactly one category and one type. The research step
reports a `document_type` and `publisher`; readers (EDGAR, ProPublica) set them directly; anything
missing is inferred from the tier and URL.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .models import Source

GLOSSARY_PATH = Path(__file__).resolve().parents[2] / "source_glossary.yaml"

CATEGORIES = ("Financial Filing", "Official Company Report", "Company Publication", "Company Website",
              "Company Social Profile", "News (Executive Quote)", "Data Provider",
              "Specialty Data & Financial Media", "Other")

# document_type (as reported by research or set by a reader) -> source_type label.
DOCUMENT_TYPES = {
    "10-K": "10-K", "20-F": "20-F", "40-F": "40-F", "sec_filing": "SEC Annual Filing",
    "annual_report": "Annual Report", "acfr": "Annual Comprehensive Financial Report (ACFR)",
    "fact_sheet": "Corporate Fact Sheet", "form_990": "IRS Form 990", "ipeds": "IPEDS Filing",
    "non_financial_report": "Non-Financial Annual Report", "press_release": "Press Release",
    "company_document": "Company Document", "website_about": "Website: About Us",
    "website_other": "Website: Other Page", "website_careers": "Website: Careers Page", "linkedin_description": "LinkedIn: Company Description",
    "news": "News: {p}", "data_provider": "Data Provider: {p}", "other": "Web Page: {p}",
}
_CATEGORY = {
    "10-K": "Financial Filing", "20-F": "Financial Filing", "40-F": "Financial Filing", "sec_filing": "Financial Filing",
    "annual_report": "Financial Filing", "acfr": "Financial Filing",
    "fact_sheet": "Official Company Report", "form_990": "Official Company Report", "ipeds": "Official Company Report",
    "non_financial_report": "Official Company Report",
    "press_release": "Company Publication", "company_document": "Company Publication",
    "website_about": "Company Website", "website_other": "Company Website", "website_careers": "Company Website",
    "linkedin_description": "Company Social Profile",
}

# Publisher names for common hosts; anything else shows its host name.
PUBLISHERS = {
    "zoominfo.com": "ZoomInfo", "reveliolabs.com": "Revelio Labs", "pitchbook.com": "PitchBook",
    "crunchbase.com": "Crunchbase", "dnb.com": "Dun & Bradstreet", "apollo.io": "Apollo", "growjo.com": "Growjo",
    "tracxn.com": "Tracxn", "cbinsights.com": "CB Insights", "leadiq.com": "LeadIQ", "rocketreach.co": "RocketReach",
    "macrotrends.net": "Macrotrends", "stockanalysis.com": "Stock Analysis", "companiesmarketcap.com": "CompaniesMarketCap",
    "wikipedia.org": "Wikipedia", "reuters.com": "Reuters", "bloomberg.com": "Bloomberg", "ft.com": "Financial Times",
    "wsj.com": "The Wall Street Journal", "nytimes.com": "The New York Times", "cnbc.com": "CNBC",
    "techcrunch.com": "TechCrunch", "forbes.com": "Forbes", "businessinsider.com": "Business Insider",
    "theinformation.com": "The Information", "axios.com": "Axios", "yahoo.com": "Yahoo Finance",
    "paymentsdive.com": "Payments Dive", "spglobal.com": "S&P Global", "marketwatch.com": "MarketWatch",
    "fortune.com": "Fortune", "sfchronicle.com": "San Francisco Chronicle", "bizjournals.com": "Business Journals",
}
MEDIA_HOSTS = {"reuters.com", "bloomberg.com", "ft.com", "wsj.com", "nytimes.com", "cnbc.com", "techcrunch.com",
               "forbes.com", "businessinsider.com", "theinformation.com", "axios.com", "yahoo.com", "paymentsdive.com",
               "marketwatch.com", "fortune.com", "sfchronicle.com", "bizjournals.com"}
def _careers(path: str) -> bool:
    return any(w in path for w in ("career", "jobs", "join-us", "working-at", "life-at"))


_ABOUT = ("about", "company", "who-we-are", "our-story", "facts", "overview")


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _base_host(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def publisher_of(url: str, reported: str | None = None) -> str:
    host = _host(url)
    return PUBLISHERS.get(host) or PUBLISHERS.get(_base_host(host)) or reported or host or "unknown"


def infer_document_type(s: Source) -> str:
    """Best document type when research or a reader didn't report one."""
    url, host = s.url.lower(), _host(s.url)
    path = urlsplit(s.url).path.lower().strip("/")
    if "sec.gov/archives/edgar/data/" in url:
        return "sec_filing"
    if "propublica.org" in host or "form990" in path.replace("-", "").replace("_", ""):
        return "form_990"
    if "nces.ed.gov" in host or "ipeds" in url:
        return "ipeds"
    if "linkedin.com" in host:
        return "linkedin_description"
    if s.tier == 1:
        return "annual_report"
    if s.tier == 2:
        return "fact_sheet" if "fact" in path else "non_financial_report"
    if s.tier == 3:
        return "press_release" if any(w in url for w in ("press", "release", "newsroom", "/news/")) else "company_document"
    if s.tier == 4:
        if _careers(path):
            return "website_careers"
        return "website_about" if not path or any(w in path for w in _ABOUT) else "website_other"
    if s.tier == 5:
        return "linkedin_description"
    if s.tier == 6:
        return "news"
    if _base_host(host) in MEDIA_HOSTS:
        return "news"
    if s.tier in (7, 8) or _base_host(host) in PUBLISHERS:
        return "data_provider"
    return "other"


def classify(s: Source) -> tuple[str, str]:
    """(source_category, source_type) for one source."""
    kind = s.document_type if s.document_type in DOCUMENT_TYPES else infer_document_type(s)
    if kind in ("website_about", "website_other") and _careers(urlsplit(s.url).path.lower()):
        kind = "website_careers"  # a careers page, however extraction labelled it
    label = DOCUMENT_TYPES[kind].format(p=publisher_of(s.url, s.publisher))
    if kind in _CATEGORY:
        return _CATEGORY[kind], label
    if kind == "news":
        category = {6: "News (Executive Quote)", 8: "Specialty Data & Financial Media"}.get(s.tier, "Other")
    elif kind == "data_provider":
        category = {7: "Data Provider", 8: "Specialty Data & Financial Media"}.get(s.tier, "Other")
    else:
        category = "Other"
    return category, label


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def glossary() -> dict:
    return _load(os.environ.get("CERTIFIER_GLOSSARY") or str(GLOSSARY_PATH))


def explain(source_type: str) -> str:
    """The glossary explanation for a source type ("News: Reuters" falls back to "News")."""
    types = glossary()["types"]
    if source_type in types:
        return " ".join(types[source_type].split())
    generic = source_type.split(":", 1)[0].strip()
    return " ".join(types.get(generic, "").split())


def category_blurb(category: str) -> str:
    return glossary()["categories"].get(category, "")


# How the glossary is grouped in the "How certification works" panel.
GLOSSARY_GROUPS = {
    "Financial Filing": ["10-K", "20-F", "40-F", "Annual Report", "Annual Comprehensive Financial Report (ACFR)"],
    "Official Company Report": ["Corporate Fact Sheet", "IRS Form 990", "IPEDS Filing", "Non-Financial Annual Report"],
    "Company Publication": ["Press Release", "Company Document"],
    "Company Website": ["Website: About Us", "Website: Careers Page", "Website: Other Page"],
    "Company Social Profile": ["LinkedIn: Company Description", "LinkedIn: Member Count"],
    "News (Executive Quote)": ["News"],
    "Data Provider": ["Data Provider"],
    "Specialty Data & Financial Media": [],
    "Other": ["Web Page"],
}


def glossary_html() -> str:
    """The glossary as HTML for the "How certification works" panel (escaped; no scripts)."""
    from html import escape

    parts = []
    for category in CATEGORIES:
        items = "".join(f"<details><summary>{escape(t)}</summary><p>{escape(explain(t))}</p></details>"
                        for t in GLOSSARY_GROUPS.get(category, []))
        parts.append(f'<div class="g-cat"><strong>{escape(category)}</strong><p>{escape(category_blurb(category))}</p>'
                     f"{items}</div>")
    return "".join(parts)
