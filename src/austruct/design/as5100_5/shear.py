"""Shear design of reinforced concrete beams to AS 5100.5:2017.

This is a DIFFERENT MODEL from AS 3600:2018
-------------------------------------------
AS 5100.5:2017 uses the AS 3600:2009 family of shear provisions::

    f_cv  = (f'c)^(1/3)  <= 4 MPa
    V_uc  = beta_1 . beta_2 . beta_3 . b_v . d_o . f_cv . (A_st/(b_v.d_o))^(1/3)
    V_us  = (A_sv . f_sy.f . d_o / s) . cot(theta_v)
    V_u,min = V_uc + 0.6 . b_v . d_o
    V_u,max = 0.2 . f'c . b_v . d_o

The concrete contribution depends on the longitudinal steel ratio and on an
absolute size effect through ``beta_1``. There is no ``k_v``, no ``d_v``, and
``theta_v`` is interpolated between 30 and 45 degrees according to how hard the
web is working -- none of which appears in AS 3600:2018.

Do not attempt to reconcile the two. They are different models of the same
phenomenon, adopted at different times.

[UNITS] mm, N, MPa. Angles radians internally, degrees when reported.

[VECTOR] UNVERIFIED. Several constants in ``constants.py`` are flagged
         UNCONFIRMED. Resolve them before any bridge calculation is issued.
"""

from __future__ import annotations

import math

from ...core.basis import Basis, ClauseRef
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_AREA, U_FORCE, U_LENGTH, U_NONE, U_STRESS, kN, to_deg
from ...materials.concrete import FC_MAX_AS5100, FC_MIN_AS5100
from ...sections.rc_section import Fitment, RCSection
from . import constants as C

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Shear capacity of RC beams to AS 5100.5:2017 (AS 3600:2009 family)",
    envelope_summary=(
        "25 <= f'c <= 100 MPa; non-prestressed; vertical fitments only; "
        "no axial force; no torsion"
    ),
)


def concrete_shear_strength(
    section: RCSection,
    d_o: float,
    Ast: float,  # noqa: N803
    has_min_fitments: bool,
    beta_2: float = C.BETA2_DEFAULT,
    beta_3: float = C.BETA3_DEFAULT,
) -> tuple[float, dict[str, float]]:
    """V_uc -- shear strength excluding shear reinforcement.

    Basis
    -----
    AS 5100.5:2017 Cl 8.2.7::

        f_cv   = (f'c)^(1/3), capped at 4 MPa
        beta_1 = 1.1 (1.6 - d_o/1000), >= 1.1 with fitments, >= 0.8 without
        V_uc   = beta_1 . beta_2 . beta_3 . b_v . d_o . f_cv
                 . (A_st / (b_v . d_o))^(1/3)

    [VECTOR] UNVERIFIED -- every coefficient and both beta_1 lower bounds.
    [ASSUMPTION] ``A_st`` is the area of fully anchored longitudinal tensile
                 reinforcement at the section. Bars must be developed a full
                 development length beyond the section to be counted; this is
                 NOT checked here.

    Returns
    -------
    (V_uc, terms)
        ``terms`` carries the intermediate values for reporting.
    """
    fc = section.concrete.fc
    bv = section.bv

    f_cv = min(fc**C.FCV_EXPONENT, C.FCV_CAP)

    beta_1_raw = C.BETA1_FACTOR * (C.BETA1_DEPTH_CONST - d_o / C.BETA1_DEPTH_DIVISOR)
    floor = C.BETA1_MIN_WITH_FITMENTS if has_min_fitments else C.BETA1_MIN_WITHOUT_FITMENTS
    beta_1 = max(beta_1_raw, floor)

    steel_ratio = Ast / (bv * d_o) if (bv * d_o) > 0 else 0.0
    Vuc = beta_1 * beta_2 * beta_3 * bv * d_o * f_cv * steel_ratio ** (1.0 / 3.0)

    return Vuc, {
        "f_cv": f_cv,
        "beta_1": beta_1,
        "beta_1_raw": beta_1_raw,
        "beta_2": beta_2,
        "beta_3": beta_3,
        "steel_ratio": steel_ratio,
    }


