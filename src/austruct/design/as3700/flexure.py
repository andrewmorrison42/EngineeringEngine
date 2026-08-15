"""Flexural design of masonry walls to AS 3700:2018 -- one-way strip only.

Scope, and what this deliberately is not
-----------------------------------------
Every function here treats the wall as a ONE-WAY SPANNING STRIP (like a
one-way slab), exactly as :class:`~austruct.sections.masonry_section.MasonryWallSection`
is built. This covers the common preliminary-design case -- a wall spanning
vertically between floor and roof, or horizontally between piers -- but it is
NOT AS 3700's full Cl 7.4.3 panel/yield-line method, which computes a
higher, support-condition- and aspect-ratio-dependent capacity for two-way
panel action. Treating a two-way panel as a one-way strip is conservative,
not wrong, but it leaves capacity on the table; do not read a FAIL from this
module as proof a two-way panel actually fails without checking the panel
method by hand.

Three distinct mechanisms, three distinct results
--------------------------------------------------
- **Vertical bending** (:func:`vertical_bending_capacity`) -- tension
  perpendicular to the bed joints, the weak direction. Vertical compression
  (``fd``, e.g. from self-weight of wall above) is credited toward the
  cracking capacity, capped at :data:`~.constants.FD_MAX_ENHANCEMENT_RATIO`.
- **Horizontal bending** (:func:`horizontal_bending_capacity`) -- tension
  parallel to the bed joints, using the ``f'mt,parallel`` enhancement on
  :class:`~austruct.materials.masonry.MasonryGrade` -- itself a documented
  simplification, see that module.
- **Reinforced** (:func:`reinforced_moment_capacity`) -- vertical bars in
  grouted cores, a rectangular stress block on ``f'm``. Only applies when
  the section has reinforcement; supersedes the unreinforced mechanisms
  entirely rather than adding to them.

:func:`check_flexure` picks between them: reinforced if the section has
reinforcement (regardless of ``direction`` -- there is only one reinforced
mechanism in this scope), unreinforced vertical or horizontal by
``direction`` otherwise.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] UNVERIFIED, and more heavily simplified than ``as3600``/``as4100``
-- see ``constants.py`` and the notes on each function.
"""

from __future__ import annotations

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_AREA, U_LENGTH, U_MOMENT, U_NONE, U_STRESS, kNm
from ...sections.masonry_section import MasonryWallSection
from . import constants as C

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Flexural capacity of masonry walls to AS 3700:2018, one-way strip only",
    envelope_summary="One-way spanning strip -- not the two-way panel/yield-line method",
)


def _require_unreinforced(section: MasonryWallSection, fn_name: str) -> None:
    if section.reinforced:
        raise ValueError(
            f"{fn_name}() is the UNREINFORCED formula -- section '{section.name}' "
            "has reinforcement. Use reinforced_moment_capacity(), or call "
            "check_flexure() which dispatches automatically."
        )


