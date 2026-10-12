# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Parse a headcount figure and its qualifier out of a source excerpt (counting rule 4)."""

from __future__ import annotations

import re
from typing import NamedTuple

from .models import Basis, Qualifier
from .policy import Policy, default_policy

_NUMBER = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s*(million|thousand|k)\b)?(?![\w,]*%)",
    re.I,
)
_HEAD_NOUNS = re.compile(
    r"^\W*(?:\w+\W+){0,3}?(people|persons|employees|team\s+members|teammates|staff|workers|"
    r"associates|colleagues|full-time|personnel|fte)",
    re.I,
)
# "we employed 31,360", "employees totaling 17,400", "number of employees to 69,505", "a workforce of 900";
# not "Employees purchased 1.1 million shares".
_HEAD_VERBS = re.compile(
    r"\b(employ(?:s|ed|ing)?|(?:employees|workforce|headcount|staff(?:ing)?|personnel)\W+(?:\w+\W+){0,2}?"
    r"(?:totaling|totalling|of|was|were|is|numbered|to|reached)|totaling|totalling)\W+(?:\w+\W+){0,3}$",
    re.I,
)
# A day number right after a month ("employed as of November 28") is a date, not a headcount.
_MONTH_BEFORE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december)\W*$", re.I
)
# "499 full-time equivalent employees", "1,200 FTEs", "FTE count of 1,200"
_FTE = re.compile(r"^\W*(?:\w+\W+){0,2}?(full[- ]time[- ]equivalents?|FTEs?)\b", re.I)
_FTE_BEFORE = re.compile(r"\b(full[- ]time[- ]equivalents?|FTEs?)\W+(?:\w+\W+){0,5}$", re.I)
_MULTIPLIERS = {"million": 1_000_000, "thousand": 1_000, "k": 1_000}


class Figure(NamedTuple):
    value: int
    qualifier: Qualifier
    basis: Basis = "headcount"


def _qualifier_before(prefix: str, policy: Policy) -> Qualifier:
    tail = prefix[-40:].lower()
    best: tuple[int, Qualifier] | None = None
    for qualifier, phrases in policy.qualifier_phrases.items():
        for phrase in phrases:
            pattern = (r"(?:^|\W)" if phrase[0].isalnum() else "") + re.escape(phrase) + r"\W*$"
            if re.search(pattern, tail) and (best is None or len(phrase) > best[0]):
                best = (len(phrase), qualifier)  # longest match wins ("no more than" over "more than")
    return best[1] if best else "exact"


def _is_year(raw: str, unit: str | None) -> bool:
    return unit is None and re.fullmatch(r"(19|20)\d\d", raw) is not None


def parse_figure(text: str, policy: Policy | None = None) -> Figure | None:
    """Return the first headcount figure in `text`, or None if there is none.

    A number counts as a headcount when a worker noun follows it within a few words
    ("31,360 people") or an employment verb precedes it ("employees totaling 17,400").
    """
    policy = policy or default_policy()
    for m in _NUMBER.finditer(text):
        raw, unit = m.group(1), m.group(2)
        if _is_year(raw, unit):
            continue
        before, after = text[: m.start()], text[m.end():]
        verb_led = _HEAD_VERBS.search(before[-60:]) and not _MONTH_BEFORE.search(before)
        if not (_HEAD_NOUNS.match(after) or verb_led):
            continue
        value = float(raw.replace(",", "")) * _MULTIPLIERS.get((unit or "").lower(), 1)
        basis = "fte" if _FTE.match(after) or _FTE_BEFORE.search(before[-60:]) else "headcount"
        return Figure(int(round(value)), _qualifier_before(before, policy), basis)
    return None