def minimum_shear_reinforcement(section: RCSection, fsy_f: float) -> float:
    """(A_sv/s)min per unit length.

    Basis
    -----
    AS 5100.5:2017 Cl 8.2.8::

        (A_sv/s)_min = max(0.06 sqrt(f'c) . b_v / f_sy.f, 0.35 . b_v / f_sy.f)

    [VECTOR] UNVERIFIED -- both coefficients.
    [UNITS] returns mm^2/mm.
    """
    bv = section.bv
    return max(
        C.ASV_MIN_COEFFICIENT * section.concrete.sqrt_fc * bv / fsy_f,
        C.ASV_MIN_FLOOR * bv / fsy_f,
    )


def _theta_v(V_star: float, Vu_min: float, Vu_max: float, phi: float) -> tuple[float, str]:  # noqa: N803
    """Compression strut angle, interpolated on the web demand.

    Basis
    -----
    AS 5100.5:2017 (AS 3600:2009 family): ``theta_v`` varies linearly from
    30 degrees at ``V* = phi.V_u,min`` to 45 degrees at ``V* = phi.V_u,max``.

    [VECTOR] UNVERIFIED -- confirm AS 5100.5:2017 adopts this interpolation.
    [ASSUMPTION] Clamped to the 30-45 degree range outside those bounds. Taking
                 30 degrees below the lower bound maximises ``cot theta_v`` and
                 so maximises the calculated ``V_us``, which is the standard
                 reading of the clause.
    """
    lo, hi = phi * Vu_min, phi * Vu_max
    if hi <= lo:
        return C.THETA_V_MIN, "clamped (V_u,max <= V_u,min)"
    frac = (abs(V_star) - lo) / (hi - lo)
    frac = min(max(frac, 0.0), 1.0)
    theta = C.THETA_V_MIN + frac * (C.THETA_V_MAX - C.THETA_V_MIN)
    return theta, f"interpolated at {frac:.2f} between 30 and 45 deg"


