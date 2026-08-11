"""Box culvert as a closed frame on soil springs.

Why a frame and not a simply supported slab
-------------------------------------------
Modelling a culvert top slab as a simply supported member -- which is what this
package could do before -- gets the midspan sagging moment roughly right and
gets everything else wrong. The real structure is a closed box: the walls
restrain the slab ends, so the slab carries hogging moment at the corners that
a simply supported model reports as zero, and the sagging moment is
correspondingly less than ``wL^2/8``. Design the corners off a simply supported
model and there is no top steel where the tension actually is.

The closed frame also picks up what the walls do: lateral earth pressure pushes
them inward, which puts sagging into the slab and hogging into the corners in
the opposite sense to the vertical load. Those two effects partly cancel, and
which one wins depends on the fill depth and the lateral earth pressure
coefficient. That is not a judgement a designer should have to make by hand.

Founding on springs, not on pins
--------------------------------
A base slab on rigid supports attracts corner moments no real soil could
deliver, and the answer is sensitive to exactly where the pins are put. A bed
of vertical springs derived from the modulus of subgrade reaction is the
least-effort model that behaves like soil: it lets the slab settle, redistributes
the bearing pressure, and removes the arbitrariness. See
:class:`~austruct.analysis.frame.Restraint`.

Landing nodes on the peaks
--------------------------
A frame reports actions at nodes, so a peak between two nodes is never
reported. :meth:`BoxCulvert.refined` solves the structure, finds the point of
maximum moment inside every member by statics, and returns a culvert with nodes
pinned exactly there. Two passes is normally enough:

    culvert = BoxCulvert(...)
    culvert = culvert.refined()      # solve, find peaks, pin nodes
    results = culvert.solve()

[UNITS] mm, N, MPa. Pressures N/mm^2 (1 MPa = 1000 kPa).

[VECTOR] The lateral earth pressure coefficients and the dispersal slope are
         UNVERIFIED. So is the treatment of the haunch, which is not modelled
         at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

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
from .perimeter import PerimeterLayout, Wall

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.DEMAND,
    ),
    description="Box culvert analysed as a closed plane frame on soil springs",
    envelope_summary=(
        "Single-cell rectangular box; prismatic members; no haunches; "
        "linear elastic soil springs under the base slab only"
    ),
)

DEFAULT_SUBGRADE_MODULUS = 0.03
"""Modulus of subgrade reaction, N/mm^3 (30 MPa/m = 30000 kPa/m). A middling
value for a competent granular founding material.
[VECTOR] UNVERIFIED and highly site-dependent -- this is a geotechnical input,
         not a code value, and should come from the geotechnical report."""

DEFAULT_K0 = 0.5
"""At-rest lateral earth pressure coefficient. A buried culvert wall cannot
move enough to mobilise active pressure, so at-rest is the right family.
[VECTOR] UNVERIFIED -- and K0 depends on the backfill's friction angle and its
         compaction, so a single default is a placeholder for a real value."""


def inside_tension_sign(wall: Wall) -> float:
    """Sign that converts a member's diagram moment to "inside face in tension".

    Why this is needed
    ------------------
    The frame solver works in each member's own local axes, and the four sides
    of a box do not agree on which way is "up". The left and right walls both
    run bottom-to-top, so their local +y' axes both point in global -x -- which
    is OUTWARD on the left wall and INWARD on the right. An identical physical
    bending therefore reads +23.8 on one wall and -23.8 on the other.

    That is correct mechanics and useless reporting. A designer reading a
    culvert schedule wants one question answered at every location: which face
    is in tension, so which face gets the steel. So a single convention is
    imposed here -- **positive means tension on the inside face of the cell** --
    and the two sides whose local axes point the other way are flipped.

    Working, for the record. Taking the diagram convention as positive =
    tension on the local -y' side:

    ==========  ==========  ===================  ======
    Wall        local +y'   -y' side is ...      sign
    ==========  ==========  ===================  ======
    ``TOP``     up          soffit -- inside     +1
    ``BOTTOM``  up          underside -- outside -1
    ``LEFT``    -x, outward inside               +1
    ``RIGHT``   -x, inward  outside              -1
    ==========  ==========  ===================  ======

    The test that this is right is symmetry: a symmetric culvert must report
    identical moments on its two walls, and identical values at its four
    corners.
    """
    return {Wall.TOP: 1.0, Wall.BOTTOM: -1.0, Wall.LEFT: 1.0, Wall.RIGHT: -1.0}[wall]


@dataclass(frozen=True)
class CulvertGeometry:
    """Dimensions of a single-cell rectangular box culvert.

    All dimensions are CLEAR internal dimensions plus member thicknesses; the
    frame is built on member centrelines, which is the standard idealisation
    and is what the derived ``span`` and ``height`` properties give.

    Attributes
    ----------
    clear_span:
        Internal horizontal clear distance between the walls (mm).
    clear_height:
        Internal vertical clear distance between the slabs (mm).
    top_thickness, base_thickness, wall_thickness:
        Member thicknesses (mm).
    transverse_width:
        Width of culvert analysed, out of plane (mm). The frame is a plane
        model, so every load and stiffness is per this width. Defaults to
        1000 mm -- the usual "analyse a metre strip".
    """

    clear_span: float
    clear_height: float
    top_thickness: float
    base_thickness: float
    wall_thickness: float
    transverse_width: float = 1000.0

    def __post_init__(self) -> None:
        for name in (
            "clear_span",
            "clear_height",
            "top_thickness",
            "base_thickness",
            "wall_thickness",
            "transverse_width",
        ):
            if getattr(self, name) <= 0:
                raise ModelError(f"{name} must be positive, got {getattr(self, name)}")

    @property
    def span(self) -> float:
        """Centreline span, wall centre to wall centre (mm)."""
        return self.clear_span + self.wall_thickness

    @property
    def height(self) -> float:
        """Centreline height, slab centre to slab centre (mm)."""
        return self.clear_height + 0.5 * (self.top_thickness + self.base_thickness)

    def thickness_of(self, wall: Wall) -> float:
        return {
            Wall.TOP: self.top_thickness,
            Wall.BOTTOM: self.base_thickness,
            Wall.LEFT: self.wall_thickness,
            Wall.RIGHT: self.wall_thickness,
        }[wall]

    def length_of(self, wall: Wall) -> float:
        """Centreline length of one side (mm)."""
        return self.span if wall in (Wall.TOP, Wall.BOTTOM) else self.height

    def describe(self) -> list[str]:
        return [
            f"Clear opening   = {self.clear_span:.0f} x {self.clear_height:.0f} mm",
            f"Centreline      = {self.span:.0f} x {self.height:.0f} mm",
            f"Top slab        = {self.top_thickness:.0f} mm",
            f"Base slab       = {self.base_thickness:.0f} mm",
            f"Walls           = {self.wall_thickness:.0f} mm",
            f"Analysed width  = {self.transverse_width:.0f} mm",
        ]


@dataclass(frozen=True)
class CulvertLoading:
    """What acts on the culvert.

    Attributes
    ----------
    fill_depth:
        Depth of fill over the top slab (mm).
    fill_density:
        Backfill density (kg/m^3).
    concrete_density:
        Member self-weight density (kg/m^3). Zero to omit self weight.
    k0:
        Lateral earth pressure coefficient.
    surcharge:
        Uniform vertical surcharge at the surface (N/mm^2). Traffic dispersed
        through fill is added separately -- see
        :meth:`BoxCulvert.with_dispersed_wheel`.
    water_table_depth:
        Depth to the water table below the surface (mm), or ``None`` for dry.
        Currently records the intent only; buoyancy and water pressure are NOT
        applied.
    """

    fill_depth: float = 0.0
    fill_density: float = 2000.0
    concrete_density: float = 2400.0
    k0: float = DEFAULT_K0
    surcharge: float = 0.0
    water_table_depth: float | None = None

    def __post_init__(self) -> None:
        if self.fill_depth < 0:
            raise ModelError(f"Fill depth must be non-negative, got {self.fill_depth}")
        if self.k0 <= 0:
            raise ModelError(f"k0 must be positive, got {self.k0}")

    def vertical_pressure_at(self, depth_below_surface: float) -> float:
        """Total vertical stress at a depth below the fill surface (N/mm^2)."""
        return self.fill_density * g * 1e-9 * max(0.0, depth_below_surface) + self.surcharge

    def lateral_pressure_at(self, depth_below_surface: float) -> float:
        """Lateral earth pressure at a depth below the fill surface (N/mm^2)."""
        return self.k0 * self.vertical_pressure_at(depth_below_surface)


@dataclass(frozen=True)
class BoxCulvert:
    """A single-cell box culvert, ready to analyse.

    Attributes
    ----------
    geometry:
        Dimensions.
    loading:
        Fill, surcharge and lateral pressure.
    E:
        Concrete elastic modulus (MPa).
    layout:
        Where the nodes go. See :mod:`austruct.structures.perimeter`.
    subgrade_modulus:
        Modulus of subgrade reaction under the base slab (N/mm^3). Zero pins
        the base slab corners instead, which is NOT recommended -- see the
        module docstring.
    extra_top_loads:
        Additional uniform pressures on the top slab (N/mm^2), e.g. a wheel
        load already dispersed through the fill.
    name:
        Label for reports.
    """

    geometry: CulvertGeometry
    loading: CulvertLoading = field(default_factory=CulvertLoading)
    E: float = 32800.0  # noqa: N815
    layout: PerimeterLayout = field(default_factory=PerimeterLayout)
    subgrade_modulus: float = DEFAULT_SUBGRADE_MODULUS
    extra_top_loads: tuple[tuple[float, float, float], ...] = ()
    """``((start_mm, end_mm, pressure), ...)`` along the top slab."""
    name: str = ""

    # -- node and member construction ----------------------------------------

    def _wall_nodes(self) -> dict[Wall, list[tuple[float, float]]]:
        """Node coordinates along each wall, in that wall's own direction."""
        geom = self.geometry
        b, h = geom.span, geom.height

        ends = {
            Wall.BOTTOM: ((0.0, 0.0), (b, 0.0)),
            Wall.TOP: ((0.0, h), (b, h)),
            Wall.LEFT: ((0.0, 0.0), (0.0, h)),
            Wall.RIGHT: ((b, 0.0), (b, h)),
        }

        out: dict[Wall, list[tuple[float, float]]] = {}
        for wall, ((x0, y0), (x1, y1)) in ends.items():
            out[wall] = [
                (x0 + f * (x1 - x0), y0 + f * (y1 - y0))
                for f in self.layout.fractions(wall)
            ]
        return out

    def build(self) -> tuple[Frame, dict[Wall, list[int]]]:
        """Assemble the frame, and a map from each wall to its member indices.

        Returns
        -------
        tuple
            ``(frame, member_index_by_wall)``.
        """
        geom = self.geometry
        wall_nodes = self._wall_nodes()

        # One shared node dictionary keyed on rounded coordinates, so the four
        # corners are shared between the walls that meet there rather than
        # duplicated -- a duplicated corner would leave the box open.
        nodes: list[Node] = []
        index: dict[tuple[float, float], int] = {}

        def node_index(x: float, y: float, label: str = "") -> int:
            key = (round(x, 6), round(y, 6))
            if key not in index:
                index[key] = len(nodes)
                nodes.append(Node(x, y, label))
            return index[key]

        corner_labels = {
            (0.0, 0.0): "SW",
            (geom.span, 0.0): "SE",
            (0.0, geom.height): "NW",
            (geom.span, geom.height): "NE",
        }
        for (x, y), label in corner_labels.items():
            node_index(x, y, label)

        members: list[Member] = []
        by_wall: dict[Wall, list[int]] = {}

        for wall in Wall:
            t = geom.thickness_of(wall)
            # Per unit transverse width: I = w.t^3/12, A = w.t
            ei = self.E * geom.transverse_width * t**3 / 12.0
            ea = self.E * geom.transverse_width * t

            coords = wall_nodes[wall]
            indices = [node_index(x, y) for x, y in coords]
            by_wall[wall] = []
            for k, (a, b) in enumerate(zip(indices, indices[1:])):
                members.append(
                    Member(a, b, EA=ea, EI=ei, name=f"{wall.value}-{k + 1}")
                )
                by_wall[wall].append(len(members) - 1)

        restraints = self._restraints(nodes, by_wall, members)
        member_loads = self._member_loads(nodes, members, by_wall)

        frame = Frame(
            nodes=tuple(nodes),
            members=tuple(members),
            restraints=tuple(restraints),
            member_loads=tuple(member_loads),
            name=self.name or "Box culvert",
        )
        return frame, by_wall

    def _restraints(
        self,
        nodes: list[Node],
        by_wall: dict[Wall, list[int]],
        members: list[Member],
    ) -> list[Restraint]:
        """Soil springs under the base slab, plus the minimum lateral restraint.

        Each base node gets a vertical spring of stiffness ``k_s x tributary
        length x transverse width``. The tributary length is half of each
        adjacent element, so a refined mesh redistributes the same total soil
        stiffness rather than adding more of it -- which it would if every node
        got the same spring.
        """
        restraints: list[Restraint] = []

        base_members = [members[i] for i in by_wall[Wall.BOTTOM]]
        tributary: dict[int, float] = {}
        for m in base_members:
            length = nodes[m.start].distance_to(nodes[m.end])
            tributary[m.start] = tributary.get(m.start, 0.0) + length / 2.0
            tributary[m.end] = tributary.get(m.end, 0.0) + length / 2.0

        if self.subgrade_modulus > 0:
            for node_idx, trib in sorted(tributary.items()):
                k = self.subgrade_modulus * trib * self.geometry.transverse_width
                restraints.append(Restraint(node=node_idx, ky=k))
            # Springs restrain vertical movement and rotation of the box, but
            # nothing resists horizontal sway: the lateral pressures on the two
            # walls balance only if they are equal, and they are not once a
            # surcharge acts on one side. One horizontal restraint at a base
            # corner removes the sway mode without adding vertical stiffness.
            sw = min(tributary)
            restraints.append(Restraint(node=sw, ux=True))
        else:
            corners = [min(tributary), max(tributary)]
            restraints.append(Restraint(node=corners[0], ux=True, uy=True))
            restraints.append(Restraint(node=corners[1], uy=True))

        return restraints

    def _member_loads(
        self,
        nodes: list[Node],
        members: list[Member],
        by_wall: dict[Wall, list[int]],
    ) -> list[MemberLoad]:
        """Earth pressure, self weight and any extra top-slab pressure.

        Distributed pressures vary with depth, but a frame member carries a
        UNIFORM load. Each element therefore takes the pressure evaluated at
        its own mid-height.

        [ASSUMPTION] Stepped approximation to a linearly varying pressure. The
                     error is second order in element length and vanishes as
                     the wall is subdivided, so it is controlled by
                     ``layout.divisions_for(Wall.LEFT)`` rather than being a
                     fixed inaccuracy. With the default 8 divisions it is well
                     under a percent.
        """
        geom = self.geometry
        loads: list[MemberLoad] = []
        top_y = geom.height
        self_weight_pressure = self.loading.concrete_density * g * 1e-9

        for wall in Wall:
            t = geom.thickness_of(wall)
            for idx in by_wall[wall]:
                m = members[idx]
                start, end = nodes[m.start], nodes[m.end]
                mid_y = 0.5 * (start.y + end.y)
                w_perp = 0.0
                w_axial = 0.0

                if wall is Wall.TOP:
                    # Vertical earth pressure plus self weight, both downward.
                    # Local +y' for a left-to-right member points UP, so a
                    # downward load is negative.
                    pressure = self.loading.vertical_pressure_at(self.loading.fill_depth)
                    w_perp -= (pressure + self_weight_pressure * t) * geom.transverse_width
                    for lo, hi, extra in self.extra_top_loads:
                        mid_x = 0.5 * (start.x + end.x)
                        if lo <= mid_x <= hi:
                            w_perp -= extra * geom.transverse_width

                elif wall is Wall.BOTTOM:
                    # Self weight only; the soil reaction comes from the springs.
                    w_perp -= self_weight_pressure * t * geom.transverse_width

                else:
                    # Lateral earth pressure, pushing INWARD on the wall.
                    depth = self.loading.fill_depth + (top_y - mid_y)
                    pressure = self.loading.lateral_pressure_at(depth)
                    # Both walls run bottom -> top, so local +y' points LEFT on
                    # the left wall (-x) and... no: for a member running +y,
                    # local x' = (0, 1) and y' = (-1, 0), i.e. local +y' points
                    # in -x for BOTH walls. Inward is +x on the left wall and
                    # -x on the right, so the sign differs between them.
                    inward = -1.0 if wall is Wall.LEFT else +1.0
                    w_perp += inward * pressure * geom.transverse_width
                    # Self weight of a vertical member acts along it, downward,
                    # which is -x' for a bottom-to-top member.
                    w_axial -= self_weight_pressure * t * geom.transverse_width

                if w_perp or w_axial:
                    loads.append(MemberLoad(member=idx, w_perp=w_perp, w_axial=w_axial))

        return loads

    # -- analysis -------------------------------------------------------------

    def solve(self) -> CulvertResults:
        """Analyse the culvert."""
        frame, by_wall = self.build()
        return CulvertResults(
            culvert=self,
            frame=frame,
            frame_results=solve_frame(frame),
            members_by_wall=by_wall,
        )

    # -- directed adjustment --------------------------------------------------

    def with_layout(self, layout: PerimeterLayout) -> BoxCulvert:
        """Copy using a different node layout."""
        return replace(self, layout=layout)

    def with_node_at(self, wall: Wall, fraction: float, reason: str = "") -> BoxCulvert:
        """Copy with a node pinned at ``fraction`` along ``wall``."""
        return replace(self, layout=self.layout.with_node_at(wall, fraction, reason))

    def with_node_at_distance(
        self, wall: Wall, distance: float, reason: str = ""
    ) -> BoxCulvert:
        """Copy with a node pinned ``distance`` mm along ``wall``.

        The wall length is taken from this culvert's geometry, so the caller
        states the dimension in the terms the drawing uses.
        """
        return replace(
            self,
            layout=self.layout.with_node_at_distance(
                wall, distance, self.geometry.length_of(wall), reason
            ),
        )

    def with_dispersed_wheel(
        self, start: float, end: float, pressure: float
    ) -> BoxCulvert:
        """Copy with an extra uniform pressure over part of the top slab.

        Intended for a wheel load already spread through the fill by
        :class:`~austruct.loads.dispersal.FillDispersal` -- this class does not
        do the dispersal itself, so the two remain independently checkable.
        """
        if end <= start:
            raise ModelError(f"Patch end ({end}) must exceed start ({start})")
        return replace(
            self, extra_top_loads=self.extra_top_loads + ((start, end, pressure),)
        )

    def refined(self, passes: int = 1, keep_existing: bool = False) -> BoxCulvert:
        """Solve, find the peak moment inside every member, pin a node there.

        This is the operation that makes the reported actions the real ones. A
        frame reports moments at nodes; a peak between two nodes is invisible.
        After one pass every interior peak has a node on it, so the second
        solve reports the true maximum rather than a sample near it.

        Parameters
        ----------
        passes:
            How many solve-and-refine cycles to run. One is normally enough --
            the peak moves only slightly once a node lands near it.
        keep_existing:
            Keep nodes pinned BEFORE this call -- explicit placements the
            engineer asked for, or peaks from an earlier refinement of a
            different load case. Defaults to False, which starts from the
            uniform divisions alone.

        Returns
        -------
        BoxCulvert
            A copy whose layout has nodes at the interior moment peaks.

        Notes
        -----
        The pinned nodes are cleared ONCE, before the first pass, and every
        pass afterwards adds to what the previous one found.

        Clearing them on each pass instead -- which is what this method did
        first -- makes refinement actively destructive. Once a node lands on a
        peak, the zero-shear point of the members either side of it sits at
        their ends rather than inside them, so the next pass finds no interior
        peak there, discards the node that was correctly placed, and returns a
        mesh no better than the one it started with. On a three-division
        culvert that showed up as a second pass reporting 13.1 kN.m where the
        first pass had correctly found 17.2.
        """
        if passes < 1:
            raise ModelError(f"passes must be at least 1, got {passes}")

        culvert = self
        if not keep_existing:
            culvert = replace(culvert, layout=culvert.layout.without_pinned())

        for _ in range(passes):
            results = culvert.solve()
            layout = culvert.layout
            for wall, peaks in results.interior_peaks().items():
                for fraction, _moment in peaks:
                    layout = layout.with_node_at(wall, fraction, "peak moment")
            culvert = replace(culvert, layout=layout)

        return culvert

    def describe(self) -> list[str]:
        lines = [f"Box culvert: {self.name or 'unnamed'}", ""]
        lines.extend(self.geometry.describe())
        lines.append(f"Fill depth      = {self.loading.fill_depth:.0f} mm")
        lines.append(f"k0              = {self.loading.k0:.2f}")
        lines.append(
            f"Subgrade k_s    = {self.subgrade_modulus * 1000:.1f} MPa/m"
            if self.subgrade_modulus
            else "Base slab       = pinned (NOT recommended)"
        )
        lines.append("")
        lines.extend(self.layout.describe())
        return lines


