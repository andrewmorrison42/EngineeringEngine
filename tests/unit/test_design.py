"""Unit tests for the design layer.

The flexure tests check the strain-compatibility solve against a closed-form
hand calculation for the singly-reinforced case where the steel yields. That is
the case an engineer would check by hand, so it is the case worth pinning.

Nothing here verifies the CODE CONSTANTS -- those are transcribed values and
can only be verified against the printed standard by a person. These tests
verify that the mechanics and the plumbing are right GIVEN the constants.
"""

from __future__ import annotations

import math

import pytest

from austruct.core.exceptions import ModelError, OutsideEnvelope
from austruct.core.units import kN, kNm
from austruct.design import as3600, as5100_5
from austruct.design.rc_common import solve_flexural_state
from austruct.materials import bar_area, concrete
from austruct.sections import RebarLayer, rc_beam, rc_tee


@pytest.fixture
def beam_section():
    """300 x 600, f'c = 32 MPa, 4-N24 bottom, N12-2leg ligatures at 200."""
    return rc_beam(
        300, 600, concrete(32), cover=40, n_bars=4, diameter=24,
        fitment_diameter=12, fitment_spacing=200,
    )


# ---------------------------------------------------------------------------
# Flexural mechanics vs hand calculation
# ---------------------------------------------------------------------------


def test_flexure_matches_hand_calculation(beam_section):
    """Singly reinforced, steel yielding -- the textbook hand calc.

    T   = A_st . f_sy
    d_n = T / (alpha_2 . f'c . b . gamma)
    z   = d - gamma.d_n/2
    M_uo = T . z
    """
    state = solve_flexural_state(beam_section)
    c = beam_section.concrete

    Ast = 4 * bar_area(24)
    d = 600 - 40 - 12 - 12
    T = Ast * 500.0
    dn_hand = T / (c.alpha2 * c.fc * 300 * c.gamma)
    z_hand = d - c.gamma * dn_hand / 2
    muo_hand = T * z_hand

    assert math.isclose(state.Ast, Ast, rel_tol=1e-9)
    assert math.isclose(state.d, d, rel_tol=1e-9)
    assert math.isclose(state.dn, dn_hand, rel_tol=1e-4)
    assert math.isclose(state.lever_arm, z_hand, rel_tol=1e-4)
    assert math.isclose(state.Muo, muo_hand, rel_tol=1e-4)
    assert state.all_tensile_steel_yielded


def test_equilibrium_is_satisfied_at_the_solution(beam_section):
    """Concrete compression must equal steel tension at the converged state."""
    state = solve_flexural_state(beam_section)
    assert math.isclose(state.block.force, state.tensile_force, rel_tol=1e-6)


def test_ku_and_kuo_differ_with_multiple_layers():
    """k_u uses the centroid of tensile steel, k_uo the outermost layer."""
    section = rc_beam(300, 600, concrete(32), n_bars=3, diameter=24, fitment_spacing=200)
    section = section.add_layer(
        RebarLayer.from_bars(3, 24, depth=470.0, label="second layer")
    )
    state = solve_flexural_state(section)
    assert state.d < state.d_o
    assert state.kuo < state.ku


def test_compression_steel_increases_capacity_and_ductility():
    singly = rc_beam(300, 600, concrete(32), n_bars=6, diameter=28, fitment_spacing=150)
    doubly = singly.add_layer(RebarLayer.from_bars(3, 20, depth=62.0, label="top"))

    s1 = solve_flexural_state(singly)
    s2 = solve_flexural_state(doubly)

    assert s2.Muo > s1.Muo
    assert s2.kuo < s1.kuo  # neutral axis rises, ductility improves


def test_tee_section_uses_flange_width():
    """A tee with the NA in the flange must match an equivalent rectangle."""
    tee = rc_tee(1200, 150, 300, 600, concrete(32), n_bars=4, diameter=24,
                 fitment_spacing=200)
    rect = rc_beam(1200, 600, concrete(32), n_bars=4, diameter=24, fitment_spacing=200)

    st_tee = solve_flexural_state(tee)
    st_rect = solve_flexural_state(rect)

    assert st_tee.block.block_depth <= 150.0, "NA should be within the flange"
    assert math.isclose(st_tee.Muo, st_rect.Muo, rel_tol=1e-9)


def test_section_with_no_reinforcement_raises():
    section = rc_beam(300, 600, concrete(32))
    with pytest.raises(ModelError, match="no reinforcement"):
        solve_flexural_state(section)


# ---------------------------------------------------------------------------
# AS 3600 flexure
# ---------------------------------------------------------------------------


