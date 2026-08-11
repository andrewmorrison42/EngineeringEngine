"""Unit tests for the analysis layer.

These test the solver against the closed-form module directly, which is the
comparison the golden vectors formalise. Kept separate from the vectors so that
the vectors stay a curated, signed-off set while these can grow freely.
"""

from __future__ import annotations

import math

import pytest

from austruct.analysis import (
    UDL,
    AppliedMoment,
    PartialUDL,
    PointLoad,
    Support,
    SupportType,
    VaryingUDL,
    cantilever,
    cantilever_tip_point,
    cantilever_udl,
    continuous,
    fixed_central_point,
    fixed_fixed,
    fixed_udl,
    propped_cantilever,
    propped_central_point,
    propped_udl,
    simply_supported,
    ss_central_point,
    ss_offset_point,
    ss_udl,
)
from austruct.core.exceptions import ModelError
from austruct.core.units import kN, kN_per_m, kNm, m

EI = 1.62e14  # N.mm^2
L = 8.0 * m
W = 25.0 * kN_per_m
P = 100.0 * kN

REL = 1e-6


def close(a: float, b: float, rel: float = REL) -> bool:
    if abs(b) < 1e-9:
        return abs(a) < 1e-6
    return abs(a - b) / abs(b) <= rel


# ---------------------------------------------------------------------------
# Solver vs closed form
# ---------------------------------------------------------------------------


def test_simply_supported_udl():
    r = simply_supported(L, (UDL(magnitude=W),), EI=EI).solve()
    e = ss_udl(W, L, EI)
    assert close(r.reactions[0].force, e.R_left)
    assert close(r.max_moment, e.M_max)
    assert close(r.max_deflection, e.deflection_max)
    assert close(r.max_shear, W * L / 2)


def test_simply_supported_central_point():
    r = simply_supported(L, (PointLoad(position=L / 2, magnitude=P),), EI=EI).solve()
    e = ss_central_point(P, L, EI)
    assert close(r.reactions[0].force, e.R_left)
    assert close(r.max_moment, e.M_max)
    assert close(r.max_deflection, e.deflection_max)


@pytest.mark.parametrize("a_frac", [0.25, 0.4, 0.5, 0.6, 0.75])
def test_simply_supported_offset_point(a_frac):
    a = a_frac * L
    r = simply_supported(L, (PointLoad(position=a, magnitude=P),), EI=EI).solve()
    e = ss_offset_point(P, a, L, EI)
    assert close(r.reactions[0].force, e.R_left)
    assert close(r.reactions[1].force, e.R_right)
    assert close(r.max_moment, e.M_max)
    # Deflection interpolation between nodes carries a little more error.
    assert close(r.max_deflection, e.deflection_max, rel=1e-4)


def test_cantilever_udl():
    r = cantilever(L, (UDL(magnitude=W),), EI=EI).solve()
    e = cantilever_udl(W, L, EI)
    assert close(r.reactions[0].force, e.R_left)
    assert close(r.min_moment, e.M_left)
    assert close(r.max_deflection, e.deflection_max)


def test_cantilever_tip_point():
    r = cantilever(L, (PointLoad(position=L, magnitude=P),), EI=EI).solve()
    e = cantilever_tip_point(P, L, EI)
    assert close(r.reactions[0].force, e.R_left)
    assert close(r.min_moment, e.M_left)
    assert close(r.max_deflection, e.deflection_max)


def test_propped_cantilever_udl():
    """The indeterminate case -- what a formula catalogue cannot generalise."""
    r = propped_cantilever(L, (UDL(magnitude=W),), EI=EI).solve()
    e = propped_udl(W, L, EI)
    assert close(r.reactions[0].force, e.R_left)
    assert close(r.reactions[1].force, e.R_right)
    assert close(r.min_moment, e.M_left)
    assert close(r.max_moment, e.M_max)
    # The 185 denominator in the closed form is rounded; see closed_form.py.
    assert close(r.max_deflection, e.deflection_max, rel=5e-3)


