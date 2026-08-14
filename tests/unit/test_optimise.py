"""Unit tests for the minimum-cost RC section search.

Nothing here verifies AS 3600 constants -- ``check_flexure`` and the
constants it uses are pinned elsewhere. These tests verify the SEARCH: that
every candidate it returns genuinely passes the code check it claims to,
that the cheapest one really is cheapest, that the economics respond to the
relative cost of steel and concrete the way a designer would expect, and
that an impossible grid comes back empty rather than lying.
"""

from __future__ import annotations

import pytest

from austruct.core.exceptions import ModelError
from austruct.core.units import kNm
from austruct.design.as3600 import optimise as opt
from austruct.design.as3600.flexure import check_flexure
from austruct.materials.concrete import concrete


@pytest.fixture
def bounds():
    return opt.SearchBounds(
        width=opt.SizeRange(250, 500, 50),
        depth=opt.SizeRange(400, 900, 50),
    )


@pytest.fixture
def rates():
    return opt.CostRates(concrete_per_m3=180.0, steel_per_tonne=2200.0)


# ---------------------------------------------------------------------------
# SizeRange
# ---------------------------------------------------------------------------


def test_size_range_is_inclusive_of_both_ends():
    values = opt.SizeRange(300, 500, 100).values()
    assert values == (300, 400, 500)


def test_size_range_clamps_the_last_step_to_the_maximum():
    # 300 -> 500 in steps of 150 does not land exactly on 500; the upper
    # bound the caller asked for must still be searched.
    values = opt.SizeRange(300, 500, 150).values()
    assert values[0] == 300
    assert values[-1] == 500


def test_size_range_rejects_a_non_positive_step():
    with pytest.raises(ValueError):
        opt.SizeRange(300, 500, 0)


def test_size_range_rejects_maximum_below_minimum():
    with pytest.raises(ValueError):
        opt.SizeRange(500, 300, 50)


# ---------------------------------------------------------------------------
# CostRates
# ---------------------------------------------------------------------------


def test_cost_rates_reject_non_positive_concrete_rate():
    with pytest.raises(ValueError):
        opt.CostRates(concrete_per_m3=0.0, steel_per_tonne=2200.0)


def test_cost_rates_reject_non_positive_steel_rate():
    with pytest.raises(ValueError):
        opt.CostRates(concrete_per_m3=180.0, steel_per_tonne=-1.0)


# ---------------------------------------------------------------------------
# The search itself
# ---------------------------------------------------------------------------


def test_every_candidate_actually_passes_check_flexure(bounds, rates):
    result = opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates)
    assert result.candidates, "expected at least one feasible candidate"
    for candidate in result.candidates:
        assert candidate.passed
        # Recompute independently -- candidate.check is not just trusted.
        recheck = check_flexure(candidate.section, 300 * kNm)
        assert recheck.passed
        assert recheck.utilisation == pytest.approx(candidate.check.utilisation)


def test_governing_is_the_cheapest_feasible_candidate(bounds, rates):
    result = opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates)
    assert result.governing is result.candidates[0]
    costs = [c.total_cost for c in result.candidates]
    assert costs == sorted(costs)


def test_candidates_are_priced_consistently_with_their_geometry(bounds, rates):
    result = opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates)
    g = result.governing
    section = g.section
    length = g.length

    volume_m3 = section.geometry.area * length * 1e-9
    expected_concrete_cost = volume_m3 * rates.concrete_per_m3
    assert g.concrete_cost == pytest.approx(expected_concrete_cost)

    mass_tonnes = section.total_steel_area * length * opt.STEEL_DENSITY * 1e-9 / 1000.0
    expected_steel_cost = mass_tonnes * rates.steel_per_tonne
    assert g.steel_cost == pytest.approx(expected_steel_cost)

    assert g.total_cost == pytest.approx(g.concrete_cost + g.steel_cost + g.other_cost)


def test_more_expensive_steel_favours_deeper_leaner_sections(bounds):
    """Economics sanity check: as steel gets relatively more expensive, the
    cheapest section should trade steel for concrete -- deeper, less steel."""
    cheap_steel = opt.minimum_cost_section(
        300 * kNm, concrete(32), bounds, opt.CostRates(180.0, 800.0)
    ).governing
    expensive_steel = opt.minimum_cost_section(
        300 * kNm, concrete(32), bounds, opt.CostRates(180.0, 8000.0)
    ).governing

    assert expensive_steel.section.geometry.D >= cheap_steel.section.geometry.D
    assert expensive_steel.section.total_steel_area <= cheap_steel.section.total_steel_area


def test_length_scales_cost_but_not_which_section_governs(bounds, rates):
    at_1m = opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates, length=1000.0)
    at_5m = opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates, length=5000.0)

    assert at_1m.governing.section.geometry.b_top == at_5m.governing.section.geometry.b_top
    assert at_1m.governing.section.geometry.D == at_5m.governing.section.geometry.D
    assert at_5m.governing.total_cost == pytest.approx(5.0 * at_1m.governing.total_cost)


def test_non_positive_length_raises(bounds, rates):
    with pytest.raises(ModelError):
        opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates, length=0.0)


def test_a_grid_too_shallow_to_carry_the_moment_is_reported_infeasible(rates):
    tiny = opt.SearchBounds(
        width=opt.SizeRange(250, 300, 50),
        depth=opt.SizeRange(150, 200, 50),
    )
    result = opt.minimum_cost_section(300 * kNm, concrete(32), tiny, rates)
    assert result.governing is None
    assert result.candidates == ()
    assert result.infeasible == result.trials


def test_a_width_too_narrow_for_any_bar_arrangement_is_skipped(rates):
    # 120 mm is too narrow to fit even 2-N12 with 40 mm cover and a 12 mm
    # fitment either side, at any depth -- so nothing at this width should
    # ever appear in the results, even though the depth range is generous.
    narrow = opt.SearchBounds(
        width=opt.SizeRange(120, 120, 50),
        depth=opt.SizeRange(600, 900, 50),
        diameters=(28, 32, 36),
    )
    result = opt.minimum_cost_section(300 * kNm, concrete(32), narrow, rates)
    assert result.governing is None


def test_other_cost_rate_adds_a_flat_allowance_without_changing_the_winner(bounds, rates):
    plain = opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates)
    with_allowance = opt.minimum_cost_section(
        300 * kNm,
        concrete(32),
        bounds,
        opt.CostRates(rates.concrete_per_m3, rates.steel_per_tonne, other_cost_rate=50.0),
    )
    # Same flat addition to every candidate at length 1 m, so the ranking is
    # unaffected -- only the totals shift.
    assert with_allowance.governing.section.layers == plain.governing.section.layers
    assert with_allowance.governing.section.geometry.D == plain.governing.section.geometry.D
    assert with_allowance.governing.other_cost == pytest.approx(50.0)
    assert with_allowance.governing.total_cost == pytest.approx(plain.governing.total_cost + 50.0)


def test_describe_reports_trial_counts_and_the_governing_section(bounds, rates):
    result = opt.minimum_cost_section(300 * kNm, concrete(32), bounds, rates)
    lines = "\n".join(result.describe())
    assert f"Searched {result.trials} sizes" in lines
    assert "Governing" in lines


def test_describe_on_an_infeasible_search_says_so_rather_than_indexing_none(rates):
    tiny = opt.SearchBounds(
        width=opt.SizeRange(250, 300, 50),
        depth=opt.SizeRange(150, 200, 50),
    )
    result = opt.minimum_cost_section(300 * kNm, concrete(32), tiny, rates)
    lines = "\n".join(result.describe())
    assert "No feasible section" in lines
