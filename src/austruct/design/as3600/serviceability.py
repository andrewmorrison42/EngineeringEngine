"""Serviceability of RC beams and slabs to AS 3600:2018 Sections 8.5 and 8.6.

Public entry points
-------------------
:func:`effective_stiffness`
    ``I_ef`` for a section under its peak service moment, with the AS 3600 cap.
:func:`check_deflection`
    Total and incremental deflection against the Table 2.3.2 limits.
:func:`check_crack_control`
    Bar diameter and spacing against the Table 8.6.1 deemed-to-comply limits.
:func:`check_span_to_depth`
    The Cl 8.5.4 deemed-to-comply ratio, for preliminary sizing.

Why serviceability usually governs
----------------------------------
A beam sized for strength alone is frequently too flexible, and the deflection
check is what sets the depth. It is also the check most often skipped in a
hand calculation because it is tedious, which is a good reason to automate it.

The load split this module insists on
-------------------------------------
Every function takes the **sustained** and **transient** parts of the service
load separately, and takes the **peak** service moment separately again from
both. Three numbers where an engineer might expect one, because:

- creep multiplies only the sustained part;
- cracking is caused by the peak, and is irreversible, so it degrades the
  stiffness that the sustained part then acts on;
- the incremental limit applies to what happens after the finishes go on,
  which is a different subset again.

Collapsing them loses the distinctions the code is built around.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] This module is UNVERIFIED. Every code constant it uses is centralised
         in ``constants.py`` and must be checked against the printed standard.
         The deflection limits in Table 2.3.2 and both crack-control tables are
         transcribed from recollection and are among the least reliable values
         in this package.
"""

from __future__ import annotations

from ...core.basis import Basis, ClauseRef
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import (
    U_I,
    U_LENGTH,
    U_MOMENT,
    U_NONE,
    U_STRESS,
    kNm,
)
from ...materials.reinforcement import Ductility
from ...sections.bar_layout import layer_layout
from ...sections.properties import cracked_properties, uncracked_properties
from ...sections.rc_section import RCSection
from ..rc_common.serviceability import (
    ServiceState,
    creep_multiplier,
    effective_second_moment,
    long_term_deflection,
    scale_deflection_for_stiffness,
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
    description="Deflection and crack control of RC members to AS 3600:2018 Sections 8.5, 8.6",
    envelope_summary=(
        "Non-prestressed; prismatic member; one I_ef for the span; "
        "deemed-to-comply crack control by bar diameter and spacing"
    ),
)


def _build_envelope(section: RCSection) -> Envelope:
    """Validity envelope common to the serviceability entry points."""
    env = Envelope(name="AS 3600 serviceability")
    env.add(
        "f'c",
        section.concrete.fc,
        lower=20.0,
        upper=100.0,
        unit=U_STRESS,
        basis=ClauseRef(C.STANDARD, "1.1.2", note="Range of application"),
    )
    env.note("Non-prestressed reinforced concrete only.")
    env.note(
        "One effective second moment of area for the whole span, computed at "
        "the section of maximum moment. A member whose section changes along "
        "its length needs a region-by-region treatment."
    )
    env.note(
        "Shrinkage-induced curvature is NOT computed. Only the reduction of "
        "M_cr by sigma_cs is available, and only if the caller supplies it."
    )
    env.note(
        "Deemed-to-comply crack control by bar diameter and spacing. No crack "
        "width is calculated."
    )
    return env


# ---------------------------------------------------------------------------
# Effective stiffness
# ---------------------------------------------------------------------------