def test_propped_cantilever_central_point():
    r = propped_cantilever(L, (PointLoad(position=L / 2, magnitude=P),), EI=EI).solve()
    e = propped_central_point(P, L, EI)
    assert close(r.reactions[0].force, e.R_left)
    assert close(r.reactions[1].force, e.R_right)
    assert close(r.min_moment, e.M_left)
    assert close(r.max_moment, e.M_max)


def test_fixed_fixed_udl():
    r = fixed_fixed(L, (UDL(magnitude=W),), EI=EI).solve()
    e = fixed_udl(W, L, EI)
    assert close(r.min_moment, e.M_left)
    assert close(r.max_moment, e.M_max)
    assert close(r.max_deflection, e.deflection_max)


def test_fixed_fixed_central_point():
    r = fixed_fixed(L, (PointLoad(position=L / 2, magnitude=P),), EI=EI).solve()
    e = fixed_central_point(P, L, EI)
    assert close(r.min_moment, e.M_left)
    assert close(r.max_moment, e.M_max)
    assert close(r.max_deflection, e.deflection_max)


def test_two_span_continuous_udl():
    """Support moment = -wL^2/8, centre reaction = 1.25wL."""
    r = continuous([L, L], (UDL(magnitude=W),), EI=EI).solve()
    assert close(r.min_moment, -W * L**2 / 8)
    assert close(r.reactions[1].force, 1.25 * W * L)
    assert close(r.reactions[0].force, 0.375 * W * L)


def test_three_span_continuous_equilibrium():
    r = continuous([L, L, L], (UDL(magnitude=W),), EI=EI).solve()
    assert close(r.total_reaction, W * 3 * L)


# ---------------------------------------------------------------------------
# Sign conventions -- the part most likely to be silently wrong
# ---------------------------------------------------------------------------


def test_applied_moment_sign_convention():
    """A positive AppliedMoment increases the sagging moment to its right."""
    M0 = 100.0 * kNm
    r = simply_supported(L, (AppliedMoment(position=L / 2, magnitude=M0),), EI=EI).solve()
    assert close(r.reactions[0].force, -M0 / L, rel=1e-5)
    assert close(r.moment_at(L / 2 - 1.0), -M0 / 2, rel=1e-2)
    assert close(r.moment_at(L / 2 + 1.0), +M0 / 2, rel=1e-2)


def test_downward_load_gives_positive_deflection_and_sagging():
    r = simply_supported(L, (UDL(magnitude=W),), EI=EI).solve()
    assert r.max_deflection > 0
    assert r.max_moment > 0
    assert r.deflection_at(L / 2) > r.deflection_at(L / 10)


def test_cantilever_root_moment_is_hogging():
    r = cantilever(L, (UDL(magnitude=W),), EI=EI).solve()
    assert r.moment_at(0.0) < 0
    # The free end carries no moment. Compared against the scale of the
    # diagram rather than against an absolute tolerance -- moments are stored
    # in N.mm, so "zero" here is order 1e-8 of a peak of order 1e9.
    assert abs(r.moment_at(L)) < 1e-6 * abs(r.min_moment)


# ---------------------------------------------------------------------------
# Load types
# ---------------------------------------------------------------------------


def test_partial_udl_equilibrium_and_symmetry():
    load = PartialUDL(start=2 * m, end=6 * m, magnitude=W)
    r = simply_supported(L, (load,), EI=EI).solve()
    assert close(r.total_reaction, W * 4 * m)
    # Symmetric about midspan, so the reactions must be equal.
    assert close(r.reactions[0].force, r.reactions[1].force)


def test_triangular_load_reactions():
    """Triangular load zero at left, w at right: R_left = wL/6, R_right = wL/3."""
    load = VaryingUDL(start=0.0, end=L, w_start=0.0, w_end=W)
    r = simply_supported(L, (load,), EI=EI).solve()
    assert close(r.total_reaction, 0.5 * W * L)
    assert close(r.reactions[0].force, W * L / 6)
    assert close(r.reactions[1].force, W * L / 3)


