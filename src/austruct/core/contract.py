"""The module contract -- the single output shape every calculation returns.

Roadmap Phase 1: "every module, regardless of type, emits inputs / basis /
envelope / outputs / provenance". :class:`CalcResult` is that shape, plus one
addition -- ``checks`` -- because a design calculation's answer is usually a
pass/fail, not a number, and burying that in ``outputs`` loses it.

Why a contract at all
---------------------
The contract is what lets a report renderer, a batch runner, a golden-vector
harness and a future web front end all consume any module without knowing
anything about it. Note the ordering of concerns from the roadmap: the contract
was *extracted* from real modules rather than designed up front. This version
was extracted from the flexure and shear modules in this package; treat it as
provisional until a third unrelated module (a footing, a retaining wall) has
been fitted to it.

Do not return bare floats from a public module function. A float has no units,
no clause reference and no envelope, and every one of those is needed by
someone downstream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .basis import Basis, ClauseRef
from .envelope import Envelope
from .provenance import Provenance
from .units import U_NONE


@dataclass(frozen=True)
class Value:
    """A number with its unit, symbol and meaning attached.

    The unit is a string from :mod:`austruct.core.units` rather than a live
    unit object. That is the deliberate trade recorded in ``units.py``: the
    declaration travels with the number into reports and serialised output,
    without a units library in the solver hot path.

    Parameters
    ----------
    value:
        Magnitude in base units (N, mm, MPa).
    unit:
        Canonical unit string. Use the ``U_*`` constants, not literals.
    symbol:
        Engineering symbol as it appears in the standard, e.g. ``"M_uo"``.
        Used as the row label in reports.
    description:
        Plain-language meaning, for a reader who does not know the symbol.
    display_unit, display_factor:
        Optional presentation override. A moment is stored in N.mm but read in
        kN.m; set ``display_unit="kN.m"`` and ``display_factor=1e6`` and the
        report divides by the factor. Storage is untouched.
    """

    value: float
    unit: str = U_NONE
    symbol: str = ""
    description: str = ""
    display_unit: str = ""
    display_factor: float = 1.0

    @property
    def display(self) -> tuple[float, str]:
        """``(magnitude, unit)`` pair for presentation."""
        if self.display_unit:
            return self.value / self.display_factor, self.display_unit
        return self.value, self.unit

    def __str__(self) -> str:
        mag, unit = self.display
        label = self.symbol or self.description or "value"
        return f"{label} = {mag:.4g} {unit}"

    def __float__(self) -> float:
        return float(self.value)


@dataclass(frozen=True)
class Check:
    """A pass/fail against a design criterion.

    Deliberately general enough to cover all three shapes a code check takes:

    - capacity:   ``M* <= phi.Muo``      -> operator "<="
    - minimum:    ``Ast >= Ast.min``     -> operator ">="
    - ductility:  ``kuo <= 0.36``        -> operator "<="

    A failing Check is a legitimate, reportable result. Contrast with an
    :class:`austruct.core.envelope.Limit`, whose breach means the calculation
    cannot be done at all. See ``envelope.py`` for that distinction.
    """

    label: str
    actual: float
    limit: float
    operator: str = "<="  # "<=" or ">="
    unit: str = U_NONE
    basis: ClauseRef | None = None
    display_factor: float = 1.0
    display_unit: str = ""

    def __post_init__(self) -> None:
        if self.operator not in {"<=", ">="}:
            raise ValueError(f"Check operator must be '<=' or '>=', got {self.operator!r}")

    @property
    def passed(self) -> bool:
        if self.operator == "<=":
            return self.actual <= self.limit
        return self.actual >= self.limit

    @property
    def utilisation(self) -> float:
        """Demand/capacity ratio, always oriented so that >1.0 means FAIL.

        For a ">=" check (e.g. Ast >= Ast.min) the ratio is inverted so that
        utilisation reads the same way everywhere. Returns ``inf`` where the
        denominator is zero and the check fails, ``0.0`` where it passes.
        """
        num, den = (self.actual, self.limit) if self.operator == "<=" else (self.limit, self.actual)
        if den == 0:
            return 0.0 if num == 0 else float("inf")
        return num / den

    def describe(self) -> str:
        f = self.display_factor
        unit = self.display_unit or self.unit
        status = "PASS" if self.passed else "FAIL"
        return (
            f"{self.label}: {self.actual / f:.4g} {self.operator} "
            f"{self.limit / f:.4g} {unit}  "
            f"(utilisation {self.utilisation:.3f})  {status}"
        )


@dataclass
class CalcResult:
    """The one output shape. Every public calculation returns one of these.

    Attributes
    ----------
    name:
        What was calculated, e.g. "Ultimate moment capacity, AS 3600".
    inputs:
        Echoed verbatim with units declared, per the roadmap contract. Echoed
        means echoed -- do not normalise, round or reinterpret them here.
    basis:
        Clause references, in application order.
    envelope:
        Validity limits with an explicit in/out flag.
    outputs:
        Results with units.
    checks:
        Pass/fail criteria. May be empty for a pure property calculation.
    provenance:
        Module version, author, checker, vector status, run timestamp.
    intermediates:
        Working values a reviewer needs to follow the arithmetic but which are
        not results in their own right -- the lever arm, the neutral axis
        depth. Kept separate so ``outputs`` stays the answer, not the working.
    """

    name: str
    provenance: Provenance
    inputs: dict[str, Value] = field(default_factory=dict)
    basis: Basis = field(default_factory=Basis)
    envelope: Envelope = field(default_factory=Envelope)
    outputs: dict[str, Value] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    intermediates: dict[str, Value] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)

    # -- construction helpers -------------------------------------------------
    # These exist so module code reads as engineering rather than as dict
    # manipulation. Each returns the Value so it can be used inline.

    def add_input(self, key: str, value: Value) -> Value:
        self.inputs[key] = value
        return value

    def add_output(self, key: str, value: Value) -> Value:
        self.outputs[key] = value
        return value

    def add_intermediate(self, key: str, value: Value) -> Value:
        self.intermediates[key] = value
        return value

    def add_check(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    def note(self, text: str) -> None:
        """Record a message for the reader -- an assumption taken, a branch of
        the code taken, a conservative simplification applied."""
        self.messages.append(text)

    # -- interrogation --------------------------------------------------------

    @property
    def passed(self) -> bool:
        """True if every check passes AND the envelope is satisfied.

        Envelope is included because a result computed outside its validity
        range must never read as a pass, even if the arithmetic came out
        favourably.
        """
        return self.envelope.within and all(c.passed for c in self.checks)

    @property
    def critical_check(self) -> Check | None:
        """The check with the highest utilisation, or None if there are none."""
        return max(self.checks, key=lambda c: c.utilisation, default=None)

    @property
    def utilisation(self) -> float:
        """Governing utilisation across all checks. 0.0 if there are none."""
        crit = self.critical_check
        return crit.utilisation if crit else 0.0

    def get(self, key: str) -> float:
        """Raw magnitude of an output, in base units.

        Convenience for chaining modules together, where the next module wants
        a float and the ceremony of unwrapping a Value adds nothing.
        """
        if key in self.outputs:
            return self.outputs[key].value
        if key in self.intermediates:
            return self.intermediates[key].value
        raise KeyError(f"{key!r} is not an output or intermediate of {self.name!r}")

    # -- serialisation --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form of the contract, for JSON, YAML or a report engine.

        This is the interoperability surface. A consumer that can read this
        dict can consume any module in the catalog without importing austruct.
        """

        def vals(d: dict[str, Value]) -> dict[str, Any]:
            return {
                k: {
                    "value": v.value,
                    "unit": v.unit,
                    "symbol": v.symbol,
                    "description": v.description,
                }
                for k, v in d.items()
            }

        return {
            "name": self.name,
            "inputs": vals(self.inputs),
            "basis": [
                {
                    "citation": r.citation,
                    "note": r.note,
                    "library_key": r.library_key,
                }
                for r in self.basis
            ],
            "envelope": {
                "within": self.envelope.within,
                "limits": [
                    {
                        "name": lim.name,
                        "value": lim.value,
                        "lower": lim.lower,
                        "upper": lim.upper,
                        "unit": lim.unit,
                        "within": lim.within,
                        "basis": lim.basis.citation if lim.basis else None,
                        "reason": lim.reason,
                    }
                    for lim in self.envelope.limits
                ],
                "notes": self.envelope.notes,
            },
            "outputs": vals(self.outputs),
            "intermediates": vals(self.intermediates),
            "checks": [
                {
                    "label": c.label,
                    "actual": c.actual,
                    "limit": c.limit,
                    "operator": c.operator,
                    "unit": c.unit,
                    "passed": c.passed,
                    "utilisation": c.utilisation,
                    "basis": c.basis.citation if c.basis else None,
                }
                for c in self.checks
            ],
            "provenance": {
                "module": self.provenance.module,
                "version": self.provenance.version,
                "author": self.provenance.author,
                "module_type": self.provenance.module_type.value,
                "status": self.provenance.status.value,
                "checker": self.provenance.checker,
                "checked_on": (
                    self.provenance.checked_on.isoformat()
                    if self.provenance.checked_on
                    else None
                ),
                "vectors": [str(v) for v in self.provenance.vectors],
                "run_at": self.provenance.run_at.isoformat(timespec="seconds"),
                "issuable": self.provenance.issuable,
            },
            "messages": self.messages,
            "passed": self.passed,
            "utilisation": self.utilisation,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"<CalcResult {self.name!r} {status} util={self.utilisation:.3f}>"
