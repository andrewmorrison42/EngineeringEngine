"""Shear capacity to AS 4100 Section 5.11, and the M-V interaction of Cl 5.12.

What carries shear in a steel beam
----------------------------------
The web, essentially alone. The flanges are close to the neutral axis in the
shear sense and contribute little, so AS 4100 takes the web area and ignores
the flanges entirely. That is a bigger simplification than it sounds and it is
what makes the shear check so quick: one area, one stress.

The two ways a web fails
------------------------
**Yield.** A stocky web reaches the shear yield stress ``0.6 f_y`` across its
whole depth. Capacity is ``V_w = 0.6 f_y A_w``.

**Buckling.** A slender web buckles diagonally before it yields, at a stress
below ``0.6 f_y``. The capacity falls away with the SQUARE of the slenderness,
so a web only slightly past the limit loses capacity quickly.

The dividing line is ``(d_p/t_w) sqrt(f_y/250) = 82``. Almost every rolled
universal beam is comfortably stocky; slender webs turn up in fabricated
plate girders, which is exactly where a designer is most likely to be
extrapolating from experience with rolled sections.

Which f_y
---------
The WEB value, not the flange value. The web is thinner, so its yield stress is
usually higher, and using the flange value here would be conservative rather
than wrong -- but it would be conservative by an amount that varies with the
section, which is worse than either being right or being consistently safe.

[UNITS] mm, N, MPa.

[VECTOR] This module is UNVERIFIED. Its constants are in ``constants.py``.
"""

from __future__ import annotations

import math

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_AREA, U_FORCE, U_MOMENT, U_NONE, U_STRESS, kN, kNm
from ...sections.steel_catalogue import CatalogueSection
from ...sections.steel_profile import ShapeType
from . import constants as C
from .flexure import section_moment_capacity

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Shear capacity and shear-moment interaction to AS 4100 Sections 5.11, 5.12",
    envelope_summary=(
        "Unstiffened webs; shear carried by the web alone; "
        "no transverse or longitudinal stiffeners"
    ),
)


def _envelope() -> Envelope:
    env = Envelope(name="AS 4100 shear")
    env.note(
        "UNSTIFFENED web. Transverse stiffeners raise the buckling capacity "
        "substantially and are not modelled, so a stiffened girder is treated "
        "conservatively -- often very conservatively."
    )
    env.note(
        "Shear carried by the web alone. The flanges are ignored, which is the "
        "standard's own idealisation."
    )
    env.note("Uniform shear stress assumed over the web depth.")
    env.note("No web openings, notches or coped ends.")
    return env


def web_area(section: CatalogueSection) -> float:
    """``A_w`` -- the web area resisting shear (mm^2).

    Taken as ``d . t_w``, the OVERALL depth times the web thickness, not the
    clear depth between flanges. That is AS 4100's definition and it is
    slightly generous relative to the clear depth -- the flange material at the
    junction does carry some shear.

    [VECTOR] UNVERIFIED -- confirm whether the standard uses d or d_1 here. The
             two differ by roughly 7% for a typical UB, straight onto the
             capacity.
    """
    if section.profile.shape is ShapeType.PLATE:
        # A plate on edge: the whole section is "web".
        return section.d * section.tf
    return section.d * section.tw


def web_slenderness(section: CatalogueSection) -> float:
    """``(d_p / t_w) sqrt(f_y / 250)`` -- what decides yield versus buckling.

    ``d_p`` is the clear depth of the web panel, between the flanges. Note this
    is the CLEAR depth, whereas the shear AREA uses the overall depth -- the
    two serve different purposes and the standard uses different depths for
    them, which is an easy thing to homogenise by mistake.
    """
    if section.profile.shape is ShapeType.PLATE:
        return (section.d / section.tf) * math.sqrt(
            section.fy_flange / C.SLENDERNESS_REFERENCE_FY
        )
    dp = section.d - 2.0 * section.tf
    return (dp / section.tw) * math.sqrt(section.fy_web / C.SLENDERNESS_REFERENCE_FY)


