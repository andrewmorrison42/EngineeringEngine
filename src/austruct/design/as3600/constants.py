"""AS 3600:2018 constants and capacity reduction factors.

=============================================================================
THIS IS THE FILE TO CHECK AGAINST THE PRINTED STANDARD.
=============================================================================

Every number AS 3600 supplies is in this one module. Nothing elsewhere in the
``as3600`` package hard-codes a code value -- they all import from here. That
is deliberate: verifying this package against the standard is a single sitting
with this file open beside the book, not an archaeology exercise across a
dozen modules.

Every value is tagged ``[VECTOR]`` and every one is currently UNVERIFIED. The
values are recorded here to the best of the author's knowledge; they must be
confirmed against AS 3600:2018 (including current amendments) and the
verification recorded with a named engineer and a date before any output of
this package is issued.

[UNITS] Stresses MPa, lengths mm, angles stored in radians via ``deg()``.
"""

from __future__ import annotations

import math

from ...core.basis import AS3600_2018, ClauseRef
from ...core.units import deg
from ...materials.reinforcement import Ductility

STANDARD = AS3600_2018

# ---------------------------------------------------------------------------
# CAPACITY REDUCTION FACTORS -- AS 3600:2018 Table 2.2.2
# ---------------------------------------------------------------------------
# [VECTOR] UNVERIFIED. Check every value and every bound in Table 2.2.2.
#          A wrong phi is the single highest-consequence error in this package:
#          it is invisible in the output and scales every capacity.

CLAUSE_PHI = ClauseRef(STANDARD, table="2.2.2", note="Capacity reduction factors")

PHI_SHEAR = 0.70
"""phi for shear. [VECTOR] UNVERIFIED."""

PHI_TORSION = 0.70
"""phi for torsion. [VECTOR] UNVERIFIED. Not used yet."""

PHI_BEARING = 0.60
"""phi for bearing. [VECTOR] UNVERIFIED. Not used yet."""

# Flexure without axial tension -- phi varies with k_uo, rewarding ductility.
PHI_FLEXURE_INTERCEPT = 1.19
PHI_FLEXURE_SLOPE = 13.0 / 12.0
"""phi = 1.19 - (13/12).k_uo, bounded by the limits below.
[VECTOR] UNVERIFIED -- both coefficients."""

PHI_FLEXURE_MIN = 0.60
PHI_FLEXURE_MAX_CLASS_N = 0.85
PHI_FLEXURE_MAX_CLASS_L = 0.64
"""Upper bound on phi for flexure. Class L reinforcement attracts a
substantially lower cap. [VECTOR] UNVERIFIED -- all three bounds."""


def phi_flexure(kuo: float, ductility: Ductility = Ductility.N) -> float:
    """Capacity reduction factor for bending without axial tension.

    Basis
    -----
    AS 3600:2018 Table 2.2.2.

    ``phi = 1.19 - (13/12).k_uo``, bounded below by 0.60 and above by 0.85 for
    Class N reinforcement, or 0.64 for Class L.

    [VECTOR] UNVERIFIED -- expression and all bounds.

    Parameters
    ----------
    kuo:
        Ratio of the neutral axis depth to ``d_o``, the depth to the centroid
        of the OUTERMOST layer of tensile reinforcement. Not ``k_u``.
    ductility:
        Ductility class of the tensile reinforcement.

    Returns
    -------
    float
        Capacity reduction factor.
    """
    upper = PHI_FLEXURE_MAX_CLASS_L if ductility is Ductility.L else PHI_FLEXURE_MAX_CLASS_N
    raw = PHI_FLEXURE_INTERCEPT - PHI_FLEXURE_SLOPE * kuo
    return max(PHI_FLEXURE_MIN, min(upper, raw))


# ---------------------------------------------------------------------------
# FLEXURE -- AS 3600:2018 Section 8.1
# ---------------------------------------------------------------------------

