"""Serviceability of bridge RC members to AS 5100.5:2017 Sections 8.5 and 8.6.

Public entry points
-------------------
:func:`effective_stiffness`
    ``I_ef`` under the peak service moment.
:func:`check_steel_stress`
    Service steel stress against the exposure-dependent limit -- the crack
    control mechanism a bridge designer reaches for first.
:func:`check_concrete_stress`
    Service concrete compressive stress against its cap.

How this differs from the AS 3600 module
----------------------------------------
The stiffness mechanics are identical and are shared through
``rc_common.serviceability``. What differs is crack control. AS 3600 offers
deemed-to-comply tables of bar diameter and spacing; AS 5100.5 caps the steel
stress directly and varies the cap with the exposure classification, because a
bridge in a coastal splash zone and a bridge over a dry inland highway are not
the same durability problem.

The two are NOT interchangeable, and neither module imports the other's
constants. A member designed to the AS 3600 tables has not been shown to
satisfy AS 5100.5, and vice versa.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] This module is UNVERIFIED. The stress limits by exposure class in
         ``constants.py`` are recalled, not transcribed, and are the values
         most likely to be wrong here.
"""

from __future__ import annotations

from ...core.basis import Basis, ClauseRef
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_I, U_LENGTH, U_MOMENT, U_NONE, U_STRESS, kNm
from ...sections.properties import cracked_properties, uncracked_properties
from ...sections.rc_section import RCSection
from ..rc_common.serviceability import (
    ServiceState,
    effective_second_moment,
    service_steel_stress,
)
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
    description="Serviceability of bridge RC members to AS 5100.5:2017 Sections 8.5, 8.6",
    envelope_summary=(
        "Non-prestressed; prismatic; crack control by steel stress limit, "
        "not by calculated crack width"
    ),
)


def _build_envelope(section: RCSection) -> Envelope:
    env = Envelope(name="AS 5100.5 serviceability")
    env.add(
        "f'c",
        section.concrete.fc,
        lower=20.0,
        upper=100.0,
        unit=U_STRESS,
        basis=ClauseRef(C.STANDARD, "1.1", note="Range of application"),
    )
    env.note("Non-prestressed reinforced concrete only.")
    env.note(
        "Crack control by a limit on the service steel stress. No crack width "
        "is calculated, and no account is taken of bar spacing beyond the "
        "separate maximum-spacing rule."
    )
    env.note(
        "Bridge live load is largely transient. The sustained fraction driving "
        "creep is the caller's decision and is not inferred here."
    )
    return env


def effective_stiffness(
    section: RCSection,
    M_s_max: float,  # noqa: N803
    sigma_cs: float = 0.0,
) -> ServiceState:
    """``I_ef`` under the peak service moment, per AS 5100.5 Cl 8.5.3.

    Mechanically identical to the AS 3600 version, but driven by this
    standard's constants so that a change to one cannot silently move the
    other.
    """
    uncracked = uncracked_properties(section)
    cracked = cracked_properties(section)

    b, d = section.b, section.d
    if b <= 0 or d <= 0:
        raise ModelError("Section width and effective depth must be positive")
    p = section.Ast / (b * d)
    factor = (
        C.IEF_MAX_FACTOR_HIGH_P if p >= C.IEF_MAX_P_THRESHOLD else C.IEF_MAX_FACTOR_LOW_P
    )

    return effective_second_moment(
        section,
        M_s_max,
        exponent=C.IEF_EXPONENT,
        ief_max=factor * uncracked.I,
        sigma_cs=sigma_cs,
        props_cracked=cracked,
        props_uncracked=uncracked,
    )


def steel_stress_limit(exposure: str) -> float:
    """Permitted service steel stress for an exposure classification (MPa).

    Raises
    ------
    KeyError
        For an unrecognised classification, listing the ones available. A
        typo'd exposure class must not silently fall back to a permissive
        default -- that is exactly the error that would let a coastal
        structure be checked against an inland limit.
    """
    key = exposure.strip().upper()
    try:
        return C.STEEL_STRESS_LIMIT_BY_EXPOSURE[key]
    except KeyError:
        available = ", ".join(sorted(C.STEEL_STRESS_LIMIT_BY_EXPOSURE))
        raise KeyError(
            f"Unknown exposure classification {exposure!r}. Available: {available}"
        ) from None


