"""Bearing pressure -- Meyerhof effective width, Terzaghi/Meyerhof capacity.

``q* = V* / B'`` against ``phi_g . q_ult`` (or a direct geotechnical
override, treated as an already-design value -- see the parameter docs).

[VECTOR] UNVERIFIED. ``N_gamma`` in particular has several accepted forms in
         the literature (Meyerhof, Vesic, Hansen); the one used here is
         Meyerhof's approximation, not necessarily the office standard.
         Shape, depth and inclination factors are NOT applied -- a
         simplification, not an omission by oversight; see the module note.
"""

from __future__ import annotations

import math

from ....core.basis import AS4678_2002, Basis, ClauseRef
from ....core.contract import CalcResult, Check, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ..engine import DesignSoil, StabilityLedger
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
    description="Bearing pressure: Meyerhof effective width, Terzaghi/Meyerhof capacity",
    envelope_summary="e/B < 0.5 required -- B' must stay positive",
)

CLAUSE_BEARING = ClauseRef(AS4678_2002, note="Bearing pressure, effective width method")


def bearing_capacity_factors(phi_deg: float) -> tuple[float, float, float]:
    """(Nq, Nc, Ngamma) -- Terzaghi Nq/Nc, Meyerhof's Ngamma approximation.

    [BASIS] Classical bearing-capacity theory, not itself an AS 4678 clause.
    [VECTOR] Ngamma specifically: several accepted forms exist; confirm which
             one the office standard expects.
    """
    phi = math.radians(phi_deg)
    Nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.radians(45) + phi / 2.0) ** 2
    Nc = (Nq - 1.0) / math.tan(phi)
    Ngamma = (Nq - 1.0) * math.tan(1.4 * phi)
    return Nq, Nc, Ngamma


def check_bearing(
    wall: WallInput,
    design: DesignSoil,
    gamma_char: float,
    ledger: StabilityLedger,
    e: float,
) -> CalcResult:
    """Bearing check.

    Parameters
    ----------
    e:
        Eccentricity from :func:`~.eccentricity.check_eccentricity` --
        threaded in rather than recomputed, so the two checks can never
        silently disagree on it.

    [ASSUMPTION] Founding depth (for the Nq overburden term) taken as
                 ``base_thickness`` -- ground level at the toe assumed level
                 with the top of the footing, same as the sliding check's
                 passive embedment.
    """
    B = wall.geometry.base_length
    B_eff = B - 2.0 * abs(e)

    env = Envelope(name="Bearing pressure")
    env.add("B_eff", B_eff, lower=0.0, unit="m", basis=CLAUSE_BEARING,
            reason="Meyerhof effective width must stay positive")
    env.require()

    basis = Basis()
    basis.add(CLAUSE_BEARING)

    q_applied = ledger.V_star / B_eff

    if wall.bearing_capacity_override is not None:
        q_design = wall.bearing_capacity_override
        Nq = Nc = Ngamma = float("nan")
        q_ult = float("nan")
    else:
        embedment = wall.geometry.base_thickness
        Nq, Nc, Ngamma = bearing_capacity_factors(design.phi_deg)
        q_overburden = gamma_char * embedment
        q_ult = design.cohesion * Nc + q_overburden * Nq + 0.5 * gamma_char * B_eff * Ngamma
        q_design = ledger.factors.bearing.geotechnical_reduction * q_ult

    result = CalcResult(
        name="Bearing pressure -- AS 4678:2002",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input("Vstar", Value(ledger.V_star, "kN/m", "V*", "Design vertical force"))
    result.add_input("e", Value(e, "m", "e", "Eccentricity"))
    result.add_intermediate("B_eff", Value(B_eff, "m", "B'", "Meyerhof effective width"))
    result.add_output("q_applied", Value(q_applied, "kPa", "q*", "Applied bearing pressure"))

    if wall.bearing_capacity_override is not None:
        result.note(
            "bearing_capacity_override supplied -- treated as an already "
            "DESIGN (factored) value from a geotechnical report; the "
            "Terzaghi/Meyerhof estimate and phi_g below were not applied."
        )
    else:
        result.add_intermediate("Nq", Value(Nq, "-", "Nq", "Bearing capacity factor"))
        result.add_intermediate("Nc", Value(Nc, "-", "Nc", "Bearing capacity factor"))
        result.add_intermediate("Ngamma", Value(Ngamma, "-", "Ngamma", "Bearing capacity factor"))
        result.add_intermediate("q_ult", Value(q_ult, "kPa", "q_ult", "Ultimate bearing capacity"))

    result.add_output("q_design", Value(q_design, "kPa", "phi_g.q_ult", "Design bearing capacity"))

    result.add_check(
        Check(
            label="Bearing, q* <= phi_g.q_ult",
            actual=q_applied,
            limit=q_design,
            operator="<=",
            unit="kPa",
            basis=CLAUSE_BEARING,
        )
    )

    return result
