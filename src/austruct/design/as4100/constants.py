"""AS 4100 constants and capacity reduction factors.

=============================================================================
THIS IS THE FILE TO CHECK AGAINST THE PRINTED STANDARD.
=============================================================================

Every number AS 4100 supplies is in this one module. Nothing elsewhere in the
``as4100`` package hard-codes a code value -- they all import from here. Same
arrangement as the AS 3600 and AS 5100.5 packages, and for the same reason:
verifying this package is a single sitting with the book open, not an
archaeology exercise.

Every value is tagged ``[VECTOR]`` and every one is currently UNVERIFIED.

Where the risk is concentrated
------------------------------
Two places, and they are not the obvious ones.

**The plate slenderness limits.** They decide whether a section is compact,
non-compact or slender, which decides ``Z_e``, which scales the moment capacity
directly. A limit in the wrong place does not produce a slightly wrong answer;
it produces a step change, and the step is invisible in the output.

**The member slenderness reduction factor.** ``alpha_s`` and ``alpha_m``
multiply together, so two mistaken factors compound quietly. The expression for
``alpha_s`` in particular has a shape that is easy to half-remember.

[UNITS] MPa, mm, N.
"""

from __future__ import annotations

from ...core.basis import ClauseRef, Standard

STANDARD = Standard(
    code="AS 4100",
    edition=2020,
    title="Steel structures",
)
"""[VECTOR] UNVERIFIED -- confirm the current edition before citing it."""


# ---------------------------------------------------------------------------
# CAPACITY REDUCTION FACTOR -- AS 4100 Table 3.4
# ---------------------------------------------------------------------------

CLAUSE_PHI = ClauseRef(STANDARD, table="3.4", note="Capacity reduction factors")

PHI = 0.9
"""phi for a member in bending, shear, axial compression and axial tension.

AS 4100 uses one value across the structural checks, which is a genuine
difference from AS 3600 where phi varies with the ductility of the failure. A
connection is 0.9 too for most cases but 0.8 for some; connections are not
implemented here.

[BASIS] Table 3.4. [VECTOR] UNVERIFIED."""

PHI_CONNECTION = 0.9
"""phi for a bolted or welded connection component. Not used -- connections are
not implemented. Recorded so the value is not invented at the call site later.
[VECTOR] UNVERIFIED."""


# ---------------------------------------------------------------------------
# SECTION SLENDERNESS -- AS 4100 Section 5.2 and Table 5.2
#
# A plate element's slenderness is
#
#     lambda_e = (b/t) . sqrt(f_y / 250)
#
# and it is compared against a yield limit and a plasticity limit that depend
# on how the element is supported and how it was made. The sqrt(f_y/250) term
# is why a higher grade is MORE prone to local buckling for the same geometry:
# it reaches yield at a stress the plate cannot sustain.
# ---------------------------------------------------------------------------

CLAUSE_SECTION_SLENDERNESS = ClauseRef(STANDARD, "5.2.2", note="Section slenderness")
CLAUSE_PLATE_LIMITS = ClauseRef(STANDARD, table="5.2", note="Plate element slenderness limits")
CLAUSE_ZE = ClauseRef(STANDARD, "5.2.3", note="Effective section modulus")

SLENDERNESS_REFERENCE_FY = 250.0
"""The f_y the slenderness limits are normalised to.
[BASIS] Cl 5.2.2. [VECTOR] UNVERIFIED."""

# Plate element limits, keyed by (element type, residual stress condition).
#
#   "flange outstand"  supported along ONE edge -- a UB or UC flange half
#   "web"              supported along BOTH edges -- the web between flanges
#
# Residual stress condition:
#   "HR"  hot-rolled
#   "HW"  heavily welded
#
# Each entry is (lambda_ep, lambda_ey) -- the plasticity limit and the yield
# limit. Below lambda_ep the element can reach and sustain the plastic moment;
# above lambda_ey it buckles before yield.
#
# [VECTOR] UNVERIFIED -- every pair. These decide the compactness class, which
#          steps the capacity. Check them first.

