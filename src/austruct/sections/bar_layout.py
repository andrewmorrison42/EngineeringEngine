"""Where the bars physically sit -- pure geometry, no code values.

Two different parts of the design layer need the same arithmetic. Crack control
needs the centre-to-centre spacing of the tensile bars; detailing needs to know
whether the bars fit in the width at all, and whether the clear gap between them
admits the aggregate. Both are questions about a rectangle and some circles,
with no standard involved, so they belong here in the sections layer rather
than in either standard's package.

The distinction that matters
----------------------------
**Centre-to-centre spacing** is what the crack-control tables are written
against. **Clear spacing** is what the placing and compaction rules are written
against. They differ by one bar diameter, and using one where the other is
meant is a silent error in both directions. Both are returned, named, from
:func:`layer_layout`.

What "cover" means here
-----------------------
``cover`` is the clear cover to the FITMENT, matching ``rc_beam``. The bars sit
inboard of it by the fitment diameter. Passing cover-to-main-bar instead
overstates the available width by twice the fitment diameter, which is roughly
one bar of room in a typical beam.

[UNITS] mm throughout.
"""

from __future__ import annotations

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
        component=ASETComponent.VERIFICATION,
    ),
    description="Bar spacing and fit geometry within a section width",
    envelope_summary="Bars in one horizontal row, equally spaced, symmetric about the centreline",
)


@dataclass(frozen=True)
class BarLayout:
    """The geometry of one row of bars across a width.

    Attributes
    ----------
    n_bars:
        Number of bars in the row.
    diameter:
        Bar diameter (mm).
    width:
        Overall section width the row sits in (mm).
    available_width:
        Width between the innermost faces of the fitments (mm).
    centre_spacing:
        Centre-to-centre spacing (mm). Zero for a single bar, where the concept
        does not apply -- crack-control spacing rules are vacuous for one bar.
    clear_spacing:
        Clear gap between adjacent bars (mm). Negative if the bars overlap,
        which is reported rather than raised so a sizing loop can test a
        layout and move on.
    edge_distance:
        Distance from the section face to the centre of the outermost bar (mm).
    """

    n_bars: int
    diameter: float
    width: float
    available_width: float
    centre_spacing: float
    clear_spacing: float
    edge_distance: float

    @property
    def fits(self) -> bool:
        """Whether the bars physically fit, ignoring any minimum-gap rule."""
        return self.clear_spacing >= 0.0

    def describe(self) -> list[str]:
        return [
            f"Row        = {self.n_bars}-N{self.diameter:.0f} in {self.width:.0f} mm",
            f"Clear width= {self.available_width:.0f} mm",
            f"c/c spacing= {self.centre_spacing:.1f} mm",
            f"Clear gap  = {self.clear_spacing:.1f} mm",
            f"Edge to bar= {self.edge_distance:.1f} mm",
        ]


def layer_layout(
    width: float,
    n_bars: int,
    diameter: float,
    cover: float,
    fitment_diameter: float = 0.0,
) -> BarLayout:
    """Lay out ``n_bars`` equally spaced in one row across ``width``.

    The bars are placed symmetrically, with the outermost bar centred one bar
    radius inboard of the fitment. That is the arrangement drawn on virtually
    every beam section, and it fixes the geometry completely.

    Parameters
    ----------
    width:
        Overall section width (mm).
    n_bars:
        Number of bars in the row. Must be at least one.
    diameter:
        Bar diameter (mm).
    cover:
        Clear cover to the fitment (mm).
    fitment_diameter:
        Fitment bar diameter (mm). Zero where there are no fitments.

    Returns
    -------
    BarLayout

    Notes
    -----
    A single bar has no spacing. ``centre_spacing`` and ``clear_spacing`` are
    returned as ``inf`` in that case rather than zero, because every rule that
    consumes them is an upper bound of the form "spacing <= limit", and zero
    would pass those vacuously while ``inf`` makes the vacuousness visible.
    Callers that check a maximum spacing must special-case one bar; the tables
    do not apply to it.
    """
    if n_bars < 1:
        raise ModelError(f"A bar row needs at least one bar, got {n_bars}")
    if diameter <= 0:
        raise ModelError(f"Bar diameter must be positive, got {diameter}")
    if width <= 0:
        raise ModelError(f"Section width must be positive, got {width}")

    inset = cover + fitment_diameter
    available = width - 2.0 * inset
    edge_distance = inset + diameter / 2.0

    if n_bars == 1:
        return BarLayout(
            n_bars=1,
            diameter=diameter,
            width=width,
            available_width=available,
            centre_spacing=float("inf"),
            clear_spacing=float("inf"),
            edge_distance=width / 2.0,
        )

    # Centres span from one bar radius inboard of each fitment.
    centre_span = available - diameter
    centre_spacing = centre_span / (n_bars - 1)
    return BarLayout(
        n_bars=n_bars,
        diameter=diameter,
        width=width,
        available_width=available,
        centre_spacing=centre_spacing,
        clear_spacing=centre_spacing - diameter,
        edge_distance=edge_distance,
    )


def max_bars_in_width(
    width: float,
    diameter: float,
    cover: float,
    fitment_diameter: float = 0.0,
    min_clear_spacing: float = 25.0,
) -> int:
    """How many bars of ``diameter`` fit in one row.

    Parameters
    ----------
    min_clear_spacing:
        Minimum acceptable clear gap (mm). The *value* is a code requirement
        and the caller supplies it; the default of 25 mm is a common figure and
        is NOT asserted to be any standard's number.

    Returns
    -------
    int
        Largest bar count that fits, or zero if not even one bar fits.
    """
    available = width - 2.0 * (cover + fitment_diameter)
    if available < diameter:
        return 0
    pitch = diameter + min_clear_spacing
    # n bars occupy n.d + (n-1).gap  <=  available
    return max(1, int((available + min_clear_spacing) // pitch))
