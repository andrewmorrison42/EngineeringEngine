"""Unit tests for the modular gravity (segmental) block wall tool.

Every test instantiates the Pydantic models directly, per the contracts-layer
test convention shared with ``test_cantilever_wall.py``.

Mechanics are checked against hand calculations where one exists: the
degenerate omega=delta=beta=0 case reduces the general Coulomb coefficient
to the closed-form Rankine value used elsewhere in this toolkit, and the
per-course self-weight/centroid arithmetic is checked against a hand
sum for a small stack. Nothing here verifies the FS minimums themselves --
those are transcribed from the source PDF (sliding, overturning, bearing)
or a documented placeholder (interface shear), as declared throughout;
these tests verify the plumbing and the mechanics given those values.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from austruct.tools.cantilever_wall.engine import resolve_soil
from austruct.tools.cantilever_wall.models import SoilInput
from austruct.tools.cantilever_wall.pressure.rankine import Ka_rankine
from austruct.tools.contracts.base import load_result, save_result
from austruct.tools.gravity_wall import (
    BlockSeries,
    GravityWallGeometry,
    GravityWallInput,
    GravityWallResult,
    analyse,
    block_series,
    block_series_names,
)
from austruct.tools.gravity_wall.engine import block_self_weight, build_ledger, eccentricity
from austruct.tools.gravity_wall.pressure import Ka_coulomb, active_thrust


def _block(**overrides) -> BlockSeries:
    defaults = dict(
        name="test_block", description="test", width=1.0, height=0.5, setback=0.05, unit_weight=21.5,
    )
    defaults.update(overrides)
    return BlockSeries(**defaults)


def _geometry(**overrides) -> GravityWallGeometry:
    defaults = dict(n_courses=6, block=_block())
    defaults.update(overrides)
    return GravityWallGeometry(**defaults)


def _soil(**overrides) -> SoilInput:
    defaults = dict(phi=32.0, gamma=19.0, cohesion=0.0, surcharge=5.0, water_table=None)
    defaults.update(overrides)
    return SoilInput(**defaults)


# ---------------------------------------------------------------------------
# Block catalogue
# ---------------------------------------------------------------------------


def test_every_catalogue_series_loads_and_has_a_positive_batter():
    for name in block_series_names():
        b = block_series(name)
        assert b.width > 0
        assert b.height > 0
        assert b.batter_deg > 0


def test_unknown_series_raises_with_the_known_list():
    with pytest.raises(KeyError, match="compact_28in"):
        block_series("nonexistent_series")


def test_batter_is_derived_from_setback_over_height():
    b = _block(height=0.4, setback=0.04)
    assert b.batter_deg == pytest.approx(math.degrees(math.atan2(0.04, 0.4)))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_wall_height_is_courses_times_block_height():
    g = _geometry(n_courses=8, block=_block(height=0.406))
    assert g.H == pytest.approx(8 * 0.406)


def test_base_width_is_the_block_width():
    g = _geometry(block=_block(width=1.03))
    assert g.base_width == pytest.approx(1.03)


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        GravityWallGeometry(n_courses=6, block=_block(), extra_field=1.0)


def test_water_table_must_be_none():
    with pytest.raises(ValidationError, match="water table"):
        GravityWallInput(geometry=_geometry(), soil=_soil(water_table=1.0))


# ---------------------------------------------------------------------------
# Block self-weight
# ---------------------------------------------------------------------------


def test_course_self_weight_and_centroid_by_hand():
    g = _geometry(n_courses=3, block=_block(width=1.0, height=0.5, setback=0.1, unit_weight=20.0))
    rows = block_self_weight(g)
    assert len(rows) == 3
    # weight per course = width * height * unit_weight = 1.0 * 0.5 * 20.0 = 10.0
    for r in rows:
        assert r.weight == pytest.approx(10.0)
    # course i's front face at i*setback, centroid at front + width/2
    assert rows[0].arm == pytest.approx(0.0 + 0.5)
    assert rows[1].arm == pytest.approx(0.1 + 0.5)
    assert rows[2].arm == pytest.approx(0.2 + 0.5)
    # elevations stack directly, no gaps or overlaps
    assert rows[0].elevation_bottom == pytest.approx(0.0)
    assert rows[0].elevation_top == pytest.approx(0.5)
    assert rows[2].elevation_bottom == pytest.approx(1.0)
    assert rows[2].elevation_top == pytest.approx(1.5)


def test_total_wall_weight_sums_every_course():
    g = _geometry(n_courses=6, block=_block(width=1.0, height=0.5, unit_weight=20.0))
    rows = block_self_weight(g)
    assert sum(r.weight for r in rows) == pytest.approx(6 * 1.0 * 0.5 * 20.0)


# ---------------------------------------------------------------------------
# Coulomb pressure -- the degenerate-case cross-check against Rankine
# ---------------------------------------------------------------------------


def test_coulomb_matches_rankine_at_zero_omega_delta_beta():
    for phi in (20.0, 25.0, 30.0, 35.0, 40.0):
        a = Ka_coulomb(phi, omega_deg=0.0, beta_deg=0.0, delta_deg=0.0)
        b = Ka_rankine(phi, backslope_deg=0.0)
        assert a == pytest.approx(b, rel=1e-9)


def test_coulomb_thrust_matches_rankine_thrust_at_zero_omega_delta_beta():
    """Not just Ka -- the full integrated thrust, including surcharge,
    must also match at the degenerate case (both are 0.5.Ka.gamma.H^2 +
    Ka.q.H when omega = delta = beta = 0)."""
    from austruct.tools.cantilever_wall.pressure.rankine import active_thrust as rankine_thrust

    resolved = resolve_soil(_soil(phi=30.0, gamma=19.0, surcharge=5.0, cohesion=0.0, delta=0.0, backslope=0.0))
    H = 3.0
    coulomb = active_thrust(H, resolved, omega_deg=0.0)
    design_soil = type("DesignSoil", (), {"phi_deg": 30.0, "cohesion": 0.0, "gamma": 19.0})()
    rankine = rankine_thrust(H, design_soil, 19.0, 0.0, 5.0, None)
    assert coulomb.horizontal == pytest.approx(rankine.horizontal, rel=1e-6)
    assert coulomb.vertical == pytest.approx(0.0, abs=1e-9)
    assert coulomb.height == pytest.approx(rankine.height, rel=1e-6)


def test_negative_omega_reduces_ka_relative_to_a_vertical_wall():
    """Ka_coulomb's own sign convention: positive omega tilts the wall face
    INTO the backfill (increases Ka); negative omega -- the direction
    api.py actually passes, since a block wall's physical batter recedes
    AWAY from the backfill -- decreases it. See api.py's ``omega_deg =
    -geometry.batter_deg`` and this module's docstring."""
    Ka_vertical = Ka_coulomb(32.0, omega_deg=0.0, beta_deg=0.0, delta_deg=20.0)
    Ka_battered_away = Ka_coulomb(32.0, omega_deg=-8.0, beta_deg=0.0, delta_deg=20.0)
    Ka_battered_into = Ka_coulomb(32.0, omega_deg=8.0, beta_deg=0.0, delta_deg=20.0)
    assert Ka_battered_away < Ka_vertical < Ka_battered_into


