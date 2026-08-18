"""General Coulomb active earth pressure on a battered wall face.

Unlike ``cantilever_wall.pressure.rankine`` (a virtual VERTICAL plane
through the heel, because that wall has a heel slab to erect one on), a
modular gravity block wall has no heel -- the earth pressure is taken to
act directly on the wall's own back face, battered ``omega`` degrees from
vertical by the block's course setback (see :attr:`.blocks.BlockSeries.batter_deg`),
with wall friction ``delta`` between the soil and that face. This needs the
general Coulomb formula (Rankine has no wall-friction or wall-batter term),
and Method B in the cantilever wall tool doesn't help either -- Culmann's
trial-wedge search already assumes ``delta = 0`` for comparability with
Method A, which is exactly the term this wall needs credit for.

[TRAP] The resultant's direction convention here is Coulomb's own -- acting
       on the wall at ``(delta + omega)`` from HORIZONTAL, against the back
       face -- NOT Rankine's "parallel to the backslope" convention used in
       ``rankine.py``. The two conventions coincide only where both delta
       and omega (and beta) are zero; do not mix formulas from the two
       modules. See the regression test that pins this coincidence.

[VECTOR] Coulomb active earth pressure theory is classical soil mechanics,
         cited FIRST_PRINCIPLES. Cohesion is not modelled at all here (see
         :func:`active_thrust`) and there is no water table -- both
         deliberate simplifications for a system specified with a
         free-draining granular backfill; see the package README.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...core.basis import FIRST_PRINCIPLES, Basis, ClauseRef
from ...core.contract import CalcResult, Value
from ...core.envelope import Envelope
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ..cantilever_wall.models import ResolvedSoil

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Coulomb active earth pressure, general wall batter and wall friction",
    envelope_summary="Homogeneous, cohesionless soil, backslope <= phi",
)

CLAUSE_COULOMB = ClauseRef(FIRST_PRINCIPLES, note="Classical Coulomb active earth pressure theory")

N_SLICES = 400
"""Trapezoidal-rule slice count -- matches ``rankine.py``'s convention, even
though Ka here does not vary with depth; kept numerical (rather than the
available closed form) so this module extends the same way ``rankine.py``
would if a layered or depth-varying case were ever added."""


def Ka_coulomb(
    phi_deg: float, omega_deg: float = 0.0, beta_deg: float = 0.0, delta_deg: float = 0.0
) -> float:
    """Coulomb active pressure coefficient, general wall batter and friction.

    ``Ka = cos^2(phi - omega) / [cos^2(omega).cos(delta+omega).
    (1 + sqrt[sin(phi+delta).sin(phi-beta) / (cos(delta+omega).cos(omega-beta))])^2]``

    ``omega``: wall batter from vertical, using Coulomb's own sign
    convention -- POSITIVE omega tilts the wall face INTO the backfill
    (increases Ka: verified numerically, see the regression test) and
    NEGATIVE omega tilts it AWAY from the backfill (decreases Ka). A
    standard gravity wall's batter -- receding away from the retained soil
    as it rises, the shape every block series in this package's catalogue
    produces -- is therefore passed as a NEGATIVE omega; see how
    :mod:`.api` calls this function, and do not pass
    :attr:`~.blocks.BlockSeries.batter_deg` (always positive, a magnitude)
    in here unnegated.
    ``beta``: backslope, +ve rising away from the wall (same sign convention
    as ``cantilever_wall.pressure.rankine.Ka_rankine``).
    ``delta``: wall friction angle.

    Reduces exactly to :func:`~austruct.tools.cantilever_wall.pressure.rankine.Ka_rankine`
    at ``omega = delta = beta = 0`` -- see the regression test. It does NOT
    reduce to ``Ka_rankine(phi, beta)`` for beta != 0 even at omega = delta = 0;
    that is a genuine, already-documented divergence between the two
    theories' backslope treatments -- see ``cantilever_wall/divergence.py``.

    Raises
    ------
    ValueError
        If ``backslope_deg > phi_deg`` (as :func:`Ka_rankine` does), or if
        ``delta_deg + omega_deg >= 90`` (the back-face normal direction
        becomes undefined).
    """
    if beta_deg > phi_deg:
        raise ValueError(
            f"backslope ({beta_deg:.1f} deg) exceeds phi ({phi_deg:.1f} deg) "
            "-- Coulomb active pressure is undefined for a slope steeper "
            "than the soil's own friction angle"
        )
    if delta_deg + omega_deg >= 90.0:
        raise ValueError(
            f"delta ({delta_deg:.1f} deg) + omega ({omega_deg:.1f} deg) >= 90 deg "
            "-- the back-face normal direction is undefined"
        )
    phi = math.radians(phi_deg)
    omega = math.radians(omega_deg)
    beta = math.radians(beta_deg)
    delta = math.radians(delta_deg)

    cos_delta_omega = math.cos(delta + omega)
    cos_omega_beta = math.cos(omega - beta)
    inner = max(
        math.sin(phi + delta) * math.sin(phi - beta) / (cos_delta_omega * cos_omega_beta), 0.0
    )
    denominator = math.cos(omega) ** 2 * cos_delta_omega * (1.0 + math.sqrt(inner)) ** 2
    return math.cos(phi - omega) ** 2 / denominator


@dataclass(frozen=True)
class ThrustComponents:
    """Resultant earth-pressure thrust, decomposed for the stability ledger.

    [UNITS] forces kN/m, height m above the base.
    """

    horizontal: float
    vertical: float
    height: float


def active_thrust(H: float, resolved: ResolvedSoil, omega_deg: float) -> ThrustComponents:  # noqa: N803
    """Integrate the Coulomb active pressure diagram over the full wall height.

    ``omega_deg`` uses :func:`Ka_coulomb`'s sign convention, NOT
    :attr:`~.blocks.BlockSeries.batter_deg`'s -- callers passing a wall's
    physical (always-positive) batter must negate it. See :func:`Ka_coulomb`'s
    docstring.

    [ASSUMPTION] Cohesionless backfill -- even where ``resolved.cohesion``
                 is nonzero (e.g. a cohesive soil preset picked for the
                 backfill by mistake), no cohesion relief is applied here.
                 A modular gravity block wall is specified with free-draining
                 granular backfill; a cohesive fill behind one is itself a
                 design deviation this tool does not attempt to credit.
    [ASSUMPTION] No water table -- see the module docstring and
                 :class:`~.models.GravityWallInput`'s validator, which
                 rejects one outright rather than silently ignoring it.
    """
    phi = resolved.phi.value
    beta = resolved.backslope.value
    delta = resolved.delta.value
    gamma = resolved.gamma.value
    surcharge = resolved.surcharge.value

    Ka = Ka_coulomb(phi, omega_deg, beta, delta)
    direction = math.radians(delta + omega_deg)

    def intensity(z: float) -> float:
        return Ka * (gamma * z + surcharge)

    dz = H / N_SLICES
    P = 0.0
    first_moment_about_base = 0.0
    for i in range(N_SLICES):
        z0, z1 = i * dz, (i + 1) * dz
        i0, i1 = intensity(z0), intensity(z1)
        strip = 0.5 * (i0 + i1) * dz
        h0, h1 = H - z0, H - z1
        strip_height = (i0 * h0 + i1 * h1) / (i0 + i1) if (i0 + i1) > 0 else 0.5 * (h0 + h1)
        P += strip
        first_moment_about_base += strip * strip_height

    height = first_moment_about_base / P if P > 0 else H / 3.0

    return ThrustComponents(
        horizontal=P * math.cos(direction),
        vertical=P * math.sin(direction),
        height=height,
    )


def coulomb_report(H: float, resolved: ResolvedSoil, omega_deg: float) -> CalcResult:  # noqa: N803
    """The full readable working behind :func:`active_thrust`."""
    env = Envelope(name="Coulomb active pressure, battered wall face")
    env.add(
        "backslope <= phi", resolved.backslope.value, upper=resolved.phi.value, unit="deg",
        basis=CLAUSE_COULOMB,
    )
    env.add(
        "delta + omega < 90", resolved.delta.value + omega_deg, upper=89.9, unit="deg",
        basis=CLAUSE_COULOMB,
    )
    env.note("Homogeneous, cohesionless soil over the full height, no water table.")
    env.require()

    basis = Basis()
    basis.add(CLAUSE_COULOMB)

    result = CalcResult(
        name="Coulomb active earth pressure -- battered wall face",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input("H", Value(H, "m", "H", "Wall height"))
    result.add_input("omega", Value(omega_deg, "deg", "omega", "Wall batter from vertical"))
    result.add_input("phi", Value(resolved.phi.value, "deg", "phi", "Characteristic friction angle"))
    result.add_input("delta", Value(resolved.delta.value, "deg", "delta", "Wall friction angle"))
    result.add_input("backslope", Value(resolved.backslope.value, "deg", "beta", "Backslope"))
    result.add_input("gamma", Value(resolved.gamma.value, "kN/m^3", "gamma", "Unit weight"))
    result.add_input("surcharge", Value(resolved.surcharge.value, "kPa", "q", "Surcharge"))

    Ka = Ka_coulomb(resolved.phi.value, omega_deg, resolved.backslope.value, resolved.delta.value)
    result.add_intermediate("Ka", Value(Ka, "-", "Ka", "Active pressure coefficient"))

    thrust = active_thrust(H, resolved, omega_deg)
    result.add_output("Ph", Value(thrust.horizontal, "kN/m", "P_h", "Horizontal active thrust"))
    result.add_output(
        "Pv", Value(thrust.vertical, "kN/m", "P_v", "Vertical thrust component (acts downward)")
    )
    result.add_output("thrust_height", Value(thrust.height, "m", "h_P", "Height of P above the base"))

    if resolved.cohesion.value > 0:
        result.note(
            "Backfill cohesion is NOT credited -- this pressure calculation "
            "assumes a free-draining granular backfill regardless of the "
            "soil input's cohesion value."
        )
    result.note(
        "Resultant acts on the wall's back face at (delta + omega) from "
        "horizontal, per Coulomb's own convention -- see the module "
        "docstring for why this differs from rankine.py's backslope-parallel "
        "convention, and do not compare Ka values across the two modules "
        "except at delta = omega = beta = 0."
    )

    return result
