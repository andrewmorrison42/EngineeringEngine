"""Bearing pressure -- Meyerhof effective width, FS-based (allowable stress
design).

``FS = q_ult / q_applied`` against
:data:`~austruct.tools.gravity_wall.factors.FS_BEARING`. Reuses
``cantilever_wall.checks.bearing.bearing_capacity_factors`` directly --
Terzaghi/Meyerhof bearing capacity theory is not specific to either wall
type, only the check built on top of it (here: FS against the ultimate
capacity directly, characteristic soil throughout; there: a design capacity
after AS 4678's ``phi_g`` reduction) differs.

[VECTOR] UNVERIFIED -- see ``cantilever_wall.checks.bearing``'s module note,
         which applies unchanged here.
"""

from __future__ import annotations

from ....core.basis import NCMA_SRW_MANUAL, Basis, ClauseRef
from ....core.contract import CalcResult, Check, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ...cantilever_wall.checks.bearing import bearing_capacity_factors
from ...cantilever_wall.models import ResolvedSoil
from ..engine import GravityLedger, eccentricity
from ..factors import FS_BEARING
from ..models import GravityWallInput

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Bearing pressure, FS-based -- NCMA-style allowable stress design",
    envelope_summary="e/B < 0.5 required -- B' must stay positive",
)

CLAUSE_BEARING = ClauseRef(NCMA_SRW_MANUAL, note="Minimum FS 2.0 bearing capacity")


def check_bearing(wall: GravityWallInput, resolved: ResolvedSoil, ledger: GravityLedger) -> CalcResult:
    """Bearing check.

    [ASSUMPTION] Founding depth for the Nq overburden term taken as
                 ``geometry.embedment`` -- see :class:`~.models.GravityWallGeometry`.
    """
    e = eccentricity(ledger)
    B = ledger.base_width
    B_eff = B - 2.0 * abs(e)

    env = Envelope(name="Bearing pressure")
    env.add(
        "B_eff", B_eff, lower=0.0, unit="m", basis=CLAUSE_BEARING,
        reason="Meyerhof effective width must stay positive",
    )
    env.require()

    basis = Basis()
    basis.add(CLAUSE_BEARING)

    q_applied = ledger.V / B_eff
    embedment = wall.geometry.embedment
    gamma_char = resolved.gamma.value

    if wall.bearing_capacity_override is not None:
        q_ult = wall.bearing_capacity_override
        Nq = Nc = Ngamma = float("nan")
    else:
        Nq, Nc, Ngamma = bearing_capacity_factors(resolved.phi.value)
        q_overburden = gamma_char * embedment
        q_ult = resolved.cohesion.value * Nc + q_overburden * Nq + 0.5 * gamma_char * B_eff * Ngamma

    FS = q_ult / q_applied if q_applied > 0 else float("inf")

    result = CalcResult(
        name="Bearing pressure, FS-based -- NCMA-style ASD",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input("V", Value(ledger.V, "kN/m", "V", "Characteristic vertical force"))
    result.add_input("e", Value(e, "m", "e", "Eccentricity"))
    result.add_intermediate("B_eff", Value(B_eff, "m", "B'", "Meyerhof effective width"))
    result.add_output("q_applied", Value(q_applied, "kPa", "q", "Applied bearing pressure"))

    if wall.bearing_capacity_override is not None:
        result.note(
            "bearing_capacity_override supplied -- treated as an ultimate "
            "capacity from a geotechnical report; the Terzaghi/Meyerhof "
            "estimate was not applied."
        )
    else:
        result.add_intermediate("Nq", Value(Nq, "-", "Nq", "Bearing capacity factor"))
        result.add_intermediate("Nc", Value(Nc, "-", "Nc", "Bearing capacity factor"))
        result.add_intermediate("Ngamma", Value(Ngamma, "-", "Ngamma", "Bearing capacity factor"))

    result.add_output("q_ult", Value(q_ult, "kPa", "q_ult", "Ultimate bearing capacity"))
    result.add_output("FS", Value(FS, "-", "FS", "Factor of safety against bearing failure"))

    result.add_check(
        Check(
            label="Bearing, FS >= 2.0",
            actual=FS,
            limit=FS_BEARING,
            operator=">=",
            unit="-",
            basis=CLAUSE_BEARING,
        )
    )

    return result
