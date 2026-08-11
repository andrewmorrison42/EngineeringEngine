"""Enveloping analysis results across load combinations.

ASET component 3 -- the post-processing half of fast demand calculation
-----------------------------------------------------------------------
Ferster's brief for component 3 is "retrieving, querying, and enveloping
analysis results in preparation for design", stored in "a file format that
allows me to query them quickly". His worked example carries, per action::

    fact_max, fact_min, fact_max_combo, fact_min_combo

That last pair is the part that matters and the part usually lost: knowing the
governing moment is 552 kN.m is half an answer; knowing it came from ULS2 is
what lets a reviewer reproduce it, and what tells you which combination to
revisit when the design changes. Every envelope here carries the governing
combination alongside the value, and :meth:`BeamEnvelope.to_dict` emits that
shape.

How the grid problem is solved
------------------------------
Each combination has a different load set, so meshed independently each would
produce a different ``x`` array, and enveloping would require interpolation --
which smears exactly the discontinuities (shear steps at point loads) that an
envelope exists to capture. Instead the union of every case's mesh points is
computed up front and handed to every combination via
``Beam.extra_mesh_points``, so all results share one exact grid and the
envelope is element-wise.

[UNITS] As elsewhere: N, mm, MPa, N.mm.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from ..core.basis import FIRST_PRINCIPLES, Basis, ClauseRef
from ..core.contract import CalcResult, Value
from ..core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ..core.registry import REGISTRY
from ..core.units import U_FORCE, U_LENGTH, U_MOMENT, kN, kNm
from ..loads.combinations import LimitState, LoadCase, LoadCombination, filter_relevant
from .beam import Beam
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
    description="Enveloping of beam analysis results across load combinations",
    envelope_summary="Linear elastic superposition; one member at a time",
)


@dataclass
class ActionEnvelope:
    """Maximum and minimum of one action along a member, with governing combos.

    Attributes
    ----------
    x:
        Sample positions (mm), shared across every combination.
    max_values, min_values:
        Envelope of the action at each position.
    max_combo, min_combo:
        Name of the combination producing each extreme, position by position.
    """

    name: str
    x: np.ndarray
    max_values: np.ndarray
    min_values: np.ndarray
    max_combo: list[str]
    min_combo: list[str]
    unit: str = ""
    display_unit: str = ""
    display_factor: float = 1.0

    # -- governing values -----------------------------------------------------

    @property
    def peak_max(self) -> float:
        return float(self.max_values.max())

    @property
    def peak_min(self) -> float:
        return float(self.min_values.min())

    @property
    def peak_max_index(self) -> int:
        return int(np.argmax(self.max_values))

    @property
    def peak_min_index(self) -> int:
        return int(np.argmin(self.min_values))

    @property
    def peak_max_position(self) -> float:
        return float(self.x[self.peak_max_index])

    @property
    def peak_min_position(self) -> float:
        return float(self.x[self.peak_min_index])

    @property
    def peak_max_combo(self) -> str:
        return self.max_combo[self.peak_max_index]

    @property
    def peak_min_combo(self) -> str:
        return self.min_combo[self.peak_min_index]

    @property
    def governing(self) -> float:
        """Largest magnitude in either direction, unsigned.

        The number a symmetric capacity is checked against. For an asymmetric
        section check :attr:`peak_max` and :attr:`peak_min` separately.
        """
        return max(abs(self.peak_max), abs(self.peak_min))

    @property
    def governing_combo(self) -> str:
        """The combination producing :attr:`governing`."""
        return (
            self.peak_max_combo
            if abs(self.peak_max) >= abs(self.peak_min)
            else self.peak_min_combo
        )

    # -- interrogation --------------------------------------------------------

    def max_at(self, position: float) -> float:
        return float(np.interp(position, self.x, self.max_values))

    def min_at(self, position: float) -> float:
        return float(np.interp(position, self.x, self.min_values))

    def governing_at(self, position: float) -> float:
        """Largest magnitude at a position, unsigned."""
        return max(abs(self.max_at(position)), abs(self.min_at(position)))

    def to_dict(self) -> dict:
        """Ferster's ``factored_forces.json`` shape, with positions added."""
        f = self.display_factor
        return {
            "fact_max": self.peak_max / f,
            "fact_min": self.peak_min / f,
            "fact_max_combo": self.peak_max_combo,
            "fact_min_combo": self.peak_min_combo,
            "fact_max_position": self.peak_max_position,
            "fact_min_position": self.peak_min_position,
            "unit": self.display_unit or self.unit,
        }


