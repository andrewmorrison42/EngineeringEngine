"""austruct -- structural engineering toolkit for Australian standards.

Layer map
---------
Modules may import from layers *above* them in this list, never below. That one
rule is what keeps the toolkit composable; breaking it is how a toolkit turns
into a program.

    L0  core        contract, basis, envelope, provenance, units, registry
    L1  materials   concrete, reinforcement, bar catalogue
    L2  sections    geometry primitives, RC sections, section properties
    L3  analysis    beam models, stiffness solver, closed-form cases
    L3b loads       load combinations, AS 5100.2 traffic loads
    L4  design      code checks: as3600/, as5100_5/, over shared rc_common/
    L5  report      the audit artifact

Verification status
-------------------
This package is at v0.1.0 and NO module has been independently verified. Every
constant transcribed from a printed standard is tagged ``[VECTOR]`` in the
source and must be checked against the standard before any output is issued.
Run with ``AUSTRUCT_STRICT=1`` to make unverified modules raise rather than
return numbers -- see :mod:`austruct.core.provenance`.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import analysis, core, design, materials, report, sections
from .core import (
    REGISTRY,
    CalcResult,
    Check,
    ClauseRef,
    Envelope,
    Provenance,
    Value,
    strict_mode,
)

__all__ = [
    "__version__",
    "core",
    "materials",
    "sections",
    "analysis",
    "design",
    "report",
    "CalcResult",
    "Value",
    "Check",
    "ClauseRef",
    "Envelope",
    "Provenance",
    "REGISTRY",
    "strict_mode",
]