def test_trapezoidal_load_equilibrium():
    load = VaryingUDL(start=1 * m, end=7 * m, w_start=10 * kN_per_m, w_end=30 * kN_per_m)
    r = simply_supported(L, (load,), EI=EI).solve()
    assert close(r.total_reaction, 0.5 * (10 + 30) * kN_per_m * 6 * m)


def test_superposition_of_load_types():
    """Combined loading equals the sum of the individual cases."""
    udl = UDL(magnitude=W)
    pt = PointLoad(position=3 * m, magnitude=P)

    combined = simply_supported(L, (udl, pt), EI=EI).solve()
    only_udl = simply_supported(L, (udl,), EI=EI).solve()
    only_pt = simply_supported(L, (pt,), EI=EI).solve()

    x = 3 * m
    assert close(
        combined.moment_at(x), only_udl.moment_at(x) + only_pt.moment_at(x), rel=1e-5
    )
    assert close(
        combined.deflection_at(x),
        only_udl.deflection_at(x) + only_pt.deflection_at(x),
        rel=1e-5,
    )


def test_point_load_is_not_double_counted():
    """A point load sitting exactly on a mesh node must be applied once."""
    for pos_frac in (0.0, 0.125, 0.25, 0.5, 0.75, 1.0):
        r = simply_supported(
            L, (PointLoad(position=pos_frac * L, magnitude=P),), EI=EI
        ).solve()
        assert close(r.total_reaction, P), f"failed at position fraction {pos_frac}"


# ---------------------------------------------------------------------------
# Model validation -- fail closed
# ---------------------------------------------------------------------------


def test_unstable_beam_raises():
    """One roller is a mechanism, not a beam."""
    from austruct.analysis import Beam

    beam = Beam(
        length=L,
        supports=(Support(0.0, SupportType.ROLLER),),
        loads=(UDL(magnitude=W),),
        EI=EI,
    )
    with pytest.raises(ModelError, match="unstable"):
        beam.solve()


def test_unrestrained_beam_raises():
    from austruct.analysis import Beam

    beam = Beam(length=L, supports=(), loads=(UDL(magnitude=W),), EI=EI)
    with pytest.raises(ModelError, match="no restraints"):
        beam.solve()


def test_support_outside_member_raises():
    from austruct.analysis import Beam

    with pytest.raises(ModelError, match="outside the member"):
        Beam(
            length=L,
            supports=(Support(0.0), Support(L * 2)),
            loads=(),
            EI=EI,
        )


def test_beam_without_stiffness_raises():
    from austruct.analysis import Beam

    with pytest.raises(ModelError, match="EI"):
        Beam(length=L, supports=(Support(0.0), Support(L)), loads=())


def test_negative_length_raises():
    from austruct.analysis import Beam

    with pytest.raises(ModelError):
        Beam(length=-1.0, supports=(), loads=(), EI=EI)


# ---------------------------------------------------------------------------
# Results interrogation
# ---------------------------------------------------------------------------


def test_shear_at_d_from_support():
    d = 500.0
    r = simply_supported(L, (UDL(magnitude=W),), EI=EI).solve()
    left, right = r.shear_at_d_from_support(d)
    expected = W * L / 2 - W * d
    assert close(left, expected, rel=1e-4)
    assert close(right, expected, rel=1e-4)


def test_udl_length_filled_from_member():
    """UDL(magnitude=...) with no length picks it up from the beam."""
    beam = simply_supported(L, (UDL(magnitude=W),), EI=EI)
    assert math.isclose(beam.loads[0].length, L)
    assert math.isclose(beam.total_load, W * L)


def test_results_convert_to_calc_result():
    r = simply_supported(L, (UDL(magnitude=W),), EI=EI).solve()
    cr = r.to_calc_result()
    assert close(cr.get("M_max"), W * L**2 / 8)
    assert "V_max" in cr.outputs
    assert cr.to_json()
