# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
from certifier.policy import load_policy


def test_policy_loads_with_v02_decisions(policy):
    assert policy.policy_version == "0.2"
    assert policy.models.research == "claude-sonnet-5-5"
    assert policy.models.extraction == "claude-sonnet-5-5"
    assert policy.budget.max_cost_usd_per_lookup == 0.50
    assert policy.budget.max_web_searches_per_entity == 8
    assert policy.recency.certified_max_age_months == 18
    assert policy.recency.stale_after_months == 24
    assert policy.agreement.corroborates_within == 0.15
    assert policy.agreement.conflict_above == 0.30


def test_tier_classes(policy):
    assert sorted(policy.tiers) == list(range(1, 10))
    assert [policy.tier_class(t) for t in range(1, 10)] == (
        ["primary"] * 2 + ["secondary"] * 4 + ["tertiary"] * 2 + ["unranked"])


def test_confidence_level_names(policy):
    assert policy.confidence_levels[5] == "Certified, corroborated"
    assert policy.confidence_levels[4] == "Certified"
    assert set(policy.confidence_levels) == set(range(6))


def test_policy_path_override(tmp_path, monkeypatch, policy):
    custom = tmp_path / "p.yaml"
    custom.write_text(open("policy.yaml", encoding="utf-8").read().replace('"0.2"', '"9.9"'), encoding="utf-8")
    monkeypatch.setenv("CERTIFIER_POLICY", str(custom))
    assert load_policy().policy_version == "9.9"


def test_research_guidelines_include_full_annual_report(policy):
    assert any("integrated report" in g for g in policy.research_guidelines)
