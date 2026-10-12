# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Rule-based extraction of headcount sources from filing snippets.

The offline fallback when no Claude extraction is available, and a cross-check on it.
Each filing contributes its single best global figure; a filing is one document, so its
own restatements never corroborate each other.
"""

from __future__ import annotations

import re
from datetime import date

from . import rules
from .figures import parse_figure
from .models import Source
from .policy import Policy, default_policy
from .sources.edgar import Filing, Snippet

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|december")
_AS_OF = re.compile(rf"\b(?:as of|as at|at|on|by)\s+({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})"
                    rf"|\b(?:as of|as at|at|on)\s+(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})", re.I)
# Clauses describing a slice of the workforce, or events rather than a headcount.
_PARTIAL = re.compile(r"\b(in the united states|in the u\.s(?=\.)|u\.s\.-based|outside (?:of )?the united states|"
                      r"internationally|in our international|domestic|of whom|of which|"
                      r"research and development|r&d|engineering|sales and marketing|represented by|"
                      r"unioni[sz]ed|collective bargaining|segment|division|country of significant employment|female|gender|age group|"
                      r"management population|seasonal|"
                      r"in (?:development|research|sales|engineering|manufacturing|operations|services|support))\b",
                      re.I)
_NOT_HEADCOUNT = re.compile(r"\b(let go|laid off|layoffs?|terminat\w*|hired|hiring|joined|"
                            r"participat\w*|survey|trained|training|completed|volunteer\w*|customers?|"
                            r"serving|plan participants|eligible|shares|stock|options|"
                            r"recruit\w*|skill(?:s|ing)?|campaign|goal|commit\w*|pledge\w*|aim\w*|by 20\d\d)\b", re.I)
# People a programme reaches, or a restructuring affects, are not the workforce. Checked only near the figure:
# "Healthier U initiative now reaches more than 59,000 employees", "the 7,500 employees whose roles are impacted";
# not "employees totaling 17,400 ..., continue to develop enterprise-wide initiatives".
_PROGRAMME = re.compile(r"\b(initiatives?|programmes?|programs?|reach(?:es)?|has reached|have reached|wellbeing|"
                        r"well-being|impacted|affected|focus groups?|data from)\b", re.I)


def _programme_reach(clause: str, value: int) -> bool:
    m = re.search(re.escape(f"{value:,}"), clause)
    if m is None:
        return False
    after = re.split(r"[,;]|\.\s+(?=[A-Z])", clause[m.end():], maxsplit=1)[0][:90]  # to the end of its phrase
    return bool(_PROGRAMME.search(clause[max(0, m.start() - 90): m.end()] + after))
_CLAUSES = re.compile(r";\s+|,\s+(?=of (?:whom|which)\b)|\s+(?=of (?:whom|which)\b)|,\s+(?=and\b)")


def _as_of(text: str, filing: Filing) -> date | None:
    m = _AS_OF.search(text)
    if m:
        month, day, year = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(4), m.group(6))
        month_num = _MONTHS.split("|").index(month.lower()) + 1
        try:
            return date(int(year), month_num, int(day))
        except ValueError:
            pass
    return filing.period


def _describes_part(clause: str, value: int) -> bool:
    """Is the figure itself regional or departmental? Only the words describing it count (up to the next
    comma): in "we employed approximately 223,000 people on a full-time basis, 121,000 in the U.S. and 102,000
    internationally" the U.S./international breakdown that follows the total doesn't narrow it."""
    m = re.search(re.escape(f"{value:,}"), clause)
    if m is None:
        return bool(_PARTIAL.search(clause))
    own = clause[: m.end()] + re.split(r"[,;]", clause[m.end():], maxsplit=1)[0]
    return bool(_PARTIAL.search(own))


def _other_entity_subject(clause: str, filing: Filing) -> bool:
    """A clause led by another entity's acronym ("FPL had ...", "NEER had ...") is a subsidiary figure."""
    m = re.match(r"\W*([A-Z][A-Z&]{1,6})\s+(?=[a-z])", clause)
    if not m:
        return False
    token = m.group(1)
    own = {filing.company.ticker or ""} | set(re.findall(r"[A-Z&]+", filing.company.name.upper()))
    return token not in own and token not in {"AS", "AT", "IN", "ON", "THE", "WE", "OUR", "BY", "OF", "US"}


def snippet_sources(snippets: list[Snippet]) -> list[Source]:
    """Every figure found, one Source per clause, scoped and dated."""
    out = []
    for i, snip in enumerate(snippets):
        for clause in _CLAUSES.split(snip.text):
            fig = parse_figure(clause)
            if fig is None or _NOT_HEADCOUNT.search(clause) or _programme_reach(clause, fig.value):
                continue
            partial = _describes_part(clause, fig.value) or _other_entity_subject(clause, snip.filing)
            out.append(Source(
                url=snip.filing.url, tier=1, value=fig.value, qualifier=fig.qualifier, basis=fig.basis,
                excerpt=snip.text, as_of_date=_as_of(snip.text, snip.filing),
                published_date=snip.filing.filed, scope="partial" if partial else "global",
                document_type=snip.filing.form,
            ))
    return out


def best_per_filing(snippets: list[Snippet], policy: Policy | None = None) -> list[Source]:
    """One source per filing: its best global figure (by date, then specificity)."""
    policy = policy or default_policy()
    by_filing: dict[str, list[Source]] = {}
    for s in snippet_sources(snippets):
        if s.scope == "global":
            by_filing.setdefault(s.url, []).append(s)
    picks = [rules.best_of(candidates, policy).source for candidates in by_filing.values()]
    return [p for p in picks if p is not None]
