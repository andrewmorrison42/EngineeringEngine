"""Section moment capacity to AS 4100 Section 5.2, and the gate to Section 5.6.

Public entry points
-------------------
:func:`section_moment_capacity`
    ``M_s = f_y Z_e``, the capacity of the cross-section.
:func:`check_flexure`
    The same, checked against ``M*`` -- but ONLY for a segment that is fully
    restrained against lateral-torsional buckling.

The thing this module refuses to do
-----------------------------------
For reinforced concrete, the section capacity is essentially the answer. For
steel it is not. A steel beam almost always fails by lateral-torsional buckling
before it reaches ``M_s``, and for a long unrestrained span the member capacity
``M_b`` can be a fraction of it.

So :func:`check_flexure` requires the caller to state that the segment is fully
restrained, and refuses otherwise -- pointing at
:mod:`austruct.design.as4100.lateral_torsional`, which does the member check.
Returning ``M_s`` for an unrestrained beam would hand back a number that looks
like an answer, is three times too big, and carries no warning that a reviewer
would notice.

That is the same stance ``check_detailing`` takes when it has no anchorage
length, and it is for the same reason: the missing input is not a detail, it is
the governing one.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] This module is UNVERIFIED. Its constants are in ``constants.py``.
"""

from __future__ import annotations

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_MOMENT, U_NONE, U_STRESS, U_Z, kNm
from ...sections.steel_catalogue import CatalogueSection
from . import constants as C
from .classification import SectionSlenderness, classify

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Section moment capacity of steel members to AS 4100 Section 5.2",
    envelope_summary=(
        "Section capacity only -- lateral-torsional buckling is NOT included. "
        "Valid for a fully restrained segment; see lateral_torsional.py otherwise"
    ),
)


def _envelope(section: CatalogueSection) -> Envelope:
    env = Envelope(name="AS 4100 section moment capacity")
    env.note(
        "SECTION capacity only. A segment that is not fully restrained against "
        "lateral-torsional buckling has a lower MEMBER capacity, often much "
        "lower. See lateral_torsional.py."
    )
    env.note(
        "Bending about one principal axis. Biaxial bending needs the combined "
        "actions of Section 8."
    )
    env.note("No axial force. With axial load the moment capacity is reduced.")
    env.note("No torsion, and no web openings or notches.")
    _ = section
    return env