CLAUSE_FLEXURE = ClauseRef(STANDARD, "8.1.2", note="Ultimate strength in bending")
CLAUSE_STRESS_BLOCK = ClauseRef(STANDARD, "8.1.3", note="Rectangular stress block")
CLAUSE_DUCTILITY = ClauseRef(STANDARD, "8.1.5", note="Ductility limit on k_uo")
CLAUSE_MIN_STEEL = ClauseRef(STANDARD, "8.1.6.1", note="Minimum strength requirement")

KUO_LIMIT = 0.36
"""Maximum k_uo for a member without confinement or compression reinforcement
credit. [BASIS] AS 3600:2018 Cl 8.1.5. [VECTOR] UNVERIFIED."""

MIN_STRENGTH_FACTOR = 1.2
"""(M_uo)min >= 1.2 . M_cr. [BASIS] Cl 8.1.6.1. [VECTOR] UNVERIFIED."""

MIN_STEEL_COEFFICIENT = 0.20
"""Coefficient in (A_st/bd)_min = 0.20 (D/d)^2 . f'ct.f / f_sy for rectangular
sections. [BASIS] Cl 8.1.6.1. [VECTOR] UNVERIFIED."""


# ---------------------------------------------------------------------------
# SHEAR -- AS 3600:2018 Section 8.2
#
# The 2018 edition replaced the earlier Vuc expression with a formulation
# derived from the modified compression field theory. Nothing in this section
# carries over from AS 3600:2009 or from AS 5100.5:2017 -- see the as5100_5
# package, which implements the older family of provisions.
# ---------------------------------------------------------------------------

CLAUSE_SHEAR = ClauseRef(STANDARD, "8.2.1.1", note="Design shear strength")
CLAUSE_DV = ClauseRef(STANDARD, "8.2.1.9", note="Effective shear depth d_v")
CLAUSE_VUC = ClauseRef(STANDARD, "8.2.4.1", note="Concrete shear contribution")
CLAUSE_SIMPLIFIED = ClauseRef(STANDARD, "8.2.4.2", note="Simplified method for k_v and theta_v")
CLAUSE_GENERAL = ClauseRef(STANDARD, "8.2.4.3", note="General method for k_v and theta_v")
CLAUSE_VUMAX = ClauseRef(STANDARD, "8.2.3.3", note="Web crushing limit V_u,max")
CLAUSE_ASV_MIN = ClauseRef(STANDARD, "8.2.1.7", note="Minimum shear reinforcement")

DV_FACTOR_D = 0.72
DV_FACTOR_d = 0.90
"""d_v = max(0.72 D, 0.9 d). [BASIS] Cl 8.2.1.9. [VECTOR] UNVERIFIED."""

SQRT_FC_CAP = 8.0
"""sqrt(f'c) is capped at 8 MPa in the shear expressions, i.e. f'c is
effectively capped at 64 MPa for the concrete contribution.
[VECTOR] UNVERIFIED -- confirm the cap and where it applies."""

THETA_V_SIMPLIFIED = deg(36.0)
"""theta_v = 36 degrees in the simplified method.
[BASIS] Cl 8.2.4.2. [VECTOR] UNVERIFIED."""

KV_SIMPLIFIED_WITH_MIN_STEEL = 0.15
"""k_v = 0.15 where at least minimum shear reinforcement is provided.
[BASIS] Cl 8.2.4.2. [VECTOR] UNVERIFIED."""

KV_NO_STEEL_NUMERATOR = 200.0
KV_NO_STEEL_DENOM_CONST = 1000.0
KV_NO_STEEL_DENOM_FACTOR = 1.3
KV_NO_STEEL_CAP = 0.10
"""k_v = 200 / (1000 + 1.3 d_o) <= 0.10 where less than minimum shear
reinforcement is provided.

[BASIS]  Cl 8.2.4.2.
[VECTOR] UNVERIFIED, and specifically UNCONFIRMED whether the depth term is
         d_o or d_v. The two differ by roughly 10-25% in a typical beam, and
         the resulting k_v differs by a few percent. Resolve this against the
         printed clause before relying on an unreinforced-web shear capacity.
         See KV_NO_STEEL_DEPTH_IS_DO below."""

