"""AS 5100.5:2017 constants and capacity reduction factors.

=============================================================================
THIS IS THE FILE TO CHECK AGAINST THE PRINTED STANDARD.
=============================================================================

Read this before using the package
----------------------------------
AS 5100.5:2017 predates AS 3600:2018. Its provisions follow the AS 3600:2009
family, which means:

- the capacity reduction factors are NOT the same as AS 3600:2018's, and in
  particular flexure does not use the ``k_uo``-dependent expression;
- the shear model is the older ``V_uc = beta_1.beta_2.beta_3 . b_v . d_o . f_cv
  . (A_st/(b_v.d_o))^(1/3)`` form, not the modified-compression-field-theory
  formulation of AS 3600:2018.

Treating AS 5100.5 as "AS 3600 with different numbers" is the single most
likely way to get a bridge design wrong with this toolkit. The two packages
therefore share the flexural MECHANICS (``rc_common``) and share nothing else.

Every value here is ``[VECTOR]`` UNVERIFIED, and several are explicitly
UNCONFIRMED -- meaning the author is not confident of the value, not merely
that it has not been formally checked. Those are marked. Resolve every one
against the printed standard before any bridge calculation is issued.

[UNITS] Stresses MPa, lengths mm, angles via ``deg()``.
"""

from __future__ import annotations

from ...core.basis import AS5100_5_2017, ClauseRef
from ...core.units import deg

STANDARD = AS5100_5_2017

# ---------------------------------------------------------------------------
# CAPACITY REDUCTION FACTORS -- AS 5100.5:2017 Table 2.3.2
# ---------------------------------------------------------------------------

CLAUSE_PHI = ClauseRef(STANDARD, table="2.3.2", note="Capacity reduction factors")

PHI_FLEXURE = 0.80
"""phi for bending without axial tension.

[VECTOR] UNVERIFIED and UNCONFIRMED. AS 5100.5:2017 follows the AS 3600:2009
         convention of a single phi for flexure rather than the k_uo-dependent
         expression of AS 3600:2018. Confirm the value AND confirm whether any
         ductility-dependent variation applies. Do not assume it matches
         AS 3600:2018."""

PHI_SHEAR = 0.70
"""phi for shear. [VECTOR] UNVERIFIED."""

PHI_TORSION = 0.70
"""phi for torsion. [VECTOR] UNVERIFIED. Not used yet."""

# ---------------------------------------------------------------------------
# FLEXURE
# ---------------------------------------------------------------------------

CLAUSE_FLEXURE = ClauseRef(STANDARD, "8.1", note="Strength of members in bending")
CLAUSE_STRESS_BLOCK = ClauseRef(STANDARD, "8.1.3", note="Rectangular stress block")
CLAUSE_DUCTILITY = ClauseRef(STANDARD, "8.1.5", note="Ductility limit on k_uo")
CLAUSE_MIN_STEEL = ClauseRef(STANDARD, "8.1.6", note="Minimum strength requirement")

KUO_LIMIT = 0.36
"""Maximum k_uo.

[VECTOR] UNVERIFIED and UNCONFIRMED. AS 3600:2009 used 0.4; AS 3600:2018 uses
         0.36. Which AS 5100.5:2017 adopts must be confirmed -- it changes
         where compression reinforcement becomes necessary."""

MIN_STRENGTH_FACTOR = 1.2
"""(M_uo)min >= 1.2 M_cr. [VECTOR] UNVERIFIED."""

MIN_STEEL_COEFFICIENT = 0.20
"""Coefficient in the rectangular-section minimum steel expression.
[VECTOR] UNVERIFIED."""

# ---------------------------------------------------------------------------
# SHEAR -- the AS 3600:2009 family formulation
# ---------------------------------------------------------------------------

CLAUSE_SHEAR = ClauseRef(STANDARD, "8.2.1", note="Design shear strength of a beam")
CLAUSE_VUC = ClauseRef(STANDARD, "8.2.7", note="Shear strength excluding shear reinforcement")
CLAUSE_VUS = ClauseRef(STANDARD, "8.2.10", note="Contribution of shear reinforcement")
CLAUSE_VUMAX = ClauseRef(STANDARD, "8.2.6", note="Maximum shear strength, web crushing")
CLAUSE_VUMIN = ClauseRef(STANDARD, "8.2.9", note="Minimum shear strength")
CLAUSE_ASV_MIN = ClauseRef(STANDARD, "8.2.8", note="Minimum shear reinforcement")

FCV_EXPONENT = 1.0 / 3.0
FCV_CAP = 4.0
"""f_cv = (f'c)^(1/3), capped at 4 MPa. [VECTOR] UNVERIFIED."""