def section_moment_capacity(
    section: CatalogueSection,
    axis: str = "x",
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """``M_s = f_y Z_e`` -- the nominal section moment capacity.

    Parameters
    ----------
    section:
        The catalogue section.
    axis:
        ``"x"`` major or ``"y"`` minor.
    residual:
        ``"HR"`` or ``"HW"``.

    Returns
    -------
    CalcResult
        With ``Ms`` and ``phiMs`` as outputs. No checks -- this is a capacity,
        not a verification.

    Notes
    -----
    The yield stress used is the FLANGE value, because the flange is what
    carries the flexural stress at the extreme fibre. A section whose web is
    thinner has a higher web ``f_y``, and using it here would overstate the
    capacity.
    """
    result = CalcResult(
        name=name or f"Section moment capacity, AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(section),
        basis=Basis([C.CLAUSE_SECTION_SLENDERNESS, C.CLAUSE_ZE, C.CLAUSE_PHI]),
    )

    slenderness = classify(section, residual, axis)
    fy = section.fy_flange
    ms = fy * slenderness.Ze

    result.add_input("section", Value(0.0, U_NONE, section.designation, "Section"))
    result.add_input("axis", Value(0.0, U_NONE, axis, "Bending axis"))
    result.add_input("fy", Value(fy, U_STRESS, "f_y", "Flange yield stress"))

    result.add_intermediate(
        "compactness", Value(0.0, U_NONE, slenderness.compactness.value, "Section class")
    )
    result.add_intermediate("Z", Value(slenderness.Z, U_Z, "Z", "Elastic modulus"))
    result.add_intermediate("S", Value(slenderness.S, U_Z, "S", "Plastic modulus"))
    result.add_intermediate("Ze", Value(slenderness.Ze, U_Z, "Z_e", "Effective modulus"))
    result.add_intermediate("phi", Value(C.PHI, U_NONE, "phi", "Capacity reduction factor"))

    result.add_output("Ms", Value(ms, U_MOMENT, "M_s", "Section moment capacity", "kN.m", kNm))
    result.add_output(
        "phiMs", Value(C.PHI * ms, U_MOMENT, "phi.M_s", "Design section capacity", "kN.m", kNm)
    )

    result.note(
        f"Section is {slenderness.compactness.value}, governed by the "
        f"{slenderness.governing.name}."
    )
    result.note(
        f"f_y taken as the FLANGE value ({fy:.0f} MPa). The web is thinner and "
        f"therefore stronger ({section.fy_web:.0f} MPa); using the web value "
        "here would overstate the capacity."
    )
    result.note(
        "This is the SECTION capacity. It is the member capacity only where "
        "the segment is fully restrained against lateral-torsional buckling."
    )
    return result


def check_flexure(
    section: CatalogueSection,
    M_star: float,  # noqa: N803
    *,
    fully_restrained: bool = False,
    axis: str = "x",
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """Check ``M*`` against the section capacity -- restrained segments only.

    Parameters
    ----------
    section:
        The catalogue section.
    M_star:
        Design bending moment (N.mm).
    fully_restrained:
        The caller's statement that the compression flange is continuously
        restrained against lateral displacement AND twist, so that
        lateral-torsional buckling cannot occur. **Required**, and the function
        refuses without it.

        A concrete slab with shear studs is fully restrained. A purlin at
        1.5 m centres is not -- it restrains at points, and the segment between
        them still buckles.
    axis:
        Bending axis. Minor-axis bending cannot buckle laterally, so
        ``fully_restrained`` is not required for ``axis="y"``.

    Raises
    ------
    ModelError
        If ``fully_restrained`` is not stated for major-axis bending. This is
        deliberate: returning ``M_s`` for an unrestrained beam gives a number
        that can be several times the real capacity, and nothing downstream
        would flag it.
    """
    if axis == "x" and not fully_restrained:
        raise ModelError(
            "check_flexure computes the SECTION capacity, which is the member "
            "capacity only for a fully restrained segment. This beam has not "
            "been declared fully restrained.\n\n"
            "A steel beam almost always fails by lateral-torsional buckling "
            "before it reaches M_s, and for a long unrestrained span M_b can "
            "be a fraction of it -- so returning M_s here would hand back a "
            "number that looks like an answer and is not one.\n\n"
            "Either pass fully_restrained=True if the compression flange is "
            "continuously restrained against lateral movement AND twist, or "
            "use as4100.check_member_flexure(), which does the buckling check."
        )

    result = section_moment_capacity(section, axis, residual, name=name)
    phi_ms = result.get("phiMs")

    result.add_input(
        "M_star", Value(M_star, U_MOMENT, "M*", "Design moment", "kN.m", kNm)
    )
    result.add_check(
        Check(
            label="M* <= phi.M_s",
            actual=abs(M_star),
            limit=phi_ms,
            operator="<=",
            unit=U_MOMENT,
            display_factor=kNm,
            display_unit="kN.m",
            basis=C.CLAUSE_PHI,
        )
    )

    if axis == "x":
        result.note(
            "Checked as a FULLY RESTRAINED segment, on the caller's statement. "
            "If the compression flange can displace laterally or twist between "
            "restraints, this result does not apply."
        )
    else:
        result.note(
            "Minor-axis bending cannot buckle laterally, so the section "
            "capacity is the member capacity here."
        )
    return result


def required_section_modulus(
    M_star: float,  # noqa: N803
    fy: float,
) -> float:
    """``Z_e`` needed to carry ``M*`` (mm^3). For preliminary sizing.

    Assumes the section will turn out compact, which most rolled beams are.
    Confirm with :func:`~austruct.design.as4100.classification.classify` once a
    section is chosen -- a slender section needs more than this.
    """
    if fy <= 0:
        raise ModelError(f"f_y must be positive, got {fy}")
    return abs(M_star) / (C.PHI * fy)


def lightest_section(
    M_star: float,  # noqa: N803
    designations: tuple[str, ...],
    *,
    grade: str = "300",
    axis: str = "x",
    residual: str = C.DEFAULT_RESIDUAL,
) -> tuple[str, CalcResult] | None:
    """The lightest section from a list that carries ``M*``.

    Parameters
    ----------
    designations:
        Candidates, e.g. ``steel_catalogue.names("UB")``.

    Returns
    -------
    tuple or None
        ``(designation, result)`` for the lightest adequate section, or None if
        none of them work.

    Notes
    -----
    SECTION capacity only, so this is a sizing aid for a restrained beam and a
    starting point otherwise -- the buckling check will usually push the answer
    up a size or two.
    """
    from ...sections import steel_catalogue

    best: tuple[str, CalcResult] | None = None
    best_mass = float("inf")

    for designation in designations:
        candidate = steel_catalogue.get(designation, grade)
        capacity = section_moment_capacity(candidate, axis, residual)
        if capacity.get("phiMs") >= abs(M_star) and candidate.mass < best_mass:
            best = (designation, capacity)
            best_mass = candidate.mass

    return best


def slenderness_of(
    section: CatalogueSection, residual: str = C.DEFAULT_RESIDUAL, axis: str = "x"
) -> SectionSlenderness:
    """Convenience re-export so a caller needs one import for flexure work."""
    return classify(section, residual, axis)
