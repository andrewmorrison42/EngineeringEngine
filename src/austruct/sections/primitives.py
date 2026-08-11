"""Cross-section geometry primitives.

Design note -- why bands
-----------------------
Every geometry in this module is represented as a stack of constant-width
horizontal bands, measured downward from the extreme compression fibre. That
single representation gives exact closed-form answers for:

    area above a depth          -> the concrete compressive force
    first moment above a depth  -> the line of action of that force
    gross section properties    -> A, centroid, I, Z

for rectangles, tee sections, inverted tees, stepped webs and box sections
alike. The flexure module then never needs to know what shape it is integrating
over, which is what stops "add a tee section" from meaning "rewrite the stress
block code".

The cost is that curved outlines (circular columns, super-T bulbs) must be
approximated by banding. That is a deliberate trade -- this package's near-term
scope is beams, and a banded circle converges fast enough to be acceptable when
it is needed.

[UNITS] All dimensions mm, areas mm^2, second moments mm^4.

Sign convention
---------------
``y`` is measured DOWNWARD from the extreme compression fibre (the top face in
sagging bending). ``y = 0`` is the top, ``y = D`` is the soffit. This matches
how the standards write ``d``, ``d_o`` and ``k_u d``, so the design code reads
the same as the printed clause.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.exceptions import ModelError


@dataclass(frozen=True)
class Band:
    """A horizontal slice of constant width.

    [UNITS] mm. ``y_top < y_bot``, both measured down from the compression face.
    """

    y_top: float
    y_bot: float
    width: float

    def __post_init__(self) -> None:
        if self.y_bot <= self.y_top:
            raise ModelError(f"Band must have y_bot > y_top, got {self.y_top} -> {self.y_bot}")
        if self.width <= 0:
            raise ModelError(f"Band width must be positive, got {self.width}")

    @property
    def height(self) -> float:
        return self.y_bot - self.y_top

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True)
class SectionGeometry:
    """A cross-section as a stack of bands, top to bottom.

    Construct via the :func:`rectangle`, :func:`tee` etc. helpers rather than
    directly.
    """

    bands: tuple[Band, ...]
    name: str = "section"

    def __post_init__(self) -> None:
        if not self.bands:
            raise ModelError("Section must have at least one band")
        # [CHECK] Bands must tile the depth with no gaps or overlaps, otherwise
        #         every integral below is silently wrong.
        for upper, lower in zip(self.bands, self.bands[1:]):
            if abs(upper.y_bot - lower.y_top) > 1e-9:
                raise ModelError(
                    f"Bands must be contiguous: band ends at {upper.y_bot}, "
                    f"next begins at {lower.y_top}"
                )
        if abs(self.bands[0].y_top) > 1e-9:
            raise ModelError("Topmost band must start at y = 0 (extreme compression fibre)")

    # -- basic dimensions -----------------------------------------------------

    @property
    def D(self) -> float:  # noqa: N802 -- D is the standard symbol for overall depth
        """Overall depth (mm)."""
        return self.bands[-1].y_bot

    @property
    def b_top(self) -> float:
        """Width at the extreme compression fibre (mm)."""
        return self.bands[0].width

    @property
    def b_bottom(self) -> float:
        """Width at the soffit (mm)."""
        return self.bands[-1].width

    @property
    def b_min(self) -> float:
        """Narrowest width anywhere in the section (mm).

        Used as the default web width ``b_v`` for shear where the caller has
        not stated one. Conservative for a tee; for a section with a local
        narrowing this may be over-conservative, so state ``bw`` explicitly.
        """
        return min(band.width for band in self.bands)

    def width_at(self, y: float) -> float:
        """Width at depth ``y`` below the compression face (mm).

        At a band boundary the LOWER band's width is returned, so a tee
        evaluated exactly at the flange soffit gives the web width.
        """
        if y < 0 or y > self.D:
            return 0.0
        for band in self.bands:
            if band.y_top <= y < band.y_bot:
                return band.width
        return self.bands[-1].width

    # -- partial integrals, for the stress block ------------------------------

    def area_above(self, y: float) -> float:
        """Area of the section between the compression face and depth ``y``.

        This is the integral the rectangular stress block needs: with
        ``y = gamma.k_u.d``, ``alpha_2.f'c * area_above(y)`` is the concrete
        compressive force, whatever the section shape.

        [UNITS] y in mm, returns mm^2.
        """
        y = _clamp(y, 0.0, self.D)
        total = 0.0
        for band in self.bands:
            if band.y_top >= y:
                break
            top = band.y_top
            bot = min(band.y_bot, y)
            total += band.width * (bot - top)
        return total

    def first_moment_above(self, y: float) -> float:
        """First moment about the compression face of the area above ``y``.

        Dividing by :meth:`area_above` gives the depth to the centroid of the
        compressive stress block -- i.e. the line of action of the concrete
        force, which is what the lever arm is measured from.

        [UNITS] y in mm, returns mm^3.
        """
        y = _clamp(y, 0.0, self.D)
        total = 0.0
        for band in self.bands:
            if band.y_top >= y:
                break
            top = band.y_top
            bot = min(band.y_bot, y)
            h = bot - top
            centroid = 0.5 * (top + bot)
            total += band.width * h * centroid
        return total

    def centroid_above(self, y: float) -> float:
        """Depth to the centroid of the area above ``y`` (mm).

        Returns 0.0 for a zero-depth block, which keeps the flexure solver's
        first iteration from dividing by zero.
        """
        area = self.area_above(y)
        if area <= 0:
            return 0.0
        return self.first_moment_above(y) / area

    # -- gross section properties ---------------------------------------------

    @property
    def area(self) -> float:
        """Gross cross-sectional area (mm^2)."""
        return sum(band.area for band in self.bands)

    @property
    def centroid(self) -> float:
        """Depth to the gross centroid from the compression face (mm)."""
        return self.first_moment_above(self.D) / self.area

    @property
    def I_gross(self) -> float:  # noqa: N802 -- I is the standard symbol
        """Second moment of area about the gross centroid (mm^4).

        Parallel-axis summation over the bands. Exact for banded sections.
        """
        yc = self.centroid
        total = 0.0
        for band in self.bands:
            h = band.height
            own = band.width * h**3 / 12.0
            d = 0.5 * (band.y_top + band.y_bot) - yc
            total += own + band.area * d**2
        return total

    @property
    def Z_top(self) -> float:  # noqa: N802
        """Elastic section modulus referred to the compression face (mm^3)."""
        return self.I_gross / self.centroid

    @property
    def Z_bottom(self) -> float:  # noqa: N802
        """Elastic section modulus referred to the soffit (mm^3).

        This is the one that governs the cracking moment in sagging bending,
        and hence the Cl 8.1.6.1 minimum reinforcement check.
        """
        return self.I_gross / (self.D - self.centroid)

    def describe(self) -> list[str]:
        return [
            f"Section    = {self.name}",
            f"D          = {self.D:.0f} mm",
            f"A_g        = {self.area:.0f} mm^2",
            f"y_c        = {self.centroid:.1f} mm from top",
            f"I_g        = {self.I_gross:.4g} mm^4",
            f"Z_bottom   = {self.Z_bottom:.4g} mm^3",
        ]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


# ---------------------------------------------------------------------------
# Constructors. Each returns a banded SectionGeometry.
# ---------------------------------------------------------------------------


def rectangle(b: float, D: float, name: str = "") -> SectionGeometry:  # noqa: N803
    """Rectangular section.

    [UNITS] b, D in mm.

    Parameters
    ----------
    b:
        Width.
    D:
        Overall depth.
    """
    return SectionGeometry(
        bands=(Band(0.0, D, b),),
        name=name or f"{b:.0f} x {D:.0f} RECT",
    )


def tee(bf: float, Df: float, bw: float, D: float, name: str = "") -> SectionGeometry:  # noqa: N803
    """Tee section -- flange at the top, in sagging bending.

    [UNITS] all mm.

    Parameters
    ----------
    bf:
        Effective flange width.
    Df:
        Flange thickness.
    bw:
        Web width.
    D:
        Overall depth including the flange.
    """
    if Df >= D:
        raise ModelError(f"Flange thickness {Df} must be less than overall depth {D}")
    return SectionGeometry(
        bands=(Band(0.0, Df, bf), Band(Df, D, bw)),
        name=name or f"T {bf:.0f}/{Df:.0f} x {bw:.0f}/{D:.0f}",
    )


def inverted_tee(
    bw: float, D: float, bf: float, Df: float, name: str = ""  # noqa: N803
) -> SectionGeometry:
    """Inverted tee -- flange at the SOFFIT, in sagging bending.

    Note this is also the shape a normal tee presents in HOGGING bending. Model
    hogging by flipping the section rather than by adding sign logic to the
    design code -- the design code assumes compression at the top throughout.

    [UNITS] all mm.
    """
    if Df >= D:
        raise ModelError(f"Flange thickness {Df} must be less than overall depth {D}")
    return SectionGeometry(
        bands=(Band(0.0, D - Df, bw), Band(D - Df, D, bf)),
        name=name or f"IT {bw:.0f}/{D:.0f} x {bf:.0f}/{Df:.0f}",
    )


def box(b: float, D: float, t_web: float, n_webs: int = 2, name: str = "") -> SectionGeometry:  # noqa: N803
    """Rectangular box, banded as a solid outer with the void's width removed.

    [ASSUMPTION] Modelled as a single band of total web width ``n_webs * t_web``
                 over the full depth PLUS the top and bottom slabs. For flexure
                 this is exact provided the neutral axis is within the top slab
                 or the webs; verify before using it where the NA falls in the
                 bottom slab.

    [UNITS] all mm.
    """
    raise NotImplementedError(
        "box() is a placeholder. Build it from explicit Band() stacks for now "
        "so the banding assumptions are visible at the call site."
    )


def from_bands(widths_and_depths: list[tuple[float, float]], name: str = "") -> SectionGeometry:
    """Build a section from ``[(width, height), ...]`` top to bottom.

    The general escape hatch for any stepped shape the named constructors do
    not cover.

    [UNITS] all mm.

    Examples
    --------
    A 300 wide x 200 deep flange over a 150 wide x 400 deep web::

        from_bands([(300, 200), (150, 400)])
    """
    bands: list[Band] = []
    y = 0.0
    for width, height in widths_and_depths:
        bands.append(Band(y, y + height, width))
        y += height
    return SectionGeometry(bands=tuple(bands), name=name or "custom")
