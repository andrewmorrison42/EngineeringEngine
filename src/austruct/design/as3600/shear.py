"""Shear design of reinforced concrete beams to AS 3600:2018 Section 8.2.

What changed in the 2018 edition
--------------------------------
AS 3600:2018 replaced the earlier ``V_uc`` formulation with one derived from
the modified compression field theory. The concrete contribution is now
``k_v . b_v . d_v . sqrt(f'c)`` with ``k_v`` and the strut angle ``theta_v``
determined either by a simplified method (Cl 8.2.4.2) or a general method
(Cl 8.2.4.3) that depends on the longitudinal strain at mid-depth.

None of this carries over to AS 5100.5:2017, which still uses the older
``beta_1.beta_2.beta_3`` family. That is why the two live in separate packages
rather than sharing a parameterised function -- they are different models, not
the same model with different constants.

Public entry points
-------------------
:func:`shear_capacity`
    Nominal and design shear capacity of a section.
:func:`check_shear`
    The same, plus the check against a design shear ``V*``.
:func:`required_shear_reinforcement`
    Inverse problem -- the ``A_sv/s`` needed for a given ``V*``.

[UNITS] mm, N, MPa. Angles in radians internally, reported in degrees.

[VECTOR] This module is UNVERIFIED. All code constants are in ``constants.py``.
"""

from __future__ import annotations

import math

from ...core.basis import Basis, ClauseRef
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_FORCE, U_LENGTH, U_NONE, U_STRESS, kN, to_deg
from ...sections.rc_section import Fitment, RCSection
from . import constants as C

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Shear capacity of RC beams to AS 3600:2018 Section 8.2",
    envelope_summary=(
        "20 <= f'c <= 100 MPa; non-prestressed; vertical fitments only; "
        "no axial force; no torsion"
    ),
)


def effective_shear_depth(section: RCSection, d: float) -> float:
    """d_v -- effective shear depth.

    Basis
    -----
    AS 3600:2018 Cl 8.2.1.9: ``d_v = max(0.72 D, 0.9 d)``.

    [VECTOR] UNVERIFIED -- both factors, in ``constants.py``.
    [UNITS] mm.
    """
    return max(C.DV_FACTOR_D * section.geometry.D, C.DV_FACTOR_d * d)


def minimum_shear_reinforcement(section: RCSection, fsy_f: float) -> float:
    """(A_sv/s)min -- minimum shear reinforcement per unit length.

    Basis
    -----
    AS 3600:2018 Cl 8.2.1.7: ``(A_sv/s)_min = 0.08 . sqrt(f'c) . b_v / f_sy.f``.

    [VECTOR] UNVERIFIED -- coefficient.
    [UNITS] returns mm^2/mm.
    """
    return C.ASV_MIN_COEFFICIENT * section.concrete.sqrt_fc * section.bv / fsy_f


def _kv_theta_simplified(
    section: RCSection, d_o: float, has_min_steel: bool
) -> tuple[float, float, str]:
    """k_v and theta_v by the simplified method.

    Basis
    -----
    AS 3600:2018 Cl 8.2.4.2.

    With at least minimum shear reinforcement: ``k_v = 0.15``, ``theta_v = 36 deg``.
    Otherwise: ``k_v = 200/(1000 + 1.3 d) <= 0.10``, ``theta_v = 36 deg``.

    [VECTOR] UNVERIFIED, and note the unresolved question of whether the depth
             term in the second expression is ``d_o`` or ``d_v`` -- see
             ``constants.KV_NO_STEEL_DEPTH_IS_DO``.
    """
    theta = C.THETA_V_SIMPLIFIED
    if has_min_steel:
        return C.KV_SIMPLIFIED_WITH_MIN_STEEL, theta, "simplified, >= minimum fitments"

    kv = C.KV_NO_STEEL_NUMERATOR / (
        C.KV_NO_STEEL_DENOM_CONST + C.KV_NO_STEEL_DENOM_FACTOR * d_o
    )
    kv = min(kv, C.KV_NO_STEEL_CAP)
    return kv, theta, "simplified, < minimum fitments"