@dataclass
class CulvertResults:
    """Analysis results, organised the way a culvert is designed."""

    culvert: BoxCulvert
    frame: Frame
    frame_results: object  # FrameResults
    members_by_wall: dict[Wall, list[int]]

    def wall_moments(self, wall: Wall) -> list[tuple[float, float]]:
        """``[(fraction_along_wall, moment), ...]`` at every node on ``wall``.

        Moments in N.mm, positive meaning **tension on the INSIDE face** of the
        cell. See :func:`inside_tension_sign` for why a single convention has
        to be imposed rather than reported raw.
        """
        out: list[tuple[float, float]] = []
        length = self.culvert.geometry.length_of(wall)
        sign = inside_tension_sign(wall)
        start_node = None

        for idx in self.members_by_wall[wall]:
            forces = self.frame_results.member_forces[idx]  # type: ignore[attr-defined]
            member = self.frame.members[idx]
            if start_node is None:
                start_node = member.start
            a = self.frame.nodes[member.start]
            b = self.frame.nodes[member.end]
            origin = self.frame.nodes[start_node]
            out.append((origin.distance_to(a) / length, sign * -forces.M_start))
            out.append((origin.distance_to(b) / length, sign * forces.M_end))

        # Deduplicate shared nodes, keeping the larger magnitude so a genuine
        # step at a joint is not averaged away. Fractions are rounded to 6 dp
        # to do it, which on a metre-scale wall is a micron -- but a caller
        # looking a node up by an exactly computed fraction must compare with a
        # tolerance rather than for equality.
        merged: dict[float, float] = {}
        for frac, moment in out:
            key = round(frac, 6)
            if key not in merged or abs(moment) > abs(merged[key]):
                merged[key] = moment
        return sorted(merged.items())

    def interior_peaks(self) -> dict[Wall, list[tuple[float, float]]]:
        """Where the moment peaks INSIDE each member, as wall fractions.

        For a member with a uniform perpendicular load the moment is
        ``M(s) = -M_start + V_start.s + w.s^2/2``, so the extremum is the point
        of zero shear at ``s = -V_start / w``. That is exact, not sampled, and
        it is why the refinement needs only one pass to land on a peak.

        Members with no distributed load have a linear moment diagram whose
        extremes are at the nodes already, so they contribute nothing.
        """
        peaks: dict[Wall, list[tuple[float, float]]] = {}
        loads = {load.member: load for load in self.frame.member_loads}

        for wall, indices in self.members_by_wall.items():
            length = self.culvert.geometry.length_of(wall)
            sign = inside_tension_sign(wall)
            found: list[tuple[float, float]] = []
            start_node = self.frame.members[indices[0]].start if indices else None

            for idx in indices:
                load = loads.get(idx)
                if load is None or load.w_perp == 0.0:
                    continue
                forces = self.frame_results.member_forces[idx]  # type: ignore[attr-defined]
                s = -forces.V_start / load.w_perp
                if not 0.0 < s < forces.length:
                    continue
                member = self.frame.members[idx]
                origin = self.frame.nodes[start_node]  # type: ignore[index]
                offset = origin.distance_to(self.frame.nodes[member.start]) + s
                found.append(
                    (offset / length, sign * forces.moment_at(s, load.w_perp))
                )
            if found:
                peaks[wall] = found
        return peaks

    def peak_moment(self, wall: Wall) -> tuple[float, float]:
        """``(fraction, moment)`` of the largest moment magnitude on ``wall``.

        Considers both the nodal values and the interior peaks, so it is right
        whether or not the mesh has been refined.
        """
        candidates = list(self.wall_moments(wall))
        candidates.extend(self.interior_peaks().get(wall, []))
        return max(candidates, key=lambda pair: abs(pair[1]))

    @property
    def max_moment(self) -> float:
        return self.frame_results.max_moment  # type: ignore[attr-defined]

    def bearing_pressure(self) -> list[tuple[float, float]]:
        """``[(x, pressure), ...]`` under the base slab (mm, N/mm^2).

        Read from the spring reactions divided by their tributary area, which
        is what the springs mean. A bearing pressure that goes negative means
        the base slab is lifting off, which linear springs cannot represent --
        see the note in :meth:`describe`.
        """
        geom = self.culvert.geometry
        out: list[tuple[float, float]] = []
        base_members = [self.frame.members[i] for i in self.members_by_wall[Wall.BOTTOM]]

        tributary: dict[int, float] = {}
        for m in base_members:
            length = self.frame.nodes[m.start].distance_to(self.frame.nodes[m.end])
            tributary[m.start] = tributary.get(m.start, 0.0) + length / 2.0
            tributary[m.end] = tributary.get(m.end, 0.0) + length / 2.0

        for node_idx, trib in sorted(tributary.items()):
            reaction = self.frame_results.reactions.get(node_idx)  # type: ignore[attr-defined]
            if reaction is None:
                continue
            area = trib * geom.transverse_width
            out.append((self.frame.nodes[node_idx].x, reaction[1] / area))
        return out

    def describe(self) -> list[str]:
        lines = [f"Culvert results: {self.culvert.name or 'unnamed'}", ""]
        lines.append(f"{'wall':<12}{'peak M':>12}{'at':>10}")
        lines.append(f"{'':<12}{'kN.m':>12}{'fraction':>10}")
        lines.append("-" * 34)
        for wall in Wall:
            frac, moment = self.peak_moment(wall)
            lines.append(f"{wall.label:<12}{moment / 1e6:>12.1f}{frac:>10.3f}")

        pressures = [p for _, p in self.bearing_pressure()]
        if pressures:
            lines.append("")
            lines.append(
                f"Bearing pressure {min(pressures) * 1e3:.1f} to "
                f"{max(pressures) * 1e3:.1f} kPa"
            )
            if min(pressures) < 0:
                lines.append(
                    "  WARNING: negative bearing pressure means the base slab "
                    "is lifting off. Linear springs cannot model that -- the "
                    "result is not valid without a no-tension analysis."
                )

        residual = self.frame_results.check_equilibrium()  # type: ignore[attr-defined]
        lines.append("")
        lines.append(
            f"Equilibrium residual: Fx {residual[0]:.3e} N, "
            f"Fy {residual[1]:.3e} N, Mz {residual[2]:.3e} N.mm"
        )
        return lines

    def _repr_markdown_(self) -> str:
        rows = ["| Wall | Peak M (kN.m) | at fraction |", "|---|---|---|"]
        for wall in Wall:
            frac, moment = self.peak_moment(wall)
            rows.append(f"| {wall.label} | {moment / 1e6:.1f} | {frac:.3f} |")
        return (
            f"**{self.culvert.name or 'Box culvert'}** — "
            f"{len(self.frame.nodes)} nodes, {len(self.frame.members)} members\n\n"
            + "\n".join(rows)
        )
