"""Minimum-cost RC section search for a given ULS moment, AS 3600:2018.

This module does not add a design method -- every candidate it proposes is
checked by :func:`austruct.design.as3600.flexure.check_flexure`, the same
function a hand-picked section would go through. What it adds is the search:
step the width and depth over a practical grid, and at each size ask the bar
catalogue for the cheapest arrangement that clears the flexural check, the
ductility limit and the minimum-strength requirement together. Concrete gets
cheaper per unit of capacity as the section deepens; steel does not scale that
way, so the minimum-cost point is a genuine trade-off, not "make it as deep as
possible" or "add more steel" -- the search finds where the two costs cross.

Deliberately excluded from the cost and the search:

- Shear reinforcement. Sizing fitments is a separate exercise once a section
  is chosen; run :mod:`.shear` against the winning candidate.
- Formwork, wastage, labour. ``other_cost_rate`` exists for the engineer to
  add a flat allowance per metre run if that materially changes the ranking;
  it does not attempt to model any of these.
- Multi-layer or unequal-diameter arrangements. Candidates are a single layer
  of one bar size, which is what :func:`~austruct.materials.bar_catalogue.options_for_area`
  proposes. A section that only closes up with two layers will not appear as
  a candidate -- widen the depth range instead of expecting this module to
  find it.

[UNITS] mm, N, MPa, N.mm, as the rest of the package. Cost rates are
        currency per m^3 (concrete) and currency per tonne (steel) -- pick
        any consistent currency, the module never looks at which one.

[VECTOR] Reuses :mod:`.constants` and :mod:`.flexure` for every code value;
         nothing here introduces a new AS 3600 constant. ``STEEL_DENSITY`` is
         a physical constant, not a code value, and is UNVERIFIED as a matter
         of course like everything else in this package.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.contract import CalcResult
from ...core.exceptions import ModelError
from ...materials.bar_catalogue import DEFORMED_DIAMETERS, options_for_area
from ...materials.concrete import Concrete
from ...materials.reinforcement import D500N, Reinforcement
from ...sections.rc_section import RCSection, rc_beam
from .detailing import minimum_clear_spacing
from .flexure import check_flexure, required_steel_area

STEEL_DENSITY = 7850.0
"""Density of reinforcing steel, kg/m^3. Physical constant, not a code value."""


@dataclass(frozen=True)
class SizeRange:
    """A stepped range of practical element sizes to search.

    [UNITS] mm.

    Examples
    --------
    300 mm to 600 mm wide, in 50 mm steps::

        SizeRange(300, 600, 50)
    """

    minimum: float
    maximum: float
    step: float

    def __post_init__(self) -> None:
        if self.step <= 0:
            raise ValueError(f"step must be positive, got {self.step}")
        if self.maximum < self.minimum:
            raise ValueError(
                f"maximum ({self.maximum}) must be >= minimum ({self.minimum})"
            )

    def values(self) -> tuple[float, ...]:
        """Every size in the range, inclusive of both ends.

        The last step is clamped to ``maximum`` even where the range is not an
        exact multiple of ``step``, so the upper bound the caller asked for is
        always searched.
        """
        out = []
        v = self.minimum
        while v < self.maximum:
            out.append(v)
            v += self.step
        out.append(self.maximum)
        return tuple(out)


@dataclass(frozen=True)
class CostRates:
    """Relative unit costs. Any consistent currency; the module never cares
    which one, only the ratio between the two matters for the ranking.

    Parameters
    ----------
    concrete_per_m3:
        Cost per cubic metre of concrete, placed.
    steel_per_tonne:
        Cost per tonne of longitudinal reinforcement, placed. Taken as a
        single rate across all bar diameters -- if the office's actual pricing
        makes small bars materially more expensive per tonne (more fixing
        labour), reflect that by biasing ``diameters`` in
        :class:`SearchBounds` rather than by faking the rate.
    other_cost_rate:
        Flat addition per metre of member length, for whatever the caller
        wants folded in (formwork, an allowance for fitments, wastage). Zero
        by default and does not vary with the candidate, so it never changes
        which candidate governs -- only the reported total.
    """

    concrete_per_m3: float
    steel_per_tonne: float
    other_cost_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.concrete_per_m3 <= 0:
            raise ValueError("concrete_per_m3 must be positive")
        if self.steel_per_tonne <= 0:
            raise ValueError("steel_per_tonne must be positive")


@dataclass(frozen=True)
class SearchBounds:
    """The grid and the reinforcement options the search is allowed to use.

    Parameters
    ----------
    width, depth:
        Element size steps to try.
    diameters:
        Candidate bar diameters. Restrict this to what the job actually
        stocks -- see :data:`~austruct.materials.bar_catalogue.DEFORMED_DIAMETERS`.
    cover:
        Clear cover to the fitment (mm), as in :func:`~austruct.sections.rc_section.rc_beam`.
    fitment_diameter:
        Used only to locate the main bars and to check they fit -- no fitment
        is added to the candidate section or its cost. See the module
        docstring.
    max_bars:
        Upper bound on bars in the single layer this search considers.
    aggregate_size:
        Maximum nominal aggregate size (mm), for the bar clear-spacing check.
    material:
        Reinforcement grade for every candidate.
    """

    width: SizeRange
    depth: SizeRange
    diameters: tuple[int, ...] = DEFORMED_DIAMETERS
    cover: float = 40.0
    fitment_diameter: float = 12.0
    max_bars: int = 8
    aggregate_size: float = 20.0
    material: Reinforcement = D500N


@dataclass(frozen=True)
class SectionCost:
    """One candidate section, priced and checked.

    ``check`` is the full :func:`~.flexure.check_flexure` result for this
    exact section -- the ductility and minimum-strength checks are already
    included, not bolted on afterwards. A ``SectionCost`` never appears in
    :attr:`OptimisationResult.candidates` unless ``check.passed`` is true.
    """

    section: RCSection
    check: CalcResult
    concrete_cost: float
    steel_cost: float
    other_cost: float
    length: float

    @property
    def total_cost(self) -> float:
        return self.concrete_cost + self.steel_cost + self.other_cost

    @property
    def passed(self) -> bool:
        return self.check.passed

    def describe(self) -> str:
        layer = self.section.layers[0]
        return (
            f"{self.section.geometry.b_top:.0f} x {self.section.geometry.D:.0f}  "
            f"{layer.designation:<10}  "
            f"util {self.check.utilisation:.3f}  "
            f"cost {self.total_cost:,.2f} "
            f"(concrete {self.concrete_cost:,.2f} + steel {self.steel_cost:,.2f})"
        )


@dataclass(frozen=True)
class OptimisationResult:
    """The outcome of a cost search for one design moment.

    Attributes
    ----------
    governing:
        The cheapest candidate that passed every check, or ``None`` if the
        grid produced no feasible section -- widen the bounds rather than
        reading that as "no solution exists".
    candidates:
        Every feasible candidate found (one per (b, D) pair that produced a
        passing arrangement), sorted by ``total_cost`` ascending. Kept so the
        engineer can see the next-cheapest options and how close they run,
        not just the single winner.
    trials:
        Number of (b, D) pairs examined.
    infeasible:
        Number of (b, D) pairs that produced no passing arrangement -- too
        shallow to develop M* at all, or no catalogue bar fits the width.
    """

    governing: SectionCost | None
    candidates: tuple[SectionCost, ...]
    trials: int
    infeasible: int

    def describe(self, top: int = 5) -> list[str]:
        lines = [
            f"Searched {self.trials} sizes, {self.trials - self.infeasible} feasible, "
            f"{self.infeasible} infeasible.",
            "",
        ]
        if self.governing is None:
            lines.append("No feasible section found -- widen the search bounds.")
            return lines
        lines.append(f"Governing (minimum cost): {self.governing.describe()}")
        if len(self.candidates) > 1:
            lines.append("")
            lines.append(f"Next cheapest alternatives (of {len(self.candidates)}):")
            for cand in self.candidates[1 : 1 + top]:
                lines.append(f"  {cand.describe()}")
        return lines


def _section_cost(
    section: RCSection,
    length: float,
    rates: CostRates,
) -> tuple[float, float, float]:
    """(concrete_cost, steel_cost, other_cost) for one length of member.

    [UNITS] length in mm.
    """
    concrete_volume_m3 = section.geometry.area * length * 1e-9
    steel_mass_tonnes = section.total_steel_area * length * STEEL_DENSITY * 1e-9 / 1000.0
    concrete_cost = concrete_volume_m3 * rates.concrete_per_m3
    steel_cost = steel_mass_tonnes * rates.steel_per_tonne
    other_cost = rates.other_cost_rate * (length / 1000.0)
    return concrete_cost, steel_cost, other_cost


def _cheapest_arrangement(
    b: float,
    D: float,  # noqa: N803
    concrete: Concrete,
    M_star: float,  # noqa: N803
    bounds: SearchBounds,
) -> RCSection | None:
    """The cheapest single-layer bar arrangement at this (b, D) that clears
    the full flexural check, or ``None`` if nothing at this size does.

    Because every candidate pays the same rate per unit mass, the least-area
    arrangement is also the least-cost one -- so the arrangements returned by
    :func:`options_for_area`, already sorted ascending by area, are tried in
    that order and the first one that passes wins. Passing means clearing
    ``check_flexure`` in full: the bisected estimate from
    :func:`~.flexure.required_steel_area` can round up into an over-reinforced
    (ductility-failing) section, so the estimate is a starting point, not the
    answer.
    """
    trial = rc_beam(b, D, concrete, cover=bounds.cover, fitment_diameter=bounds.fitment_diameter)
    try:
        estimate = required_steel_area(trial, M_star)
    except ValueError:
        return None

    area_required = estimate.get("Ast_req")
    clear_spacing = minimum_clear_spacing(min(bounds.diameters), bounds.aggregate_size)

    arrangements = options_for_area(
        area_required,
        diameters=bounds.diameters,
        max_bars=bounds.max_bars,
    )

    for arrangement in arrangements:
        width_needed = arrangement.width_required(
            bounds.cover, bounds.fitment_diameter, clear_spacing
        )
        if width_needed > b:
            continue

        candidate = rc_beam(
            b,
            D,
            concrete,
            cover=bounds.cover,
            n_bars=arrangement.count,
            diameter=arrangement.diameter,
            fitment_diameter=bounds.fitment_diameter,
            material=bounds.material,
        )
        if check_flexure(candidate, M_star).passed:
            return candidate

    return None


def minimum_cost_section(
    M_star: float,  # noqa: N803
    concrete: Concrete,
    bounds: SearchBounds,
    rates: CostRates,
    length: float = 1000.0,
) -> OptimisationResult:
    """Search a size grid for the cheapest section that carries ``M_star``.

    Every (width, depth) pair in ``bounds`` is tried. At each, the cheapest
    catalogue bar arrangement that fits the width and clears
    :func:`~.flexure.check_flexure` in full (strength, ductility, minimum
    strength together) is kept; pairs where no arrangement qualifies are
    infeasible and excluded, not silently relaxed.

    Parameters
    ----------
    M_star:
        Design bending moment to carry (N.mm), magnitude.
    concrete:
        Concrete grade, fixed across the search. Run the search again at a
        different grade to compare -- grade is a decision the engineer makes,
        not one this function makes for them.
    bounds:
        The size grid and reinforcement options.
    rates:
        Relative unit costs.
    length:
        Member length the cost is priced over (mm). Defaults to 1 m, i.e. a
        cost rate per metre run. Set the actual span for an absolute quote;
        it does not change which candidate governs since every candidate is
        priced over the same length.

    Returns
    -------
    OptimisationResult

    Examples
    --------
    >>> bounds = SearchBounds(width=SizeRange(250, 500, 50), depth=SizeRange(400, 800, 50))
    >>> rates = CostRates(concrete_per_m3=180.0, steel_per_tonne=2200.0)
    >>> result = minimum_cost_section(300 * kNm, concrete(32), bounds, rates)
    >>> result.governing.describe()
    """
    M_star = abs(M_star)
    if length <= 0:
        raise ModelError(f"length must be positive, got {length}")

    candidates: list[SectionCost] = []
    trials = 0
    infeasible = 0

    for D in bounds.depth.values():  # noqa: N806
        for b in bounds.width.values():
            trials += 1
            section = _cheapest_arrangement(b, D, concrete, M_star, bounds)
            if section is None:
                infeasible += 1
                continue

            check = check_flexure(section, M_star)
            concrete_cost, steel_cost, other_cost = _section_cost(section, length, rates)
            candidates.append(
                SectionCost(
                    section=section,
                    check=check,
                    concrete_cost=concrete_cost,
                    steel_cost=steel_cost,
                    other_cost=other_cost,
                    length=length,
                )
            )

    candidates.sort(key=lambda c: c.total_cost)
    governing = candidates[0] if candidates else None

    return OptimisationResult(
        governing=governing,
        candidates=tuple(candidates),
        trials=trials,
        infeasible=infeasible,
    )
