"""Serviceability mechanics shared by AS 3600 and AS 5100.5.

What belongs here
-----------------
The *mechanics* of a cracked reinforced section under service load: where the
neutral axis sits, what stress the steel carries, and how much stiffness the
member retains once it has cracked. None of that is standard-specific -- both
codes use the same cracked-transformed-section model and the same
Branson-family interpolation for effective stiffness.

What does NOT belong here
-------------------------
The coefficients. The exponent in the interpolation, the cap on ``I_ef``, the
creep multiplier and every deflection limit are code values, and they live in
the ``constants.py`` of the standard that supplies them. This module takes them
as arguments so that the same mechanics can serve two standards without either
one's numbers leaking into the other's answers.

Why serviceability is not a smaller version of strength
-------------------------------------------------------
Strength design asks one question at one instant. Serviceability asks what the
member does over fifty years, and the answer depends on load *history*: which
part of the load is sustained, whether the member has ever been cracked by a
transient overload, and how much creep and shrinkage have accumulated. The
functions here take the sustained and transient parts separately for exactly
that reason -- collapsing them into one "service load" silently discards the
distinction the long-term multiplier is applied to.

[UNITS] N, mm, MPa. Moments N.mm, second moments mm^4, stresses MPa.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance
from ...core.registry import REGISTRY
from ...sections.properties import (
    TransformedProperties,
    cracked_properties,
    cracking_moment,
    uncracked_properties,
)
from ...sections.rc_section import RCSection

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
    ),
    description="Cracked-section serviceability mechanics shared by both standards",
    envelope_summary="Linear elastic materials, plane sections, no tension stiffening in I_cr",
)


# ---------------------------------------------------------------------------
# Cracked-section state under a service moment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceState:
    """What a section is doing under one service moment.

    Attributes
    ----------
    M_s:
        The service moment this state describes (N.mm).
    M_cr:
        Cracking moment (N.mm).
    cracked:
        Whether ``M_s`` exceeds ``M_cr``. Note this is a statement about *this*
        moment only -- see :func:`effective_second_moment` for why the peak
        moment ever applied is the one that matters.
    I_uncracked, I_cracked:
        Transformed second moments in the two states (mm^4).
    I_ef:
        Effective second moment to use for deflection (mm^4).
    steel_stress:
        Tensile steel stress at the outermost layer (MPa). Computed on the
        cracked section, which is the basis both codes' crack-control rules
        assume, even where ``M_s < M_cr``.
    na_depth:
        Cracked neutral axis depth (mm).
    """

    M_s: float
    M_cr: float
    cracked: bool
    I_uncracked: float
    I_cracked: float
    I_ef: float
    steel_stress: float
    na_depth: float

    @property
    def stiffness_retained(self) -> float:
        """``I_ef / I_uncracked`` -- the fraction of gross stiffness remaining.

        A quick sanity read for a reviewer: 1.0 means uncracked, and values
        below about 0.3 mean the member is heavily cracked and the deflection
        estimate is sensitive to every assumption feeding it.
        """
        return self.I_ef / self.I_uncracked if self.I_uncracked else 0.0

    def describe(self) -> list[str]:
        state = "CRACKED" if self.cracked else "uncracked"
        return [
            f"M_s        = {self.M_s / 1e6:.1f} kN.m",
            f"M_cr       = {self.M_cr / 1e6:.1f} kN.m   -> {state}",
            f"d_n        = {self.na_depth:.1f} mm",
            f"I_uncr     = {self.I_uncracked:.4g} mm^4",
            f"I_cr       = {self.I_cracked:.4g} mm^4",
            f"I_ef       = {self.I_ef:.4g} mm^4  ({self.stiffness_retained:.0%} of uncracked)",
            f"f_s        = {self.steel_stress:.1f} MPa",
        ]


def service_steel_stress(
    section: RCSection,
    M_s: float,  # noqa: N803
    props: TransformedProperties | None = None,
) -> float:
    """Tensile stress in the outermost steel layer under a service moment.

    On the cracked transformed section::

        f_s = n . M_s . (d_o - d_n) / I_cr

    Parameters
    ----------
    section:
        The RC section.
    M_s:
        Service moment (N.mm), positive sagging.
    props:
        Pre-computed cracked properties, to avoid re-solving the neutral axis
        in a loop. Computed here when omitted.

    Returns
    -------
    float
        Steel stress (MPa). Zero for zero moment; never negative -- a negative
        result would mean the outermost "tensile" layer is in compression,
        which means the caller has passed a moment of the wrong sign.

    [ASSUMPTION] No tension stiffening. The concrete between cracks carries
                 some tension in reality, so the true average steel stress is
                 lower than this. Using the bare cracked section is the
                 conservative and conventional choice for crack control.
    """
    if M_s == 0.0:
        return 0.0
    props = props or cracked_properties(section)
    lever = section.d_o - props.na_depth
    if lever <= 0:
        raise ModelError(
            f"The outermost steel layer at d_o = {section.d_o:.0f} mm lies above "
            f"the cracked neutral axis at {props.na_depth:.0f} mm. That layer is "
            "in compression, so it has no crack-control stress. Check the sign "
            "of the moment and which face is in tension."
        )
    return max(0.0, props.n * abs(M_s) * lever / props.I)


def effective_second_moment(
    section: RCSection,
    M_s_max: float,  # noqa: N803
    *,
    exponent: float,
    ief_max: float,
    sigma_cs: float = 0.0,
    props_cracked: TransformedProperties | None = None,
    props_uncracked: TransformedProperties | None = None,
) -> ServiceState:
    """Effective second moment of area by Branson-family interpolation.

        I_ef = I_cr + (I - I_cr) . (M_cr / M_s)^n     bounded above by I_ef.max

    Parameters
    ----------
    section:
        The RC section.
    M_s_max:
        The **maximum** service moment the member has ever carried at this
        section (N.mm) -- not the moment currently acting.

        This distinction is the one most often got wrong. Cracking is
        irreversible: a beam cracked by a transient live load does not recover
        its uncracked stiffness when that load is removed. So the stiffness
        used for the *sustained* deflection must be the stiffness left behind
        by the *peak* load. Passing the sustained moment here overestimates
        stiffness and underestimates long-term deflection.
    exponent:
        Interpolation exponent, supplied by the calling standard.
    ief_max:
        Upper bound on ``I_ef`` (mm^4), supplied by the calling standard.
        Both codes reduce this cap for lightly reinforced sections.
    sigma_cs:
        Shrinkage-induced tensile stress on the uncracked section (MPa).
        Reduces ``M_cr``. Defaults to zero, which is UNCONSERVATIVE.
    props_cracked, props_uncracked:
        Pre-computed properties, to avoid re-solving in a loop.

    Returns
    -------
    ServiceState

    [ASSUMPTION] One ``I_ef`` for the whole member, computed at the section of
                 maximum moment. Both codes permit this; a member whose section
                 changes along its length needs the region-by-region treatment
                 instead, which this function does not do.
    """
    cracked = props_cracked or cracked_properties(section)
    uncracked = props_uncracked or uncracked_properties(section)
    m_cr = cracking_moment(section, sigma_cs=sigma_cs)
    m_s = abs(M_s_max)

    if m_s <= m_cr or m_s == 0.0:
        # Uncracked. The interpolation would give (M_cr/M_s)^n > 1 here, which
        # is why it is bounded rather than evaluated.
        i_ef = min(uncracked.I, ief_max)
        is_cracked = False
    else:
        ratio = m_cr / m_s
        i_ef = cracked.I + (uncracked.I - cracked.I) * ratio**exponent
        i_ef = min(i_ef, ief_max)
        is_cracked = True

    # I_ef can never fall below the fully cracked value -- a cap set below
    # I_cr would otherwise produce a member softer than its own cracked
    # section, which is not physical.
    i_ef = max(i_ef, cracked.I)

    return ServiceState(
        M_s=m_s,
        M_cr=m_cr,
        cracked=is_cracked,
        I_uncracked=uncracked.I,
        I_cracked=cracked.I,
        I_ef=i_ef,
        steel_stress=service_steel_stress(section, m_s, cracked),
        na_depth=cracked.na_depth,
    )


def creep_multiplier(
    section: RCSection,
    *,
    intercept: float,
    slope: float,
    minimum: float,
) -> float:
    """Long-term deflection multiplier ``k_cs`` from the compression steel ratio.

        k_cs = intercept - slope . (A_sc / A_st)  >=  minimum

    Compression reinforcement restrains creep, so a doubly reinforced section
    creeps less. The coefficients come from the calling standard.

    [ASSUMPTION] ``A_sc`` and ``A_st`` are taken at the section supplied, by
                 the section's default centroid split. For a continuous member
                 the ratio differs between span and support, and the standard
                 intends the value at the section being checked.
    """
    ast = section.Ast
    if ast <= 0:
        raise ModelError("k_cs needs tensile reinforcement; this section has none")
    return max(minimum, intercept - slope * (section.Asc / ast))


def long_term_deflection(
    delta_sustained_immediate: float,
    delta_transient: float,
    kcs: float,
) -> dict[str, float]:
    """Combine immediate and creep deflections.

        delta_total = delta_transient + (1 + k_cs) . delta_sustained_immediate

    Parameters
    ----------
    delta_sustained_immediate:
        Immediate deflection under the sustained load (mm) -- dead load plus
        the sustained fraction psi_l . Q of the live load.
    delta_transient:
        Immediate deflection under the non-sustained remainder of the live
        load (mm).
    kcs:
        Creep multiplier from :func:`creep_multiplier`.

    Returns
    -------
    dict
        ``immediate``, ``creep``, ``total``. Returned as parts rather than a
        single number because a reviewer checking a deflection wants to see
        which part dominates -- and because the incremental limit applies to
        everything after the brittle finishes went on, which is a different
        combination of the same parts.
    """
    creep = kcs * delta_sustained_immediate
    immediate = delta_sustained_immediate + delta_transient
    return {
        "immediate": immediate,
        "creep": creep,
        "total": immediate + creep,
    }


def scale_deflection_for_stiffness(
    delta_gross: float,
    I_gross: float,  # noqa: N803
    I_ef: float,  # noqa: N803
) -> float:
    """Rescale a deflection computed on one stiffness to another.

    An elastic deflection is inversely proportional to ``EI``, so a single
    analysis run on the gross section can be corrected to the effective
    section without re-solving::

        delta_ef = delta_gross . I_gross / I_ef

    This is exact for a prismatic member, which is the case the ``I_ef``
    provisions themselves assume.

    [ASSUMPTION] Prismatic, and one stiffness for the whole span. A member with
                 a genuinely varying ``I_ef`` along its length must be
                 re-analysed with that variation rather than scaled.
    """
    if I_ef <= 0:
        raise ModelError(f"I_ef must be positive, got {I_ef}")
    return delta_gross * I_gross / I_ef