def ief_max(section: RCSection, uncracked_I: float) -> tuple[float, float]:  # noqa: N803
    """Upper bound on ``I_ef`` and the reinforcement ratio that set it.

    AS 3600 Cl 8.5.3.1 caps ``I_ef`` at the uncracked value for a normally
    reinforced section, but at a reduced fraction of it for a lightly
    reinforced one. The reduction recognises that a lightly reinforced section
    drops almost to ``I_cr`` the instant it cracks, so interpolating from the
    uncracked value overstates its stiffness badly.

    Returns
    -------
    tuple
        ``(I_ef_max, p)`` where ``p = A_st / (b . d)``.

    [VECTOR] UNVERIFIED -- the threshold, both factors, and whether ``I`` in
             the clause means the gross or the uncracked transformed value.
             This implementation uses the uncracked TRANSFORMED value.
    """
    b = section.b
    d = section.d
    if b <= 0 or d <= 0:
        raise ModelError("Section width and effective depth must be positive")
    p = section.Ast / (b * d)
    factor = (
        C.IEF_MAX_FACTOR_HIGH_P if p >= C.IEF_MAX_P_THRESHOLD else C.IEF_MAX_FACTOR_LOW_P
    )
    return factor * uncracked_I, p


def effective_stiffness(
    section: RCSection,
    M_s_max: float,  # noqa: N803
    sigma_cs: float = 0.0,
) -> ServiceState:
    """``I_ef`` under the peak service moment, per AS 3600 Cl 8.5.3.1.

    Parameters
    ----------
    section:
        The RC section.
    M_s_max:
        Maximum service moment ever applied at this section (N.mm). See the
        module docstring on why this is the peak and not the current moment.
    sigma_cs:
        Shrinkage-induced tensile stress on the uncracked section (MPa).
        Reduces ``M_cr``, so omitting it is UNCONSERVATIVE.

    Returns
    -------
    ServiceState
    """
    uncracked = uncracked_properties(section)
    cracked = cracked_properties(section)
    cap, _ = ief_max(section, uncracked.I)
    return effective_second_moment(
        section,
        M_s_max,
        exponent=C.IEF_EXPONENT,
        ief_max=cap,
        sigma_cs=sigma_cs,
        props_cracked=cracked,
        props_uncracked=uncracked,
    )


# ---------------------------------------------------------------------------
# Deflection
# ---------------------------------------------------------------------------


