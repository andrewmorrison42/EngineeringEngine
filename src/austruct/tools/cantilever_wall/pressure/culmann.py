"""Method B -- Culmann trial wedge, searched numerically.

Every trial plane, at angle ``theta`` from horizontal, defines a wedge
bounded by the SAME virtual plane :mod:`.rankine` uses (vertical, through
the back of the heel -- see that module's docstring for why this is
canonical here), the ground surface above (with backslope), and the trial
plane itself. The wedge's weight (soil plus whatever surcharge sits ON that
wedge's own top surface -- see the note on surcharge below) is resolved
into the force the wall must supply to hold it, via the classical
three-force equilibrium (weight, the plane reaction at friction angle phi
from its normal, and the wall reaction). The critical plane is the one that
MAXIMISES that force -- searched by a fine grid over theta, not a closed
form, which is what lets this handle backslope and a finite wedge cleanly
without a combined-effects formula to get subtly wrong.

Wall friction (delta) is NOT modelled -- the virtual plane is treated as
frictionless here too (delta = 0), matching :mod:`.rankine`'s Rankine
assumption. This is deliberate: the highest-value check this method exists
for is convergence with Method A in the degenerate case, and that
convergence only holds when both methods share the same frictionless-plane
assumption. Crediting wall friction is a real extension, left for later,
noted in the README.

Two things this method does NOT do (yet), and fails loudly rather than
silently on
------------------------------------------------------------------------
- **Cohesion.** The wedge weight includes soil and surcharge only. Since
  this tool's own soil defaults take c' = 0 for retained fill, this rarely
  matters -- but where a cohesive preset (e.g. ``stiff_clay``) IS in use,
  Method A's cohesion relief term and Method B's lack of one is a real,
  named divergence source -- see :mod:`.divergence`.
- **A water table.** :func:`trial_wedge_thrust` raises ``NotImplementedError``
  rather than silently comparing a submerged-effective-stress Method A
  against a dry-unit-weight Method B, which would be misleading, not
  merely approximate. ``api.analyse`` catches this and reports that Method
  B was not run, rather than failing the whole assessment.

What this tool's surcharge model means for the "surcharge outside the
wedge" divergence source
-------------------------------------------------------------------------
The classic reason Method A and Method B diverge is a surcharge that sits
behind the failure wedge and so never loads it, while the closed-form
method applies it everywhere regardless. This tool's ``SoilInput.surcharge``
is a single flat, INFINITE-extent value -- there is no surcharge set-back
distance to model, and worked through algebraically (see the test suite),
the surcharge and the soil self-weight share the same wedge-angle
dependence, so a flat infinite surcharge alone (backslope = 0) makes the
two methods agree almost exactly. That is a genuine finding, not a gap:
the divergence source the brief anticipated needs a surcharge SET-BACK
input this tool does not yet have.

Backslope is a DIFFERENT, and genuinely real, divergence source
------------------------------------------------------------------
With backslope present, Method A (Rankine) and Method B (Coulomb/Culmann,
delta = 0) are NOT expected to agree, and do not: this is a well-known
theoretical distinction between the two classical theories, not a defect in
either implementation. Rankine's backslope solution assumes the stress
resultant on a vertical plane WITHIN the soil mass acts parallel to the
ground surface, from the equilibrium of a semi-infinite sloping mass;
Coulomb/Culmann wedge equilibrium at delta = 0 assumes the WALL reaction is
horizontal (perpendicular to the vertical wall), a different boundary
condition. The two coincide exactly at backslope = 0 (verified in the test
suite to floating-point precision) and diverge by a real, non-trivial
margin as backslope grows -- confirmed against Coulomb's closed-form
Ka(phi, beta, delta=0) formula, which this module's numerical search
reproduces exactly. Expect the divergence report to flag this whenever a
wall has a backslope, and treat it as the two theories genuinely disagreeing
about a sloped case, not as noise to average away.

[UNITS] This tool's own convention -- m, kN/m^3, kPa, kN/m, degrees.
[VECTOR] Classical wedge-equilibrium mechanics, cited FIRST_PRINCIPLES, same
         basis as :mod:`.rankine`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ....core.basis import Basis
from ....core.contract import CalcResult, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ..engine import DesignSoil
from .rankine import CLAUSE_RANKINE, ThrustComponents

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Culmann trial wedge search -- Method B",
    envelope_summary="Frictionless virtual plane, no cohesion credit, drained only",
)

N_TRIALS = 900
"""Grid resolution over the search range -- 0.1 degree steps. The
degenerate-case regression test checks this converges on the exact Rankine
closed form to within 0.1%, which bounds how coarse this can be."""


@dataclass(frozen=True)
class WedgeSearch:
    """The critical wedge, plus enough of the search to report it."""

    theta_deg: float
    thrust: ThrustComponents
    soil_weight: float
    surcharge_weight: float


def _wedge_geometry(
    theta_deg: float, H: float, backslope_deg: float  # noqa: N803
) -> float | None:
    """Horizontal extent of the wedge's top (ground-surface) edge, m, or
    ``None`` if this trial plane is not steep enough to intersect the
    (possibly sloping) ground ahead of the wall at all."""
    theta = math.radians(theta_deg)
    beta = math.radians(backslope_deg)
    denom = math.tan(theta) - math.tan(beta)
    if denom <= 0:
        return None
    return H / denom


def trial_wedge_thrust(
    H: float,  # noqa: N803
    design_soil: DesignSoil,
    gamma_char: float,
    backslope_deg: float,
    surcharge: float,
    water_table: float | None,
) -> WedgeSearch:
    """Search trial planes and return the critical wedge.

    Parameters
    ----------
    H:
        Height of the virtual plane, m -- same meaning as in
        :func:`~.rankine.active_thrust`.
    design_soil:
        Post-material-factor phi -- see :func:`~.engine.apply_material_factors`.
        Cohesion is present on this object but NOT used here; see the
        module docstring.
    water_table:
        Must be ``None`` -- see the module docstring.

    Raises
    ------
    NotImplementedError
        If ``water_table`` is not ``None``.
    ValueError
        If ``backslope_deg > design_soil.phi_deg`` (mirrors
        :func:`~.rankine.Ka_rankine`'s guard -- the same geometry is
        invalid for both methods), or if no trial plane in the search
        range is valid.
    """
    if water_table is not None:
        raise NotImplementedError(
            "Method B (trial wedge) does not yet model a water table. "
            "Comparing a submerged Method A against a dry-unit-weight "
            "Method B would be misleading, not merely approximate -- this "
            "raises rather than doing that silently."
        )
    phi = design_soil.phi_deg
    if backslope_deg > phi:
        raise ValueError(
            f"backslope ({backslope_deg:.1f} deg) exceeds phi ({phi:.1f} deg) "
            "-- the same geometry that invalidates Rankine invalidates the "
            "trial wedge search too."
        )

    lower = phi + 0.05
    upper = 89.95
    if lower >= upper:  # pragma: no cover -- phi is bounded well below 90 by SoilInput
        raise ValueError(f"No valid trial-plane search range for phi = {phi:.1f} deg")

    best_theta = lower
    best_P = -math.inf  # noqa: N806
    best_soil_weight = 0.0
    best_surcharge_weight = 0.0

    for i in range(N_TRIALS + 1):
        theta_deg = lower + (upper - lower) * i / N_TRIALS
        x_top = _wedge_geometry(theta_deg, H, backslope_deg)
        if x_top is None:
            continue
        soil_weight = 0.5 * x_top * H * gamma_char
        surcharge_weight = surcharge * x_top
        total_weight = soil_weight + surcharge_weight

        theta = math.radians(theta_deg)
        P = total_weight * math.tan(theta - math.radians(phi))  # noqa: N806
        if P > best_P:
            best_P = P  # noqa: N806
            best_theta = theta_deg
            best_soil_weight = soil_weight
            best_surcharge_weight = surcharge_weight

    if best_P <= 0:  # pragma: no cover -- defensive; the degenerate case always finds a positive peak
        raise ValueError("No valid trial plane produced a positive thrust")

    # [ASSUMPTION] Height of application H/3, borrowed from the Rankine
    # result -- the wedge method gives the resultant MAGNITUDE, not a
    # pressure distribution, and H/3 is the conventional assumption used in
    # practice even for a general (non-triangular-diagram) wedge search.
    thrust = ThrustComponents(horizontal=best_P, vertical=0.0, height=H / 3.0)
    return WedgeSearch(
        theta_deg=best_theta,
        thrust=thrust,
        soil_weight=best_soil_weight,
        surcharge_weight=best_surcharge_weight,
    )


def culmann_report(
    H: float,  # noqa: N803
    design_soil: DesignSoil,
    gamma_char: float,
    backslope_deg: float,
    surcharge: float,
    water_table: float | None,
) -> CalcResult:
    """The readable working behind :func:`trial_wedge_thrust`, as a
    :class:`~austruct.core.contract.CalcResult` -- same convention as
    :func:`~.rankine.rankine_report`."""
    env = Envelope(name="Culmann trial wedge search")
    env.add(
        "backslope <= phi", backslope_deg, upper=design_soil.phi_deg, unit="deg",
        basis=CLAUSE_RANKINE,
    )
    env.note("Frictionless virtual plane (delta = 0), no cohesion credit, drained only.")
    env.require()

    basis = Basis()
    basis.add(CLAUSE_RANKINE)

    result = CalcResult(
        name="Culmann trial wedge search -- Method B",
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

    search = trial_wedge_thrust(H, design_soil, gamma_char, backslope_deg, surcharge, water_table)

    result.add_intermediate(
        "theta_critical", Value(search.theta_deg, "deg", "theta_cr", "Critical trial plane angle")
    )
    result.add_intermediate(
        "soil_weight", Value(search.soil_weight, "kN/m", "W_soil", "Critical wedge soil weight")
    )
    result.add_intermediate(
        "surcharge_weight",
        Value(search.surcharge_weight, "kN/m", "W_q", "Surcharge on the critical wedge"),
    )
    result.add_output(
        "Ph", Value(search.thrust.horizontal, "kN/m", "P_h", "Horizontal thrust (delta = 0)")
    )
    result.add_output(
        "thrust_height", Value(search.thrust.height, "m", "h_P", "Height of P above the base")
    )
    result.note(
        f"{N_TRIALS + 1} trial planes searched from {design_soil.phi_deg + 0.05:.1f} deg "
        "to 89.95 deg; the critical plane above is the one MAXIMISING the thrust, "
        "not necessarily 45 + phi/2 once backslope and surcharge are present."
    )
    result.note(
        "Cohesion is NOT credited (see module docstring) -- if the soil has "
        "c' > 0, expect this method to read higher than Method A, which "
        "does credit it."
    )
    return result