def _kv_theta_general(
    section: RCSection,
    d_v: float,
    Ast: float,  # noqa: N803
    M_star: float,  # noqa: N803
    V_star: float,  # noqa: N803
    aggregate_size: float,
) -> tuple[float, float, float, str]:
    """k_v and theta_v by the general method.

    Basis
    -----
    AS 3600:2018 Cl 8.2.4.3::

        eps_x   = (M*/d_v + V*) / (2 . E_s . A_st)      <= 3e-3
        k_dg    = 32/(16 + d_g) >= 0.8, or 1.0 for f'c > 65 MPa
        k_v     = [0.4/(1 + 1500.eps_x)] . [1300/(1000 + k_dg.d_v)]
        theta_v = 29 + 7000.eps_x   (degrees)

    [VECTOR] UNVERIFIED -- every coefficient.
    [ASSUMPTION] Non-prestressed, no axial force, so the ``0.5 N*`` and
                 prestress terms of the full expression are zero. Only the
                 tensile reinforcement on the flexural tension side is counted
                 in ``A_st``, and it is assumed fully developed at the section.

    Returns
    -------
    (k_v, theta_v_radians, eps_x, description)
    """
    Es = 200_000.0  # [BASIS] Cl 3.2.2, via materials.reinforcement
    if Ast <= 0:
        raise ModelError(
            "The general method needs longitudinal tensile reinforcement to "
            "compute eps_x, and the section has none in tension."
        )

    eps_x = (abs(M_star) / d_v + abs(V_star)) / (2.0 * Es * Ast)
    # [CHECK] The clause caps eps_x; beyond the cap the model is not calibrated.
    eps_x = min(max(eps_x, 0.0), C.EPS_X_MAX)

    if section.concrete.fc > C.KDG_FC_THRESHOLD:
        # [ASSUMPTION] For high-strength concrete the crack passes through the
        #              aggregate, so aggregate interlock is not credited.
        k_dg = 1.0
    else:
        k_dg = max(C.KDG_MIN, C.KDG_NUMERATOR / (C.KDG_CONST + aggregate_size))

    kv = (C.KV_GENERAL_NUMERATOR / (1.0 + C.KV_GENERAL_STRAIN_FACTOR * eps_x)) * (
        C.KV_GENERAL_SIZE_NUMERATOR / (C.KV_GENERAL_SIZE_CONST + k_dg * d_v)
    )
    theta_deg = C.THETA_V_GENERAL_INTERCEPT + C.THETA_V_GENERAL_SLOPE * eps_x
    return kv, math.radians(theta_deg), eps_x, "general method"


