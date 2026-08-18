"""Modular block catalogue -- manufacturer-agnostic gravity wall units.

Each row is one block SERIES: a course width, course height, per-course
setback (the batter mechanism -- most segmental gravity systems achieve
their standard batter by stepping each course back a fixed amount from the
one below, via a pin/knob/lip detail, rather than by a sloped block face)
and an equivalent unit weight for a filled/grouted course.

Seeded from the Redi-Rock Design Resource Manual V20's width series --
see ``data/block_catalogue.json`` for exactly what was and was not
transcribed from that document. This catalogue is deliberately
manufacturer-agnostic: nothing downstream of :class:`BlockSeries` cares
which manufacturer a row came from, or whether it came from the catalogue
at all -- any :class:`BlockSeries` instance, built by hand from an actual
data sheet, works identically.
"""

from __future__ import annotations

import math

from ..contracts.base import ToolkitModel
from . import _data


class BlockSeries(ToolkitModel):
    """One modular gravity block series' course geometry and self-weight.

    [UNITS] this tool's convention -- m, kN/m^3, degrees (derived). See
    :mod:`.models` for why this differs from ``austruct.core.units``.
    """

    name: str
    description: str
    width: float
    """Front-to-back footprint of ONE course, m."""
    height: float
    """Course height, m."""
    setback: float
    """Horizontal setback of each course's front face from the course below, m."""
    unit_weight: float
    """Equivalent unit weight of a filled/grouted block, kN/m^3."""

    @property
    def batter_deg(self) -> float:
        """Wall batter angle from vertical, degrees -- DERIVED from
        setback/height, not a separate catalogue field, so the two numbers
        can never silently disagree."""
        return math.degrees(math.atan2(self.setback, self.height))


def block_series_names() -> tuple[str, ...]:
    """Every series name available to :class:`~.models.GravityWallGeometry`."""
    return tuple(row["name"] for row in _data.load_json("block_catalogue.json")["series"])


def block_series(name: str) -> BlockSeries:
    """Look up one block series by name.

    Raises
    ------
    KeyError
        If ``name`` is not in :func:`block_series_names`.
    """
    for row in _data.load_json("block_catalogue.json")["series"]:
        if row["name"] == name:
            return BlockSeries.model_validate(row)
    raise KeyError(
        f"Unknown block series {name!r}. Known series: {', '.join(block_series_names())}"
    )
