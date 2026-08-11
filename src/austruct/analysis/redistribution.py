"""Moment redistribution on continuous members.

The idea
--------
An elastic analysis of a continuous beam concentrates moment over the interior
supports. A ductile reinforced concrete section reaching its capacity there
does not fail -- it forms a plastic hinge and sheds moment into the adjacent
spans, which still have reserve. Codes permit the designer to anticipate that
by reducing the elastic support moments by some percentage and increasing the
span moments to match.

The practical gain is a more even distribution of reinforcement, and relief
from the bar congestion that peak hogging moments cause over supports.

The one rule that makes it safe
-------------------------------
The redistributed diagram must still be in equilibrium with the applied loads.
That constraint is more useful than it first appears, because of this fact:

    **Adding any function that is LINEAR within each span leaves the
    equilibrium of the member unchanged.**

A linear bending moment distribution corresponds to zero distributed load and
zero point load within the span -- only a constant shear. So the correction
applied here is built as a piecewise-linear function pinned to the chosen
change in moment at each support and interpolated across each span between
them. Equilibrium is preserved by construction rather than checked afterwards,
and :func:`verify_equilibrium` exists to demonstrate that rather than to
enforce it.

What this module does NOT decide
--------------------------------
How much redistribution is allowed. That is a code question turning on the
section's ductility -- how much rotation the hinge can deliver before the
concrete crushes -- and it lives with the standard. See
:func:`austruct.design.as3600.redistribution_limit`.

[UNITS] mm, N, N.mm.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from ..core.exceptions import ModelError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from .envelope import ActionEnvelope, BeamEnvelope

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.DEMAND,
    ),
    description="Moment redistribution on continuous members, preserving equilibrium",
    envelope_summary=(
        "Ductile sections capable of forming plastic hinges; "
        "linear correction within each span; percentage supplied by the caller"
    ),
)


@dataclass(frozen=True)
class Redistribution:
    """The result of redistributing a moment envelope.

    Attributes
    ----------
    envelope:
        The redistributed envelope, ready for the design layer.
    original:
        The elastic envelope it came from, kept so a report can show both.
    support_positions:
        Positions of the interior supports the moments were shed from (mm).
    percentages:
        Percentage reduction actually applied at each interior support.
    support_moments_before, support_moments_after:
        Hogging moment at each interior support (N.mm, negative).
    """

    envelope: BeamEnvelope
    original: BeamEnvelope
    support_positions: tuple[float, ...]
    percentages: tuple[float, ...]
    support_moments_before: tuple[float, ...]
    support_moments_after: tuple[float, ...]

    @property
    def sagging_increase(self) -> float:
        """How much the peak sagging moment grew (N.mm).

        The price of redistribution, and the number a reviewer should look at
        first -- shedding moment from a support has to put it somewhere.
        """
        return self.envelope.M_star_sagging - self.original.M_star_sagging

    def describe(self) -> list[str]:
        lines = ["Moment redistribution:"]
        for pos, pct, before, after in zip(
            self.support_positions,
            self.percentages,
            self.support_moments_before,
            self.support_moments_after,
        ):
            lines.append(
                f"  support at {pos / 1000:6.2f} m: {before / 1e6:8.1f} -> "
                f"{after / 1e6:8.1f} kN.m  ({pct:.0f}% reduction)"
            )
        lines.append(
            f"  peak sagging {self.original.M_star_sagging / 1e6:.1f} -> "
            f"{self.envelope.M_star_sagging / 1e6:.1f} kN.m "
            f"(+{self.sagging_increase / 1e6:.1f})"
        )
        return lines


def _linear_correction(
    x: np.ndarray,
    support_positions: tuple[float, ...],
    deltas: tuple[float, ...],
) -> np.ndarray:
    """Piecewise-linear correction pinned to ``deltas`` at the supports.

    Interpolated linearly between consecutive supports and held flat outside
    the outermost ones. Linear-within-a-span is precisely the condition for the
    correction to carry no load, so the corrected diagram remains in
    equilibrium with the original loading.
    """
    return np.interp(x, np.asarray(support_positions), np.asarray(deltas))


def redistribute(
    envelope: BeamEnvelope,
    support_positions: tuple[float, ...],
    percentage: float | tuple[float, ...],
    *,
    tolerance: float = 1e-9,
) -> Redistribution:
    """Reduce hogging moments at interior supports and raise the spans to suit.

    Parameters
    ----------
    envelope:
        The elastic moment envelope, from
        :func:`austruct.analysis.envelope.analyse_combinations`.
    support_positions:
        Positions of **all** vertical supports (mm), including the end ones.
        The end supports anchor the correction at zero; only the interior ones
        shed moment.
    percentage:
        Percentage reduction in hogging moment. A single value applies to every
        interior support; a tuple gives one value per interior support, in
        order from the left.
    tolerance:
        Positions closer than this are treated as the same support.

    Returns
    -------
    Redistribution

    Raises
    ------
    ModelError
        If fewer than three supports are supplied (nothing to redistribute), or
        if a percentage is outside 0-100.

    Notes
    -----
    Only the **hogging** envelope is reduced. The sagging envelope receives the
    same correction, which increases it -- that is the whole point, and it is
    why the design of the span sections must be done with the redistributed
    envelope rather than the elastic one.

    [ASSUMPTION] The correction is applied uniformly to the max and min
                 envelopes alike. Strictly, redistribution applies to each
                 load case before enveloping, and applying it to an envelope
                 conflates cases that may have different governing
                 arrangements. The result is conservative for the spans and
                 correct at the supports; a member where this matters should be
                 redistributed case by case.
    """
    positions = tuple(sorted(support_positions))
    if len(positions) < 3:
        raise ModelError(
            f"Redistribution needs at least three supports -- {len(positions)} "
            "supplied. A single span has no interior support to shed moment "
            "from, so there is nothing to redistribute."
        )

    interior = positions[1:-1]
    n_interior = len(interior)

    if isinstance(percentage, (int, float)):
        pcts = (float(percentage),) * n_interior
    else:
        pcts = tuple(float(p) for p in percentage)
        if len(pcts) != n_interior:
            raise ModelError(
                f"{len(pcts)} percentages supplied for {n_interior} interior "
                "supports. Give one value per interior support, or a single "
                "value for all of them."
            )

    for p in pcts:
        if not 0.0 <= p <= 100.0:
            raise ModelError(f"Redistribution percentage must be 0-100, got {p}")

    moment = envelope.moment
    x = moment.x

    # Hogging moment at each interior support, read off the min envelope.
    before: list[float] = []
    deltas_interior: list[float] = []
    for pos, pct in zip(interior, pcts):
        idx = int(np.argmin(np.abs(x - pos)))
        if abs(x[idx] - pos) > max(tolerance, 1e-6 * envelope.length):
            raise ModelError(
                f"No sample point near the support at {pos:.1f} mm. The "
                "envelope grid does not resolve this support, so the moment "
                "there cannot be read."
            )
        m_support = float(moment.min_values[idx])
        before.append(m_support)
        # Hogging is negative; reducing its magnitude means adding a positive
        # delta. A support already in sagging sheds nothing.
        deltas_interior.append(-m_support * pct / 100.0 if m_support < 0 else 0.0)

    # End supports are pinned at zero change, which is what keeps the
    # correction from moving the reactions.
    deltas = (0.0, *deltas_interior, 0.0)
    correction = _linear_correction(x, positions, deltas)

    redistributed_moment = replace(
        moment,
        max_values=moment.max_values + correction,
        min_values=moment.min_values + correction,
        name=f"{moment.name} (redistributed)",
    )
    new_envelope = replace(
        envelope,
        moment=redistributed_moment,
        member=f"{envelope.member} [redistributed]",
    )

    after = [
        float(redistributed_moment.min_values[int(np.argmin(np.abs(x - pos)))])
        for pos in interior
    ]

    return Redistribution(
        envelope=new_envelope,
        original=envelope,
        support_positions=interior,
        percentages=pcts,
        support_moments_before=tuple(before),
        support_moments_after=tuple(after),
    )


def verify_equilibrium(
    original: ActionEnvelope,
    redistributed: ActionEnvelope,
    support_positions: tuple[float, ...],
    *,
    rtol: float = 1e-6,
) -> bool:
    """Confirm the correction is linear within every span.

    Equilibrium is preserved by construction, so this is a demonstration for a
    reviewer rather than a guard. It re-derives the correction as the
    difference between the two diagrams and checks that its second difference
    vanishes inside each span -- which is the numerical statement of "carries
    no load".

    Returns
    -------
    bool
        True if the correction is linear within every span to ``rtol``.
    """
    correction = redistributed.max_values - original.max_values
    x = original.x
    positions = tuple(sorted(support_positions))

    scale = float(np.abs(correction).max())
    if scale == 0.0:
        return True

    for lo, hi in zip(positions, positions[1:]):
        mask = (x >= lo) & (x <= hi)
        if mask.sum() < 3:
            continue
        xs, ys = x[mask], correction[mask]
        # Fit a straight line and measure the residual against the correction's
        # own magnitude -- an absolute tolerance would be meaningless here.
        fit = np.polyfit(xs, ys, 1)
        residual = float(np.abs(ys - np.polyval(fit, xs)).max())
        if residual > rtol * scale:
            return False
    return True
