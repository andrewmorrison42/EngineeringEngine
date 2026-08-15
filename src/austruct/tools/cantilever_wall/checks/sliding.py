"""Sliding resistance -- friction, adhesion and passive, AS 4678:2002.

``utilisation``, not pass/fail, per :class:`~austruct.core.contract.Check` --
this is what lets a caller rank checks and find the governing one for free.

[VECTOR] UNVERIFIED. The compounding of ``sliding.friction_reduction`` on top
         of the already-factored ``phi_design`` (rather than an alternative
         scheme, e.g. applying it only to passive) is a documented choice,
         not a transcribed clause -- confirm against AS 4678 Table 8.3.
"""

from __future__ import annotations

import math

from ....core.basis import AS4678_2002, Basis, ClauseRef
from ....core.contract import CalcResult, Check, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ..engine import DesignSoil, StabilityLedger, base_friction_angle
from ..models import WallInput
from ..pressure.rankine import Kp_rankine

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Sliding resistance: friction, adhesion, passive -- AS 4678:2002",
    envelope_summary="Homogeneous soil, Rankine passive (no wall friction credit)",
)

CLAUSE_SLIDING = ClauseRef(AS4678_2002, table="8.3", note="Sliding resistance")


def check_sliding(
    wall: WallInput,
    design: DesignSoil,
    gamma_char: float,
    ledger: StabilityLedger,
    passive_neglect_depth: float,
) -> CalcResult:
    """Sliding check: design driving force vs design sliding resistance.

    Passive resistance uses the toe embedment = ``base_thickness``
    [ASSUMPTION: ground level at the toe is level with the top of the
    footing -- override by adjusting ``geometry`` if not], less
    ``passive_neglect_depth`` (ON by default -- see :mod:`.models`).
    """
    env = Envelope(name="Sliding resistance")
    env.note("Rankine passive (no wall friction credit) -- see Kp_rankine.")
    env.require()

    basis = Basis()
    basis.add(CLAUSE_SLIDING)

    geometry = wall.geometry
    embedment = geometry.base_thickness
    Kp = Kp_rankine(design.phi_deg)
    net_embedment = max(embedment - passive_neglect_depth, 0.0)
    # Passive resistance is the integral of Kp.gamma.z from the
    # passive-neglect depth down to the full toe embedment:
    #   0.5.Kp.gamma.(embedment^2 - passive_neglect_depth^2)
    passive = 0.0
    if net_embedment > 0:
        passive = 0.5 * Kp * gamma_char * (embedment**2 - passive_neglect_depth**2)

    phi_base_deg = base_friction_angle(wall, design)
    friction = ledger.V_star * math.tan(math.radians(phi_base_deg))
    adhesion = design.cohesion * geometry.base_length

    factors = ledger.factors
    R_star = factors.sliding.friction_reduction * (friction + adhesion + passive)
    H_star = ledger.H_star

    result = CalcResult(
        name="Sliding resistance -- AS 4678:2002",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input("Vstar", Value(ledger.V_star, "kN/m", "V*", "Design vertical force"))
    result.add_input("Hstar", Value(H_star, "kN/m", "H*", "Design driving force"))
    result.add_intermediate(
        "phi_base", Value(phi_base_deg, "deg", "phi_base", f"Base friction ({wall.construction})")
    )
    result.add_intermediate("Kp", Value(Kp, "-", "Kp", "Rankine passive coefficient"))
    result.add_intermediate(
        "net_embedment",
        Value(net_embedment, "m", "d_p", "Embedment beyond the passive-neglect depth"),
    )
    result.add_intermediate("friction", Value(friction, "kN/m", "V*.tan(phi_base)", "Friction"))
    result.add_intermediate("adhesion", Value(adhesion, "kN/m", "c.B", "Base adhesion"))
    result.add_intermediate("passive", Value(passive, "kN/m", "P_p", "Passive resistance"))
    result.add_output("Rstar", Value(R_star, "kN/m", "R*", "Design sliding resistance"))

    result.add_check(
        Check(
            label="Sliding, H* <= R*",
            actual=H_star,
            limit=R_star,
            operator="<=",
            unit="kN/m",
            basis=CLAUSE_SLIDING,
        )
    )

    if passive_neglect_depth >= embedment:
        result.note(
            f"passive_neglect_depth ({passive_neglect_depth:.2f} m) >= toe "
            f"embedment ({embedment:.2f} m) -- passive resistance is zero. "
            "This is the services-trenching-removes-the-toe-cover case the "
            "default is deliberately conservative about."
        )
    if design.cohesion > 0:
        result.note(
            "Full cohesion credited as base adhesion -- some offices limit "
            "adhesion credit below full cohesion; not applied here."
        )

    return result
