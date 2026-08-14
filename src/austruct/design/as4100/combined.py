"""Combined bending and axial force, AS 4100 Section 8.

Why a member with both is not two checks
----------------------------------------
An axial force uses up capacity the section would otherwise have for bending,
and vice versa. Checking each alone and finding both under 100% proves nothing:
a member at 70% in bending and 70% in compression is not at 70%, it has failed.

AS 4100 handles this at two levels, and both are needed:

**Section** (Cl 8.3) -- the cross-section's reduced moment capacity in the
presence of axial force. A local check, at the section where the actions peak.

**Member** (Cl 8.4) -- the whole member, where the axial force also amplifies
the deflection and therefore the moment. This is where slenderness re-enters,
and it is usually the one that governs.

The 1.18 that surprises people
------------------------------
The reduced section moment capacity is::

    M_r = 1.18 M_s (1 - N*/(phi N_s))   <=  M_s

At zero axial force that gives ``1.18 M_s``, capped back to ``M_s``. The effect
is that a small axial force costs nothing at all -- up to about 15% of the
squash load, the cap is still biting and the moment capacity is untouched. The
cap is not a detail; without it the expression would hand out 18% more capacity
than the section has.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] This module is UNVERIFIED. The 1.18 and the member interaction form
         are the values to check first.
"""

from __future__ import annotations

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_FORCE, U_MOMENT, U_NONE, kN, kNm
from ...sections.steel_catalogue import CatalogueSection
from . import constants as C
from .compression import member_compression_capacity, section_compression_capacity
from .flexure import section_moment_capacity
from .lateral_torsional import member_moment_capacity
from .restraints import Segment

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Combined bending and axial force to AS 4100 Section 8",
    envelope_summary=(
        "Uniaxial bending with axial compression; doubly symmetric sections; "
        "no biaxial bending, no tension"
    ),
)


def _envelope() -> Envelope:
    env = Envelope(name="AS 4100 combined actions")
    env.note(
        "COMPRESSION with uniaxial bending. Axial TENSION with bending uses a "
        "different interaction and is not implemented."
    )
    env.note(
        "Biaxial bending is not implemented. A member bent about both axes at "
        "once needs the full Cl 8.4.5 interaction."
    )
    env.note("Doubly symmetric sections.")
    return env


def reduced_section_moment_capacity(
    Ms: float,  # noqa: N803
    N_star: float,  # noqa: N803
    phi_Ns: float,  # noqa: N803
) -> float:
    """``M_r = 1.18 M_s (1 - N*/(phi N_s)) <= M_s``.

    The cap is what makes this sensible: at low axial force the 1.18 has not
    been eaten away yet, so the moment capacity is simply ``M_s`` and the axial
    force costs nothing. It starts to bite at about 15% of the squash load.
    """
    if phi_Ns <= 0:
        raise ModelError(f"phi.N_s must be positive, got {phi_Ns}")
    reduced = C.COMBINED_REDUCED_MOMENT_FACTOR * Ms * (1.0 - abs(N_star) / phi_Ns)
    return max(0.0, min(Ms, reduced))