def check_deflection(
    section: RCSection,
    span: float,
    delta_sustained: float,
    delta_transient: float,
    M_s_max: float,  # noqa: N803
    I_analysis: float | None = None,  # noqa: N803
    *,
    sigma_cs: float = 0.0,
    total_limit_ratio: float = C.DEFL_TOTAL_SPAN_RATIO,
    incremental_limit_ratio: float | None = None,
    delta_before_finishes: float = 0.0,
    cantilever: bool = False,
    name: str = "",
) -> CalcResult:
    """Total and incremental deflection against the AS 3600 Table 2.3.2 limits.

    Parameters
    ----------
    section:
        The RC section at the point of maximum moment.
    span:
        Effective span ``L_ef`` (mm). For a cantilever pass the cantilever
        length and set ``cantilever=True``.
    delta_sustained:
        **Immediate** deflection under the sustained service load (mm) -- dead
        load plus the sustained fraction of live load. Computed on
        ``I_analysis``; this function rescales it to ``I_ef``.
    delta_transient:
        Immediate deflection under the non-sustained remainder of the live
        load (mm), on the same ``I_analysis``.
    M_s_max:
        Peak service moment (N.mm), used to determine how much the member has
        cracked.
    I_analysis:
        The second moment of area the two deflections were computed with
        (mm^4). Defaults to the uncracked transformed value, which is what an
        analysis run on gross section properties gives. Pass the value actually
        used -- getting this wrong scales the answer directly.
    sigma_cs:
        Shrinkage-induced tensile stress (MPa).
    total_limit_ratio:
        Denominator of the total-deflection limit, ``L_ef/ratio``.
    incremental_limit_ratio:
        Denominator of the incremental limit. When ``None`` the incremental
        check is skipped, which is correct only where nothing is supported that
        could be damaged.
    delta_before_finishes:
        Deflection already taken up before the finishes were applied (mm), on
        ``I_analysis``. Subtracted from the total to give the increment. Zero
        means the finishes went on before any deflection occurred, which is
        conservative.
    cantilever:
        Applies the cantilever multiplier to the span used in the limits.

    Returns
    -------
    CalcResult

    [ASSUMPTION] Deflections are rescaled from ``I_analysis`` to ``I_ef`` by
                 simple inverse proportion, which is exact for a prismatic
                 member. See ``rc_common.serviceability``.
    """
    result = CalcResult(
        name=name or f"Deflection, AS 3600 -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_build_envelope(section),
        basis=Basis(
            [
                C.CLAUSE_DEFLECTION,
                C.CLAUSE_IEF,
                C.CLAUSE_KCS,
                C.CLAUSE_DEFL_LIMITS,
            ]
        ),
    )

    if span <= 0:
        raise ModelError(f"Span must be positive, got {span}")

    state = effective_stiffness(section, M_s_max, sigma_cs=sigma_cs)
    i_ref = I_analysis if I_analysis is not None else state.I_uncracked

    result.add_input("span", Value(span, U_LENGTH, "L_ef", "Effective span"))
    result.add_input(
        "M_s_max",
        Value(M_s_max, U_MOMENT, "M_s*", "Peak service moment", "kN.m", kNm),
    )
    result.add_input(
        "delta_sustained",
        Value(delta_sustained, U_LENGTH, "d_sus", "Immediate deflection, sustained load"),
    )
    result.add_input(
        "delta_transient",
        Value(delta_transient, U_LENGTH, "d_tr", "Immediate deflection, transient load"),
    )
    result.add_input("I_analysis", Value(i_ref, U_I, "I_an", "Stiffness used in the analysis"))

    # -- effective stiffness ------------------------------------------------
    cap, p = ief_max(section, state.I_uncracked)
    result.add_intermediate("p", Value(p, U_NONE, "p", "A_st/(b.d)"))
    result.add_intermediate("M_cr", Value(state.M_cr, U_MOMENT, "M_cr", "Cracking moment", "kN.m", kNm))
    result.add_intermediate("I_uncracked", Value(state.I_uncracked, U_I, "I", "Uncracked transformed"))
    result.add_intermediate("I_cracked", Value(state.I_cracked, U_I, "I_cr", "Cracked transformed"))
    result.add_intermediate("I_ef_max", Value(cap, U_I, "I_ef.max", "Cap on I_ef"))
    result.add_output("I_ef", Value(state.I_ef, U_I, "I_ef", "Effective second moment of area"))

    if not state.cracked:
        result.note(
            f"M_s* = {M_s_max / kNm:.1f} kN.m does not reach M_cr = "
            f"{state.M_cr / kNm:.1f} kN.m, so the section is taken as uncracked. "
            "This is sensitive to sigma_cs, which is "
            + (f"{sigma_cs:.2f} MPa." if sigma_cs else "ZERO here -- see below.")
        )
    if sigma_cs == 0.0:
        result.note(
            "[ASSUMPTION] Shrinkage stress sigma_cs taken as zero. Shrinkage "
            "reduces M_cr and therefore reduces I_ef, so this is "
            "UNCONSERVATIVE. Supply a real value for issued work."
        )
    if p < C.IEF_MAX_P_THRESHOLD:
        result.note(
            f"p = {p:.4f} is below {C.IEF_MAX_P_THRESHOLD}, so I_ef is capped at "
            f"{C.IEF_MAX_FACTOR_LOW_P:g} I rather than I."
        )

    # -- creep and the long-term total --------------------------------------
    kcs = creep_multiplier(
        section, intercept=C.KCS_INTERCEPT, slope=C.KCS_SLOPE, minimum=C.KCS_MIN
    )
    result.add_intermediate("kcs", Value(kcs, U_NONE, "k_cs", "Long-term multiplier"))

    d_sus = scale_deflection_for_stiffness(delta_sustained, i_ref, state.I_ef)
    d_tr = scale_deflection_for_stiffness(delta_transient, i_ref, state.I_ef)
    d_pre = scale_deflection_for_stiffness(delta_before_finishes, i_ref, state.I_ef)

    parts = long_term_deflection(d_sus, d_tr, kcs)
    result.add_intermediate(
        "delta_sustained_ef", Value(d_sus, U_LENGTH, "d_sus,ef", "Sustained, on I_ef")
    )
    result.add_intermediate(
        "delta_creep", Value(parts["creep"], U_LENGTH, "d_creep", "Creep component")
    )
    result.add_output(
        "delta_immediate",
        Value(parts["immediate"], U_LENGTH, "d_i", "Immediate deflection on I_ef"),
    )
    result.add_output(
        "delta_total", Value(parts["total"], U_LENGTH, "d_tot", "Total long-term deflection")
    )

    # -- limits --------------------------------------------------------------
    limit_span = span * (C.DEFL_CANTILEVER_SPAN_FACTOR if cantilever else 1.0)
    if cantilever:
        result.note(
            f"Cantilever: the span used in the deflection limits is "
            f"{C.DEFL_CANTILEVER_SPAN_FACTOR:g} x {span:.0f} = {limit_span:.0f} mm. "
            "[VECTOR] UNVERIFIED -- confirm AS 3600 treats cantilevers this way."
        )

    total_limit = limit_span / total_limit_ratio
    result.add_check(
        Check(
            label=f"Total deflection <= L_ef/{total_limit_ratio:g}",
            actual=parts["total"],
            limit=total_limit,
            operator="<=",
            unit=U_LENGTH,
            basis=C.CLAUSE_DEFL_LIMITS,
        )
    )

    if incremental_limit_ratio is not None:
        increment = parts["total"] - d_pre
        result.add_output(
            "delta_incremental",
            Value(increment, U_LENGTH, "d_inc", "Deflection after finishes applied"),
        )
        result.add_check(
            Check(
                label=f"Incremental deflection <= L_ef/{incremental_limit_ratio:g}",
                actual=increment,
                limit=limit_span / incremental_limit_ratio,
                operator="<=",
                unit=U_LENGTH,
                basis=C.CLAUSE_DEFL_LIMITS,
            )
        )
        if delta_before_finishes == 0.0:
            result.note(
                "[ASSUMPTION] No deflection had occurred when the finishes were "
                "applied, so the whole total counts as incremental. Conservative."
            )
    else:
        result.note(
            "No incremental limit checked. That is correct only where nothing "
            "supported by this member could be damaged by movement."
        )

    return result