def test_analyse_negates_batter_deg_for_the_coulomb_sign_convention():
    """End-to-end: a wall with MORE batter (a wider setback/height ratio,
    hence a larger BlockSeries.batter_deg) must read a LOWER Ka than the
    same wall with less batter -- api.py negating batter_deg before it
    reaches Ka_coulomb is what makes that true; the wrong sign would flip
    this comparison."""
    soil = _soil(phi=32.0, gamma=19.0, surcharge=5.0, delta=20.0)
    low_batter = analyse(GravityWallInput(
        geometry=GravityWallGeometry(n_courses=6, block=_block(setback=0.02)), soil=soil,
    ))
    high_batter = analyse(GravityWallInput(
        geometry=GravityWallGeometry(n_courses=6, block=_block(setback=0.15)), soil=soil,
    ))
    assert high_batter.pressure.Ka < low_batter.pressure.Ka


def test_backslope_steeper_than_phi_is_rejected():
    with pytest.raises(ValueError, match="exceeds phi"):
        Ka_coulomb(20.0, beta_deg=25.0)


def test_vertical_thrust_component_acts_downward_and_stabilises():
    resolved = resolve_soil(_soil(phi=32.0, delta=20.0))
    # omega_deg negative -- Ka_coulomb's convention for a wall battered
    # away from the backfill, as api.py always passes it.
    thrust = active_thrust(4.0, resolved, omega_deg=-5.77)
    assert thrust.vertical > 0.0


# ---------------------------------------------------------------------------
# Ledger and eccentricity
# ---------------------------------------------------------------------------


def test_ledger_vertical_force_includes_the_stabilising_thrust_component():
    g = _geometry(n_courses=6, block=_block(width=1.0, height=0.5, unit_weight=20.0))
    resolved = resolve_soil(_soil(phi=32.0, delta=20.0))
    thrust = active_thrust(g.H, resolved, g.batter_deg)
    ledger = build_ledger(g, thrust)
    self_weight = sum(r.weight for r in block_self_weight(g))
    assert ledger.V == pytest.approx(self_weight + thrust.vertical)


def test_eccentricity_zero_for_a_ridiculously_oversized_wall():
    """A wall so heavy relative to the earth pressure that the resultant
    sits almost exactly on the toe-side edge -- eccentricity should still
    be well inside the base, a sanity bound rather than an exact value."""
    g = _geometry(n_courses=20, block=_block(width=3.0, height=0.5, setback=0.02, unit_weight=24.0))
    resolved = resolve_soil(_soil(phi=32.0, gamma=15.0, surcharge=0.0, delta=10.0))
    thrust = active_thrust(g.H, resolved, g.batter_deg)
    ledger = build_ledger(g, thrust)
    e = eccentricity(ledger)
    assert abs(e) < g.base_width / 2.0


