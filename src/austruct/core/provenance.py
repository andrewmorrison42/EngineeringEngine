"""Provenance -- the block that makes a module reusable by someone who did not
write it.

Roadmap Phase 1 is explicit that this matters more than the schema types, and
Phase 3 makes it enforceable: *no module enters the catalog without golden
vectors and a named checker*. This module holds the machinery for both.

The verification stance
-----------------------
Numeric values transcribed from a printed standard are the highest-consequence,
lowest-visibility failure mode in a toolkit like this. A wrong capacity
reduction factor produces plausible numbers forever.

So every module declares a :class:`VerificationStatus`, and it starts at
``UNVERIFIED``. Promoting it requires a named engineer and a date. Setting
``strict_mode(True)`` makes any use of an unverified module raise -- that is the
setting a production or issued-calculation configuration should run with, and
the setting that stops a draft module quietly ending up on a drawing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

from .exceptions import UnverifiedConstant


class VerificationStatus(str, Enum):
    """Where a module sits against the Phase 3 verification spine."""

    UNVERIFIED = "UNVERIFIED"
    """Written, not yet checked against any external source. Not for issue."""

    SELF_CHECKED = "SELF_CHECKED"
    """Author has checked it against a source. No independent checker yet."""

    VERIFIED = "VERIFIED"
    """Golden vectors pass and a named engineer other than the author signed off."""

    FAILED = "FAILED"
    """Vectors previously passed and now do not. Pulled from the catalog."""

    SUPERSEDED = "SUPERSEDED"
    """Standard revised; retained only to reproduce previously issued outputs."""


class ModuleType(str, Enum):
    """Roadmap Phase 0 classification. Drives the review model, not the code.

    Recorded here so the module register can report the mix, and so that a
    reviewer knows what kind of scrutiny an output needs before trusting it.
    """

    A_TABULATED = "A"  # Design once, publish a lookup table + validity envelope
    B_PER_JOB = "B"  # Design per job, calc with audit trail, per-job sign-off
    C_GEOMETRY = "C"  # Geometry generation, envelope certified once
    D_EXTRACTION = "D"  # Extraction & scheduling, reconciliation checks


class ASETComponent(str, Enum):
    """Which of the six ASET components a module belongs to.

    From Connor Ferster, *The Anatomy of Your Automated Structural Engineering
    Toolkit* (2025). The six components are a framework for seeing where each
    tool sits in the whole, which is what makes building one out "manageable,
    coherent, and most importantly, actionable".

    Recorded per module so that :meth:`ModuleRegistry.coverage` can report which
    components are built out and which are still thin -- the register answers
    "what have we actually got?" rather than only "what have we verified?".
    """

    REFERENCE_DATA = "1"
    """Static data you look up. Loadable and queryable in one or two calls."""

    PROJECT_DATA = "2"
    """Client-supplied information, and what is derived from it."""

    DEMAND = "3"
    """Fast demand calculation -- pre-processing, analysis, post-processing and
    enveloping of results, in a form that permits fast design iteration."""

    DESIGN_DOCUMENTATION = "4"
    """Plain-text formats describing design decisions -- human AND machine
    readable, so a schedule can be reviewed by an engineer and consumed by a
    program without being written twice."""

    VERIFICATION = "5"
    """Capacity determination and the comparison of demand against capacity,
    coordinating input data across the other domains."""

    REPORTING = "6"
    """Generation of documents and drawings for record or deliverable."""

    INFRASTRUCTURE = "0"
    """Not one of the six. The cross-cutting contract that lets components 1-6
    exchange data -- what component 5 calls "an over-arching structure to
    coordinate the retrieval of information from the multiple domains"."""


ASET_COMPONENT_NAMES: dict[ASETComponent, str] = {
    ASETComponent.INFRASTRUCTURE: "Infrastructure (cross-cutting)",
    ASETComponent.REFERENCE_DATA: "Reference data",
    ASETComponent.PROJECT_DATA: "Project data",
    ASETComponent.DEMAND: "Fast demand calculation",
    ASETComponent.DESIGN_DOCUMENTATION: "Design documentation",
    ASETComponent.VERIFICATION: "Design verification",
    ASETComponent.REPORTING: "Reporting and documentation",
}


# ---------------------------------------------------------------------------
# Strict mode. Process-wide, deliberately -- this is a deployment posture, not
# a per-call option, and making it per-call invites it being switched off at
# the one call site that mattered.
# ---------------------------------------------------------------------------

