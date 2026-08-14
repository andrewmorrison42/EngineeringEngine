"""Compression member capacity to AS 4100 Section 6.

The two capacities, and why both are needed
-------------------------------------------
``N_s`` **section capacity** -- what the cross-section can carry if it cannot
buckle. Squashing.

``N_c`` **member capacity** -- what the member can carry given that it can. For
anything but a stub, ``N_c`` is the smaller and it is the answer.

Same shape as the flexure story: the section capacity is not the design
capacity, and the difference grows with length. Unlike flexure, this module
does not need to refuse anything -- a compression member's effective length is
a geometric property of the frame, not a restraint condition that has to be
declared, so there is a sensible thing to compute in every case.

The form factor
---------------
``k_f = A_e / A_g``. A slender plate element cannot carry stress right up to
yield across its whole width, so part of it is discounted. For a rolled section
``k_f`` is 1.0 -- rolled sections are compact in compression too -- and it bites
only on fabricated sections with thin plates.

The column curve
----------------
``alpha_c`` comes from a chain of four intermediate quantities, not one
expression. That chain is written out in ``constants.py`` because a
half-remembered chain is worse than none. What it encodes is that a real column
is not the Euler ideal: it has residual stresses from rolling and it is not
perfectly straight, and ``alpha_b`` says how bad those are for this section and
this axis.

The single most consequential input here is ``alpha_b``, and it is not a
property of the geometry -- it depends on how the section was made and which
axis is buckling. Major-axis buckling of a rolled UB is the best case;
everything else is worse.

[UNITS] mm, N, MPa.

[VECTOR] This module is UNVERIFIED. The column-curve chain in ``constants.py``
         compounds -- four coefficients multiply into one answer and none is
         checkable from the result alone.
"""

from __future__ import annotations

import math

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_AREA, U_FORCE, U_LENGTH, U_NONE, U_STRESS, kN
from ...sections.steel_catalogue import CatalogueSection
from . import constants as C
from .classification import Compactness, classify

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Compression member capacity to AS 4100 Section 6",
    envelope_summary=(
        "Concentrically loaded prismatic members; flexural buckling only; "
        "no torsional or flexural-torsional buckling"
    ),
)


def _envelope() -> Envelope:
    env = Envelope(name="AS 4100 compression")
    env.note(
        "FLEXURAL buckling only. A singly symmetric or thin-walled open "
        "section can buckle torsionally or flexural-torsionally at a lower "
        "load, and that is NOT checked here -- which matters most for "
        "channels and cruciforms."
    )
    env.note("Concentric load. Any eccentricity needs the combined actions of Section 8.")
    env.note("Prismatic member, uniform axial force along its length.")
    return env


def form_factor(section: CatalogueSection, residual: str = C.DEFAULT_RESIDUAL) -> float:
    """``k_f = A_e / A_g`` -- the effective area fraction.

    1.0 for a section whose plate elements are all compact or non-compact in
    uniform compression, which covers every rolled UB and UC. Below 1.0 only
    where an element is slender, i.e. it buckles locally before the section
    reaches yield.

    [ASSUMPTION] Computed from the section slenderness classification, which
                 was derived for BENDING. In uniform compression a web has no
                 stress gradient to help it and the limits differ. This is
                 therefore approximate, and UNCONSERVATIVE for a section with a
                 slender web in compression.
    """
    slenderness = classify(section, residual, "x")
    if slenderness.compactness is not Compactness.SLENDER:
        return 1.0
    return min(1.0, slenderness.lambda_sy / slenderness.lambda_s)


def modified_slenderness(
    le: float, r: float, kf: float, fy: float
) -> float:
    """``lambda_n = (l_e/r) sqrt(k_f) sqrt(f_y/250)``.

    The geometric slenderness, adjusted for the form factor and normalised to
    Grade 250 -- the same normalisation the plate slenderness uses, and for the
    same reason: a higher grade asks more of the same geometry.
    """
    if r <= 0:
        raise ModelError(f"Radius of gyration must be positive, got {r}")
    if le <= 0:
        raise ModelError(f"Effective length must be positive, got {le}")
    return (le / r) * math.sqrt(kf) * math.sqrt(fy / C.SLENDERNESS_REFERENCE_FY)


def compression_factor(lambda_n: float, alpha_b: float) -> float:
    """``alpha_c`` -- the member slenderness reduction factor.

    The chain from Cl 6.3.3, written out in ``constants.py``. Bounded above by
    1.0: a member can never carry more than its own section.

    Parameters
    ----------
    lambda_n:
        Modified slenderness.
    alpha_b:
        Member section constant. Encodes residual stresses and out-of-
        straightness. Lower is better -- 0.0 for major-axis buckling of a
        rolled UB, 0.5 for minor axis, and this is where the answer is most
        sensitive to an input that is not geometric.
    """
    if lambda_n <= 0:
        return 1.0

    denominator = (
        lambda_n**2 - C.ALPHA_A_QUAD_B * lambda_n + C.ALPHA_A_QUAD_C
    )
    if denominator == 0:
        raise ModelError(
            f"The alpha_a denominator vanishes at lambda_n = {lambda_n:.3f}. "
            "This is a singularity in the fitted curve, not a physical result."
        )
    alpha_a = C.ALPHA_A_NUMERATOR * (lambda_n - C.ALPHA_A_OFFSET) / denominator

    lam = lambda_n + alpha_a * alpha_b
    if lam <= 0:
        return 1.0

    eta = max(0.0, C.ETA_COEFFICIENT * (lam - C.ETA_OFFSET))
    ratio = (lam / C.LAMBDA_REFERENCE) ** 2
    if ratio == 0:
        return 1.0

    xi = (ratio + 1.0 + eta) / (2.0 * ratio)
    inner = 1.0 - (C.LAMBDA_REFERENCE / (xi * lam)) ** 2
    if inner < 0:
        # Very stocky: the curve tops out and the member squashes.
        return 1.0
    return min(1.0, xi * (1.0 - math.sqrt(inner)))


