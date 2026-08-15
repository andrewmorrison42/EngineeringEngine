"""Unit tests for AS 3700 masonry flexure and shear.

Nothing here verifies the AS 3700 CONSTANTS -- ``constants.py`` is a heavily
simplified, prominently UNVERIFIED slice of the standard, same posture as
every other design package in this toolkit. These tests pin the MECHANICS
and the PLUMBING against hand calculations performed with the same
(documented) constants the modules use, so a future edit that silently
changes the arithmetic shows up here.
"""

from __future__ import annotations

import math

import pytest

from austruct.core.exceptions import ModelError, OutsideEnvelope
from austruct.core.units import kN, kNm
from austruct.design import as3700
from austruct.materials.bar_catalogue import bar_area
from austruct.materials.masonry import MortarClass, get_unit, masonry_properties, unit_names
from austruct.sections.masonry_section import MasonryReinforcement, masonry_wall


@pytest.fixture
def grade():
    """15 MPa unit, M3 mortar, grouted -- matches the worked hand calc below."""
    return masonry_properties(15.0, MortarClass.M3, grouted=True)


@pytest.fixture
def unreinforced_wall(grade):
    return masonry_wall(190, grade)


@pytest.fixture
def reinforced_wall(grade):
    return masonry_wall(190, grade, bar_area_per_metre=bar_area(16) * 1000 / 600, bar_depth=95)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


def test_every_catalogue_unit_resolves():
    for name in unit_names():
        u = get_unit(name)
        assert u.f_uc > 0
        assert u.thickness > 0


def test_unknown_unit_raises():
    with pytest.raises(KeyError):
        get_unit("not_a_real_unit")


def test_fm_matches_the_documented_formula():
    g = masonry_properties(15.0, MortarClass.M3, grouted=False)
    expected = 1.4 * math.sqrt(15.0) * 0.9
    assert g.f_m == pytest.approx(expected)


def test_grouting_raises_fmt_and_fms_but_not_fm():
    dry = masonry_properties(15.0, MortarClass.M4, grouted=False)
    wet = masonry_properties(15.0, MortarClass.M4, grouted=True)
    assert wet.f_mt > dry.f_mt
    assert wet.f_ms > dry.f_ms
    assert wet.f_m == pytest.approx(dry.f_m)


def test_fmt_parallel_is_the_kp_multiple_of_fmt():
    g = masonry_properties(15.0, MortarClass.M3)
    assert g.f_mt_parallel == pytest.approx(2.0 * g.f_mt)


def test_weaker_mortar_gives_lower_fm():
    strong = masonry_properties(15.0, MortarClass.M4)
    weak = masonry_properties(15.0, MortarClass.M1)
    assert weak.f_m < strong.f_m


def test_f_uc_outside_the_envelope_is_rejected():
    with pytest.raises(OutsideEnvelope):
        masonry_properties(1.0)  # below the 5 MPa floor


# ---------------------------------------------------------------------------
# Section geometry
# ---------------------------------------------------------------------------


def test_Z_is_the_rectangular_strip_formula(unreinforced_wall):
    assert unreinforced_wall.Z == pytest.approx(1000.0 * 190.0**2 / 6.0)


def test_reinforcement_deeper_than_the_wall_is_rejected(grade):
    with pytest.raises(ModelError):
        masonry_wall(190, grade, bar_area_per_metre=300.0, bar_depth=200.0)


def test_ast_scales_with_design_width(grade):
    per_metre = bar_area(16) * 1000 / 600
    reinf = MasonryReinforcement(area_per_metre=per_metre, depth=95)
    from austruct.sections.masonry_section import MasonryWallSection

    half_metre = MasonryWallSection(
        thickness=190, masonry=grade, design_width=500.0, reinforcement=reinf
    )
    assert half_metre.Ast == pytest.approx(per_metre * 0.5)


# ---------------------------------------------------------------------------
# Flexure -- unreinforced, hand-verified
# ---------------------------------------------------------------------------


def test_vertical_bending_matches_hand_calculation(unreinforced_wall):
    """Muo = (f'mt + fd_credited).Z, phi = 0.6, at fd = 0.2 MPa (below the
    fd_credit cap of 2.0 x 0.40 = 0.80 MPa, so fully credited)."""
    result = as3700.vertical_bending_capacity(unreinforced_wall, fd=0.2)
    Z = 1000.0 * 190.0**2 / 6.0
    expected_Muo = (0.40 + 0.2) * Z
    assert result.get("Muo") == pytest.approx(expected_Muo)
    assert result.get("phiMuo") == pytest.approx(0.6 * expected_Muo)


def test_fd_credit_is_capped(unreinforced_wall):
    """fd = 5 MPa is far beyond the 2x f'mt = 0.80 MPa cap -- only 0.80 MPa
    of it is credited toward the capacity."""
    result = as3700.vertical_bending_capacity(unreinforced_wall, fd=5.0)
    Z = 1000.0 * 190.0**2 / 6.0
    expected_Muo = (0.40 + 0.80) * Z
    assert result.get("Muo") == pytest.approx(expected_Muo)
    assert result.messages  # the cap note is recorded


def test_horizontal_bending_uses_fmt_parallel_and_no_fd(unreinforced_wall):
    result = as3700.horizontal_bending_capacity(unreinforced_wall)
    Z = 1000.0 * 190.0**2 / 6.0
    expected_Muo = 0.80 * Z  # f'mt_parallel = 2.0 x 0.40
    assert result.get("Muo") == pytest.approx(expected_Muo)