# ---------------------------------------------------------------------------
# Span-to-depth, for preliminary sizing
# ---------------------------------------------------------------------------


def check_span_to_depth(
    section: RCSection,
    span: float,
    limit_ratio: float,
    *,
    name: str = "",
) -> CalcResult:
    """The Cl 8.5.4 deemed-to-comply span-to-depth ratio.

    Parameters
    ----------
    limit_ratio:
        The permissible ``L_ef/d`` for this member. **The caller supplies it**,
        because the clause's expression depends on the support conditions, the
        load, the concrete modulus and the deflection limit, and this package
        does not transcribe it.

    This function therefore does arithmetic and bookkeeping, not code lookup.
    It is offered because the ratio is the first thing an engineer checks when
    sizing, not because it substitutes for :func:`check_deflection`.
    """
    result = CalcResult(
        name=name or f"Span-to-depth ratio -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_build_envelope(section),
        basis=Basis([C.CLAUSE_SPAN_DEPTH]),
    )
    d = section.d
    ratio = span / d
    result.add_input("span", Value(span, U_LENGTH, "L_ef", "Effective span"))
    result.add_input("d", Value(d, U_LENGTH, "d", "Effective depth"))
    result.add_output("ratio", Value(ratio, U_NONE, "L_ef/d", "Span-to-depth ratio"))
    result.add_check(
        Check(
            label="L_ef/d <= limit",
            actual=ratio,
            limit=limit_ratio,
            operator="<=",
            unit=U_NONE,
            basis=C.CLAUSE_SPAN_DEPTH,
        )
    )
    result.note(
        "The limiting ratio was supplied by the caller, not derived from "
        "Cl 8.5.4. This check does not relieve the member of a deflection "
        "calculation unless the caller has satisfied themselves that the "
        "deemed-to-comply route applies."
    )
    return result


