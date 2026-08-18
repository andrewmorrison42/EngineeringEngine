"""Overturning about the toe -- FS-based (allowable stress design).

``FS = SumMr / SumMo`` against
:data:`~austruct.tools.gravity_wall.factors.FS_OVERTURNING`. This tool
reports overturning as its own check (unlike ``cantilever_wall``, which
uses the middle-third eccentricity rule instead) because that is what the
source methodology names explicitly -- see :mod:`.models`'s module
docstring and the package README.
"""

from __future__ import annotations

from ....core.basis import NCMA_SRW_MANUAL, Basis, ClauseRef
from ....core.contract import CalcResult, Check, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ..engine import GravityLedger
from ..factors import FS_OVERTURNING

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Overturning about the toe, FS-based -- NCMA-style allowable stress design",
    envelope_summary="M_overturning > 0 required",
)

CLAUSE_OVERTURNING = ClauseRef(NCMA_SRW_MANUAL, note="Minimum FS 1.5 overturning")


def check_overturning(ledger: GravityLedger) -> CalcResult:
    env = Envelope(name="Overturning")
    env.add(
        "M_overturning", ledger.M_overturning, lower=0.0, unit="kN.m/m", basis=CLAUSE_OVERTURNING,
        reason="A zero or negative overturning moment makes FS undefined",
    )
    env.require()

    basis = Basis()
    basis.add(CLAUSE_OVERTURNING)

    Mr = ledger.M_resisting
    Mo = ledger.M_overturning
    FS = Mr / Mo

    result = CalcResult(
        name="Overturning about the toe, FS-based -- NCMA-style ASD",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input("Mr", Value(Mr, "kN.m/m", "SumMr", "Characteristic resisting moment"))
    result.add_input("Mo", Value(Mo, "kN.m/m", "SumMo", "Characteristic overturning moment"))
    result.add_output("FS", Value(FS, "-", "FS", "Factor of safety against overturning"))

    result.add_check(
        Check(
            label="Overturning, FS >= 1.5",
            actual=FS,
            limit=FS_OVERTURNING,
            operator=">=",
            unit="-",
            basis=CLAUSE_OVERTURNING,
        )
    )

    return result
