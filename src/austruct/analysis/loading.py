"""Loads applied to a beam.

SIGN CONVENTION -- read this before using anything in this package
------------------------------------------------------------------
One convention, applied everywhere, stated once:

===========================  ==================================================
Downward load                POSITIVE. A UDL of 25 kN/m is ``+25``.
Downward deflection          POSITIVE. A sagging beam deflects positive.
Sagging bending moment       POSITIVE (tension in the bottom fibre).
Shear force                  POSITIVE where the resultant of forces to the
                             LEFT of the section acts UPWARD.
Applied concentrated moment  POSITIVE where it INCREASES the sagging moment
                             in the beam to its right.
Support reaction             Reported POSITIVE UPWARD.
===========================  ==================================================

This is the convention an Australian structural engineer draws diagrams with,
so it is the one the toolkit uses at its boundary. The solver works internally
in an upward-positive frame and converts once, at a single point, in
``solver.py``. Do not introduce a second conversion anywhere else.

[UNITS] Positions and lengths mm. Point loads N. Distributed loads N/mm
        (identically kN/m -- see core/units.py). Moments N.mm.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import ClassVar

from ..core.exceptions import ModelError


@dataclass(frozen=True)
class Load(ABC):
    """Base class for anything applied to a beam.

    Subclasses answer two families of question:

    1. **For the solver** -- where does the mesh need nodes, and what is the
       load intensity or concentrated action at a point.
    2. **For the diagrams** -- what is the resultant of the portion of this
       load lying to the left of a section, and its moment about that section.

    The second family is what makes exact bending moment and shear force
    diagrams possible by statics once reactions are known, rather than by
    reading them off a finite element mesh.
    """

    label: str = ""

    _SCALABLE_FIELDS: ClassVar[tuple[str, ...]] = ()
    """Fields multiplied by a load factor. Declared per subclass so that
    :meth:`scale` lives in one place rather than being reimplemented seven
    times -- and so that adding a load type with an unscaled field (a position,
    an extent) cannot silently scale it."""

    def scale(self, factor: float) -> Load:
        """Return a copy with every magnitude multiplied by ``factor``.

        This is what a load combination does to a load case: 1.2 G means every
        load in the permanent case scaled by 1.2. Positions and extents are
        untouched.

        Raises
        ------
        NotImplementedError
            If the subclass has not declared which of its fields scale. Failing
            loudly is deliberate -- a load type that silently refused to scale
            would drop out of every factored combination.
        """
        if not self._SCALABLE_FIELDS:
            raise NotImplementedError(
                f"{type(self).__name__} does not declare _SCALABLE_FIELDS, so it "
                "cannot be used in a load combination."
            )
        updates = {name: getattr(self, name) * factor for name in self._SCALABLE_FIELDS}
        return replace(self, **updates)

    @abstractmethod
    def mesh_points(self) -> list[float]:
        """Positions where the mesh must place a node.

        Any discontinuity in load intensity, and any concentrated action.
        Getting this wrong degrades accuracy rather than causing a wrong
        answer, but degrades it silently -- so be generous.
        """

    @abstractmethod
    def intensity(self, x: float) -> float:
        """Distributed load intensity at ``x`` (N/mm, downward positive).

        Zero for concentrated actions.
        """

    @abstractmethod
    def point_forces(self) -> list[tuple[float, float]]:
        """Concentrated forces as ``[(position, magnitude_down), ...]``."""

    @abstractmethod
    def point_moments(self) -> list[tuple[float, float]]:
        """Concentrated moments as ``[(position, magnitude), ...]``."""

    @abstractmethod
    def resultant_left_of(self, x: float) -> tuple[float, float]:
        """Resultant of the part of this load left of ``x``.

        Returns
        -------
        (force_down, moment_about_x)
            ``force_down`` is the downward resultant (N).
            ``moment_about_x`` is its moment about the section at ``x``,
            positive in the sense that REDUCES the sagging moment there --
            i.e. ``force * (x - position)`` for a downward force.

        Concentrated applied moments contribute to the second term only,
        with the sign defined in the module docstring.
        """

    @abstractmethod
    def total(self) -> float:
        """Total downward force this load applies to the beam (N)."""

    def _check_in_span(self, position: float, length: float, name: str = "position") -> None:
        """[CHECK] A load off the end of the member is a modelling error, not a
        zero contribution -- fail loudly rather than analysing a beam the user
        did not describe."""
        if position < -1e-9 or position > length + 1e-9:
            raise ModelError(
                f"{type(self).__name__} {name} = {position:.1f} mm lies outside "
                f"the member, which is {length:.1f} mm long"
            )


@dataclass(frozen=True)
class PointLoad(Load):
    """A concentrated force.

    Parameters
    ----------
    position:
        Distance from the left end of the member (mm).
    magnitude:
        Downward force (N). Negative for an uplift force.

    Examples
    --------
    A 50 kN point load at midspan of an 8 m beam::

        PointLoad(position=4 * m, magnitude=50 * kN)
    """

    position: float = 0.0
    magnitude: float = 0.0

    _SCALABLE_FIELDS: ClassVar[tuple[str, ...]] = ("magnitude",)

    def mesh_points(self) -> list[float]:
        return [self.position]

    def intensity(self, x: float) -> float:
        return 0.0

    def point_forces(self) -> list[tuple[float, float]]:
        return [(self.position, self.magnitude)]

    def point_moments(self) -> list[tuple[float, float]]:
        return []

    def resultant_left_of(self, x: float) -> tuple[float, float]:
        if self.position > x + 1e-9:
            return 0.0, 0.0
        return self.magnitude, self.magnitude * (x - self.position)

    def total(self) -> float:
        return self.magnitude


@dataclass(frozen=True)
class AppliedMoment(Load):
    """A concentrated moment applied to the member.

    Parameters
    ----------
    position:
        Distance from the left end (mm).
    magnitude:
        Moment (N.mm), positive where it increases the sagging moment to its
        right. See the module docstring.
    """

    position: float = 0.0
    magnitude: float = 0.0

    _SCALABLE_FIELDS: ClassVar[tuple[str, ...]] = ("magnitude",)

    def mesh_points(self) -> list[float]:
        return [self.position]

    def intensity(self, x: float) -> float:
        return 0.0

    def point_forces(self) -> list[tuple[float, float]]:
        return []

    def point_moments(self) -> list[tuple[float, float]]:
        return [(self.position, self.magnitude)]

    def resultant_left_of(self, x: float) -> tuple[float, float]:
        if self.position > x + 1e-9:
            return 0.0, 0.0
        # Negative because resultant_left_of returns the moment that REDUCES
        # sagging, and a positive applied moment increases it.
        return 0.0, -self.magnitude

    def total(self) -> float:
        return 0.0


@dataclass(frozen=True)
class UDL(Load):
    """A uniformly distributed load over the whole member.

    Parameters
    ----------
    magnitude:
        Intensity (N/mm, downward positive). Note 1 kN/m == 1 N/mm exactly.
    length:
        Member length (mm). Required so the load knows its own extent; set
        automatically when the load is attached to a :class:`~austruct.analysis.beam.Beam`.

    Examples
    --------
    A 25 kN/m UDL::

        UDL(magnitude=25 * kN_per_m)
    """

    magnitude: float = 0.0
    length: float = 0.0

    _SCALABLE_FIELDS: ClassVar[tuple[str, ...]] = ("magnitude",)

    def mesh_points(self) -> list[float]:
        return [0.0, self.length]

    def intensity(self, x: float) -> float:
        return self.magnitude if 0.0 <= x <= self.length else 0.0

    def point_forces(self) -> list[tuple[float, float]]:
        return []

    def point_moments(self) -> list[tuple[float, float]]:
        return []

    def resultant_left_of(self, x: float) -> tuple[float, float]:
        covered = max(0.0, min(x, self.length))
        force = self.magnitude * covered
        return force, force * (covered / 2.0)

    def total(self) -> float:
        return self.magnitude * self.length


@dataclass(frozen=True)
class PartialUDL(Load):
    """A uniformly distributed load over part of the member.

    Parameters
    ----------
    start, end:
        Extent of the load from the left end (mm).
    magnitude:
        Intensity (N/mm, downward positive).

    Examples
    --------
    30 kN/m over the middle 3 m of an 8 m beam::

        PartialUDL(start=2.5 * m, end=5.5 * m, magnitude=30 * kN_per_m)
    """

    start: float = 0.0
    end: float = 0.0
    magnitude: float = 0.0

    _SCALABLE_FIELDS: ClassVar[tuple[str, ...]] = ("magnitude",)

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ModelError(
                f"PartialUDL end ({self.end}) must be greater than start ({self.start})"
            )

    @property
    def extent(self) -> float:
        return self.end - self.start

    def mesh_points(self) -> list[float]:
        return [self.start, self.end]

    def intensity(self, x: float) -> float:
        return self.magnitude if self.start <= x <= self.end else 0.0

    def point_forces(self) -> list[tuple[float, float]]:
        return []

    def point_moments(self) -> list[tuple[float, float]]:
        return []

    def resultant_left_of(self, x: float) -> tuple[float, float]:
        lo = self.start
        hi = min(self.end, x)
        if hi <= lo:
            return 0.0, 0.0
        force = self.magnitude * (hi - lo)
        centroid = 0.5 * (lo + hi)
        return force, force * (x - centroid)

    def total(self) -> float:
        return self.magnitude * self.extent


@dataclass(frozen=True)
class VaryingUDL(Load):
    """A linearly varying distributed load -- triangular or trapezoidal.

    Parameters
    ----------
    start, end:
        Extent from the left end (mm).
    w_start, w_end:
        Intensity at ``start`` and ``end`` (N/mm, downward positive).

    Examples
    --------
    A triangular load rising from zero to 40 kN/m across a 6 m span::

        VaryingUDL(start=0, end=6 * m, w_start=0, w_end=40 * kN_per_m)
    """

    start: float = 0.0
    end: float = 0.0
    w_start: float = 0.0
    w_end: float = 0.0

    _SCALABLE_FIELDS: ClassVar[tuple[str, ...]] = ("w_start", "w_end")

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ModelError(
                f"VaryingUDL end ({self.end}) must be greater than start ({self.start})"
            )

    @property
    def extent(self) -> float:
        return self.end - self.start

    def mesh_points(self) -> list[float]:
        return [self.start, self.end]

    def intensity(self, x: float) -> float:
        if not (self.start <= x <= self.end):
            return 0.0
        f = (x - self.start) / self.extent
        return self.w_start + f * (self.w_end - self.w_start)

    def point_forces(self) -> list[tuple[float, float]]:
        return []

    def point_moments(self) -> list[tuple[float, float]]:
        return []

    def resultant_left_of(self, x: float) -> tuple[float, float]:
        lo = self.start
        hi = min(self.end, x)
        if hi <= lo:
            return 0.0, 0.0

        # Trapezoid between lo and hi: split into the uniform part (w_lo) and
        # the triangular remainder, so the centroid is exact rather than
        # approximated.
        w_lo = self.intensity(lo)
        w_hi = self.intensity(hi)
        length = hi - lo

        f_rect = w_lo * length
        c_rect = lo + length / 2.0

        f_tri = 0.5 * (w_hi - w_lo) * length
        # Centroid of a triangle measured from its zero-height end.
        c_tri = lo + (2.0 / 3.0) * length if w_hi >= w_lo else lo + (1.0 / 3.0) * length

        force = f_rect + f_tri
        if abs(force) < 1e-15:
            return 0.0, 0.0
        moment = f_rect * (x - c_rect) + f_tri * (x - c_tri)
        return force, moment

    def total(self) -> float:
        return 0.5 * (self.w_start + self.w_end) * self.extent


@dataclass(frozen=True)
class SelfWeight(Load):
    """Member self weight, as a UDL derived from a section and a density.

    Convenience wrapper so self weight is never a hand-computed number sitting
    in a load list with no traceability.

    Parameters
    ----------
    area:
        Cross-sectional area (mm^2).
    density:
        Material density (kg/m^3). Defaults to 2400 for normal-weight concrete.
    length:
        Member length (mm). Set automatically when attached to a Beam.
    gravity:
        Acceleration due to gravity (m/s^2).

    [UNITS] The conversion to N/mm is:
            rho [kg/m^3] * A [mm^2] * g [m/s^2] * 1e-9 [m^3/mm^3] = N/mm
    """

    area: float = 0.0
    density: float = 2400.0
    length: float = 0.0
    gravity: float = 9.81
    factor: float = 1.0
    """Load factor applied by a combination. Self weight derives its
    magnitude from area and density, so it cannot scale those directly --
    scaling the section would be a different beam."""

    _SCALABLE_FIELDS: ClassVar[tuple[str, ...]] = ("factor",)

    @property
    def magnitude(self) -> float:
        """Equivalent UDL intensity (N/mm), including any load factor."""
        return self.density * self.area * self.gravity * 1e-9 * self.factor

    def mesh_points(self) -> list[float]:
        return [0.0, self.length]

    def intensity(self, x: float) -> float:
        return self.magnitude if 0.0 <= x <= self.length else 0.0

    def point_forces(self) -> list[tuple[float, float]]:
        return []

    def point_moments(self) -> list[tuple[float, float]]:
        return []

    def resultant_left_of(self, x: float) -> tuple[float, float]:
        covered = max(0.0, min(x, self.length))
        force = self.magnitude * covered
        return force, force * (covered / 2.0)

    def total(self) -> float:
        return self.magnitude * self.length
