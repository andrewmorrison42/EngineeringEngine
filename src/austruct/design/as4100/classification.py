"""Section slenderness and the effective section modulus, AS 4100 Section 5.2.

Why this comes before flexure
-----------------------------
The moment capacity of a steel section is ``M_s = f_y . Z_e``, and ``Z_e`` is
not a property of the geometry alone. It depends on whether the section's plate
elements can reach yield and hold it, buckle locally before yield, or manage
something in between. So classification is not a refinement applied afterwards
-- there is no ``M_s`` without it.

The mechanism
-------------
Each plate element gets a slenderness::

    lambda_e = (b/t) . sqrt(f_y / 250)

compared against two limits: a **plasticity** limit below which the element can
sustain the plastic moment, and a **yield** limit above which it buckles before
reaching yield. The ``sqrt(f_y/250)`` term is why a higher grade is *more*
prone to local buckling for the same geometry -- it asks the plate to carry a
higher stress, and the plate does not care what grade it is.

The section then takes the WORST of its elements, on the reasonable ground that
a section is no more compact than its most slender part.

  compact       Z_e = S, the plastic modulus
  non-compact   Z_e interpolates between S and Z
  slender       Z_e is reduced below Z

The trap
--------
For an I-section, the flange outstand is ``(b_f - t_w)/2`` measured from the
web face to the toe -- NOT ``b_f/2``, and not the full flange width. The web
element is the clear depth between the flanges. Getting either wrong shifts the
compactness class, and the class steps the capacity rather than nudging it.

[UNITS] mm, MPa, mm^3.

[VECTOR] This module is UNVERIFIED. The plate limits in ``constants.py`` are
         the values to check first -- they decide a step change, not a gradient.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ...core.basis import Basis
from ...core.contract import CalcResult, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_LENGTH, U_NONE, U_STRESS, U_Z
from ...sections.steel_catalogue import CatalogueSection
from ...sections.steel_profile import ShapeType
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
    description="Section slenderness and effective section modulus to AS 4100 Section 5.2",
    envelope_summary="I-sections, channels and plates; uniform compression assumed in each element",
)


class Compactness(str, Enum):
    """What a section can do before it buckles locally."""

    COMPACT = "compact"
    """Reaches and sustains the plastic moment. ``Z_e = S``."""

    NON_COMPACT = "non-compact"
    """Reaches yield but cannot sustain full plasticity. ``Z_e`` interpolates."""

    SLENDER = "slender"
    """Buckles locally before reaching yield. ``Z_e`` is reduced below ``Z``."""


@dataclass(frozen=True)
class PlateElement:
    """One plate element of a section, and its slenderness.

    Attributes
    ----------
    name:
        ``"flange outstand"``, ``"web"``, ``"flange both edges"``.
    b, t:
        The flat width and the thickness (mm).
    fy:
        Yield stress of THIS element (MPa) -- the flange and the web can
        differ, because they are different thicknesses.
    lambda_e:
        ``(b/t) sqrt(f_y/250)``.
    lambda_ep, lambda_ey:
        Plasticity and yield limits from Table 5.2.
    """

    name: str
    b: float
    t: float
    fy: float
    lambda_e: float
    lambda_ep: float
    lambda_ey: float

    @property
    def compactness(self) -> Compactness:
        if self.lambda_e <= self.lambda_ep:
            return Compactness.COMPACT
        if self.lambda_e <= self.lambda_ey:
            return Compactness.NON_COMPACT
        return Compactness.SLENDER

    @property
    def utilisation(self) -> float:
        """``lambda_e / lambda_ey`` -- how close this element is to slender."""
        return self.lambda_e / self.lambda_ey if self.lambda_ey else 0.0

    def __str__(self) -> str:
        return (
            f"{self.name:<18} b/t = {self.b / self.t:6.2f}  "
            f"lambda_e = {self.lambda_e:6.2f}  "
            f"(ep {self.lambda_ep:.0f}, ey {self.lambda_ey:.0f})  "
            f"{self.compactness.value}"
        )


@dataclass(frozen=True)
class SectionSlenderness:
    """The classification of a whole section.

    Attributes
    ----------
    elements:
        Every plate element, each with its own slenderness.
    governing:
        The element that decides the class -- the one with the highest
        ``lambda_e / lambda_ey``.
    compactness:
        The section class, taken from the governing element.
    lambda_s, lambda_sp, lambda_sy:
        Section slenderness and its two limits, taken from the governing
        element. AS 4100 works with these at section level.
    Ze:
        Effective section modulus (mm^3).
    """

    elements: tuple[PlateElement, ...]
    governing: PlateElement
    compactness: Compactness
    lambda_s: float
    lambda_sp: float
    lambda_sy: float
    Ze: float  # noqa: N815
    Z: float  # noqa: N815
    S: float  # noqa: N815

    @property
    def uses_plastic_modulus(self) -> bool:
        return self.compactness is Compactness.COMPACT

    def describe(self) -> list[str]:
        lines = ["Plate elements:"]
        lines.extend(f"  {e}" for e in self.elements)
        lines.append("")
        lines.append(f"Governing:   {self.governing.name}")
        lines.append(f"Section:     {self.compactness.value}")
        lines.append(
            f"lambda_s = {self.lambda_s:.2f}  "
            f"(sp {self.lambda_sp:.0f}, sy {self.lambda_sy:.0f})"
        )
        lines.append(f"Z  = {self.Z:.4g} mm^3")
        lines.append(f"S  = {self.S:.4g} mm^3")
        lines.append(f"Z_e = {self.Ze:.4g} mm^3")
        return lines


# ---------------------------------------------------------------------------
# Element extraction
# ---------------------------------------------------------------------------


def plate_elements(
    section: CatalogueSection, residual: str = C.DEFAULT_RESIDUAL
) -> tuple[PlateElement, ...]:
    """The plate elements of a section, with their flat widths.

    The flat widths are where mistakes live, so they are spelled out:

    - **I-section flange outstand**: ``(b_f - t_w) / 2``. From the face of the
      web to the toe of the flange. Not ``b_f / 2``, which would include half
      the web thickness and understate the slenderness.
    - **I-section web**: ``d - 2 t_f``, the clear depth between the flanges.
    - **Channel flange outstand**: ``b_f - t_w``. A channel flange is supported
      at the web and free at its toe, so the whole projection is the outstand
      -- twice the equivalent I-section value for the same overall width.

    The root radii are ignored, which makes every flat width slightly LONGER
    than the true one and therefore the slenderness slightly conservative.
    """
    if residual not in ("HR", "HW"):
        raise ModelError(
            f"Residual stress condition must be 'HR' (hot-rolled) or 'HW' "
            f"(heavily welded), got {residual!r}"
        )

    shape = section.profile.shape
    elements: list[PlateElement] = []

    def build(name: str, b: float, t: float, fy: float) -> PlateElement:
        lam = (b / t) * math.sqrt(fy / C.SLENDERNESS_REFERENCE_FY)
        ep, ey = C.PLATE_LIMITS[(name, residual)]
        return PlateElement(
            name=name, b=b, t=t, fy=fy, lambda_e=lam, lambda_ep=ep, lambda_ey=ey
        )

    if shape in (ShapeType.I_SECTION, ShapeType.WELDED_I):
        elements.append(
            build(
                "flange outstand",
                (section.bf - section.tw) / 2.0,
                section.tf,
                section.fy_flange,
            )
        )
        elements.append(
            build("web", section.d - 2.0 * section.tf, section.tw, section.fy_web)
        )

    elif shape is ShapeType.CHANNEL:
        elements.append(
            build("flange outstand", section.bf - section.tw, section.tf, section.fy_flange)
        )
        elements.append(
            build("web", section.d - 2.0 * section.tf, section.tw, section.fy_web)
        )

    elif shape is ShapeType.PLATE:
        # A plate on edge in bending: the whole depth is an outstand from
        # nothing, so the flange-outstand limits are the closest fit and the
        # most conservative of the available choices.
        elements.append(
            build("flange outstand", section.d, section.tf, section.fy_flange)
        )

    else:
        raise ModelError(
            f"Shape {shape.value!r} has no plate-element decomposition here. "
            "Add one rather than letting it fall through -- an unclassified "
            "section would silently be treated as compact."
        )

    return tuple(elements)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(
    section: CatalogueSection,
    residual: str = C.DEFAULT_RESIDUAL,
    axis: str = "x",
) -> SectionSlenderness:
    """Classify a section and compute its effective section modulus.

    Parameters
    ----------
    section:
        The catalogue section.
    residual:
        ``"HR"`` hot-rolled or ``"HW"`` heavily welded. Welded limits are
        tighter; defaulting a welded section to hot-rolled is unconservative,
        so the shape's own type is checked against this and disagreement
        raises.
    axis:
        ``"x"`` major or ``"y"`` minor.

    Returns
    -------
    SectionSlenderness
    """
    if axis not in ("x", "y"):
        raise ModelError(f"Axis must be 'x' or 'y', got {axis!r}")

    if section.profile.shape is ShapeType.WELDED_I and residual == "HR":
        raise ModelError(
            "This is a welded section but the hot-rolled slenderness limits "
            "were asked for. Welded limits are tighter, so this would be "
            "unconservative. Pass residual='HW'."
        )

    elements = plate_elements(section, residual)
    governing = max(elements, key=lambda e: e.utilisation)

    props = section.properties
    z = props.Zx if axis == "x" else props.Zy
    s = props.Sx if axis == "x" else props.Sy

    lam_s = governing.lambda_e
    lam_sp = governing.lambda_ep
    lam_sy = governing.lambda_ey

    compactness = governing.compactness
    ze = effective_modulus(compactness, lam_s, lam_sp, lam_sy, z, s)

    return SectionSlenderness(
        elements=elements,
        governing=governing,
        compactness=compactness,
        lambda_s=lam_s,
        lambda_sp=lam_sp,
        lambda_sy=lam_sy,
        Ze=ze,
        Z=z,
        S=s,
    )


def effective_modulus(
    compactness: Compactness,
    lambda_s: float,
    lambda_sp: float,
    lambda_sy: float,
    Z: float,  # noqa: N803
    S: float,  # noqa: N803
) -> float:
    """``Z_e`` from the section class, per AS 4100 Cl 5.2.3 to 5.2.5.

    Compact
        ``Z_e = min(S, 1.5 Z)``. The cap stops a section with a very high shape
        factor -- a solid rectangle at 1.5 -- from claiming more reserve than
        the standard allows.

    Non-compact
        Linear interpolation between ``Z`` at the yield limit and the compact
        ``Z_e`` at the plasticity limit. Continuous at both ends by
        construction, which is worth checking: a discontinuity here would show
        up as a section getting *stronger* by being made more slender.

    Slender
        ``Z_e = Z (lambda_sy / lambda_s)``, which falls away as the element gets
        more slender.

    [VECTOR] UNVERIFIED -- the 1.5 cap, the interpolation form, and the slender
             reduction. The slender expression in particular differs between
             element types in the standard and this uses one form for all.
    """
    if compactness is Compactness.COMPACT:
        return min(S, 1.5 * Z)

    if compactness is Compactness.NON_COMPACT:
        ze_compact = min(S, 1.5 * Z)
        span = lambda_sy - lambda_sp
        if span <= 0:
            return Z
        fraction = (lambda_sy - lambda_s) / span
        return Z + fraction * (ze_compact - Z)

    return Z * (lambda_sy / lambda_s)


# ---------------------------------------------------------------------------
# The reportable form
# ---------------------------------------------------------------------------


def check_classification(
    section: CatalogueSection,
    residual: str = C.DEFAULT_RESIDUAL,
    axis: str = "x",
    name: str = "",
) -> CalcResult:
    """Classification as a reportable calculation.

    Not a pass/fail -- a slender section is perfectly legitimate, it just has a
    lower ``Z_e``. So this carries no checks and exists to put the working in
    the report, where a reviewer can see WHY the capacity used the modulus it
    did.
    """
    result = CalcResult(
        name=name or f"Section slenderness, AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(),
        basis=Basis([C.CLAUSE_SECTION_SLENDERNESS, C.CLAUSE_PLATE_LIMITS, C.CLAUSE_ZE]),
    )

    slenderness = classify(section, residual, axis)

    result.add_input("section", Value(0.0, U_NONE, section.designation, "Section"))
    result.add_input(
        "fy_flange", Value(section.fy_flange, U_STRESS, "f_yf", "Flange yield stress")
    )
    result.add_input("fy_web", Value(section.fy_web, U_STRESS, "f_yw", "Web yield stress"))
    result.add_input("residual", Value(0.0, U_NONE, residual, "Residual stress condition"))

    for element in slenderness.elements:
        key = element.name.replace(" ", "_")
        result.add_intermediate(
            f"b_{key}", Value(element.b, U_LENGTH, f"b[{element.name}]", "Flat width")
        )
        result.add_intermediate(
            f"lambda_{key}",
            Value(element.lambda_e, U_NONE, f"lam_e[{element.name}]", "Element slenderness"),
        )

    result.add_intermediate(
        "lambda_s", Value(slenderness.lambda_s, U_NONE, "lam_s", "Section slenderness")
    )
    result.add_intermediate("Z", Value(slenderness.Z, U_Z, "Z", "Elastic section modulus"))
    result.add_intermediate("S", Value(slenderness.S, U_Z, "S", "Plastic section modulus"))
    result.add_output("Ze", Value(slenderness.Ze, U_Z, "Z_e", "Effective section modulus"))

    result.note(
        f"Governed by the {slenderness.governing.name}: the section is "
        f"{slenderness.compactness.value.upper()}."
    )
    if slenderness.compactness is Compactness.COMPACT and slenderness.S > 1.5 * slenderness.Z:
        result.note(
            "Z_e capped at 1.5 Z. The section's own shape factor is higher, but "
            "the standard does not allow the full plastic modulus to be used."
        )
    if slenderness.compactness is Compactness.SLENDER:
        result.note(
            "SLENDER. The section buckles locally before reaching yield, so Z_e "
            "is below the elastic modulus and the capacity is reduced "
            "accordingly."
        )
    result.note(
        "Root radii are not modelled, so every flat width is slightly longer "
        "than the true one and the slenderness is slightly conservative."
    )
    return result


def _envelope() -> Envelope:
    env = Envelope(name="AS 4100 section slenderness")
    env.note(
        "Uniform compression assumed across each plate element. A web in "
        "bending has a stress gradient and less of it is in compression, which "
        "the standard recognises with different limits -- not implemented, and "
        "this is CONSERVATIVE for a web in pure bending."
    )
    env.note(
        "Root radii ignored, so flat widths are slightly overstated and the "
        "classification is slightly conservative."
    )
    env.note("Doubly symmetric I-sections, channels and plates only.")
    return env
