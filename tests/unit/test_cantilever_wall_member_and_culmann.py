"""Unit tests for stem/heel/toe concrete design (Method A only, wired into
``analyse()``) and Method B (Culmann trial wedge) plus divergence reporting.

The highest-value regression here is the same one the original build brief
named for Method B: the trial wedge must converge on Rankine within a tight
tolerance for the degenerate case. A second, equally load-bearing check
confirms the BACKSLOPE difference between the two methods is not a bug --
it is verified against Coulomb's own closed-form Ka(phi, beta, delta=0)
formula, which the numerical wedge search reproduces exactly.
"""

from __future__ import annotations

import math

import pytest

from austruct.core.units import kNm
from austruct.tools.cantilever_wall import WallGeometry, WallInput, analyse
from austruct.tools.cantilever_wall.divergence import INFORMATIONAL_LIMIT, compare_thrust
from austruct.tools.cantilever_wall.engine import DesignSoil, apply_material_factors, resolve_soil
from austruct.tools.cantilever_wall.factor_sets import load_factor_set
from austruct.tools.cantilever_wall.member_design import (
    VARIABLE_LOAD_FACTOR,
    bearing_pressure,
    design_heel,
    design_stem,
    design_toe,
    eccentricity,
    member_design_ledger,
)
from austruct.tools.cantilever_wall.models import SoilInput
from austruct.tools.cantilever_wall.pressure.culmann import trial_wedge_thrust
from austruct.tools.cantilever_wall.pressure.rankine import active_thrust
from austruct.tools.contracts.base import load_result, save_result


def _geometry(**overrides) -> WallGeometry:
    defaults = dict(
        H_retained=4.0, base_length=3.6, base_thickness=0.55,
        toe_length=1.0, stem_thickness_top=0.3, stem_thickness_bottom=0.45,
    )
    defaults.update(overrides)
    return WallGeometry(**defaults)


def _soil(**overrides) -> SoilInput:
    defaults = dict(phi=32.0, gamma=19.0, cohesion=0.0, surcharge=5.0, water_table=None)
    defaults.update(overrides)
    return SoilInput(**defaults)


def _coulomb_ka_delta_zero(phi_deg: float, beta_deg: float) -> float:
    """Independent closed-form check: Coulomb's Ka for a vertical wall,
    zero wall friction -- Ka = cos^2(phi) / [1 + sqrt(sin(phi).sin(phi-beta)/cos(beta))]^2."""
    phi, beta = math.radians(phi_deg), math.radians(beta_deg)
    root = math.sqrt(math.sin(phi) * math.sin(phi - beta) / math.cos(beta))
    return math.cos(phi) ** 2 / (1.0 + root) ** 2


# ---------------------------------------------------------------------------
# Method B: the degenerate case must match Rankine -- the highest-value test
# ---------------------------------------------------------------------------


def test_degenerate_case_matches_rankine_to_a_tight_tolerance():
    """No backslope, no water table -- Method B must converge on Method A's
    exact closed form. This is the highest-value test in the suite."""
    ds = DesignSoil(phi_deg=30.0, cohesion=0.0, gamma=18.0)
    wedge = trial_wedge_thrust(4.0, ds, 18.0, backslope_deg=0.0, surcharge=0.0, water_table=None)
    rankine = active_thrust(4.0, ds, 18.0, backslope_deg=0.0, surcharge=0.0, water_table=None)

    assert wedge.thrust.horizontal == pytest.approx(rankine.horizontal, rel=1e-3)
    assert wedge.theta_deg == pytest.approx(45.0 + 30.0 / 2.0, abs=0.2)


def test_degenerate_case_with_surcharge_still_matches():
    """A flat, infinite-extent surcharge shares the same wedge-angle
    dependence as the soil self-weight, so the two methods still agree
    closely even with surcharge added, at zero backslope."""
    ds = DesignSoil(phi_deg=30.0, cohesion=0.0, gamma=18.0)
    wedge = trial_wedge_thrust(4.0, ds, 18.0, backslope_deg=0.0, surcharge=10.0, water_table=None)
    rankine = active_thrust(4.0, ds, 18.0, backslope_deg=0.0, surcharge=10.0, water_table=None)
    assert wedge.thrust.horizontal == pytest.approx(rankine.horizontal, rel=1e-3)


def test_backslope_divergence_matches_coulomb_not_rankine():
    """With backslope, Method B should NOT match Rankine -- it should match
    Coulomb's own closed-form Ka at delta=0, confirming the numerical
    search is a correct wedge-equilibrium implementation and the
    difference from Rankine is real, not a bug."""
    phi, beta, H, gamma = 30.0, 10.0, 4.0, 18.0
    ds = DesignSoil(phi_deg=phi, cohesion=0.0, gamma=gamma)

    wedge = trial_wedge_thrust(H, ds, gamma, backslope_deg=beta, surcharge=0.0, water_table=None)
    rankine = active_thrust(H, ds, gamma, backslope_deg=beta, surcharge=0.0, water_table=None)

    expected_coulomb = 0.5 * _coulomb_ka_delta_zero(phi, beta) * gamma * H**2
    assert wedge.thrust.horizontal == pytest.approx(expected_coulomb, rel=1e-3)
    # And genuinely different from Rankine -- not a rounding-level gap.
    assert abs(wedge.thrust.horizontal - rankine.horizontal) / rankine.horizontal > 0.05