PLATE_LIMITS: dict[tuple[str, str], tuple[float, float]] = {
    ("flange outstand", "HR"): (9.0, 16.0),
    ("flange outstand", "HW"): (8.0, 14.0),
    ("web", "HR"): (82.0, 115.0),
    ("web", "HW"): (82.0, 115.0),
    ("flange both edges", "HR"): (30.0, 45.0),
    ("flange both edges", "HW"): (30.0, 45.0),
}
"""``(lambda_ep, lambda_ey)`` by element type and residual stress condition.
[BASIS] Table 5.2. [VECTOR] UNVERIFIED -- all of them."""

DEFAULT_RESIDUAL = "HR"
"""Residual stress condition assumed when the caller does not say. Hot-rolled,
which is what a catalogue section is. A welded section must say so -- its
limits are tighter, and defaulting it to HR would be unconservative."""


# ---------------------------------------------------------------------------
# SHEAR -- AS 4100 Section 5.11
# ---------------------------------------------------------------------------

CLAUSE_SHEAR = ClauseRef(STANDARD, "5.11.1", note="Shear capacity")
CLAUSE_SHEAR_YIELD = ClauseRef(STANDARD, "5.11.4", note="Shear yield capacity")
CLAUSE_SHEAR_BUCKLING = ClauseRef(STANDARD, "5.11.5", note="Shear buckling capacity")
CLAUSE_SHEAR_MOMENT = ClauseRef(STANDARD, "5.12.3", note="Combined shear and bending")

SHEAR_YIELD_FACTOR = 0.6
"""V_w = 0.6 . f_y . A_w. The 0.6 is the von Mises shear-to-tension ratio
rounded from 1/sqrt(3) = 0.577.
[BASIS] Cl 5.11.4. [VECTOR] UNVERIFIED."""

WEB_SLENDERNESS_YIELD_LIMIT = 82.0
"""(d_p/t_w) . sqrt(f_y/250) below which the web yields in shear rather than
buckling. [BASIS] Cl 5.11.5. [VECTOR] UNVERIFIED."""

SHEAR_BUCKLING_COEFFICIENT = 82.0
"""alpha_v = [82 / ((d_p/t_w) sqrt(f_y/250))]^2 for a slender unstiffened web.
[BASIS] Cl 5.11.5. [VECTOR] UNVERIFIED -- and specifically UNCONFIRMED whether
the exponent is 2, which is what makes the capacity fall away quickly."""

SHEAR_MOMENT_INTERACTION_THRESHOLD = 0.75
"""Shear below this fraction of phi.V_v does not reduce the moment capacity.
[BASIS] Cl 5.12.3. [VECTOR] UNVERIFIED."""

SHEAR_MOMENT_SLOPE_NUM = 2.2
SHEAR_MOMENT_SLOPE_DEN = 1.6
"""Above the threshold, V_vm = V_v . (2.2 - 1.6 M*/(phi.M_s)).
[BASIS] Cl 5.12.3. [VECTOR] UNVERIFIED -- both coefficients."""


# ---------------------------------------------------------------------------
# MEMBER CAPACITY IN BENDING -- AS 4100 Section 5.6
# ---------------------------------------------------------------------------

CLAUSE_MEMBER_MOMENT = ClauseRef(STANDARD, "5.6.1", note="Member moment capacity")
CLAUSE_REFERENCE_BUCKLING = ClauseRef(STANDARD, "5.6.1.1", note="Reference buckling moment")
CLAUSE_ALPHA_M = ClauseRef(STANDARD, "5.6.1.1(a)", note="Moment modification factor")
CLAUSE_EFFECTIVE_LENGTH = ClauseRef(STANDARD, "5.6.3", note="Effective length")
CLAUSE_RESTRAINT = ClauseRef(STANDARD, "5.4", note="Restraints")

