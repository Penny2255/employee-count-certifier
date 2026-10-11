"""Worked examples (SPEC.md: Example library). One YAML file per case in examples/.

Each example is both a regression test for the engine and, from step 3 on, reference
material for the research prompt.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .figures import parse_figure
from .models import CountType, Entity, LinkedInEvidence, Qualifier, Source

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


class Expected(BaseModel):
    certified_count: int | None
    qualifier: Qualifier | None = None
    count_type: CountType | None = None
    policy_tier: int | None = None
    confidence_score: int
    range: tuple[int, int] | None = None
    selected_url: str | None = None


class Example(BaseModel):
    case: str
    entity: Entity
    lookup_date: date
    tags: list[str] = Field(default_factory=list)
    sources: list[Source]
    linkedin: LinkedInEvidence | None = None
    event_flags: list[str] = Field(default_factory=list)
    expected: Expected
    lesson: str
    path: Path | None = None


def _source(raw: dict) -> dict:
    """Fill value and qualifier from the excerpt when the file doesn't state them."""
    if "value" not in raw:
        fig = parse_figure(raw.get("excerpt", ""))
        if fig is None:
            raise ValueError(f"No value given and none parsed from excerpt: {raw.get('url')}")
        raw = {**raw, "value": fig.value, "qualifier": raw.get("qualifier", fig.qualifier),
               "basis": raw.get("basis", fig.basis)}
    return raw


def load_example(path: Path) -> Example:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw["sources"] = [_source(s) for s in raw.get("sources", [])]
    return Example.model_validate({**raw, "path": path})


def load_examples(directory: Path | None = None) -> list[Example]:
    return [load_example(p) for p in sorted((directory or EXAMPLES_DIR).glob("*.yaml"))]