def section_compression_capacity(
    section: CatalogueSection,
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """``N_s = k_f A_n f_y`` -- the squash capacity of the cross-section."""
    result = CalcResult(
        name=name or f"Section compression capacity, AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(),
        basis=Basis([C.CLAUSE_SECTION_COMPRESSION, C.CLAUSE_PHI]),
    )

    kf = form_factor(section, residual)
    # Net area equals gross: no holes are modelled.
    an = section.properties.A
    fy = section.fy_flange
    ns = kf * an * fy

    result.add_input("section", Value(0.0, U_NONE, section.designation, "Section"))
    result.add_input("fy", Value(fy, U_STRESS, "f_y", "Yield stress"))
    result.add_intermediate("An", Value(an, U_AREA, "A_n", "Net area"))
    result.add_intermediate("kf", Value(kf, U_NONE, "k_f", "Form factor"))
    result.add_output("Ns", Value(ns, U_FORCE, "N_s", "Section capacity", "kN", kN))
    result.add_output(
        "phiNs", Value(C.PHI * ns, U_FORCE, "phi.N_s", "Design section capacity", "kN", kN)
    )

    result.note(
        "Net area taken as gross -- no bolt holes are modelled. A member with "
        "holes in the compression zone is unaffected (the bolt fills it), but "
        "one in tension is not, and this module does not do tension."
    )
    if kf < 1.0:
        result.note(
            f"k_f = {kf:.3f}: an element is slender in compression and part of "
            "it is discounted. Note the classification was derived for bending, "
            "so this is approximate -- see the function docstring."
        )
    return result


def member_compression_capacity(
    section: CatalogueSection,
    le: float,
    *,
    axis: str = "y",
    alpha_b: float = C.ALPHA_B_DEFAULT,
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """``N_c = alpha_c N_s <= N_s`` -- the member capacity.

    Parameters
    ----------
    le:
        Effective length for buckling about ``axis`` (mm). This is
        ``k_e L`` -- the caller supplies it, because ``k_e`` depends on the
        frame the member sits in, which this package cannot see.
    axis:
        Which axis buckles. Defaults to ``"y"``, the minor axis, because that
        is the one that governs unless it is separately braced -- and
        defaulting to the major axis would be unconservative.
    alpha_b:
        Member section constant. See :func:`compression_factor`.
    """
    if axis not in ("x", "y"):
        raise ModelError(f"Axis must be 'x' or 'y', got {axis!r}")

    result = section_compression_capacity(section, residual, name=name)
    result.name = name or f"Compression capacity, AS 4100 -- {section.designation}"
    result.basis = Basis(
        [C.CLAUSE_COMPRESSION, C.CLAUSE_SECTION_COMPRESSION, C.CLAUSE_MEMBER_COMPRESSION]
    )

    props = section.properties
    r = props.rx if axis == "x" else props.ry
    kf = result.get("kf")
    ns = result.get("Ns")

    lam_n = modified_slenderness(le, r, kf, section.fy_flange)
    alpha_c = compression_factor(lam_n, alpha_b)
    nc = min(alpha_c * ns, ns)

    result.add_input("le", Value(le, U_LENGTH, "l_e", "Effective length"))
    result.add_input("axis", Value(0.0, U_NONE, axis, "Buckling axis"))
    result.add_intermediate("r", Value(r, U_LENGTH, f"r_{axis}", "Radius of gyration"))
    result.add_intermediate(
        "lambda_n", Value(lam_n, U_NONE, "lam_n", "Modified slenderness")
    )
    result.add_intermediate(
        "alpha_b", Value(alpha_b, U_NONE, "alpha_b", "Member section constant")
    )
    result.add_intermediate(
        "alpha_c", Value(alpha_c, U_NONE, "alpha_c", "Slenderness reduction factor")
    )
    result.add_output("Nc", Value(nc, U_FORCE, "N_c", "Member capacity", "kN", kN))
    result.add_output(
        "phiNc", Value(C.PHI * nc, U_FORCE, "phi.N_c", "Design member capacity", "kN", kN)
    )

    result.note(
        f"Buckling about the {axis}-axis with l_e = {le:.0f} mm gives "
        f"lambda_n = {lam_n:.1f} and alpha_c = {alpha_c:.3f} -- the member "
        f"carries {nc / ns:.0%} of its section capacity."
    )
    if axis == "y":
        result.note(
            "Minor axis, which governs unless it is separately braced. Check "
            "the major axis too where the bracing differs between them."
        )
    result.note(
        "Flexural buckling only. Torsional and flexural-torsional buckling are "
        "NOT checked, and they can govern for a channel or a thin-walled open "
        "section."
    )
    return result


def check_compression(
    section: CatalogueSection,
    N_star: float,  # noqa: N803
    le: float,
    *,
    axis: str = "y",
    alpha_b: float = C.ALPHA_B_DEFAULT,
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """Check ``N*`` against the member compression capacity."""
    result = member_compression_capacity(
        section, le, axis=axis, alpha_b=alpha_b, residual=residual, name=name
    )
    result.add_input(
        "N_star", Value(N_star, U_FORCE, "N*", "Design compression", "kN", kN)
    )
    result.add_check(
        Check(
            label="N* <= phi.N_c",
            actual=abs(N_star),
            limit=result.get("phiNc"),
            operator="<=",
            unit=U_FORCE,
            display_factor=kN,
            display_unit="kN",
            basis=C.CLAUSE_MEMBER_COMPRESSION,
        )
    )
    return result
