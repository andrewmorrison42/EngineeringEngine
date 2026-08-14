"""Member moment capacity -- lateral-torsional buckling, AS 4100 Section 5.6.

The check that actually governs
-------------------------------
A steel beam bent about its major axis does not usually reach ``M_s``. Before
it gets there the compression flange goes sideways and the section twists, and
the beam fails at a moment that can be a fraction of the section capacity. The
longer the unrestrained length, the worse it gets.

::

    M_b = alpha_m . alpha_s . M_s   <=  M_s

``alpha_s``
    The slenderness reduction factor, from the ratio of the section capacity to
    the elastic buckling moment ``M_o``. This is the part that falls away with
    length.

``alpha_m``
    The moment modification factor. A beam under uniform moment is the worst
    case, because every section along it is at the peak. A beam with a peaked
    diagram is better off -- the highly stressed part is short and is braced by
    the rest. ``alpha_m`` is the credit for that.

Two factors multiplying together is where quiet errors live, which is why both
are reported separately rather than only their product.

alpha_m comes from the real diagram
-----------------------------------
AS 4100 gives ``alpha_m`` in terms of the moments at the quarter, mid and
three-quarter points of the segment::

    alpha_m = 1.7 M_max / sqrt(M_2^2 + M_3^2 + M_4^2)   <= 2.5

Those are exactly what the analysis layer already produces. So
:func:`alpha_m_from_moments` takes them from the solved bending moment diagram
rather than from a table keyed on an idealised load case -- which means a beam
with a real load pattern gets its own ``alpha_m``, not the nearest textbook
one.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] This module is UNVERIFIED. The ``alpha_s`` expression and the 1.7 in
         ``alpha_m`` are the values to check first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_LENGTH, U_MOMENT, U_NONE, kNm
from ...sections.steel_catalogue import CatalogueSection
from . import constants as C
from .flexure import section_moment_capacity
from .restraints import Segment, effective_length

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Lateral-torsional buckling and member moment capacity to AS 4100 Section 5.6",
    envelope_summary=(
        "Doubly symmetric I-sections bent about the major axis; "
        "elastic buckling; no axial force; thin-walled J understates torsional stiffness"
    ),
)


def _envelope(section: CatalogueSection) -> Envelope:
    env = Envelope(name="AS 4100 member moment capacity")
    env.note(
        "The torsion constant J is computed thin-walled and IGNORES THE ROOT "
        "RADII, so it runs 10-30% low for a rolled section. J appears inside "
        "M_o, so the buckling moment is understated and the capacity is "
        "CONSERVATIVE -- but by an amount that varies with the section."
    )
    env.note(
        "Doubly symmetric sections. A channel's shear centre is offset from "
        "its centroid, which changes the buckling behaviour; M_o here does not "
        "account for it."
    )
    env.note("No axial force. See Section 8 for combined actions.")
    env.note(
        "Elastic buckling. The reference moment M_o assumes the member is "
        "elastic up to buckling, which alpha_s then corrects for."
    )
    _ = section
    return env


# ---------------------------------------------------------------------------
# The reference buckling moment
# ---------------------------------------------------------------------------


def reference_buckling_moment(
    section: CatalogueSection,
    le: float,
) -> float:
    """``M_o`` -- the elastic lateral-torsional buckling moment (N.mm).

    ::

        M_o = sqrt[ (pi^2 E I_y / l_e^2) . ( G J + pi^2 E I_w / l_e^2 ) ]

    Two mechanisms resist buckling and the expression multiplies them:

    - **St Venant torsion** ``G J`` -- the section twisting as a whole. Cheap
      for a closed section, poor for an open one, which is why I-beams buckle
      and tubes do not.
    - **Warping torsion** ``pi^2 E I_w / l_e^2`` -- the flanges bending
      sideways in opposite directions. Falls away with length squared, so it
      dominates for short segments and vanishes for long ones.

    The minor-axis stiffness ``I_y`` scales the whole thing, which is why a
    deep narrow beam is so much worse than a shallow wide one.

    Parameters
    ----------
    le:
        Effective length (mm), from
        :func:`~austruct.design.as4100.restraints.effective_length`.
    """
    if le <= 0:
        raise ModelError(f"Effective length must be positive, got {le}")

    props = section.properties
    e = section.grade.E
    g = section.grade.G

    minor = math.pi**2 * e * props.Iy / le**2
    torsion = g * props.J
    warping = math.pi**2 * e * props.Iw / le**2

    return math.sqrt(minor * (torsion + warping))


def slenderness_reduction(Ms: float, Mo: float) -> float:  # noqa: N803
    """``alpha_s`` -- the slenderness reduction factor.

    ::

        alpha_s = 0.6 [ sqrt( (M_s/M_o)^2 + 3 ) - (M_s/M_o) ]

    Bounded by 1.0 above -- the member can never be stronger than its section.

    The shape is worth knowing: as ``M_o`` becomes large relative to ``M_s``
    (a short, stocky, well-restrained segment) the ratio tends to zero and
    ``alpha_s`` tends to ``0.6 sqrt(3) = 1.039``, capped at 1.0. As ``M_o``
    falls away (a long segment) ``alpha_s`` falls with it.
    """
    if Mo <= 0:
        raise ModelError(f"M_o must be positive, got {Mo}")
    ratio = Ms / Mo
    raw = C.ALPHA_S_CONSTANT * (math.sqrt(ratio**2 + C.ALPHA_S_INNER) - ratio)
    return min(1.0, raw)


# ---------------------------------------------------------------------------
# The moment modification factor
# ---------------------------------------------------------------------------


def alpha_m_from_moments(
    M_max: float,  # noqa: N803
    M_quarter: float,  # noqa: N803
    M_mid: float,  # noqa: N803
    M_three_quarter: float,  # noqa: N803
) -> float:
    """``alpha_m`` from the four moments AS 4100 asks for.

    ::

        alpha_m = 1.7 M_max / sqrt(M_2^2 + M_3^2 + M_4^2)   <= 2.5

    Uniform moment gives ``1.7 / sqrt(3) = 0.98``, near enough to 1.0, which is
    the reference case: the whole segment at peak moment, nothing to brace it.
    A peaked diagram gives more, because the highly stressed region is short.

    All four moments are taken as ABSOLUTE values -- the formula is about the
    magnitude of the diagram, not its sign.
    """
    root = math.sqrt(M_quarter**2 + M_mid**2 + M_three_quarter**2)
    if root == 0:
        return 1.0
    return min(C.ALPHA_M_MAX, C.ALPHA_M_NUMERATOR * abs(M_max) / root)


def alpha_m_from_diagram(
    x: np.ndarray,
    moments: np.ndarray,
    start: float,
    end: float,
) -> float:
    """``alpha_m`` read off a solved bending moment diagram.

    This is the integration the analysis layer makes free. The solver already
    produces the moment at every position; the quarter points of a segment are
    just four of them.

    Parameters
    ----------
    x, moments:
        The diagram, as produced by
        :attr:`~austruct.analysis.results.BeamResults.x` and ``.moment``, or by
        an envelope's ``max_values``.
    start, end:
        The segment's extent along the member (mm).

    Returns
    -------
    float

    Notes
    -----
    The peak is taken over the WHOLE segment, not just the four sample points.
    A diagram peaking between the quarter and mid points would otherwise have
    its maximum missed, which would overstate ``alpha_m`` and the capacity.
    """
    if end <= start:
        raise ModelError(f"Segment end ({end}) must exceed start ({start})")

    mask = (x >= start - 1e-9) & (x <= end + 1e-9)
    if not mask.any():
        raise ModelError(
            f"No points of the moment diagram lie in the segment "
            f"{start:.0f} to {end:.0f} mm. Check the segment extent against "
            "the member length."
        )

    length = end - start
    quarter = float(np.interp(start + 0.25 * length, x, moments))
    mid = float(np.interp(start + 0.50 * length, x, moments))
    three_q = float(np.interp(start + 0.75 * length, x, moments))
    peak = float(np.abs(moments[mask]).max())

    return alpha_m_from_moments(peak, quarter, mid, three_q)


# ---------------------------------------------------------------------------
# Member capacity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BucklingState:
    """Everything that went into ``M_b``, kept separate so it can be read."""

    Ms: float  # noqa: N815
    Mo: float  # noqa: N815
    alpha_s: float
    alpha_m: float
    Mb: float  # noqa: N815
    le: float

    @property
    def reduction(self) -> float:
        """``M_b / M_s`` -- how much buckling costs. The headline number."""
        return self.Mb / self.Ms if self.Ms else 0.0

    @property
    def governed_by_section(self) -> bool:
        """Whether the ``M_b <= M_s`` cap bit, i.e. buckling is not critical."""
        return self.Mb >= self.Ms * (1 - 1e-9)

    def describe(self) -> list[str]:
        return [
            f"l_e        = {self.le:.0f} mm",
            f"M_o        = {self.Mo / 1e6:8.1f} kN.m   elastic buckling moment",
            f"M_s        = {self.Ms / 1e6:8.1f} kN.m   section capacity",
            f"alpha_s    = {self.alpha_s:8.3f}   slenderness reduction",
            f"alpha_m    = {self.alpha_m:8.3f}   moment modification",
            f"M_b        = {self.Mb / 1e6:8.1f} kN.m   "
            f"({self.reduction:.0%} of the section capacity)",
        ]


def member_moment_capacity(
    section: CatalogueSection,
    seg: Segment,
    *,
    alpha_m: float = 1.0,
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """``M_b`` -- the member moment capacity of a segment.

    Parameters
    ----------
    section:
        The catalogue section.
    seg:
        The segment, from :mod:`austruct.design.as4100.restraints`.
    alpha_m:
        Moment modification factor. Defaults to 1.0, the uniform-moment case,
        which is the CONSERVATIVE choice -- a real diagram almost always earns
        more. Use :func:`alpha_m_from_diagram` to get the real one.

    Returns
    -------
    CalcResult
        With ``Mb`` and ``phiMb`` as outputs, and ``Mo``, ``alpha_s``,
        ``alpha_m`` as intermediates so a reviewer can see which factor drove
        the answer.
    """
    if alpha_m <= 0:
        raise ModelError(f"alpha_m must be positive, got {alpha_m}")

    result = CalcResult(
        name=name or f"Member moment capacity, AS 4100 -- {section.designation}",
        provenance=PROVENANCE,
        envelope=_envelope(section),
        basis=Basis(
            [C.CLAUSE_MEMBER_MOMENT, C.CLAUSE_REFERENCE_BUCKLING, C.CLAUSE_ALPHA_M]
        ),
    )

    ms = section_moment_capacity(section, "x", residual).get("Ms")
    le = effective_length(seg)
    mo = reference_buckling_moment(section, le)
    a_s = slenderness_reduction(ms, mo)
    mb = min(alpha_m * a_s * ms, ms)

    result.add_input("section", Value(0.0, U_NONE, section.designation, "Section"))
    result.add_input("L", Value(seg.length, U_LENGTH, "L", "Segment length"))
    result.add_input("restraints", Value(0.0, U_NONE, seg.code, "Restraint arrangement"))
    result.add_input(
        "load_height", Value(0.0, U_NONE, seg.load_height.value, "Load height")
    )

    result.add_intermediate("le", Value(le, U_LENGTH, "l_e", "Effective length"))
    result.add_intermediate(
        "Mo", Value(mo, U_MOMENT, "M_o", "Elastic buckling moment", "kN.m", kNm)
    )
    result.add_intermediate(
        "Ms", Value(ms, U_MOMENT, "M_s", "Section moment capacity", "kN.m", kNm)
    )
    result.add_intermediate(
        "alpha_s", Value(a_s, U_NONE, "alpha_s", "Slenderness reduction factor")
    )
    result.add_intermediate(
        "alpha_m", Value(alpha_m, U_NONE, "alpha_m", "Moment modification factor")
    )

    result.add_output(
        "Mb", Value(mb, U_MOMENT, "M_b", "Member moment capacity", "kN.m", kNm)
    )
    result.add_output(
        "phiMb", Value(C.PHI * mb, U_MOMENT, "phi.M_b", "Design capacity", "kN.m", kNm)
    )

    state = BucklingState(Ms=ms, Mo=mo, alpha_s=a_s, alpha_m=alpha_m, Mb=mb, le=le)

    if state.governed_by_section:
        result.note(
            "M_b reaches M_s, so the section capacity governs and buckling is "
            "not critical for this segment."
        )
    else:
        result.note(
            f"Buckling governs: M_b is {state.reduction:.0%} of the section "
            f"capacity. The effective length is {le:.0f} mm."
        )
    if alpha_m == 1.0:
        result.note(
            "alpha_m taken as 1.0, the uniform-moment case. This is "
            "CONSERVATIVE -- a real moment diagram almost always earns more. "
            "Use alpha_m_from_diagram() on the solved bending moment diagram "
            "to claim it."
        )
    result.note(
        "The torsion constant J is thin-walled and ignores the root radii, so "
        "M_o is understated and this capacity is conservative for a rolled "
        "section."
    )
    return result


def check_member_flexure(
    section: CatalogueSection,
    M_star: float,  # noqa: N803
    seg: Segment,
    *,
    alpha_m: float = 1.0,
    residual: str = C.DEFAULT_RESIDUAL,
    name: str = "",
) -> CalcResult:
    """Check ``M*`` against the member capacity, including buckling.

    This is the flexure check for a real beam. Use
    :func:`~austruct.design.as4100.flexure.check_flexure` only where the
    segment is continuously restrained.
    """
    result = member_moment_capacity(
        section, seg, alpha_m=alpha_m, residual=residual, name=name
    )
    result.add_input(
        "M_star", Value(M_star, U_MOMENT, "M*", "Design moment", "kN.m", kNm)
    )
    result.add_check(
        Check(
            label="M* <= phi.M_b",
            actual=abs(M_star),
            limit=result.get("phiMb"),
            operator="<=",
            unit=U_MOMENT,
            display_factor=kNm,
            display_unit="kN.m",
            basis=C.CLAUSE_MEMBER_MOMENT,
        )
    )
    return result


def buckling_state(
    section: CatalogueSection,
    seg: Segment,
    alpha_m: float = 1.0,
    residual: str = C.DEFAULT_RESIDUAL,
) -> BucklingState:
    """The factors alone, without building a report. For sizing loops."""
    ms = section_moment_capacity(section, "x", residual).get("Ms")
    le = effective_length(seg)
    mo = reference_buckling_moment(section, le)
    a_s = slenderness_reduction(ms, mo)
    return BucklingState(
        Ms=ms, Mo=mo, alpha_s=a_s, alpha_m=alpha_m, Mb=min(alpha_m * a_s * ms, ms), le=le
    )