KV_NO_STEEL_DEPTH_IS_DO = True
"""Switch controlling which depth the k_v expression above uses.
True  -> d_o (depth to the outermost tensile bar)
False -> d_v (effective shear depth)
[VECTOR] UNVERIFIED. Set this from the printed clause."""

ASV_MIN_COEFFICIENT = 0.08
"""(A_sv/s)_min = 0.08 . sqrt(f'c) . b_v / f_sy.f.
[BASIS] Cl 8.2.1.7. [VECTOR] UNVERIFIED."""

VU_MAX_COEFFICIENT = 0.55
"""V_u,max = 0.55 . f'c . b_v . d_v . (cot theta_v + cot alpha_v)/(1 + cot^2 theta_v).
[BASIS] Cl 8.2.3.3. [VECTOR] UNVERIFIED."""

# -- general method parameters, Cl 8.2.4.3 ---------------------------------

KV_GENERAL_NUMERATOR = 0.40
KV_GENERAL_STRAIN_FACTOR = 1500.0
KV_GENERAL_SIZE_NUMERATOR = 1300.0
KV_GENERAL_SIZE_CONST = 1000.0
"""k_v = [0.4 / (1 + 1500.eps_x)] . [1300 / (1000 + k_dg.d_v)].
[BASIS] Cl 8.2.4.3. [VECTOR] UNVERIFIED."""

THETA_V_GENERAL_INTERCEPT = 29.0
THETA_V_GENERAL_SLOPE = 7000.0
"""theta_v = 29 + 7000.eps_x  (degrees).
[BASIS] Cl 8.2.4.3. [VECTOR] UNVERIFIED."""

KDG_NUMERATOR = 32.0
KDG_CONST = 16.0
KDG_MIN = 0.80
"""k_dg = 32/(16 + d_g) >= 0.8, with d_g the maximum aggregate size in mm.
Taken as 1.0 for f'c > 65 MPa, where the crack surface passes through the
aggregate. [BASIS] Cl 8.2.4.3. [VECTOR] UNVERIFIED, including the f'c
threshold below."""

KDG_FC_THRESHOLD = 65.0
"""Above this f'c, k_dg is taken as 1.0. [VECTOR] UNVERIFIED."""

EPS_X_MAX = 3.0e-3
"""Upper bound on the longitudinal strain eps_x in the general method.
[VECTOR] UNVERIFIED."""

DEFAULT_AGGREGATE_SIZE = 20.0
"""Default maximum nominal aggregate size (mm) where the caller does not state
one. Not a code value -- an implementation default."""


def cot(angle_rad: float) -> float:
    """Cotangent. Named because ``1/math.tan`` in the middle of a shear
    expression obscures which code term is being evaluated."""
    return 1.0 / math.tan(angle_rad)


# ---------------------------------------------------------------------------
# SERVICEABILITY -- DEFLECTION -- AS 3600:2018 Section 8.5 and Table 2.3.2
# ---------------------------------------------------------------------------

CLAUSE_DEFLECTION = ClauseRef(STANDARD, "8.5.1", note="Deflection of beams")
CLAUSE_IEF = ClauseRef(STANDARD, "8.5.3.1", note="Effective second moment of area")
CLAUSE_KCS = ClauseRef(STANDARD, "8.5.3.2", note="Long-term deflection multiplier")
CLAUSE_SPAN_DEPTH = ClauseRef(STANDARD, "8.5.4", note="Deemed-to-comply span-to-depth ratio")
CLAUSE_DEFL_LIMITS = ClauseRef(STANDARD, table="2.3.2", note="Deflection limits")

IEF_EXPONENT = 3.0
"""Exponent n in I_ef = I_cr + (I - I_cr)(M_cr/M_s)^n.
[BASIS] Cl 8.5.3.1. [VECTOR] UNVERIFIED."""

IEF_MAX_P_THRESHOLD = 0.005
"""Reinforcement ratio p = A_st/(b d) at or above which I_ef.max is the full
uncracked value. [BASIS] Cl 8.5.3.1. [VECTOR] UNVERIFIED."""