def test_horizontal_bending_capacity_exceeds_vertical(unreinforced_wall):
    """kp = 2.0 and no fd on the horizontal case -- the horizontal capacity
    must exceed vertical bending at fd = 0 for the same wall."""
    vertical = as3700.vertical_bending_capacity(unreinforced_wall, fd=0.0)
    horizontal = as3700.horizontal_bending_capacity(unreinforced_wall)
    assert horizontal.get("Muo") > vertical.get("Muo")


def test_unreinforced_functions_reject_a_reinforced_section(reinforced_wall):
    with pytest.raises(ValueError, match="UNREINFORCED"):
        as3700.vertical_bending_capacity(reinforced_wall)
    with pytest.raises(ValueError, match="UNREINFORCED"):
        as3700.horizontal_bending_capacity(reinforced_wall)


# ---------------------------------------------------------------------------
# Flexure -- reinforced, hand-verified
# ---------------------------------------------------------------------------


def test_reinforced_capacity_matches_hand_calculation(reinforced_wall):
    result = as3700.reinforced_moment_capacity(reinforced_wall)
    Ast = bar_area(16) * 1000 / 600
    fsy, f_m, b, d = 500.0, reinforced_wall.masonry.f_m, 1000.0, 95.0
    a = Ast * fsy / (0.85 * f_m * b)
    expected_Muo = Ast * fsy * (d - a / 2.0)
    assert result.get("a") == pytest.approx(a)
    assert result.get("Muo") == pytest.approx(expected_Muo)
    assert result.get("phiMuo") == pytest.approx(0.75 * expected_Muo)


def test_reinforced_function_rejects_an_unreinforced_section(unreinforced_wall):
    with pytest.raises(ValueError, match="requires reinforcement"):
        as3700.reinforced_moment_capacity(unreinforced_wall)


def test_over_reinforced_wall_fails_ductility_even_though_strength_passes():
    """A heavily over-reinforced wall can develop a large Muo while its
    stress block depth ratio breaches the ductility limit -- the governing
    utilisation must come from the ductility check, not the strength one."""
    grade = masonry_properties(15.0, MortarClass.M3, grouted=True)
    heavy = masonry_wall(190, grade, bar_area_per_metre=bar_area(20) * 1000 / 200, bar_depth=95)
    result = as3700.check_flexure(heavy, 1.0 * kNm)  # tiny M* -- strength easily passes
    ductility_check = next(c for c in result.checks if "Ductility" in c.label)
    assert not ductility_check.passed
    assert not result.passed
    assert result.utilisation == pytest.approx(ductility_check.utilisation)


# ---------------------------------------------------------------------------
# check_flexure dispatch
# ---------------------------------------------------------------------------


def test_check_flexure_dispatches_to_reinforced_when_present(reinforced_wall, unreinforced_wall):
    reinforced_result = as3700.check_flexure(reinforced_wall, 5.0 * kNm)
    unreinforced_result = as3700.check_flexure(unreinforced_wall, 5.0 * kNm, direction="vertical")
    # Reinforced dispatch produces the ductility check; unreinforced does not.
    assert any("Ductility" in c.label for c in reinforced_result.checks)
    assert not any("Ductility" in c.label for c in unreinforced_result.checks)


def test_check_flexure_unknown_direction_raises(unreinforced_wall):
    with pytest.raises(ValueError, match="direction"):
        as3700.check_flexure(unreinforced_wall, 1.0 * kNm, direction="sideways")


def test_check_flexure_pass_and_fail(unreinforced_wall):
    weak = as3700.check_flexure(unreinforced_wall, 5.0 * kNm, direction="vertical")
    assert not weak.passed
    strong = as3700.check_flexure(unreinforced_wall, 0.5 * kNm, direction="vertical")
    assert strong.passed


# ---------------------------------------------------------------------------
# Shear -- hand-verified
# ---------------------------------------------------------------------------


def test_shear_capacity_matches_hand_calculation(unreinforced_wall):
    result = as3700.shear_capacity(unreinforced_wall, fd=0.2)
    v = 0.25 + 0.30 * 0.2  # f'ms (grouted) + kv.fd
    A = 1000.0 * 190.0
    expected_Vo = v * A
    assert result.get("Vo") == pytest.approx(expected_Vo)
    assert result.get("phiVo") == pytest.approx(0.6 * expected_Vo)  # unreinforced phi


def test_shear_stress_is_capped_at_high_fd(unreinforced_wall):
    result = as3700.shear_capacity(unreinforced_wall, fd=100.0)
    A = 1000.0 * 190.0
    assert result.get("Vo") == pytest.approx(2.0 * A)  # SHEAR_STRESS_CAP
    assert result.messages


def test_shear_capacity_is_identical_with_or_without_flexural_reinforcement(grade):
    """Vertical bars resist flexure, not this sliding-shear mechanism -- the
    MASONRY contribution (Vo before phi) must be unchanged by reinforcement,
    even though phi (and hence phiVo) differs by category."""
    plain = masonry_wall(190, grade)
    reinforced = masonry_wall(190, grade, bar_area_per_metre=300.0, bar_depth=95)
    r1 = as3700.shear_capacity(plain, fd=0.15)
    r2 = as3700.shear_capacity(reinforced, fd=0.15)
    assert r1.get("Vo") == pytest.approx(r2.get("Vo"))
    assert r2.get("phiVo") != r1.get("phiVo")  # different phi row


def test_check_shear_pass_and_fail(unreinforced_wall):
    weak = as3700.check_shear(unreinforced_wall, 40.0 * kN, fd=0.1)
    assert not weak.passed
    strong = as3700.check_shear(unreinforced_wall, 5.0 * kN, fd=0.1)
    assert strong.passed