def vertical_bending_capacity(section: MasonryWallSection, fd: float = 0.0) -> CalcResult:
    """Unreinforced vertical bending capacity -- tension perpendicular to
    the bed joints.

    Basis
    -----
    AS 3700:2018 Cl 7.4.2, SIMPLIFIED to a one-way strip (see module
    docstring): ``Muo = (f'mt + fd_credited) . Z``.

    Parameters
    ----------
    section:
        Must be unreinforced.
    fd:
        Design compressive stress on the section from vertical load (MPa),
        e.g. self-weight of wall and any supported floor/roof above. Credited
        toward the flexural tensile capacity, capped at
        ``FD_MAX_ENHANCEMENT_RATIO . f'mt`` (see ``constants.py``).
    """
    _require_unreinforced(section, "vertical_bending_capacity")

    env = Envelope(name="Vertical bending, unreinforced")
    env.add("fd", fd, lower=0.0, unit="MPa", basis=C.CLAUSE_VERTICAL_BENDING)
    env.note("One-way vertical strip -- see module docstring for the panel-method gap.")
    env.require()

    basis = Basis()
    basis.add(C.CLAUSE_VERTICAL_BENDING)

    fmt = section.masonry.f_mt
    fd_credited = min(fd, C.FD_MAX_ENHANCEMENT_RATIO * fmt)
    effective_stress = fmt + fd_credited
    Muo = effective_stress * section.Z
    phi = C.PHI_UNREINFORCED_FLEXURE

    result = CalcResult(
        name="Vertical bending capacity, unreinforced -- AS 3700:2018 Cl 7.4.2",
        provenance=PROVENANCE, basis=basis, envelope=env,
    )
    result.add_input("t", Value(section.thickness, U_LENGTH, "t", "Wall thickness"))
    result.add_input("f_mt", Value(fmt, U_STRESS, "f'mt", "Flexural tensile strength, perpendicular"))
    result.add_input("fd", Value(fd, U_STRESS, "fd", "Design compressive stress"))
    result.add_intermediate(
        "fd_credited", Value(fd_credited, U_STRESS, "fd,cr", "fd credited toward capacity")
    )
    result.add_intermediate("Z", Value(section.Z, "mm^3", "Z", "Section modulus"))
    result.add_output("phi", Value(phi, U_NONE, "phi", "Capacity reduction factor"))
    result.add_output("Muo", Value(Muo, U_MOMENT, "M_uo", "Nominal capacity", "kN.m/m", kNm))
    result.add_output(
        "phiMuo", Value(phi * Muo, U_MOMENT, "phi.M_uo", "Design capacity", "kN.m/m", kNm)
    )
    if fd > fd_credited:
        result.note(
            f"fd ({fd:.2f} MPa) exceeds the {C.FD_MAX_ENHANCEMENT_RATIO:g}x f'mt "
            f"credit cap -- only {fd_credited:.2f} MPa of it was used."
        )
    return result


def horizontal_bending_capacity(section: MasonryWallSection) -> CalcResult:
    """Unreinforced horizontal bending capacity -- tension parallel to the
    bed joints.

    Basis
    -----
    AS 3700:2018 Cl 7.4.3, SIMPLIFIED to a one-way strip using
    ``f'mt,parallel`` (see :class:`~austruct.materials.masonry.MasonryGrade`)
    rather than the full panel/aspect-ratio method: ``Muo = f'mt,par . Z``.
    No fd enhancement -- unlike vertical bending, axial load does not act to
    close a horizontal-spanning crack in this simplified model.
    """
    _require_unreinforced(section, "horizontal_bending_capacity")

    env = Envelope(name="Horizontal bending, unreinforced")
    env.note("One-way horizontal strip -- see module docstring for the panel-method gap.")
    env.require()

    basis = Basis()
    basis.add(C.CLAUSE_HORIZONTAL_BENDING)

    fmt_par = section.masonry.f_mt_parallel
    Muo = fmt_par * section.Z
    phi = C.PHI_UNREINFORCED_FLEXURE

    result = CalcResult(
        name="Horizontal bending capacity, unreinforced -- AS 3700:2018 Cl 7.4.3",
        provenance=PROVENANCE, basis=basis, envelope=env,
    )
    result.add_input("t", Value(section.thickness, U_LENGTH, "t", "Wall thickness"))
    result.add_input(
        "f_mt_par", Value(fmt_par, U_STRESS, "f'mt,par", "Flexural tensile strength, parallel")
    )
    result.add_intermediate("Z", Value(section.Z, "mm^3", "Z", "Section modulus"))
    result.add_output("phi", Value(phi, U_NONE, "phi", "Capacity reduction factor"))
    result.add_output("Muo", Value(Muo, U_MOMENT, "M_uo", "Nominal capacity", "kN.m/m", kNm))
    result.add_output(
        "phiMuo", Value(phi * Muo, U_MOMENT, "phi.M_uo", "Design capacity", "kN.m/m", kNm)
    )
    return result


