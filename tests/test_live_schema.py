# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
"""Live check that the extraction schema compiles under the API's structured-output grammar limit.
Near-zero cost (tiny prompt). Run with RUN_LIVE=1 before shipping any change to research.py's schemas."""

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live API test; set RUN_LIVE=1")


def test_extraction_schema_compiles():
    from certifier.config import load_env
    from certifier.llm import Claude, Spend
    from certifier.policy import default_policy
    from certifier.research import Extraction

    load_env()
    policy = default_policy()
    result = Claude(policy).extract("Return empty lists and the default values.", "No sources were found.",
                                    Extraction, Spend(policy))
    assert result is not None and result.sources == []
