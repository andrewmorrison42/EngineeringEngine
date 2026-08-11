"""Unit tests for moving loads, AS 5100.2 traffic models and fill dispersal.

The moving-load tests lean on closed-form results for a simply supported span,
because those are what an engineer would check the answer against by hand.
"""

from __future__ import annotations

import math

import pytest

from austruct.analysis import (
    LoadTrain,
    influence_line,
    moving_load_envelope,
    simply_supported,
    sweep_positions,
)
from austruct.analysis.moving import _position_from_label
from austruct.core.exceptions import ModelError
from austruct.core.units import kN, kN_per_m, kNm, m
from austruct.loads import FillDispersal, buried_structure_loads
from austruct.loads import as5100_2 as traffic

EI = 1e15
L = 20.0 * m


@pytest.fixture
def beam():
    return simply_supported(L, EI=EI, name="BR1")


# ---------------------------------------------------------------------------
# LoadTrain
# ---------------------------------------------------------------------------


def test_train_places_axles_at_offsets_from_the_datum():
    train = LoadTrain("t", axles=((0.0, 100 * kN), (3000.0, 60 * kN)), length=3000.0)
    loads = train.at(5000.0, L)
    positions = sorted(p for load in loads for p, _ in load.point_forces())
    assert positions == [5000.0, 8000.0]


def test_train_drops_axles_that_fall_off_the_member():
    train = LoadTrain("t", axles=((0.0, 100 * kN), (3000.0, 60 * kN)), length=3000.0)
    assert len(train.at(-2000.0, L)) == 1, "leading axle is off the left end"
    assert train.at(-5000.0, L) == (), "whole train is clear of the member"


def test_train_clips_distributed_components_to_the_member():
    train = LoadTrain("t", udl_segments=((0.0, 5000.0, 10 * kN_per_m),), length=5000.0)
    (load,) = train.at(-2000.0, L)
    assert load.start == 0.0
    assert load.end == 3000.0


def test_train_scaling_leaves_geometry_alone():
    train = LoadTrain("t", axles=((0.0, 100 * kN), (3000.0, 60 * kN)), length=3000.0)
    scaled = train.scaled(1.35)
    assert scaled.total_axle_load == pytest.approx(1.35 * train.total_axle_load)
    assert [o for o, _ in scaled.axles] == [o for o, _ in train.axles]
    assert scaled.length == train.length


def test_sweep_runs_the_train_on_and_off_both_ends():
    train = LoadTrain("t", axles=((0.0, 1.0),), length=4000.0)
    positions = sweep_positions(train, L, 500.0)
    assert positions[0] == pytest.approx(-4000.0)
    assert positions[-1] == pytest.approx(L)


def test_sweep_includes_positions_placing_an_axle_on_a_support():
    """A uniform sweep only gets within half a step of a support, which
    understates the peak support shear."""
    train = LoadTrain("t", axles=((0.0, 1.0), (3333.0, 1.0)), length=3333.0)
    positions = sweep_positions(train, L, 500.0, critical_positions=(0.0, L))
    assert any(abs(p - (-3333.0)) < 1e-6 for p in positions)
    assert any(abs(p - (L - 3333.0)) < 1e-6 for p in positions)


# ---------------------------------------------------------------------------
# Moving load envelope vs closed form
# ---------------------------------------------------------------------------


def test_single_moving_load_gives_PL_over_4(beam):  # noqa: N802
    P = 100 * kN
    result = moving_load_envelope(beam, LoadTrain("P", axles=((0.0, P),)), step=100.0)
    assert result.M_star == pytest.approx(P * L / 4, rel=1e-6)
    assert result.critical_position("moment") == pytest.approx(L / 2, abs=100.0)


def test_two_axle_train_matches_the_closed_form(beam):
    """For two equal loads P at spacing a, the maximum moment is
    P(2L - a)^2 / (8L), with the resultant and the nearer load straddling
    midspan."""
    P = 100 * kN
    a = 4.0 * m
    train = LoadTrain("2ax", axles=((0.0, P), (a, P)), length=a)
    result = moving_load_envelope(beam, train, step=50.0)
    assert result.M_star == pytest.approx(P * (2 * L - a) ** 2 / (8 * L), rel=1e-4)


