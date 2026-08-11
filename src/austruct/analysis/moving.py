"""Moving loads -- load trains swept along a member, and influence lines.

The problem
-----------
A traffic load model is not a load, it is a load *pattern with a free position*.
M1600 does not act at midspan; it acts wherever it produces the worst effect,
and that position differs for moment at midspan, for shear at a support, and
for the reaction at a pier. So the analysis has to search.

Two tools, and when to use each:

:func:`moving_load_envelope`
    Sweep the train along the member, solve at every position, and envelope.
    Works for any member, determinate or not, any number of spans. The
    governing "combination" label becomes the governing POSITION, so the answer
    to "what is M*?" comes with "and where was the vehicle?" attached.

:func:`influence_line`
    The response at ONE fixed location as a unit load moves along the member.
    Answers the different question "where should I put a load to maximise
    this?", and its area and peaks are what let you sanity-check a sweep result
    by hand.

Why a sweep rather than influence-line optimisation
---------------------------------------------------
Placing a load train optimally from influence lines is exact and fast for a
determinate member, but it is a separate algorithm per response type, and the
optimum for a train with a UDL component requires integrating the influence
line over the loaded length with the UDL free to break at the sign changes.
A sweep needs none of that: it reuses the solver and the envelope machinery
unchanged, generalises to indeterminate members without alteration, and its
only cost is CPU time -- which for a beam is trivially cheap. The accuracy is
controlled by the step, and the step is reported.

[UNITS] Positions and lengths mm, loads N and N/mm.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from ..core.exceptions import ModelError
from ..core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ..core.registry import REGISTRY
from ..loads.combinations import LimitState
from .beam import Beam
from .envelope import BeamEnvelope, envelope_from_results
from .loading import Load, LoadTrain, PointLoad
from .results import BeamResults

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.DEMAND,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Moving load trains, position sweeps and influence lines",
    envelope_summary="Linear elastic; load pattern rigid; position swept at a finite step",
)


@dataclass
class MovingLoadResult:
    """A moving-load envelope, plus where the train was.

    Wraps :class:`~austruct.analysis.envelope.BeamEnvelope` rather than
    subclassing it, so everything downstream that consumes an envelope --
    the design layer, the report -- works unchanged.
    """

    envelope: BeamEnvelope
    train: LoadTrain
    positions: np.ndarray
    step: float
    notes: list[str] = field(default_factory=list)

    @property
    def M_star(self) -> float:  # noqa: N802
        return self.envelope.M_star

    @property
    def V_star(self) -> float:  # noqa: N802
        return self.envelope.V_star

    def critical_position(self, action: str = "moment") -> float:
        """Datum position (mm) of the train producing the peak of ``action``.

        Parsed back out of the label the envelope recorded.
        """
        env = {
            "moment": self.envelope.moment,
            "shear": self.envelope.shear,
            "deflection": self.envelope.deflection,
        }[action]
        return _position_from_label(env.governing_combo)

    def summary(self) -> str:
        lines = [
            f"Moving load: {self.train.name} over {self.envelope.member}",
            f"  {len(self.positions)} positions at {self.step / 1000:.3f} m steps",
            "",
        ]
        lines.extend(self.envelope.summary().splitlines()[3:])
        for note in self.notes:
            lines.append(f"  NOTE: {note}")
        return "\n".join(lines)


_READ_EPS = 1e-6
"""Offset (mm) at which a diagram is read just to one side of a discontinuity.

