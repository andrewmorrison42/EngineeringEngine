"""Method A -- Rankine active earth pressure on a virtual plane through the
heel, integrated numerically over depth.

The virtual plane is CANONICAL here: a vertical plane erected at the back
edge of the heel (== the back edge of the footing, since the stem's back
face is held vertical -- see :func:`~.engine.concrete_self_weight`). Soil
resting on the heel between the stem and this plane is carried as part of
the wall's stabilising weight (:func:`~.engine.heel_soil_weight`), not as
part of the earth-pressure force. :func:`~.models.WallGeometry` asserts this
plane clears the stem (``heel_length > 0``) before any of this runs.

Why numerical integration rather than the closed-form algebra
---------------------------------------------------------------
The classic closed-form results (``P = 0.5 Ka.gamma.H^2.cos(beta)``, height
``H/3``) only combine cleanly with EITHER a backslope OR a water table OR a
surcharge in isolation. Combining all three correctly is a longer derivation
than it is worth getting subtly wrong -- so the pressure diagram is built
depth-slice by depth-slice and integrated by the trapezoidal rule instead.
For the pure triangular case (no water table, no surcharge, beta = 0) this
reproduces the closed-form ``H/3`` height to numerical precision, because the
trapezoidal rule is exact for a linear integrand -- see the regression test.

[TRAP] Effective stress and the water table are kept SEPARATE deliberately:
       the earth-pressure integration below always uses submerged unit
       weight below the water table, and the hydrostatic thrust is returned
       as its own force, never added into ``thrust_horizontal``. Lumping the
       two together is a common, code-invisible error this module structure
       makes hard to make by accident.

[VECTOR] Rankine active earth pressure theory is classical soil mechanics,
         not itself an AS 4678 clause -- cited FIRST_PRINCIPLES. The
         cohesion-relief term and the backslope+surcharge combination
         formula are UNVERIFIED simplifications; see the notes below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ....core.basis import FIRST_PRINCIPLES, Basis, ClauseRef
from ....core.contract import CalcResult, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ..engine import GAMMA_WATER, DesignSoil

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Rankine active earth pressure on a virtual plane through the heel",
    envelope_summary="Homogeneous soil, vertical virtual plane, backslope <= phi",
)

CLAUSE_RANKINE = ClauseRef(FIRST_PRINCIPLES, note="Classical Rankine active earth pressure theory")

N_SLICES = 400
"""Trapezoidal-rule slice count. Exact for the linear (no WT, no surcharge)
case regardless of count; fine enough elsewhere that halving or doubling it
does not move a reported result in its third significant figure."""


def Ka_rankine(phi_deg: float, backslope_deg: float = 0.0) -> float:
    """Rankine active pressure coefficient, with backslope.

    ``Ka = cos(beta) . [cos(beta) - sqrt(cos^2(beta) - cos^2(phi))]``
    ``     / [cos(beta) + sqrt(cos^2(beta) - cos^2(phi))]``

    Reduces to the familiar ``(1-sin(phi))/(1+sin(phi))`` at ``beta = 0``.

    Raises
    ------
    ValueError
        If ``backslope_deg > phi_deg`` -- the backslope is then steeper than
        the soil can stand at, and Rankine theory does not apply.
    """
    if backslope_deg > phi_deg:
        raise ValueError(
            f"backslope ({backslope_deg:.1f} deg) exceeds phi ({phi_deg:.1f} deg) "
            "-- Rankine active pressure is undefined for a slope steeper than "
            "the soil's own friction angle"
        )
    phi = math.radians(phi_deg)
    beta = math.radians(backslope_deg)
    cos_b = math.cos(beta)
    root = math.sqrt(max(cos_b**2 - math.cos(phi) ** 2, 0.0))
    return cos_b * (cos_b - root) / (cos_b + root)


def Kp_rankine(phi_deg: float) -> float:
    """Rankine passive pressure coefficient, horizontal ground, no wall
    friction credit: ``Kp = (1+sin(phi))/(1-sin(phi))``.

    Using plain Rankine (delta = 0) rather than Coulomb passive sidesteps
    the Coulomb-at-high-delta overestimate the brief warns about -- there is
    no wall-friction credit to overestimate. Revisit only if the office
    wants that credit, at which point a Caquot-Kerisel lookup or a delta
    cap at phi/3 is needed instead of the plain Coulomb formula.
    """
    phi = math.radians(phi_deg)
    return (1.0 + math.sin(phi)) / (1.0 - math.sin(phi))


@dataclass(frozen=True)
class ThrustComponents:
    """Resultant earth-pressure thrust, decomposed for the stability ledger.

    [UNITS] forces kN/m (per metre run), height m above the base.
    """

    horizontal: float
    vertical: float
    height: float


def active_thrust(
    H: float,  # noqa: N803
    design_soil: DesignSoil,
    gamma_char: float,
    backslope_deg: float,
    surcharge: float,
    water_table: float | None,
) -> ThrustComponents:
    """Integrate the Rankine active pressure diagram over the full height.

    Parameters
    ----------
    H:
        Total height of the virtual plane, m (== ``geometry.H_retained``).
    design_soil:
        Post-material-factor phi and cohesion -- see
        :func:`~.engine.apply_material_factors`. ``gamma_char`` is passed
        separately because unit weight is not a strength and is never
        factored.
    backslope_deg, surcharge, water_table:
        As resolved onto :class:`~.models.ResolvedSoil`. ``water_table`` is
        depth (m) below the TOP of the retained soil, or ``None`` (drained).

    [ASSUMPTION] The cohesion-relief term (``-2c.sqrt(Ka)``) is only applied
                 for a horizontal backslope. For beta != 0 it is dropped
                 (conservatively -- no credit, not a penalty) rather than
                 combined with the backslope algebra, which the classical
                 formula does not cleanly extend to. Revisit if a cohesive
                 preset is ever paired with a sloped backfill in practice.
    [ASSUMPTION] Surcharge behind a sloped backfill is treated as an
                 additional uniform vertical stress added before the
                 ``cos(beta)`` projection -- a common simplified practice,
                 not the more exact "equivalent height of fill" construction.
    """
    Ka = Ka_rankine(design_soil.phi_deg, backslope_deg)
    beta = math.radians(backslope_deg)
    wt_depth = water_table if (water_table is not None and water_table < H) else None

    def sigma_v(z: float) -> float:
        """Vertical effective stress at depth z below the top of soil."""
        if wt_depth is None or z <= wt_depth:
            return gamma_char * z
        gamma_sub = gamma_char - GAMMA_WATER
        return gamma_char * wt_depth + gamma_sub * (z - wt_depth)

    def intensity(z: float) -> float:
        base = Ka * (sigma_v(z) + surcharge)
        if backslope_deg == 0.0:
            base -= 2.0 * design_soil.cohesion * math.sqrt(Ka)
        return max(base, 0.0) * math.cos(beta)

    dz = H / N_SLICES
    P = 0.0  # resultant magnitude, acting parallel to the backslope
    first_moment_about_base = 0.0
    for i in range(N_SLICES):
        z0, z1 = i * dz, (i + 1) * dz
        i0, i1 = intensity(z0), intensity(z1)
        strip = 0.5 * (i0 + i1) * dz
        # Height above the BASE of this strip's centroid, weighted by area:
        h0, h1 = H - z0, H - z1
        strip_height = (i0 * h0 + i1 * h1) / (i0 + i1) if (i0 + i1) > 0 else 0.5 * (h0 + h1)
        P += strip
        first_moment_about_base += strip * strip_height

    height = first_moment_about_base / P if P > 0 else H / 3.0

    return ThrustComponents(
        horizontal=P * math.cos(beta),
        vertical=P * math.sin(beta),
        height=height,
    )


def hydrostatic_thrust(H: float, water_table: float | None) -> ThrustComponents:  # noqa: N803
    """Triangular hydrostatic thrust below the water table -- a SEPARATE
    action from the earth pressure above, never lumped into it."""
    if water_table is None or water_table >= H:
        return ThrustComponents(horizontal=0.0, vertical=0.0, height=0.0)
    submerged_height = H - water_table
    P = 0.5 * GAMMA_WATER * submerged_height**2
    return ThrustComponents(horizontal=P, vertical=0.0, height=submerged_height / 3.0)


def rankine_report(
    H: float,  # noqa: N803
    design_soil: DesignSoil,
    gamma_char: float,
    backslope_deg: float,
    surcharge: float,
    water_table: float | None,
) -> CalcResult:
    """The full readable working behind :func:`active_thrust`, as a
    :class:`~austruct.core.contract.CalcResult` -- this is where "every
    check must emit readable working" is satisfied, by reusing the same
    report contract the rest of ``austruct`` uses rather than a separate
    rendering library.
    """
    env = Envelope(name="Rankine active pressure, virtual plane through heel")
    env.add(
        "backslope <= phi", backslope_deg, upper=design_soil.phi_deg, unit="deg",
        basis=CLAUSE_RANKINE,
    )
    env.note("Homogeneous soil over the full height -- see Method B for layering.")
    env.require()

    basis = Basis()
    basis.add(CLAUSE_RANKINE)

    result = CalcResult(
        name="Rankine active earth pressure -- virtual plane through heel",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input("H", Value(H, "m", "H", "Height of the virtual plane"))
    result.add_input(
        "phi_design", Value(design_soil.phi_deg, "deg", "phi_design", "Design friction angle")
    )
    result.add_input("gamma", Value(gamma_char, "kN/m^3", "gamma", "Unit weight"))
    result.add_input("backslope", Value(backslope_deg, "deg", "beta", "Backslope"))
    result.add_input("surcharge", Value(surcharge, "kPa", "q", "Surcharge"))
    result.add_input(
        "water_table",
        Value(water_table if water_table is not None else -1.0, "m", "z_w", "Water table depth"),
    )
    Ka = Ka_rankine(design_soil.phi_deg, backslope_deg)
    result.add_intermediate("Ka", Value(Ka, "-", "Ka", "Active pressure coefficient"))

    thrust = active_thrust(H, design_soil, gamma_char, backslope_deg, surcharge, water_table)
    hydro = hydrostatic_thrust(H, water_table)

    result.add_output(
        "Ph", Value(thrust.horizontal, "kN/m", "P_h", "Horizontal earth-pressure thrust")
    )
    result.add_output(
        "Pv", Value(thrust.vertical, "kN/m", "P_v", "Vertical earth-pressure thrust")
    )
    result.add_output(
        "thrust_height", Value(thrust.height, "m", "h_P", "Height of P above the base")
    )
    result.add_output(
        "Ph_hydrostatic", Value(hydro.horizontal, "kN/m", "P_w", "Hydrostatic thrust (separate)")
    )
    result.add_output(
        "hydrostatic_height", Value(hydro.height, "m", "h_w", "Height of P_w above the base")
    )

    if water_table is not None and water_table < H:
        result.note(
            "Water table within the retained height -- earth pressure above "
            "uses moist unit weight, submerged unit weight below; hydrostatic "
            "thrust is reported as a SEPARATE action, not added into P_h."
        )
    if backslope_deg > 0:
        result.note(
            "Backslope present: cohesion relief is not credited in this case "
            "(dropped conservatively, not combined with the backslope algebra)."
        )
    result.note(
        "This closed-form method applies the full surcharge to the virtual "
        "plane regardless of where it sits behind the wall. A trial wedge "
        "(Method B, not yet implemented) would exclude surcharge outside the "
        "failure wedge -- expect this method to read higher whenever the "
        "surcharge is set well back from the wall, and treat that as an "
        "expected divergence source, not a discrepancy to chase."
    )

    return result