ALPHA_S_CONSTANT = 0.6
"""alpha_s = 0.6 [ sqrt((M_s/M_o)^2 + 3) - (M_s/M_o) ].
[BASIS] Cl 5.6.1.1. [VECTOR] UNVERIFIED -- the 0.6 and the 3."""

ALPHA_S_INNER = 3.0
"""The 3 inside the square root above. [VECTOR] UNVERIFIED."""

ALPHA_M_MAX = 2.5
"""Upper bound on the moment modification factor.
[BASIS] Cl 5.6.1.1(a). [VECTOR] UNVERIFIED."""

ALPHA_M_NUMERATOR = 1.7
"""alpha_m = 1.7 M_max / sqrt(M_2^2 + M_3^2 + M_4^2), with M_2, M_3, M_4 the
moments at the quarter, mid and three-quarter points.
[BASIS] Cl 5.6.1.1(a)(iii). [VECTOR] UNVERIFIED."""

# -- Effective length factors, Cl 5.6.3 ------------------------------------
#
# l_e = k_t . k_l . k_r . L
#
# k_t   twist restraint factor -- how well the ends are held against twisting
# k_l   load height factor -- a load applied at the top flange is destabilising
# k_r   lateral rotation restraint factor -- restraint against minor-axis
#       rotation of the flanges at the ends
#
# [VECTOR] UNVERIFIED -- every value below.

KT_FACTORS: dict[str, float] = {
    "FF": 1.0,
    "FP": 1.0,
    "FL": 1.0,
    "PP": 1.0,
    "PL": 1.0,
    "LL": 1.0,
}
"""k_t by restraint arrangement.

[VECTOR] UNVERIFIED and DELIBERATELY FLAT. The real k_t for partial and
lateral restraint depends on the section geometry and the segment length --
Cl 5.6.3 gives expressions, not a table of constants, and inventing constants
here would be worse than refusing.

:func:`austruct.design.as4100.restraints.twist_factor` raises for anything
other than FF rather than reading a made-up number out of this dict. The dict
exists so the restraint codes have one place to live."""

KL_LOAD_AT_SHEAR_CENTRE = 1.0
KL_LOAD_AT_TOP_FLANGE = 1.4
"""k_l -- the load height factor. A gravity load applied at the TOP flange of a
beam is destabilising: as the beam twists, the load moves outboard and drives
it further. A load at the shear centre does not.

1.4 is the value for a top-flange load on a segment with both ends fully
restrained. [BASIS] Cl 5.6.3. [VECTOR] UNVERIFIED, and note it varies with the
restraint arrangement, which this pair of constants does not capture."""

KR_BOTH_ENDS_UNRESTRAINED = 1.0
KR_ONE_END_RESTRAINED = 0.85
KR_BOTH_ENDS_RESTRAINED = 0.70
"""k_r -- lateral rotation restraint factor. Restraining the flanges against
minor-axis rotation at the ends shortens the effective length.

[BASIS] Cl 5.6.3. [VECTOR] UNVERIFIED. Taking 1.0 (no restraint) is
conservative and is the default."""


# ---------------------------------------------------------------------------
# COMPRESSION -- AS 4100 Section 6
# ---------------------------------------------------------------------------

CLAUSE_COMPRESSION = ClauseRef(STANDARD, "6.1", note="Compression member capacity")
CLAUSE_SECTION_COMPRESSION = ClauseRef(STANDARD, "6.2", note="Section capacity in compression")
CLAUSE_MEMBER_COMPRESSION = ClauseRef(STANDARD, "6.3", note="Member capacity in compression")

COMPRESSION_SLENDERNESS_REFERENCE = 90.0
"""lambda_n = (l_e/r) sqrt(k_f) sqrt(f_y/250), and the column curves are
anchored at 90. [BASIS] Cl 6.3.3. [VECTOR] UNVERIFIED."""

