"""Validity envelope -- the ``envelope`` half of the module contract.

Roadmap Phase 1 requires every module to declare "the validity limits, and an
explicit in/out flag". This module is that mechanism.

The distinction that matters
----------------------------
An **envelope limit** is a bound on the range of application of the calculation
itself: the range of concrete strengths a formula was calibrated over, the
geometry a simplification assumes. Breaching one means the answer is not
merely conservative or unconservative -- it is *unknown*, and the module must
refuse to produce it.

A **design check** is a pass/fail against a code criterion: is the capacity
adequate, is the ductility limit met. Breaching one is a legitimate result that
gets reported as FAIL. See :class:`austruct.core.contract.Check`.

Do not use an Envelope to express a design check. A beam that is overstressed
is a valid calculation with a failing result; a beam of 150 MPa concrete is not
a calculation this toolkit can do at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .basis import ClauseRef
from .exceptions import OutsideEnvelope
from .units import U_NONE


@dataclass(frozen=True)
class Limit:
    """One bound on the validity of a calculation.

    Parameters
    ----------
    name:
        The quantity being bounded, as an engineer would name it, e.g. ``"f'c"``.
    value:
        The actual value supplied.
    lower, upper:
        Inclusive bounds. ``None`` means unbounded on that side.
    unit:
        Unit string for ``value`` and the bounds, from :mod:`austruct.core.units`.
    basis:
        The clause that imposes the limit, where one does. ``None`` where the
        limit is an implementation restriction rather than a code provision --
        which should be stated in ``reason``.
    reason:
        Why the limit exists. Required when ``basis`` is None, so that an
        implementation restriction is never mistaken for a code restriction.
    """

    name: str
    value: float
    lower: float | None = None
    upper: float | None = None
    unit: str = U_NONE
    basis: ClauseRef | None = None
    reason: str = ""

    @property
    def within(self) -> bool:
        """True if ``value`` satisfies both bounds.

        NaN is treated as out of bounds -- a NaN reaching an envelope check
        means something upstream already went wrong, and it must not pass.
        """
        if math.isnan(self.value):
            return False
        if self.lower is not None and self.value < self.lower:
            return False
        if self.upper is not None and self.value > self.upper:
            return False
        return True

    def describe(self) -> str:
        """Human-readable statement of the limit and whether it is met."""
        if self.lower is not None and self.upper is not None:
            rng = f"{self.lower:g} <= {self.name} <= {self.upper:g}"
        elif self.lower is not None:
            rng = f"{self.name} >= {self.lower:g}"
        elif self.upper is not None:
            rng = f"{self.name} <= {self.upper:g}"
        else:
            rng = f"{self.name} unbounded"
        flag = "OK" if self.within else "OUTSIDE"
        return f"{rng} {self.unit}  [actual {self.value:g}]  {flag}"


@dataclass
class Envelope:
    """The set of validity limits for one calculation, with an in/out flag.

    Typical use inside a module::

        env = Envelope("AS 3600 flexure")
        env.add("f'c", fc, lower=20.0, upper=100.0, unit=U_STRESS,
                basis=ClauseRef(AS3600_2018, "1.1.2", note="Range of application"))
        env.require()   # fail closed before any arithmetic happens
    """

    name: str = ""
    limits: list[Limit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(
        self,
        name: str,
        value: float,
        lower: float | None = None,
        upper: float | None = None,
        unit: str = U_NONE,
        basis: ClauseRef | None = None,
        reason: str = "",
    ) -> Limit:
        """Declare a limit and record the value tested against it."""
        limit = Limit(
            name=name,
            value=value,
            lower=lower,
            upper=upper,
            unit=unit,
            basis=basis,
            reason=reason,
        )
        self.limits.append(limit)
        return limit

    def note(self, text: str) -> None:
        """Record a qualitative restriction that is not a numeric bound.

        For example "singly reinforced sections only" or "uniform prismatic
        member assumed". These appear in the report's envelope statement but
        cannot be machine-checked, so they never affect :attr:`within`.
        """
        self.notes.append(text)

    def extend(self, other: Envelope) -> None:
        """Absorb another envelope's limits and notes.

        Used when a design module delegates to a lower layer: the caller's
        envelope must carry the callee's restrictions too, or the composite
        calculation claims a wider validity than it has.
        """
        self.limits.extend(other.limits)
        self.notes.extend(other.notes)

    @property
    def within(self) -> bool:
        """Explicit in/out flag required by the module contract."""
        return all(limit.within for limit in self.limits)

    @property
    def breaches(self) -> list[Limit]:
        """Every limit that is not satisfied, for reporting."""
        return [limit for limit in self.limits if not limit.within]

    def require(self) -> None:
        """Raise :class:`OutsideEnvelope` if any limit is breached.

        This is the fail-closed gate. Call it before the calculation, not after
        -- an out-of-envelope input should never produce a number at all.
        """
        bad = self.breaches
        if not bad:
            return
        detail = "; ".join(limit.describe() for limit in bad)
        label = f" [{self.name}]" if self.name else ""
        raise OutsideEnvelope(
            f"Inputs outside validity envelope{label}: {detail}",
            envelope=self,
        )

    def describe(self) -> list[str]:
        """All limits and notes as report-ready lines."""
        lines = [limit.describe() for limit in self.limits]
        lines.extend(f"NOTE: {n}" for n in self.notes)
        return lines