@dataclass
class ReactionEnvelope:
    """Envelope of one support reaction across combinations."""

    position: float
    label: str
    max_force: float
    min_force: float
    max_combo: str
    min_combo: str
    max_moment: float = 0.0
    min_moment: float = 0.0
    max_moment_combo: str = ""
    min_moment_combo: str = ""

    @property
    def has_moment(self) -> bool:
        return abs(self.max_moment) > 1e-6 or abs(self.min_moment) > 1e-6

    @property
    def uplift(self) -> bool:
        """Whether any combination produces a net downward (uplift) reaction.

        Worth surfacing because an uplift reaction usually means a holding-down
        detail is required, and it is easy to miss when only the maximum
        reaction is reported.
        """
        return self.min_force < 0.0

    def to_dict(self) -> dict:
        out = {
            "fact_max": self.max_force / kN,
            "fact_min": self.min_force / kN,
            "fact_max_combo": self.max_combo,
            "fact_min_combo": self.min_combo,
            "position": self.position,
            "unit": "kN",
        }
        if self.has_moment:
            out["moment"] = {
                "fact_max": self.max_moment / kNm,
                "fact_min": self.min_moment / kNm,
                "fact_max_combo": self.max_moment_combo,
                "fact_min_combo": self.min_moment_combo,
                "unit": "kN.m",
            }
        return out