# ---------------------------------------------------------------------------
# Crack control
# ---------------------------------------------------------------------------


def _table_limit(table: tuple[tuple[float, float], ...], stress: float) -> float:
    """Largest permitted value from a (stress, limit) table.

    The tables are written as "at a steel stress of X, the limit is Y", with Y
    decreasing as X increases. A stress between two rows takes the stricter
    (lower) limit -- the conservative reading, and the one that avoids claiming
    an interpolation the standard may not permit.

    Returns ``0.0`` where the stress exceeds every row, which fails any check
    that consumes it. That is the intended behaviour: the tables simply do not
    extend that far, and a member whose steel stress is off the end of them is
    not deemed to comply.
    """
    limit = table[0][1]
    for row_stress, row_limit in table:
        if stress <= row_stress:
            return row_limit
        limit = 0.0
    return limit


def check_crack_control(
    section: RCSection,
    M_s: float,  # noqa: N803
    *,
    cover: float | None = None,
    fitment_diameter: float | None = None,
    bar_spacing: float | None = None,
    bar_diameter: float | None = None,
    name: str = "",
) -> CalcResult:
    """Deemed-to-comply crack control, AS 3600 Cl 8.6.1.

    The route implemented is the tabulated one: compute the steel stress under
    the service moment, then require the bar diameter and the bar spacing to be
    no greater than the tables allow at that stress. No crack width is
    calculated.

    Parameters
    ----------
    section:
        The RC section.
    M_s:
        Service moment for crack control (N.mm). Which combination this is
        depends on the exposure classification and is the caller's decision.
    cover, fitment_diameter:
        Used to derive the bar spacing from the section geometry when
        ``bar_spacing`` is not given. Both are needed for the derivation.
    bar_spacing:
        Centre-to-centre spacing of the tensile bars (mm). Supply directly for
        a layout this package cannot infer -- bundled bars, unequal spacing,
        or bars in more than one row.
    bar_diameter:
        Overrides the diameter recorded on the outermost tensile layer.

    Returns
    -------
    CalcResult
    """
    result = CalcResult(
        name=name or f"Crack control, AS 3600 -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_build_envelope(section),
        basis=Basis([C.CLAUSE_CRACK_CONTROL, C.CLAUSE_CRACK_TABLES]),
    )

    props = cracked_properties(section)
    f_s = service_steel_stress(section, M_s, props)

    result.add_input("M_s", Value(M_s, U_MOMENT, "M_s", "Service moment", "kN.m", kNm))
    result.add_intermediate("d_n", Value(props.na_depth, U_LENGTH, "d_n", "Cracked NA depth"))
    result.add_intermediate("n", Value(props.n, U_NONE, "n", "Modular ratio"))
    result.add_output("f_s", Value(f_s, U_STRESS, "f_s", "Service steel stress"))

    # -- which bars are we talking about? -----------------------------------
    outer = max(section.layers, key=lambda x: x.depth) if section.layers else None
    if outer is None:
        raise ModelError("Crack control needs tensile reinforcement; section has none")

    dia = bar_diameter if bar_diameter is not None else outer.diameter
    if dia is None:
        raise ModelError(
            "Crack control needs the bar diameter. The outermost layer was "
            "specified by area alone, so pass bar_diameter explicitly."
        )

    spacing = bar_spacing
    if spacing is None:
        if cover is None or fitment_diameter is None or outer.n_bars is None:
            result.note(
                "Bar spacing was not supplied and could not be derived (needs "
                "cover, fitment diameter and a bar count), so the SPACING CHECK "
                "HAS BEEN OMITTED. Supply bar_spacing to have it applied."
            )
        else:
            layout = layer_layout(section.b, outer.n_bars, dia, cover, fitment_diameter)
            spacing = layout.centre_spacing
            result.add_intermediate(
                "clear_spacing",
                Value(layout.clear_spacing, U_LENGTH, "a_c", "Clear gap between bars"),
            )

    # -- the two table checks ------------------------------------------------
    dia_limit = _table_limit(C.CRACK_BAR_DIAMETER_TABLE, f_s)
    result.add_intermediate(
        "max_bar_diameter", Value(dia_limit, U_LENGTH, "d_b.max", "From Table 8.6.1(A)")
    )
    result.add_check(
        Check(
            label="Bar diameter <= table limit",
            actual=dia,
            limit=dia_limit,
            operator="<=",
            unit=U_LENGTH,
            basis=C.CLAUSE_CRACK_TABLES,
        )
    )
    if dia_limit == 0.0:
        result.note(
            f"Steel stress f_s = {f_s:.0f} MPa is beyond the end of Table "
            "8.6.1(A). The deemed-to-comply route does not apply at this "
            "stress; the check is reported as a failure rather than "
            "extrapolated."
        )

    if spacing is not None:
        if spacing == float("inf"):
            result.note(
                "A single bar in the row, so centre-to-centre spacing does not "
                "apply and the spacing check has been omitted."
            )
        else:
            table_spacing = _table_limit(C.CRACK_BAR_SPACING_TABLE, f_s)
            limit = min(table_spacing, C.CRACK_MAX_BAR_SPACING) if table_spacing else 0.0
            result.add_input(
                "bar_spacing", Value(spacing, U_LENGTH, "s_b", "Bar centre-to-centre spacing")
            )
            result.add_intermediate(
                "max_bar_spacing", Value(limit, U_LENGTH, "s_b.max", "From Table 8.6.1(B)")
            )
            result.add_check(
                Check(
                    label="Bar spacing <= table limit",
                    actual=spacing,
                    limit=limit,
                    operator="<=",
                    unit=U_LENGTH,
                    basis=C.CLAUSE_CRACK_TABLES,
                )
            )

    result.note(
        "Deemed-to-comply route only -- no crack width has been calculated. "
        "Members in an aggressive exposure classification, or where crack "
        "width itself is specified, need the direct calculation which this "
        "package does not implement."
    )
    return result