IEF_MAX_FACTOR_HIGH_P = 1.0
IEF_MAX_FACTOR_LOW_P = 0.6
"""I_ef.max as a fraction of I. The reduced cap for lightly reinforced sections
recognises that such a section loses most of its stiffness the moment it
cracks. [BASIS] Cl 8.5.3.1. [VECTOR] UNVERIFIED -- both factors AND the
question of whether I means the gross or the uncracked transformed value."""

KCS_INTERCEPT = 2.0
KCS_SLOPE = 1.2
KCS_MIN = 0.8
"""k_cs = 2 - 1.2 (A_sc/A_st) >= 0.8. [BASIS] Cl 8.5.3.2. [VECTOR] UNVERIFIED."""

# -- Deflection limits, Table 2.3.2 ----------------------------------------
# Expressed as denominators of the effective span: 250 means L_ef/250.
# [VECTOR] UNVERIFIED -- every ratio, and the applicability of each.

DEFL_TOTAL_SPAN_RATIO = 250.0
"""Total deflection limit for a member not supporting brittle finishes,
L_ef/250. [BASIS] Table 2.3.2. [VECTOR] UNVERIFIED."""

DEFL_INCREMENTAL_BRITTLE_RATIO = 500.0
"""Deflection occurring AFTER the addition of brittle finishes or partitions,
L_ef/500. [BASIS] Table 2.3.2. [VECTOR] UNVERIFIED."""

DEFL_INCREMENTAL_NON_BRITTLE_RATIO = 250.0
"""As above but where the finishes are not brittle, L_ef/250.
[BASIS] Table 2.3.2. [VECTOR] UNVERIFIED."""

DEFL_CANTILEVER_SPAN_FACTOR = 2.0
"""Multiplier applied to a cantilever's length to obtain the effective span
used in the ratio limits. [VECTOR] UNVERIFIED -- confirm whether AS 3600
handles cantilevers this way or by a separate ratio."""

PSI_S_DEFAULT = 0.7
PSI_L_DEFAULT = 0.4
"""Short-term and long-term live load factors used to form the serviceability
combinations. These are AS/NZS 1170.0 values and vary with occupancy -- the
``project`` package supplies the real ones. These defaults exist so a
standalone deflection check runs, and they are deliberately the office/
residential values. [VECTOR] UNVERIFIED."""


# ---------------------------------------------------------------------------
# SERVICEABILITY -- CRACK CONTROL -- AS 3600:2018 Section 8.6
# ---------------------------------------------------------------------------

CLAUSE_CRACK_CONTROL = ClauseRef(STANDARD, "8.6.1", note="Crack control for flexure")
CLAUSE_CRACK_TABLES = ClauseRef(STANDARD, table="8.6.1", note="Bar diameter and spacing limits")

CRACK_MAX_BAR_SPACING = 300.0
"""Maximum centre-to-centre spacing of tensile bars, mm.
[BASIS] Cl 8.6.1. [VECTOR] UNVERIFIED."""

CRACK_MAX_COVER_TO_BAR = 100.0
"""Maximum distance from the section face to the nearest longitudinal bar, mm.
[BASIS] Cl 8.6.1. [VECTOR] UNVERIFIED."""

# Table 8.6.1(A): maximum bar diameter for a given steel stress.
# Stored ascending by stress. Read as: at or below this stress, a bar of at
# most this diameter is acceptable.
# [VECTOR] UNVERIFIED -- every pair, and whether interpolation is permitted.
CRACK_BAR_DIAMETER_TABLE: tuple[tuple[float, float], ...] = (
    (150.0, 40.0),
    (200.0, 32.0),
    (240.0, 25.0),
    (280.0, 20.0),
    (320.0, 16.0),
    (360.0, 12.0),
    (400.0, 10.0),
)

# Table 8.6.1(B): maximum centre-to-centre bar spacing for a given steel stress.
# [VECTOR] UNVERIFIED -- every pair.
CRACK_BAR_SPACING_TABLE: tuple[tuple[float, float], ...] = (
    (150.0, 300.0),
    (200.0, 250.0),
    (240.0, 200.0),
    (280.0, 150.0),
    (320.0, 100.0),
    (360.0, 50.0),
)