def test_moving_udl_longer_than_the_span_reduces_to_a_full_udl(beam):
    w = 10 * kN_per_m
    train = LoadTrain("udl", udl_segments=((0.0, 3 * L, w),), length=3 * L)
    result = moving_load_envelope(beam, train, step=250.0)
    assert result.M_star == pytest.approx(w * L**2 / 8, rel=1e-4)
    assert result.V_star == pytest.approx(w * L / 2, rel=1e-4)


def test_governing_position_is_recorded_and_parseable(beam):
    P = 100 * kN
    result = moving_load_envelope(beam, LoadTrain("P", axles=((0.0, P),)), step=100.0)
    label = result.envelope.moment.governing_combo
    assert label.startswith("x=")
    assert _position_from_label(label) == pytest.approx(
        result.critical_position("moment")
    )


def test_static_loads_are_present_at_every_position(beam):
    from austruct.analysis import UDL

    w = 5 * kN_per_m
    train = LoadTrain("P", axles=((0.0, 100 * kN),))
    with_static = moving_load_envelope(
        beam, train, step=250.0, static_loads=(UDL(magnitude=w),)
    )
    without = moving_load_envelope(beam, train, step=250.0)
    assert with_static.M_star > without.M_star
    assert with_static.M_star == pytest.approx(
        without.M_star + w * L**2 / 8, rel=1e-3
    )


def test_all_sweep_positions_share_one_grid(beam):
    train = LoadTrain("2ax", axles=((0.0, 100 * kN), (4000.0, 100 * kN)), length=4000.0)
    result = moving_load_envelope(beam, train, step=500.0)
    grids = {tuple(r.x) for r in result.envelope.case_results.values()}
    assert len(grids) == 1


def test_train_that_never_lands_raises(beam):
    train = LoadTrain("t", axles=((0.0, 0.0),), length=0.0)
    with pytest.raises(ValueError, match="never lands"):
        moving_load_envelope(beam, train, step=1000.0)


def test_negative_step_raises():
    train = LoadTrain("t", axles=((0.0, 1.0),))
    with pytest.raises(ModelError, match="step"):
        sweep_positions(train, L, -1.0)


# ---------------------------------------------------------------------------
# Influence lines
# ---------------------------------------------------------------------------


def test_moment_influence_line_peaks_at_L_over_4(beam):  # noqa: N802
    il = influence_line(beam, "moment", location=L / 2, n_points=81)
    assert il.peak == pytest.approx(L / 4, rel=1e-6)
    assert il.peak_position == pytest.approx(L / 2, abs=L / 80)


def test_moment_influence_line_area_reproduces_a_full_udl(beam):
    """The standard hand check: UDL effect = intensity x area under the line."""
    il = influence_line(beam, "moment", location=L / 2, n_points=81)
    w = 10 * kN_per_m
    assert w * il.area == pytest.approx(w * L**2 / 8, rel=1e-3)


def test_reaction_influence_line_runs_from_one_to_zero(beam):
    il = influence_line(beam, "reaction", location=0.0, n_points=41)
    assert il.at(0.0) == pytest.approx(1.0, abs=1e-6)
    assert il.at(L) == pytest.approx(0.0, abs=1e-6)
    assert il.at(L / 2) == pytest.approx(0.5, abs=1e-3)


def test_shear_influence_line_steps_by_one_at_the_section(beam):
    """The shear line is discontinuous at the section it is measured at."""
    il = influence_line(beam, "shear", location=L / 4, n_points=81, side="right")
    delta = max(1.0, L * 1e-4)
    jump = il.at(L / 4 + delta) - il.at(L / 4 - delta)
    assert jump == pytest.approx(1.0, abs=1e-3)
    assert il.at(L / 4 + delta) == pytest.approx(0.75, abs=1e-3)
    assert il.at(L / 4 - delta) == pytest.approx(-0.25, abs=1e-3)