def test_backslope_exceeding_phi_is_rejected():
    ds = DesignSoil(phi_deg=20.0, cohesion=0.0, gamma=18.0)
    with pytest.raises(ValueError, match="exceeds phi"):
        trial_wedge_thrust(4.0, ds, 18.0, backslope_deg=25.0, surcharge=0.0, water_table=None)


def test_water_table_is_not_modelled_and_raises():
    ds = DesignSoil(phi_deg=30.0, cohesion=0.0, gamma=18.0)
    with pytest.raises(NotImplementedError, match="water table"):
        trial_wedge_thrust(4.0, ds, 18.0, backslope_deg=0.0, surcharge=0.0, water_table=1.0)


# ---------------------------------------------------------------------------
# Divergence banding
# ---------------------------------------------------------------------------


def test_identical_thrust_is_informational():
    d = compare_thrust(50.0, 50.0, backslope_deg=0.0, cohesion=0.0)
    assert d.band == "informational"
    assert d.divergence == 0.0


def test_divergence_just_under_the_warn_limit_is_informational():
    d = compare_thrust(100.0, 100.0 * (1 + INFORMATIONAL_LIMIT - 0.001), 0.0, 0.0)
    assert d.band == "informational"


def test_divergence_between_limits_warns_and_names_backslope():
    d = compare_thrust(100.0, 100.0 * (1 + INFORMATIONAL_LIMIT + 0.01), backslope_deg=8.0, cohesion=0.0)
    assert d.band == "warn"
    assert "backslope" in d.cause


def test_divergence_over_the_warn_limit_flags_and_names_cohesion():
    # divergence = |a-b|/max(a,b) = x/(1+x) for b = a.(1+x) -- need x large
    # enough that x/(1+x) clears WARN_LIMIT (0.15), not just x itself.
    d = compare_thrust(100.0, 100.0 * 1.30, backslope_deg=0.0, cohesion=5.0)
    assert d.band == "flag"
    assert "cohesion" in d.cause


def test_large_divergence_with_no_known_cause_says_so():
    d = compare_thrust(100.0, 200.0, backslope_deg=0.0, cohesion=0.0)
    assert d.band == "flag"
    assert "investigate" in d.cause


# ---------------------------------------------------------------------------
# Member design: bearing pressure and eccentricity
# ---------------------------------------------------------------------------


def test_bearing_pressure_matches_the_trapezoid_formula_at_the_edges():
    V, e, B = 300.0, 0.2, 3.0
    q_toe = bearing_pressure(0.0, V, e, B)
    q_heel = bearing_pressure(B, V, e, B)
    assert q_toe == pytest.approx(V / B * (1 + 6 * e / B))
    assert q_heel == pytest.approx(V / B * (1 - 6 * e / B))


def test_bearing_pressure_is_uniform_at_zero_eccentricity():
    V, B = 300.0, 3.0
    assert bearing_pressure(0.0, V, 0.0, B) == pytest.approx(V / B)
    assert bearing_pressure(B, V, 0.0, B) == pytest.approx(V / B)


def test_member_design_ledger_eccentricity_matches_manual_formula():
    wall = WallInput(geometry=_geometry(), soil=_soil())
    resolved = resolve_soil(wall.soil)
    design = apply_material_factors(resolved, load_factor_set("as4678_class_b"))
    ledger = member_design_ledger(wall, resolved, design)

    e = eccentricity(ledger, wall.geometry.base_length)
    x_bar = (ledger.M_resisting_star - ledger.M_overturning_star) / ledger.V_star
    assert e == pytest.approx(wall.geometry.base_length / 2.0 - x_bar)


# ---------------------------------------------------------------------------
# Member design: stem, heel, toe
# ---------------------------------------------------------------------------


def test_stem_moment_uses_only_the_stem_height_not_the_full_wall():
    """The stem is a much shorter cantilever than the whole wall -- its
    design moment must come from a SHORTER pressure diagram, not the full
    H_retained one used for the stability checks."""
    wall = WallInput(geometry=_geometry(), soil=_soil())
    resolved = resolve_soil(wall.soil)
    design = apply_material_factors(resolved, load_factor_set("as4678_class_b"))

    stem = design_stem(wall, resolved, design)
    full_wall_thrust = active_thrust(
        wall.geometry.H_retained, design, resolved.gamma.value,
        resolved.backslope.value, resolved.surcharge.value, resolved.water_table,
    )
    # M* for the stem must be far smaller than a (wrong) full-height moment
    # would give -- a loose but meaningful sanity bound. Method's thrust is
    # in this tool's kN/m.m convention; M* on the CalcResult is N.mm.
    wrong_full_height_moment_kNm = (
        VARIABLE_LOAD_FACTOR * full_wall_thrust.horizontal * full_wall_thrust.height
    )
    assert stem.flexure.inputs["Mstar"].value < wrong_full_height_moment_kNm * kNm