@dataclass
class BeamEnvelope:
    """Enveloped demands on one member across a set of load combinations."""

    member: str
    limit_state: LimitState
    moment: ActionEnvelope
    shear: ActionEnvelope
    deflection: ActionEnvelope
    reactions: list[ReactionEnvelope] = field(default_factory=list)
    combinations: tuple[LoadCombination, ...] = ()
    case_results: dict[str, BeamResults] = field(default_factory=dict)
    length: float = 0.0

    # -- the numbers the design layer asks for --------------------------------

    @property
    def M_star(self) -> float:  # noqa: N802
        """Governing design moment, unsigned (N.mm)."""
        return self.moment.governing

    @property
    def V_star(self) -> float:  # noqa: N802
        """Governing design shear, unsigned (N)."""
        return self.shear.governing

    @property
    def M_star_sagging(self) -> float:  # noqa: N802
        """Governing sagging moment (N.mm). Zero if never in sagging."""
        return max(self.moment.peak_max, 0.0)

    @property
    def M_star_hogging(self) -> float:  # noqa: N802
        """Governing hogging moment, returned negative (N.mm)."""
        return min(self.moment.peak_min, 0.0)

    def shear_at_d_from_support(self, d: float) -> float:
        """Governing shear at ``d`` inboard of the outermost supports (N).

        Both AS 3600 and AS 5100.5 permit the design shear to be taken at a
        distance from the support where the support introduces compression.
        Carries the same assumption as the single-case version: the offset is
        measured from the support centreline, not its face.
        """
        if not self.reactions:
            raise ValueError("No reactions available")
        first = min(r.position for r in self.reactions)
        last = max(r.position for r in self.reactions)
        return max(
            self.shear.governing_at(min(first + d, self.length)),
            self.shear.governing_at(max(last - d, 0.0)),
        )

    # -- reporting ------------------------------------------------------------

    def summary(self) -> str:
        lines = [
            f"Envelope: {self.member}  [{self.limit_state.value}]",
            f"  {len(self.combinations)} combination(s) analysed",
            "",
        ]
        for combo in self.combinations:
            lines.append(f"    {combo}")
        lines.extend(
            [
                "",
                "Governing actions:",
                f"  M_max (sagging)   {self.moment.peak_max / kNm:10.2f} kN.m  "
                f"at x = {self.moment.peak_max_position / 1000:6.3f} m   "
                f"[{self.moment.peak_max_combo}]",
                f"  M_min (hogging)   {self.moment.peak_min / kNm:10.2f} kN.m  "
                f"at x = {self.moment.peak_min_position / 1000:6.3f} m   "
                f"[{self.moment.peak_min_combo}]",
                f"  V_max             {self.shear.peak_max / kN:10.2f} kN    "
                f"at x = {self.shear.peak_max_position / 1000:6.3f} m   "
                f"[{self.shear.peak_max_combo}]",
                f"  V_min             {self.shear.peak_min / kN:10.2f} kN    "
                f"at x = {self.shear.peak_min_position / 1000:6.3f} m   "
                f"[{self.shear.peak_min_combo}]",
                f"  Deflection max    {self.deflection.peak_max:10.2f} mm    "
                f"at x = {self.deflection.peak_max_position / 1000:6.3f} m   "
                f"[{self.deflection.peak_max_combo}]",
                "",
                "Reactions (positive upward):",
            ]
        )
        for r in self.reactions:
            flag = "   UPLIFT" if r.uplift else ""
            lines.append(
                f"  {r.label:<12} max {r.max_force / kN:9.2f} kN [{r.max_combo}]   "
                f"min {r.min_force / kN:9.2f} kN [{r.min_combo}]{flag}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Queryable factored-forces record, keyed by member name.

        Deliberately the shape from the ASET material, so that a stored
        envelope can be looked up the way the framework describes::

            forces = json.load(open("factored_forces.json"))
            forces["B37"]["moment"]["Mz"]["fact_max"]
        """
        return {
            self.member: {
                "limit_state": self.limit_state.value,
                "combinations": [c.name for c in self.combinations],
                "shear": {"Fy": self.shear.to_dict()},
                "moment": {"Mz": self.moment.to_dict()},
                "deflection": {"dy": self.deflection.to_dict()},
                "reactions": {r.label: r.to_dict() for r in self.reactions},
            }
        }

    def to_calc_result(self) -> CalcResult:
        """Express the envelope through the standard contract."""
        basis = Basis()
        basis.add(
            ClauseRef(
                FIRST_PRINCIPLES,
                note="Linear elastic analysis, results enveloped over load combinations",
            )
        )
        for combo in self.combinations:
            if combo.basis:
                basis.add(combo.basis)

        result = CalcResult(
            name=f"Enveloped demands -- {self.member} ({self.limit_state.value})",
            provenance=PROVENANCE,
            basis=basis,
        )
        result.add_input(
            "n_combos",
            Value(float(len(self.combinations)), "-", "n", "Combinations analysed"),
        )
        result.add_output(
            "M_star_sag",
            Value(self.M_star_sagging, U_MOMENT, "M*_sag",
                  f"Governing sagging moment [{self.moment.peak_max_combo}]", "kN.m", kNm),
        )
        result.add_output(
            "M_star_hog",
            Value(self.M_star_hogging, U_MOMENT, "M*_hog",
                  f"Governing hogging moment [{self.moment.peak_min_combo}]", "kN.m", kNm),
        )
        result.add_output(
            "V_star",
            Value(self.V_star, U_FORCE, "V*",
                  f"Governing shear [{self.shear.governing_combo}]", "kN", kN),
        )
        result.add_output(
            "delta_max",
            Value(self.deflection.peak_max, U_LENGTH, "delta",
                  f"Maximum deflection [{self.deflection.peak_max_combo}]"),
        )
        for r in self.reactions:
            result.add_output(
                f"R_{r.label}",
                Value(r.max_force, U_FORCE, f"R_{r.label}",
                      f"Maximum reaction [{r.max_combo}]", "kN", kN),
            )
            if r.uplift:
                result.note(
                    f"Support {r.label} carries uplift of "
                    f"{abs(r.min_force) / kN:.1f} kN under {r.min_combo}. A "
                    "holding-down detail is required."
                )
        return result


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------


def _union_mesh_points(cases: tuple[LoadCase, ...], length: float) -> tuple[float, ...]:
    """Every mesh point any case would ask for, so all combinations share a grid."""
    points: set[float] = set()
    for case in cases:
        for load in case.loads:
            for p in load.mesh_points():
                if 0.0 <= p <= length:
                    points.add(float(p))
    return tuple(sorted(points))


def _envelope_arrays(
    per_combo: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Element-wise max/min across combinations, with the winning combo name.

    Every array must be the same length -- guaranteed by the shared mesh.
    """
    names = list(per_combo)
    stacked = np.vstack([per_combo[n] for n in names])

    max_idx = np.argmax(stacked, axis=0)
    min_idx = np.argmin(stacked, axis=0)

    max_values = stacked[max_idx, np.arange(stacked.shape[1])]
    min_values = stacked[min_idx, np.arange(stacked.shape[1])]

    return (
        max_values,
        min_values,
        [names[i] for i in max_idx],
        [names[i] for i in min_idx],
    )


def analyse_combinations(
    beam: Beam,
    cases: tuple[LoadCase, ...],
    combinations: tuple[LoadCombination, ...],
    limit_state: LimitState | None = None,
    min_elements: int = 200,
    skip_irrelevant: bool = True,
) -> BeamEnvelope:
    """Analyse a member under every combination and envelope the results.

    Parameters
    ----------
    beam:
        The member. Its own ``loads`` are IGNORED -- the load cases supply the
        loading. Everything else (length, supports, EI, section) is used.
    cases:
        Unfactored load cases, each tagged with its action type.
    combinations:
        Combinations to analyse. Mixing limit states in one call is allowed but
        rarely what you want; see :func:`envelope_by_limit_state`.
    limit_state:
        Recorded on the result. Inferred from the combinations when they agree.
    min_elements:
        Mesh density, as :func:`austruct.analysis.solver.solve`.
    skip_irrelevant:
        Drop combinations no supplied case contributes to. Leaving them in
        analyses an unloaded beam and pollutes the governing-combination record.

    Returns
    -------
    BeamEnvelope

    Raises
    ------
    ValueError
        If no combination has anything to act on.

    Examples
    --------
    >>> cases = (LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),)),
    ...          LoadCase("Q", ActionType.Q, (UDL(magnitude=15 * kN_per_m),)))
    >>> env = analyse_combinations(beam, cases, as1170_uls())
    >>> env.M_star / kNm, env.moment.governing_combo
    """
    if skip_irrelevant:
        combinations = filter_relevant(combinations, cases)
    if not combinations:
        raise ValueError(
            "No load combination acts on any of the supplied load cases. Check "
            "that the cases' action types match the combinations' factors."
        )

    # One grid for every combination -- see the module docstring.
    shared = _union_mesh_points(cases, beam.length)

    results: dict[str, BeamResults] = {}
    for combo in combinations:
        loads = combo.apply(cases)
        trial = replace(beam, loads=loads, extra_mesh_points=shared)
        # refine_peaks=False keeps every combination on one sample grid --
        # see Beam.solve. Resolution comes from min_elements instead.
        results[combo.name] = trial.solve(
            min_elements=min_elements, refine_peaks=False
        )

    if limit_state is None:
        states = {c.limit_state for c in combinations}
        limit_state = states.pop() if len(states) == 1 else LimitState.ULS

    return envelope_from_results(
        results, beam, limit_state=limit_state, combinations=combinations
    )


def envelope_from_results(
    results: dict[str, BeamResults],
    beam: Beam,
    limit_state: LimitState = LimitState.ULS,
    combinations: tuple[LoadCombination, ...] = (),
) -> BeamEnvelope:
    """Envelope a set of named results into one :class:`BeamEnvelope`.

    The shared core of every kind of enveloping this package does. The keys of
    ``results`` become the "governing combination" labels, so what a label
    MEANS depends on the caller:

    - :func:`analyse_combinations` passes combination names, and the label
      answers "which load combination governs?"
    - :func:`austruct.analysis.moving.moving_load_envelope` passes train
      positions, and the same label answers "where was the vehicle?"

    Both questions have the same shape -- "which of these cases produced the
    peak" -- so they share one implementation rather than two that drift.

    Parameters
    ----------
    results:
        Named results, all solved on an IDENTICAL sample grid.
    beam:
        The member, for support positions and labels.
    limit_state, combinations:
        Recorded on the envelope for reporting.

    Raises
    ------
    ValueError
        If the results do not share one grid -- enveloping element-wise across
        differing grids would silently compare different positions.
    """
    if not results:
        raise ValueError("No results to envelope")

    # [CHECK] A shared grid is a precondition, not an aspiration. Refuse rather
    #         than interpolate: interpolation would smear the shear
    #         discontinuities an envelope exists to capture.
    lengths = {len(r.x) for r in results.values()}
    if len(lengths) != 1:
        raise ValueError(
            f"Results have differing sample counts {sorted(lengths)}; the shared "
            "mesh failed. Pass every case the same Beam.extra_mesh_points."
        )

    x = next(iter(results.values())).x

    def build(attr: str, name: str, unit: str, disp_unit: str, disp_factor: float):
        per_case = {n: getattr(r, attr) for n, r in results.items()}
        mx, mn, mx_case, mn_case = _envelope_arrays(per_case)
        return ActionEnvelope(
            name=name,
            x=x,
            max_values=mx,
            min_values=mn,
            max_combo=mx_case,
            min_combo=mn_case,
            unit=unit,
            display_unit=disp_unit,
            display_factor=disp_factor,
        )

    moment = build("moment", "Bending moment", U_MOMENT, "kN.m", kNm)
    shear = build("shear", "Shear force", U_FORCE, "kN", kN)
    deflection = build("deflection", "Deflection", U_LENGTH, "mm", 1.0)

    # -- reactions ------------------------------------------------------------
    reaction_envelopes: list[ReactionEnvelope] = []
    for i, support in enumerate(beam.supports):
        forces = {n: r.reactions[i].force for n, r in results.items()}
        moments = {n: r.reactions[i].moment for n, r in results.items()}
        max_name = max(forces, key=lambda n: forces[n])
        min_name = min(forces, key=lambda n: forces[n])
        max_m_name = max(moments, key=lambda n: moments[n])
        min_m_name = min(moments, key=lambda n: moments[n])
        reaction_envelopes.append(
            ReactionEnvelope(
                position=support.position,
                label=support.label or f"R{i + 1}",
                max_force=forces[max_name],
                min_force=forces[min_name],
                max_combo=max_name,
                min_combo=min_name,
                max_moment=moments[max_m_name],
                min_moment=moments[min_m_name],
                max_moment_combo=max_m_name,
                min_moment_combo=min_m_name,
            )
        )

    return BeamEnvelope(
        member=beam.name or "member",
        limit_state=limit_state,
        moment=moment,
        shear=shear,
        deflection=deflection,
        reactions=reaction_envelopes,
        combinations=combinations,
        case_results=results,
        length=beam.length,
    )


def envelope_by_limit_state(
    beam: Beam,
    cases: tuple[LoadCase, ...],
    combinations: tuple[LoadCombination, ...],
    min_elements: int = 200,
) -> dict[LimitState, BeamEnvelope]:
    """Separate envelopes for each limit state present in ``combinations``.

    The normal way to use this module: strength checks read the ULS envelope,
    deflection checks read the SLS one, and mixing them would compare a
    factored moment against an unfactored deflection limit.
    """
    out: dict[LimitState, BeamEnvelope] = {}
    for state in (LimitState.ULS, LimitState.SLS):
        subset = tuple(c for c in combinations if c.limit_state is state)
        if not subset:
            continue
        relevant = filter_relevant(subset, cases)
        if not relevant:
            continue
        out[state] = analyse_combinations(
            beam, cases, relevant, limit_state=state, min_elements=min_elements
        )
    return out
