"""Tests for fatigue assessment.

The property that matters most is that fatigue responds to the RANGE and not
the peak, so the tests lean on that: adding permanent load to both ends of the
cycle must not change the answer, while widening the cycle must.
"""

from __future__ import annotations

import pytest

from austruct.analysis import (
    UDL,
    LoadTrain,
    moving_load_envelope,
    simply_supported,
)
from austruct.core.exceptions import ModelError
from austruct.core.units import kN, kN_per_m, kNm, m
from austruct.design import as5100_5
from austruct.design.as5100_5 import constants as C
from austruct.materials import concrete
from austruct.sections import rc_beam

SPAN = 20.0 * m


@pytest.fixture
def girder():
    return rc_beam(
        b=600, D=1200, concrete=concrete(40), cover=40,
        n_bars=8, diameter=32, fitment_diameter=12, fitment_spacing=200,
        name="Girder",
    )


@pytest.fixture
def swept():
    """A 200 kN axle crossing a 20 m span, on a 30 kN/m permanent load."""
    beam = simply_supported(SPAN, EI=1e15, name="BR1")
    return moving_load_envelope(
        beam,
        LoadTrain("axle", axles=((0.0, 200 * kN),)),
        step=250.0,
        static_loads=(UDL(magnitude=30 * kN_per_m),),
    )


# ---------------------------------------------------------------------------
# The stress range itself
# ---------------------------------------------------------------------------


def test_range_is_the_difference_between_the_two_ends(girder):
    rng = as5100_5.stress_range(girder, 800 * kNm, 300 * kNm)
    assert rng.delta == pytest.approx(rng.f_max - rng.f_min)
    assert rng.f_max > rng.f_min > 0


def test_permanent_load_cancels_out_of_the_range(girder):
    """The defining property. Raising both ends of the cycle by the same
    moment leaves the range untouched -- fatigue does not care where the
    cycle sits, only how wide it is."""
    narrow = as5100_5.stress_range(girder, 500 * kNm, 300 * kNm)
    shifted = as5100_5.stress_range(girder, 1500 * kNm, 1300 * kNm)
    assert shifted.delta == pytest.approx(narrow.delta)
    assert shifted.f_max > narrow.f_max, "the cycle did move, it just stayed as wide"


def test_a_wider_cycle_gives_a_bigger_range(girder):
    narrow = as5100_5.stress_range(girder, 900 * kNm, 800 * kNm)
    wide = as5100_5.stress_range(girder, 900 * kNm, 100 * kNm)
    assert wide.delta > narrow.delta


def test_a_static_load_has_no_range_at_all(girder):
    """No variation, no fatigue. A member that never cycles cannot fatigue."""
    rng = as5100_5.stress_range(girder, 900 * kNm, 900 * kNm)
    assert rng.delta == pytest.approx(0.0)


def test_compression_at_the_low_end_is_taken_as_zero_not_negative(girder):
    """A bar unloads to zero and the concrete takes over; it does not go into
    meaningful compression while the section is cracked."""
    rng = as5100_5.stress_range(girder, 900 * kNm, -400 * kNm)
    assert rng.f_min == 0.0
    assert rng.delta == pytest.approx(rng.f_max)
    assert rng.reversal


def test_no_reversal_flag_when_the_moment_keeps_its_sign(girder):
    assert not as5100_5.stress_range(girder, 900 * kNm, 100 * kNm).reversal


def test_the_arguments_must_be_in_order(girder):
    with pytest.raises(ModelError, match="less than"):
        as5100_5.stress_range(girder, 100 * kNm, 900 * kNm)


# ---------------------------------------------------------------------------
# Limits by detail
# ---------------------------------------------------------------------------


def test_the_detail_governs_not_the_bar():
    straight = as5100_5.stress_range_limit("straight")
    welded = as5100_5.stress_range_limit("welded")
    assert straight > as5100_5.stress_range_limit("bent") > welded


def test_detail_lookup_is_case_insensitive():
    assert as5100_5.stress_range_limit("STRAIGHT") == as5100_5.stress_range_limit("straight")


def test_an_unknown_detail_refuses_and_lists_the_options():
    """A typo must not fall back to the most permissive category."""
    with pytest.raises(KeyError) as exc:
        as5100_5.stress_range_limit("bolted")
    assert "welded" in str(exc.value)


def test_the_reference_cycle_count_returns_the_reference_limit():
    assert as5100_5.stress_range_limit(
        "straight", C.FATIGUE_CYCLES_REFERENCE
    ) == pytest.approx(as5100_5.stress_range_limit("straight"))


def test_more_cycles_lower_the_limit():
    at_2m = as5100_5.stress_range_limit("straight", 2e6)
    at_10m = as5100_5.stress_range_limit("straight", 10e6)
    at_1m = as5100_5.stress_range_limit("straight", 1e6)
    assert at_1m > at_2m > at_10m