def shear_capacity(section: CatalogueSection, name: str = "") -> CalcResult:
    """Nominal shear capacity ``V_v``, by yield or by buckling.

    Returns
    -------
    CalcResult
        With ``Vv`` and ``phiVv`` as outputs, and an intermediate saying which
        mechanism governed.
    """
    result = CalcResult(
        name=name or f"Shear capacity, AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(),
        basis=Basis([C.CLAUSE_SHEAR, C.CLAUSE_SHEAR_YIELD, C.CLAUSE_SHEAR_BUCKLING]),
    )

    aw = web_area(section)
    fy = (
        section.fy_flange
        if section.profile.shape is ShapeType.PLATE
        else section.fy_web
    )
    lam = web_slenderness(section)

    vw = C.SHEAR_YIELD_FACTOR * fy * aw

    result.add_input("section", Value(0.0, U_NONE, section.designation, "Section"))
    result.add_input("fy_web", Value(fy, U_STRESS, "f_yw", "Web yield stress"))
    result.add_intermediate("Aw", Value(aw, U_AREA, "A_w", "Web shear area"))
    result.add_intermediate(
        "lambda_w", Value(lam, U_NONE, "lam_w", "Web slenderness for shear")
    )
    result.add_intermediate(
        "Vw", Value(vw, U_FORCE, "V_w", "Shear yield capacity", "kN", kN)
    )

    if lam <= C.WEB_SLENDERNESS_YIELD_LIMIT:
        vv = vw
        alpha_v = 1.0
        governed = "web yield"
    else:
        alpha_v = (C.SHEAR_BUCKLING_COEFFICIENT / lam) ** 2
        vv = alpha_v * vw
        governed = "web shear buckling"

    result.add_intermediate(
        "alpha_v", Value(alpha_v, U_NONE, "alpha_v", "Shear buckling factor")
    )
    result.add_output("Vv", Value(vv, U_FORCE, "V_v", "Nominal shear capacity", "kN", kN))
    result.add_output(
        "phiVv", Value(C.PHI * vv, U_FORCE, "phi.V_v", "Design shear capacity", "kN", kN)
    )

    result.note(f"Governed by {governed} (lambda_w = {lam:.1f}).")
    if governed == "web shear buckling":
        result.note(
            f"The web is SLENDER in shear -- lambda_w = {lam:.1f} exceeds "
            f"{C.WEB_SLENDERNESS_YIELD_LIMIT:.0f}. Capacity falls with the "
            "square of slenderness, so it drops quickly past the limit. "
            "Transverse stiffeners would raise it substantially and are not "
            "modelled."
        )
    result.note(
        "Shear area uses the OVERALL depth; the slenderness uses the CLEAR "
        "depth between flanges. Different depths for different purposes -- not "
        "an inconsistency."
    )
    return result


def check_shear(
    section: CatalogueSection,
    V_star: float,  # noqa: N803
    name: str = "",
) -> CalcResult:
    """Check ``V*`` against the shear capacity."""
    result = shear_capacity(section, name=name)
    phi_vv = result.get("phiVv")

    result.add_input("V_star", Value(V_star, U_FORCE, "V*", "Design shear", "kN", kN))
    result.add_check(
        Check(
            label="V* <= phi.V_v",
            actual=abs(V_star),
            limit=phi_vv,
            operator="<=",
            unit=U_FORCE,
            display_factor=kN,
            display_unit="kN",
            basis=C.CLAUSE_SHEAR,
        )
    )
    return result


