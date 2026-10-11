"""Every file in examples/ is a regression test: the engine must reproduce its expected result."""

import pytest

from certifier import certify
from certifier.examples import load_examples

EXAMPLES = load_examples()


def test_examples_exist():
    assert len(EXAMPLES) >= 7


@pytest.mark.parametrize("ex", EXAMPLES, ids=[e.path.stem for e in EXAMPLES])
def test_example(ex):
    cert = certify(ex.entity, ex.sources, linkedin=ex.linkedin, lookup_date=ex.lookup_date,
                   event_flags=ex.event_flags)
    exp = ex.expected
    assert cert.certified_count == exp.certified_count
    assert cert.confidence_score == exp.confidence_score
    for field in ("qualifier", "count_type", "policy_tier", "range"):
        if getattr(exp, field) is not None:
            assert getattr(cert, field) == getattr(exp, field), field
    if exp.selected_url:
        assert [s.url for s in cert.sources if s.role == "selected"] == [exp.selected_url]