def test_influence_line_works_on_an_indeterminate_member():
    """Two equal spans: the hogging influence line at the centre support peaks
    at about -0.096 L."""
    from austruct.analysis import continuous

    c = continuous([L, L], EI=EI, name="C2")
    il = influence_line(c, "moment", location=L, n_points=61)
    assert il.values.min() == pytest.approx(-0.0962 * L, rel=0.02)
    assert il.values.max() <= 1e-6, "no sagging anywhere in this line"


def test_bad_response_and_side_raise(beam):
    with pytest.raises(ValueError, match="response"):
        influence_line(beam, "torsion", location=L / 2)
    with pytest.raises(ValueError, match="side"):
        influence_line(beam, "shear", location=L / 2, side="middle")


# ---------------------------------------------------------------------------
# AS 5100.2 traffic models
#
# The catalogue itself -- nominating a model by name, what each model carries,
# and the unverified-geometry guard -- is tested in test_traffic_catalogue.py.
# What belongs here is only the interaction between a traffic model and the
# moving-load machinery above.
# ---------------------------------------------------------------------------


def test_m1600_swept_over_a_span_finds_a_sensible_position(beam):
    with traffic.unverified_ok():
        train = traffic.get("M1600").train_with_dla()
    result = moving_load_envelope(beam, train, step=500.0)
    assert result.M_star > 0
    assert 0.0 <= result.critical_position("moment") + train.length <= L + train.length


# ---------------------------------------------------------------------------
# Fill dispersal
# ---------------------------------------------------------------------------


def test_zero_fill_applies_exactly_the_wheel_load():
    """Regression: multiplying the pressure by the full strip width rather than
    the dispersed width turned an 80 kN wheel into 200 kN."""
    fill = FillDispersal(depth=0.0, effective_width=1000.0)
    load, cl, cw = 80 * kN, 250.0, 400.0
    patch = fill.disperse_wheel(load, 3000.0, cl, cw, 6000.0)
    assert patch.total() == pytest.approx(load, rel=1e-9)


@pytest.mark.parametrize("depth", [0.0, 300.0, 1000.0, 3000.0])
def test_dispersed_load_equals_the_share_landing_on_the_strip(depth):
    fill = FillDispersal(depth=depth, effective_width=1000.0)
    load, cl, cw = 80 * kN, 250.0, 400.0
    patch = fill.disperse_wheel(load, 3000.0, cl, cw, 6000.0)
    share = min(fill.spread(cw), fill.effective_width) / fill.spread(cw)
    assert patch.total() == pytest.approx(load * share, rel=1e-9)


def test_deeper_fill_spreads_further_and_reduces_pressure():
    shallow = FillDispersal(depth=300.0)
    deep = FillDispersal(depth=2000.0)
    assert deep.spread(250.0) > shallow.spread(250.0)
    assert deep.wheel_pressure(80 * kN, 250.0, 400.0) < shallow.wheel_pressure(
        80 * kN, 250.0, 400.0
    )


def test_earth_pressure_grows_linearly_with_depth():
    a = FillDispersal(depth=1000.0, density=2000.0, effective_width=1000.0)
    b = FillDispersal(depth=2000.0, density=2000.0, effective_width=1000.0)
    assert b.vertical_pressure == pytest.approx(2 * a.vertical_pressure)
    # 2000 kg/m^3 over 1 m is about 19.6 kPa.
    assert a.vertical_pressure * 1e3 == pytest.approx(19.62, rel=1e-3)


def test_shallow_fill_governs_live_load_and_deep_fill_governs_dead_load():
    """The reason a buried structure needs both extremes checked."""
    span = 6.0 * m
    beam = simply_supported(span, EI=1e14, name="TS")
    load, cl, cw = 80 * kN, 250.0, 400.0

    def moments(depth):
        fill = FillDispersal(depth=depth, effective_width=1000.0)
        wheel = beam.with_loads(
            (fill.disperse_wheel(load, span / 2, cl, cw, span),)
        ).solve()
        earth = beam.with_loads((fill.earth_pressure_udl(),)).solve()
        return wheel.max_moment, earth.max_moment

    shallow_wheel, shallow_earth = moments(300.0)
    deep_wheel, deep_earth = moments(3000.0)

    assert shallow_wheel > deep_wheel
    assert deep_earth > shallow_earth