CRACK_STEEL_STRESS_LIMIT_FLEXURE = 0.8
"""Cap on service steel stress as a fraction of f_sy for flexural crack
control where the deemed-to-comply tables are used.
[VECTOR] UNVERIFIED -- both the existence and the value of this cap."""


# ---------------------------------------------------------------------------
# DETAILING AND ANCHORAGE -- AS 3600:2018 Section 13
#
# Anchorage is where a strength calculation meets the drawing. A beam whose
# section capacity is ample fails anyway if the bars cannot develop that
# capacity where it is needed, and unlike a capacity shortfall this failure
# mode is invisible in the flexure output. That is the reason this section
# exists in a package that already computes M_uo.
# ---------------------------------------------------------------------------

CLAUSE_DEVELOPMENT = ClauseRef(STANDARD, "13.1.2.2", note="Basic development length in tension")
CLAUSE_DEVELOPMENT_REFINED = ClauseRef(STANDARD, "13.1.2.3", note="Refined development length")
CLAUSE_DEVELOPMENT_COMP = ClauseRef(STANDARD, "13.1.5", note="Development length in compression")
CLAUSE_LAP_TENSION = ClauseRef(STANDARD, "13.2.2", note="Lapped splices in tension")
CLAUSE_LAP_COMPRESSION = ClauseRef(STANDARD, "13.2.4", note="Lapped splices in compression")
CLAUSE_CURTAILMENT = ClauseRef(STANDARD, "8.1.10", note="Curtailment of flexural reinforcement")
CLAUSE_BAR_SPACING = ClauseRef(STANDARD, "13.1.2.1", note="Minimum clear spacing of bars")

# -- Basic tension development length, Cl 13.1.2.2 -------------------------
#     L_sy.tb = 0.5 . k1 . k3 . f_sy . d_b / (k2 . sqrt(f'c))
#            >= 0.058 . f_sy . k1 . d_b

LSY_TB_COEFFICIENT = 0.5
"""Leading coefficient in L_sy.tb. [VECTOR] UNVERIFIED."""

LSY_TB_FLOOR_COEFFICIENT = 0.058
"""Lower bound coefficient: L_sy.tb >= 0.058 f_sy k1 d_b.
[VECTOR] UNVERIFIED."""

K1_CAST_BELOW_300 = 1.3
K1_DEFAULT = 1.0
"""k1 = 1.3 for a horizontal bar with more than 300 mm of concrete cast below
it, otherwise 1.0. The penalty accounts for bleed water collecting under the
bar and weakening the bond. [VECTOR] UNVERIFIED -- both values and the 300 mm
threshold below."""

K1_DEPTH_THRESHOLD = 300.0
"""Depth of concrete cast below a bar, in mm, above which k1 applies.
[VECTOR] UNVERIFIED."""

K2_NUMERATOR = 132.0
K2_DIVISOR = 100.0
"""k2 = (132 - d_b)/100. [VECTOR] UNVERIFIED."""

K3_INTERCEPT = 1.0
K3_SLOPE = 0.15
K3_MIN = 0.7
K3_MAX = 1.0
"""k3 = 1.0 - 0.15 (c_d - d_b)/d_b, bounded to [0.7, 1.0]. c_d is a cover or
half-spacing dimension depending on the bar arrangement.
[VECTOR] UNVERIFIED -- coefficients and both bounds."""

K4_NO_TRANSVERSE = 1.0
K4_MIN = 0.7
"""k4 = 1 - K.lambda, bounded below by 0.7, crediting transverse
reinforcement crossing the splitting plane. Taken as 1.0 (no credit) unless
the caller supplies a value. [VECTOR] UNVERIFIED."""

K5_NO_PRESSURE = 1.0
K5_MIN = 0.7
"""k5 = 1 - 0.04 rho_p, bounded below by 0.7, crediting transverse compressive
pressure. Taken as 1.0 (no credit) by default. [VECTOR] UNVERIFIED."""

