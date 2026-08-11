"""Fatigue assessment of RC bridge members to AS 5100.5:2017 Section 12.

Public entry points
-------------------
:func:`stress_range`
    Steel stress range at a section between two moments.
:func:`check_fatigue`
    Stress range against the detail's limit, with an optional cycle-count
    adjustment.
:func:`fatigue_from_envelope`
    The same, taking the range straight off a moving-load envelope.
:func:`check_concrete_fatigue`
    Concrete compressive stress under the fatigue load.

Why fatigue needs the moving-load machinery
-------------------------------------------
Fatigue responds to the **range** of stress, not its peak. That makes it the
one check that cannot be done from a single static analysis: you need the
maximum and the minimum stress a section sees as the vehicle crosses, which is
exactly what a sweep produces. The envelope's ``max_values`` and ``min_values``
at a position are the two ends of the cycle.

A consequence worth stating plainly, because it is counter-intuitive: a heavily
loaded member can be safer in fatigue than a lightly loaded one. What matters is
how much of the stress *varies*, so a girder carrying mostly dead load may have
a smaller range than a lighter member carrying mostly traffic.

The detail governs, not the bar
-------------------------------
A straight bar tolerates roughly twice the stress range of the same bar at a
weld or a coupler, because the stress concentration at the discontinuity is
what starts the crack. :func:`check_fatigue` therefore requires the detail
category as an argument and will not assume one.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] This module is UNVERIFIED. The stress range limits, the reference
         cycle count and the S-N exponent are all recalled rather than
         transcribed. The S-N adjustment in particular may not be permitted by
         AS 5100.5 at all -- see ``constants.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.basis import Basis, ClauseRef
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_LENGTH, U_MOMENT, U_NONE, U_STRESS, kNm
from ...sections.properties import cracked_properties
from ...sections.rc_section import RCSection
from ..rc_common.serviceability import service_steel_stress
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
    description="Fatigue of reinforcement and concrete to AS 5100.5:2017 Section 12",
    envelope_summary=(
        "Non-prestressed; constant-amplitude stress range; cracked section "
        "throughout the cycle; no cumulative damage summation"
    ),
)


def _envelope(section: RCSection) -> Envelope:
    env = Envelope(name="AS 5100.5 fatigue")
    env.add(
        "f'c",
        section.concrete.fc,
        lower=20.0,
        upper=100.0,
        unit=U_STRESS,
        basis=ClauseRef(C.STANDARD, "1.1", note="Range of application"),
    )
    env.note(
        "CONSTANT-amplitude stress range. Real traffic is variable-amplitude, "
        "and a Miner's-rule summation over a load spectrum is NOT performed. "
        "Using the worst single cycle is conservative for the range but takes "
        "no account of how many smaller cycles accompany it."
    )
    env.note(
        "The section is treated as cracked throughout the cycle. Where the "
        "minimum moment closes the crack the true range is smaller, so this "
        "is conservative."
    )
    env.note("Non-prestressed reinforcement only. Tendon fatigue is not covered.")
    return env


@dataclass(frozen=True)
class StressRange:
    """The stress cycle a section sees.

    Attributes
    ----------
    f_max, f_min:
        Steel stress at the two ends of the cycle (MPa). ``f_min`` is zero
        where the section is in compression at that end -- a bar cannot be
        pushed below zero stress once the concrete has cracked around it.
    delta:
        The range, ``f_max - f_min`` (MPa). This is what fatigue responds to.
    M_max, M_min:
        The moments producing them (N.mm).
    reversal:
        Whether the moment changes sign over the cycle. A reversal means both
        faces of the member are cycled, and the face NOT checked here may be
        the critical one.
    """

    f_max: float
    f_min: float
    delta: float
    M_max: float
    M_min: float
    reversal: bool

    def describe(self) -> list[str]:
        lines = [
            f"M_max      = {self.M_max / 1e6:8.1f} kN.m  -> f = {self.f_max:6.1f} MPa",
            f"M_min      = {self.M_min / 1e6:8.1f} kN.m  -> f = {self.f_min:6.1f} MPa",
            f"Range      = {self.delta:6.1f} MPa",
        ]
        if self.reversal:
            lines.append(
                "NOTE: the moment reverses. The opposite face is cycled too "
                "and must be checked separately."
            )
        return lines


def stress_range(
    section: RCSection,
    M_max: float,  # noqa: N803
    M_min: float,  # noqa: N803
) -> StressRange:
    """Steel stress range in the tensile face between two moments.

    Parameters
    ----------
    section:
        The RC section, oriented so the face being checked is in tension under
        ``M_max``.
    M_max, M_min:
        The extremes of the moment cycle at this position (N.mm). Take them
        from a moving-load envelope's ``max_values`` and ``min_values``, and
        include the permanent load in both -- it sets where the cycle sits, and
        although it cancels in the range it decides whether the section is
        cracked at all.

    Returns
    -------
    StressRange

    Notes
    -----
    A negative ``M_min`` puts the checked face into compression. The stress
    there is taken as **zero** rather than as a negative number, because the
    bar unloads to zero and then the concrete takes over -- it does not go into
    meaningful compression while the section is cracked. Taking it as zero
    makes the range the full ``f_max``, which is the conservative reading and
    also flags the reversal.
    """
    if M_max < M_min:
        raise ModelError(
            f"M_max ({M_max:.3g}) is less than M_min ({M_min:.3g}). Pass the "
            "envelope maximum and minimum in that order."
        )

    props = cracked_properties(section)
    f_max = service_steel_stress(section, M_max, props) if M_max > 0 else 0.0
    f_min = service_steel_stress(section, M_min, props) if M_min > 0 else 0.0

    return StressRange(
        f_max=f_max,
        f_min=f_min,
        delta=f_max - f_min,
        M_max=M_max,
        M_min=M_min,
        reversal=(M_max > 0 > M_min),
    )


def stress_range_limit(detail: str, n_cycles: float | None = None) -> float:
    """Limiting stress range for a detail category (MPa).

    Parameters
    ----------
    detail:
        Category name -- ``"straight"``, ``"bent"``, ``"welded"`` or
        ``"coupler"``.
    n_cycles:
        Design cycle count. When given, the reference limit is adjusted by the
        S-N relationship ``(Delta_f)^m . N = constant``. When omitted the
        reference limit is returned unadjusted.

    Raises
    ------
    KeyError
        For an unknown detail category, listing what is available. A typo must
        not fall back to the most permissive category.

    [VECTOR] UNVERIFIED -- and note specifically that the S-N adjustment may
             not be permitted by AS 5100.5, which may instead fix a single
             endurance limit regardless of cycle count. Confirm before relying
             on a limit raised by a low cycle count.
    """
    key = detail.strip().lower()
    try:
        reference = C.FATIGUE_STRESS_RANGE_BY_DETAIL[key]
    except KeyError:
        available = ", ".join(sorted(C.FATIGUE_STRESS_RANGE_BY_DETAIL))
        raise KeyError(
            f"Unknown fatigue detail category {detail!r}. Available: {available}"
        ) from None

    if n_cycles is None:
        return reference
    if n_cycles <= 0:
        raise ModelError(f"Cycle count must be positive, got {n_cycles}")

    ratio = C.FATIGUE_CYCLES_REFERENCE / n_cycles
    return reference * ratio ** (1.0 / C.FATIGUE_SN_EXPONENT)


def check_fatigue(
    section: RCSection,
    M_max: float,  # noqa: N803
    M_min: float,  # noqa: N803
    detail: str = "straight",
    *,
    n_cycles: float | None = None,
    name: str = "",
) -> CalcResult:
    """Steel stress range against the limit for its detail.

    Parameters
    ----------
    section:
        The RC section.
    M_max, M_min:
        Extremes of the moment cycle (N.mm), including permanent load.
    detail:
        Fatigue detail category at the section being checked. Defaults to
        ``"straight"``, the most permissive -- state it explicitly wherever
        bars are bent, welded or coupled near the critical section.
    n_cycles:
        Design cycle count, for the S-N adjustment. Omit to use the reference
        limit unadjusted.

    Returns
    -------
    CalcResult
    """
    result = CalcResult(
        name=name or f"Fatigue, AS 5100.5 -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_envelope(section),
        basis=Basis([C.CLAUSE_FATIGUE, C.CLAUSE_FATIGUE_STEEL]),
    )

    rng = stress_range(section, M_max, M_min)
    limit = stress_range_limit(detail, n_cycles)

    result.add_input("M_max", Value(M_max, U_MOMENT, "M_max", "Cycle maximum", "kN.m", kNm))
    result.add_input("M_min", Value(M_min, U_MOMENT, "M_min", "Cycle minimum", "kN.m", kNm))
    result.add_input("detail", Value(0.0, U_NONE, detail, "Fatigue detail category"))
    if n_cycles is not None:
        result.add_input("n_cycles", Value(n_cycles, U_NONE, "N", "Design cycles"))

    result.add_intermediate("f_max", Value(rng.f_max, U_STRESS, "f_max", "Steel stress, cycle max"))
    result.add_intermediate("f_min", Value(rng.f_min, U_STRESS, "f_min", "Steel stress, cycle min"))
    result.add_output("delta_f", Value(rng.delta, U_STRESS, "d_f", "Steel stress range"))
    result.add_intermediate(
        "delta_f_limit", Value(limit, U_STRESS, "d_f.lim", f"Limit for a {detail} detail")
    )

    result.add_check(
        Check(
            label=f"Stress range <= limit ({detail})",
            actual=rng.delta,
            limit=limit,
            operator="<=",
            unit=U_STRESS,
            basis=C.CLAUSE_FATIGUE_STEEL,
        )
    )

    if rng.reversal:
        result.note(
            "The moment REVERSES over the cycle, so the opposite face of the "
            "member is cycled as well. This check covers one face only -- "
            "invert the section and check the other."
        )
    if detail == "straight":
        result.note(
            "Detail category defaults to 'straight', the most permissive. "
            "State the category explicitly wherever bars are bent, welded or "
            "coupled near this section -- a weld more than halves the limit."
        )
    if n_cycles is not None:
        result.note(
            f"Limit adjusted from the {C.FATIGUE_CYCLES_REFERENCE:.0e}-cycle "
            f"reference by the S-N relationship. [VECTOR] UNVERIFIED -- confirm "
            "AS 5100.5 permits this adjustment rather than fixing a single "
            "endurance limit."
        )
    return result


def _as_envelope(obj):  # noqa: ANN001, ANN202
    """Accept a BeamEnvelope or anything wrapping one.

    ``moving_load_envelope`` returns a ``MovingLoadResult`` that HOLDS an
    envelope rather than being one. Both are natural things to have after a
    sweep, so unwrap rather than making the caller remember the difference.
    """
    return getattr(obj, "envelope", obj)


def fatigue_from_envelope(
    section: RCSection,
    envelope,  # noqa: ANN001 -- BeamEnvelope; avoids importing the analysis layer
    position: float | None = None,
    detail: str = "straight",
    *,
    n_cycles: float | None = None,
    name: str = "",
) -> CalcResult:
    """Fatigue check taking the stress range straight off a moving-load envelope.

    Parameters
    ----------
    section:
        The RC section.
    envelope:
        A :class:`~austruct.analysis.envelope.BeamEnvelope`, or the
        :class:`~austruct.analysis.moving.MovingLoadResult` that wraps one.
        Either is accepted because both are natural things to have in hand
        after a sweep, and requiring the caller to remember which one is
        which serves nobody.
    position:
        Where along the member to check (mm). Defaults to the position of peak
        sagging moment, which is usually but NOT always the worst for fatigue
        -- the largest range can occur where the reversal is greatest rather
        than where the peak is. See :func:`worst_fatigue_position`.
    detail, n_cycles:
        As :func:`check_fatigue`.
    """
    moment = _as_envelope(envelope).moment
    if position is None:
        index = moment.peak_max_index
    else:
        index = int(min(range(len(moment.x)), key=lambda i: abs(moment.x[i] - position)))

    m_max = float(moment.max_values[index])
    m_min = float(moment.min_values[index])

    result = check_fatigue(
        section, m_max, m_min, detail, n_cycles=n_cycles, name=name
    )
    result.add_input(
        "position",
        Value(float(moment.x[index]), U_LENGTH, "x", "Position checked"),
    )
    result.note(
        f"Stress range read from the envelope at x = {moment.x[index] / 1000:.3f} m. "
        "The permanent load must already be included in the envelope -- it "
        "cancels in the range but decides whether the section is cracked."
    )
    return result


def worst_fatigue_position(section: RCSection, envelope) -> tuple[float, float]:  # noqa: ANN001
    """Position of the greatest steel stress range, and that range.

    Worth using rather than assuming the peak-moment section governs. The
    largest range occurs where ``M_max - M_min`` is greatest, which on a
    continuous or multi-span member is often near a point of contraflexure
    rather than at a peak.

    Returns
    -------
    tuple
        ``(position_mm, delta_f_MPa)``.
    """
    moment = _as_envelope(envelope).moment
    props = cracked_properties(section)

    best_pos, best_delta = 0.0, -1.0
    for i, x in enumerate(moment.x):
        m_max = float(moment.max_values[i])
        m_min = float(moment.min_values[i])
        f_max = service_steel_stress(section, m_max, props) if m_max > 0 else 0.0
        f_min = service_steel_stress(section, m_min, props) if m_min > 0 else 0.0
        delta = f_max - f_min
        if delta > best_delta:
            best_pos, best_delta = float(x), delta

    return best_pos, best_delta


def check_concrete_fatigue(
    section: RCSection,
    M_max: float,  # noqa: N803
    *,
    name: str = "",
) -> CalcResult:
    """Concrete compressive stress under the fatigue load against its cap."""
    result = CalcResult(
        name=name or f"Concrete fatigue, AS 5100.5 -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_envelope(section),
        basis=Basis([C.CLAUSE_FATIGUE_CONCRETE]),
    )

    props = cracked_properties(section)
    f_c = abs(M_max) * props.na_depth / props.I
    limit = C.FATIGUE_CONCRETE_STRESS_LIMIT * section.concrete.fc

    result.add_input("M_max", Value(M_max, U_MOMENT, "M_max", "Fatigue load moment", "kN.m", kNm))
    result.add_output("f_c", Value(f_c, U_STRESS, "f_c", "Extreme fibre compressive stress"))
    result.add_check(
        Check(
            label=f"Concrete stress <= {C.FATIGUE_CONCRETE_STRESS_LIMIT:g} f'c",
            actual=f_c,
            limit=limit,
            operator="<=",
            unit=U_STRESS,
            basis=C.CLAUSE_FATIGUE_CONCRETE,
        )
    )
    return result
