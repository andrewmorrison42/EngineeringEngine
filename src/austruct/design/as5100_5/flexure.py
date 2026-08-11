"""Flexural design of reinforced concrete sections to AS 5100.5:2017.

Relationship to the AS 3600 module
----------------------------------
The MECHANICS are identical and are shared: both standards use the same
rectangular stress block and the same plane-sections assumption, so both call
:func:`austruct.design.rc_common.strain_compat.solve_flexural_state`.

What differs, and what this module therefore owns:

- the capacity reduction factor -- AS 5100.5:2017 uses a single value for
  flexure rather than the ``k_uo``-dependent expression of AS 3600:2018;
- the ductility limit on ``k_uo``;
- the minimum-strength provision and its clause reference.

If you find yourself copying code from ``as3600/flexure.py`` into here, the
shared part belongs in ``rc_common`` instead.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] UNVERIFIED. See ``constants.py`` -- several values there are flagged
         UNCONFIRMED, not merely unchecked.
"""

from __future__ import annotations

from ...core.basis import Basis, ClauseRef
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.provenance import ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import (
    U_AREA,
    U_LENGTH,
    U_MOMENT,
    U_NONE,
    U_STRESS,
    kNm,
)
from ...materials.concrete import FC_MAX_AS5100, FC_MIN_AS5100
from ...sections.properties import cracking_moment
from ...sections.rc_section import RCSection
from ..rc_common.strain_compat import solve_flexural_state
from . import constants as C

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Ultimate flexural capacity of RC sections to AS 5100.5:2017",
    envelope_summary=(
        "25 <= f'c <= 100 MPa; non-prestressed; pure bending; "
        "compression at the top of the section as supplied"
    ),
)