LSY_T_ABSOLUTE_MIN = 200.0
"""Absolute minimum development length, mm. [VECTOR] UNVERIFIED."""

# -- Compression development length, Cl 13.1.5 ------------------------------

LSY_C_COEFFICIENT = 0.22
LSY_C_FLOOR_COEFFICIENT = 0.0435
LSY_C_ABSOLUTE_MIN = 200.0
"""L_sy.c = 0.22 f_sy d_b / sqrt(f'c) >= 0.0435 f_sy d_b >= 200 mm.
[VECTOR] UNVERIFIED -- all three."""

# -- Laps, Cl 13.2 ----------------------------------------------------------

K7_STAGGERED = 1.25
K7_GENEROUS_STEEL = 1.0
"""k7 on a tension lap: 1.25 in general, reducible to 1.0 where the area of
steel provided is at least twice that required AND no more than half the bars
are lapped at the section. [VECTOR] UNVERIFIED -- both values and both
qualifying conditions."""

LAP_TENSION_ABSOLUTE_MIN = 300.0
"""Minimum tension lap, mm. [VECTOR] UNVERIFIED."""

LAP_COMPRESSION_DB_FACTOR = 40.0
LAP_COMPRESSION_ABSOLUTE_MIN = 300.0
"""Compression lap >= max(40 d_b, L_sy.c, 300 mm).
[VECTOR] UNVERIFIED -- the 40 and the 300."""

# -- Curtailment, Cl 8.1.10 -------------------------------------------------

CURTAIL_EXTENSION_D_FACTOR = 1.0
CURTAIL_EXTENSION_DB_FACTOR = 12.0
"""A bar must extend past the point at which it is no longer required for
flexure by at least max(D, 12 d_b). The extension covers the shift in the
tensile force caused by diagonal cracking.
[VECTOR] UNVERIFIED -- both factors."""

# -- Minimum clear spacing, Cl 13.1.2.1 -------------------------------------

MIN_CLEAR_SPACING_ABSOLUTE = 25.0
MIN_CLEAR_SPACING_AGGREGATE_FACTOR = 1.33
"""Clear distance between parallel bars >= max(25 mm, d_b, 1.33 x maximum
aggregate size). The aggregate rule is about getting concrete between the bars,
not about bond. [VECTOR] UNVERIFIED -- the 25 mm and the 1.33."""


# ---------------------------------------------------------------------------
# MOMENT REDISTRIBUTION -- AS 3600:2018 Cl 6.2.7
#
# How much moment a support can shed depends on how much rotation the plastic
# hinge there can deliver before the concrete crushes -- which is a question
# about the neutral axis depth. A lightly reinforced, shallow-axis section is
# ductile and can redistribute; a heavily reinforced one cannot, and asking it
# to would be asking for a brittle failure.
# ---------------------------------------------------------------------------

CLAUSE_REDISTRIBUTION = ClauseRef(STANDARD, "6.2.7", note="Moment redistribution")

REDISTRIBUTION_KUO_FULL = 0.2
"""k_uo at or below which the full redistribution percentage is available.
[BASIS] Cl 6.2.7. [VECTOR] UNVERIFIED."""

REDISTRIBUTION_KUO_NONE = 0.4
"""k_uo at or above which NO redistribution is permitted.
[BASIS] Cl 6.2.7. [VECTOR] UNVERIFIED."""

REDISTRIBUTION_MAX_CLASS_N = 30.0
"""Maximum redistribution for Class N reinforcement, per cent.
[BASIS] Cl 6.2.7. [VECTOR] UNVERIFIED."""

REDISTRIBUTION_MAX_CLASS_L = 0.0
"""Maximum redistribution for Class L reinforcement, per cent. Class L is not
ductile enough to form a reliable hinge, so no redistribution is permitted.
[BASIS] Cl 6.2.7. [VECTOR] UNVERIFIED -- confirm this is a flat prohibition
rather than a reduced allowance."""
