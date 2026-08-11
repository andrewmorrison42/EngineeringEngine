"""Tests for development length, laps, curtailment and bar fit.

Anchorage arithmetic is short enough to check by hand, so most of these tests
carry the hand calculation in the docstring and assert against it. The ones
that matter most are the boundary tests -- where a floor takes over from the
main expression, and where a factor hits its bound -- because those are the
branches a spot check will miss.
"""

from __future__ import annotations

import math

import pytest

from austruct.core.exceptions import ModelError
from austruct.design import as3600
from austruct.design.as3600 import constants as C
from austruct.materials import concrete
from austruct.sections import rc_beam

FC = 32.0
FSY = 500.0


@pytest.fixture
def beam_section():
    return rc_beam(
        b=300, D=600, concrete=concrete(FC), cover=40,
        n_bars=4, diameter=20, fitment_diameter=12, fitment_spacing=200,
        name="B1",
    )


# ---------------------------------------------------------------------------
# The k factors
# ---------------------------------------------------------------------------


def test_k1_penalises_bars_with_deep_concrete_below():
    """Bleed water under a bar weakens its bond -- a 30% penalty past 300 mm."""
    assert as3600.development_length(
        20, FC, FSY, cd=25, concrete_cast_below=500
    ).k1 == pytest.approx(1.3)
    assert as3600.development_length(
        20, FC, FSY, cd=25, concrete_cast_below=50
    ).k1 == pytest.approx(1.0)


def test_k1_switches_exactly_at_the_threshold():
    below = as3600.development_length(20, FC, FSY, cd=25, concrete_cast_below=300.0)
    above = as3600.development_length(20, FC, FSY, cd=25, concrete_cast_below=300.1)
    assert below.k1 == pytest.approx(1.0)
    assert above.k1 == pytest.approx(1.3)


def test_k2_falls_as_the_bar_grows():
    """k2 = (132 - d_b)/100, and it sits in the DENOMINATOR, so a bigger bar
    needs a longer development length for two reasons at once."""
    small = as3600.development_length(12, FC, FSY, cd=25)
    large = as3600.development_length(32, FC, FSY, cd=40)
    assert small.k2 == pytest.approx((132 - 12) / 100)
    assert large.k2 == pytest.approx((132 - 32) / 100)
    assert large.k2 < small.k2


def test_k3_rewards_generous_cover_and_is_bounded():
    tight = as3600.development_length(20, FC, FSY, cd=20).k3
    generous = as3600.development_length(20, FC, FSY, cd=200).k3
    assert tight == pytest.approx(1.0)  # cd == db -> no reduction
    assert generous == pytest.approx(C.K3_MIN), "k3 must be floored at 0.7"
    assert C.K3_MIN <= generous <= C.K3_MAX


def test_cd_takes_the_smallest_splitting_dimension():
    """Splitting occurs on the weakest plane, so the minimum governs."""
    assert as3600.cd_dimension(50, clear_spacing=40) == pytest.approx(20.0)
    assert as3600.cd_dimension(15, clear_spacing=400) == pytest.approx(15.0)
    assert as3600.cd_dimension(50, clear_spacing=40, side_cover=10) == pytest.approx(10.0)


def test_cd_ignores_an_infinite_clear_spacing():
    """A single bar reports infinite spacing; that must not poison the min."""
    assert as3600.cd_dimension(45, clear_spacing=float("inf")) == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# Development length
# ---------------------------------------------------------------------------


def test_development_length_matches_the_hand_calculation():
    """N20, f'c 32, fsy 500, cd = 20 so k1 = k3 = 1.0.

        k2      = (132 - 20)/100 = 1.12
        L_sy.tb = 0.5 x 1 x 1 x 500 x 20 / (1.12 x sqrt(32))
                = 5000 / 6.3357 = 789.2 mm
    """
    dev = as3600.development_length(20, FC, FSY, cd=20)
    expected = 0.5 * 500 * 20 / (1.12 * math.sqrt(32))
    assert dev.basic == pytest.approx(expected)
    assert dev.length == pytest.approx(expected)
    assert dev.governed_by == "the main expression"


def test_the_floor_takes_over_for_high_strength_concrete():
    """sqrt(f'c) in the denominator makes the main expression small for strong
    concrete, and the 0.058 f_sy k1 d_b floor is what stops it going silly."""
    dev = as3600.development_length(20, 100.0, FSY, cd=20)
    assert dev.floor > dev.basic
    assert dev.length == pytest.approx(0.058 * 500 * 1.0 * 20)
    assert "floor" in dev.governed_by


