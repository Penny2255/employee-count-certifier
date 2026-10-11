"""Claude calls: web research (search + fetch, free-text notes) and structured extraction.

Two calls because web search returns cited text, and structured outputs reject citations.
Spend is tracked per lookup against policy.budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import load_env
from .policy import Policy

FALLBACK_BETA = "server-side-fallback-2026-07-01"
T = TypeVar("T", bound=BaseModel)


@dataclass
class Spend:
    """Running cost of one lookup."""

    policy: Policy
    usd: float = 0.0
    searches: int = 0
    fetches: int = 0
    calls: int = 0
    notes: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)  # searches and fetches run, for transparency

    def add(self, model: str, usage) -> None:
        price = self.policy.pricing.models.get(model)
        if price is None:
            self.notes.append(f"No price for {model}; cost not counted.")
            return
        cached = usage.cache_read_input_tokens or 0
        tool = usage.server_tool_use
        searches = (tool.web_search_requests or 0) if tool else 0
        self.searches += searches
        self.fetches += (tool.web_fetch_requests or 0) if tool else 0
        self.calls += 1
        self.usd += ((usage.input_tokens + (usage.cache_creation_input_tokens or 0)) * price.input_per_mtok
                     + cached * price.cache_read_per_mtok + usage.output_tokens * price.output_per_mtok) / 1e6
        self.usd += searches * self.policy.pricing.web_search_per_1000 / 1000

    @property
    def over_budget(self) -> bool:
        return self.usd >= self.policy.budget.max_cost_usd_per_lookup


def _cached(system: str) -> list[dict]:
    """The system prompt (policy, guidelines, examples) is identical across lookups: cache it."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


class Claude:
    def __init__(self, policy: Policy, client: anthropic.Anthropic | None = None):
        load_env()
        self.policy = policy
        self.client = client or anthropic.Anthropic()

    def research(self, system: str, prompt: str, spend: Spend, max_searches: int | None = None,
                 max_fetches: int | None = None) -> str:
        """Run a web research turn; returns the model's text notes (with URLs and quotes)."""
        model = self.policy.models.research
        budget = self.policy.budget
        searches_left = budget.max_web_searches_per_entity if max_searches is None else max_searches
        fetches_left = budget.max_web_fetches_per_entity if max_fetches is None else max_fetches
        messages: list = [{"role": "user", "content": prompt}]
        texts: list[str] = []
        for _ in range(budget.max_continuations + 1):
            tools = []
            if searches_left > 0:
                tools.append({"type": budget.web_search_tool, "name": "web_search", "max_uses": searches_left})
            if fetches_left > 0:
                tools.append({"type": budget.web_fetch_tool, "name": "web_fetch", "max_uses": fetches_left,
                              "max_content_tokens": budget.fetch_max_content_tokens})
            with self.client.beta.messages.stream(
                model=model, max_tokens=16000, system=_cached(system), messages=messages, tools=tools,
                output_config={"effort": budget.effort},
                betas=[FALLBACK_BETA], fallbacks="default",
            ) as stream:
                response = stream.get_final_message()
            searches_before, fetches_before = spend.searches, spend.fetches
            spend.add(response.model, response.usage)
            searches_left -= spend.searches - searches_before
            fetches_left -= spend.fetches - fetches_before
            texts.extend(b.text for b in response.content if b.type == "text")
            spend.queries += [f"{b.name}: {b.input.get('query') or b.input.get('url')}"
                              for b in response.content if b.type == "server_tool_use" and isinstance(b.input, dict)]
            if response.stop_reason == "refusal":
                spend.notes.append("Research declined by the model; continuing with other evidence.")
                break
            if response.stop_reason != "pause_turn" or spend.over_budget:
                if spend.over_budget:
                    spend.notes.append(f"Budget of ${budget.max_cost_usd_per_lookup:.2f} reached; research stopped.")
                break
            messages = [messages[0], {"role": "assistant", "content": response.content}]
        return "\n".join(texts).strip()

    def extract(self, system: str, prompt: str, schema: type[T], spend: Spend) -> T | None:
        """Structured extraction (no tools); returns a validated instance of `schema`."""
        model = self.policy.models.extraction
        response = self.client.beta.messages.parse(
            model=model, max_tokens=16000, system=_cached(system), messages=[{"role": "user", "content": prompt}],
            output_format=schema, output_config={"effort": self.policy.budget.effort},
            betas=[FALLBACK_BETA], fallbacks="default",
        )
        spend.add(response.model, response.usage)
        if response.stop_reason == "refusal":
            spend.notes.append("Extraction declined by the model.")
            return None
        return response.parsed_output