def test_as3600_moment_capacity_contract(beam_section):
    result = as3600.moment_capacity(beam_section)

    assert result.envelope.within
    assert result.get("phiMuo") == pytest.approx(
        result.get("phi") * result.get("Muo")
    )
    assert {"Muo", "phiMuo", "phi"} <= set(result.outputs)
    assert any("Ductility" in c.label for c in result.checks)
    assert any("Minimum strength" in c.label for c in result.checks)
    assert len(result.basis) > 0
    assert result.to_json()


def test_as3600_phi_falls_as_section_becomes_less_ductile():
    lightly = rc_beam(300, 600, concrete(32), n_bars=2, diameter=16, fitment_spacing=200)
    heavily = rc_beam(300, 600, concrete(32), n_bars=8, diameter=32, fitment_spacing=200)

    phi_light = as3600.moment_capacity(lightly).get("phi")
    phi_heavy = as3600.moment_capacity(heavily).get("phi")

    assert phi_light >= phi_heavy


def test_as3600_ductility_check_fails_when_over_reinforced():
    over = rc_beam(300, 600, concrete(32), n_bars=8, diameter=36, fitment_spacing=150)
    result = as3600.moment_capacity(over)
    ductility = next(c for c in result.checks if "Ductility" in c.label)
    assert not ductility.passed
    assert not result.passed


def test_as3600_check_flexure_pass_and_fail(beam_section):
    capacity = as3600.moment_capacity(beam_section).get("phiMuo")

    passing = as3600.check_flexure(beam_section, 0.5 * capacity)
    assert passing.passed
    assert passing.utilisation < 1.0

    failing = as3600.check_flexure(beam_section, 1.5 * capacity)
    assert not failing.passed
    assert failing.utilisation > 1.0


def test_as3600_required_steel_area_develops_the_moment(beam_section):
    target = 400 * kNm
    result = as3600.required_steel_area(beam_section, target)
    assert result.passed
    assert result.get("phiMuo") >= target


def test_as3600_required_steel_area_raises_when_section_too_small(beam_section):
    with pytest.raises(ValueError, match="cannot be developed"):
        as3600.required_steel_area(beam_section, 5000 * kNm)


def test_minimum_steel_area_refuses_non_rectangular():
    tee = rc_tee(1200, 150, 300, 600, concrete(32), n_bars=4, diameter=24,
                 fitment_spacing=200)
    with pytest.raises(ValueError, match="rectangular"):
        as3600.minimum_steel_area(tee, 500.0)


# ---------------------------------------------------------------------------
# AS 3600 shear
# ---------------------------------------------------------------------------


def test_as3600_shear_capacity_contract(beam_section):
    result = as3600.shear_capacity(beam_section, method="simplified")
    assert result.get("Vu") == pytest.approx(
        min(result.get("Vuc") + result.get("Vus"), result.get("Vumax"))
    )
    assert result.get("phiVu") == pytest.approx(0.7 * result.get("Vu"))


def test_as3600_effective_shear_depth(beam_section):
    dv = as3600.effective_shear_depth(beam_section, beam_section.d)
    assert dv == pytest.approx(max(0.72 * 600, 0.9 * beam_section.d))


def test_as3600_closer_fitments_give_more_capacity(beam_section):
    wide = beam_section.with_fitment(
        beam_section.fitment.__class__.from_bars(12, 300)
    )
    tight = beam_section.with_fitment(
        beam_section.fitment.__class__.from_bars(12, 100)
    )
    assert (
        as3600.shear_capacity(tight).get("Vus")
        > as3600.shear_capacity(wide).get("Vus")
    )


def test_as3600_no_fitments_gives_zero_vus():
    section = rc_beam(300, 600, concrete(32), n_bars=4, diameter=24)
    result = as3600.shear_capacity(section)
    assert result.get("Vus") == 0.0
    assert result.get("Vuc") > 0.0


def test_as3600_web_crushing_caps_capacity():
    """Very heavy fitments must not increase capacity beyond V_u,max."""
    section = rc_beam(200, 600, concrete(25), n_bars=4, diameter=24,
                      fitment_diameter=20, fitment_spacing=75)
    result = as3600.shear_capacity(section)
    assert result.get("Vu") == pytest.approx(result.get("Vumax"))
    assert any("web crushing" in m for m in result.messages)


def test_as3600_general_method_needs_actions(beam_section):
    simplified = as3600.shear_capacity(beam_section, method="simplified")
    general = as3600.shear_capacity(
        beam_section, M_star=200 * kNm, V_star=200 * kN, method="general"
    )
    assert "eps_x" in general.intermediates
    assert "eps_x" not in simplified.intermediates
    assert general.intermediates["theta_v"].value != pytest.approx(36.0)


