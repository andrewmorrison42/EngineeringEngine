"""AS 3700:2018 constants -- flexure and shear only.

=============================================================================
THIS IS THE FILE TO CHECK AGAINST THE PRINTED STANDARD.
=============================================================================

Every AS 3700 numeric value this package's flexure and shear modules use is
here. As with the rest of this toolkit, every value is tagged ``[VECTOR]``
and every one is currently UNVERIFIED, recorded to the best of the author's
knowledge.

This is a narrower, more heavily SIMPLIFIED slice of AS 3700 than the
``as3600``/``as4100`` packages are of their standards -- see the module
docstrings in ``flexure.py`` and ``shear.py`` for exactly which mechanisms
are simplified and why. Do not treat the flat capacity-reduction factors
below as a substitute for AS 3700 Table 4.4's full dependence on category of
construction and type of action; they are placeholders in the same sense as
everything else on this page.

[UNITS] Stresses MPa, lengths mm.
"""

from __future__ import annotations

from ...core.basis import AS3700_2018, ClauseRef

STANDARD = AS3700_2018

# ---------------------------------------------------------------------------
# CAPACITY REDUCTION FACTORS
#
# AS 3700 Table 4.4 varies phi by category of construction (e.g. Category 1
# vs 2, controlled vs uncontrolled) as well as by action. Flat values are
# used here as a conservative simplification -- confirm the category that
# applies to the actual job and the corresponding phi before issue.
# ---------------------------------------------------------------------------

CLAUSE_PHI = ClauseRef(STANDARD, table="4.4", note="Capacity reduction factors")

PHI_UNREINFORCED_FLEXURE = 0.60
"""phi for unreinforced masonry in bending. [VECTOR] UNVERIFIED."""

PHI_REINFORCED_FLEXURE = 0.75
"""phi for reinforced masonry in bending. [VECTOR] UNVERIFIED."""

PHI_UNREINFORCED_SHEAR = 0.60
"""phi for unreinforced masonry in shear. [VECTOR] UNVERIFIED."""

PHI_REINFORCED_SHEAR = 0.75
"""phi for reinforced masonry in shear. [VECTOR] UNVERIFIED."""

# ---------------------------------------------------------------------------
# FLEXURE -- unreinforced (Cl 7.4, simplified one-way strip)
# ---------------------------------------------------------------------------

CLAUSE_VERTICAL_BENDING = ClauseRef(
    STANDARD, "7.4.2", note="Vertical bending -- tension perpendicular to bed joints"
)
CLAUSE_HORIZONTAL_BENDING = ClauseRef(
    STANDARD, "7.4.3", note="Horizontal bending -- tension parallel to bed joints"
)

FD_MAX_ENHANCEMENT_RATIO = 2.0
"""Design compressive stress fd is credited toward flexural tensile capacity
only up to this multiple of f'mt, to stop an unrealistically high axial load
implying an unbounded flexural capacity from this simplified formula.
[VECTOR] UNVERIFIED -- an implementation safeguard, not a transcribed limit."""

# ---------------------------------------------------------------------------
# FLEXURE -- reinforced (Cl 8.5, simplified rectangular stress block)
# ---------------------------------------------------------------------------

CLAUSE_REINFORCED_FLEXURE = ClauseRef(STANDARD, "8.5", note="Reinforced masonry in bending")

ALPHA_MASONRY = 0.85
"""Stress block intensity factor: compressive stress = ALPHA_MASONRY . f'm
over the stress block depth. [VECTOR] UNVERIFIED -- AS 3700 Cl 8.5 does not
use the same alpha_2/gamma pair as AS 3600; this is a simplified single
factor standing in for it."""

KU_MAX_REINFORCED = 0.36
"""Maximum neutral-axis-depth ratio ku = a/d for ductile behaviour --
borrowed in form from AS 3600 Cl 8.1.5, not a transcribed AS 3700 clause.
[VECTOR] UNVERIFIED, and specifically UNCONFIRMED as an AS 3700 value at
all."""

# ---------------------------------------------------------------------------
# SHEAR -- out-of-plane, one-way (companion to the bending strip above)
#
# [VECTOR] This is NOT AS 3700's in-plane shear-wall (racking) provision --
# see shear.py's module docstring for why that check is out of scope here.
# ---------------------------------------------------------------------------

CLAUSE_SHEAR = ClauseRef(STANDARD, "7.5.4", note="Shear strength of unreinforced masonry")

KV_FRICTION = 0.30
"""Friction-like coefficient kv in v = f'ms + kv.fd. [VECTOR] UNVERIFIED --
typical AS 3700 guidance is in the range 0.3-0.5; the office standard or a
test should confirm."""

SHEAR_STRESS_CAP = 2.0
"""Upper bound on the shear stress v = f'ms + kv.fd, MPa -- a safeguard
against an unrealistically high result at large fd, not a transcribed AS
3700 limit. [VECTOR] UNVERIFIED implementation safeguard."""
