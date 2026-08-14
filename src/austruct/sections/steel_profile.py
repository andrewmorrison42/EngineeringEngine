"""Steel section geometry as an assembly of rectangular plates.

Why not the banded model
------------------------
:class:`~austruct.sections.primitives.SectionGeometry` is a stack of horizontal
bands, each of one width, centred on a common vertical axis. That is everything
a reinforced concrete section needs, because RC is bent about one axis and its
shapes are symmetric about the other.

Steel is neither. A PFC is symmetric about its horizontal axis and emphatically
not about its vertical one, so a band model with no horizontal offset cannot
place its web. And steel design needs the minor axis second moment, the plastic
modulus, the torsion constant and the warping constant, none of which the banded
model computes.

So a steel section is described here as a set of rectangles, each with its own
centre, width and height. That covers I-sections, channels, plates, and later
hollow sections and angles, and every property follows from the same assembly by
the parallel axis theorem.

Axes
----
``x`` is horizontal and ``y`` is vertical, both measured from the assembly's own
centroid once it is computed. The MAJOR axis is x-x -- bending about it puts the
flanges in tension and compression, which is how a beam is normally used. This
matches AS 4100's convention and is worth stating because "the x axis" means the
opposite in some other traditions.

What the thin-walled approximations are
---------------------------------------
Two properties cannot be had exactly from a plate assembly:

``J``   Torsion constant, taken as ``sum(b.t^3 / 3)`` over the plates. This
        ignores the root fillets, which contribute meaningfully -- published
        values for a rolled section run perhaps 10-25% above the thin-walled
        sum. The error is one-sided and unconservative for anything that relies
        on torsional stiffness, which includes lateral-torsional buckling.

``I_w`` Warping constant, which depends on the shape and is computed per shape
        type rather than generically. There is no shape-independent expression.

Both are flagged on the result so a caller cannot mistake them for exact, and
the catalogue cross-check applies a looser tolerance to them for exactly this
reason.

[UNITS] mm, mm^2, mm^3, mm^4, mm^6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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
        component=ASETComponent.REFERENCE_DATA,
    ),
    description="Steel section geometry as an assembly of rectangular plates",
    envelope_summary=(
        "Rectangular plates only; thin-walled J ignoring fillets; "
        "I_w computed per shape type"
    ),
)


class ShapeType(str, Enum):
    """What kind of section this is.

    Drives the warping constant, which has no shape-independent expression, and
    the plate-element classification, which depends on whether an element is
    supported on one edge or two.
    """

    I_SECTION = "I"
    """Universal beam or column -- two flanges and a web, doubly symmetric."""

    CHANNEL = "PFC"
    """Parallel flange channel -- symmetric about x-x only."""

    PLATE = "plate"
    """A single rectangle."""

    WELDED_I = "welded I"
    """Fabricated I-section. Same geometry as a rolled one but no root fillets,
    so the thin-walled ``J`` is close to exact rather than low."""


@dataclass(frozen=True)
class Plate:
    """One rectangle in the assembly.

    Attributes
    ----------
    xc, yc:
        Centre of the rectangle, in whatever coordinate system the assembly was
        built in. Recentred on the centroid when properties are computed.
    width:
        Horizontal extent (mm).
    height:
        Vertical extent (mm).
    role:
        ``"flange"``, ``"web"`` or ``"plate"``. Not used in the property
        arithmetic -- it is carried so the classification code can ask which
        elements are outstand flanges and which are supported webs without
        re-deriving it from the geometry.
    """

    xc: float
    yc: float
    width: float
    height: float
    role: str = "plate"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ModelError(
                f"Plate dimensions must be positive, got {self.width} x {self.height}"
            )

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def thickness(self) -> float:
        """The smaller dimension -- what "t" means for a plate element."""
        return min(self.width, self.height)

    @property
    def flat(self) -> float:
        """The larger dimension -- the flat width of the plate element."""
        return max(self.width, self.height)

    def y_extent(self) -> tuple[float, float]:
        return (self.yc - self.height / 2.0, self.yc + self.height / 2.0)

    def x_extent(self) -> tuple[float, float]:
        return (self.xc - self.width / 2.0, self.xc + self.width / 2.0)


@dataclass(frozen=True)
class SectionProperties:
    """Everything a steel design calculation asks the geometry for.

    Attributes
    ----------
    A:
        Gross area (mm^2).
    Ix, Iy:
        Second moments of area about the centroidal axes (mm^4). ``x`` is the
        MAJOR axis.
    Zx, Zy:
        Elastic section moduli (mm^3), taken to the extreme fibre.
    Sx, Sy:
        Plastic section moduli (mm^3).
    rx, ry:
        Radii of gyration (mm).
    J:
        Torsion constant (mm^4), thin-walled and therefore LOW for a rolled
        section -- see the module docstring.
    Iw:
        Warping constant (mm^6).
    d, bf:
        Overall depth and overall width (mm).
    approximate:
        Names of the properties that are approximations rather than exact
        consequences of the plate assembly.
    """

    A: float  # noqa: N815
    Ix: float  # noqa: N815
    Iy: float  # noqa: N815
    Zx: float  # noqa: N815
    Zy: float  # noqa: N815
    Sx: float  # noqa: N815
    Sy: float  # noqa: N815
    rx: float
    ry: float
    J: float  # noqa: N815
    Iw: float  # noqa: N815
    d: float
    bf: float  # noqa: N815
    approximate: tuple[str, ...] = ()

    @property
    def shape_factor_x(self) -> float:
        """``S_x / Z_x`` -- how much reserve there is past first yield.

        About 1.12-1.15 for a rolled I-section bent about its major axis, and
        1.5 for a rectangle. A value outside roughly 1.0 to 1.7 means the
        plastic modulus is wrong.
        """
        return self.Sx / self.Zx if self.Zx else 0.0

    def describe(self) -> list[str]:
        lines = [
            f"A          = {self.A:>10.0f} mm^2",
            f"I_x        = {self.Ix:>10.4g} mm^4",
            f"I_y        = {self.Iy:>10.4g} mm^4",
            f"Z_x        = {self.Zx:>10.4g} mm^3",
            f"S_x        = {self.Sx:>10.4g} mm^3   (S/Z = {self.shape_factor_x:.3f})",
            f"r_x        = {self.rx:>10.1f} mm",
            f"r_y        = {self.ry:>10.1f} mm",
            f"J          = {self.J:>10.4g} mm^4",
            f"I_w        = {self.Iw:>10.4g} mm^6",
        ]
        if self.approximate:
            lines.append(f"Approximate: {', '.join(self.approximate)}")
        return lines


# ---------------------------------------------------------------------------
# The assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SteelProfile:
    """A steel section: a shape type, a set of plates, and a name.

    Build one with :func:`i_section`, :func:`channel` or :func:`plate_section`
    rather than by listing plates, unless the shape is not one of those.
    """

    name: str
    shape: ShapeType
    plates: tuple[Plate, ...]

    def __post_init__(self) -> None:
        if not self.plates:
            raise ModelError(f"Section {self.name!r} has no plates")

    # -- basic geometry -------------------------------------------------------

    @property
    def area(self) -> float:
        return sum(p.area for p in self.plates)

    @property
    def centroid(self) -> tuple[float, float]:
        """``(x, y)`` of the area centroid, in the build coordinates."""
        a = self.area
        return (
            sum(p.area * p.xc for p in self.plates) / a,
            sum(p.area * p.yc for p in self.plates) / a,
        )

    @property
    def depth(self) -> float:
        tops = [p.y_extent()[1] for p in self.plates]
        bots = [p.y_extent()[0] for p in self.plates]
        return max(tops) - min(bots)

    @property
    def width(self) -> float:
        rights = [p.x_extent()[1] for p in self.plates]
        lefts = [p.x_extent()[0] for p in self.plates]
        return max(rights) - min(lefts)

    def plates_with_role(self, role: str) -> tuple[Plate, ...]:
        return tuple(p for p in self.plates if p.role == role)

    # -- second moments -------------------------------------------------------

    def second_moments(self) -> tuple[float, float]:
        """``(I_x, I_y)`` about the centroidal axes, by the parallel axis theorem."""
        cx, cy = self.centroid
        ix = sum(
            p.width * p.height**3 / 12.0 + p.area * (p.yc - cy) ** 2
            for p in self.plates
        )
        iy = sum(
            p.height * p.width**3 / 12.0 + p.area * (p.xc - cx) ** 2
            for p in self.plates
        )
        return ix, iy

    # -- plastic moduli -------------------------------------------------------

    def _area_above(self, y: float, axis: str = "x") -> float:
        """Area on the positive side of a line, in build coordinates."""
        total = 0.0
        for p in self.plates:
            if axis == "x":
                lo, hi = p.y_extent()
                overlap = max(0.0, hi - max(lo, y))
                total += p.width * overlap
            else:
                lo, hi = p.x_extent()
                overlap = max(0.0, hi - max(lo, y))
                total += p.height * overlap
        return total

    def _equal_area_axis(self, axis: str = "x") -> float:
        """Position of the line splitting the section into equal areas.

        Bisection rather than a closed form: the area-above function is
        piecewise linear with a break at every plate edge, so a general
        expression would be a per-shape special case -- which is what the plate
        assembly exists to avoid.
        """
        if axis == "x":
            lo = min(p.y_extent()[0] for p in self.plates)
            hi = max(p.y_extent()[1] for p in self.plates)
        else:
            lo = min(p.x_extent()[0] for p in self.plates)
            hi = max(p.x_extent()[1] for p in self.plates)

        half = self.area / 2.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if self._area_above(mid, axis) > half:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-9:
                break
        return 0.5 * (lo + hi)

    def plastic_modulus(self, axis: str = "x") -> float:
        """First moment of the whole area about the equal-area axis.

        ``S = sum |A_i . dbar_i|`` with plates split at the axis, which is what
        the plastic modulus IS -- the two halves each contribute their area
        times the distance from their own centroid to the axis.
        """
        pna = self._equal_area_axis(axis)
        total = 0.0

        for p in self.plates:
            lo, hi = p.y_extent() if axis == "x" else p.x_extent()
            across = p.width if axis == "x" else p.height

            for a, b in ((lo, min(hi, pna)), (max(lo, pna), hi)):
                if b <= a:
                    continue
                part_area = across * (b - a)
                part_centroid = 0.5 * (a + b)
                total += part_area * abs(part_centroid - pna)
        return total

    # -- torsion and warping --------------------------------------------------

    def torsion_constant(self) -> float:
        """``J = sum(b.t^3 / 3)`` -- the thin-walled open-section value.

        LOW for a rolled section, because the root fillets add material exactly
        where torsional stiffness is most sensitive to it. See the module
        docstring.
        """
        return sum(p.flat * p.thickness**3 / 3.0 for p in self.plates)

    def warping_constant(self) -> float:
        """``I_w``, computed per shape type.

        There is no shape-independent expression, so this dispatches. A shape
        the module does not recognise gets zero, which is the correct value for
        a plate and a conservative one elsewhere -- but a caller relying on it
        should check that the shape is handled.
        """
        if self.shape in (ShapeType.I_SECTION, ShapeType.WELDED_I):
            flanges = self.plates_with_role("flange")
            if len(flanges) != 2:
                return 0.0
            _, iy = self.second_moments()
            # Iw = Iy . hs^2 / 4, with hs the distance between flange centroids.
            hs = abs(flanges[0].yc - flanges[1].yc)
            return iy * hs**2 / 4.0

        if self.shape is ShapeType.CHANNEL:
            return self._channel_warping()

        # A single plate has no warping stiffness worth the name.
        return 0.0

    def _channel_warping(self) -> float:
        """Warping constant of a channel.

        A channel's shear centre lies OUTSIDE the section, on the far side of
        the web from the flanges, and the warping constant follows from that
        offset. Both are computed here on the thin-walled idealisation.
        """
        flanges = self.plates_with_role("flange")
        webs = self.plates_with_role("web")
        if len(flanges) != 2 or len(webs) != 1:
            return 0.0

        tf = flanges[0].height
        tw = webs[0].width
        h = abs(flanges[0].yc - flanges[1].yc)  # between flange centroids
        # Flange flat measured from the web centreline to the toe.
        b = flanges[0].width - tw / 2.0

        return (tf * b**3 * h**2 / 12.0) * ((3.0 * b * tf + 2.0 * h * tw) /
                                            (6.0 * b * tf + h * tw))

    # -- the assembled answer -------------------------------------------------

    def properties(self) -> SectionProperties:
        """Every property, computed from the plate assembly."""
        a = self.area
        ix, iy = self.second_moments()
        cx, cy = self.centroid

        y_top = max(p.y_extent()[1] for p in self.plates) - cy
        y_bot = cy - min(p.y_extent()[0] for p in self.plates)
        x_right = max(p.x_extent()[1] for p in self.plates) - cx
        x_left = cx - min(p.x_extent()[0] for p in self.plates)

        approximate = ["J (thin-walled, ignores fillets)"]
        if self.shape is ShapeType.CHANNEL:
            approximate.append("I_w (thin-walled channel)")
        elif self.shape in (ShapeType.I_SECTION, ShapeType.WELDED_I):
            approximate.append("I_w (flange-centroid idealisation)")

        return SectionProperties(
            A=a,
            Ix=ix,
            Iy=iy,
            Zx=ix / max(y_top, y_bot),
            Zy=iy / max(x_left, x_right),
            Sx=self.plastic_modulus("x"),
            Sy=self.plastic_modulus("y"),
            rx=math.sqrt(ix / a),
            ry=math.sqrt(iy / a),
            J=self.torsion_constant(),
            Iw=self.warping_constant(),
            d=self.depth,
            bf=self.width,
            approximate=tuple(approximate),
        )

    def describe(self) -> list[str]:
        lines = [f"{self.name}  ({self.shape.value})", ""]
        lines.extend(self.properties().describe())
        return lines


# ---------------------------------------------------------------------------
# Constructors -- the shapes, built the way a catalogue describes them
# ---------------------------------------------------------------------------


def i_section(
    d: float,
    bf: float,  # noqa: N803
    tf: float,
    tw: float,
    name: str = "",
    welded: bool = False,
) -> SteelProfile:
    """A doubly symmetric I-section from its catalogue dimensions.

    Parameters
    ----------
    d:
        Overall depth (mm).
    bf:
        Flange width (mm).
    tf:
        Flange thickness (mm).
    tw:
        Web thickness (mm).
    welded:
        Fabricated rather than rolled. Changes only the shape type, which the
        torsion constant note and the classification limits key off -- the
        geometry is identical.

    Notes
    -----
    The web is taken as the FULL clear depth between the flanges, ``d - 2 tf``.
    The root radii are not modelled, which is where the small shortfall in
    computed area and ``I_x`` against published values comes from.
    """
    if d <= 2 * tf:
        raise ModelError(
            f"Section depth {d} must exceed twice the flange thickness {tf}"
        )
    web_depth = d - 2.0 * tf
    return SteelProfile(
        name=name or f"{d:.0f}x{bf:.0f} I",
        shape=ShapeType.WELDED_I if welded else ShapeType.I_SECTION,
        plates=(
            Plate(xc=0.0, yc=(d - tf) / 2.0, width=bf, height=tf, role="flange"),
            Plate(xc=0.0, yc=0.0, width=tw, height=web_depth, role="web"),
            Plate(xc=0.0, yc=-(d - tf) / 2.0, width=bf, height=tf, role="flange"),
        ),
    )


def channel(
    d: float,
    bf: float,  # noqa: N803
    tf: float,
    tw: float,
    name: str = "",
) -> SteelProfile:
    """A parallel flange channel from its catalogue dimensions.

    The web sits at the left, flanges extend to the right. The section is
    symmetric about x-x and not about y-y, which is the whole reason the plate
    assembly exists -- the centroid is offset from the web and every minor-axis
    property depends on that offset.
    """
    if d <= 2 * tf:
        raise ModelError(
            f"Channel depth {d} must exceed twice the flange thickness {tf}"
        )
    web_depth = d - 2.0 * tf
    return SteelProfile(
        name=name or f"{d:.0f} PFC",
        shape=ShapeType.CHANNEL,
        plates=(
            Plate(xc=bf / 2.0, yc=(d - tf) / 2.0, width=bf, height=tf, role="flange"),
            Plate(xc=tw / 2.0, yc=0.0, width=tw, height=web_depth, role="web"),
            Plate(xc=bf / 2.0, yc=-(d - tf) / 2.0, width=bf, height=tf, role="flange"),
        ),
    )


def plate_section(b: float, t: float, name: str = "") -> SteelProfile:
    """A single rectangular plate, bent about its strong axis.

    ``b`` is the depth in the plane of bending and ``t`` the thickness, so a
    150 x 12 flat bar on edge is ``plate_section(150, 12)``.
    """
    return SteelProfile(
        name=name or f"{b:.0f}x{t:.0f} PL",
        shape=ShapeType.PLATE,
        plates=(Plate(xc=0.0, yc=0.0, width=t, height=b, role="plate"),),
    )
