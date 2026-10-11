from datetime import date

import pytest

from certifier import Entity, Source, load_policy

LOOKUP = date(2026, 10, 11)


@pytest.fixture(scope="session")
def policy():
    return load_policy()


@pytest.fixture
def entity():
    return Entity(name="Example Corp", website="https://example.com")


def src(tier: int, value: int, as_of: date | None = date(2025, 12, 31), url: str | None = None, **kw) -> Source:
    return Source(url=url or f"https://example.com/t{tier}/{value}/{as_of}", tier=tier, value=value,
                  as_of_date=as_of, **kw)