BETA1_FACTOR = 1.1
BETA1_DEPTH_CONST = 1.6
BETA1_DEPTH_DIVISOR = 1000.0
BETA1_MIN_WITH_FITMENTS = 1.1
BETA1_MIN_WITHOUT_FITMENTS = 0.8
"""beta_1 = 1.1 . (1.6 - d_o/1000), not less than 1.1 where at least minimum
shear reinforcement is provided, or 0.8 where it is not.

[VECTOR] UNVERIFIED and UNCONFIRMED -- particularly the two lower bounds and
         whether AS 5100.5 applies the same distinction as AS 3600:2009."""

BETA2_DEFAULT = 1.0
BETA3_DEFAULT = 1.0
"""beta_2 accounts for axial force, beta_3 for loads applied close to a
support. Both taken as 1.0 -- the conservative value for beta_3 and the
correct value for beta_2 in the absence of axial force.

[ASSUMPTION] beta_3 > 1.0 is available where a load is applied within 2 d_o of
             a support face. Not implemented; taking 1.0 is conservative."""

VUMIN_COEFFICIENT = 0.6
"""V_u.min = V_uc + 0.6 . b_v . d_o. [VECTOR] UNVERIFIED."""

VUMAX_COEFFICIENT = 0.2
"""V_u.max = 0.2 . f'c . b_v . d_o. [VECTOR] UNVERIFIED."""

ASV_MIN_COEFFICIENT = 0.06
ASV_MIN_FLOOR = 0.35
"""(A_sv/s)_min = max(0.06 . sqrt(f'c) . b_v / f_sy.f, 0.35 . b_v / f_sy.f).
[VECTOR] UNVERIFIED -- both coefficients."""

THETA_V_MIN = deg(30.0)
THETA_V_MAX = deg(45.0)
"""theta_v varies linearly from 30 degrees where V* = phi.V_u,min to 45 degrees
where V* = phi.V_u,max.

[VECTOR] UNVERIFIED. This linear interpolation between the two bounds is the
         AS 3600:2009 rule; confirm AS 5100.5:2017 adopts it."""

ALPHA_V_VERTICAL = deg(90.0)
"""Fitment inclination for vertical ligatures."""


# ---------------------------------------------------------------------------
# SERVICEABILITY -- AS 5100.5:2017 Section 8.5 (deflection) and 8.6 (cracking)
#
# Bridges differ from buildings in two ways that matter here. The traffic load
# is largely transient, so the sustained fraction driving creep is a smaller
# part of the total than in a building. And exposure is usually more severe,
# so crack control governs more often than deflection does.
# ---------------------------------------------------------------------------

CLAUSE_SLS_DEFLECTION = ClauseRef(STANDARD, "8.5.3", note="Effective second moment of area")
CLAUSE_SLS_CRACKING = ClauseRef(STANDARD, "8.6.1", note="Crack control for flexure")
CLAUSE_SLS_STRESS = ClauseRef(STANDARD, "8.6.2", note="Serviceability stress limits")

IEF_EXPONENT = 3.0
"""Exponent in the effective-second-moment interpolation.
[BASIS] Cl 8.5.3. [VECTOR] UNVERIFIED."""

IEF_MAX_P_THRESHOLD = 0.005
IEF_MAX_FACTOR_HIGH_P = 1.0
IEF_MAX_FACTOR_LOW_P = 0.6
"""Cap on I_ef, reduced for lightly reinforced sections.
[BASIS] Cl 8.5.3. [VECTOR] UNVERIFIED."""

KCS_INTERCEPT = 2.0
KCS_SLOPE = 1.2
KCS_MIN = 0.8
"""k_cs = 2 - 1.2 (A_sc/A_st) >= 0.8. [VECTOR] UNVERIFIED."""

# -- Serviceability steel stress limits ------------------------------------
# The governing crack-control mechanism in AS 5100.5 is a direct cap on the
# steel stress increment, differentiated by exposure. These are the values a
# bridge designer reaches for first.
# [VECTOR] UNVERIFIED -- every value, and the exposure classifications they
#          attach to. Confirm against Cl 8.6 before use.

STEEL_STRESS_LIMIT_BY_EXPOSURE: dict[str, float] = {
    "A1": 250.0,
    "A2": 250.0,
    "B1": 200.0,
    "B2": 175.0,
    "C1": 150.0,
    "C2": 150.0,
    "U": 150.0,
}
"""Maximum service-load tensile stress increment in the reinforcement (MPa),
by AS 5100.5 exposure classification.
[VECTOR] UNVERIFIED -- all seven values and the classification names."""

CRACK_MAX_BAR_SPACING = 300.0
"""Maximum centre-to-centre spacing of tensile bars, mm.
[BASIS] Cl 8.6.1. [VECTOR] UNVERIFIED."""

CONCRETE_COMPRESSIVE_STRESS_SLS = 0.4
"""Cap on concrete compressive stress under service load, as a fraction of
f'c. Guards against excessive creep and microcracking.
[BASIS] Cl 8.6.2. [VECTOR] UNVERIFIED -- both the existence and the value."""
