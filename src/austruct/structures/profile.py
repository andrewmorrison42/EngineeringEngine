"""Perimeter geometry: paths that curve, and members that change thickness.

Why this exists
---------------
A box culvert is four straight members of constant thickness, and a frame built
from node coordinates covers it completely. A crown unit is not: its crown is an
arc, its legs are often tapered, and it is thickened into a haunch where the two
meet. None of that fits "four corners and a thickness".

So the perimeter is described here as an ordered list of **segments**, each with

- a **path** -- straight or circular -- that can report a point, a tangent and
  an outward normal at any fraction along itself; and
- a **thickness profile** -- constant, tapered or haunched -- that reports a
  thickness at any fraction.

The frame is then built by walking each segment at the fractions the layout
asks for, taking a straight element between consecutive points and giving that
element the thickness at its own midpoint.

The approximations this makes, and why they are controlled
----------------------------------------------------------
1. **A curved member is modelled as a chain of straight chords.** The chord
   error is second order in the subtended angle, so it falls away as the
   segment is divided and is governed by ``divisions``, not fixed.
2. **A tapered member is modelled as a chain of prismatic elements**, each at
   its own mid-length thickness. Same story: second order, controlled by
   division count.

Both are honest trades: they keep one element type in the solver rather than
introducing curved or tapered element formulations, and the error is something
the user can drive down rather than something baked in. The tests assert the
convergence rather than asserting an accuracy.

Outward normals
---------------
"Outward" means away from the enclosed opening, and it is what earth pressure
acts against. Getting it backwards points the earth pressure into the hole,
which produces a beautifully symmetric and entirely wrong answer.

A single rotation rule cannot supply it. Each segment is given the direction
that makes its own *fraction* read naturally -- 0.5 on the crown is the apex,
0.0 on a leg is its base -- and once the crown runs left-to-right while both
legs run bottom-to-top, the traversal is no longer a consistent loop. The left
normal is outward on the crown and the left leg, and inward on the right leg.

So :class:`Path` supplies the LEFT normal, which is purely geometric, and
:class:`Segment` carries an explicit ``normal_sign`` saying whether that is
outward for this particular side. The same problem, and the same answer, as the
moment sign convention in ``box_culvert.inside_tension_sign``. It is asserted in
the tests rather than trusted.

[UNITS] mm, radians.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

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
    description="Straight and circular perimeter paths with variable member thickness",
    envelope_summary="Plane geometry; circular arcs only; thickness varies along the path",
)

Point = tuple[float, float]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


class Path(ABC):
    """A curve through the plane, parameterised by fraction of its own length."""

    @property
    @abstractmethod
    def length(self) -> float:
        """Length along the path (mm)."""

    @abstractmethod
    def point_at(self, f: float) -> Point:
        """Coordinates at fraction ``f`` along the path."""

    @abstractmethod
    def tangent_at(self, f: float) -> Point:
        """Unit tangent at fraction ``f``, pointing from start towards end."""

    def normal_at(self, f: float) -> Point:
        """Unit LEFT normal at fraction ``f`` -- the tangent rotated
        counter-clockwise by 90 degrees.

        Purely geometric. Whether this points out of the structure or into it
        depends on which way the segment was drawn, which is why
        :attr:`Segment.normal_sign` exists. See the module docstring.
        """
        tx, ty = self.tangent_at(f)
        return (-ty, tx)


@dataclass(frozen=True)
class Line(Path):
    """A straight path between two points."""

    start: Point
    end: Point

    def __post_init__(self) -> None:
        if self.length == 0.0:
            raise ModelError(f"Line has zero length: {self.start} to {self.end}")

    @property
    def length(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    def point_at(self, f: float) -> Point:
        return (
            self.start[0] + f * (self.end[0] - self.start[0]),
            self.start[1] + f * (self.end[1] - self.start[1]),
        )

    def tangent_at(self, f: float) -> Point:  # noqa: ARG002 -- constant along a line
        length = self.length
        return (
            (self.end[0] - self.start[0]) / length,
            (self.end[1] - self.start[1]) / length,
        )


@dataclass(frozen=True)
class Arc(Path):
    """A circular arc from ``start`` to ``end`` with a given rise.

    Parameters
    ----------
    start, end:
        The two ends of the arc (mm).
    rise:
        Perpendicular distance from the chord to the arc at its midpoint (mm).
        Positive bulges to the LEFT of the direction start -> end, which for a
        crown traversed left to right means upward.

    Notes
    -----
    A crown is specified by span and rise, not by radius -- that is what the
    product catalogue gives and what a drawing dimensions. The radius follows::

        R = (a^2 + r^2) / (2 r)      with a = half-chord, r = rise

    which is worth writing down because it is easy to mis-derive and a wrong
    radius produces an arch of the right span and wrong shape.
    """

    start: Point
    end: Point
    rise: float

    def __post_init__(self) -> None:
        if self.rise == 0.0:
            raise ModelError(
                "An arc of zero rise is a straight line -- use Line instead, "
                "which avoids a division by zero in the radius."
            )
        if self._chord == 0.0:
            raise ModelError("Arc start and end coincide")

    @property
    def _chord(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @property
    def radius(self) -> float:
        """Radius of the circle the arc lies on (mm)."""
        a = self._chord / 2.0
        r = abs(self.rise)
        return (a * a + r * r) / (2.0 * r)

    @property
    def half_angle(self) -> float:
        """Half the angle the arc subtends at its centre (radians)."""
        return math.asin(min(1.0, (self._chord / 2.0) / self.radius))

    @property
    def centre(self) -> Point:
        """Centre of the circle."""
        mx = 0.5 * (self.start[0] + self.end[0])
        my = 0.5 * (self.start[1] + self.end[1])
        # Unit vector from start to end, and its left normal.
        ux = (self.end[0] - self.start[0]) / self._chord
        uy = (self.end[1] - self.start[1]) / self._chord
        lx, ly = -uy, ux
        # The centre lies on the far side of the chord from the bulge.
        offset = self.radius - abs(self.rise)
        sign = -1.0 if self.rise > 0 else 1.0
        return (mx + sign * lx * offset, my + sign * ly * offset)

    @property
    def length(self) -> float:
        return 2.0 * self.half_angle * self.radius

    def _angle_at(self, f: float) -> float:
        cx, cy = self.centre
        a0 = math.atan2(self.start[1] - cy, self.start[0] - cx)
        a1 = math.atan2(self.end[1] - cy, self.end[0] - cx)
        # Take the sweep that matches the subtended angle, in the direction
        # that keeps the arc on the bulge side.
        sweep = a1 - a0
        while sweep > math.pi:
            sweep -= 2.0 * math.pi
        while sweep < -math.pi:
            sweep += 2.0 * math.pi
        return a0 + f * sweep

    def point_at(self, f: float) -> Point:
        cx, cy = self.centre
        a = self._angle_at(f)
        return (cx + self.radius * math.cos(a), cy + self.radius * math.sin(a))

    def tangent_at(self, f: float) -> Point:
        cx, cy = self.centre
        a0 = math.atan2(self.start[1] - cy, self.start[0] - cx)
        a1 = math.atan2(self.end[1] - cy, self.end[0] - cx)
        sweep = a1 - a0
        while sweep > math.pi:
            sweep -= 2.0 * math.pi
        while sweep < -math.pi:
            sweep += 2.0 * math.pi

        a = self._angle_at(f)
        # d/df of (cos a, sin a) is (-sin a, cos a) * sweep; normalise and keep
        # the sign of the sweep so the tangent runs start -> end.
        sign = 1.0 if sweep >= 0 else -1.0
        return (-math.sin(a) * sign, math.cos(a) * sign)


# ---------------------------------------------------------------------------
# Thickness
# ---------------------------------------------------------------------------


class Thickness(ABC):
    """Member thickness as a function of fraction along a segment."""

    @abstractmethod
    def at(self, f: float) -> float:
        """Thickness at fraction ``f`` (mm)."""

    @property
    def maximum(self) -> float:
        """Largest thickness anywhere on the segment (mm)."""
        return max(self.at(i / 40.0) for i in range(41))

    @property
    def minimum(self) -> float:
        return min(self.at(i / 40.0) for i in range(41))


@dataclass(frozen=True)
class Constant(Thickness):
    """One thickness the whole way along."""

    value: float

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ModelError(f"Thickness must be positive, got {self.value}")

    def at(self, f: float) -> float:  # noqa: ARG002
        return self.value


@dataclass(frozen=True)
class Tapered(Thickness):
    """Thickness varying linearly from one end to the other.

    A crown unit's legs are commonly thicker at the base than at the springing,
    because the base carries the accumulated thrust and the moment from the
    lateral earth pressure.
    """

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.start <= 0 or self.end <= 0:
            raise ModelError(
                f"Tapered thickness must be positive at both ends, got "
                f"{self.start} and {self.end}"
            )

    def at(self, f: float) -> float:
        return self.start + (self.end - self.start) * f


@dataclass(frozen=True)
class Haunched(Thickness):
    """Constant in the middle, thickening linearly into a haunch at each end.

    This is the crown of a crown unit: thin over most of the arc, thickened
    where it meets the legs, because that is where the moment concentrates and
    where the precast unit needs the bearing area.

    Parameters
    ----------
    mid:
        Thickness away from the haunches (mm).
    haunch:
        Thickness at the very end of the segment (mm).
    extent:
        Fraction of the segment over which each haunch runs. ``0.15`` means the
        outer 15% at each end is haunched and the middle 70% is at ``mid``.
    both_ends:
        Whether the haunch appears at both ends. A crown is symmetric so it
        does; set False for a segment haunched at its start only.
    """

    mid: float
    haunch: float
    extent: float = 0.15
    both_ends: bool = True

    def __post_init__(self) -> None:
        if self.mid <= 0 or self.haunch <= 0:
            raise ModelError("Haunched thicknesses must be positive")
        if not 0.0 <= self.extent <= 0.5:
            raise ModelError(
                f"Haunch extent must be between 0 and 0.5 (half the segment), "
                f"got {self.extent}. Two haunches of more than half each would "
                "overlap in the middle."
            )

    def at(self, f: float) -> float:
        if self.extent == 0.0:
            return self.mid

        # Distance from the nearest haunched end, as a fraction.
        from_start = f
        from_end = 1.0 - f
        d = min(from_start, from_end) if self.both_ends else from_start

        if d >= self.extent:
            return self.mid
        # Linear from `haunch` at the end to `mid` at the haunch limit.
        return self.haunch + (self.mid - self.haunch) * (d / self.extent)


# ---------------------------------------------------------------------------
# A segment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    """One named side of a perimeter: where it runs and how thick it is.

    Attributes
    ----------
    name:
        Identifier, used by :class:`~austruct.structures.perimeter.PerimeterLayout`
        to place nodes on it.
    path:
        Its geometry.
    thickness:
        Its thickness profile.
    normal_sign:
        ``+1`` where the path's LEFT normal points out of the structure, ``-1``
        where it points in. See the module docstring -- no single rotation rule
        gives "outward" once the segments are drawn in the directions that make
        their fractions read naturally.
    """

    name: str
    path: Path
    thickness: Thickness
    normal_sign: float = 1.0

    def __post_init__(self) -> None:
        if self.normal_sign not in (1.0, -1.0):
            raise ModelError(
                f"normal_sign must be +1 or -1, got {self.normal_sign}. It says "
                "which way is out; it is not a scale factor."
            )

    @property
    def length(self) -> float:
        return self.path.length

    def outward_normal_at(self, f: float) -> Point:
        """Unit normal pointing OUT of the structure at fraction ``f``."""
        nx, ny = self.path.normal_at(f)
        return (self.normal_sign * nx, self.normal_sign * ny)

    def describe(self) -> list[str]:
        kind = type(self.path).__name__
        extra = ""
        if isinstance(self.path, Arc):
            extra = (
                f", R = {self.path.radius:.0f} mm, "
                f"{math.degrees(2 * self.path.half_angle):.1f} deg"
            )
        t_min, t_max = self.thickness.minimum, self.thickness.maximum
        t = (
            f"{t_min:.0f} mm"
            if abs(t_max - t_min) < 1e-9
            else f"{t_min:.0f}-{t_max:.0f} mm"
        )
        return [f"{self.name:<12} {kind:<5} {self.length:7.0f} mm{extra}, t = {t}"]
