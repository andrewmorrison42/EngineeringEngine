"""Reinforcing bar catalogue -- the queryable reference-data layer.

This module is the direct analogue of the crane-catalogue example in the ASET
material: reference data reorganised so that the engineer asks a natural
question and gets an actionable answer, rather than reading a table.

    >>> bar_area(20)                 # one N20
    314.159...
    >>> layer_area(4, 20)            # 4-N20
    1256.6...
    >>> bars_for_area(1800, 20)      # how many N20 to make 1800 mm2?
    6
    >>> options_for_area(1800)       # every sensible arrangement
    [(6, 20, 1885.0), (3, 28, 1847.3), (4, 24, 1809.6), ...]

[UNITS] Diameters and spacings in mm, areas in mm^2.

[VECTOR] Bar diameters are from AS/NZS 4671 and are UNVERIFIED. Areas are
         computed from the nominal diameter, not transcribed, so they are
         arithmetic rather than transcription -- but confirm that the office
         convention is nominal-diameter area and not a tabulated value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.provenance import ModuleType, Provenance
from ..core.registry import REGISTRY

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.D_EXTRACTION,
    ),
    description="Standard reinforcing bar sizes, areas and arrangement queries",
    envelope_summary="Standard AS/NZS 4671 bar diameters only",
)

# ---------------------------------------------------------------------------
# [BASIS]  AS/NZS 4671 -- standard deformed bar diameters (mm).
# [VECTOR] UNVERIFIED. Confirm the sizes actually stocked/specified by the
#          office; carrying sizes nobody can buy produces undeliverable designs.
# ---------------------------------------------------------------------------
DEFORMED_DIAMETERS: tuple[int, ...] = (10, 12, 16, 20, 24, 28, 32, 36, 40)

# [BASIS]  AS/NZS 4671 -- standard plain round bar diameters (mm), fitments.
PLAIN_DIAMETERS: tuple[int, ...] = (6, 10, 12, 16, 20, 24)

# Sizes normally used as fitments (ligatures/stirrups). Restricting the search
# space here keeps `options_for_area` from proposing 36 mm ligatures.
FITMENT_DIAMETERS: tuple[int, ...] = (10, 12, 16, 20)


def bar_area(diameter: float) -> float:
    """Cross-sectional area of one bar.

    [UNITS] diameter mm, returns mm^2.
    [ASSUMPTION] Area from the nominal diameter, pi.d^2/4. Deformed bar is
                 specified by nominal diameter defined on this basis.
    """
    return math.pi * diameter**2 / 4.0


def layer_area(count: int, diameter: float) -> float:
    """Total area of ``count`` bars of ``diameter``.

    [UNITS] returns mm^2.
    """
    return count * bar_area(diameter)


def bars_for_area(area_required: float, diameter: float, minimum: int = 2) -> int:
    """Number of bars of ``diameter`` needed to reach ``area_required``.

    Rounds up -- never returns an arrangement short of the requirement.

    Parameters
    ----------
    area_required:
        Required steel area (mm^2).
    diameter:
        Bar diameter (mm).
    minimum:
        Floor on the count. Defaults to 2 because a single bottom bar in a beam
        is not a practical detail.

    [UNITS] area_required mm^2, diameter mm.
    """
    if area_required <= 0:
        return minimum
    n = math.ceil(area_required / bar_area(diameter))
    return max(minimum, int(n))


def spacing_for_area(area_required_per_m: float, diameter: float) -> float:
    """Bar spacing giving ``area_required_per_m`` in a slab or wall.

    [UNITS] area_required_per_m in mm^2/m, diameter mm, returns mm.

    Returns the exact spacing; round DOWN to a practical increment before
    detailing, since rounding up reduces the area provided.
    """
    if area_required_per_m <= 0:
        raise ValueError("area_required_per_m must be positive")
    return bar_area(diameter) * 1000.0 / area_required_per_m


@dataclass(frozen=True)
class BarArrangement:
    """One candidate arrangement satisfying an area requirement."""

    count: int
    diameter: int
    area: float

    @property
    def label(self) -> str:
        """Detailing label, e.g. ``"6-N20"``."""
        return f"{self.count}-N{self.diameter}"

    def width_required(self, cover: float, fitment_dia: float, clear_spacing: float) -> float:
        """Minimum web width to fit this arrangement in one layer.

        [UNITS] all mm.
        [ASSUMPTION] Single layer, bars evenly spaced, fitment passing outside
                     the main bars, equal cover both faces. Does not check the
                     aggregate-size or bar-diameter minimum clear spacing rules
                     -- pass the governing clear spacing in.
        """
        n = self.count
        return (
            2 * cover
            + 2 * fitment_dia
            + n * self.diameter
            + max(0, n - 1) * clear_spacing
        )

    def __str__(self) -> str:
        return f"{self.label} (A_s = {self.area:.0f} mm^2)"


def options_for_area(
    area_required: float,
    diameters: tuple[int, ...] = DEFORMED_DIAMETERS,
    max_bars: int = 12,
    minimum: int = 2,
    max_waste: float = 0.35,
) -> list[BarArrangement]:
    """Every practical bar arrangement meeting an area requirement.

    This is the query the ASET example is really about: the engineer has a
    number (required As) and wants the *actionable* list, not a table to read
    across. Results are sorted by how little steel is wasted, so the first
    entry is the most efficient arrangement.

    Parameters
    ----------
    area_required:
        Required steel area (mm^2).
    diameters:
        Candidate bar diameters. Restrict this to what the job actually uses.
    max_bars:
        Upper limit on bars in a layer. 12 is already impractical for most
        beams; the width check is the real constraint.
    minimum:
        Minimum bars per layer.
    max_waste:
        Discard arrangements providing more than ``(1 + max_waste)`` times the
        required area. Default 0.35 keeps the list short and sensible.

    Returns
    -------
    list[BarArrangement]
        Sorted by provided area ascending -- least wasteful first.

    [UNITS] area_required mm^2, diameters mm.
    """
    if area_required <= 0:
        raise ValueError("area_required must be positive")

    out: list[BarArrangement] = []
    limit = area_required * (1.0 + max_waste)
    for dia in diameters:
        n = bars_for_area(area_required, dia, minimum=minimum)
        if n > max_bars:
            continue
        provided = layer_area(n, dia)
        if provided > limit:
            continue
        out.append(BarArrangement(count=n, diameter=dia, area=provided))

    return sorted(out, key=lambda a: a.area)


def describe_options(area_required: float, **kwargs) -> str:
    """Formatted table of arrangements, for a report or a quick console check."""
    opts = options_for_area(area_required, **kwargs)
    if not opts:
        return f"No practical arrangement found for As = {area_required:.0f} mm^2"
    lines = [f"Required As = {area_required:.0f} mm^2", ""]
    lines.append(f"{'Arrangement':<14}{'As prov':>10}{'Excess':>10}")
    lines.append("-" * 34)
    for o in opts:
        excess = (o.area / area_required - 1.0) * 100.0
        lines.append(f"{o.label:<14}{o.area:>10.0f}{excess:>9.1f}%")
    return "\n".join(lines)