def shear_capacity(
    section: RCSection,
    M_star: float = 0.0,  # noqa: N803
    V_star: float = 0.0,  # noqa: N803
    method: str = "simplified",
    aggregate_size: float = C.DEFAULT_AGGREGATE_SIZE,
    d: float | None = None,
    Ast: float | None = None,  # noqa: N803
) -> CalcResult:
    """Shear capacity of a reinforced concrete section.

    Basis
    -----
    AS 3600:2018:

    - Cl 8.2.1.1 -- ``V_u = V_uc + V_us``
    - Cl 8.2.1.7 -- minimum shear reinforcement
    - Cl 8.2.1.9 -- effective shear depth ``d_v``
    - Cl 8.2.3.3 -- web crushing limit ``V_u,max``
    - Cl 8.2.4.1 -- ``V_uc = k_v . b_v . d_v . sqrt(f'c)``
    - Cl 8.2.4.2 / 8.2.4.3 -- ``k_v`` and ``theta_v``
    - Table 2.2.2 -- ``phi = 0.7``

    Envelope
    --------
    20 MPa <= f'c <= 100 MPa. Non-prestressed. Vertical fitments only. No
    axial force, no torsion.

    Parameters
    ----------
    section:
        The RC section, including its fitment if any.
    M_star, V_star:
        Design actions at the section (N.mm, N). Required by the general
        method, which depends on them through ``eps_x``. Ignored by the
        simplified method.
    method:
        ``"simplified"`` (Cl 8.2.4.2) or ``"general"`` (Cl 8.2.4.3).
    aggregate_size:
        Maximum nominal aggregate size ``d_g`` (mm). General method only.
    d, Ast:
        Effective depth and tensile steel area. Default to the section's own
        values; supply explicitly where the flexural solution has already
        determined them more precisely.

    Returns
    -------
    CalcResult
        ``outputs["Vu"]``, ``outputs["phiVu"]``, ``outputs["Vuc"]``,
        ``outputs["Vus"]``, ``outputs["Vumax"]``.

    Examples
    --------
    >>> res = shear_capacity(section, method="simplified")
    >>> res.get("phiVu") / 1e3      # kN
    """
    if method not in {"simplified", "general"}:
        raise ValueError(f"method must be 'simplified' or 'general', got {method!r}")

    env = Envelope(name="AS 3600 shear")
    env.add(
        "f'c",
        section.concrete.fc,
        lower=20.0,
        upper=100.0,
        unit=U_STRESS,
        basis=ClauseRef(C.STANDARD, "1.1.2", note="Range of application"),
    )
    env.note("Non-prestressed reinforced concrete. No axial force, no torsion.")
    env.note("Vertical fitments only (alpha_v = 90 degrees).")
    env.note(
        "Shear friction across construction joints, and shear in the vicinity "
        "of concentrated loads within 2d of a support, are not considered."
    )

    fitment = section.fitment
    if fitment is not None and abs(fitment.angle - math.pi / 2) > 1e-6:
        env.add(
            "alpha_v",
            to_deg(fitment.angle),
            lower=90.0,
            upper=90.0,
            unit="deg",
            reason="Only vertical fitments are implemented",
        )
    env.require()

    basis = Basis()
    basis.add(C.CLAUSE_SHEAR)

    d_eff = d if d is not None else section.d
    ast = Ast if Ast is not None else section.Ast
    d_v = effective_shear_depth(section, d_eff)
    d_o = section.d_o
    bv = section.bv

    result = CalcResult(
        name=f"Shear capacity -- AS 3600:2018 Cl 8.2 ({method} method)",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )

    result.add_input("fc", Value(section.concrete.fc, U_STRESS, "f'c", "Concrete strength"))
    result.add_input("bv", Value(bv, U_LENGTH, "b_v", "Effective web width"))
    result.add_input("D", Value(section.geometry.D, U_LENGTH, "D", "Overall depth"))
    result.add_input("d", Value(d_eff, U_LENGTH, "d", "Effective depth"))
    result.add_input("Ast", Value(ast, "mm^2", "A_st", "Tensile reinforcement area"))
    if fitment:
        result.add_input(
            "fitment",
            Value(fitment.asv_per_s, "mm^2/mm", "A_sv/s", f"Fitments: {fitment.designation}"),
        )

    basis.add(C.CLAUSE_DV)
    result.add_intermediate("dv", Value(d_v, U_LENGTH, "d_v", "Effective shear depth"))
    result.add_intermediate("do", Value(d_o, U_LENGTH, "d_o", "Depth to outermost tensile bar"))

    # -- minimum shear reinforcement -----------------------------------------
    basis.add(C.CLAUSE_ASV_MIN)
    fsy_f = fitment.material.fsy if fitment else 500.0
    asv_s_min = minimum_shear_reinforcement(section, fsy_f)
    asv_s = fitment.asv_per_s if fitment else 0.0
    has_min_steel = asv_s >= asv_s_min - 1e-12

    result.add_intermediate(
        "Asv_s_min", Value(asv_s_min, "mm^2/mm", "(A_sv/s)_min", "Minimum shear reinforcement")
    )

    # -- k_v and theta_v -------------------------------------------------------
    if method == "simplified":
        basis.add(C.CLAUSE_SIMPLIFIED)
        depth_for_kv = d_o if C.KV_NO_STEEL_DEPTH_IS_DO else d_v
        kv, theta_v, how = _kv_theta_simplified(section, depth_for_kv, has_min_steel)
        eps_x = None
    else:
        basis.add(C.CLAUSE_GENERAL)
        kv, theta_v, eps_x, how = _kv_theta_general(
            section, d_v, ast, M_star, V_star, aggregate_size
        )
        result.add_intermediate(
            "eps_x", Value(eps_x, U_NONE, "eps_x", "Longitudinal strain at mid-depth")
        )

    result.add_intermediate("kv", Value(kv, U_NONE, "k_v", f"Concrete shear factor ({how})"))
    result.add_intermediate(
        "theta_v", Value(to_deg(theta_v), "deg", "theta_v", "Compression strut angle")
    )

    # -- V_uc ------------------------------------------------------------------
    basis.add(C.CLAUSE_VUC)
    # [CHECK] sqrt(f'c) is capped, which caps the concrete contribution for
    #         high-strength concrete.
    sqrt_fc = min(section.concrete.sqrt_fc, C.SQRT_FC_CAP)
    if section.concrete.sqrt_fc > C.SQRT_FC_CAP:
        result.note(
            f"sqrt(f'c) capped at {C.SQRT_FC_CAP} MPa "
            f"(actual {section.concrete.sqrt_fc:.2f} MPa)."
        )
    Vuc = kv * bv * d_v * sqrt_fc
    result.add_output("Vuc", Value(Vuc, U_FORCE, "V_uc", "Concrete contribution", "kN", kN))

    # -- V_us ------------------------------------------------------------------
    # [BASIS] Cl 8.2.5 -- V_us = (A_sv . f_sy.f . d_v / s) . cot(theta_v) for
    #         fitments perpendicular to the member axis.
    if fitment:
        Vus = asv_s * fsy_f * d_v * C.cot(theta_v)
    else:
        Vus = 0.0
        result.note("No shear reinforcement provided; V_us taken as zero.")
    result.add_output("Vus", Value(Vus, U_FORCE, "V_us", "Fitment contribution", "kN", kN))

    # -- V_u,max ---------------------------------------------------------------
    basis.add(C.CLAUSE_VUMAX)
    # [BASIS] Cl 8.2.3.3 with alpha_v = 90 deg, so cot(alpha_v) = 0.
    cot_t = C.cot(theta_v)
    Vumax = C.VU_MAX_COEFFICIENT * section.concrete.fc * bv * d_v * cot_t / (1.0 + cot_t**2)
    result.add_output(
        "Vumax", Value(Vumax, U_FORCE, "V_u,max", "Web crushing limit", "kN", kN)
    )

    # -- V_u -------------------------------------------------------------------
    Vu_uncapped = Vuc + Vus
    Vu = min(Vu_uncapped, Vumax)
    if Vu_uncapped > Vumax:
        result.note(
            "Capacity governed by web crushing (V_u,max). Additional fitments "
            "will not increase the capacity -- widen the web or raise f'c."
        )

    result.add_intermediate(
        "Vu_uncapped", Value(Vu_uncapped, U_FORCE, "V_uc + V_us", "Before the V_u,max cap",
                             "kN", kN)
    )
    result.add_output("Vu", Value(Vu, U_FORCE, "V_u", "Nominal shear capacity", "kN", kN))

    phi = C.PHI_SHEAR
    basis.add(C.CLAUSE_PHI)
    result.add_output("phi", Value(phi, U_NONE, "phi", "Capacity reduction factor, shear"))
    result.add_output(
        "phiVu", Value(phi * Vu, U_FORCE, "phi.V_u", "Design shear capacity", "kN", kN)
    )

    # -- minimum fitment check -------------------------------------------------
    # Reported always, because a section relying on the higher k_v must have at
    # least minimum fitments for that k_v to be valid.
    if fitment:
        result.add_check(
            Check(
                label="Minimum shear reinforcement, A_sv/s",
                actual=asv_s,
                limit=asv_s_min,
                operator=">=",
                unit="mm^2/mm",
                basis=C.CLAUSE_ASV_MIN,
            )
        )

    return result