def test_patch_load_moment_matches_the_closed_form():
    """A total load W spread over length a at midspan gives M = W(L/4 - a/8)."""
    span = 6.0 * m
    fill = FillDispersal(depth=0.0, effective_width=1000.0)
    load, cl, cw = 80 * kN, 250.0, 400.0
    patch = fill.disperse_wheel(load, span / 2, cl, cw, span)
    result = simply_supported(span, EI=1e14).with_loads((patch,)).solve()
    assert result.max_moment == pytest.approx(load * (span / 4 - cl / 8), rel=1e-6)


def test_transverse_coverage_flags_a_patch_narrower_than_the_strip():
    narrow = FillDispersal(depth=0.0, effective_width=1000.0)
    wide = FillDispersal(depth=2000.0, effective_width=1000.0)
    assert narrow.transverse_coverage(400.0) < 1.0
    assert wide.transverse_coverage(400.0) > 1.0


def test_overlapping_patches_superpose():
    """Two wheels close together must add where their patches overlap."""
    span = 6.0 * m
    fill = FillDispersal(depth=1500.0, effective_width=1000.0)
    load, cl, cw = 80 * kN, 250.0, 400.0
    loads = buried_structure_loads(
        fill, span, load, cl, cw, (2800.0, 3200.0), include_earth_pressure=False
    )
    assert len(loads) == 2
    total = sum(load_.total() for load_ in loads)
    share = fill.effective_width / fill.spread(cw)
    assert total == pytest.approx(2 * load * share, rel=1e-9)


def test_dispersed_train_is_still_positionable():
    fill = FillDispersal(depth=600.0, effective_width=1000.0)
    with traffic.unverified_ok():
        train = traffic.get("M1600").train
    dispersed = fill.dispersed_train(train, 20.0 * m, 250.0, 400.0)
    assert not dispersed.axles, "axles become patches"
    assert len(dispersed.udl_segments) >= len(train.axles)
    assert dispersed.trailing_udl == train.trailing_udl, "a lane UDL does not re-disperse"


def test_dispersed_train_conserves_load():
    fill = FillDispersal(depth=1000.0, effective_width=1000.0)
    train = LoadTrain("t", axles=((0.0, 100 * kN), (2000.0, 100 * kN)), length=2000.0)
    dispersed = fill.dispersed_train(train, 20.0 * m, 250.0, 400.0)

    share = fill.effective_width / fill.spread(400.0)
    applied = sum(w * (b - a) for a, b, w in dispersed.udl_segments)
    assert applied == pytest.approx(train.total_axle_load * share, rel=1e-9)


def test_invalid_fill_parameters_raise():
    with pytest.raises(ModelError, match="depth"):
        FillDispersal(depth=-1.0)
    with pytest.raises(ModelError, match="slope"):
        FillDispersal(depth=100.0, slope=0.0)
    with pytest.raises(ModelError, match="width"):
        FillDispersal(depth=100.0, effective_width=0.0)


def test_buried_structure_loads_includes_earth_pressure_by_default():
    span = 6.0 * m
    fill = FillDispersal(depth=1000.0, effective_width=1000.0)
    with_earth = buried_structure_loads(fill, span, 80 * kN, 250.0, 400.0, (3000.0,))
    without = buried_structure_loads(
        fill, span, 80 * kN, 250.0, 400.0, (3000.0,), include_earth_pressure=False
    )
    assert len(with_earth) == len(without) + 1


def test_wheel_entirely_off_the_member_returns_nothing():
    fill = FillDispersal(depth=0.0, effective_width=1000.0)
    assert fill.disperse_wheel(80 * kN, -5000.0, 250.0, 400.0, 6000.0) is None


def test_dispersal_geometry_is_the_documented_formula():
    fill = FillDispersal(depth=1000.0, slope=2.0)
    assert fill.spread(250.0) == pytest.approx(250.0 + 2 * 1000.0 / 2.0)
    assert math.isclose(fill.spread(0.0), 1000.0)


def test_kNm_import_is_used():  # noqa: N802
    """Guard against the unit constants drifting out of the test module."""
    assert kNm == 1e6