# ---------------------------------------------------------------------------
# Moment redistribution limit -- AS 3600 Cl 6.2.7
#
# Placed in this module rather than in flexure.py because redistribution is a
# question about how the member behaves as a whole, not about the strength of
# one section.
# ---------------------------------------------------------------------------


def redistribution_limit(kuo: float, ductility: Ductility = Ductility.N) -> float:
    """Maximum permitted moment redistribution, per cent.

    Linear between the two ``k_uo`` bounds: the full allowance at or below
    ``k_uo = 0.2``, tapering to zero at ``k_uo = 0.4``. A deeper neutral axis
    means the concrete crushes sooner, so the hinge delivers less rotation
    before it fails.

    Parameters
    ----------
    kuo:
        Neutral axis depth ratio at the section shedding moment -- the SUPPORT
        section, not the span. This is the input most easily got wrong: the
        allowance is set by the ductility of the hinge that forms, and the
        hinge forms over the support.
    ductility:
        Reinforcement ductility class. Class L permits none.

    Returns
    -------
    float
        Maximum redistribution in per cent, between 0 and the class maximum.

    [VECTOR] UNVERIFIED -- both bounds, the maximum, and the linear taper
             between them.
    """
    if ductility is Ductility.L:
        return C.REDISTRIBUTION_MAX_CLASS_L

    maximum = C.REDISTRIBUTION_MAX_CLASS_N
    if kuo <= C.REDISTRIBUTION_KUO_FULL:
        return maximum
    if kuo >= C.REDISTRIBUTION_KUO_NONE:
        return 0.0

    span = C.REDISTRIBUTION_KUO_NONE - C.REDISTRIBUTION_KUO_FULL
    return maximum * (C.REDISTRIBUTION_KUO_NONE - kuo) / span