def reinforced_moment_capacity(section: MasonryWallSection) -> CalcResult:
    """Reinforced masonry flexural capacity -- vertical bars in grouted cores.

    Basis
    -----
    AS 3700:2018 Cl 8.5, SIMPLIFIED rectangular stress block (see
    ``constants.py``): ``a = Ast.fsy / (ALPHA_MASONRY.f'm.b)``,
    ``Muo = Ast.fsy.(d - a/2)``, with a ductility check ``ku = a/d <= KU_MAX``.

    Raises
    ------
    ValueError
        If ``section`` has no reinforcement.
    """
    if not section.reinforced:
        raise ValueError(
            f"reinforced_moment_capacity() requires reinforcement -- section "
            f"'{section.name}' has none. Use vertical_/horizontal_bending_capacity()."
        )

    env = Envelope(name="Reinforced masonry flexure")
    env.require()

    basis = Basis()
    basis.add(C.CLAUSE_REINFORCED_FLEXURE)

    r = section.reinforcement
    Ast = section.Ast
    d = r.depth
    fsy = r.material.fsy
    f_m = section.masonry.f_m
    b = section.design_width

    a = Ast * fsy / (C.ALPHA_MASONRY * f_m * b)
    ku = a / d
    Muo = Ast * fsy * (d - a / 2.0)
    phi = C.PHI_REINFORCED_FLEXURE

    result = CalcResult(
        name="Reinforced masonry flexural capacity -- AS 3700:2018 Cl 8.5",
        provenance=PROVENANCE, basis=basis, envelope=env,
    )
    result.add_input("t", Value(section.thickness, U_LENGTH, "t", "Wall thickness"))
    result.add_input("Ast", Value(Ast, U_AREA, "A_st", "Reinforcement area in strip width"))
    result.add_input("d", Value(d, U_LENGTH, "d", "Effective depth"))
    result.add_input("fsy", Value(fsy, U_STRESS, "f_sy", "Reinforcement yield strength"))
    result.add_input("f_m", Value(f_m, U_STRESS, "f'm", "Masonry compressive strength"))
    result.add_intermediate("a", Value(a, U_LENGTH, "a", "Stress block depth"))
    result.add_intermediate("ku", Value(ku, U_NONE, "k_u", "a / d"))
    result.add_output("phi", Value(phi, U_NONE, "phi", "Capacity reduction factor"))
    result.add_output("Muo", Value(Muo, U_MOMENT, "M_uo", "Nominal capacity", "kN.m/m", kNm))
    result.add_output(
        "phiMuo", Value(phi * Muo, U_MOMENT, "phi.M_uo", "Design capacity", "kN.m/m", kNm)
    )
    result.add_check(
        Check(
            label="Ductility, k_u <= limit",
            actual=ku, limit=C.KU_MAX_REINFORCED, operator="<=", unit=U_NONE,
            basis=C.CLAUSE_REINFORCED_FLEXURE,
        )
    )
    return result


def check_flexure(
    section: MasonryWallSection,
    M_star: float,  # noqa: N803
    direction: str = "vertical",
    fd: float = 0.0,
) -> CalcResult:
    """Check a wall's flexural capacity against a design moment.

    Dispatches on ``section.reinforced``: reinforced sections always use
    :func:`reinforced_moment_capacity` (``direction`` is ignored -- there is
    only one reinforced mechanism in this scope); unreinforced sections use
    ``direction`` to choose vertical or horizontal bending.

    Parameters
    ----------
    M_star:
        Design bending moment per metre of wall length (N.mm/m), magnitude.
    direction:
        ``"vertical"`` or ``"horizontal"``. Ignored for a reinforced section.
    fd:
        Design compressive stress (MPa) -- only used for unreinforced
        vertical bending.
    """
    M_star = abs(M_star)

    if section.reinforced:
        result = reinforced_moment_capacity(section)
    elif direction == "vertical":
        result = vertical_bending_capacity(section, fd)
    elif direction == "horizontal":
        result = horizontal_bending_capacity(section)
    else:
        raise ValueError(f"direction must be 'vertical' or 'horizontal', got {direction!r}")

    result.name = f"Flexural strength check -- AS 3700:2018 ({result.name.split('--')[-1].strip()})"
    result.add_input(
        "Mstar", Value(M_star, U_MOMENT, "M*", "Design bending moment", "kN.m/m", kNm)
    )
    result.add_check(
        Check(
            label="Flexural strength, M* <= phi.M_uo",
            actual=M_star, limit=result.get("phiMuo"), operator="<=", unit=U_MOMENT,
            basis=C.CLAUSE_REINFORCED_FLEXURE if section.reinforced else C.CLAUSE_VERTICAL_BENDING,
            display_factor=kNm, display_unit="kN.m/m",
        )
    )
    return result