Matches the solver's own sampling offset, so the read lands exactly on a
sampled point rather than on an interpolation between the two sides.
"""


def _load_offset(member_length: float) -> float:
    """How far either side of a section to place the bracketing unit loads.

    Not arbitrarily small. A unit load creates a mesh node at its position, so
    an offset of a micron would put two nodes a micron apart and produce an
    element whose stiffness is twelve orders of magnitude above its neighbours.
    One ten-thousandth of the span is close enough to capture the jump and far
    enough to keep the mesh well conditioned.
    """
    return max(1.0, member_length * 1e-4)

_LABEL_PREFIX = "x="


def _label_for(position: float) -> str:
    """Label a sweep position. Parsed back by :func:`_position_from_label`, so
    the two must stay in step -- hence both living here."""
    return f"{_LABEL_PREFIX}{position / 1000:.3f}m"


def _position_from_label(label: str) -> float:
    if not label.startswith(_LABEL_PREFIX):
        raise ValueError(f"Not a sweep position label: {label!r}")
    return float(label[len(_LABEL_PREFIX) : -1]) * 1000.0


def sweep_positions(
    train: LoadTrain,
    member_length: float,
    step: float,
    critical_positions: tuple[float, ...] = (),
) -> np.ndarray:
    """Datum positions to try.

    Runs from fully off the left end to fully off the right end, so that
    partial loading is covered. The worst shear at a support commonly occurs
    with the train partly off the member, and a sweep confined to
    ``0 <= x <= L`` would miss it.

    Beyond the uniform sweep, positions are added that place each axle exactly
    on each ``critical_position`` -- normally the supports. Peak shear occurs
    with an axle right at a support, and a uniform sweep only ever gets within
    half a step of it: on a 20 m span at 50 mm steps that understates the
    support shear of a single axle by about 0.5%. Adding the exact positions
    costs a handful of extra solves and removes the error entirely.

    Parameters
    ----------
    train:
        The load pattern, for its length and axle offsets.
    member_length:
        Length of the member (mm).
    step:
        Uniform datum increment (mm).
    critical_positions:
        Positions at which an axle should be placed exactly.
    """
    if step <= 0:
        raise ModelError(f"Sweep step must be positive, got {step}")

    start = -train.length
    end = member_length
    n = int(np.ceil((end - start) / step)) + 1
    positions = list(np.linspace(start, start + (n - 1) * step, n))

    for target in critical_positions:
        for offset, _ in train.axles:
            datum = target - offset
            if start <= datum <= end:
                positions.append(datum)

    # Merge near-duplicates so the sweep does not solve the same case twice.
    positions.sort()
    merged: list[float] = []
    for value in positions:
        if not merged or value - merged[-1] > 1e-6:
            merged.append(value)
    return np.array(merged)


def moving_load_envelope(
    beam: Beam,
    train: LoadTrain,
    step: float | None = None,
    min_elements: int = 100,
    limit_state: LimitState = LimitState.ULS,
    static_loads: tuple[Load, ...] = (),
) -> MovingLoadResult:
    """Sweep a load train along a member and envelope the results.

    Parameters
    ----------
    beam:
        The member. Its own ``loads`` are ignored; pass anything permanent via
        ``static_loads`` so it is present at every train position.
    train:
        The load pattern to sweep.
    step:
        Datum increment (mm). Defaults to 1/100 of the member length, floored
        at 100 mm. A finer step costs linearly and improves the peak estimate.
    min_elements:
        Mesh density per solve. Lower than the single-analysis default because
        a sweep runs many solves; the diagrams still come from statics, so this
        affects only the deflected shape.
    static_loads:
        Loads present at every position -- self weight, superimposed dead,
        earth pressure. These are NOT swept.

    Returns
    -------
    MovingLoadResult

    Examples
    --------
    >>> result = moving_load_envelope(beam, m1600(), step=250.0)
    >>> result.M_star / kNm, result.critical_position("moment") / 1000
    """
    if step is None:
        step = max(100.0, beam.length / 100.0)

    # Supports are where peak shear and peak reaction occur with an axle
    # exactly on them, so the sweep is given those positions explicitly.
    positions = sweep_positions(
        train,
        beam.length,
        step,
        critical_positions=tuple(s.position for s in beam.supports),
    )

    # One grid for every position, so the envelope is element-wise. Static
    # loads contribute their own mesh points through the normal path.
    shared = train.mesh_points_over_sweep(positions, beam.length)

    results: dict[str, BeamResults] = {}
    skipped = 0
    for pos in positions:
        loads = train.at(float(pos), beam.length)
        if not loads and not static_loads:
            skipped += 1
            continue  # train entirely off the member
        trial = replace(
            beam,
            loads=tuple(loads) + tuple(static_loads),
            extra_mesh_points=shared,
        )
        # refine_peaks=False keeps every train position on one sample grid.
        results[_label_for(float(pos))] = trial.solve(
            min_elements=min_elements, refine_peaks=False
        )

    if not results:
        raise ValueError(
            f"Train {train.name!r} never lands on the member. Check the train "
            "length and the member length."
        )

    envelope = envelope_from_results(results, beam, limit_state=limit_state)

    notes: list[str] = []
    if skipped:
        notes.append(f"{skipped} position(s) skipped with the train clear of the member.")
    notes.append(
        f"Peak values are the best of {len(results)} discrete positions at "
        f"{step / 1000:.3f} m steps; the true peak lies within one step."
    )

    return MovingLoadResult(
        envelope=envelope,
        train=train,
        positions=positions,
        step=step,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Influence lines
# ---------------------------------------------------------------------------


@dataclass
class InfluenceLine:
    """Response at one fixed location as a unit load traverses the member.

    Attributes
    ----------
    response:
        ``"moment"``, ``"shear"`` or ``"reaction"``.
    location:
        Where the response is measured (mm), or the support position for a
        reaction.
    x:
        Unit-load positions (mm).
    values:
        Response per unit load. Multiply by a load to get its contribution.
    """

    response: str
    location: float
    x: np.ndarray
    values: np.ndarray

    @property
    def peak(self) -> float:
        return float(np.abs(self.values).max())

    @property
    def peak_position(self) -> float:
        return float(self.x[int(np.argmax(np.abs(self.values)))])

    @property
    def area(self) -> float:
        """Area under the line.

        Multiplied by a UDL intensity this gives that UDL's contribution when
        applied over the whole member -- the standard hand check on an
        influence line.
        """
        return float(np.trapezoid(self.values, self.x))

    def at(self, position: float) -> float:
        return float(np.interp(position, self.x, self.values))

    def effect_of(self, loads: tuple[tuple[float, float], ...]) -> float:
        """Total effect of ``((position, magnitude), ...)`` point loads.

        The quick way to place a train by hand once the line is known.
        """
        return sum(magnitude * self.at(pos) for pos, magnitude in loads)


def influence_line(
    beam: Beam,
    response: str,
    location: float,
    n_points: int = 101,
    unit_load: float = 1.0,
    min_elements: int = 100,
    side: str = "right",
) -> InfluenceLine:
    """Influence line for one response, by sweeping a unit load.

    Computed numerically rather than from closed-form expressions, so it works
    unchanged on continuous and fixed-ended members where the closed forms do
    not exist.

    Parameters
    ----------
    beam:
        The member. Its own loads are ignored.
    response:
        ``"moment"``, ``"shear"`` or ``"reaction"``.
    location:
        Position at which the response is measured (mm). For ``"reaction"``,
        the position of the support -- the nearest support is used.
    n_points:
        Unit-load positions. Each costs one solve.
    unit_load:
        Magnitude of the travelling load (N). Results are divided by it, so
        this only affects conditioning.
    side:
        ``"left"`` or ``"right"`` -- which side of ``location`` to read a SHEAR
        influence line on. Ignored for moment and reaction.

        The shear influence line is discontinuous at the section it is measured
        at: it steps by 1.0 as the unit load crosses. So "the shear at L/4" is
        two different values depending on which face you stand on, and asking
        for it without saying which returns the average of the two -- a number
        that is not the answer to either question. Reading the diagram a
        hair's breadth to one side makes the line single-valued.

    Returns
    -------
    InfluenceLine

    Examples
    --------
    >>> il = influence_line(beam, "moment", location=4000.0)
    >>> il.peak, il.peak_position          # L/4 = 2000 for a simply supported span

    Shear at the quarter point of a simply supported span, read on the right
    face: ``+0.75`` with the load just to the right, ``-0.25`` just to the left.
    """
    if response not in {"moment", "shear", "reaction"}:
        raise ValueError(
            f"response must be 'moment', 'shear' or 'reaction', got {response!r}"
        )
    if side not in {"left", "right"}:
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")

    # Sample positions: a uniform sweep, plus points either side of the
    # measurement location. Without those the jump in the shear line falls
    # between samples and is smeared by interpolation.
    delta = _load_offset(beam.length)
    xs = set(np.linspace(0.0, beam.length, n_points))
    if response != "reaction":
        for offset in (-delta, delta):
            x = location + offset
            if 0.0 <= x <= beam.length:
                xs.add(x)
    positions = np.array(sorted(xs))
    values = np.zeros(len(positions))

    support_index = 0
    if response == "reaction":
        if not beam.supports:
            raise ModelError("Beam has no supports, so it has no reaction to measure")
        support_index = int(
            np.argmin([abs(s.position - location) for s in beam.supports])
        )

    # Where the response is read. For shear, a hair to one side of the section
    # so the reading is single-valued; see `side` above.
    # The SECTION is the mesh node; the reading is taken a sampling offset to
    # one side of it. Making the offset point itself a node would put two nodes
    # a micron apart -- see _load_offset.
    shared = (location,) if response != "reaction" else ()
    if response == "shear":
        read_at = location + (_READ_EPS if side == "right" else -_READ_EPS)
        read_at = min(max(read_at, 0.0), beam.length)
    else:
        read_at = location

    for i, pos in enumerate(positions):
        trial = replace(
            beam,
            loads=(PointLoad(position=float(pos), magnitude=unit_load),),
            extra_mesh_points=shared,
        )
        result = trial.solve(min_elements=min_elements)
        if response == "moment":
            values[i] = result.moment_at(read_at) / unit_load
        elif response == "shear":
            values[i] = result.shear_at(read_at) / unit_load
        else:
            values[i] = result.reactions[support_index].force / unit_load

    return InfluenceLine(
        response=response, location=location, x=positions, values=values
    )