def test_the_sn_adjustment_follows_the_stated_exponent():
    """(delta_f)^m . N = constant."""
    base = as5100_5.stress_range_limit("straight")
    doubled = as5100_5.stress_range_limit("straight", 2 * C.FATIGUE_CYCLES_REFERENCE)
    assert doubled == pytest.approx(base * 0.5 ** (1.0 / C.FATIGUE_SN_EXPONENT))


def test_a_non_positive_cycle_count_refuses():
    with pytest.raises(ModelError, match="positive"):
        as5100_5.stress_range_limit("straight", 0.0)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def test_check_produces_a_contract_result(girder):
    result = as5100_5.check_fatigue(girder, 900 * kNm, 300 * kNm)
    assert "delta_f" in result.outputs
    assert result.checks
    assert not result.provenance.issuable


def test_a_welded_detail_can_fail_what_a_straight_one_passes(girder):
    straight = as5100_5.check_fatigue(girder, 900 * kNm, 300 * kNm, "straight")
    welded = as5100_5.check_fatigue(girder, 900 * kNm, 300 * kNm, "welded")
    assert welded.utilisation > straight.utilisation
    assert welded.get("delta_f") == pytest.approx(straight.get("delta_f"))


def test_the_default_detail_is_flagged_as_the_permissive_one(girder):
    result = as5100_5.check_fatigue(girder, 900 * kNm, 300 * kNm)
    assert any("most permissive" in note for note in result.messages)


def test_a_reversal_is_flagged_as_only_half_checked(girder):
    result = as5100_5.check_fatigue(girder, 900 * kNm, -300 * kNm)
    assert any("REVERSES" in note for note in result.messages)


def test_the_sn_adjustment_is_flagged_as_unverified(girder):
    result = as5100_5.check_fatigue(girder, 900 * kNm, 300 * kNm, n_cycles=5e6)
    assert any("UNVERIFIED" in note for note in result.messages)


# ---------------------------------------------------------------------------
# Straight off a sweep -- what the moving-load machinery is for
# ---------------------------------------------------------------------------


def test_fatigue_reads_the_cycle_off_a_moving_load_result(girder, swept):
    result = as5100_5.fatigue_from_envelope(girder, swept)
    assert result.get("delta_f") > 0
    assert "position" in result.inputs


def test_either_a_result_or_its_envelope_may_be_passed(girder, swept):
    """Both are natural things to have after a sweep."""
    from_result = as5100_5.fatigue_from_envelope(girder, swept)
    from_envelope = as5100_5.fatigue_from_envelope(girder, swept.envelope)
    assert from_result.get("delta_f") == pytest.approx(from_envelope.get("delta_f"))


def test_the_cycle_comes_from_the_envelope_not_the_peak_alone(girder, swept):
    """max_values and min_values at ONE position are the two ends of the
    cycle. Taking the global max and the global min instead would invent a
    cycle no section ever sees."""
    moment = swept.envelope.moment
    i = moment.peak_max_index
    expected = as5100_5.stress_range(
        girder, float(moment.max_values[i]), float(moment.min_values[i])
    )
    result = as5100_5.fatigue_from_envelope(girder, swept)
    assert result.get("delta_f") == pytest.approx(expected.delta)


def test_a_specific_position_can_be_asked_for(girder, swept):
    quarter = as5100_5.fatigue_from_envelope(girder, swept, position=SPAN / 4)
    assert quarter.inputs["position"].value == pytest.approx(SPAN / 4, abs=300.0)


def test_worst_position_is_at_least_as_bad_as_any_other(girder, swept):
    pos, worst = as5100_5.worst_fatigue_position(girder, swept)
    assert worst > 0
    for trial in (SPAN / 4, SPAN / 2, 3 * SPAN / 4):
        result = as5100_5.fatigue_from_envelope(girder, swept, position=trial)
        assert result.get("delta_f") <= worst + 1e-6
    assert 0.0 <= pos <= SPAN


def test_a_heavier_permanent_load_does_not_worsen_fatigue(girder):
    """The counter-intuitive one, and the reason fatigue is checked separately
    from strength: more dead load raises the stress but not the range."""
    beam = simply_supported(SPAN, EI=1e15)
    train = LoadTrain("axle", axles=((0.0, 200 * kN),))

    light = moving_load_envelope(
        beam, train, step=500.0, static_loads=(UDL(magnitude=10 * kN_per_m),)
    )
    heavy = moving_load_envelope(
        beam, train, step=500.0, static_loads=(UDL(magnitude=60 * kN_per_m),)
    )

    _, light_range = as5100_5.worst_fatigue_position(girder, light)
    _, heavy_range = as5100_5.worst_fatigue_position(girder, heavy)
    assert heavy_range == pytest.approx(light_range, rel=0.02)


def test_concrete_fatigue_check(girder):
    result = as5100_5.check_concrete_fatigue(girder, 900 * kNm)
    assert result.get("f_c") > 0
    assert result.checks[0].limit == pytest.approx(0.5 * girder.concrete.fc)