def test_as3600_invalid_shear_method_raises(beam_section):
    with pytest.raises(ValueError, match="simplified"):
        as3600.shear_capacity(beam_section, method="nonsense")


def test_as3600_required_shear_reinforcement(beam_section):
    result = as3600.required_shear_reinforcement(beam_section, V_star=300 * kN)
    assert result.passed
    assert result.get("s_req") > 0


# ---------------------------------------------------------------------------
# AS 5100.5 -- shared mechanics, different code layer
# ---------------------------------------------------------------------------


def test_as5100_flexure_shares_mechanics_with_as3600(beam_section):
    """Same nominal capacity, different phi. That is the whole design intent
    of splitting rc_common out from the two code packages."""
    r3600 = as3600.moment_capacity(beam_section)
    r5100 = as5100_5.moment_capacity(beam_section)

    assert r5100.get("Muo") == pytest.approx(r3600.get("Muo"))
    assert r5100.get("phi") != pytest.approx(r3600.get("phi"))
    assert r5100.get("phiMuo") != pytest.approx(r3600.get("phiMuo"))


def test_as5100_shear_is_a_different_model(beam_section):
    """AS 5100.5 shear must not merely be AS 3600 with different constants."""
    r3600 = as3600.shear_capacity(beam_section)
    r5100 = as5100_5.shear_capacity(beam_section, V_star=200 * kN)

    # AS 5100.5 reports V_u,min, which has no counterpart in AS 3600:2018.
    assert "Vumin" in r5100.outputs
    assert "Vumin" not in r3600.outputs
    # And AS 3600:2018 reports k_v and d_v, which have no counterpart here.
    assert "kv" in r3600.intermediates
    assert "kv" not in r5100.intermediates
    assert "beta1" in r5100.intermediates


def test_as5100_vuc_depends_on_longitudinal_steel():
    """The older model's concrete contribution scales with the steel ratio --
    a behaviour AS 3600:2018's simplified method does not have."""
    light = rc_beam(300, 600, concrete(32), n_bars=2, diameter=16, fitment_spacing=200)
    heavy = rc_beam(300, 600, concrete(32), n_bars=6, diameter=28, fitment_spacing=200)

    v_light = as5100_5.shear_capacity(light, V_star=100 * kN).get("Vuc")
    v_heavy = as5100_5.shear_capacity(heavy, V_star=100 * kN).get("Vuc")
    assert v_heavy > v_light

    # The AS 5100.5 concrete term scales as (A_st/(b_v.d_o))^(1/3), so tripling
    # the steel ratio must move V_uc materially, not marginally.
    assert v_heavy / v_light > 1.3

    # AS 3600:2018 simplified: k_v is a fixed 0.15 once minimum fitments are
    # present, so the concrete term carries NO dependence on A_st. (V_uc itself
    # still differs slightly between these two sections because the larger bars
    # sit deeper and change d_v -- so the comparison must be on k_v.)
    a_light = as3600.shear_capacity(light)
    a_heavy = as3600.shear_capacity(heavy)
    assert a_light.intermediates["kv"].value == pytest.approx(
        a_heavy.intermediates["kv"].value, rel=1e-12
    )


def test_as5100_rejects_grade_below_its_minimum():
    """AS 5100.5 sets a higher minimum grade than AS 3600 for bridgeworks."""
    section = rc_beam(300, 600, concrete(20), n_bars=4, diameter=24, fitment_spacing=200)
    # AS 3600 accepts f'c = 20 MPa.
    assert as3600.moment_capacity(section).envelope.within
    # AS 5100.5 must not.
    with pytest.raises(OutsideEnvelope):
        as5100_5.moment_capacity(section)


# ---------------------------------------------------------------------------
# Contract compliance -- every module must honour it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [
        lambda s: as3600.moment_capacity(s),
        lambda s: as3600.check_flexure(s, 200 * kNm),
        lambda s: as3600.shear_capacity(s),
        lambda s: as3600.check_shear(s, 200 * kN),
        lambda s: as5100_5.moment_capacity(s),
        lambda s: as5100_5.shear_capacity(s, V_star=200 * kN),
    ],
)
def test_every_entry_point_honours_the_contract(beam_section, factory):
    result = factory(beam_section)
    assert result.name
    assert result.inputs, "inputs must be echoed"
    assert len(result.basis) > 0, "basis must cite clauses"
    assert result.envelope.limits, "envelope must declare limits"
    assert result.outputs, "outputs must be reported"
    assert result.provenance.module.startswith("austruct.")
    assert result.to_dict()["provenance"]["issuable"] is False, (
        "no module is verified yet -- if this fails, a module has been marked "
        "issuable and its golden vectors must be checked"
    )