# Member section constant alpha_b, Table 6.3.3(1). Lower is better.
ALPHA_B_VALUES: dict[str, float] = {
    "hot-rolled UB/UC major": 0.0,
    "hot-rolled UB/UC minor": 0.5,
    "hot-rolled channel": 0.5,
    "welded": 0.5,
    "hot-rolled plate": -0.5,
}
"""alpha_b by section type and axis. [BASIS] Table 6.3.3(1).
[VECTOR] UNVERIFIED -- every value, and the categories they attach to."""

ALPHA_B_DEFAULT = 0.5
"""Used when the caller does not nominate one. Mid-range and therefore NOT
conservative in either direction -- state the real one."""

# -- The column curve, Cl 6.3.3 --------------------------------------------
#
# AS 4100 builds alpha_c from a chain of intermediate quantities rather than
# one expression. Written out because a half-remembered chain is worse than
# none:
#
#   alpha_a = 2100 (lambda_n - 13.5) / (lambda_n^2 - 15.3 lambda_n + 2050)
#   lambda  = lambda_n + alpha_a . alpha_b
#   eta     = 0.00326 (lambda - 13.5)          >= 0
#   xi      = [ (lambda/90)^2 + 1 + eta ] / [ 2 (lambda/90)^2 ]
#   alpha_c = xi [ 1 - sqrt( 1 - (90/(xi lambda))^2 ) ]      <= 1.0
#
# [VECTOR] UNVERIFIED -- every coefficient in the chain. They multiply and
#          compound, and no single one is checkable from the result.

ALPHA_A_NUMERATOR = 2100.0
ALPHA_A_OFFSET = 13.5
ALPHA_A_QUAD_B = 15.3
ALPHA_A_QUAD_C = 2050.0
"""alpha_a = 2100 (lam_n - 13.5) / (lam_n^2 - 15.3 lam_n + 2050).
[BASIS] Cl 6.3.3. [VECTOR] UNVERIFIED."""

ETA_COEFFICIENT = 0.00326
ETA_OFFSET = 13.5
"""eta = 0.00326 (lambda - 13.5), not less than zero. The imperfection term:
below lambda = 13.5 a stub column simply squashes and there is no imperfection
to amplify. [BASIS] Cl 6.3.3. [VECTOR] UNVERIFIED."""

LAMBDA_REFERENCE = 90.0
"""The slenderness the column curves are anchored at.
[BASIS] Cl 6.3.3. [VECTOR] UNVERIFIED."""


# ---------------------------------------------------------------------------
# COMBINED ACTIONS -- AS 4100 Section 8
# ---------------------------------------------------------------------------

CLAUSE_COMBINED_SECTION = ClauseRef(STANDARD, "8.3", note="Section capacity, combined actions")
CLAUSE_COMBINED_MEMBER = ClauseRef(STANDARD, "8.4", note="Member capacity, combined actions")

COMBINED_REDUCED_MOMENT_FACTOR = 1.18
"""M_rx = 1.18 M_sx (1 - N*/(phi N_s)) <= M_sx -- the reduced section moment
capacity in the presence of axial force. The 1.18 lets a small axial force be
absorbed without reducing the moment capacity at all, which is why the cap
matters. [BASIS] Cl 8.3.2. [VECTOR] UNVERIFIED."""

COMBINED_MINOR_EXPONENT = 2.0
"""Exponent in the minor-axis interaction. [VECTOR] UNVERIFIED."""


# ---------------------------------------------------------------------------
# SERVICEABILITY
# ---------------------------------------------------------------------------

CLAUSE_DEFLECTION = ClauseRef(STANDARD, "3.5.3", note="Serviceability limit state")

DEFL_TOTAL_SPAN_RATIO = 250.0
DEFL_LIVE_SPAN_RATIO = 360.0
"""Span/250 total and span/360 under imposed action alone. These are
CONVENTIONAL values, not transcribed -- AS 4100 refers deflection limits out to
AS/NZS 1170.0 and to the client's own requirements.
[VECTOR] UNVERIFIED, and arguably not code values at all."""
