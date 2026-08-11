"""Load dispersal through fill onto a buried structure.

The problem
-----------
A culvert, headwall or buried slab does not see a wheel load. It sees whatever
that wheel has become after spreading through the fill above it. Two things
arrive at the structure:

1. **Earth pressure** -- the weight of the fill itself, a UDL over the whole
   member.
2. **Dispersed live load** -- each wheel spread over a patch that grows with
   fill depth, so a 400 x 250 mm contact under 1.5 m of fill becomes a patch
   several metres across at a small fraction of the original pressure.

The consequence is worth stating because it drives the design: **shallow fill
is the worst case for the live load and the best case for the dead load.** A
sweep over fill depth usually shows the top slab governed by wheels at minimum
cover and by earth pressure at maximum, so both extremes must be checked.

How the dispersal is modelled
-----------------------------
Each wheel's contact patch is spread at a fixed slope through the fill::

    dispersed_length = contact_length + 2 * depth / slope
    dispersed_width  = contact_width  + 2 * depth / slope
    pressure         = wheel_load / (dispersed_length * dispersed_width)

The pressure is then applied to the member as a :class:`PartialUDL` over the
dispersed LENGTH, at an intensity of
``pressure * min(dispersed_width, effective_width)``.

That ``min`` matters. Under shallow fill the patch is narrower than the strip
being analysed, and the strip carries the whole wheel; multiplying by the full
strip width would invent load -- an 80 kN wheel on a 400 mm patch analysed as a
1 m strip would arrive as 200 kN. Under deep fill the patch is wider than the
strip and the excess correctly sheds to the strips either side, which is only
legitimate if those strips exist -- see :meth:`FillDispersal.transverse_coverage`.

Overlapping patches are handled by superposition: each wheel becomes its own
``PartialUDL`` and where they overlap the intensities add, which is exactly
right and needs no special case.

[UNITS] mm, N, N/mm. Fill density in kg/m^3, converted internally.

[VECTOR] The dispersal slope and the earth pressure treatment are UNVERIFIED.
         Confirm against AS 5100.2 and the relevant road authority supplement,
         which sometimes mandate a different slope from the standard's.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..analysis.loading import UDL, Load, LoadTrain, PartialUDL
from ..core.exceptions import ModelError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.PROJECT_DATA,
    ),
    description="Dispersal of wheel loads and earth pressure through fill onto a buried structure",
    envelope_summary=(
        "Single-layer fill; linear dispersal at a stated slope; "
        "no soil-structure interaction; no arching"
    ),
)

# ---------------------------------------------------------------------------
# [BASIS]  Dispersal through fill.
# [VECTOR] UNVERIFIED. AS 5100.2 states a dispersal slope for loads through
#          fill; some road authorities mandate a different one. 2.0 here means
#          2 horizontal to 1 vertical, i.e. the patch grows by `depth` on each
#          side per unit of `slope`.
# ---------------------------------------------------------------------------
DEFAULT_DISPERSAL_SLOPE = 2.0
"""Horizontal spread per unit depth, expressed as H:V. 2.0 = 2H:1V."""

DEFAULT_FILL_DENSITY = 2000.0
"""kg/m^3. A common assumption for compacted granular fill.
[VECTOR] UNVERIFIED -- use the geotechnical report's value."""

GRAVITY = 9.81


