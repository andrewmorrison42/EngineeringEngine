"""Unit tests for load combinations and result envelopes -- ASET components 2 and 3.

The envelope is the part most likely to be subtly wrong in a way that produces
plausible numbers: a governing combination misattributed, or an envelope taken
across grids that do not line up. These tests pin both.
"""

from __future__ import annotations

import pytest

from austruct.analysis import (
    UDL,
    Beam,
    PartialUDL,
    PointLoad,
    Support,
    SupportType,
    analyse_combinations,
    envelope_by_limit_state,
    simply_supported,
)
from austruct.core.units import kN, kN_per_m, m
from austruct.loads import (
    ActionType,
    LimitState,
    LoadCase,
    LoadCombination,
    as1170_sls,
    as1170_uls,
    basic_building_combinations,
    filter_relevant,
)

EI = 2.6e14
L = 8.0 * m


@pytest.fixture
def cases():
    return (
        LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),)),
        LoadCase(
            "Q",
            ActionType.Q,
            (UDL(magnitude=15 * kN_per_m), PointLoad(position=4 * m, magnitude=60 * kN)),
        ),
    )


@pytest.fixture
def beam():
    return simply_supported(L, EI=EI, name="B1")


# ---------------------------------------------------------------------------
# Load scaling
# ---------------------------------------------------------------------------


def test_loads_scale_magnitudes_not_positions():
    load = PointLoad(position=3 * m, magnitude=50 * kN)
    scaled = load.scale(1.5)
    assert scaled.magnitude == pytest.approx(75 * kN)
    assert scaled.position == pytest.approx(3 * m), "position must not scale"


def test_partial_udl_scales_magnitude_not_extent():
    load = PartialUDL(start=2 * m, end=6 * m, magnitude=10 * kN_per_m)
    scaled = load.scale(2.0)
    assert scaled.magnitude == pytest.approx(20 * kN_per_m)
    assert (scaled.start, scaled.end) == (2 * m, 6 * m)


def test_self_weight_scales_through_its_factor():
    from austruct.analysis import SelfWeight

    sw = SelfWeight(area=300 * 600, length=L)
    assert sw.scale(1.2).magnitude == pytest.approx(1.2 * sw.magnitude)


def test_zero_factor_drops_loads_entirely():
    case = LoadCase("Q", ActionType.Q, (UDL(magnitude=10 * kN_per_m),))
    assert case.scaled(0.0) == ()
    assert len(case.scaled(1.5)) == 1


# ---------------------------------------------------------------------------
# Combinations
# ---------------------------------------------------------------------------


def test_combination_applies_the_right_factor_per_action(cases):
    combo = LoadCombination(
        "test", {ActionType.G: 1.2, ActionType.Q: 1.5}, LimitState.ULS
    )
    loads = combo.apply(cases)
    total = sum(load.total() for load in loads)
    expected = 1.2 * cases[0].total + 1.5 * cases[1].total
    assert total == pytest.approx(expected)


def test_action_absent_from_a_combination_contributes_nothing(cases):
    combo = LoadCombination("G only", {ActionType.G: 1.35}, LimitState.ULS)
    total = sum(load.total() for load in combo.apply(cases))
    assert total == pytest.approx(1.35 * cases[0].total)


def test_psi_factors_flow_into_the_combinations():
    tight = as1170_uls(psi_c=0.4, psi_l=0.4)
    loose = as1170_uls(psi_c=0.6, psi_l=0.8)
    uls3_tight = next(c for c in tight if c.name == "ULS3")
    uls3_loose = next(c for c in loose if c.name == "ULS3")
    assert uls3_loose.factor_for(ActionType.Q) > uls3_tight.factor_for(ActionType.Q)


def test_filter_relevant_drops_wind_when_there_is_no_wind_case(cases):
    relevant = filter_relevant(as1170_uls(), cases)
    names = {c.name for c in relevant}
    assert "ULS2" in names
    assert "ULS5" not in names, "0.9G + Wu has no wind case to act on"


def test_bridge_combinations_fail_loudly_not_silently():
    from austruct.loads import as5100_sls, as5100_uls

    with pytest.raises(NotImplementedError, match="traffic load models"):
        as5100_uls()
    with pytest.raises(NotImplementedError):
        as5100_sls()


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------


def test_envelope_matches_hand_calculation_and_names_the_combination(beam, cases):
    env = analyse_combinations(beam, cases, as1170_uls())

    w = (1.2 * 20 + 1.5 * 15) * kN_per_m
    P = 1.5 * 60 * kN
    assert env.M_star == pytest.approx(w * L**2 / 8 + P * L / 4, rel=1e-6)
    assert env.V_star == pytest.approx(w * L / 2 + P / 2, rel=1e-6)
    assert env.moment.governing_combo == "ULS2"
    assert env.shear.governing_combo == "ULS2"


