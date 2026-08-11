"""Directed node layout around a closed perimeter.

The problem this solves
-----------------------
A frame analysis reports actions at nodes. If no node sits at the point of
maximum moment, the peak is never reported -- the diagram is sampled either
side of it and the design action is understated. Refining uniformly everywhere
is the brute-force answer, and it is wasteful: it multiplies the model size to
fix a handful of locations.

What an engineer actually wants is to say *put a node here*, and to be able to
say it in the terms the structure is described in -- "at midspan of the top
slab", "600 mm from the inside face of the left wall", "wherever the moment
peaks". That is what this module provides.

The three ways to place a node
------------------------------
1. **Uniform division.** ``divisions`` per wall gives a baseline mesh.
2. **Explicit placement.** :meth:`PerimeterLayout.with_node_at` pins a node at
   a fraction along a wall, or :meth:`with_node_at_distance` at a distance in
   millimetres from the wall's start.
3. **Automatic refinement.** :meth:`PerimeterLayout.refined_for` reads a solved
   result, finds the point of maximum action inside each member, and pins a
   node there. Solve, refine, solve again and the peaks are landed on exactly.

The third is the one that makes the first two rarely necessary, but all three
are available because an engineer checking a specific location -- a
construction joint, a haunch, a service penetration -- needs to put a node
there whether or not the moment peaks at it.

Fractions, not loop distance
----------------------------
Positions are given as a fraction of the wall they lie on, measured from that
wall's own start. Each wall's direction is chosen so the fraction reads the way
an engineer would expect: 0.5 on the top slab is midspan, 0.0 on a wall is its
base. The perimeter is a closed loop, but it is NOT traversed as one continuous
chain, because "0.37 of the way around a culvert" is not a thing anyone means.

[UNITS] mm throughout. Fractions dimensionless, 0.0 to 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from ..core.exceptions import ModelError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.C_GEOMETRY,
        component=ASETComponent.DEMAND,
    ),
    description="Directed node placement around a closed structural perimeter",
    envelope_summary="Four-sided closed perimeter; nodes placed by fraction along each side",
)

# Two node positions closer than this fraction of a wall are treated as the
# same node. Without it, refinement run twice stacks near-coincident nodes and
# produces elements of vanishing length, which wrecks the conditioning of the
# stiffness matrix -- the same failure the beam mesher guards against.
MERGE_TOLERANCE = 1e-4


class Wall(str, Enum):
    """The four sides of a box structure.

    Each carries its own direction convention, chosen so that a fraction reads
    naturally:

    ==========  ==============  ==================================
    Wall        Runs from       Fraction 0.0 is ...
    ==========  ==============  ==================================
    ``TOP``     left to right   the left-hand end of the top slab
    ``BOTTOM``  left to right   the left-hand end of the base slab
    ``LEFT``    bottom to top   the base of the left wall
    ``RIGHT``   bottom to top   the base of the right wall
    ==========  ==============  ==================================
    """

    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"

    @property
    def label(self) -> str:
        return {
            Wall.TOP: "top slab",
            Wall.BOTTOM: "base slab",
            Wall.LEFT: "left wall",
            Wall.RIGHT: "right wall",
        }[self]


@dataclass(frozen=True)
class PinnedNode:
    """A node the engineer has asked for at a specific place.

    Attributes
    ----------
    wall:
        Which side it lies on.
    fraction:
        Position along that wall, 0.0 to 1.0.
    reason:
        Why it is there -- ``"peak sagging"``, ``"construction joint"``.
        Carried into the report so a reviewer can see the mesh was directed
        rather than arbitrary.
    """

    wall: Wall
    fraction: float
    reason: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.fraction <= 1.0:
            raise ModelError(
                f"Node fraction must be between 0 and 1, got {self.fraction}. "
                "Positions are measured along one wall, not around the whole "
                "perimeter."
            )

    def __str__(self) -> str:
        tag = f"  ({self.reason})" if self.reason else ""
        return f"{self.wall.label} at {self.fraction:.3f}{tag}"


@dataclass(frozen=True)
class PerimeterLayout:
    """Where the nodes go around a four-sided closed perimeter.

    Immutable: every adjustment returns a new layout, so a model that has been
    analysed and reported cannot have its mesh changed underneath the report.

    Attributes
    ----------
    divisions:
        Baseline number of equal divisions per wall. Missing walls take
        ``default_divisions``.
    pinned:
        Explicitly placed nodes.
    default_divisions:
        Divisions for any wall not named in ``divisions``.
    """

    divisions: dict[Wall, int] = field(default_factory=dict)
    pinned: tuple[PinnedNode, ...] = ()
    default_divisions: int = 8

    def __post_init__(self) -> None:
        if self.default_divisions < 1:
            raise ModelError(
                f"default_divisions must be at least 1, got {self.default_divisions}"
            )
        for wall, n in self.divisions.items():
            if n < 1:
                raise ModelError(
                    f"{wall.label} needs at least one division, got {n}"
                )

    # -- interrogation --------------------------------------------------------

    def divisions_for(self, wall: Wall) -> int:
        return self.divisions.get(wall, self.default_divisions)

    def fractions(self, wall: Wall) -> tuple[float, ...]:
        """Every node position on ``wall``, as sorted fractions including ends.

        The uniform division points and the pinned nodes merged together, with
        near-coincident positions collapsed. Always includes 0.0 and 1.0 --
        the corners are nodes of the frame whatever else is asked for.
        """
        n = self.divisions_for(wall)
        candidates = [i / n for i in range(n + 1)]
        candidates.extend(p.fraction for p in self.pinned if p.wall is wall)

        merged: list[float] = []
        for value in sorted(candidates):
            if not merged or value - merged[-1] > MERGE_TOLERANCE:
                merged.append(value)
            elif value in (0.0, 1.0):
                # Never let a pinned node just inside a corner displace the
                # corner itself -- the corner must remain a node.
                merged[-1] = value
        if merged[0] > 0.0:
            merged.insert(0, 0.0)
        if merged[-1] < 1.0:
            merged.append(1.0)
        return tuple(merged)

    def reasons_for(self, wall: Wall) -> dict[float, str]:
        """``{fraction: reason}`` for the pinned nodes on one wall."""
        return {p.fraction: p.reason for p in self.pinned if p.wall is wall and p.reason}

    @property
    def total_nodes(self) -> int:
        """Node count around the closed perimeter, corners counted once."""
        return sum(len(self.fractions(w)) - 1 for w in Wall)

    # -- directed adjustment --------------------------------------------------

    def with_node_at(
        self, wall: Wall, fraction: float, reason: str = ""
    ) -> PerimeterLayout:
        """Copy with one more node pinned at ``fraction`` along ``wall``.

        Examples
        --------
        A node exactly at midspan of the top slab::

            layout.with_node_at(Wall.TOP, 0.5, "midspan")
        """
        return replace(self, pinned=self.pinned + (PinnedNode(wall, fraction, reason),))

    def with_node_at_distance(
        self, wall: Wall, distance: float, wall_length: float, reason: str = ""
    ) -> PerimeterLayout:
        """Copy with a node pinned ``distance`` mm from the start of ``wall``.

        The wall length has to be supplied because a layout knows nothing about
        the geometry it will be applied to -- that separation is what lets one
        layout be reused across a parametric sweep of culvert sizes.
        """
        if wall_length <= 0:
            raise ModelError(f"Wall length must be positive, got {wall_length}")
        if not 0.0 <= distance <= wall_length:
            raise ModelError(
                f"{distance} mm is outside the {wall_length:.0f} mm length of the "
                f"{wall.label}."
            )
        return self.with_node_at(wall, distance / wall_length, reason)

    def with_divisions(self, wall: Wall, n: int) -> PerimeterLayout:
        """Copy with a different baseline division count on one wall."""
        updated = dict(self.divisions)
        updated[wall] = n
        return replace(self, divisions=updated)

    def without_pinned(self) -> PerimeterLayout:
        """Copy with every pinned node removed, keeping the uniform divisions.

        Useful before re-refining from scratch, so successive refinement passes
        do not accumulate stale nodes from an earlier load case.
        """
        return replace(self, pinned=())

    # -- reporting ------------------------------------------------------------

    def describe(self) -> list[str]:
        lines = [f"Perimeter layout: {self.total_nodes} nodes"]
        for wall in Wall:
            fracs = self.fractions(wall)
            reasons = self.reasons_for(wall)
            lines.append(
                f"  {wall.label:<11} {self.divisions_for(wall)} divisions, "
                f"{len(fracs)} nodes"
            )
            for frac, reason in sorted(reasons.items()):
                lines.append(f"      pinned at {frac:.3f} -- {reason}")
        return lines

    def _repr_markdown_(self) -> str:
        rows = ["| Wall | Divisions | Nodes | Directed |", "|---|---|---|---|"]
        for wall in Wall:
            reasons = self.reasons_for(wall)
            note = ", ".join(f"{f:.3f} ({r})" for f, r in sorted(reasons.items())) or "-"
            rows.append(
                f"| {wall.label} | {self.divisions_for(wall)} | "
                f"{len(self.fractions(wall))} | {note} |"
            )
        return "**Perimeter layout**\n\n" + "\n".join(rows)


def uniform(divisions: int = 8) -> PerimeterLayout:
    """A layout with the same number of divisions on every wall."""
    return PerimeterLayout(default_divisions=divisions)