def test_toe_self_weight_relieves_the_net_moment():
    """A heavier toe slab (thicker base) should relieve more of the
    upward-bearing moment -- the net M* should not increase with thickness
    even though gross bearing pressure barely changes for a small delta."""
    wall_thin = WallInput(geometry=_geometry(base_thickness=0.45), soil=_soil())
    wall_thick = WallInput(geometry=_geometry(base_thickness=0.85), soil=_soil())

    resolved = resolve_soil(wall_thin.soil)
    design = apply_material_factors(resolved, load_factor_set("as4678_class_b"))

    ledger_thin = member_design_ledger(wall_thin, resolved, design)
    ledger_thick = member_design_ledger(wall_thick, resolved, design)

    toe_thin = design_toe(wall_thin, ledger_thin)
    toe_thick = design_toe(wall_thick, ledger_thick)

    assert toe_thick.flexure.inputs["Mstar"].value < toe_thin.flexure.inputs["Mstar"].value


def test_heel_moment_is_positive_and_the_shear_check_runs():
    wall = WallInput(geometry=_geometry(), soil=_soil())
    resolved = resolve_soil(wall.soil)
    design = apply_material_factors(resolved, load_factor_set("as4678_class_b"))
    ledger = member_design_ledger(wall, resolved, design)

    heel = design_heel(wall, resolved, ledger)
    assert heel.flexure.inputs["Mstar"].value > 0
    assert heel.shear.inputs["Vstar"].value > 0


def test_a_thick_lightly_loaded_member_can_fail_on_minimum_strength_alone():
    """required_steel_area() bisects on STRENGTH only -- a thick, lightly
    loaded footing slab can satisfy M* <= phi.Muo exactly (utilisation
    1.000) and still FAIL overall because Cl 8.1.6.1's minimum-strength
    check (Muo >= 1.2 Mcr) is not targeted by that bisection. This is
    documented, expected behaviour, not a bug -- this test pins it."""
    wall = WallInput(geometry=_geometry(), soil=_soil())
    resolved = resolve_soil(wall.soil)
    design = apply_material_factors(resolved, load_factor_set("as4678_class_b"))
    ledger = member_design_ledger(wall, resolved, design)

    toe = design_toe(wall, ledger)
    strength_check = next(c for c in toe.flexure.checks if "M* <=" in c.label)
    min_strength_check = next(c for c in toe.flexure.checks if "Minimum strength" in c.label)

    assert strength_check.passed
    assert strength_check.utilisation == pytest.approx(1.0, abs=0.01)
    assert not min_strength_check.passed
    assert not toe.flexure.passed


# ---------------------------------------------------------------------------
# analyse(): the whole pipeline, stem/heel/toe + Method B + divergence wired in
# ---------------------------------------------------------------------------


def test_analyse_carries_member_design_checks():
    wall = WallInput(geometry=_geometry(), soil=_soil())
    result = analyse(wall)
    for key in (
        "stem_flexure", "stem_shear", "toe_flexure", "toe_shear", "heel_flexure", "heel_shear",
    ):
        assert key in result.checks


def test_analyse_runs_method_b_and_reports_divergence():
    wall = WallInput(geometry=_geometry(), soil=_soil(backslope=5.0))
    result = analyse(wall)
    assert result.method_b is not None
    assert result.method_b.method == "culmann"
    assert result.divergence is not None


def test_analyse_skips_method_b_gracefully_with_a_water_table():
    wall = WallInput(geometry=_geometry(), soil=_soil(water_table=1.0))
    result = analyse(wall)
    assert result.method_b is None
    assert result.divergence is None
    assert any("Method B not run" in note for note in result.notes)


def test_a_flagged_divergence_makes_the_wall_not_pass():
    """Even if every stability and member check passes, a 'flag'-band
    divergence between the two earth-pressure methods must still fail the
    wall overall -- the tool must never silently prefer one method's answer.
    backslope=24 deg against phi=35 deg gives ~20% divergence (checked by
    hand), safely over the 15% flag threshold."""
    wall = WallInput(
        geometry=_geometry(base_length=6.0, base_thickness=0.8, toe_length=1.5,
                            stem_thickness_bottom=0.6, stem_thickness_top=0.4),
        soil=_soil(phi=35.0, backslope=24.0, surcharge=0.0),
    )
    result = analyse(wall)
    assert result.divergence is not None
    assert result.divergence.band == "flag"
    assert not result.passed


def test_wall_result_with_method_b_round_trips(tmp_path):
    from austruct.tools.cantilever_wall.models import WallResult

    wall = WallInput(geometry=_geometry(), soil=_soil(backslope=5.0))
    result = analyse(wall)
    path = tmp_path / "result.json"
    save_result(result, path)
    reloaded = load_result(WallResult, path)

    assert reloaded.method_b is not None
    assert reloaded.method_b.critical_wedge_angle == pytest.approx(result.method_b.critical_wedge_angle)
    assert reloaded.divergence.band == result.divergence.band
    assert set(reloaded.checks) == set(result.checks)