def test_absolute_minimum_applies_when_both_expressions_are_small():
    """Needs a small bar AND strong concrete -- an N6 in 32 MPa still gives
    210 mm from the main expression, so the 200 mm floor never bites there.

        d_b = 6, f'c = 100: main = 0.5 x 500 x 6 / (1.26 x 10) = 119 mm
                            floor = 0.058 x 500 x 6            = 174 mm
        both below 200, so the absolute minimum governs.
    """
    dev = as3600.development_length(6, 100.0, FSY, cd=6)
    assert dev.basic < C.LSY_T_ABSOLUTE_MIN
    assert dev.floor < C.LSY_T_ABSOLUTE_MIN
    assert dev.length == pytest.approx(C.LSY_T_ABSOLUTE_MIN)
    assert "absolute minimum" in dev.governed_by


def test_k4_and_k5_reduce_the_length_multiplicatively():
    plain = as3600.development_length(20, FC, FSY, cd=20)
    credited = as3600.development_length(20, FC, FSY, cd=20, k4=0.8, k5=0.9)
    assert credited.length == pytest.approx(plain.length * 0.8 * 0.9)


def test_development_length_grows_with_bar_size():
    lengths = [as3600.development_length(d, FC, FSY, cd=d).length for d in (12, 16, 20, 24, 28)]
    assert lengths == sorted(lengths)


def test_top_steel_needs_more_anchorage_than_bottom_steel():
    top = as3600.development_length(20, FC, FSY, cd=20, concrete_cast_below=600)
    bot = as3600.development_length(20, FC, FSY, cd=20, concrete_cast_below=52)
    assert top.length == pytest.approx(1.3 * bot.length)


def test_cd_can_be_derived_from_cover_instead_of_given():
    derived = as3600.development_length(20, FC, FSY, cover_to_bar=52, clear_spacing=40)
    explicit = as3600.development_length(20, FC, FSY, cd=20)
    assert derived.length == pytest.approx(explicit.length)


def test_missing_both_cd_and_cover_refuses():
    with pytest.raises(ModelError, match="cd"):
        as3600.development_length(20, FC, FSY)


def test_an_absurdly_large_bar_refuses_rather_than_returning_a_negative_length():
    """k2 = (132 - d_b)/100 goes negative past 132 mm. The expression simply
    does not apply there, and a negative length must never be returned."""
    with pytest.raises(ModelError, match="k2"):
        as3600.development_length(140, FC, FSY, cd=100)


def test_zero_bar_diameter_refuses():
    with pytest.raises(ModelError):
        as3600.development_length(0, FC, FSY, cd=20)


# ---------------------------------------------------------------------------
# Compression and laps
# ---------------------------------------------------------------------------


def test_compression_development_is_shorter_than_tension():
    """End bearing carries part of the force, and there is no splitting."""
    tension = as3600.development_length(20, FC, FSY, cd=20).length
    comp = as3600.compression_development_length(20, FC, FSY)
    assert comp < tension


def test_compression_length_matches_the_hand_calculation():
    """0.22 x 500 x 20 / sqrt(32) = 388.9, floor 0.0435 x 500 x 20 = 435.
    The floor governs."""
    assert as3600.compression_development_length(20, FC, FSY) == pytest.approx(435.0)


def test_compression_length_has_an_absolute_minimum():
    assert as3600.compression_development_length(6, FC, FSY) == pytest.approx(
        C.LSY_C_ABSOLUTE_MIN
    )


def test_tension_lap_is_125_percent_of_development_by_default():
    dev = as3600.development_length(20, FC, FSY, cd=20).length
    lap = as3600.lap_length(20, FC, FSY, cd=20)
    assert lap == pytest.approx(1.25 * dev)


def test_the_lap_reduction_needs_BOTH_conditions():
    """k7 drops to 1.0 only when the steel is generous AND the bars are
    staggered. Satisfying one alone is a common unconservative slip."""
    full = as3600.lap_length(20, FC, FSY, cd=20)
    only_staggered = as3600.lap_length(20, FC, FSY, cd=20, staggered=True)
    only_generous = as3600.lap_length(20, FC, FSY, cd=20, generous_steel=True)
    both = as3600.lap_length(20, FC, FSY, cd=20, staggered=True, generous_steel=True)

    assert only_staggered == pytest.approx(full)
    assert only_generous == pytest.approx(full)
    assert both < full
    assert both == pytest.approx(full / 1.25)


def test_compression_lap_is_governed_by_40_db():
    """40 x 20 = 800, vs L_sy.c of 435 and the 300 minimum."""
    assert as3600.lap_length(20, FC, FSY, tension=False) == pytest.approx(800.0)


def test_laps_have_an_absolute_minimum():
    assert as3600.lap_length(6, FC, FSY, cd=6) >= C.LAP_TENSION_ABSOLUTE_MIN
    assert as3600.lap_length(6, FC, FSY, tension=False) >= C.LAP_COMPRESSION_ABSOLUTE_MIN