@dataclass(frozen=True)
class FillDispersal:
    """Fill over a buried structure, and how load spreads through it.

    Parameters
    ----------
    depth:
        Depth of fill from the road surface to the top of the structure (mm).
    density:
        Fill density (kg/m^3).
    slope:
        Dispersal slope, horizontal per vertical. 2.0 means 2H:1V.
    effective_width:
        Transverse width of structure that the member being analysed carries
        (mm). For a unit-strip analysis this is 1000; for a girder it is the
        girder spacing.

    Examples
    --------
    1.2 m of fill over a culvert, analysed as a 1 m strip::

        fill = FillDispersal(depth=1200, effective_width=1000)
    """

    depth: float
    density: float = DEFAULT_FILL_DENSITY
    slope: float = DEFAULT_DISPERSAL_SLOPE
    effective_width: float = 1000.0

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise ModelError(f"Fill depth must be non-negative, got {self.depth}")
        if self.slope <= 0:
            raise ModelError(f"Dispersal slope must be positive, got {self.slope}")
        if self.effective_width <= 0:
            raise ModelError(
                f"Effective width must be positive, got {self.effective_width}"
            )

    # -- dead load -------------------------------------------------------------

    @property
    def vertical_pressure(self) -> float:
        """Vertical earth pressure at the top of the structure (MPa).

        [UNITS] density kg/m^3 * depth mm * g m/s^2 * 1e-9 -> N/mm^2.
        [ASSUMPTION] Full overburden, no arching relief. Conservative for a
                     rigid buried structure; NOT conservative for a flexible
                     one, where negative arching can increase the load above
                     the prism weight.
        """
        return self.density * self.depth * GRAVITY * 1e-9

    def earth_pressure_udl(self, label: str = "fill") -> UDL:
        """The fill's own weight as a UDL on the member.

        [UNITS] returns N/mm.
        """
        return UDL(magnitude=self.vertical_pressure * self.effective_width, label=label)

    # -- live load -------------------------------------------------------------

    def spread(self, contact_dimension: float) -> float:
        """A contact dimension after spreading through the fill (mm).

        Grows by ``depth / slope`` on each side.
        """
        return contact_dimension + 2.0 * self.depth / self.slope

    def wheel_pressure(
        self, wheel_load: float, contact_length: float, contact_width: float
    ) -> float:
        """Pressure under one dispersed wheel (MPa).

        [UNITS] wheel_load N, contacts mm, returns N/mm^2.
        """
        area = self.spread(contact_length) * self.spread(contact_width)
        return wheel_load / area

    def disperse_wheel(
        self,
        wheel_load: float,
        position: float,
        contact_length: float,
        contact_width: float,
        member_length: float,
        label: str = "wheel",
    ) -> PartialUDL | None:
        """One wheel, dispersed through the fill onto the member.

        Parameters
        ----------
        wheel_load:
            Load on the wheel (N).
        position:
            Longitudinal position of the wheel centre (mm along the member).
        contact_length, contact_width:
            Tyre contact patch at the surface (mm). ``length`` is along the
            member, ``width`` transverse.
        member_length:
            Member length (mm), for clipping.

        Returns
        -------
        PartialUDL or None
            ``None`` if the dispersed patch falls entirely off the member.

        [ASSUMPTION] The dispersed pressure is uniform over the patch. Real
                     dispersal is not uniform -- the pressure bulb is peaked --
                     so this is unconservative at the centre and conservative
                     at the edges. It is the standard simplification.

        [ASSUMPTION] The load applied to the member is the pressure times the
                     width of patch that actually lands on the strip, i.e.
                     ``min(dispersed_width, effective_width)`` -- NOT the full
                     effective width. Under shallow fill the patch is narrower
                     than the strip, and multiplying by the strip width would
                     invent load: an 80 kN wheel on a 400 mm patch analysed as
                     a 1 m strip would arrive as 200 kN. Under deep fill the
                     patch is wider than the strip and the excess correctly
                     sheds to the strips either side.

        [ASSUMPTION] The TRANSVERSE dispersed width is used only to compute the
                     pressure; the load applied to the member is that pressure
                     times ``effective_width``. Where the dispersed width is
                     narrower than the effective width, this SPREADS the load
                     over more structure than actually receives it and is
                     unconservative -- check ``transverse_coverage`` below.
        """
        length = self.spread(contact_length)
        pressure = self.wheel_pressure(wheel_load, contact_length, contact_width)

        start = max(0.0, position - length / 2.0)
        end = min(member_length, position + length / 2.0)
        if end - start <= 1e-9:
            return None

        return PartialUDL(
            start=start,
            end=end,
            magnitude=pressure * self.carried_width(contact_width),
            label=label,
        )

    def carried_width(self, contact_width: float) -> float:
        """Transverse width of dispersed pressure that lands on the strip (mm).

        ``min(dispersed_width, effective_width)``. See the assumption note on
        :meth:`disperse_wheel` for why this is not simply the effective width.
        """
        return min(self.spread(contact_width), self.effective_width)

    def transverse_coverage(self, contact_width: float) -> float:
        """Dispersed transverse width divided by the effective width.

        Below 1.0 the patch sits entirely within the strip, so the strip
        carries the whole wheel. Above 1.0 the patch is wider than the strip
        and that fraction of the load sheds to the strips either side --
        which is only valid if those strips exist. On a member narrower than
        the dispersed patch (an isolated headwall, say) taking the reduction
        is unconservative; use ``effective_width`` equal to the real structure
        width in that case.
        """
        return self.spread(contact_width) / self.effective_width

    # -- assembling a whole vehicle --------------------------------------------

    def disperse_train(
        self,
        train: LoadTrain,
        datum: float,
        member_length: float,
        contact_length: float,
        contact_width: float,
    ) -> tuple[Load, ...]:
        """Every axle of a load train, dispersed onto the member.

        Each axle becomes its own ``PartialUDL``; overlapping patches add by
        superposition, which is the correct treatment and requires no special
        handling.

        Parameters
        ----------
        train:
            The load train. Its axle loads are treated as loads to disperse.
        datum:
            Where to place the train's datum (mm).
        contact_length, contact_width:
            Contact patch per axle load (mm).
        """
        loads: list[Load] = []
        for i, (offset, magnitude) in enumerate(train.axles, start=1):
            patch = self.disperse_wheel(
                wheel_load=magnitude,
                position=datum + offset,
                contact_length=contact_length,
                contact_width=contact_width,
                member_length=member_length,
                label=f"{train.name} axle {i}",
            )
            if patch is not None:
                loads.append(patch)
        return tuple(loads)

    def dispersed_train(
        self,
        train: LoadTrain,
        member_length: float,
        contact_length: float,
        contact_width: float,
    ) -> LoadTrain:
        """A NEW load train whose axles have been replaced by dispersed patches.

        This is the form to hand to
        :func:`~austruct.analysis.moving.moving_load_envelope`: the dispersal
        geometry is baked in, and the resulting train is still positionable, so
        the sweep finds the worst position of the dispersed vehicle rather than
        of the point loads.

        Returns
        -------
        LoadTrain
            With ``udl_segments`` in place of ``axles``. The trailing UDL is
            carried through unchanged -- a lane UDL is already distributed and
            does not disperse further.
        """
        length = self.spread(contact_length)
        pressure_per_load = 1.0 / (length * self.spread(contact_width))
        carried = self.carried_width(contact_width)

        segments = []
        for offset, magnitude in train.axles:
            intensity = magnitude * pressure_per_load * carried
            segments.append((offset - length / 2.0, offset + length / 2.0, intensity))

        return LoadTrain(
            name=f"{train.name} dispersed through {self.depth:.0f} mm fill",
            axles=(),
            udl_segments=tuple(segments) + train.udl_segments,
            length=train.length,
            trailing_udl=train.trailing_udl,
        )

    def describe(self) -> list[str]:
        return [
            f"Fill depth       = {self.depth:.0f} mm",
            f"Fill density     = {self.density:.0f} kg/m^3",
            f"Dispersal slope  = {self.slope:g}H:1V",
            f"Effective width  = {self.effective_width:.0f} mm",
            f"Earth pressure   = {self.vertical_pressure * 1e3:.2f} kPa",
            f"UDL on member    = {self.earth_pressure_udl().magnitude:.3f} N/mm "
            f"({self.earth_pressure_udl().magnitude:.2f} kN/m)",
        ]


