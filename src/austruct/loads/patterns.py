"""Pattern loading of continuous members.

The problem
-----------
On a continuous beam, the worst effect at a given point is almost never
produced by loading every span. Loading alternate spans maximises the sagging
moment in the loaded ones; loading the two spans either side of a support
maximises the hogging moment over it. Load every span and you get neither
extreme, and the answer is unconservative in both directions at once.

So the imposed action has to be applied in several arrangements, and every
arrangement is a separate analysis whose results are then enveloped. Permanent
actions are NOT patterned -- self weight is present everywhere, always.

How this fits the existing machinery
------------------------------------
A pattern is just another case dimension, so it goes through the same envelope
core as the load combinations and the moving-load sweep. The governing label
becomes ``"ULS1 [alternate odd]"`` rather than ``"ULS1"``, and the reviewer can
see not only which combination governed but which arrangement of live load did.
That is the same trick :mod:`austruct.analysis.moving` plays with train
positions, and it is why the envelope core was factored out.

What this module does NOT do
----------------------------
It does not decide which patterns are required -- that is a code question, and
the answer differs between AS 3600 and AS 5100. :func:`standard_patterns` offers
the conventional set and names what it assumes.

[UNITS] mm, N, N/mm.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..analysis.loading import (
    AppliedMoment,
    Load,
    PartialUDL,
    PointLoad,
    SelfWeight,
    VaryingUDL,
)
from ..analysis.loading import (
    UDL as UDLoad,
)
from ..core.exceptions import ModelError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from .combinations import ActionType, LoadCase

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.FAST_DEMAND,
    ),
    description="Pattern loading arrangements for continuous members",
    envelope_summary="Imposed actions patterned span by span; permanent actions never patterned",
)


# ---------------------------------------------------------------------------
# Restricting a load to an interval
# ---------------------------------------------------------------------------


def restrict_load(load: Load, start: float, end: float) -> Load | None:
    """The part of ``load`` lying within ``[start, end]``, or None.

    This is the operation pattern loading is built on: "apply the live load to
    span 2 only" means restricting each live load to that span's extent.

    Returns
    -------
    Load or None
        ``None`` where the load falls entirely outside the interval. Callers
        must handle that rather than receiving a zero-magnitude load, because a
        zero load still forces mesh points where nothing acts.

    Raises
    ------
    ModelError
        For a load type this function does not know how to restrict. Failing
        loudly matters here: silently dropping an unrecognised load would
        under-load the member, and nothing downstream would notice.

    Notes
    -----
    A concentrated load exactly on the boundary is INCLUDED. Two adjacent spans
    therefore both claim a load sitting precisely on the support between them.
    That is deliberate -- it is the conservative reading, and a point load at a
    support contributes nothing to either span's moment anyway.
    """
    if end <= start:
        raise ModelError(f"Interval end ({end}) must exceed start ({start})")

    if isinstance(load, PointLoad | AppliedMoment):
        return load if start <= load.position <= end else None

    if isinstance(load, UDLoad | SelfWeight):
        lo = max(start, 0.0)
        hi = min(end, load.length)
        if hi <= lo:
            return None
        return PartialUDL(
            start=lo, end=hi, magnitude=load.magnitude, label=load.label
        )

    if isinstance(load, PartialUDL):
        lo = max(start, load.start)
        hi = min(end, load.end)
        if hi <= lo:
            return None
        return replace(load, start=lo, end=hi)

    if isinstance(load, VaryingUDL):
        lo = max(start, load.start)
        hi = min(end, load.end)
        if hi <= lo:
            return None
        # Interpolate the intensity at the clipped ends so the restricted load
        # lies on the same line as the original -- clipping the extent without
        # re-interpolating would change the load's slope.
        span = load.end - load.start
        w_lo = load.w_start + (load.w_end - load.w_start) * (lo - load.start) / span
        w_hi = load.w_start + (load.w_end - load.w_start) * (hi - load.start) / span
        return replace(load, start=lo, end=hi, w_start=w_lo, w_end=w_hi)

    raise ModelError(
        f"restrict_load does not know how to restrict {type(load).__name__}. "
        "Add a branch for it -- silently dropping it would under-load the "
        "member with nothing downstream to catch it."
    )


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadPattern:
    """One arrangement of imposed load across the spans of a member.

    Attributes
    ----------
    name:
        Short label, e.g. ``"alternate odd"``. Becomes part of the governing
        case name in the envelope, so keep it readable.
    loaded:
        One flag per span, in order from the left. ``True`` means the imposed
        load acts on that span.
    purpose:
        What this arrangement is trying to maximise, in words. Carried into
        reports so a reviewer knows why the arrangement was considered.
    """

    name: str
    loaded: tuple[bool, ...]
    purpose: str = ""

    def __post_init__(self) -> None:
        if not self.loaded:
            raise ModelError("A load pattern must cover at least one span")

    @property
    def n_spans(self) -> int:
        return len(self.loaded)

    @property
    def fraction_loaded(self) -> float:
        return sum(self.loaded) / len(self.loaded)

    def __str__(self) -> str:
        marks = "".join("X" if f else "." for f in self.loaded)
        return f"{self.name} [{marks}]"


def span_extents(support_positions: tuple[float, ...]) -> tuple[tuple[float, float], ...]:
    """Span start/end pairs from a sorted list of vertical support positions."""
    ordered = tuple(sorted(support_positions))
    if len(ordered) < 2:
        raise ModelError(
            "Pattern loading needs at least two vertical supports -- a single "
            "span with one support is not a continuous member."
        )
    return tuple(zip(ordered, ordered[1:]))


def all_spans_loaded(n_spans: int) -> LoadPattern:
    """Every span loaded. The base case, and often not the worst one."""
    return LoadPattern(
        name="all spans",
        loaded=(True,) * n_spans,
        purpose="Baseline; maximises reactions and total load",
    )


def alternate_spans(n_spans: int, start_loaded: bool = True) -> LoadPattern:
    """Alternate spans loaded, maximising sagging in the loaded ones.

    Parameters
    ----------
    start_loaded:
        Whether span 1 carries load. The two variants (odd and even spans
        loaded) are both needed -- neither alone covers every span.
    """
    loaded = tuple(
        (i % 2 == 0) == start_loaded for i in range(n_spans)
    )
    which = "odd" if start_loaded else "even"
    return LoadPattern(
        name=f"alternate {which}",
        loaded=loaded,
        purpose=f"Maximum sagging moment in the {which}-numbered spans",
    )


def adjacent_pair(n_spans: int, support_index: int) -> LoadPattern:
    """The two spans either side of an interior support.

    Maximises the hogging moment over that support, and the shear either side
    of it.

    Parameters
    ----------
    support_index:
        Which interior support, numbered from 1. Support ``i`` sits between
        span ``i`` and span ``i + 1``.
    """
    if not 1 <= support_index <= n_spans - 1:
        raise ModelError(
            f"Support index {support_index} is not an interior support of a "
            f"{n_spans}-span member. Interior supports are numbered 1 to "
            f"{n_spans - 1}."
        )
    loaded = tuple(i in (support_index - 1, support_index) for i in range(n_spans))
    return LoadPattern(
        name=f"pair at support {support_index}",
        loaded=loaded,
        purpose=f"Maximum hogging moment over interior support {support_index}",
    )


def standard_patterns(n_spans: int) -> tuple[LoadPattern, ...]:
    """The conventional set of arrangements for a continuous member.

    Comprises:

    - all spans loaded;
    - both alternate-span arrangements (for maximum sagging);
    - one adjacent-pair arrangement per interior support (for maximum hogging).

    For a single span this returns just the one fully loaded arrangement --
    there is nothing to pattern.

    [ASSUMPTION] This is the conventional engineering set, NOT a transcription
                 of any clause. AS 3600 and AS 5100 each state their own
                 requirements, including whether the imposed load may be
                 reduced when patterned. Confirm the required set for the
                 standard in use, and supply your own patterns if it differs.
    """
    if n_spans < 1:
        raise ModelError(f"A member must have at least one span, got {n_spans}")
    if n_spans == 1:
        return (all_spans_loaded(1),)

    patterns = [
        all_spans_loaded(n_spans),
        alternate_spans(n_spans, start_loaded=True),
        alternate_spans(n_spans, start_loaded=False),
    ]
    patterns.extend(adjacent_pair(n_spans, i) for i in range(1, n_spans))
    return tuple(patterns)


# ---------------------------------------------------------------------------
# Applying a pattern to a load case
# ---------------------------------------------------------------------------


def apply_pattern(
    case: LoadCase,
    pattern: LoadPattern,
    spans: tuple[tuple[float, float], ...],
) -> LoadCase:
    """Restrict a load case to the spans a pattern marks as loaded.

    Parameters
    ----------
    case:
        The imposed load case. Its action type is preserved so the combination
        factors still apply.
    pattern:
        The arrangement.
    spans:
        Span extents from :func:`span_extents`.

    Returns
    -------
    LoadCase
        A new case, named ``"<case> [<pattern>]"``, carrying only the loads
        that fall on the loaded spans. May carry no loads at all if the pattern
        loads no span the case acts on.
    """
    if pattern.n_spans != len(spans):
        raise ModelError(
            f"Pattern covers {pattern.n_spans} spans but the member has "
            f"{len(spans)}. The pattern was built for a different member."
        )

    kept: list[Load] = []
    for loaded, (start, end) in zip(pattern.loaded, spans):
        if not loaded:
            continue
        for load in case.loads:
            piece = restrict_load(load, start, end)
            if piece is not None:
                kept.append(piece)

    return LoadCase(
        name=f"{case.name} [{pattern.name}]",
        action=case.action,
        loads=tuple(kept),
    )


def patterned_case_sets(
    cases: tuple[LoadCase, ...],
    patterns: tuple[LoadPattern, ...],
    spans: tuple[tuple[float, float], ...],
    patterned_actions: frozenset[ActionType] = frozenset({ActionType.Q}),
) -> tuple[tuple[str, tuple[LoadCase, ...]], ...]:
    """Build one full set of load cases per pattern.

    Permanent actions pass through untouched; only the actions named in
    ``patterned_actions`` are rearranged. That default is the important part:
    **self weight is not patterned**, because it is physically present on every
    span whatever the imposed load is doing. Patterning it would model a beam
    with sections of itself missing.

    Parameters
    ----------
    cases:
        All unfactored load cases.
    patterns:
        The arrangements to apply.
    spans:
        Span extents from :func:`span_extents`.
    patterned_actions:
        Which action types get patterned. Defaults to imposed action ``Q``
        alone.

    Returns
    -------
    tuple
        ``((pattern_name, cases), ...)`` -- one entry per pattern, each a
        complete set of cases ready for
        :func:`austruct.analysis.envelope.analyse_combinations`.
    """
    if not patterns:
        raise ModelError("No patterns supplied")

    sets: list[tuple[str, tuple[LoadCase, ...]]] = []
    for pattern in patterns:
        built: list[LoadCase] = []
        for case in cases:
            if case.action in patterned_actions:
                patterned = apply_pattern(case, pattern, spans)
                if patterned.loads:
                    built.append(patterned)
            else:
                built.append(case)
        sets.append((pattern.name, tuple(built)))
    return tuple(sets)
