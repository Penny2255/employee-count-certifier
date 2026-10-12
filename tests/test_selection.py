# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
from datetime import date

from certifier.rules import is_stale, select_source, within_months

from .conftest import LOOKUP, src


def sel(policy, *sources):
    return select_source(list(sources), LOOKUP, policy)


def test_within_months():
    assert within_months(date(2025, 4, 11), LOOKUP, 18)
    assert not within_months(date(2025, 4, 10), LOOKUP, 18)
    assert within_months(date(2024, 2, 29), date(2026, 2, 28), 24)  # month-end clamping
    assert not within_months(date(2024, 2, 27), date(2026, 2, 28), 24)


def test_stale_uses_as_of_then_published(policy):
    assert not is_stale(src(3, 1, as_of=date(2024, 10, 11)), LOOKUP, policy)  # exactly 24 months
    assert is_stale(src(3, 1, as_of=date(2024, 10, 10)), LOOKUP, policy)
    assert is_stale(src(3, 1, as_of=None, published_date=date(2023, 1, 1)), LOOKUP, policy)
    assert not is_stale(src(3, 1, as_of=None), LOOKUP, policy)  # fully undated is never stale


def test_highest_tier_wins(policy):
    t1, t4 = src(1, 1_000), src(4, 1_200, as_of=date(2026, 9, 1))
    assert sel(policy, t4, t1).selected is t1


def test_newest_within_tier_wins(policy):
    old, new = src(1, 900, as_of=date(2024, 12, 31)), src(1, 1_000, as_of=date(2025, 12, 31))
    assert sel(policy, old, new).selected is new


def test_dated_beats_undated_within_tier(policy):
    undated, dated = src(4, 900, as_of=None), src(4, 1_000, as_of=date(2025, 1, 1))
    assert sel(policy, undated, dated).selected is dated


def test_exact_beats_qualified_on_tie(policy):
    qualified, exact = src(1, 69_500, qualifier="more_than"), src(1, 69_505, url="https://x/exact")
    assert sel(policy, qualified, exact).selected is exact


# --- Specificity: detailed figures beat rounded statements when in line (SAP, Novo) ---

def test_detailed_figure_in_line_with_more_than_wins(policy):
    headline = src(1, 110_000, qualifier="more_than", url="https://x/20f")
    detailed = src(1, 112_234, url="https://x/annual-report")
    result = sel(policy, headline, detailed)
    assert result.selected is detailed
    assert result.flags == []
    assert any("More specific figure 112,234" in n for n in result.notes)


def test_more_precise_approximate_beats_rounder_one(policy):
    rounded = src(1, 100_000, qualifier="more_than", url="https://x/a")
    precise = src(1, 112_200, qualifier="approximately", url="https://x/b")
    assert sel(policy, rounded, precise).selected is precise


def test_detailed_figure_below_more_than_is_not_in_line(policy):
    headline = src(1, 110_000, qualifier="more_than", url="https://x/20f")
    detailed = src(1, 105_000, url="https://x/table")
    result = sel(policy, headline, detailed)
    assert result.selected is headline
    assert result.inconsistent == [detailed]
    assert "not in line" in result.flags[0]


def test_detailed_figure_too_far_from_approximately_is_not_in_line(policy):
    headline = src(1, 100_000, qualifier="approximately", url="https://x/a")
    detailed = src(1, 120_000, url="https://x/b")
    assert sel(policy, headline, detailed).selected is headline


def test_detailed_figure_above_up_to_is_not_in_line(policy):
    headline = src(1, 5_000, qualifier="up_to", url="https://x/a")
    assert sel(policy, headline, src(1, 5_120, url="https://x/b")).selected is headline
    assert sel(policy, headline, src(1, 4_870, url="https://x/c")).selected.value == 4_870


def test_unrelated_figure_in_same_document_does_not_block_specific_one(policy):
    exact = src(1, 69_505, url="https://x/a")
    rounded = src(1, 69_500, qualifier="more_than", url="https://x/b")
    layoffs = src(1, 9_000, qualifier="approximately", url="https://x/c")  # "9,000 employees were let go"
    assert sel(policy, exact, rounded, layoffs).selected is exact


def test_specificity_only_among_same_tier_and_date(policy):
    newer_rounded = src(1, 110_000, qualifier="more_than", as_of=date(2025, 12, 31), url="https://x/a")
    older_exact = src(1, 108_123, as_of=date(2024, 12, 31), url="https://x/b")
    assert sel(policy, newer_rounded, older_exact).selected is newer_rounded
    tier3_exact = src(3, 112_234, url="https://x/c")
    assert sel(policy, newer_rounded, tier3_exact).selected is newer_rounded


def test_secondary_overrides_stale_primary_only_when_newer_and_dated(policy):
    stale_primary = src(1, 1_000, as_of=date(2023, 12, 31))
    newer_secondary = src(3, 1_500, as_of=date(2026, 3, 1))
    result = sel(policy, stale_primary, newer_secondary)
    assert result.selected is newer_secondary
    assert any("overrides" in n for n in result.notes)


def test_undated_secondary_does_not_override_stale_primary(policy):
    stale_primary = src(1, 1_000, as_of=date(2023, 12, 31))
    assert sel(policy, stale_primary, src(4, 1_500, as_of=None)).selected is stale_primary


def test_secondary_does_not_override_fresh_primary(policy):
    primary = src(1, 1_000, as_of=date(2025, 1, 31))  # 20 months: not Certified-recent, but not stale
    assert sel(policy, primary, src(3, 1_500, as_of=date(2026, 9, 1))).selected is primary


def test_tertiary_never_overrides_primary(policy):
    stale_primary = src(1, 1_000, as_of=date(2020, 12, 31))
    assert sel(policy, stale_primary, src(7, 5_000, as_of=date(2026, 9, 1))).selected is stale_primary


def test_tertiary_does_not_override_secondary(policy):
    secondary = src(4, 1_000, as_of=None)
    assert sel(policy, secondary, src(7, 5_000, as_of=date(2026, 9, 1))).selected is secondary


def test_stale_secondary_is_supporting_only(policy):
    stale = src(3, 1_000, as_of=date(2022, 1, 1))
    tertiary = src(7, 1_100, as_of=date(2026, 6, 1))
    result = sel(policy, stale, tertiary)
    assert result.selected is None
    assert result.derive_from == [tertiary]


def test_partial_scope_never_selected(policy):
    regional = src(1, 800, scope="partial")
    global_ = src(4, 1_000, as_of=None)
    result = sel(policy, regional, global_)
    assert result.selected is global_
    assert any("partial-scope" in n for n in result.notes)


def test_nothing_found(policy):
    result = sel(policy)
    assert result.selected is None and result.derive_from == []
