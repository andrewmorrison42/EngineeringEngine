"""Restraints and effective length, AS 4100 Section 5.4 and Cl 5.6.3.

What a restraint actually has to do
-----------------------------------
Lateral-torsional buckling is a beam's compression flange going sideways while
the section twists. To stop it you must prevent BOTH -- lateral movement and
twist. Preventing one alone does not work, and the distinction is what the
restraint classification is about:

``F`` full
    Prevents lateral deflection of the critical flange AND twist of the
    section. A slab on shear studs. A beam with a properly connected cleat to
    both flanges.

``P`` partial
    Prevents lateral deflection of the critical flange and gives *some*
    resistance to twist. A cleat to the tension flange only, relying on the
    web to carry the twist.

``L`` lateral
    Prevents lateral deflection of a flange that is NOT the critical one, and
    does nothing about twist. Contributes far less than it looks like it should.

``U`` unrestrained
    Nothing.

A segment is named by its two ends: ``"FF"``, ``"FP"``, ``"PP"``, ``"FL"`` and
so on.

Why this module asks rather than assumes
----------------------------------------
The effective length is::

    l_e = k_t . k_l . k_r . L

and of those three factors only ``k_r`` has a small, safely-defaulted range.

``k_t`` depends on the restraint arrangement AND on the section geometry AND
on the segment length -- AS 4100 gives expressions, not a table of constants.
This module implements ``k_t = 1.0`` for a fully restrained pair, which the
standard states directly, and **requires the caller to supply** ``k_t`` for
every other arrangement.

That is deliberate, and it is the same stance ``check_detailing`` takes on
anchorage length. Inventing a plausible ``k_t`` would produce an effective
length that is wrong by a factor the output gives no sign of, and the member
capacity scales with it.

``k_l`` is the load height factor, and it is the one people forget. A gravity
load applied at the TOP flange is destabilising: as the beam twists, the load
moves outboard and drives it further over. Ignoring it -- taking 1.0 when the
load really is on the top flange -- overstates the capacity by around 40%.

[UNITS] mm.

[VECTOR] This module is UNVERIFIED. See ``constants.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
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
    description="Restraint classification and effective length to AS 4100 Cl 5.6.3",
    envelope_summary="k_t supplied by the caller except for fully restrained segments",
)


class Restraint(str, Enum):
    """What one end of a segment is restrained against."""

    FULL = "F"
    """Lateral deflection AND twist prevented."""

    PARTIAL = "P"
    """Lateral deflection of the critical flange prevented, twist partly."""

    LATERAL = "L"
    """A non-critical flange held laterally. No twist restraint."""

    UNRESTRAINED = "U"
    """Nothing."""

    @property
    def label(self) -> str:
        return {
            Restraint.FULL: "full",
            Restraint.PARTIAL: "partial",
            Restraint.LATERAL: "lateral",
            Restraint.UNRESTRAINED: "unrestrained",
        }[self]


class LoadHeight(str, Enum):
    """Where the load is applied, relative to the shear centre.

    The one people forget, and it costs about 40% of the capacity.
    """

    SHEAR_CENTRE = "shear centre"
    """At or below the shear centre. Not destabilising."""

    TOP_FLANGE = "top flange"
    """On the top flange of a beam in sagging. Destabilising: as the section
    twists, the load moves outboard and drives it further."""


@dataclass(frozen=True)
class Segment:
    """A length of beam between restraints, and everything ``l_e`` needs.

    Attributes
    ----------
    length:
        Distance between the restraints (mm). NOT the span, unless the only
        restraints are at the supports.
    ends:
        Restraint at each end.
    load_height:
        Where the load is applied.
    kt:
        Twist restraint factor. Required unless both ends are FULL.
    kr:
        Lateral rotation restraint factor. Defaults to 1.0 -- no restraint --
        which is conservative.
    name:
        Label for reports.
    """

    length: float
    ends: tuple[Restraint, Restraint]
    load_height: LoadHeight = LoadHeight.SHEAR_CENTRE
    kt: float | None = None
    kr: float = C.KR_BOTH_ENDS_UNRESTRAINED
    name: str = ""

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ModelError(f"Segment length must be positive, got {self.length}")
        if self.kt is not None and self.kt < 1.0:
            raise ModelError(
                f"k_t must be at least 1.0 -- it lengthens the effective length "
                f"and never shortens it. Got {self.kt}."
            )
        if not 0.0 < self.kr <= 1.0:
            raise ModelError(f"k_r must be in (0, 1], got {self.kr}")

    @property
    def code(self) -> str:
        """The two-letter arrangement, e.g. ``"FF"``."""
        return self.ends[0].value + self.ends[1].value

    @property
    def fully_restrained_ends(self) -> bool:
        return all(e is Restraint.FULL for e in self.ends)

    @property
    def has_unrestrained_end(self) -> bool:
        return any(e is Restraint.UNRESTRAINED for e in self.ends)

    def describe(self) -> list[str]:
        return [
            f"Segment    = {self.name or self.code}",
            f"  length   = {self.length:.0f} mm between restraints",
            f"  ends     = {self.ends[0].label} / {self.ends[1].label}  ({self.code})",
            f"  load at  = {self.load_height.value}",
            f"  k_t      = {self.kt if self.kt is not None else 1.0:.3f}",
            f"  k_l      = {load_height_factor(self.load_height):.3f}",
            f"  k_r      = {self.kr:.3f}",
            f"  l_e      = {effective_length(self):.0f} mm",
        ]


def segment(
    length: float,
    ends: str = "FF",
    load_height: LoadHeight | str = LoadHeight.SHEAR_CENTRE,
    kt: float | None = None,
    kr: float = C.KR_BOTH_ENDS_UNRESTRAINED,
    name: str = "",
) -> Segment:
    """Build a segment from the two-letter restraint code.

    Examples
    --------
    A beam with full restraint at both ends, load at the shear centre::

        segment(6000, "FF")

    A 4 m segment with a partial restraint at one end, load on the top flange,
    with ``k_t`` read off Table 5.6.3(1)::

        segment(4000, "FP", load_height="top flange", kt=1.08)
    """
    code = ends.strip().upper()
    if len(code) != 2:
        raise ModelError(
            f"Restraint code must be two letters, one per end, got {ends!r}. "
            "Use F (full), P (partial), L (lateral) or U (unrestrained) -- "
            "for example 'FF', 'FP', 'PL'."
        )
    try:
        pair = (Restraint(code[0]), Restraint(code[1]))
    except ValueError as exc:
        raise ModelError(
            f"Unknown restraint letter in {ends!r}. Valid letters are "
            "F (full), P (partial), L (lateral), U (unrestrained)."
        ) from exc

    height = (
        load_height
        if isinstance(load_height, LoadHeight)
        else LoadHeight(str(load_height))
    )
    return Segment(length=length, ends=pair, load_height=height, kt=kt, kr=kr, name=name)


# ---------------------------------------------------------------------------
# The three factors
# ---------------------------------------------------------------------------


def twist_factor(seg: Segment) -> float:
    """``k_t`` -- the twist restraint factor.

    Returns 1.0 for a segment fully restrained at both ends, which AS 4100
    states directly. For every other arrangement the caller must supply
    ``k_t``, because the standard gives an EXPRESSION involving the segment
    length, the web slenderness and the number of webs -- not a constant.

    Raises
    ------
    ModelError
        For a non-FF arrangement with no ``k_t`` supplied. Defaulting to 1.0
        would treat a partially restrained segment as fully restrained, which
        understates the effective length and overstates the capacity.
    """
    if seg.kt is not None:
        return seg.kt
    if seg.fully_restrained_ends:
        return 1.0
    raise ModelError(
        f"Segment '{seg.code}' is not fully restrained at both ends, so k_t is "
        "not 1.0 and this package will not guess it.\n\n"
        "AS 4100 Cl 5.6.3 gives k_t as an expression in the segment length, "
        "the web geometry and the number of webs -- not a table of constants -- "
        "so it depends on the section as well as the restraint arrangement.\n\n"
        "Read it off Table 5.6.3(1) for this segment and pass it: "
        "segment(length, 'FP', kt=1.08). Taking 1.0 would treat a partially "
        "restrained segment as fully restrained and overstate the capacity."
    )


def load_height_factor(load_height: LoadHeight) -> float:
    """``k_l`` -- the load height factor.

    1.0 for a load at or below the shear centre, 1.4 for a gravity load applied
    at the top flange of a beam in sagging.

    The 1.4 is the value for a segment with both ends fully restrained. AS 4100
    varies it with the restraint arrangement, which this function does not --
    so it is right for FF and approximate elsewhere.

    [VECTOR] UNVERIFIED, and knowingly incomplete.
    """
    return (
        C.KL_LOAD_AT_TOP_FLANGE
        if load_height is LoadHeight.TOP_FLANGE
        else C.KL_LOAD_AT_SHEAR_CENTRE
    )


def effective_length(seg: Segment) -> float:
    """``l_e = k_t . k_l . k_r . L`` (mm)."""
    return twist_factor(seg) * load_height_factor(seg.load_height) * seg.kr * seg.length


def fully_restrained(length: float, name: str = "") -> Segment:
    """A segment with full restraint at both ends and load at the shear centre.

    The best case, and the one where ``l_e = L`` exactly. Offered as a named
    constructor because it is the arrangement people mean when they say "the
    beam is restrained", and because it is the only one this module can build
    without being told ``k_t``.
    """
    return segment(length, "FF", name=name or "fully restrained")


def continuously_restrained(length: float, name: str = "") -> Segment:
    """A segment whose compression flange is continuously restrained.

    Physically this cannot buckle laterally at all, so the member capacity is
    the section capacity. Represented as a segment of zero effective length by
    convention -- see
    :func:`~austruct.design.as4100.lateral_torsional.member_moment_capacity`,
    which short-circuits to ``M_s``.
    """
    return Segment(
        length=length,
        ends=(Restraint.FULL, Restraint.FULL),
        kt=1.0,
        name=name or "continuously restrained",
    )
