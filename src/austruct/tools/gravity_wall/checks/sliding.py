"""Sliding resistance -- friction only, FS-based (allowable stress design).

``FS = R / H`` against :data:`~austruct.tools.gravity_wall.factors.FS_SLIDING`,
reported via ``operator=">="`` so :class:`~austruct.core.contract.Check`'s
utilisation still reads ">1.0 = FAIL" the same way every other check in this
toolkit does, even though the underlying quantity here is a factor of
safety, not a demand/capacity ratio.

[VECTOR] UNVERIFIED. No passive resistance credit is taken at all -- see
         the module note.
"""

from __future__ import annotations

import math

from ....core.basis import NCMA_SRW_MANUAL, Basis, ClauseRef
from ....core.contract import CalcResult, Check, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ...cantilever_wall.models import ResolvedSoil
from ..engine import GravityLedger, base_friction_angle
from ..factors import FS_SLIDING
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
    description="Sliding resistance, FS-based -- NCMA-style allowable stress design",
    envelope_summary="No passive resistance credited",
)

CLAUSE_SLIDING = ClauseRef(NCMA_SRW_MANUAL, note="Minimum FS 1.5 sliding")


def check_sliding(wall: GravityWallInput, resolved: ResolvedSoil, ledger: GravityLedger) -> CalcResult:
    """Sliding check: characteristic resistance vs characteristic driving force.

    [ASSUMPTION] No passive resistance in front of the base course --
                 deliberate, not an oversight: a modular block wall's toe is
                 rarely a formed key the way a cantilever footing's is, and
                 crediting passive resistance from disturbed, often
                 shallow-embedment fill in front of the wall is a common
                 source of overconfidence in these systems. Revisit if the
                 design includes a genuine embedded shear-key detail.
    """
    env = Envelope(name="Sliding resistance")
    env.note("No passive resistance credited -- see the module note.")
    env.require()

    basis = Basis()
    basis.add(CLAUSE_SLIDING)

    phi_base_deg = base_friction_angle(wall, resolved)
    friction = ledger.V * math.tan(math.radians(phi_base_deg))
    R = friction
    H = ledger.thrust.horizontal
    FS = R / H if H > 0 else float("inf")

    result = CalcResult(
        name="Sliding resistance, FS-based -- NCMA-style ASD",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input("V", Value(ledger.V, "kN/m", "V", "Characteristic vertical force"))
    result.add_input("H", Value(H, "kN/m", "H", "Characteristic driving force"))
    result.add_intermediate(
        "phi_base", Value(phi_base_deg, "deg", "phi_base", "Base-to-foundation friction angle")
    )
    result.add_intermediate("friction", Value(friction, "kN/m", "V.tan(phi_base)", "Friction resistance"))
    result.add_output("R", Value(R, "kN/m", "R", "Characteristic sliding resistance"))
    result.add_output("FS", Value(FS, "-", "FS", "Factor of safety against sliding"))

    result.add_check(
        Check(
            label="Sliding, FS >= 1.5",
            actual=FS,
            limit=FS_SLIDING,
            operator=">=",
            unit="-",
            basis=CLAUSE_SLIDING,
        )
    )

    return result