def check_shear_and_moment(
    section: CatalogueSection,
    V_star: float,  # noqa: N803
    M_star: float,  # noqa: N803
    *,
    fully_restrained: bool = False,
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """Combined shear and bending, AS 4100 Cl 5.12.3.

    A web carrying high shear has less capacity left for the flexural stresses,
    so beyond a threshold the moment capacity is reduced::

        V* <= 0.75 phi.V_v          no reduction
        V* >  0.75 phi.V_v          V_vm = V_v (2.2 - 1.6 M*/(phi.M_s))

    The interaction bites at a support of a heavily loaded short-span beam,
    where shear and hogging moment peak together -- and almost nowhere else,
    which is why it is easy to forget it exists.

    Parameters
    ----------
    fully_restrained:
        As :func:`~austruct.design.as4100.flexure.check_flexure`. The moment
        side of this check is a SECTION capacity, so the same restriction
        applies.

    Raises
    ------
    ModelError
        If the segment is not declared fully restrained.
    """
    if not fully_restrained:
        raise ModelError(
            "check_shear_and_moment uses the SECTION moment capacity, so it is "
            "valid only for a fully restrained segment. Declare "
            "fully_restrained=True, or check the member capacity separately "
            "with as4100.check_member_flexure() and this interaction against "
            "that."
        )

    result = CalcResult(
        name=name or f"Shear and bending, AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(),
        basis=Basis([C.CLAUSE_SHEAR, C.CLAUSE_SHEAR_MOMENT]),
    )

    shear = shear_capacity(section)
    flexure = section_moment_capacity(section, "x", residual)
    vv = shear.get("Vv")
    ms = flexure.get("Ms")
    phi_vv = C.PHI * vv
    phi_ms = C.PHI * ms

    result.add_input("V_star", Value(V_star, U_FORCE, "V*", "Design shear", "kN", kN))
    result.add_input(
        "M_star", Value(M_star, U_MOMENT, "M*", "Design moment", "kN.m", kNm)
    )
    result.add_intermediate("Vv", Value(vv, U_FORCE, "V_v", "Shear capacity", "kN", kN))
    result.add_intermediate(
        "Ms", Value(ms, U_MOMENT, "M_s", "Section moment capacity", "kN.m", kNm)
    )

    ratio = abs(V_star) / phi_vv if phi_vv else float("inf")
    result.add_intermediate(
        "V_ratio", Value(ratio, U_NONE, "V*/phi.V_v", "Shear utilisation")
    )

    if ratio <= C.SHEAR_MOMENT_INTERACTION_THRESHOLD:
        vvm = vv
        result.note(
            f"V* is {ratio:.0%} of phi.V_v, at or below the "
            f"{C.SHEAR_MOMENT_INTERACTION_THRESHOLD:.0%} threshold, so the "
            "moment capacity is not reduced."
        )
    else:
        moment_ratio = abs(M_star) / phi_ms if phi_ms else 0.0
        factor = C.SHEAR_MOMENT_SLOPE_NUM - C.SHEAR_MOMENT_SLOPE_DEN * moment_ratio
        vvm = max(0.0, min(vv, factor * vv))
        result.note(
            f"V* is {ratio:.0%} of phi.V_v, above the "
            f"{C.SHEAR_MOMENT_INTERACTION_THRESHOLD:.0%} threshold, so the "
            "shear capacity is reduced by the coincident moment."
        )

    result.add_output(
        "Vvm", Value(vvm, U_FORCE, "V_vm", "Shear capacity with moment", "kN", kN)
    )
    result.add_check(
        Check(
            label="V* <= phi.V_vm  (with coincident moment)",
            actual=abs(V_star),
            limit=C.PHI * vvm,
            operator="<=",
            unit=U_FORCE,
            display_factor=kN,
            display_unit="kN",
            basis=C.CLAUSE_SHEAR_MOMENT,
        )
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
    result.note(
        "M* and V* must be COINCIDENT -- the values at the same section under "
        "the same load case. Taking the envelope maximum of each is "
        "conservative but can be very conservative, because peak shear and "
        "peak moment rarely occur together."
    )
    return result


def shear_at_distance(
    section: CatalogueSection,
    V_star: float,  # noqa: N803
    name: str = "",
) -> CalcResult:
    """Alias for :func:`check_shear`, kept explicit.

    AS 4100 does not permit the shear to be taken at a distance from the
    support the way the concrete standards do -- there is no equivalent of
    "shear at d from the face". So there is no reduction to apply here, and a
    function named for one would be misleading.
    """
    return check_shear(section, V_star, name=name)
