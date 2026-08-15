"""Masonry wall sections -- geometry plus material plus (optional) vertical
reinforcement, for a one-way spanning wall strip.

A :class:`MasonryWallSection` is designed the way a masonry wall actually is:
per METRE of wall length, spanning ONE way (vertically or horizontally)
between supports, exactly like a one-way slab strip in concrete design. This
is the same simplification the ``design/as3700`` flexure and shear modules
build on -- see their docstrings for what it does not cover (panel/yield-line
bending, in-plane shear walls).

[UNITS] mm, mm^2, MPa throughout. ``design_width`` defaults to 1000 mm (the
per-metre strip), matching how a wall's flexural/shear capacity is normally
reported (kN.m/m, kN/m).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.exceptions import ModelError
from ..materials.masonry import MasonryGrade
from ..materials.reinforcement import D500N, Reinforcement


@dataclass(frozen=True)
class MasonryReinforcement:
    """Vertical reinforcement in grouted cores, per metre of wall length.

    Parameters
    ----------
    area_per_metre:
        Total steel area per metre of wall length (mm^2/m) -- e.g. N16 bars
        at 600 mm centres is ``bar_area(16) * 1000 / 600``.
    depth:
        Depth to the reinforcement centroid from the compression (leading)
        face, mm.
    material:
        Reinforcement grade. Defaults to D500N.
    """

    area_per_metre: float
    depth: float
    material: Reinforcement = D500N

    def __post_init__(self) -> None:
        if self.area_per_metre <= 0:
            raise ModelError(
                f"area_per_metre must be positive, got {self.area_per_metre}"
            )
        if self.depth <= 0:
            raise ModelError(f"depth must be positive, got {self.depth}")


@dataclass(frozen=True)
class MasonryWallSection:
    """A masonry wall, per metre of length, for one-way (out-of-plane) design.

    Construct via :func:`masonry_wall` for the common case, or directly.
    """

    thickness: float
    """t -- overall wall thickness, mm."""

    masonry: MasonryGrade

    design_width: float = 1000.0
    """Strip width the capacity is computed over, mm. 1000 -- per metre --
    unless there is a specific reason to design a narrower strip."""

    reinforcement: MasonryReinforcement | None = None
    """None for unreinforced masonry. Present -> :mod:`design.as3700.flexure`
    and :mod:`design.as3700.shear` use the reinforced formulas."""

    cover: float = 25.0
    """Cover to reinforcement, mm. Used only for reporting/detailing context
    in this scope -- not independently checked."""

    name: str = ""

    def __post_init__(self) -> None:
        if self.thickness <= 0:
            raise ModelError(f"thickness must be positive, got {self.thickness}")
        if self.reinforcement is not None and self.reinforcement.depth >= self.thickness:
            raise ModelError(
                f"Reinforcement depth ({self.reinforcement.depth} mm) must be "
                f"less than the wall thickness ({self.thickness} mm)"
            )

    @property
    def reinforced(self) -> bool:
        return self.reinforcement is not None

    @property
    def Z(self) -> float:  # noqa: N802
        """Elastic section modulus of the strip, mm^3 -- ``b.t^2 / 6``."""
        return self.design_width * self.thickness**2 / 6.0

    @property
    def area(self) -> float:
        """Gross cross-sectional area of the strip, mm^2."""
        return self.design_width * self.thickness

    @property
    def Ast(self) -> float:  # noqa: N802
        """Reinforcement area within the strip width, mm^2. Zero if unreinforced."""
        if self.reinforcement is None:
            return 0.0
        return self.reinforcement.area_per_metre * (self.design_width / 1000.0)

    def with_reinforcement(self, reinforcement: MasonryReinforcement | None) -> MasonryWallSection:
        """Copy with different (or no) reinforcement."""
        return replace(self, reinforcement=reinforcement)

    def describe(self) -> list[str]:
        lines = [
            f"Section       = {self.name or 'masonry wall'}",
            f"thickness t   = {self.thickness:.0f} mm",
            f"design_width  = {self.design_width:.0f} mm",
            f"Z             = {self.Z:.3e} mm^3",
        ]
        lines.extend(f"  {line}" for line in self.masonry.describe())
        if self.reinforcement:
            r = self.reinforcement
            lines.append(
                f"reinforcement = {r.area_per_metre:.0f} mm^2/m at d = {r.depth:.0f} mm"
            )
        else:
            lines.append("reinforcement = none (unreinforced)")
        return lines


def masonry_wall(
    thickness: float,
    masonry: MasonryGrade,
    bar_area_per_metre: float = 0.0,
    bar_depth: float = 0.0,
    material: Reinforcement = D500N,
    cover: float = 25.0,
    name: str = "",
) -> MasonryWallSection:
    """Build a wall section the way it is specified on a drawing.

    Pass ``bar_area_per_metre`` and ``bar_depth`` for a reinforced wall;
    leave them at zero for unreinforced masonry.

    Examples
    --------
    N16 vertical bars at 600 mm centres, 190 series block, d = 95 mm::

        masonry_wall(190, masonry_properties(15.0, grouted=True),
                     bar_area_per_metre=bar_area(16) * 1000 / 600, bar_depth=95)
    """
    reinforcement = None
    if bar_area_per_metre and bar_depth:
        reinforcement = MasonryReinforcement(
            area_per_metre=bar_area_per_metre, depth=bar_depth, material=material
        )
    return MasonryWallSection(
        thickness=thickness,
        masonry=masonry,
        reinforcement=reinforcement,
        cover=cover,
        name=name or f"{thickness:.0f} mm masonry wall",
    )
