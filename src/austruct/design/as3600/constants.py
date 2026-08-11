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