# ---------------------------------------------------------------------------
# Curtailment and spacing
# ---------------------------------------------------------------------------


def test_curtailment_takes_the_greater_of_D_and_12db():
    assert as3600.curtailment_extension(600, 20) == pytest.approx(600.0)  # D governs
    assert as3600.curtailment_extension(200, 32) == pytest.approx(384.0)  # 12 db governs


def test_minimum_clear_spacing_can_be_governed_by_the_aggregate():
    """Large aggregate with small bars -- a placing problem, not a bond one."""
    assert as3600.minimum_clear_spacing(12, aggregate_size=40) == pytest.approx(53.2)
    assert as3600.minimum_clear_spacing(40, aggregate_size=10) == pytest.approx(40.0)
    assert as3600.minimum_clear_spacing(12, aggregate_size=10) == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Bar fit -- the check a capacity calculation cannot make
# ---------------------------------------------------------------------------


def test_a_reasonable_layout_fits(beam_section):
    result = as3600.check_bar_fit(beam_section, cover=40)
    assert result.passed
    assert result.checks


def test_too_many_bars_fails_and_says_so():
    """M_uo is perfectly happy with twelve N32 in a 300 web. This is the only
    check that isn't."""
    crowded = rc_beam(
        b=300, D=600, concrete=concrete(FC), cover=40,
        n_bars=12, diameter=32, fitment_diameter=12, fitment_spacing=200,
    )
    result = as3600.check_bar_fit(crowded, cover=40)
    assert not result.passed
    assert any("does NOT physically fit" in note for note in result.messages)


def test_a_layer_given_by_area_alone_is_reported_not_silently_passed():
    from austruct.sections import RCSection, RebarLayer, rectangle

    section = RCSection(
        geometry=rectangle(300, 600),
        concrete=concrete(FC),
        layers=(RebarLayer(area=1200.0, depth=540.0),),
    )
    result = as3600.check_bar_fit(section, cover=40)
    assert any("area alone" in note for note in result.messages)
    assert any("not evidence" in note for note in result.messages)


def test_a_single_bar_has_no_spacing_to_check():
    single = rc_beam(
        b=300, D=600, concrete=concrete(FC), cover=40,
        n_bars=1, diameter=20, fitment_diameter=12, fitment_spacing=200,
    )
    result = as3600.check_bar_fit(single, cover=40)
    assert any("single bar" in note for note in result.messages)


def test_large_aggregate_can_fail_a_layout_that_otherwise_fits():
    section = rc_beam(
        b=300, D=600, concrete=concrete(FC), cover=40,
        n_bars=5, diameter=20, fitment_diameter=12, fitment_spacing=200,
    )
    fine = as3600.check_bar_fit(section, cover=40, aggregate_size=10)
    coarse = as3600.check_bar_fit(section, cover=40, aggregate_size=40)
    assert coarse.utilisation > fine.utilisation


# ---------------------------------------------------------------------------
# The composite detailing check
# ---------------------------------------------------------------------------


def test_detailing_reports_lengths_but_does_not_check_without_geometry(beam_section):
    """The package sees a cross-section, not a member. It must not invent an
    available anchorage length."""
    result = as3600.check_detailing(beam_section, cover=40)
    assert any("NOT CHECKED" in note for note in result.messages)
    assert not any("Anchorage available" in c.label for c in result.checks)


def test_supplying_the_anchorage_adds_the_check(beam_section):
    result = as3600.check_detailing(beam_section, cover=40, available_anchorage=1200)
    assert any("Anchorage available" in c.label for c in result.checks)


def test_short_anchorage_fails(beam_section):
    generous = as3600.check_detailing(beam_section, cover=40, available_anchorage=2000)
    stingy = as3600.check_detailing(beam_section, cover=40, available_anchorage=200)
    assert generous.passed
    assert not stingy.passed


def test_detailing_uses_the_section_depth_for_top_steel_cast_below():
    """Top steel in a deep beam attracts k1 = 1.3 automatically."""
    doubly = rc_beam(
        b=300, D=800, concrete=concrete(FC), cover=40,
        n_bars=4, diameter=20, n_top_bars=2, top_diameter=16,
        fitment_diameter=12, fitment_spacing=200,
    )
    result = as3600.check_detailing(doubly, cover=40)
    k1_values = [v.value for k, v in result.intermediates.items() if k.startswith("k1_")]
    assert 1.3 in k1_values, "top steel in an 800 mm beam should attract k1 = 1.3"
    assert 1.0 in k1_values, "bottom steel should not"


def test_detailing_result_is_unverified(beam_section):
    result = as3600.check_detailing(beam_section, cover=40)
    assert not result.provenance.issuable