def moment_capacity(
    section: RCSection,
    deduct_displaced_concrete: bool = True,
) -> CalcResult:
    """Ultimate flexural capacity of an RC section to AS 5100.5:2017.

    Basis
    -----
    AS 5100.5:2017 Section 8.1 (strength in bending), Table 2.3.2 (capacity
    reduction factors), with the stress block and plane-sections idealisations
    shared with AS 3600.

    Envelope
    --------
    25 MPa <= f'c <= 100 MPa (AS 5100.5 minimum grade -- UNCONFIRMED, see
    ``materials.concrete.FC_MIN_AS5100``). Non-prestressed. Pure bending.

    Parameters
    ----------
    section:
        The RC section to assess.
    deduct_displaced_concrete:
        Whether to deduct the concrete displaced by compression reinforcement.

    Returns
    -------
    CalcResult
        ``outputs["Muo"]``, ``outputs["phiMuo"]``, ``outputs["phi"]``.
        Checks: ductility on ``k_uo``, minimum strength.
    """
    env = Envelope(name="AS 5100.5 flexure")
    env.add(
        "f'c",
        section.concrete.fc,
        lower=FC_MIN_AS5100,
        upper=FC_MAX_AS5100,
        unit=U_STRESS,
        basis=ClauseRef(C.STANDARD, "1.1", note="Range of application"),
    )
    env.note("Non-prestressed reinforced concrete only. No axial force.")
    env.note(
        "Sagging bending with the compression face at the top of the section "
        "as supplied. Model hogging by inverting the section."
    )
    env.note(
        "AS 5100.5 restricts the use of Class L reinforcement in bridgeworks. "
        "That restriction is NOT enforced by this module -- check it separately."
    )
    env.extend(section.concrete.envelope)
    env.require()

    basis = Basis()
    basis.add(C.CLAUSE_FLEXURE)
    basis.add(C.CLAUSE_STRESS_BLOCK)

    state = solve_flexural_state(
        section, deduct_displaced_concrete=deduct_displaced_concrete
    )

    result = CalcResult(
        name="Ultimate moment capacity -- AS 5100.5:2017 Cl 8.1",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )

    result.add_input("fc", Value(section.concrete.fc, U_STRESS, "f'c", "Concrete strength"))
    result.add_input("D", Value(section.geometry.D, U_LENGTH, "D", "Overall depth"))
    result.add_input("b", Value(section.geometry.b_top, U_LENGTH, "b", "Compression face width"))
    for i, layer in enumerate(sorted(section.layers, key=lambda x: x.depth), start=1):
        result.add_input(
            f"layer{i}",
            Value(layer.area, U_AREA, f"A_s{i}",
                  f"{layer.designation} at d = {layer.depth:.0f} mm"),
        )

    result.add_intermediate(
        "alpha2", Value(section.concrete.alpha2, U_NONE, "alpha_2", "Stress block intensity")
    )
    result.add_intermediate(
        "gamma", Value(section.concrete.gamma, U_NONE, "gamma", "Stress block depth ratio")
    )
    result.add_intermediate("dn", Value(state.dn, U_LENGTH, "d_n", "Neutral axis depth"))
    result.add_intermediate("d", Value(state.d, U_LENGTH, "d", "Effective depth"))
    result.add_intermediate(
        "do", Value(state.d_o, U_LENGTH, "d_o", "Depth to outermost tensile layer")
    )
    result.add_intermediate("ku", Value(state.ku, U_NONE, "k_u", "d_n / d"))
    result.add_intermediate("kuo", Value(state.kuo, U_NONE, "k_uo", "d_n / d_o"))
    result.add_intermediate("z", Value(state.lever_arm, U_LENGTH, "z", "Lever arm"))
    result.add_intermediate("Ast", Value(state.Ast, U_AREA, "A_st", "Tensile steel area"))

    # -- capacity reduction factor -------------------------------------------
    # [BASIS] AS 5100.5:2017 Table 2.3.2. Unlike AS 3600:2018 this is a single
    #         value, not a function of k_uo. That difference is the reason this
    #         module exists rather than parameterising the AS 3600 one.
    basis.add(C.CLAUSE_PHI)
    phi = C.PHI_FLEXURE
    result.add_output("phi", Value(phi, U_NONE, "phi", "Capacity reduction factor, bending"))

    result.add_output(
        "Muo", Value(state.Muo, U_MOMENT, "M_uo", "Nominal moment capacity", "kN.m", kNm)
    )
    result.add_output(
        "phiMuo",
        Value(phi * state.Muo, U_MOMENT, "phi.M_uo", "Design moment capacity", "kN.m", kNm),
    )

    basis.add(C.CLAUSE_DUCTILITY)
    result.add_check(
        Check(
            label="Ductility, k_uo",
            actual=state.kuo,
            limit=C.KUO_LIMIT,
            operator="<=",
            unit=U_NONE,
            basis=C.CLAUSE_DUCTILITY,
        )
    )

    basis.add(C.CLAUSE_MIN_STEEL)
    try:
        mcr = cracking_moment(section)
        result.add_intermediate(
            "Mcr", Value(mcr, U_MOMENT, "M_cr", "Cracking moment", "kN.m", kNm)
        )
        result.add_check(
            Check(
                label="Minimum strength, M_uo >= 1.2 M_cr",
                actual=state.Muo,
                limit=C.MIN_STRENGTH_FACTOR * mcr,
                operator=">=",
                unit=U_MOMENT,
                basis=C.CLAUSE_MIN_STEEL,
                display_factor=kNm,
                display_unit="kN.m",
            )
        )
    except Exception as exc:  # pragma: no cover -- defensive
        result.note(f"Minimum strength check not performed: {exc}")

    for note in state.notes:
        result.note(note)

    return result


def check_flexure(
    section: RCSection,
    M_star: float,  # noqa: N803
    deduct_displaced_concrete: bool = True,
) -> CalcResult:
    """Check flexural capacity against a design moment, to AS 5100.5:2017.

    Parameters
    ----------
    M_star:
        Design bending moment (N.mm), magnitude.

    Returns
    -------
    CalcResult
    """
    result = moment_capacity(section, deduct_displaced_concrete)
    result.name = "Flexural strength check -- AS 5100.5:2017 Cl 8.1"

    result.add_input(
        "Mstar", Value(abs(M_star), U_MOMENT, "M*", "Design bending moment", "kN.m", kNm)
    )
    result.add_check(
        Check(
            label="Flexural strength, M* <= phi.M_uo",
            actual=abs(M_star),
            limit=result.get("phiMuo"),
            operator="<=",
            unit=U_MOMENT,
            basis=ClauseRef(C.STANDARD, "2.3", note="Strength requirement"),
            display_factor=kNm,
            display_unit="kN.m",
        )
    )
    return result
