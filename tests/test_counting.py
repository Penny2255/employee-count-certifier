# © 2026 Matthew Beltrano. All rights reserved. Proprietary and confidential. Not open source. See LICENSE.
from certifier import certify
from certifier.rules import apply_counting_rules, qualifier_range

from .conftest import LOOKUP, src


def test_contractors_subtracted_and_logged():
    value, log = apply_counting_rules(src(1, 12_400, contractors_included=1_100))
    assert value == 11_300
    assert len(log) == 1
    assert (log[0].source_figure, log[0].change, log[0].result) == (12_400, -1_100, 11_300)
    assert "contractor" in log[0].reason


def test_worker_types_summed():
    value, log = apply_counting_rules(src(1, 0, components={"full_time": 9_000, "part_time": 2_500, "seasonal": 500}))
    assert value == 12_000
    assert log[0].result == 12_000


def test_separately_reported_categories_noted_not_added(entity):
    # IPEDS: "Total all staff (excludes graduate assistants)"; graduate assistants listed separately.
    source = src(2, 15_029, separately_reported={"graduate assistants": 4_000})
    value, log = apply_counting_rules(source)
    assert value == 15_029
    assert log[0].change == 0 and "graduate assistants (4,000)" in log[0].reason
    cert = certify(entity, [source], lookup_date=LOOKUP)
    assert (cert.certified_count, cert.count_type) == (15_029, "reported")


def test_no_breakdown_means_full_count():
    value, log = apply_counting_rules(src(1, 12_400))
    assert value == 12_400
    assert log == []


def test_adjusted_value_is_calculated(entity):
    cert = certify(entity, [src(1, 12_400, contractors_included=1_100)], lookup_date=LOOKUP)
    assert cert.certified_count == 11_300
    assert cert.count_type == "calculated"
    assert cert.adjustments[0].result == 11_300


def test_unadjusted_value_is_reported(entity):
    cert = certify(entity, [src(1, 12_400)], lookup_date=LOOKUP)
    assert cert.count_type == "reported"
    assert cert.adjustments == []


def test_qualified_value_recorded_as_stated(entity, policy):
    cert = certify(entity, [src(1, 5_000, qualifier="more_than")], lookup_date=LOOKUP)
    assert cert.certified_count == 5_000
    assert cert.qualifier == "more_than"
    assert cert.range == (5_000, 5_500)


def test_range_bands(policy):
    assert qualifier_range(10_000, "exact", policy) == (10_000, 10_000)
    assert qualifier_range(10_000, "approximately", policy) == (9_500, 10_500)
    assert qualifier_range(10_000, "more_than", policy) == (10_000, 11_000)
    assert qualifier_range(10_000, "up_to", policy) == (9_000, 10_000)
