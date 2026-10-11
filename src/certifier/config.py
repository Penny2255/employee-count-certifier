"""Credentials from .env (never committed): ANTHROPIC_API_KEY, SEC_USER_AGENT."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


@lru_cache(maxsize=1)
def load_env() -> None:
    load_dotenv(ENV_PATH)


def sec_user_agent() -> str:
    load_env()
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise RuntimeError("SEC_USER_AGENT is not set; SEC EDGAR requires a User-Agent with contact info.")
    return ua


def has_anthropic_key() -> bool:
    load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