def check_combined_section(
    section: CatalogueSection,
    N_star: float,  # noqa: N803
    M_star: float,  # noqa: N803
    *,
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """Section capacity under combined compression and bending, Cl 8.3.

    A LOCAL check at the section where the actions peak. It does not consider
    the member's slenderness at all -- see :func:`check_combined_member`.
    """
    result = CalcResult(
        name=name or f"Combined actions (section), AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(),
        basis=Basis([C.CLAUSE_COMBINED_SECTION, C.CLAUSE_PHI]),
    )

    ms = section_moment_capacity(section, "x", residual).get("Ms")
    ns = section_compression_capacity(section, residual).get("Ns")
    phi_ns = C.PHI * ns
    mr = reduced_section_moment_capacity(ms, N_star, phi_ns)

    result.add_input("N_star", Value(N_star, U_FORCE, "N*", "Design axial", "kN", kN))
    result.add_input("M_star", Value(M_star, U_MOMENT, "M*", "Design moment", "kN.m", kNm))
    result.add_intermediate("Ns", Value(ns, U_FORCE, "N_s", "Section axial capacity", "kN", kN))
    result.add_intermediate(
        "Ms", Value(ms, U_MOMENT, "M_s", "Section moment capacity", "kN.m", kNm)
    )
    result.add_intermediate(
        "N_ratio", Value(abs(N_star) / phi_ns, U_NONE, "N*/phi.N_s", "Axial utilisation")
    )
    result.add_output(
        "Mr", Value(mr, U_MOMENT, "M_r", "Reduced moment capacity", "kN.m", kNm)
    )

    result.add_check(
        Check(
            label="N* <= phi.N_s",
            actual=abs(N_star),
            limit=phi_ns,
            operator="<=",
            unit=U_FORCE,
            display_factor=kN,
            display_unit="kN",
            basis=C.CLAUSE_SECTION_COMPRESSION,
        )
    )
    result.add_check(
        Check(
            label="M* <= phi.M_r  (reduced for axial force)",
            actual=abs(M_star),
            limit=C.PHI * mr,
            operator="<=",
            unit=U_MOMENT,
            display_factor=kNm,
            display_unit="kN.m",
            basis=C.CLAUSE_COMBINED_SECTION,
        )
    )

    if mr >= ms * (1 - 1e-9):
        result.note(
            f"N* is {abs(N_star) / phi_ns:.0%} of phi.N_s, which is low enough "
            "that the 1.18 factor is still capped at M_s -- the axial force "
            "costs no moment capacity at all."
        )
    else:
        result.note(
            f"The axial force has reduced the moment capacity to "
            f"{mr / ms:.0%} of M_s."
        )
    result.note(
        "SECTION check only. The member's slenderness amplifies the moment as "
        "well, which check_combined_member() covers and this does not."
    )
    return result


def check_combined_member(
    section: CatalogueSection,
    N_star: float,  # noqa: N803
    M_star: float,  # noqa: N803
    seg: Segment,
    le_compression: float,
    *,
    alpha_m: float = 1.0,
    alpha_b: float = C.ALPHA_B_DEFAULT,
    axis: str = "y",
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """Member capacity under combined compression and bending, Cl 8.4.

    The linear interaction::

        N*/(phi N_c) + M*/(phi M_b)  <=  1.0

    Parameters
    ----------
    seg:
        The segment, for the bending side -- lateral-torsional buckling.
    le_compression:
        Effective length for column buckling (mm). SEPARATE from the segment
        length, because the bracing that restrains a beam against
        lateral-torsional buckling is often not the same as the bracing that
        holds a column. Conflating them is a common and unconservative
        shortcut, which is why they are two arguments.

    Notes
    -----
    The linear form is the conservative one AS 4100 always permits. The
    standard also offers a less conservative expression for members meeting
    certain conditions; that is not implemented, so this may be pessimistic for
    a compact, well-restrained member.
    """
    result = CalcResult(
        name=name or f"Combined actions (member), AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(),
        basis=Basis([C.CLAUSE_COMBINED_MEMBER, C.CLAUSE_PHI]),
    )

    bending = member_moment_capacity(section, seg, alpha_m=alpha_m, residual=residual)
    compression = member_compression_capacity(
        section, le_compression, axis=axis, alpha_b=alpha_b, residual=residual
    )
    phi_mb = bending.get("phiMb")
    phi_nc = compression.get("phiNc")

    ratio = abs(N_star) / phi_nc + abs(M_star) / phi_mb

    result.add_input("N_star", Value(N_star, U_FORCE, "N*", "Design axial", "kN", kN))
    result.add_input("M_star", Value(M_star, U_MOMENT, "M*", "Design moment", "kN.m", kNm))
    result.add_input(
        "le_compression",
        Value(le_compression, U_NONE, "l_e,c", "Effective length, compression"),
    )
    result.add_intermediate(
        "phiNc", Value(phi_nc, U_FORCE, "phi.N_c", "Member axial capacity", "kN", kN)
    )
    result.add_intermediate(
        "phiMb", Value(phi_mb, U_MOMENT, "phi.M_b", "Member moment capacity", "kN.m", kNm)
    )
    result.add_output(
        "interaction", Value(ratio, U_NONE, "N*/phiN_c + M*/phiM_b", "Interaction")
    )

    result.add_check(
        Check(
            label="N*/(phi.N_c) + M*/(phi.M_b) <= 1.0",
            actual=ratio,
            limit=1.0,
            operator="<=",
            unit=U_NONE,
            basis=C.CLAUSE_COMBINED_MEMBER,
        )
    )

    result.note(
        f"Axial contributes {abs(N_star) / phi_nc:.2f} and bending "
        f"{abs(M_star) / phi_mb:.2f} to an interaction of {ratio:.2f}."
    )
    result.note(
        "The bending effective length and the compression effective length are "
        "SEPARATE inputs. Bracing that restrains a beam against "
        "lateral-torsional buckling is often not the bracing that holds a "
        "column, and conflating them is unconservative."
    )
    result.note(
        "Linear interaction -- the conservative form AS 4100 always permits. "
        "The alternative expressions for members meeting certain conditions "
        "are not implemented, so this may be pessimistic."
    )
    return result