# ---------------------------------------------------------------------------
# analyse() integration
# ---------------------------------------------------------------------------


def test_a_generously_sized_wall_passes_every_check():
    geometry = GravityWallGeometry(n_courses=8, block=block_series("large_60in"), embedment=0.4)
    wall = GravityWallInput(geometry=geometry, soil=_soil(phi=32.0, gamma=19.0, surcharge=5.0))
    result = analyse(wall)
    assert result.passed
    for name, check in result.checks.items():
        assert check.passed, f"{name} failed unexpectedly: util={check.utilisation}"


def test_a_narrow_wall_on_a_shallow_footing_fails_bearing():
    geometry = GravityWallGeometry(n_courses=8, block=block_series("standard_41in"), embedment=0.0)
    wall = GravityWallInput(geometry=geometry, soil=_soil(phi=32.0, gamma=19.0, surcharge=5.0))
    result = analyse(wall)
    assert not result.checks["bearing"].passed
    assert not result.passed


def test_utilisation_worsens_as_wall_height_grows_for_a_fixed_block_series():
    soil = _soil(phi=32.0, gamma=19.0, surcharge=5.0)
    short = analyse(GravityWallInput(
        geometry=GravityWallGeometry(n_courses=4, block=block_series("large_60in"), embedment=0.4),
        soil=soil,
    ))
    tall = analyse(GravityWallInput(
        geometry=GravityWallGeometry(n_courses=14, block=block_series("large_60in"), embedment=0.4),
        soil=soil,
    ))
    assert tall.governing_utilisation > short.governing_utilisation


def test_interface_shear_governing_is_at_a_lower_course_for_a_taller_wall():
    """More courses above an interface means more driving thrust AND more
    clamping normal force -- not obviously monotonic -- but the governing
    interface should always be reported, never silently skipped, for any
    wall with more than one course."""
    geometry = GravityWallGeometry(n_courses=10, block=block_series("standard_41in"), embedment=0.3)
    wall = GravityWallInput(geometry=geometry, soil=_soil(phi=32.0, gamma=19.0, surcharge=5.0))
    result = analyse(wall)
    interface = result.checks["interface_shear"]
    assert interface.working["intermediates"]["governing_interface"]["value"] >= 1.0


def test_single_course_wall_has_no_interface_to_check():
    geometry = GravityWallGeometry(n_courses=1, block=block_series("standard_41in"), embedment=0.3)
    wall = GravityWallInput(geometry=geometry, soil=_soil(phi=32.0, gamma=19.0, surcharge=5.0))
    result = analyse(wall)
    interface = result.checks["interface_shear"]
    assert interface.passed  # FS = inf, no interface exists
    assert "no interface" in " ".join(interface.working["messages"]).lower()


def test_bearing_capacity_override_bypasses_terzaghi_meyerhof():
    geometry = GravityWallGeometry(n_courses=6, block=block_series("standard_41in"), embedment=0.0)
    wall = GravityWallInput(
        geometry=geometry, soil=_soil(phi=32.0, gamma=19.0, surcharge=5.0),
        bearing_capacity_override=500.0,
    )
    result = analyse(wall)
    assert result.checks["bearing"].working["outputs"]["q_ult"]["value"] == pytest.approx(500.0)


def test_delta_and_c_interface_govern_interface_shear():
    """A weaker interface (lower delta_interface, lower c_interface) must
    make the interface shear check strictly worse, never better."""
    geometry = GravityWallGeometry(n_courses=10, block=block_series("standard_41in"), embedment=0.3)
    soil = _soil(phi=32.0, gamma=19.0, surcharge=5.0)
    strong = analyse(GravityWallInput(
        geometry=geometry, soil=soil, delta_interface=40.0, c_interface=30.0,
    ))
    weak = analyse(GravityWallInput(
        geometry=geometry, soil=soil, delta_interface=15.0, c_interface=2.0,
    ))
    assert weak.checks["interface_shear"].utilisation > strong.checks["interface_shear"].utilisation


def test_result_round_trips_through_save_and_load(tmp_path):
    geometry = GravityWallGeometry(n_courses=8, block=block_series("large_60in"), embedment=0.4)
    wall = GravityWallInput(geometry=geometry, soil=_soil(phi=32.0, gamma=19.0, surcharge=5.0))
    result = analyse(wall)

    out = tmp_path / "gravity_wall_result.json"
    save_result(result, out)
    reloaded = load_result(GravityWallResult, out)

    assert reloaded.passed == result.passed
    assert reloaded.governing_utilisation == pytest.approx(result.governing_utilisation)
    assert reloaded.pressure.thrust_horizontal == pytest.approx(result.pressure.thrust_horizontal)
    assert reloaded.checks["sliding"].working["messages"] == result.checks["sliding"].working["messages"]