def check_steel_stress(
    section: RCSection,
    M_s: float,  # noqa: N803
    exposure: str,
    *,
    bar_spacing: float | None = None,
    name: str = "",
) -> CalcResult:
    """Service steel stress against the exposure-dependent limit.

    Parameters
    ----------
    section:
        The RC section.
    M_s:
        Service moment for crack control (N.mm). Which combination this is
        depends on the exposure and is the caller's decision.
    exposure:
        AS 5100.5 exposure classification, e.g. ``"B2"``.
    bar_spacing:
        Centre-to-centre spacing of the tensile bars (mm). When supplied, the
        maximum-spacing rule is applied as a second check.

    Returns
    -------
    CalcResult
    """
    result = CalcResult(
        name=name or f"SLS steel stress, AS 5100.5 -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_build_envelope(section),
        basis=Basis([C.CLAUSE_SLS_CRACKING, C.CLAUSE_SLS_STRESS]),
    )

    props = cracked_properties(section)
    f_s = service_steel_stress(section, M_s, props)
    limit = steel_stress_limit(exposure)

    result.add_input("M_s", Value(M_s, U_MOMENT, "M_s", "Service moment", "kN.m", kNm))
    result.add_input("exposure", Value(0.0, U_NONE, exposure, "Exposure classification"))
    result.add_intermediate("d_n", Value(props.na_depth, U_LENGTH, "d_n", "Cracked NA depth"))
    result.add_intermediate("n", Value(props.n, U_NONE, "n", "Modular ratio"))
    result.add_output("f_s", Value(f_s, U_STRESS, "f_s", "Service steel stress"))
    result.add_intermediate(
        "f_s_limit", Value(limit, U_STRESS, "f_s.lim", f"Limit for exposure {exposure}")
    )

    result.add_check(
        Check(
            label=f"Steel stress <= limit for exposure {exposure}",
            actual=f_s,
            limit=limit,
            operator="<=",
            unit=U_STRESS,
            basis=C.CLAUSE_SLS_STRESS,
        )
    )

    if bar_spacing is not None:
        result.add_input(
            "bar_spacing", Value(bar_spacing, U_LENGTH, "s_b", "Bar centre-to-centre spacing")
        )
        result.add_check(
            Check(
                label="Bar spacing <= maximum",
                actual=bar_spacing,
                limit=C.CRACK_MAX_BAR_SPACING,
                operator="<=",
                unit=U_LENGTH,
                basis=C.CLAUSE_SLS_CRACKING,
            )
        )
    else:
        result.note(
            "Bar spacing not supplied, so the maximum-spacing rule has NOT "
            "been checked. The stress limit alone does not control crack "
            "spacing."
        )

    result.note(
        "Crack control by steel stress limit. No crack width has been "
        "calculated, and the stress limits by exposure class are UNVERIFIED."
    )
    return result


def check_concrete_stress(
    section: RCSection,
    M_s: float,  # noqa: N803
    *,
    name: str = "",
) -> CalcResult:
    """Service concrete compressive stress against its cap.

    On the cracked transformed section the extreme fibre stress is::

        f_c = M_s . d_n / I_cr

    The cap guards against excessive creep and internal microcracking under
    sustained compression, which is why it is expressed as a fraction of f'c
    rather than as a strength check.
    """
    result = CalcResult(
        name=name or f"SLS concrete stress, AS 5100.5 -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_build_envelope(section),
        basis=Basis([C.CLAUSE_SLS_STRESS]),
    )

    props = cracked_properties(section)
    f_c = abs(M_s) * props.na_depth / props.I
    limit = C.CONCRETE_COMPRESSIVE_STRESS_SLS * section.concrete.fc

    result.add_input("M_s", Value(M_s, U_MOMENT, "M_s", "Service moment", "kN.m", kNm))
    result.add_intermediate("d_n", Value(props.na_depth, U_LENGTH, "d_n", "Cracked NA depth"))
    result.add_intermediate("I_cr", Value(props.I, U_I, "I_cr", "Cracked transformed"))
    result.add_output("f_c", Value(f_c, U_STRESS, "f_c", "Extreme fibre compressive stress"))

    result.add_check(
        Check(
            label=f"Concrete stress <= {C.CONCRETE_COMPRESSIVE_STRESS_SLS:g} f'c",
            actual=f_c,
            limit=limit,
            operator="<=",
            unit=U_STRESS,
            basis=C.CLAUSE_SLS_STRESS,
        )
    )
    result.note(
        "Stress computed on the CRACKED section. Where the section is in fact "
        "uncracked under this moment the true stress is lower, so this is "
        "conservative."
    )
    return result
