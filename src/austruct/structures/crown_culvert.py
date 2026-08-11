"""Crown (arch) culvert -- two legs and an arched crown, on footings.

How this differs from a box, structurally
-----------------------------------------
A box culvert carries load in **bending**. A crown unit carries it mostly in
**thrust**: the arch pushes outward at its springings, and what is left over
after the thrust has done its work is a comparatively small moment. That single
difference changes what the analysis has to get right.

1. **Axial force stops being an afterthought.** In a box the axial force in the
   top slab is a minor consequence of the frame action; in an arch it IS the
   load path. This is where the plane frame's axial degree of freedom earns its
   place -- a beam solver cannot model an arch at all.

2. **The springing thrust is a design output, not a by-product.** The footings
   have to resist it, and it is the number that decides whether the unit can be
   founded as drawn. :meth:`CrownResults.springing_thrust` reports it.

3. **Lateral earth pressure is helpful.** On a box it bends the walls inward
   and is a load. On an arch it pushes back against the outward thrust, so a
   crown unit backfilled evenly on both sides is *better* off than one
   backfilled on one side only. Which means the unbalanced case is the one that
   governs, and ``surcharge_left`` / ``surcharge_right`` exist to build it.

4. **The fill depth varies across the crown.** It is deepest at the springings
   and shallowest at the apex, because the crown is curved. Treating it as
   uniform -- which is what a box calculation does -- misses that entirely.

Soil loading on a curved surface
--------------------------------
At depth ``h`` the free-field soil stress is vertical ``sigma_v`` and horizontal
``sigma_h = K0 . sigma_v``. The traction on a surface whose outward normal is
``n`` is then ``t = (sigma_h . n_x, sigma_v . n_y)``, which has BOTH a component
normal to the member and one along it. Both are applied.

That is more than a box calculation needs -- on a horizontal slab the tangential
component vanishes -- and it is the right physics for an arch, where the
tangential traction feeds directly into the thrust.

[ASSUMPTION] Free-field stresses. Soil-structure interaction is NOT modelled:
             no arching, no relative-stiffness redistribution, no Marston or
             Spangler factor. A rigid culvert under fill attracts MORE vertical
             load than the free field, so this is UNCONSERVATIVE unless the
             caller supplies ``vertical_arching_factor``.

What this is not
----------------
It is a parametric model of a crown unit, not a model of any manufacturer's
product. Humes and others publish span, rise, thicknesses and haunch dimensions
for each unit in their range; those numbers must be read off the catalogue and
entered. Nothing in this module knows them, and nothing in it should be taken
as a substitute for the manufacturer's own design.

[UNITS] mm, N, MPa. Pressures N/mm^2 (1 MPa = 1000 kPa).

[VECTOR] K0, the subgrade modulus and the arching factor are all UNVERIFIED
         geotechnical inputs, not code values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum

from ..analysis.frame import (
    Frame,
    Member,
    MemberLoad,
    Node,
    Restraint,
    solve_frame,
)
from ..core.exceptions import ModelError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from ..core.units import g
from .box_culvert import DEFAULT_K0, DEFAULT_SUBGRADE_MODULUS
from .perimeter import PerimeterLayout
from .profile import Arc, Constant, Haunched, Line, Segment, Tapered

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.DEMAND,
    ),
    description="Crown (arch) culvert as a plane frame, with tapered legs and a haunched crown",
    envelope_summary=(
        "Single-cell arch on two legs; circular crown; linear elastic; "
        "free-field soil stresses with no arching; no soil-structure interaction"
    ),
)


class Part(str, Enum):
    """The three segments of a crown unit.

    Directions are chosen so a fraction reads the way an engineer would say it:

    ==============  ==============  ==============================
    Part            Runs from       Fraction 0.0 is ...
    ==============  ==============  ==============================
    ``LEFT_LEG``    base to spring  the base of the left leg
    ``CROWN``       left to right   the left springing
    ``RIGHT_LEG``   base to spring  the base of the right leg
    ==============  ==============  ==============================

    So 0.5 on the crown is the apex, and 1.0 on a leg is its springing.
    """

    LEFT_LEG = "left leg"
    CROWN = "crown"
    RIGHT_LEG = "right leg"

    @property
    def label(self) -> str:
        return self.value


class BaseFixity(str, Enum):
    """How the feet of the legs are held.

    ``PINNED`` is the usual idealisation for a precast unit seated on a strip
    footing: the joint can rotate, and pretending otherwise attracts a base
    moment the detail cannot deliver.

    ``FIXED`` suits a unit cast monolithically with its footing.

    ``SPRUNG`` puts a vertical spring under each foot and pins it horizontally,
    which is the honest model where settlement matters.
    """

    PINNED = "pinned"
    FIXED = "fixed"
    SPRUNG = "sprung"


@dataclass(frozen=True)
class CrownGeometry:
    """Dimensions of a crown unit, on member centrelines.

    Attributes
    ----------
    span:
        Horizontal distance between the leg centrelines at springing level (mm).
    rise:
        Height of the crown apex above springing level, on the centreline (mm).
    leg_height:
        Height of the springing above the base of the legs (mm). Zero for a
        unit that springs straight off its footing.
    crown_thickness:
        Crown thickness away from the haunches (mm).
    haunch_thickness:
        Crown thickness at the springing (mm). Equal to ``crown_thickness``
        for a unit with no haunch.
    haunch_extent:
        Fraction of the crown's arc length over which each haunch runs.
    leg_thickness_base, leg_thickness_top:
        Leg thickness at the footing and at the springing (mm). Equal for a
        prismatic leg.
    transverse_width:
        Width analysed, out of plane (mm).
    """

    span: float
    rise: float
    leg_height: float = 0.0
    crown_thickness: float = 200.0
    haunch_thickness: float = 200.0
    haunch_extent: float = 0.15
    leg_thickness_base: float = 250.0
    leg_thickness_top: float = 250.0
    transverse_width: float = 1000.0

    def __post_init__(self) -> None:
        if self.span <= 0:
            raise ModelError(f"Span must be positive, got {self.span}")
        if self.rise <= 0:
            raise ModelError(
                f"Rise must be positive, got {self.rise}. A crown unit with no "
                "rise is a box culvert -- use BoxCulvert, which models the "
                "corners properly."
            )
        if self.leg_height < 0:
            raise ModelError(f"Leg height must be non-negative, got {self.leg_height}")
        for name in (
            "crown_thickness",
            "haunch_thickness",
            "leg_thickness_base",
            "leg_thickness_top",
            "transverse_width",
        ):
            if getattr(self, name) <= 0:
                raise ModelError(f"{name} must be positive, got {getattr(self, name)}")

    @property
    def springing_level(self) -> float:
        """Height of the springing above the base of the legs (mm)."""
        return self.leg_height

    @property
    def apex_level(self) -> float:
        """Height of the crown apex above the base of the legs (mm)."""
        return self.leg_height + self.rise

    @property
    def crown_radius(self) -> float:
        """Radius of the crown arc (mm)."""
        a = self.span / 2.0
        return (a * a + self.rise * self.rise) / (2.0 * self.rise)

    def recommended_crown_divisions(self, max_angle_deg: float = 5.0) -> int:
        """How many elements the crown needs for the chord error to be small.

        The crown is modelled as a chain of chords, and the error in that
        approximation depends on the angle each chord subtends -- not on the
        span, and not on how many divisions sound generous. A 4 m crown at a
        0.3 rise ratio subtends about 124 degrees, so eight divisions put 15
        degrees in each chord and leave the peak moment some 12% out.

        Aiming at five degrees per chord brings that to around 1%, which is
        below every other uncertainty in the model.

        This matters more on an arch than node placement does. On a box,
        refinement is the whole game because the geometry is exact and only the
        sampling is coarse; on a curve the geometry is approximate too, and no
        amount of clever node placement fixes it.
        """
        total = math.degrees(2 * math.asin(min(1.0, (self.span / 2) / self.crown_radius)))
        return max(8, math.ceil(total / max_angle_deg))

    @property
    def rise_to_span(self) -> float:
        """Rise divided by span. The single number that says how much of an
        arch this is: below about 0.15 the unit behaves much more like a beam
        and the thrust it develops needs a footing that can hold it."""
        return self.rise / self.span

    def segments(self) -> tuple[Segment, ...]:
        """The three segments, with their paths, thicknesses and normals."""
        y_spring = self.springing_level
        left = (0.0, y_spring)
        right = (self.span, y_spring)

        crown_thickness = (
            Constant(self.crown_thickness)
            if abs(self.haunch_thickness - self.crown_thickness) < 1e-9
            else Haunched(
                mid=self.crown_thickness,
                haunch=self.haunch_thickness,
                extent=self.haunch_extent,
            )
        )
        leg_thickness = (
            Constant(self.leg_thickness_base)
            if abs(self.leg_thickness_top - self.leg_thickness_base) < 1e-9
            else Tapered(start=self.leg_thickness_base, end=self.leg_thickness_top)
        )

        out: list[Segment] = []
        if self.leg_height > 0:
            out.append(
                Segment(
                    Part.LEFT_LEG.value,
                    Line((0.0, 0.0), left),
                    leg_thickness,
                    normal_sign=+1.0,
                )
            )
        out.append(
            Segment(
                Part.CROWN.value,
                Arc(left, right, rise=self.rise),
                crown_thickness,
                normal_sign=+1.0,
            )
        )
        if self.leg_height > 0:
            out.append(
                Segment(
                    Part.RIGHT_LEG.value,
                    Line((self.span, 0.0), right),
                    leg_thickness,
                    normal_sign=-1.0,
                )
            )
        return tuple(out)

    def describe(self) -> list[str]:
        lines = [
            f"Span (c/c)      = {self.span:.0f} mm",
            f"Rise            = {self.rise:.0f} mm   (rise/span {self.rise_to_span:.3f})",
            f"Crown radius    = {self.crown_radius:.0f} mm",
            f"Leg height      = {self.leg_height:.0f} mm",
            f"Crown thickness = {self.crown_thickness:.0f} mm",
        ]
        if abs(self.haunch_thickness - self.crown_thickness) > 1e-9:
            lines.append(
                f"Haunch          = {self.haunch_thickness:.0f} mm over the "
                f"outer {self.haunch_extent:.0%} of each half"
            )
        if abs(self.leg_thickness_top - self.leg_thickness_base) > 1e-9:
            lines.append(
                f"Legs            = {self.leg_thickness_base:.0f} mm at base "
                f"tapering to {self.leg_thickness_top:.0f} mm at springing"
            )
        elif self.leg_height > 0:
            lines.append(f"Legs            = {self.leg_thickness_base:.0f} mm")
        lines.append(f"Analysed width  = {self.transverse_width:.0f} mm")
        return lines


@dataclass(frozen=True)
class CrownLoading:
    """What acts on the crown unit.

    Attributes
    ----------
    fill_depth:
        Depth of fill above the crown APEX (mm). This is how cover is specified
        and dimensioned; the depth everywhere else follows from the geometry.
    fill_density:
        Backfill density (kg/m^3).
    concrete_density:
        Self-weight density (kg/m^3). Zero to omit self weight.
    k0:
        Lateral earth pressure coefficient.
    surcharge:
        Uniform vertical surcharge at the fill surface (N/mm^2).
    surcharge_left, surcharge_right:
        Additional surcharge applied only to the left or right half. The
        UNBALANCED case is what governs an arch, because symmetric lateral
        pressure largely cancels and asymmetric pressure does not.
    vertical_arching_factor:
        Multiplier on the vertical soil stress, for the load a rigid culvert
        attracts in excess of the free field. ``1.0`` is the free field and is
        UNCONSERVATIVE for a rigid unit under deep fill.
    """

    fill_depth: float = 0.0
    fill_density: float = 2000.0
    concrete_density: float = 2400.0
    k0: float = DEFAULT_K0
    surcharge: float = 0.0
    surcharge_left: float = 0.0
    surcharge_right: float = 0.0
    vertical_arching_factor: float = 1.0

    def __post_init__(self) -> None:
        if self.fill_depth < 0:
            raise ModelError(f"Fill depth must be non-negative, got {self.fill_depth}")
        if self.k0 <= 0:
            raise ModelError(f"k0 must be positive, got {self.k0}")
        if self.vertical_arching_factor <= 0:
            raise ModelError("vertical_arching_factor must be positive")

    @property
    def is_unbalanced(self) -> bool:
        return abs(self.surcharge_left - self.surcharge_right) > 0.0

    def vertical_stress(self, depth: float, x_fraction: float = 0.5) -> float:
        """Vertical soil stress at a depth below the fill surface (N/mm^2).

        ``x_fraction`` is the position across the span, 0 at the left springing
        and 1 at the right, used to apply the one-sided surcharges.
        """
        base = self.fill_density * g * 1e-9 * max(0.0, depth) + self.surcharge
        side = self.surcharge_left if x_fraction < 0.5 else self.surcharge_right
        return self.vertical_arching_factor * base + side

    def horizontal_stress(self, depth: float, x_fraction: float = 0.5) -> float:
        """Horizontal soil stress at a depth (N/mm^2).

        ``K0`` is applied to the free-field vertical stress, NOT to the arched
        value -- the arching factor represents load shed onto the structure by
        the soil above it, which does not raise the horizontal stress beside it.
        """
        base = self.fill_density * g * 1e-9 * max(0.0, depth) + self.surcharge
        side = self.surcharge_left if x_fraction < 0.5 else self.surcharge_right
        return self.k0 * (base + side)


@dataclass(frozen=True)
class CrownCulvert:
    """A crown (arch) culvert, ready to analyse."""

    geometry: CrownGeometry
    loading: CrownLoading = field(default_factory=CrownLoading)
    E: float = 32800.0  # noqa: N815
    layout: PerimeterLayout = field(default_factory=PerimeterLayout)
    base_fixity: BaseFixity = BaseFixity.PINNED
    subgrade_modulus: float = DEFAULT_SUBGRADE_MODULUS
    name: str = ""

    def __post_init__(self) -> None:
        names = tuple(s.name for s in self.geometry.segments())
        layout = self.layout
        if tuple(layout.segments) != names:
            layout = layout.for_segments(names)

        # Give the crown enough divisions for its own curvature unless the
        # caller has said otherwise. A default that ignores the subtended angle
        # is wrong by more than 10% on a deep arch, and silently so.
        if Part.CROWN.value not in layout.divisions:
            layout = layout.with_divisions(
                Part.CROWN.value, self.geometry.recommended_crown_divisions()
            )
        object.__setattr__(self, "layout", layout)

    # -- construction ---------------------------------------------------------

    def build(self) -> tuple[Frame, dict[str, list[int]]]:
        """Assemble the frame, and a map from each segment to its members."""
        geom = self.geometry
        segments = geom.segments()

        nodes: list[Node] = []
        index: dict[tuple[float, float], int] = {}

        def node_index(x: float, y: float, label: str = "") -> int:
            key = (round(x, 6), round(y, 6))
            if key not in index:
                index[key] = len(nodes)
                nodes.append(Node(x, y, label))
            return index[key]

        members: list[Member] = []
        member_loads: list[MemberLoad] = []
        by_segment: dict[str, list[int]] = {}

        for segment in segments:
            fractions = self.layout.fractions(segment.name)
            points = [segment.path.point_at(f) for f in fractions]
            indices = [node_index(x, y) for x, y in points]
            by_segment[segment.name] = []

            for k in range(len(indices) - 1):
                f_mid = 0.5 * (fractions[k] + fractions[k + 1])
                t = segment.thickness.at(f_mid)
                ei = self.E * geom.transverse_width * t**3 / 12.0
                ea = self.E * geom.transverse_width * t

                members.append(
                    Member(
                        indices[k],
                        indices[k + 1],
                        EA=ea,
                        EI=ei,
                        name=f"{segment.name}-{k + 1}",
                    )
                )
                idx = len(members) - 1
                by_segment[segment.name].append(idx)
                member_loads.append(
                    self._element_load(idx, segment, fractions[k], fractions[k + 1], t)
                )

        restraints = self._restraints(nodes, geom)

        frame = Frame(
            nodes=tuple(nodes),
            members=tuple(members),
            restraints=tuple(restraints),
            member_loads=tuple(load for load in member_loads if load is not None),
            name=self.name or "Crown culvert",
        )
        return frame, by_segment

    def _element_load(
        self,
        index: int,
        segment: Segment,
        f_start: float,
        f_end: float,
        thickness: float,
    ) -> MemberLoad:
        """Soil traction plus self weight on one element, in LOCAL axes.

        The soil traction is the free-field stress state resolved onto the
        element's own orientation, so a curved crown picks up both a normal and
        a tangential component without either being written out by hand.
        """
        geom = self.geometry
        f_mid = 0.5 * (f_start + f_end)
        x, y = segment.path.point_at(f_mid)
        nx, ny = segment.outward_normal_at(f_mid)
        tx, ty = segment.path.tangent_at(f_mid)

        depth = geom.apex_level + self.loading.fill_depth - y
        x_fraction = x / geom.span if geom.span else 0.5
        sigma_v = self.loading.vertical_stress(depth, x_fraction)
        sigma_h = self.loading.horizontal_stress(depth, x_fraction)

        # Traction on a plane with outward normal n, for a diagonal stress
        # state (compression positive): t = (sigma_h.n_x, sigma_v.n_y). It acts
        # INTO the surface, i.e. along -n.
        width = geom.transverse_width
        traction_x = -sigma_h * nx * width
        traction_y = -sigma_v * ny * width

        # Self weight, globally downward.
        self_weight = self.loading.concrete_density * g * 1e-9 * thickness * width
        traction_y -= self_weight

        # Resolve into the member's local axes. Local x' is the tangent; local
        # y' is the LEFT normal, which is the path normal before the segment's
        # outward sign is applied.
        lx, ly = -ty, tx
        w_axial = traction_x * tx + traction_y * ty
        w_perp = traction_x * lx + traction_y * ly

        return MemberLoad(member=index, w_perp=w_perp, w_axial=w_axial)

    def _restraints(self, nodes: list[Node], geom: CrownGeometry) -> list[Restraint]:
        """Support at the foot of each leg."""
        feet = []
        for x in (0.0, geom.span):
            y = 0.0 if geom.leg_height > 0 else geom.springing_level
            for i, node in enumerate(nodes):
                if abs(node.x - x) < 1e-6 and abs(node.y - y) < 1e-6:
                    feet.append(i)
                    break

        if len(feet) != 2:
            raise ModelError(
                "Could not find both leg feet in the mesh. This is a bug in the "
                "geometry construction, not something the caller can fix."
            )

        if self.base_fixity is BaseFixity.FIXED:
            return [Restraint(node=i, ux=True, uy=True, rz=True) for i in feet]

        if self.base_fixity is BaseFixity.SPRUNG:
            # Tributary width per foot: the leg carries into a footing whose
            # size is not modelled, so the spring is per unit width and the
            # caller scales it via subgrade_modulus.
            k = self.subgrade_modulus * geom.leg_thickness_base * geom.transverse_width
            return [Restraint(node=i, ux=True, ky=k) for i in feet]

        return [Restraint(node=i, ux=True, uy=True) for i in feet]

    # -- analysis -------------------------------------------------------------

    def solve(self) -> CrownResults:
        frame, by_segment = self.build()
        return CrownResults(
            culvert=self,
            frame=frame,
            frame_results=solve_frame(frame),
            members_by_segment=by_segment,
        )

    # -- directed adjustment --------------------------------------------------

    def with_layout(self, layout: PerimeterLayout) -> CrownCulvert:
        return replace(self, layout=layout)

    def with_node_at(self, part: Part | str, fraction: float, reason: str = "") -> CrownCulvert:
        """Copy with a node pinned at ``fraction`` along ``part``."""
        return replace(self, layout=self.layout.with_node_at(str(part.value if isinstance(part, Part) else part), fraction, reason))

    def with_node_at_distance(
        self, part: Part | str, distance: float, reason: str = ""
    ) -> CrownCulvert:
        """Copy with a node pinned ``distance`` mm along ``part``.

        For the crown the distance is measured along the ARC, not along the
        chord -- which is what a drawing dimensions and what a precast unit is
        actually made to.
        """
        name = part.value if isinstance(part, Part) else str(part)
        segment = next(s for s in self.geometry.segments() if s.name == name)
        return replace(
            self,
            layout=self.layout.with_node_at_distance(
                name, distance, segment.length, reason
            ),
        )

    def refined(self, passes: int = 1, keep_existing: bool = False) -> CrownCulvert:
        """Solve, find the peak moment inside every member, pin a node there.

        Same operation as :meth:`BoxCulvert.refined`, and the same reasoning:
        a frame reports actions at nodes, so a peak between two nodes is never
        reported. The pinned nodes are cleared once, before the first pass, and
        every pass adds to what the previous found.

        Worth less here than on a box, and it is honest to say so. On a box the
        geometry is exact and only the sampling is coarse, so landing a node on
        the peak fixes the answer outright. On a crown the geometry is a chain
        of chords, so successive passes move the answer as well as the nodes --
        they converge, but by improving the shape rather than by finding the
        peak. Get the crown divisions right first: see
        :meth:`CrownGeometry.recommended_crown_divisions`, which is applied by
        default.
        """
        if passes < 1:
            raise ModelError(f"passes must be at least 1, got {passes}")

        culvert = self
        if not keep_existing:
            culvert = replace(culvert, layout=culvert.layout.without_pinned())

        for _ in range(passes):
            results = culvert.solve()
            layout = culvert.layout
            for name, peaks in results.interior_peaks().items():
                for fraction, _moment in peaks:
                    layout = layout.with_node_at(name, fraction, "peak moment")
            culvert = replace(culvert, layout=layout)
        return culvert

    def describe(self) -> list[str]:
        lines = [f"Crown culvert: {self.name or 'unnamed'}", ""]
        lines.extend(self.geometry.describe())
        lines.append("")
        for segment in self.geometry.segments():
            lines.extend(segment.describe())
        lines.append("")
        lines.append(f"Fill over apex  = {self.loading.fill_depth:.0f} mm")
        lines.append(f"k0              = {self.loading.k0:.2f}")
        lines.append(f"Base fixity     = {self.base_fixity.value}")
        if self.loading.vertical_arching_factor != 1.0:
            lines.append(
                f"Arching factor  = {self.loading.vertical_arching_factor:.2f}"
            )
        if self.loading.is_unbalanced:
            lines.append("Loading is UNBALANCED left to right")
        lines.append("")
        lines.extend(self.layout.describe())
        return lines


@dataclass
class CrownResults:
    """Analysis results for a crown unit."""

    culvert: CrownCulvert
    frame: Frame
    frame_results: object  # FrameResults
    members_by_segment: dict[str, list[int]]

    # -- actions along a segment ---------------------------------------------

    def segment_moments(self, part: Part | str) -> list[tuple[float, float]]:
        """``[(fraction, moment), ...]`` along a segment.

        Positive means **tension on the INSIDE face** of the opening, the same
        convention the box culvert reports in and for the same reason: a
        designer wants one question answered everywhere, which face gets the
        steel.
        """
        name = part.value if isinstance(part, Part) else str(part)
        sign = self._inside_sign(name)
        return self._along(name, lambda f, i: (sign * -f.M_start, sign * f.M_end), i_unused=True)

    def segment_thrust(self, part: Part | str) -> list[tuple[float, float]]:
        """``[(fraction, axial force), ...]`` along a segment, COMPRESSION
        POSITIVE.

        Compression positive because an arch is in compression everywhere it is
        working, and a design output that is negative everywhere invites sign
        errors downstream.

        The frame returns the actions the nodes exert on the member, in which
        ``N_start`` is already compression-positive but ``N_end`` is the
        opposite -- the two ends of an axially loaded member carry equal and
        opposite end actions. Hence the negation on the end value only.
        """
        name = part.value if isinstance(part, Part) else str(part)
        return self._along(name, lambda f, i: (f.N_start, -f.N_end), i_unused=True)

    def _along(self, name, extract, i_unused=False):  # noqa: ANN001, ANN202, ARG002
        """Walk a segment, pairing each element's end actions with its nodes.

        Positions come from the LAYOUT's fractions, not from accumulated
        element lengths. On a curved segment those differ: the elements are
        chords and their lengths sum to slightly less than the arc, so
        accumulating them puts the last node at 0.997 rather than 1.0 and the
        segment stops being symmetric about its own midpoint.

        The nodes were placed at the layout's fractions in the first place, so
        reading them back from there is both exact and consistent.
        """
        indices = self.members_by_segment[name]
        fractions = self.culvert.layout.fractions(name)

        out: list[tuple[float, float]] = []
        for k, idx in enumerate(indices):
            forces = self.frame_results.member_forces[idx]  # type: ignore[attr-defined]
            a, b = extract(forces, idx)
            out.append((fractions[k], a))
            out.append((fractions[k + 1], b))

        merged: dict[float, float] = {}
        for frac, value in out:
            key = round(frac, 9)
            if key not in merged or abs(value) > abs(merged[key]):
                merged[key] = value
        return sorted(merged.items())

    def _inside_sign(self, name: str) -> float:
        """Sign converting the diagram moment to inside-face-tension positive.

        Same problem as the box: the segments are drawn in the directions that
        make their fractions read naturally, so the local axes do not agree
        about which side is in. The right leg is the odd one out.
        """
        return -1.0 if name == Part.RIGHT_LEG.value else 1.0

    def interior_peaks(self) -> dict[str, list[tuple[float, float]]]:
        """Where the moment peaks INSIDE each member, as segment fractions."""
        peaks: dict[str, list[tuple[float, float]]] = {}
        loads = {load.member: load for load in self.frame.member_loads}

        for name, indices in self.members_by_segment.items():
            fractions = self.culvert.layout.fractions(name)
            sign = self._inside_sign(name)
            found: list[tuple[float, float]] = []

            for k, idx in enumerate(indices):
                forces = self.frame_results.member_forces[idx]  # type: ignore[attr-defined]
                load = loads.get(idx)
                if load is None or load.w_perp == 0.0:
                    continue
                s = -forces.V_start / load.w_perp
                if not 0.0 < s < forces.length:
                    continue
                # Map the position within the element onto the segment's own
                # fraction scale, by interpolating between the element's two
                # node fractions -- not by dividing a chord length by an arc
                # length, which do not agree on a curve.
                lo, hi = fractions[k], fractions[k + 1]
                position = lo + (s / forces.length) * (hi - lo)
                found.append((position, sign * forces.moment_at(s, load.w_perp)))
            if found:
                peaks[name] = found
        return peaks

    def peak_moment(self, part: Part | str) -> tuple[float, float]:
        """``(fraction, moment)`` of the largest moment magnitude on a segment."""
        name = part.value if isinstance(part, Part) else str(part)
        candidates = list(self.segment_moments(name))
        candidates.extend(self.interior_peaks().get(name, []))
        return max(candidates, key=lambda pair: abs(pair[1]))

    # -- the numbers an arch is designed on ----------------------------------

    def springing_thrust(self) -> tuple[float, float]:
        """``(horizontal, vertical)`` reaction at the LEFT foot (N).

        The horizontal component is the arch thrust, and it is the number that
        decides whether the unit can be founded as drawn -- the footing, or the
        base slab tying the two feet together, has to resist it.

        Sign: positive horizontal means the structure pushes the support to the
        RIGHT, i.e. inward for the left foot. An arch under vertical load
        pushes its supports OUTWARD, so the left foot reaction is expected
        positive here.
        """
        reactions = self.frame_results.reactions  # type: ignore[attr-defined]
        foot = min(reactions)
        rx, ry, _ = reactions[foot]
        return rx, ry

    @property
    def max_thrust(self) -> float:
        """Largest COMPRESSIVE axial force anywhere in the structure (N).

        Zero if nothing is in compression, which for an arch would mean the
        model is wrong.
        """
        return max(
            (
                max(f.N_start, -f.N_end)
                for f in self.frame_results.member_forces  # type: ignore[attr-defined]
            ),
            default=0.0,
        )

    @property
    def max_moment(self) -> float:
        return self.frame_results.max_moment  # type: ignore[attr-defined]

    @property
    def arch_efficiency(self) -> float:
        """``M / (N . t)`` at the crown apex -- how much of an arch this is.

        A pure arch carries its load as thrust with the line of thrust inside
        the section, giving a small ratio. A value approaching or exceeding
        0.17 (= t/6 divided by t) means the line of thrust has left the middle
        third and the section is in bending as much as compression.
        """
        crown = Part.CROWN.value
        moments = dict(self.segment_moments(crown))
        thrusts = dict(self.segment_thrust(crown))
        apex = min(moments, key=lambda f: abs(f - 0.5))
        m = abs(moments[apex])
        n = abs(thrusts.get(apex, 0.0))
        t = self.culvert.geometry.crown_thickness
        if n == 0 or t == 0:
            return float("inf")
        return m / (n * t)

    def describe(self) -> list[str]:
        geom = self.culvert.geometry
        lines = [f"Crown culvert results: {self.culvert.name or 'unnamed'}", ""]
        lines.append(f"{'segment':<12}{'peak M':>11}{'at':>9}{'max thrust':>13}")
        lines.append(f"{'':<12}{'kN.m':>11}{'fraction':>9}{'kN':>13}")
        lines.append("-" * 45)
        for segment in geom.segments():
            frac, moment = self.peak_moment(segment.name)
            thrust = max(abs(t) for _, t in self.segment_thrust(segment.name))
            lines.append(
                f"{segment.name:<12}{moment / 1e6:>11.1f}{frac:>9.3f}{thrust / 1e3:>13.1f}"
            )

        h, v = self.springing_thrust()
        lines.append("")
        lines.append("Springing reaction (left foot):")
        lines.append(f"  horizontal thrust {h / 1e3:8.1f} kN   <- the footing must resist this")
        lines.append(f"  vertical          {v / 1e3:8.1f} kN")
        lines.append(f"  thrust/vertical   {abs(h / v) if v else float('nan'):8.3f}")
        lines.append("")
        lines.append(
            f"Arch efficiency M/(N.t) at the apex = {self.arch_efficiency:.3f}"
        )
        if self.arch_efficiency > 1.0 / 6.0:
            lines.append(
                "  The line of thrust is OUTSIDE the middle third at the apex, "
                "so the crown is bending as much as arching."
            )

        residual = self.frame_results.check_equilibrium()  # type: ignore[attr-defined]
        lines.append("")
        lines.append(
            f"Equilibrium residual: Fx {residual[0]:.3e} N, "
            f"Fy {residual[1]:.3e} N, Mz {residual[2]:.3e} N.mm"
        )
        return lines

    def _repr_markdown_(self) -> str:
        rows = [
            "| Segment | Peak M (kN.m) | at | Max thrust (kN) |",
            "|---|---|---|---|",
        ]
        for segment in self.culvert.geometry.segments():
            frac, moment = self.peak_moment(segment.name)
            thrust = max(abs(t) for _, t in self.segment_thrust(segment.name))
            rows.append(
                f"| {segment.name} | {moment / 1e6:.1f} | {frac:.3f} | {thrust / 1e3:.1f} |"
            )
        h, _ = self.springing_thrust()
        return (
            f"**{self.culvert.name or 'Crown culvert'}** — "
            f"{len(self.frame.nodes)} nodes, springing thrust {h / 1e3:.1f} kN\n\n"
            + "\n".join(rows)
        )