def check_shear(
    section: RCSection,
    V_star: float,  # noqa: N803
    M_star: float = 0.0,  # noqa: N803
    method: str = "simplified",
    aggregate_size: float = C.DEFAULT_AGGREGATE_SIZE,
    d: float | None = None,
    Ast: float | None = None,  # noqa: N803
) -> CalcResult:
    """Check a section's shear capacity against a design shear force.

    Basis
    -----
    As :func:`shear_capacity`, plus ``V* <= phi.V_u`` (Cl 2.2.2).

    Parameters
    ----------
    V_star:
        Design shear force (N), magnitude. Take it from
        :meth:`~austruct.analysis.results.BeamResults.shear_at_d_from_support`
        where the support introduces compression, or from
        :attr:`~austruct.analysis.results.BeamResults.max_shear` otherwise.
    M_star:
        Coexisting design moment (N.mm). Used by the general method only.

    Returns
    -------
    CalcResult
    """
    result = shear_capacity(
        section,
        M_star=M_star,
        V_star=V_star,
        method=method,
        aggregate_size=aggregate_size,
        d=d,
        Ast=Ast,
    )
    result.name = f"Shear strength check -- AS 3600:2018 Cl 8.2 ({method} method)"

    result.add_input("Vstar", Value(abs(V_star), U_FORCE, "V*", "Design shear force", "kN", kN))
    result.add_check(
        Check(
            label="Shear strength, V* <= phi.V_u",
            actual=abs(V_star),
            limit=result.get("phiVu"),
            operator="<=",
            unit=U_FORCE,
            basis=ClauseRef(C.STANDARD, "2.2.2", note="Strength requirement"),
            display_factor=kN,
            display_unit="kN",
        )
    )
    return result


