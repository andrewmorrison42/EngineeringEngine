"""Direct stiffness solver for plane frames.

What this adds over ``solver.py``
---------------------------------
The beam solver has two degrees of freedom per node -- vertical translation and
rotation -- which is everything a beam needs and nothing a frame does. A frame
member is oriented arbitrarily in the plane, carries axial force as well as
bending, and its axial stiffness couples into the global equations as soon as
the member is not horizontal.

So this module works in three degrees of freedom per node::

    [u, v, theta]    horizontal, vertical, rotation

and each member carries a 6x6 stiffness matrix rotated from its local axes into
global ones. A horizontal member with no axial load reduces exactly to the beam
element, which is the sanity check the tests lean on.

What it deliberately does not do
--------------------------------
No second-order (P-Delta) effects, no geometric or material non-linearity, no
member releases beyond fully rigid connections, no shear deformation. Those are
the reasons this is a *frame* solver and not a general FE package -- see the
README on where an external library becomes the better trade.

Sign conventions
----------------
Global axes: x to the right, y UPWARD, rotations counter-clockwise positive.
This differs from the beam module, which works downward-positive at its public
surface. The difference is deliberate and confined: a frame has no single
"down" once members are vertical, so the natural mathematical frame is used
throughout and the conversion happens only where a result is presented.

Member local axes: x' along the member from its start node to its end node,
y' perpendicular, 90 degrees counter-clockwise from x'.

[UNITS] mm, N, MPa. EA in N, EI in N.mm^2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from ..core.exceptions import ModelError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.DEMAND,
    ),
    description="Plane frame direct stiffness solver, 3 DOF per node",
    envelope_summary=(
        "Linear elastic, small displacement, prismatic members; "
        "no P-Delta, no shear deformation, rigid joints"
    ),
)

DOF_PER_NODE = 3


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    """A joint in the frame.

    Attributes
    ----------
    x, y:
        Position in global coordinates (mm). ``y`` is measured UPWARD.
    name:
        Optional label. Appears in results, so a meaningful name -- ``"NW
        corner"`` -- is worth the keystrokes.
    """

    x: float
    y: float
    name: str = ""

    def distance_to(self, other: Node) -> float:
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True)
class Restraint:
    """What a support prevents at a node.

    Each degree of freedom is either free, fully fixed, or elastically
    restrained by a spring.

    Attributes
    ----------
    node:
        Index of the restrained node.
    ux, uy, rz:
        ``True`` to fix that degree of freedom rigidly.
    kx, ky, krz:
        Spring stiffnesses (N/mm, N/mm, N.mm/rad). Ignored where the
        corresponding rigid flag is set -- a rigid restraint is infinitely
        stiffer than any spring, so combining them is meaningless rather than
        additive.

    Notes
    -----
    Springs are how a buried structure sits on soil. A culvert base slab on
    rigid supports attracts moments no real founding soil could deliver; a bed
    of vertical springs is the least-effort model that behaves sensibly.
    """

    node: int
    ux: bool = False
    uy: bool = False
    rz: bool = False
    kx: float = 0.0
    ky: float = 0.0
    krz: float = 0.0

    def __post_init__(self) -> None:
        for name, k in (("kx", self.kx), ("ky", self.ky), ("krz", self.krz)):
            if k < 0:
                raise ModelError(f"Spring stiffness {name} must be non-negative, got {k}")

    @property
    def is_free(self) -> bool:
        return not any(
            (self.ux, self.uy, self.rz, self.kx > 0, self.ky > 0, self.krz > 0)
        )


@dataclass(frozen=True)
class Member:
    """A prismatic frame member between two nodes.

    Attributes
    ----------
    start, end:
        Node indices. The member's local x' axis runs start -> end, which fixes
        the sign of every local result.
    EA:
        Axial rigidity (N).
    EI:
        Flexural rigidity (N.mm^2).
    name:
        Optional label.
    """

    start: int
    end: int
    EA: float  # noqa: N815
    EI: float  # noqa: N815
    name: str = ""

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise ModelError(f"Member {self.name or '?'} starts and ends at node {self.start}")
        if self.EA <= 0 or self.EI <= 0:
            raise ModelError(f"Member {self.name or '?'} needs positive EA and EI")


@dataclass(frozen=True)
class MemberLoad:
    """A uniformly distributed load on a member, in its LOCAL axes.

    Attributes
    ----------
    member:
        Index of the loaded member.
    w_perp:
        Intensity perpendicular to the member (N/mm), positive in the local
        +y' direction (90 degrees counter-clockwise from start -> end).
    w_axial:
        Intensity along the member (N/mm), positive from start towards end.

    Notes
    -----
    Local rather than global because the loads a frame actually carries are
    mostly face loads: earth pressure normal to a wall, self weight normal to a
    slab. Expressing those globally means resolving them by hand for every
    member orientation, which is exactly the arithmetic worth automating away.
    Use :func:`gravity_load` for a genuinely global load.
    """

    member: int
    w_perp: float = 0.0
    w_axial: float = 0.0


@dataclass(frozen=True)
class NodeLoad:
    """A concentrated action at a node, in GLOBAL axes.

    ``fx`` and ``fy`` in N, ``mz`` in N.mm counter-clockwise positive.
    """

    node: int
    fx: float = 0.0
    fy: float = 0.0
    mz: float = 0.0


@dataclass(frozen=True)
class Frame:
    """A plane frame: nodes, members, restraints and loads.

    Frozen, like :class:`~austruct.analysis.beam.Beam`, so that a model which
    has been reported on cannot change underneath the report. Use
    :meth:`with_loads` to build variants.
    """

    nodes: tuple[Node, ...]
    members: tuple[Member, ...]
    restraints: tuple[Restraint, ...] = ()
    member_loads: tuple[MemberLoad, ...] = ()
    node_loads: tuple[NodeLoad, ...] = ()
    name: str = ""

    def __post_init__(self) -> None:
        n = len(self.nodes)
        if n < 2:
            raise ModelError("A frame needs at least two nodes")
        for m in self.members:
            for idx in (m.start, m.end):
                if not 0 <= idx < n:
                    raise ModelError(
                        f"Member {m.name or '?'} refers to node {idx}, which does "
                        f"not exist (the frame has {n} nodes, 0 to {n - 1})"
                    )
        for r in self.restraints:
            if not 0 <= r.node < n:
                raise ModelError(f"Restraint refers to node {r.node}, which does not exist")
        for load in self.member_loads:
            if not 0 <= load.member < len(self.members):
                raise ModelError(
                    f"Member load refers to member {load.member}, which does not exist"
                )
        for load in self.node_loads:
            if not 0 <= load.node < n:
                raise ModelError(f"Node load refers to node {load.node}, which does not exist")

    @property
    def n_dof(self) -> int:
        return len(self.nodes) * DOF_PER_NODE

    def member_length(self, index: int) -> float:
        m = self.members[index]
        return self.nodes[m.start].distance_to(self.nodes[m.end])

    def with_loads(
        self,
        member_loads: tuple[MemberLoad, ...] = (),
        node_loads: tuple[NodeLoad, ...] = (),
    ) -> Frame:
        """Copy carrying a different load set. Geometry and restraints kept."""
        return replace(self, member_loads=member_loads, node_loads=node_loads)

    def add_loads(
        self,
        member_loads: tuple[MemberLoad, ...] = (),
        node_loads: tuple[NodeLoad, ...] = (),
    ) -> Frame:
        """Copy with loads appended to those already present."""
        return replace(
            self,
            member_loads=self.member_loads + member_loads,
            node_loads=self.node_loads + node_loads,
        )

    def describe(self) -> list[str]:
        lines = [
            f"Frame      = {self.name or 'unnamed'}",
            f"Nodes      = {len(self.nodes)}",
            f"Members    = {len(self.members)}",
            f"Restraints = {len(self.restraints)}",
            f"DOF        = {self.n_dof}",
        ]
        return lines


def gravity_load(frame: Frame, member: int, w: float) -> MemberLoad:
    """A globally downward UDL of intensity ``w`` (N/mm) on one member.

    Resolves the global vertical load into the member's local axes, which is
    the arithmetic that otherwise has to be done by hand for every member
    orientation. A vertical member gets a purely axial load; a horizontal one
    gets a purely perpendicular load; anything between gets both.
    """
    m = frame.members[member]
    start, end = frame.nodes[m.start], frame.nodes[m.end]
    length = start.distance_to(end)
    if length == 0:
        raise ModelError(f"Member {member} has zero length")

    c = (end.x - start.x) / length
    s = (end.y - start.y) / length

    # Global (0, -w) resolved into local axes: x' = (c, s), y' = (-s, c).
    return MemberLoad(member=member, w_perp=-w * c, w_axial=-w * s)


# ---------------------------------------------------------------------------
# Element matrices
# ---------------------------------------------------------------------------


def local_stiffness(EA: float, EI: float, L: float) -> np.ndarray:  # noqa: N803
    """6x6 frame element stiffness in LOCAL axes.

    DOF order ``[u1, v1, th1, u2, v2, th2]``. The axial and flexural parts are
    uncoupled in local axes -- the coupling appears only after rotation into
    global axes, which is precisely why a frame needs this and a beam does not.
    """
    k = np.zeros((6, 6))
    ax = EA / L
    k[0, 0] = k[3, 3] = ax
    k[0, 3] = k[3, 0] = -ax

    f = EI / L**3
    k[1, 1] = k[4, 4] = 12.0 * f
    k[1, 4] = k[4, 1] = -12.0 * f
    k[1, 2] = k[2, 1] = 6.0 * L * f
    k[1, 5] = k[5, 1] = 6.0 * L * f
    k[2, 4] = k[4, 2] = -6.0 * L * f
    k[4, 5] = k[5, 4] = -6.0 * L * f
    k[2, 2] = k[5, 5] = 4.0 * L**2 * f
    k[2, 5] = k[5, 2] = 2.0 * L**2 * f
    return k


def transformation(c: float, s: float) -> np.ndarray:
    """6x6 rotation from global to local axes for direction cosines ``(c, s)``."""
    t = np.zeros((6, 6))
    block = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    t[:3, :3] = block
    t[3:, 3:] = block
    return t


def fixed_end_forces(w_perp: float, w_axial: float, L: float) -> np.ndarray:  # noqa: N803
    """Fixed-end actions for a local UDL, as a LOCAL force vector.

    Returned as the forces the member exerts ON the nodes -- i.e. already
    negated from the classic fixed-end moments, ready to be added to the load
    vector.
    """
    return np.array(
        [
            w_axial * L / 2.0,
            w_perp * L / 2.0,
            w_perp * L**2 / 12.0,
            w_axial * L / 2.0,
            w_perp * L / 2.0,
            -w_perp * L**2 / 12.0,
        ]
    )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class MemberForces:
    """End actions on one member, in its LOCAL axes.

    Attributes
    ----------
    N_start, V_start, M_start:
        Axial, shear and moment at the start node.
    N_end, V_end, M_end:
        The same at the end node.

    Sign convention: these are the actions the NODES exert on the member, which
    is the convention that makes ``M_start`` and ``M_end`` read directly as the
    hogging moments a designer wants at a joint.
    """

    member: int
    name: str
    length: float
    N_start: float
    V_start: float
    M_start: float
    N_end: float
    V_end: float
    M_end: float

    @property
    def axial(self) -> float:
        """Axial force, positive TENSION, taken at the start."""
        return -self.N_start

    def moment_at(self, s: float, w_perp: float = 0.0) -> float:
        """Bending moment at distance ``s`` along the member (N.mm).

        Built by statics from the start-node actions plus any distributed load,
        so it is exact at any position and independent of mesh density -- the
        same division of labour the beam solver uses.
        """
        return -self.M_start + self.V_start * s + w_perp * s * s / 2.0

    def describe(self) -> list[str]:
        return [
            f"{self.name or f'member {self.member}'}:",
            f"  N = {self.N_start / 1e3:8.1f} / {self.N_end / 1e3:8.1f} kN",
            f"  V = {self.V_start / 1e3:8.1f} / {self.V_end / 1e3:8.1f} kN",
            f"  M = {self.M_start / 1e6:8.1f} / {self.M_end / 1e6:8.1f} kN.m",
        ]


@dataclass
class FrameResults:
    """Displacements, reactions and member end actions for one load set."""

    frame: Frame
    displacements: np.ndarray
    """Flat global DOF vector, ``[u0, v0, th0, u1, ...]`` (mm, mm, rad)."""
    reactions: dict[int, tuple[float, float, float]]
    """``{node: (Fx, Fy, Mz)}`` at every restrained node (N, N, N.mm)."""
    member_forces: list[MemberForces]

    def node_displacement(self, node: int) -> tuple[float, float, float]:
        """``(u, v, theta)`` at a node."""
        base = node * DOF_PER_NODE
        d = self.displacements
        return float(d[base]), float(d[base + 1]), float(d[base + 2])

    @property
    def max_moment(self) -> float:
        """Largest member end moment anywhere in the frame (N.mm, unsigned)."""
        return max(
            (max(abs(f.M_start), abs(f.M_end)) for f in self.member_forces),
            default=0.0,
        )

    @property
    def max_axial(self) -> float:
        return max(
            (max(abs(f.N_start), abs(f.N_end)) for f in self.member_forces),
            default=0.0,
        )

    def check_equilibrium(self, tol: float = 1e-6) -> tuple[float, float, float]:
        """Residual of global equilibrium: ``(sum Fx, sum Fy, sum Mz)``.

        Applied loads plus reactions, which must sum to zero. This is the
        check worth running on any frame result before believing it -- an
        under-restrained or badly connected model can still produce a solution
        that looks reasonable.
        """
        fx = fy = mz = 0.0

        for load in self.frame.node_loads:
            node = self.frame.nodes[load.node]
            fx += load.fx
            fy += load.fy
            mz += load.mz + load.fy * node.x - load.fx * node.y

        for load in self.frame.member_loads:
            m = self.frame.members[load.member]
            start, end = self.frame.nodes[m.start], self.frame.nodes[m.end]
            length = start.distance_to(end)
            c = (end.x - start.x) / length
            s = (end.y - start.y) / length
            # Local -> global: x' = (c, s), y' = (-s, c)
            gx = (load.w_axial * c - load.w_perp * s) * length
            gy = (load.w_axial * s + load.w_perp * c) * length
            mid_x = 0.5 * (start.x + end.x)
            mid_y = 0.5 * (start.y + end.y)
            fx += gx
            fy += gy
            mz += gy * mid_x - gx * mid_y

        for node_index, (rx, ry, rm) in self.reactions.items():
            node = self.frame.nodes[node_index]
            fx += rx
            fy += ry
            mz += rm + ry * node.x - rx * node.y

        return fx, fy, mz

    def describe(self) -> list[str]:
        lines = [f"Frame results: {self.frame.name or 'unnamed'}", ""]
        lines.append("Reactions (global, kN and kN.m):")
        for node_index in sorted(self.reactions):
            rx, ry, rm = self.reactions[node_index]
            label = self.frame.nodes[node_index].name or f"node {node_index}"
            lines.append(
                f"  {label:<16} Fx {rx / 1e3:8.2f}  Fy {ry / 1e3:8.2f}  "
                f"Mz {rm / 1e6:8.2f}"
            )
        lines.append("")
        lines.append("Member end actions (local, kN and kN.m):")
        for f in self.member_forces:
            lines.extend(f.describe())
        return lines


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------


def solve_frame(frame: Frame) -> FrameResults:
    """Solve a plane frame by the direct stiffness method.

    Parameters
    ----------
    frame:
        The model.

    Returns
    -------
    FrameResults

    Raises
    ------
    ModelError
        If the frame is a mechanism -- insufficiently restrained to have a
        unique solution. The message names the likely cause rather than
        reporting a singular matrix, because "singular" is not actionable.
    """
    n_dof = frame.n_dof
    K = np.zeros((n_dof, n_dof))
    F = np.zeros(n_dof)

    # -- assemble -----------------------------------------------------------
    member_geometry: list[tuple[float, float, float]] = []  # (L, c, s)
    for i, member in enumerate(frame.members):
        start, end = frame.nodes[member.start], frame.nodes[member.end]
        L = start.distance_to(end)
        if L == 0:
            raise ModelError(f"Member {member.name or i} has zero length")
        c = (end.x - start.x) / L
        s = (end.y - start.y) / L
        member_geometry.append((L, c, s))

        T = transformation(c, s)
        k_global = T.T @ local_stiffness(member.EA, member.EI, L) @ T

        dofs = _member_dofs(member)
        K[np.ix_(dofs, dofs)] += k_global

    # -- loads ---------------------------------------------------------------
    for load in frame.member_loads:
        member = frame.members[load.member]
        L, c, s = member_geometry[load.member]
        local_f = fixed_end_forces(load.w_perp, load.w_axial, L)
        T = transformation(c, s)
        F[_member_dofs(member)] += T.T @ local_f

    for load in frame.node_loads:
        base = load.node * DOF_PER_NODE
        F[base] += load.fx
        F[base + 1] += load.fy
        F[base + 2] += load.mz

    # -- restraints ----------------------------------------------------------
    # Springs add stiffness on the diagonal; rigid restraints remove the DOF.
    #
    # Restraints are merged per node first. A node may legitimately be named by
    # more than one Restraint -- a spring bed under a slab plus a single lateral
    # restraint to remove sway is the natural way to write it -- and treating
    # them as separate entries silently loses all but the last when reactions
    # are reported back.
    merged = _merge_restraints(frame.restraints)

    fixed: list[int] = []
    for r in merged.values():
        base = r.node * DOF_PER_NODE
        for offset, rigid, spring in (
            (0, r.ux, r.kx),
            (1, r.uy, r.ky),
            (2, r.rz, r.krz),
        ):
            if rigid:
                fixed.append(base + offset)
            elif spring > 0:
                K[base + offset, base + offset] += spring

    free = np.array([i for i in range(n_dof) if i not in set(fixed)], dtype=int)
    if free.size == 0:
        raise ModelError("Every degree of freedom is restrained; there is nothing to solve")

    K_ff = K[np.ix_(free, free)]

    # Jacobi scaling before the rank test. A frame stiffness matrix mixes
    # translational terms (~EA/L) with rotational ones (~EI/L), which differ by
    # many orders of magnitude; an unscaled rank test reports a perfectly
    # well-posed frame as singular. Same trick, same reason, as the beam solver.
    diag = np.sqrt(np.abs(np.diag(K_ff)))
    diag[diag == 0] = 1.0
    scaled = K_ff / np.outer(diag, diag)

    if np.linalg.matrix_rank(scaled, tol=1e-12) < free.size:
        raise ModelError(
            "The frame is a mechanism -- it has a mode of deformation that "
            "attracts no resistance, so no unique solution exists. Usual "
            "causes: too few restraints, a node connected to only one member "
            "with a free rotation, or a member missing from a closed loop. "
            "Check the restraints first."
        )

    displacements = np.zeros(n_dof)
    displacements[free] = np.linalg.solve(K_ff, F[free])

    # -- reactions -----------------------------------------------------------
    # R = K.d - F over the whole system, read at restrained DOFs. Spring
    # reactions are read as -k.d, since the spring stiffness was folded into K
    # and so does not appear as an external unknown.
    residual = K @ displacements - F
    reactions: dict[int, tuple[float, float, float]] = {}
    for r in merged.values():
        base = r.node * DOF_PER_NODE
        values = []
        for offset, rigid, spring in (
            (0, r.ux, r.kx),
            (1, r.uy, r.ky),
            (2, r.rz, r.krz),
        ):
            if rigid:
                values.append(float(residual[base + offset]))
            elif spring > 0:
                values.append(float(-spring * displacements[base + offset]))
            else:
                values.append(0.0)
        reactions[r.node] = (values[0], values[1], values[2])

    # -- member end actions --------------------------------------------------
    forces: list[MemberForces] = []
    for i, member in enumerate(frame.members):
        L, c, s = member_geometry[i]
        T = transformation(c, s)
        d_local = T @ displacements[_member_dofs(member)]
        f_local = local_stiffness(member.EA, member.EI, L) @ d_local

        applied = next(
            (load for load in frame.member_loads if load.member == i), None
        )
        if applied is not None:
            f_local -= fixed_end_forces(applied.w_perp, applied.w_axial, L)

        forces.append(
            MemberForces(
                member=i,
                name=member.name,
                length=L,
                N_start=float(f_local[0]),
                V_start=float(f_local[1]),
                M_start=float(f_local[2]),
                N_end=float(f_local[3]),
                V_end=float(f_local[4]),
                M_end=float(f_local[5]),
            )
        )

    return FrameResults(
        frame=frame,
        displacements=displacements,
        reactions=reactions,
        member_forces=forces,
    )


def _merge_restraints(restraints: tuple[Restraint, ...]) -> dict[int, Restraint]:
    """Combine multiple Restraint entries naming the same node into one.

    Rigid flags OR together and spring stiffnesses ADD, which is what a user
    writing two entries for one node means. A rigid flag beats any spring on
    the same degree of freedom -- an infinitely stiff restraint in parallel
    with a finite one is still infinitely stiff.
    """
    out: dict[int, Restraint] = {}
    for r in restraints:
        existing = out.get(r.node)
        if existing is None:
            out[r.node] = r
            continue
        out[r.node] = Restraint(
            node=r.node,
            ux=existing.ux or r.ux,
            uy=existing.uy or r.uy,
            rz=existing.rz or r.rz,
            kx=existing.kx + r.kx,
            ky=existing.ky + r.ky,
            krz=existing.krz + r.krz,
        )
    return out


def _member_dofs(member: Member) -> list[int]:
    """Global DOF indices for a member, in local order."""
    a = member.start * DOF_PER_NODE
    b = member.end * DOF_PER_NODE
    return [a, a + 1, a + 2, b, b + 1, b + 2]
