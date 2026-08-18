"""``run_sweep`` -- run any existing check against every named variation.

This is the general-purpose half of the "running variations on a scheme"
workflow: given a base scenario, a list of :class:`~.scheme.Scheme`
overrides, a function that BUILDS the thing being checked, and a function
that CHECKS it, run every scheme, rank the ones that pass, and report the
ones that don't -- or that didn't even build -- rather than crashing on the
first bad row.

Nothing here imports ``design``, ``sections`` or ``materials``. The sweep
engine knows nothing about beams, walls or sections -- it only knows that
whatever ``check`` returns has ``.utilisation`` (float) and ``.passed``
(bool), which every :class:`~austruct.core.contract.CalcResult` in this
package already provides. That is what lets the SAME engine drive an RC
section, a masonry wall, or a retaining wall stability check without a line
of design-domain code in this module -- see ``examples/12_optioneering.py``
for exactly that, across two different domains in one sweep.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .scheme import Scheme


class Checkable(Protocol):
    """The shape :func:`run_sweep` needs from whatever ``check`` returns.
    Every :class:`~austruct.core.contract.CalcResult` already satisfies
    this -- no adapter is needed to sweep an existing design check."""

    @property
    def passed(self) -> bool: ...
    @property
    def utilisation(self) -> float: ...


@dataclass(frozen=True)
class SchemeOutcome:
    """One scheme's result -- or, if it never got that far, its error.

    A scheme that fails to BUILD (bad geometry, an envelope breach) is not
    the same as a scheme that builds but fails a CHECK -- the first is
    recorded with ``error`` set and ``passed``/``utilisation``/``result``
    all ``None``; the second carries a real (failing) result. Both are kept
    in :attr:`SweepResult.outcomes` rather than one silently swallowing the
    other, because "this option is not buildable" is itself information a
    designer needs from a sweep.
    """

    scheme: Scheme
    subject: Any | None
    result: Checkable | None
    cost: float | None
    error: str | None

    @property
    def passed(self) -> bool | None:
        return None if self.result is None else self.result.passed

    @property
    def utilisation(self) -> float | None:
        return None if self.result is None else self.result.utilisation

    def describe(self) -> str:
        if self.error is not None:
            return f"{self.scheme.name:<16} ERROR: {self.error}"
        status = "PASS" if self.passed else "FAIL"
        cost_part = f"  cost {self.cost:,.2f}" if self.cost is not None else ""
        return f"{self.scheme.name:<16} util {self.utilisation:>7.3f}  {status:<4}{cost_part}"


def _rank_key(outcome: SchemeOutcome) -> tuple[int, float]:
    """Sort key: passing schemes first (by cost if given, else utilisation
    ascending -- most spare capacity first), then failing (closest to
    passing first), then errored schemes last of all."""
    if outcome.error is not None:
        return (2, 0.0)
    if outcome.passed:
        return (0, outcome.cost if outcome.cost is not None else outcome.utilisation)
    return (1, outcome.utilisation)


@dataclass(frozen=True)
class SweepResult:
    """Every scheme's outcome, in input order, plus a ranked view."""

    outcomes: tuple[SchemeOutcome, ...]

    @property
    def ranked(self) -> tuple[SchemeOutcome, ...]:
        """Passing schemes first (cheapest, or lowest utilisation if no cost
        function was given), then failing, then errored -- see :func:`_rank_key`."""
        return tuple(sorted(self.outcomes, key=_rank_key))

    @property
    def governing(self) -> SchemeOutcome | None:
        """The best PASSING scheme, or ``None`` if nothing passed."""
        ranked = self.ranked
        return ranked[0] if ranked and ranked[0].passed else None

    @property
    def passing(self) -> tuple[SchemeOutcome, ...]:
        return tuple(o for o in self.outcomes if o.passed)

    @property
    def failing(self) -> tuple[SchemeOutcome, ...]:
        return tuple(o for o in self.outcomes if o.error is None and not o.passed)

    @property
    def errored(self) -> tuple[SchemeOutcome, ...]:
        return tuple(o for o in self.outcomes if o.error is not None)

    def to_rows(self) -> list[dict[str, Any]]:
        """Plain-dict rows -- for a CSV export, a pandas DataFrame, or a
        notebook table, without this module needing an opinion on which."""
        rows = []
        for o in self.outcomes:
            rows.append(
                {
                    "scheme": o.scheme.name,
                    **o.scheme.overrides,
                    "passed": o.passed,
                    "utilisation": o.utilisation,
                    "cost": o.cost,
                    "error": o.error,
                    "notes": o.scheme.notes,
                }
            )
        return rows

    def describe(self, top: int = 10) -> list[str]:
        lines = [
            f"{len(self.outcomes)} scheme(s): {len(self.passing)} passed, "
            f"{len(self.failing)} failed, {len(self.errored)} did not build.",
            "",
        ]
        governing = self.governing
        if governing is None:
            lines.append("No scheme passed.")
        else:
            lines.append(f"Governing: {governing.describe()}")
        if len(self.outcomes) > 1:
            lines.append("")
            lines.append("Ranked:")
            for outcome in self.ranked[:top]:
                lines.append(f"  {outcome.describe()}")
        return lines


def run_sweep(
    schemes: list[Scheme],
    build: Callable[..., Any],
    check: Callable[[Any], Checkable],
    base: dict[str, Any] | None = None,
    cost: Callable[[Any], float] | None = None,
) -> SweepResult:
    """Run ``check(build(**merged_overrides))`` for every scheme.

    Parameters
    ----------
    schemes:
        The variations to run -- see :mod:`.scheme`.
    build:
        Builds the thing being checked from keyword arguments, e.g.
        ``lambda b, D, diameter: rc_beam(b, D, concrete(32), n_bars=4, diameter=diameter)``.
        Any exception here is caught and recorded as that scheme's error --
        a scheme with an impossible geometry does not stop the sweep.
    check:
        Runs the actual design check, e.g. ``lambda section: check_flexure(section, M_star)``.
        Must return something with ``.passed``/``.utilisation`` -- any
        ``CalcResult`` already qualifies. Exceptions here are caught the
        same way as in ``build``.
    base:
        Keyword arguments common to every scheme; each scheme's overrides
        are merged on top (see :meth:`~.scheme.Scheme.merged`).
    cost:
        Optional cost function over the built subject, e.g.
        ``lambda section: section.geometry.area * 180e-9``. When given,
        passing schemes rank by cost ascending; when omitted, they rank by
        utilisation ascending instead (see :func:`_rank_key`).

    Returns
    -------
    SweepResult
    """
    base = base or {}
    outcomes: list[SchemeOutcome] = []

    for scheme in schemes:
        kwargs = scheme.merged(base)
        try:
            subject = build(**kwargs)
        except Exception as exc:  # noqa: BLE001 -- report every failure, don't stop the sweep
            outcomes.append(SchemeOutcome(scheme, None, None, None, error=str(exc)))
            continue

        try:
            result = check(subject)
        except Exception as exc:  # noqa: BLE001
            outcomes.append(SchemeOutcome(scheme, subject, None, None, error=str(exc)))
            continue

        cost_value = cost(subject) if cost is not None else None
        outcomes.append(SchemeOutcome(scheme, subject, result, cost_value, error=None))

    return SweepResult(outcomes=tuple(outcomes))
