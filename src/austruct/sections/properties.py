"""Transformed and cracked section properties.

Gross properties live on :class:`~austruct.sections.primitives.SectionGeometry`
because they are pure geometry. Anything that needs the modular ratio -- and
therefore the materials -- lives here.

These are the properties serviceability work is built on: the cracked second
moment of area feeds deflection, and the cracking moment feeds both the
minimum-reinforcement check and the decision about which stiffness to use.

[UNITS] mm, mm^2, mm^4, MPa.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.basis import AS3600_2018, ClauseRef
from ..core.exceptions import ConvergenceError
from ..core.provenance import ModuleType, Provenance
from ..core.registry import REGISTRY
from .rc_section import RCSection

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
    ),
    description="Transformed and cracked section properties for RC sections",
    envelope_summary="Linear elastic materials; concrete tension ignored when cracked",
)

CLAUSE_CRACKING = ClauseRef(
    AS3600_2018, "8.5.3", note="Cracking moment for deflection calculations"
)


def modular_ratio(section: RCSection) -> float:
    """n = E_s / E_c.

    [ASSUMPTION] Short-term modular ratio. For long-term effects the concrete
                 modulus must be reduced by (1 + creep factor); that is not
                 applied here.
    """
    steel_moduli = {layer.material.Es for layer in section.layers}
    if not steel_moduli:
        raise ValueError("Section has no reinforcement; modular ratio is undefined")
    if len(steel_moduli) > 1:
        raise ValueError(
            "Section mixes reinforcement grades with different Es; "
            "transformed properties need a single modular ratio"
        )
    return steel_moduli.pop() / section.concrete.Ec


@dataclass(frozen=True)
class TransformedProperties:
    """Section properties of an equivalent all-concrete section.

    Attributes
    ----------
    na_depth:
        Neutral axis depth from the extreme compression fibre (mm).
    I:
        Second moment of area about the neutral axis (mm^4), in concrete units.
    area:
        Transformed area (mm^2), in concrete units.
    n:
        Modular ratio used.
    cracked:
        Whether concrete in tension was ignored.
    """

    na_depth: float
    I: float  # noqa: E741 -- I is the standard symbol
    area: float
    n: float
    cracked: bool

    def describe(self) -> list[str]:
        state = "cracked" if self.cracked else "uncracked"
        return [
            f"State      = {state} transformed",
            f"n          = {self.n:.2f}",
            f"d_n        = {self.na_depth:.1f} mm",
            f"A_t        = {self.area:.0f} mm^2",
            f"I          = {self.I:.4g} mm^4",
        ]


def _concrete_second_moment_above(section: RCSection, y: float, about: float) -> float:
    """Second moment of the concrete area above depth ``y``, about ``about``.

    Band-wise parallel axis summation. Exact for banded geometry.

    [UNITS] mm, returns mm^4.
    """
    total = 0.0
    for band in section.geometry.bands:
        if band.y_top >= y:
            break
        top = band.y_top
        bot = min(band.y_bot, y)
        h = bot - top
        if h <= 0:
            continue
        area = band.width * h
        own = band.width * h**3 / 12.0
        arm = 0.5 * (top + bot) - about
        total += own + area * arm**2
    return total


def uncracked_properties(section: RCSection) -> TransformedProperties:
    """Transformed properties with the full concrete section acting.

    Used before the cracking moment is exceeded, and to compute that moment.

    [ASSUMPTION] Concrete acts in tension over the full depth. Steel is
                 transformed by ``(n - 1)`` -- the ``-1`` avoids double-counting
                 the concrete displaced by the bars.
    """
    n = modular_ratio(section)
    geom = section.geometry

    area = geom.area
    first_moment = geom.first_moment_above(geom.D)
    for layer in section.layers:
        extra = (n - 1.0) * layer.area
        area += extra
        first_moment += extra * layer.depth

    na = first_moment / area

    inertia = _concrete_second_moment_above(section, geom.D, na)
    for layer in section.layers:
        inertia += (n - 1.0) * layer.area * (layer.depth - na) ** 2

    return TransformedProperties(na_depth=na, I=inertia, area=area, n=n, cracked=False)


def cracked_properties(
    section: RCSection,
    tol: float = 1e-8,
    max_iter: int = 200,
) -> TransformedProperties:
    """Transformed properties ignoring concrete in tension.

    Solves for the neutral axis by bisection on the first-moment balance::

        Q_concrete(x) + (n-1) * sum(Asc_i * (x - d_i))
                      - n * sum(Ast_j * (d_j - x))  =  0

    Bisection rather than the textbook quadratic because the banded geometry
    makes the concrete term piecewise-quadratic, not quadratic -- a closed form
    would be a per-shape special case, which is exactly what the band
    representation exists to avoid.

    [ASSUMPTION] Linear elastic concrete in compression, no tension stiffening.
    [UNITS] returns mm and mm^4.

    Raises
    ------
    ConvergenceError
        If the neutral axis cannot be bracketed -- which in practice means the
        section has no tensile reinforcement.
    """
    n = modular_ratio(section)
    geom = section.geometry

    def imbalance(x: float) -> float:
        """First moment of the transformed area about the trial neutral axis.

        Zero at the solution. Every term is ``area * (depth - x)`` in the SAME
        sense -- concrete above the axis contributes negatively, steel below it
        positively. Mixing the two senses is easy to do and produces a residual
        that never changes sign, so the bracket fails rather than the answer
        being subtly wrong.
        """
        value = geom.first_moment_above(x) - geom.area_above(x) * x
        for layer in section.layers:
            # (n-1) above the axis avoids double-counting the concrete the bar
            # displaces; n below it, where the concrete is taken as cracked.
            factor = (n - 1.0) if layer.depth <= x else n
            value += factor * layer.area * (layer.depth - x)
        return value

    lo, hi = 1e-6, geom.D
    f_lo, f_hi = imbalance(lo), imbalance(hi)
    if f_lo * f_hi > 0:
        raise ConvergenceError(
            "Cannot bracket the cracked neutral axis. The section most likely "
            "has no reinforcement below the neutral axis.",
            last_value=hi,
        )

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = imbalance(mid)
        if abs(hi - lo) < tol * geom.D:
            break
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    else:
        raise ConvergenceError(
            f"Cracked neutral axis did not converge in {max_iter} iterations",
            last_value=0.5 * (lo + hi),
            iterations=max_iter,
        )

    na = 0.5 * (lo + hi)

    inertia = _concrete_second_moment_above(section, na, na)
    area = geom.area_above(na)
    for layer in section.layers:
        factor = (n - 1.0) if layer.depth <= na else n
        inertia += factor * layer.area * (layer.depth - na) ** 2
        area += factor * layer.area

    return TransformedProperties(na_depth=na, I=inertia, area=area, n=n, cracked=True)


def cracking_moment(section: RCSection, sigma_cs: float = 0.0) -> float:
    """M_cr -- the moment at which flexural cracking initiates.

    Basis
    -----
    AS 3600:2018 Cl 8.5.3::

        M_cr = Z * (f'ct.f - sigma_cs + P/A_g) + P.e

    Parameters
    ----------
    section:
        The RC section. Prestress is not handled -- P and e are taken as zero.
    sigma_cs:
        Maximum shrinkage-induced tensile stress on the uncracked section
        (MPa). Defaults to zero, which is UNCONSERVATIVE for the deflection
        case: shrinkage reduces the cracking moment. Supply a real value for
        serviceability work.

    Returns
    -------
    float
        Cracking moment (N.mm).

    [VECTOR] UNVERIFIED -- confirm the clause form, and in particular whether
             the uncracked TRANSFORMED Z or the gross Z is intended.
    [ASSUMPTION] Uncracked transformed section modulus used. Reinforced
                 (non-prestressed) sections only.
    """
    props = uncracked_properties(section)
    z_tension = props.I / (section.D - props.na_depth)
    return z_tension * max(0.0, section.concrete.fctf - sigma_cs)