_STRICT = os.environ.get("AUSTRUCT_STRICT", "").lower() in {"1", "true", "yes"}


def strict_mode(enabled: bool | None = None) -> bool:
    """Get or set strict mode.

    In strict mode, constructing a :class:`Provenance` whose status is
    ``UNVERIFIED`` or ``FAILED`` raises :class:`UnverifiedConstant`.

    Can also be set at process start with the ``AUSTRUCT_STRICT`` environment
    variable, which is how it should be set in any environment that issues
    calculations.
    """
    global _STRICT
    if enabled is not None:
        _STRICT = bool(enabled)
    return _STRICT


@dataclass(frozen=True)
class GoldenVector:
    """One benchmark case, and who stands behind it.

    Roadmap Phase 3: "Every module ships with benchmark cases checked against
    the legacy spreadsheet, a published worked example, or a hand calc. Each
    case names the engineer who verified it and the date."

    Parameters
    ----------
    case_id:
        Stable identifier, referenced from the vector YAML files.
    source:
        Where the expected answer came from. Be specific enough that someone
        can go and find it: "Warner et al. Example 3.4", "BLW spreadsheet
        rev C tab 'Flexure' row 42", not "hand calc".
    checked_by:
        Engineer who verified it. Not the author of the module.
    checked_on:
        Date of that verification.
    tolerance:
        Relative tolerance the comparison passes at. Recorded because a vector
        passing at 5% and one passing at 0.01% carry different weight.
    """

    case_id: str
    source: str
    checked_by: str
    checked_on: date
    tolerance: float = 1e-6

    def __str__(self) -> str:
        return (
            f"{self.case_id}: {self.source} "
            f"(checked by {self.checked_by}, {self.checked_on.isoformat()}, "
            f"tol {self.tolerance:g})"
        )


@dataclass(frozen=True)
class Provenance:
    """Who wrote this, who checked it, what version, and when it ran.

    Every :class:`austruct.core.contract.CalcResult` carries one.
    """

    module: str
    """Dotted module path, e.g. ``austruct.design.as3600.flexure``."""

    version: str
    """Semantic version of the *module*, independent of the package version.

    Governance minimum from the roadmap. Bump the minor when behaviour changes
    in a way that could change an issued number; bump the patch for anything
    that provably cannot.
    """

    author: str
    module_type: ModuleType = ModuleType.B_PER_JOB
    component: ASETComponent = ASETComponent.VERIFICATION
    """Which of the six ASET components this module belongs to."""

    status: VerificationStatus = VerificationStatus.UNVERIFIED
    checker: str | None = None
    checked_on: date | None = None
    vectors: tuple[GoldenVector, ...] = ()
    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = ""

    def __post_init__(self) -> None:
        # [CHECK] Fail closed in strict mode rather than producing an
        #         unverifiable number. See module docstring.
        if _STRICT and self.status in {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.FAILED,
        }:
            raise UnverifiedConstant(
                f"Module '{self.module}' has verification status "
                f"{self.status.value} and strict mode is enabled. "
                "Verify the module and record a named checker, or disable "
                "strict mode for development use."
            )
        # [CHECK] VERIFIED is a claim about a person, so require the person.
        if self.status is VerificationStatus.VERIFIED and not self.checker:
            raise ValueError(
                f"Module '{self.module}' claims VERIFIED status without a named "
                "checker. Phase 3 rule: no module enters the catalog without "
                "golden vectors and a named checker."
            )

    @property
    def issuable(self) -> bool:
        """Whether output from this module may go into an issued document."""
        return self.status is VerificationStatus.VERIFIED

    def describe(self) -> list[str]:
        """Report-ready provenance lines."""
        lines = [
            f"Module:      {self.module} v{self.version}",
            f"Type:        {self.module_type.value} ({self.module_type.name})",
            f"ASET:        {self.component.value} -- {ASET_COMPONENT_NAMES[self.component]}",
            f"Author:      {self.author}",
            f"Status:      {self.status.value}",
        ]
        if self.checker:
            on = self.checked_on.isoformat() if self.checked_on else "date not recorded"
            lines.append(f"Checked by:  {self.checker} ({on})")
        else:
            lines.append("Checked by:  NOT CHECKED")
        lines.append(f"Vectors:     {len(self.vectors)} registered")
        lines.append(f"Run at:      {self.run_at.isoformat(timespec='seconds')}")
        if not self.issuable:
            lines.append(
                "WARNING:     This module is not verified for issue. "
                "Results are for development use only."
            )
        return lines