def buried_structure_loads(
    fill: FillDispersal,
    member_length: float,
    wheel_load: float,
    contact_length: float,
    contact_width: float,
    wheel_positions: tuple[float, ...],
    include_earth_pressure: bool = True,
) -> tuple[Load, ...]:
    """Earth pressure plus a set of dispersed wheels, at fixed positions.

    The non-moving version: use it when the wheel positions are already known
    (from a separate sweep, or from a governing arrangement). For the moving
    case use :meth:`FillDispersal.dispersed_train` with
    :func:`~austruct.analysis.moving.moving_load_envelope`.

    Parameters
    ----------
    wheel_positions:
        Longitudinal positions of the wheel centres (mm).

    Returns
    -------
    tuple[Load, ...]
        Ready to hand to a :class:`~austruct.analysis.beam.Beam`.
    """
    loads: list[Load] = []
    if include_earth_pressure:
        loads.append(fill.earth_pressure_udl())

    for i, position in enumerate(wheel_positions, start=1):
        patch = fill.disperse_wheel(
            wheel_load=wheel_load,
            position=position,
            contact_length=contact_length,
            contact_width=contact_width,
            member_length=member_length,
            label=f"wheel {i}",
        )
        if patch is not None:
            loads.append(patch)

    return tuple(loads)