def required_shear_reinforcement(
    section: RCSection,
    V_star: float,  # noqa: N803
    M_star: float = 0.0,  # noqa: N803
    method: str = "simplified",
    fitment_diameter: float = 12.0,
    n_legs: int = 2,
    spacings: tuple[float, ...] = (300.0, 250.0, 200.0, 150.0, 125.0, 100.0, 75.0),
    aggregate_size: float = C.DEFAULT_AGGREGATE_SIZE,
) -> CalcResult:
    """Closest practical fitment spacing that satisfies the shear check.

    Searches the supplied spacings from widest to tightest and returns the
    first that passes, rather than solving for an exact ``A_sv/s`` -- because
    the deliverable is a spacing that can be detailed, not a number.

    Parameters
    ----------
    V_star, M_star:
        Design actions (N, N.mm).
    fitment_diameter, n_legs:
        Fitment to try.
    spacings:
        Candidate spacings (mm), widest first.

    Returns
    -------
    CalcResult
        The check for the chosen fitment, with ``outputs["s_req"]``. If no
        candidate spacing works, the result carries the tightest spacing tried
        and FAILS -- it does not raise, because "this section cannot be made to
        work in shear" is a design outcome that belongs in the report.
    """
    chosen: Fitment | None = None
    result: CalcResult | None = None

    for s in spacings:
        trial_fitment = Fitment.from_bars(fitment_diameter, s, n_legs)
        trial = section.with_fitment(trial_fitment)
        candidate = check_shear(
            trial, V_star=V_star, M_star=M_star, method=method, aggregate_size=aggregate_size
        )
        chosen, result = trial_fitment, candidate
        if candidate.passed:
            break

    assert result is not None and chosen is not None  # spacings is never empty

    result.name = "Shear design -- required fitments, AS 3600:2018"
    result.add_output(
        "s_req",
        Value(chosen.spacing, U_LENGTH, "s", f"Fitment spacing ({chosen.designation})"),
    )
    if not result.passed:
        result.note(
            f"No candidate spacing down to {min(spacings):.0f} mm satisfies the "
            "shear check. Increase the web width, the concrete grade, or the "
            "fitment size."
        )
    return result