def shear_capacity(
    section: RCSection,
    V_star: float = 0.0,  # noqa: N803
    beta_2: float = C.BETA2_DEFAULT,
    beta_3: float = C.BETA3_DEFAULT,
    d_o: float | None = None,
    Ast: float | None = None,  # noqa: N803
) -> CalcResult:
    """Shear capacity of a reinforced concrete section to AS 5100.5:2017.

    Basis
    -----
    AS 5100.5:2017 Cl 8.2 -- ``V_u = V_uc + V_us``, with ``V_uc`` from Cl 8.2.7,
    ``V_us`` from Cl 8.2.10, and the web crushing limit from Cl 8.2.6.
    Table 2.3.2 for ``phi``.

    Envelope
    --------
    25 MPa <= f'c <= 100 MPa. Non-prestressed. Vertical fitments only. No axial
    force, no torsion.

    Parameters
    ----------
    section:
        The RC section including its fitment.
    V_star:
        Design shear force (N). Needed because ``theta_v`` depends on how hard
        the web is working, so the capacity is not independent of the demand.
    beta_2:
        Axial force factor. 1.0 with no axial force.
    beta_3:
        Factor for loads applied close to a support. 1.0 is conservative.
    d_o, Ast:
        Depth to the outermost tensile bar and the tensile steel area. Default
        to the section's own values.

    Returns
    -------
    CalcResult
        ``outputs["Vu"]``, ``outputs["phiVu"]``, ``outputs["Vuc"]``,
        ``outputs["Vus"]``, ``outputs["Vumin"]``, ``outputs["Vumax"]``.
    """
    env = Envelope(name="AS 5100.5 shear")
    env.add(
        "f'c",
        section.concrete.fc,
        lower=FC_MIN_AS5100,
        upper=FC_MAX_AS5100,
        unit=U_STRESS,
        basis=ClauseRef(C.STANDARD, "1.1", note="Range of application"),
    )
    env.note("Non-prestressed reinforced concrete. No axial force, no torsion.")
    env.note("Vertical fitments only (alpha_v = 90 degrees).")
    env.note(
        "Longitudinal reinforcement assumed fully anchored beyond the section. "
        "Development length is NOT checked."
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

    do = d_o if d_o is not None else section.d_o
    ast = Ast if Ast is not None else section.Ast
    bv = section.bv

    result = CalcResult(
        name="Shear capacity -- AS 5100.5:2017 Cl 8.2",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )

    result.add_input("fc", Value(section.concrete.fc, U_STRESS, "f'c", "Concrete strength"))
    result.add_input("bv", Value(bv, U_LENGTH, "b_v", "Effective web width"))
    result.add_input("do", Value(do, U_LENGTH, "d_o", "Depth to outermost tensile bar"))
    result.add_input("Ast", Value(ast, U_AREA, "A_st", "Tensile reinforcement area"))
    if fitment:
        result.add_input(
            "fitment",
            Value(fitment.asv_per_s, "mm^2/mm", "A_sv/s", f"Fitments: {fitment.designation}"),
        )

    # -- minimum fitments ------------------------------------------------------
    basis.add(C.CLAUSE_ASV_MIN)
    fsy_f = fitment.material.fsy if fitment else 500.0
    asv_s_min = minimum_shear_reinforcement(section, fsy_f)
    asv_s = fitment.asv_per_s if fitment else 0.0
    has_min = asv_s >= asv_s_min - 1e-12
    result.add_intermediate(
        "Asv_s_min", Value(asv_s_min, "mm^2/mm", "(A_sv/s)_min", "Minimum shear reinforcement")
    )

    # -- V_uc -------------------------------------------------------------------
    basis.add(C.CLAUSE_VUC)
    Vuc, terms = concrete_shear_strength(section, do, ast, has_min, beta_2, beta_3)
    result.add_intermediate("fcv", Value(terms["f_cv"], U_STRESS, "f_cv", "(f'c)^(1/3), capped"))
    result.add_intermediate("beta1", Value(terms["beta_1"], U_NONE, "beta_1", "Size effect factor"))
    result.add_intermediate("beta2", Value(terms["beta_2"], U_NONE, "beta_2", "Axial force factor"))
    result.add_intermediate("beta3", Value(terms["beta_3"], U_NONE, "beta_3", "Proximity factor"))
    result.add_intermediate(
        "p_w", Value(terms["steel_ratio"], U_NONE, "A_st/(b_v.d_o)", "Tensile steel ratio")
    )
    result.add_output("Vuc", Value(Vuc, U_FORCE, "V_uc", "Concrete contribution", "kN", kN))

    # -- V_u,min and V_u,max ----------------------------------------------------
    basis.add(C.CLAUSE_VUMIN)
    basis.add(C.CLAUSE_VUMAX)
    Vumin = Vuc + C.VUMIN_COEFFICIENT * bv * do
    Vumax = C.VUMAX_COEFFICIENT * section.concrete.fc * bv * do
    result.add_output("Vumin", Value(Vumin, U_FORCE, "V_u,min", "Minimum shear strength", "kN", kN))
    result.add_output("Vumax", Value(Vumax, U_FORCE, "V_u,max", "Web crushing limit", "kN", kN))

    # -- theta_v and V_us -------------------------------------------------------
    phi = C.PHI_SHEAR
    theta_v, how = _theta_v(V_star, Vumin, Vumax, phi)
    result.add_intermediate(
        "theta_v", Value(to_deg(theta_v), "deg", "theta_v", f"Strut angle ({how})")
    )

    basis.add(C.CLAUSE_VUS)
    if fitment:
        # [BASIS] Cl 8.2.10, fitments perpendicular to the member axis.
        Vus = asv_s * fsy_f * do / math.tan(theta_v)
    else:
        Vus = 0.0
        result.note("No shear reinforcement provided; V_us taken as zero.")
    result.add_output("Vus", Value(Vus, U_FORCE, "V_us", "Fitment contribution", "kN", kN))

    # -- V_u ---------------------------------------------------------------------
    Vu_uncapped = Vuc + Vus
    Vu = min(Vu_uncapped, Vumax)
    if Vu_uncapped > Vumax:
        result.note(
            "Capacity governed by web crushing (V_u,max). Additional fitments "
            "will not increase the capacity -- widen the web or raise f'c."
        )
    result.add_intermediate(
        "Vu_uncapped",
        Value(Vu_uncapped, U_FORCE, "V_uc + V_us", "Before the V_u,max cap", "kN", kN),
    )
    result.add_output("Vu", Value(Vu, U_FORCE, "V_u", "Nominal shear capacity", "kN", kN))

    basis.add(C.CLAUSE_PHI)
    result.add_output("phi", Value(phi, U_NONE, "phi", "Capacity reduction factor, shear"))
    result.add_output(
        "phiVu", Value(phi * Vu, U_FORCE, "phi.V_u", "Design shear capacity", "kN", kN)
    )

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
    beta_2: float = C.BETA2_DEFAULT,
    beta_3: float = C.BETA3_DEFAULT,
    d_o: float | None = None,
    Ast: float | None = None,  # noqa: N803
) -> CalcResult:
    """Check shear capacity against a design shear force, to AS 5100.5:2017.

    Note the capacity depends on ``V*`` through ``theta_v``, so unlike the
    AS 3600 simplified method this is not a fixed capacity being compared
    against a demand -- the two are coupled.

    Parameters
    ----------
    V_star:
        Design shear force (N), magnitude.

    Returns
    -------
    CalcResult
    """
    result = shear_capacity(section, V_star=V_star, beta_2=beta_2, beta_3=beta_3,
                            d_o=d_o, Ast=Ast)
    result.name = "Shear strength check -- AS 5100.5:2017 Cl 8.2"

    result.add_input("Vstar", Value(abs(V_star), U_FORCE, "V*", "Design shear force", "kN", kN))
    result.add_check(
        Check(
            label="Shear strength, V* <= phi.V_u",
            actual=abs(V_star),
            limit=result.get("phiVu"),
            operator="<=",
            unit=U_FORCE,
            basis=ClauseRef(C.STANDARD, "2.3", note="Strength requirement"),
            display_factor=kN,
            display_unit="kN",
        )
    )
    return result


def required_shear_reinforcement(
    section: RCSection,
    V_star: float,  # noqa: N803
    fitment_diameter: float = 12.0,
    n_legs: int = 2,
    spacings: tuple[float, ...] = (300.0, 250.0, 200.0, 150.0, 125.0, 100.0, 75.0),
    beta_2: float = C.BETA2_DEFAULT,
    beta_3: float = C.BETA3_DEFAULT,
) -> CalcResult:
    """Closest practical fitment spacing satisfying the AS 5100.5 shear check.

    See :func:`austruct.design.as3600.shear.required_shear_reinforcement` for
    the rationale -- the deliverable is a detailable spacing, not an exact area.
    """
    chosen: Fitment | None = None
    result: CalcResult | None = None

    for s in spacings:
        trial_fitment = Fitment.from_bars(fitment_diameter, s, n_legs)
        trial = section.with_fitment(trial_fitment)
        candidate = check_shear(trial, V_star=V_star, beta_2=beta_2, beta_3=beta_3)
        chosen, result = trial_fitment, candidate
        if candidate.passed:
            break

    assert result is not None and chosen is not None

    result.name = "Shear design -- required fitments, AS 5100.5:2017"
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