def test_1_35G_governs_when_there_is_no_imposed_load(beam):
    only_g = (LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),)),)
    env = analyse_combinations(beam, only_g, as1170_uls())
    assert env.moment.governing_combo == "ULS1"
    assert env.M_star == pytest.approx(1.35 * 20 * kN_per_m * L**2 / 8, rel=1e-6)


def test_all_combinations_share_one_exact_grid(beam, cases):
    """The point of Beam.extra_mesh_points. Without it the envelope would be
    comparing different positions."""
    env = analyse_combinations(beam, cases, as1170_uls())
    grids = {tuple(r.x) for r in env.case_results.values()}
    assert len(grids) == 1, "combinations must be sampled on identical grids"
    assert len(env.moment.max_combo) == len(env.moment.x)


def test_shear_peak_is_captured_at_the_support(beam, cases):
    """Regression: the sampler must bracket a discontinuity sitting on a member
    end, or the shear just inboard of an end support is never sampled."""
    env = analyse_combinations(beam, cases, as1170_uls())
    assert env.shear.peak_max_position == pytest.approx(0.0, abs=1e-3)
    assert env.shear.peak_min_position == pytest.approx(L, abs=1e-3)
    assert abs(env.shear.peak_min) == pytest.approx(env.shear.peak_max, rel=1e-6)


def test_envelope_is_at_least_every_individual_combination(beam, cases):
    env = analyse_combinations(beam, cases, as1170_uls())
    for name, result in env.case_results.items():
        assert env.moment.peak_max >= result.max_moment - 1e-6, name
        assert env.moment.peak_min <= result.min_moment + 1e-6, name


def test_uplift_is_detected_and_attributed():
    beam = Beam(
        length=10 * m,
        supports=(
            Support(0.0, SupportType.PINNED, "A"),
            Support(6 * m, SupportType.PINNED, "B"),
        ),
        EI=EI,
        name="B2",
    )
    cases = (
        LoadCase("G", ActionType.G, (UDL(magnitude=10 * kN_per_m),)),
        LoadCase("Wu", ActionType.Wu, (PointLoad(position=10 * m, magnitude=-80 * kN),)),
    )
    env = analyse_combinations(beam, cases, as1170_uls())

    uplifting = [r for r in env.reactions if r.uplift]
    assert uplifting, "uplift at B should be detected"
    assert uplifting[0].label == "B"
    # 0.9G + Wu is the combination that exists for exactly this.
    assert uplifting[0].min_combo == "ULS5"
    assert any("holding-down" in m for m in env.to_calc_result().messages)


def test_factored_forces_dict_has_the_aset_shape(beam, cases):
    env = analyse_combinations(beam, cases, as1170_uls())
    data = env.to_dict()
    entry = data["B1"]["moment"]["Mz"]
    for key in ("fact_max", "fact_min", "fact_max_combo", "fact_min_combo"):
        assert key in entry
    assert entry["fact_max_combo"] == "ULS2"
    assert entry["unit"] == "kN.m"


def test_limit_states_are_enveloped_separately(beam, cases):
    envs = envelope_by_limit_state(beam, cases, basic_building_combinations())
    assert set(envs) == {LimitState.ULS, LimitState.SLS}
    # SLS is unfactored, so its moment must be smaller than the ULS one.
    assert envs[LimitState.SLS].M_star < envs[LimitState.ULS].M_star
    assert all(c.limit_state is LimitState.SLS for c in envs[LimitState.SLS].combinations)


def test_sls_deflection_uses_unfactored_loads(beam, cases):
    envs = envelope_by_limit_state(beam, cases, as1170_sls())
    sls = envs[LimitState.SLS]
    single = beam.with_loads(
        tuple(load for case in cases for load in case.loads)
    ).solve()
    # G + 0.7Q must be less than G + Q.
    assert sls.deflection.peak_max < single.max_deflection


def test_envelope_with_no_applicable_combination_raises(beam):
    wind_only = (LoadCase("Wu", ActionType.Wu, (UDL(magnitude=5 * kN_per_m),)),)
    gravity_only = (LoadCombination("G", {ActionType.G: 1.35}, LimitState.ULS),)
    with pytest.raises(ValueError, match="No load combination"):
        analyse_combinations(beam, wind_only, gravity_only)


def test_envelope_feeds_the_design_layer(beam, cases):
    """The join that makes the whole thing worth having."""
    from austruct.design import as3600
    from austruct.materials import concrete
    from austruct.sections import rc_beam

    section = rc_beam(350, 650, concrete(40), n_bars=4, diameter=28, fitment_spacing=200)
    env = analyse_combinations(beam, cases, as1170_uls())

    flexure = as3600.check_flexure(section, env.M_star)
    shear = as3600.check_shear(section, V_star=env.shear_at_d_from_support(section.d))
    assert flexure.passed
    assert shear.passed
