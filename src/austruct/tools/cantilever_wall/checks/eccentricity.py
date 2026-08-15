"""Eccentricity of the base resultant -- ``e = B/2 - (SumMr - SumMo)/SumV``.

Reported as ``e/B`` against ``max_e_over_b`` from the factor set (B/6, the
classic middle-third rule, for AS 4678 Class B by default). Governs where the
resultant runs close to the edge of the base -- which is also the input
:mod:`.bearing` needs for the Meyerhof effective width.
"""

from __future__ import annotations

from ....core.basis import AS4678_2002, Basis, ClauseRef
from ....core.contract import CalcResult, Check, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ..engine import StabilityLedger
from ..models import WallInput

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Eccentricity of the base resultant, AS 4678:2002",
    envelope_summary="V* > 0 required -- a net uplift makes eccentricity undefined",
)

CLAUSE_ECCENTRICITY = ClauseRef(AS4678_2002, note="Eccentricity / middle-third rule")


def check_eccentricity(wall: WallInput, ledger: StabilityLedger) -> CalcResult:
    env = Envelope(name="Eccentricity")
    env.add("V*", ledger.V_star, lower=0.0, unit="kN/m", basis=CLAUSE_ECCENTRICITY)
    env.require()

    basis = Basis()
    basis.add(CLAUSE_ECCENTRICITY)

    B = wall.geometry.base_length
    x_bar = (ledger.M_resisting_star - ledger.M_overturning_star) / ledger.V_star
    e = B / 2.0 - x_bar
    e_over_b = abs(e) / B
    limit = ledger.factors.eccentricity.max_e_over_b

    result = CalcResult(
        name="Eccentricity of the base resultant -- AS 4678:2002",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input(
        "Mr", Value(ledger.M_resisting_star, "kN.m/m", "SumMr*", "Design resisting moment")
    )
    result.add_input(
        "Mo", Value(ledger.M_overturning_star, "kN.m/m", "SumMo*", "Design overturning moment")
    )
    result.add_input("Vstar", Value(ledger.V_star, "kN/m", "V*", "Design vertical force"))
    result.add_intermediate("x_bar", Value(x_bar, "m", "x_bar", "Resultant location from the toe"))
    result.add_output("e", Value(e, "m", "e", "Eccentricity from the base centreline"))
    result.add_output("e_over_b", Value(e_over_b, "-", "e/B", "Eccentricity ratio"))

    result.add_check(
        Check(
            label="Eccentricity, e/B <= limit",
            actual=e_over_b,
            limit=limit,
            operator="<=",
            unit="-",
            basis=CLAUSE_ECCENTRICITY,
        )
    )

    if e < 0:
        result.note(
            "Resultant falls toward the heel side of centre (e < 0) -- unusual "
            "for a retaining wall and worth a second look at the backslope/"
            "surcharge inputs rather than treating this as automatically safe."
        )

    return result
