"""Unit tests for the cantilever wall tool.

Every test instantiates the Pydantic models directly (never a dict), per the
contracts-layer test convention: a broken bound or validator should show up
here immediately, not downstream in an engine that trusted an unvalidated
dict.

Mechanics are checked against hand calculations where one exists (the
degenerate no-backslope, no-water-table, no-surcharge Rankine case has an
exact closed form: P = 0.5.Ka.gamma.H^2, height H/3). Nothing here verifies
the AS 4678 factor VALUES -- those are transcribed and UNVERIFIED, as
declared throughout; these tests verify the plumbing and the mechanics given
those values.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from austruct.tools.cantilever_wall import (
    ResolvedSoil,
    SoilInput,
    WallGeometry,
    WallInput,
    analyse,
    soil_preset,
    soil_preset_names,
)
from austruct.tools.cantilever_wall.engine import (
    apply_material_factors,
    concrete_self_weight,
    heel_soil_weight,
    resolve_soil,
)
from austruct.tools.cantilever_wall.factor_sets import load_factor_set
from austruct.tools.cantilever_wall.pressure.rankine import (
    Ka_rankine,
    Kp_rankine,
    active_thrust,
    hydrostatic_thrust,
)
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


# ---------------------------------------------------------------------------
# Geometry validation
# ---------------------------------------------------------------------------


def test_heel_and_stem_height_are_derived_not_stored():
    g = _geometry()
    assert g.heel_length == pytest.approx(3.6 - 1.0 - 0.45)
    assert g.stem_height == pytest.approx(4.0 - 0.55)


def test_a_geometry_with_no_heel_is_rejected():
    with pytest.raises(ValidationError, match="no heel"):
        _geometry(base_length=1.0, toe_length=0.6, stem_thickness_bottom=0.5)


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        WallGeometry(
            H_retained=4.0, base_length=3.6, base_thickness=0.55,
            toe_length=1.0, stem_thickness_top=0.3, stem_thickness_bottom=0.45,
            not_a_real_field=1.0,
        )


# ---------------------------------------------------------------------------
# Soil input: presets, explicit choices, bounds
# ---------------------------------------------------------------------------


def test_soil_needs_phi_or_soil_type():
    with pytest.raises(ValidationError, match="soil.phi or soil.soil_type"):
        SoilInput(water_table=None)


def test_water_table_must_be_given_explicitly():
    with pytest.raises(ValidationError, match="water_table must be given explicitly"):
        SoilInput(phi=30.0)


def test_unknown_soil_type_is_rejected():
    with pytest.raises(ValidationError, match="Unknown soil_type"):
        SoilInput(soil_type="unobtainium", water_table=None)


def test_every_preset_name_resolves():
    for name in soil_preset_names():
        preset = soil_preset(name)
        assert preset.phi > 0
        assert preset.gamma > 0
        assert preset.cohesion >= 0


# ---------------------------------------------------------------------------
# Resolution: source tagging is the point of this input layer
# ---------------------------------------------------------------------------


def test_supplied_values_are_tagged_supplied():
    resolved = resolve_soil(_soil())
    assert resolved.phi.source == "supplied"
    assert resolved.gamma.source == "supplied"
    assert resolved.cohesion.source == "supplied"
    assert resolved.surcharge.source == "supplied"


def test_preset_derived_values_are_tagged_preset():
    soil = SoilInput(soil_type="clean_sand", water_table=None)
    resolved = resolve_soil(soil)
    preset = soil_preset("clean_sand")
    assert resolved.phi.value == pytest.approx(preset.phi)
    assert resolved.phi.source == "preset"
    assert resolved.gamma.source == "preset"
    assert resolved.cohesion.source == "preset"


def test_unstated_values_fall_back_to_default_and_are_tagged():
    soil = SoilInput(phi=30.0, water_table=None)  # gamma, cohesion untouched
    resolved = resolve_soil(soil)
    assert resolved.gamma.source == "default"
    assert resolved.cohesion.source == "default"
    assert resolved.delta.source == "default"
    assert resolved.delta.value == pytest.approx(min(2.0 / 3.0 * 30.0, 20.0))


def test_delta_cap_applies_for_a_high_friction_angle():
    soil = SoilInput(phi=42.0, water_table=None)  # 2/3 * 42 = 28 > cap of 20
    resolved = resolve_soil(soil)
    assert resolved.delta.value == pytest.approx(20.0)


def test_assumptions_lists_only_non_supplied_fields():
    resolved = resolve_soil(_soil())  # everything explicit except delta/backslope
    lines = resolved.assumptions()
    assert any("delta" in line.lower() for line in lines)
    assert not any("friction angle phi" in line.lower() for line in lines)


def test_a_preset_soil_still_surfaces_a_source_tagged_result():
    soil = SoilInput(soil_type="stiff_clay", water_table=None)
    resolved = resolve_soil(soil)
    assert all(
        getattr(resolved, field).source == "preset"
        for field in ("phi", "gamma", "cohesion")
    )


# ---------------------------------------------------------------------------
# AS 4678 material factoring
# ---------------------------------------------------------------------------


def test_material_factors_reduce_phi_and_cohesion():
    resolved = resolve_soil(_soil(cohesion=5.0))
    factors = load_factor_set("as4678_class_b")
    design = apply_material_factors(resolved, factors)

    assert design.phi_deg < resolved.phi.value
    assert design.cohesion == pytest.approx(5.0 * factors.material.cohesion_factor)
    # tan(phi) scales exactly by the material factor -- phi itself does not.
    assert math.tan(math.radians(design.phi_deg)) == pytest.approx(
        math.tan(math.radians(resolved.phi.value)) * factors.material.phi_ug_factor
    )


def test_gamma_is_never_factored():
    resolved = resolve_soil(_soil())
    design = apply_material_factors(resolved, load_factor_set("as4678_class_b"))
    assert design.gamma == pytest.approx(resolved.gamma.value)


def test_unknown_framework_is_rejected():
    with pytest.raises(ValueError, match="Unknown framework"):
        load_factor_set("made_up_framework")


# ---------------------------------------------------------------------------
# Rankine pressure -- the exact degenerate case, then each effect in turn
# ---------------------------------------------------------------------------


def test_Ka_matches_the_textbook_closed_form_at_phi_30():
    assert Ka_rankine(30.0, 0.0) == pytest.approx(1.0 / 3.0, rel=1e-9)


def test_Kp_matches_the_textbook_closed_form_at_phi_30():
    assert Kp_rankine(30.0) == pytest.approx(3.0, rel=1e-9)


def test_backslope_steeper_than_phi_is_rejected():
    with pytest.raises(ValueError, match="Rankine active pressure is undefined"):
        Ka_rankine(20.0, 25.0)


class _Soil:
    def __init__(self, phi_deg, cohesion=0.0, gamma=18.0):
        self.phi_deg = phi_deg
        self.cohesion = cohesion
        self.gamma = gamma


def test_degenerate_triangular_case_matches_the_exact_closed_form():
    """No backslope, no surcharge, no water table, no cohesion -- the
    textbook exact result: P = 0.5.Ka.gamma.H^2, height = H/3, no vertical
    component. This is the highest-value regression check in the suite: if
    the general numerical integration cannot reproduce the one case with a
    known closed form, nothing else it computes can be trusted."""
    H, gamma = 4.0, 18.0
    design = _Soil(phi_deg=30.0)
    Ka = 1.0 / 3.0

    thrust = active_thrust(H, design, gamma, backslope_deg=0.0, surcharge=0.0, water_table=None)

    assert thrust.horizontal == pytest.approx(0.5 * Ka * gamma * H**2, rel=1e-4)
    assert thrust.vertical == pytest.approx(0.0, abs=1e-9)
    assert thrust.height == pytest.approx(H / 3.0, rel=1e-3)


def test_surcharge_adds_a_rectangular_component_at_half_height():
    H, gamma, q = 4.0, 18.0, 10.0
    design = _Soil(phi_deg=30.0)
    Ka = 1.0 / 3.0

    thrust = active_thrust(H, design, gamma, backslope_deg=0.0, surcharge=q, water_table=None)

    P_tri = 0.5 * Ka * gamma * H**2
    P_rect = Ka * q * H
    expected_P = P_tri + P_rect
    expected_height = (P_tri * (H / 3.0) + P_rect * (H / 2.0)) / expected_P

    assert thrust.horizontal == pytest.approx(expected_P, rel=1e-3)
    assert thrust.height == pytest.approx(expected_height, rel=1e-3)


def test_backslope_gives_a_nonzero_vertical_component():
    design = _Soil(phi_deg=32.0)
    thrust = active_thrust(4.0, design, 18.0, backslope_deg=10.0, surcharge=0.0, water_table=None)
    beta = math.radians(10.0)
    assert thrust.vertical == pytest.approx(thrust.horizontal * math.tan(beta), rel=1e-6)
    assert thrust.vertical > 0


def test_water_table_is_reported_as_a_separate_hydrostatic_thrust():
    """[TRAP] Water must never be lumped into the earth-pressure thrust."""
    H, gamma, wt = 4.0, 18.0, 2.0
    design = _Soil(phi_deg=30.0)

    drained = active_thrust(H, design, gamma, 0.0, 0.0, water_table=None)
    submerged = active_thrust(H, design, gamma, 0.0, 0.0, water_table=wt)
    hydro = hydrostatic_thrust(H, wt)

    # Submerged effective-stress thrust is LESS than the drained case (the
    # submerged unit weight below the water table is lower) -- the drop is
    # not compensated by folding hydrostatic pressure into the same number.
    assert submerged.horizontal < drained.horizontal
    # And the hydrostatic thrust exists as its own, separately reported force.
    assert hydro.horizontal == pytest.approx(0.5 * 9.81 * (H - wt) ** 2, rel=1e-6)
    assert hydro.height == pytest.approx((H - wt) / 3.0, rel=1e-6)


def test_no_water_table_means_zero_hydrostatic_thrust():
    hydro = hydrostatic_thrust(4.0, None)
    assert hydro.horizontal == 0.0


# ---------------------------------------------------------------------------
# Self-weight geometry (independent hand check of the trapezoid centroid)
# ---------------------------------------------------------------------------


def test_uniform_stem_centroid_is_at_the_rectangle_midpoint():
    g = _geometry(stem_thickness_top=0.45, stem_thickness_bottom=0.45)  # no taper
    _footing, stem = concrete_self_weight(g)
    back_x = g.toe_length + g.stem_thickness_bottom
    assert stem.arm == pytest.approx(back_x - 0.45 / 2.0)


def test_tapered_stem_centroid_sits_between_the_two_face_midpoints():
    g = _geometry(stem_thickness_top=0.2, stem_thickness_bottom=0.5)
    _footing, stem = concrete_self_weight(g)
    back_x = g.toe_length + g.stem_thickness_bottom
    # Centroid offset from the back face must lie strictly between top/2 and
    # bottom/2 for a linear taper.
    offset = back_x - stem.arm
    assert 0.2 / 2.0 < offset < 0.5 / 2.0


def test_heel_soil_weight_uses_the_full_retained_height_above_the_heel():
    g = _geometry()
    weight = heel_soil_weight(g, gamma=19.0, surcharge=5.0)
    assert weight.soil_weight.weight == pytest.approx(g.heel_length * g.stem_height * 19.0)
    assert weight.surcharge_weight.weight == pytest.approx(g.heel_length * 5.0)


# ---------------------------------------------------------------------------
# End-to-end: analyse()
# ---------------------------------------------------------------------------


def test_an_adequately_sized_wall_passes_every_check():
    wall = WallInput(geometry=_geometry(), soil=_soil())
    result = analyse(wall)
    assert result.passed
    assert all(c.passed for c in result.checks.values())
    assert result.governing_utilisation == max(c.utilisation for c in result.checks.values())


def test_an_undersized_wall_fails_and_says_which_check_governs():
    undersized = _geometry(base_length=2.2, toe_length=0.5, base_thickness=0.35)
    wall = WallInput(geometry=undersized, soil=_soil())
    result = analyse(wall)
    assert not result.passed
    assert any(not c.passed for c in result.checks.values())


def test_utilisation_worsens_as_retained_height_grows_for_a_fixed_footing():
    """More retained height means more thrust against the same resistance --
    the governing utilisation should not improve as H grows."""
    utilisations = []
    for H in (2.5, 3.5, 4.5):
        wall = WallInput(geometry=_geometry(H_retained=H), soil=_soil())
        utilisations.append(analyse(wall).governing_utilisation)
    assert utilisations == sorted(utilisations)


def test_assumed_vs_supplied_list_is_carried_on_the_result():
    wall = WallInput(geometry=_geometry(), soil=_soil())  # delta, backslope defaulted
    result = analyse(wall)
    assert result.assumptions
    assert any("delta" in a.lower() for a in result.assumptions)


def test_method_a_reports_only_earth_pressure_not_hydrostatic():
    wet_soil = _soil(water_table=1.0)
    wall = WallInput(geometry=_geometry(), soil=wet_soil)
    result = analyse(wall)
    assert result.method_a.hydrostatic_horizontal > 0
    # thrust_horizontal is the earth-pressure component alone.
    dry = analyse(WallInput(geometry=_geometry(), soil=_soil(water_table=None)))
    assert result.method_a.thrust_horizontal < dry.method_a.thrust_horizontal


def test_bearing_capacity_override_bypasses_the_terzaghi_estimate():
    wall = WallInput(
        geometry=_geometry(), soil=_soil(), bearing_capacity_override=500.0,
    )
    result = analyse(wall)
    bearing_working = result.checks["bearing"].working
    assert bearing_working["outputs"]["q_design"]["value"] == pytest.approx(500.0)


def test_precast_construction_uses_two_thirds_phi_for_base_friction():
    cast_in_situ = WallInput(geometry=_geometry(), soil=_soil(), construction="cast_in_situ")
    precast = WallInput(geometry=_geometry(), soil=_soil(), construction="precast")
    r1 = analyse(cast_in_situ)
    r2 = analyse(precast)
    # Less base friction -- precast must not do BETTER on sliding.
    assert r2.checks["sliding"].utilisation >= r1.checks["sliding"].utilisation


# ---------------------------------------------------------------------------
# Composition: save/load round trip, per the contracts layer's own test
# convention -- and the actual mechanism a larger tool would consume this
# result through.
# ---------------------------------------------------------------------------


def test_wall_result_round_trips_through_save_and_load(tmp_path):
    from austruct.tools.cantilever_wall.models import WallResult

    wall = WallInput(geometry=_geometry(), soil=_soil())
    result = analyse(wall)

    path = tmp_path / "wall_result.json"
    save_result(result, path)
    reloaded = load_result(WallResult, path)

    assert reloaded.passed == result.passed
    assert reloaded.governing_utilisation == pytest.approx(result.governing_utilisation)
    assert reloaded.checks["sliding"].working["checks"] == result.checks["sliding"].working["checks"]


def test_a_resolved_soil_also_round_trips_with_its_sourcing_intact(tmp_path):
    resolved = resolve_soil(SoilInput(soil_type="gravel", water_table=None))
    path = tmp_path / "soil.json"
    save_result(resolved, path)
    reloaded = load_result(ResolvedSoil, path)
    assert reloaded.phi.source == "preset"
    assert reloaded.phi.value == pytest.approx(resolved.phi.value)
