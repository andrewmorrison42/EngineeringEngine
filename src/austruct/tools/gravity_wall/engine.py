"""Block self-weight and the allowable-stress-design force ledger.

Deliberately simpler than ``cantilever_wall.engine``'s :class:`StabilityLedger`:
there are no AS 4678-style action factors here (see :mod:`.models`'s module
docstring for why) -- every force below is CHARACTERISTIC, and the factor of
safety is applied whole, per check, against the minimums this tool's
:mod:`.checks` package reads from :data:`FS_MINIMUMS`.

[UNITS] m, kN/m^3, kPa, kN/m, kN.m/m, degrees -- this tool's convention.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cantilever_wall.models import ResolvedSoil
from .models import GravityWallGeometry, GravityWallInput
from .pressure import ThrustComponents


@dataclass(frozen=True)
class CourseWeight:
    """One course's self-weight and its lever arm from the toe.

    [UNITS] weight kN/m (per metre run of wall), arm/elevations m.
    """

    course_index: int
    weight: float
    arm: float
    """Distance from the toe (front-bottom edge of the BASE course, x=0) to
    this course's own centroid, m -- NOT corrected for the batter of courses
    below it, because each course's ``arm`` already includes its own
    ``course_index * setback`` front-face offset; see :func:`block_self_weight`."""
    elevation_bottom: float
    elevation_top: float


def block_self_weight(geometry: GravityWallGeometry) -> tuple[CourseWeight, ...]:
    """Every course's self-weight and centroid, base course first.

    [ASSUMPTION] Every course in the stack is the SAME :class:`.blocks.BlockSeries`
                 -- a wall built from more than one series (e.g. a wider base
                 course transitioning to a narrower series higher up) is not
                 modelled; build such a wall as two separate
                 :func:`~austruct.tools.gravity_wall.api.analyse` runs instead,
                 one per zone, if that is ever needed.
    """
    block = geometry.block
    rows = []
    for i in range(geometry.n_courses):
        front_x = i * block.setback
        weight = block.width * block.height * block.unit_weight
        rows.append(
            CourseWeight(
                course_index=i,
                weight=weight,
                arm=front_x + block.width / 2.0,
                elevation_bottom=i * block.height,
                elevation_top=(i + 1) * block.height,
            )
        )
    return tuple(rows)


def base_friction_angle(wall: GravityWallInput, resolved: ResolvedSoil) -> float:
    """Base-to-foundation interface friction angle, degrees.

    Full characteristic phi by default -- [ASSUMPTION] the base course
    bears on a compacted granular levelling pad, effectively as rough as
    the soil itself. An explicit override always wins.
    """
    if wall.base_friction_override is not None:
        return wall.base_friction_override
    return resolved.phi.value


@dataclass(frozen=True)
class GravityLedger:
    """Every force and moment contribution for one gravity wall, ASD
    (characteristic, unfactored) throughout.
    """

    courses: tuple[CourseWeight, ...]
    thrust: ThrustComponents
    base_width: float

    @property
    def V(self) -> float:  # noqa: N802
        """Total characteristic vertical force, kN/m. The Coulomb vertical
        thrust component acts DOWNWARD on the wall (wall friction credit,
        see :mod:`.pressure`) and so ADDS to the stabilising self-weight."""
        return sum(c.weight for c in self.courses) + self.thrust.vertical

    @property
    def M_resisting(self) -> float:  # noqa: N802
        """Design resisting moment about the toe, kN.m/m. The vertical
        thrust component's arm is taken as the BASE course's back edge
        (``base_width``), the same simplification
        ``cantilever_wall.engine.build_ledger`` makes for its own
        backslope-vertical-component row."""
        return (
            sum(c.weight * c.arm for c in self.courses)
            + self.thrust.vertical * self.base_width
        )

    @property
    def M_overturning(self) -> float:  # noqa: N802
        """Design overturning moment about the toe, kN.m/m."""
        return self.thrust.horizontal * self.thrust.height

    def describe(self) -> list[str]:
        lines = [f"{'Course':<10}{'Weight':>10}{'Arm':>8}"]
        for c in self.courses:
            lines.append(f"{c.course_index:<10}{c.weight:>10.2f}{c.arm:>8.2f}")
        lines.append(
            f"{'Thrust H':<10}{self.thrust.horizontal:>10.2f}{self.thrust.height:>8.2f}"
        )
        lines.append(
            f"{'Thrust V':<10}{self.thrust.vertical:>10.2f}{self.base_width:>8.2f}"
        )
        return lines


def build_ledger(geometry: GravityWallGeometry, thrust: ThrustComponents) -> GravityLedger:
    courses = block_self_weight(geometry)
    return GravityLedger(courses=courses, thrust=thrust, base_width=geometry.base_width)


def eccentricity(ledger: GravityLedger) -> float:
    """Eccentricity of the base resultant from the base centreline, m.

    Not promoted to its own :class:`~austruct.core.contract.CalcResult` check
    -- unlike ``cantilever_wall``, this tool's methodology (see the package
    README) does not call out a separate middle-third/e-over-B limit;
    eccentricity feeds :mod:`.checks.bearing`'s Meyerhof effective width
    only, the same way it does there.
    """
    x_bar = (ledger.M_resisting - ledger.M_overturning) / ledger.V
    return ledger.base_width / 2.0 - x_bar
