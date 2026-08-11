"""Direct stiffness solver for Euler-Bernoulli beams.

What this does
--------------
Two-node beam elements, two degrees of freedom per node (vertical translation
and rotation). Loads become consistent nodal loads by integrating the Hermite
shape functions, which means any load -- uniform, partial, linearly varying,
concentrated force, concentrated moment -- is handled by one code path rather
than by a per-load-type formula.

Division of labour with statics
-------------------------------
The solver produces **reactions and displacements**. The shear and bending
moment diagrams are then built by **statics** from those reactions, in
:func:`_statics_diagrams`, not read off the element end forces.

That is deliberate. Statics gives exact diagram values at any position for any
load type with no dependence on mesh density, and it is independently checkable
by hand -- which matters when the numbers go on a drawing. The finite element
solve is used only for the quantities statics cannot give on an indeterminate
member: the reactions and the deflected shape.

Internal sign convention
------------------------
The solver works in an upward-positive frame (v up, rotations counter-clockwise,
moments counter-clockwise) because that is the frame every textbook stiffness
matrix is written in. The conversion to and from the engineer-facing
downward-positive convention happens ONLY in this module, at the points marked
``[UNITS]``/``[ASSUMPTION]``. See ``loading.py`` for the external convention.

[UNITS] mm, N, MPa. EI in N.mm^2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..core.exceptions import ModelError
from .loading import Load
from .results import BeamResults, Reaction

if TYPE_CHECKING:  # pragma: no cover -- avoids a circular import at runtime
    from .beam import Beam

# Gauss-Legendre points and weights on [0, 1], 4 point.
# Exact for polynomials to degree 7. The integrand is a cubic shape function
# times a load intensity, so this is exact for load intensities up to degree 4
# -- comfortably beyond the linearly varying loads the package supports.
_GAUSS_XI = np.array(
    [
        0.5 - 0.5 * 0.8611363115940526,
        0.5 - 0.5 * 0.3399810435848563,
        0.5 + 0.5 * 0.3399810435848563,
        0.5 + 0.5 * 0.8611363115940526,
    ]
)
_GAUSS_W = np.array(
    [
        0.5 * 0.3478548451374538,
        0.5 * 0.6521451548625461,
        0.5 * 0.6521451548625461,
        0.5 * 0.3478548451374538,
    ]
)

# Offset used to sample either side of a discontinuity in the diagrams.
_EPS = 1e-6


def _shape_functions(xi: float, L: float) -> np.ndarray:  # noqa: N803
    """Hermite shape functions at local coordinate ``xi`` in [0, 1].

    Order matches the element DOF vector ``[v1, theta1, v2, theta2]``.
    """
    return np.array(
        [
            1.0 - 3.0 * xi**2 + 2.0 * xi**3,
            L * (xi - 2.0 * xi**2 + xi**3),
            3.0 * xi**2 - 2.0 * xi**3,
            L * (-(xi**2) + xi**3),
        ]
    )


def _shape_derivatives(xi: float, L: float) -> np.ndarray:  # noqa: N803
    """d(N)/dx at local coordinate ``xi``. Used for concentrated moments and
    for recovering rotations."""
    return np.array(
        [
            (-6.0 * xi + 6.0 * xi**2) / L,
            1.0 - 4.0 * xi + 3.0 * xi**2,
            (6.0 * xi - 6.0 * xi**2) / L,
            -2.0 * xi + 3.0 * xi**2,
        ]
    )


def _element_stiffness(EI: float, L: float) -> np.ndarray:  # noqa: N803
    """4x4 Euler-Bernoulli element stiffness matrix.

    [BASIS] Standard direct stiffness formulation, DOFs [v1, theta1, v2, theta2]
            with v upward positive and theta counter-clockwise positive.
    """
    k = EI / L**3
    return k * np.array(
        [
            [12.0, 6.0 * L, -12.0, 6.0 * L],
            [6.0 * L, 4.0 * L**2, -6.0 * L, 2.0 * L**2],
            [-12.0, -6.0 * L, 12.0, -6.0 * L],
            [6.0 * L, 2.0 * L**2, -6.0 * L, 4.0 * L**2],
        ]
    )


def _build_mesh(beam: Beam, min_elements: int) -> np.ndarray:
    """Node positions: supports, load discontinuities, then uniform infill.

    Nodes are forced at every support and at every load boundary so that no
    element spans a discontinuity in load intensity -- which would make the
    Gauss integration of the consistent load vector inexact.
    """
    critical = {0.0, beam.length}
    critical.update(s.position for s in beam.supports)
    for load in beam.loads:
        for p in load.mesh_points():
            if 0.0 <= p <= beam.length:
                critical.add(float(p))
    # Positions the caller has asked for regardless of this load set -- see
    # Beam.extra_mesh_points. This is what lets an envelope across load
    # combinations share one exact grid.
    for p in beam.extra_mesh_points:
        if 0.0 <= p <= beam.length:
            critical.add(float(p))

    # [CHECK] Merge near-coincident nodes before meshing.
    #
    #         Positions arriving from a moving-load sweep are computed by
    #         floating-point arithmetic, so a point that should be 4000.0 may
    #         arrive as 3999.9999999999995. Deduplicating by exact value keeps
    #         both, producing an element ~5e-13 mm long whose stiffness is
    #         ~1e38 -- the assembled matrix then loses rank and the solve
    #         reports the beam as an unstable mechanism. Merging on a tolerance
    #         is the fix; rounding is not, because two genuinely distinct
    #         points can straddle a rounding boundary.
    tol = max(1e-6, 1e-9 * beam.length)
    nodes: list[float] = []
    for value in sorted(critical):
        if not nodes or value - nodes[-1] > tol:
            nodes.append(value)
    # The member end must survive the merge even if a load sits just inside it.
    if beam.length - nodes[-1] > 0:
        nodes[-1] = beam.length

    # Infill each gap so that no element is longer than the target, giving a
    # smooth deflected shape and accurate nodal displacements.
    target = beam.length / max(min_elements, 1)
    filled: list[float] = []
    for a, b in zip(nodes, nodes[1:]):
        filled.append(a)
        gap = b - a
        n_sub = max(1, int(np.ceil(gap / target)))
        for i in range(1, n_sub):
            filled.append(a + gap * i / n_sub)
    filled.append(nodes[-1])

    return np.array(filled)


def _assign_point_actions_to_elements(
    loads: list[Load], nodes: np.ndarray
) -> dict[int, list[tuple[str, float, float]]]:
    """Map each concentrated action to exactly one element.

    A point load sitting exactly on a node belongs to the element to its right,
    except at the final node where it belongs to the element to its left. Doing
    this once, up front, is clearer than scattering the tie-breaking logic
    through the integration loop -- and double-counting a point load is a
    failure mode that produces plausible-looking wrong answers.
    """
    assignment: dict[int, list[tuple[str, float, float]]] = {}
    n_elem = len(nodes) - 1

    def element_for(pos: float) -> int:
        idx = int(np.searchsorted(nodes, pos - _EPS, side="right") - 1)
        return min(max(idx, 0), n_elem - 1)

    for load in loads:
        for pos, mag in load.point_forces():
            assignment.setdefault(element_for(pos), []).append(("F", pos, mag))
        for pos, mag in load.point_moments():
            assignment.setdefault(element_for(pos), []).append(("M", pos, mag))
    return assignment


def _distributed_load_vector(loads: list[Load], x_start: float, L: float) -> np.ndarray:  # noqa: N803
    """Consistent nodal loads from DISTRIBUTED intensity only."""
    f = np.zeros(4)
    for load in loads:
        for xi, wt in zip(_GAUSS_XI, _GAUSS_W):
            x = x_start + xi * L
            w_down = load.intensity(x)
            if w_down != 0.0:
                f += _shape_functions(xi, L) * (-w_down) * wt * L
    return f


def solve(
    beam: Beam, min_elements: int = 200, refine_peaks: bool = True
) -> BeamResults:
    """Analyse a beam and return its diagrams, reactions and deflections.

    Parameters
    ----------
    beam:
        The beam model.
    min_elements:
        Approximate number of elements over the whole member. Nodal
        displacements from a consistent-load formulation are exact at the
        nodes, so this controls the smoothness of the plotted deflected shape
        and the resolution of the extrema search, not the accuracy of the
        reactions.
    refine_peaks:
        Add sample points at the zero-shear crossings, where the bending moment
        is stationary, so the reported peak is exact rather than read from the
        nearest sample.

        Must be FALSE when the result will be enveloped against others: the
        crossings differ from case to case, so refining would give each case a
        different sample grid and the envelope could no longer be taken
        element-wise. The envelope machinery passes False for that reason and
        relies on ``min_elements`` for its resolution instead.

    Returns
    -------
    BeamResults

    Raises
    ------
    ModelError
        If the beam is unstable -- insufficient restraint to prevent rigid body
        motion -- or otherwise ill-posed.
    """
    nodes = _build_mesh(beam, min_elements)
    n_nodes = len(nodes)
    n_dof = 2 * n_nodes
    n_elem = n_nodes - 1

    if n_elem < 1:
        raise ModelError("Beam mesh has no elements; check the member length")

    K = np.zeros((n_dof, n_dof))
    F = np.zeros(n_dof)

    point_actions = _assign_point_actions_to_elements(beam.loads, nodes)

    # -- assembly -------------------------------------------------------------
    for e in range(n_elem):
        x1, x2 = nodes[e], nodes[e + 1]
        L = x2 - x1
        EI = beam.EI_at(0.5 * (x1 + x2))
        if EI <= 0:
            raise ModelError(f"Non-positive EI ({EI}) at x = {0.5 * (x1 + x2):.1f} mm")

        ke = _element_stiffness(EI, L)
        fe = _distributed_load_vector(beam.loads, x1, L)

        # Concentrated actions belonging to this element. See
        # _assign_point_actions_to_elements for the tie-breaking rule.
        for kind, pos, mag in point_actions.get(e, []):
            xi = min(max((pos - x1) / L, 0.0), 1.0)
            if kind == "F":
                # [ASSUMPTION] downward positive external -> upward positive internal
                fe += _shape_functions(xi, L) * (-mag)
            else:
                # [ASSUMPTION] sagging-increasing external -> counter-clockwise internal
                fe += _shape_derivatives(xi, L) * (-mag)

        dofs = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
        K[np.ix_(dofs, dofs)] += ke
        F[dofs] += fe

    # -- boundary conditions --------------------------------------------------
    fixed_dofs: list[int] = []
    for support in beam.supports:
        node = int(np.argmin(np.abs(nodes - support.position)))
        if abs(nodes[node] - support.position) > 1e-6:
            raise ModelError(
                f"Support at x = {support.position} mm did not land on a mesh node; "
                "this is an internal error in mesh generation"
            )
        if support.restrains_vertical:
            fixed_dofs.append(2 * node)
        if support.restrains_rotation:
            fixed_dofs.append(2 * node + 1)

    fixed = sorted(set(fixed_dofs))
    free = [d for d in range(n_dof) if d not in set(fixed)]

    if not fixed:
        raise ModelError(
            "Beam has no restraints. Add at least two vertical supports, or one "
            "fixed support."
        )

    # -- solve ----------------------------------------------------------------
    K_ff = K[np.ix_(free, free)]
    F_f = F[free]

    # [ASSUMPTION] The system is Jacobi-scaled before both the stability check
    #              and the solve.
    #
    # A beam stiffness matrix mixes degrees of freedom with different physical
    # dimensions: translational terms go as 12EI/L^3, rotational ones as 4EI/L.
    # For a fine mesh of a stiff member those differ by many orders of
    # magnitude -- with EI = 1e15 N.mm^2 and 50 mm elements, by about 1e4 per
    # element.
    #
    # That matters because np.linalg.matrix_rank sets its zero-tolerance from
    # the LARGEST singular value. On such a matrix, genuine non-zero singular
    # values fall below that tolerance and a perfectly stable beam is reported
    # as a mechanism. Scaling each row and column by 1/sqrt(diagonal) puts
    # every diagonal at 1.0, which removes the dimensional mismatch and makes
    # the rank test mean what it says. Scaling is a similarity transform, so it
    # cannot turn a singular matrix into a non-singular one -- a real mechanism
    # is still caught.
    diag = np.diag(K_ff).copy()
    if np.any(diag <= 0.0):
        raise ModelError(
            "Beam is unstable -- a degree of freedom has no stiffness at all. "
            "Check that every span is supported and that EI is positive."
        )
    scale = 1.0 / np.sqrt(diag)
    K_scaled = K_ff * scale[:, None] * scale[None, :]

    # [CHECK] A singular reduced stiffness matrix means a rigid body mechanism:
    #         a beam on one roller, or a span with no support at all. Report it
    #         as a model error rather than letting numpy return nonsense.
    #
    # The tolerance is explicit. On a Jacobi-scaled matrix every diagonal is
    # 1.0, so a healthy system's smallest singular value stays well above
    # 1e-12 even for an awkward mesh, while a genuine rigid-body mode gives a
    # singular value at machine zero (~1e-16). Leaving numpy to pick the
    # tolerance from the largest singular value is what produced false
    # "unstable" reports on fine meshes of stiff members.
    if np.linalg.matrix_rank(K_scaled, tol=1e-12) < len(free):
        raise ModelError(
            "Beam is unstable -- the restraints do not prevent rigid body motion. "
            "Check that there are at least two vertical supports (or one fixed "
            "support), and that every span is supported."
        )

    d = np.zeros(n_dof)
    try:
        # Solve the scaled system and unscale: K.d = F becomes
        # (S K S)(S^-1 d) = S F with S = diag(scale).
        d[free] = scale * np.linalg.solve(K_scaled, scale * F_f)
    except np.linalg.LinAlgError as exc:  # pragma: no cover -- rank check catches this
        raise ModelError(f"Stiffness solve failed: {exc}") from exc

    # -- reactions ------------------------------------------------------------
    # R = K.d - F evaluated at the restrained DOFs.
    residual = K @ d - F

    reactions: list[Reaction] = []
    for support in beam.supports:
        node = int(np.argmin(np.abs(nodes - support.position)))
        force_up = residual[2 * node] if support.restrains_vertical else 0.0
        moment_ccw = residual[2 * node + 1] if support.restrains_rotation else 0.0
        reactions.append(
            Reaction(
                position=float(support.position),
                force=float(force_up),
                # [ASSUMPTION] Reported in the same convention as AppliedMoment:
                #              positive increases sagging to the right. That is
                #              the negative of the counter-clockwise internal value.
                moment=float(-moment_ccw),
            )
        )

    # -- diagrams by statics --------------------------------------------------
    xs = _diagram_positions(beam, nodes)
    shear, moment = _statics_diagrams(beam, reactions, xs)

    # [CHECK] Refine at the zero-shear crossings.
    #
    # The peak bending moment occurs where the shear passes through zero, and
    # under a distributed load that point is generally NOT a load boundary or a
    # mesh node -- so nothing in the sampling above puts a point there. The peak
    # is then read from the nearest sample and understated by w.delta^2/2. On a
    # 6 m span with a 250 mm patch load that is a 0.03% error, which is small
    # but is a systematic bias, always low, and it would need a much finer mesh
    # to remove any other way.
    #
    # Locating the crossings costs one extra statics pass and no extra solve,
    # because the shear diagram already exists.
    crossings = _zero_shear_crossings(xs, shear) if refine_peaks else []
    if crossings:
        xs = np.array(sorted(set(xs.tolist()) | set(crossings)))
        shear, moment = _statics_diagrams(beam, reactions, xs)

    # -- deflections by interpolation of the nodal solution --------------------
    deflection, rotation = _interpolate_displacements(nodes, d, xs)

    results = BeamResults(
        x=xs,
        shear=shear,
        moment=moment,
        deflection=deflection,
        rotation=rotation,
        reactions=reactions,
        length=beam.length,
        EI=beam.EI_at(beam.length / 2.0),
        beam_name=beam.name,
    )

    # [CHECK] Vertical equilibrium. A failure here is a solver bug, not a user
    #         error, so it is reported loudly rather than silently tolerated.
    applied = sum(load.total() for load in beam.loads)
    err = results.equilibrium_error(applied)
    if err > 1e-6:
        results.messages.append(
            f"WARNING: vertical equilibrium error {err:.2e} -- sum of reactions "
            f"{results.total_reaction:.3f} N vs applied {applied:.3f} N. "
            "This indicates a solver problem; do not use these results."
        )

    return results


def _diagram_positions(beam: Beam, nodes: np.ndarray) -> np.ndarray:
    """Sample positions for the diagrams.

    Every mesh node, plus a point either side of each discontinuity so that a
    shear jump at a point load or support is captured at full magnitude on both
    sides rather than being averaged away.
    """
    positions = set(float(x) for x in nodes)

    discontinuities = {s.position for s in beam.supports}
    for load in beam.loads:
        discontinuities.update(p for p, _ in load.point_forces())
        discontinuities.update(p for p, _ in load.point_moments())
        discontinuities.update(load.mesh_points())

    # Caller-requested positions are treated as discontinuities too. Without
    # this, two load combinations sharing a node set would still be sampled at
    # different positions -- a combination that omits a point load would not
    # get the pair of points either side of it -- and could not be enveloped
    # element-wise. See Beam.extra_mesh_points.
    discontinuities.update(beam.extra_mesh_points)

    # Bracket every discontinuity, including one sitting on a member end. A
    # support at x = 0 or x = L is a discontinuity like any other: the shear
    # immediately inboard of an end support is the largest on the member and is
    # exactly where the shear check is made, so failing to sample it reports a
    # peak from the next node in and understates V*.
    for x in discontinuities:
        for p in (x - _EPS, x + _EPS):
            if 0.0 <= p <= beam.length:
                positions.add(float(p))

    return np.array(sorted(p for p in positions if -_EPS <= p <= beam.length + _EPS))


def _zero_shear_crossings(xs: np.ndarray, shear: np.ndarray) -> list[float]:
    """Positions where the shear diagram crosses zero.

    These are where the bending moment is stationary, so sampling them makes
    the reported peak moment exact rather than merely close.

    Only genuine crossings between adjacent samples are returned -- a step
    THROUGH zero at a point load is a discontinuity, not a stationary point,
    and the moment there is already sampled by the discontinuity bracketing.
    """
    crossings: list[float] = []
    for i in range(len(xs) - 1):
        v1, v2 = shear[i], shear[i + 1]
        if v1 == 0.0 or v2 == 0.0 or (v1 > 0) == (v2 > 0):
            continue
        gap = xs[i + 1] - xs[i]
        # Skip the pair straddling a discontinuity: they are 2.EPS apart and
        # the sign change there is a jump, not a crossing.
        if gap <= 4 * _EPS:
            continue
        crossings.append(float(xs[i] + gap * v1 / (v1 - v2)))
    return crossings


def _statics_diagrams(
    beam: Beam, reactions: list[Reaction], xs: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Shear and bending moment at each position, by statics from the left.

    ``V(x) = sum(R_up, left) - sum(F_down, left)``

    ``M(x) = sum(R_up * (x - x_R), left) + sum(M_R, left) - sum(F_down * (x - x_F), left)``

    Both in the external convention: shear positive where the resultant to the
    left acts upward, moment positive sagging.
    """
    shear = np.zeros_like(xs)
    moment = np.zeros_like(xs)

    for i, x in enumerate(xs):
        v = 0.0
        m = 0.0

        for r in reactions:
            if r.position <= x + _EPS / 2:
                v += r.force
                m += r.force * (x - r.position) + r.moment

        for load in beam.loads:
            f_down, m_reducing = load.resultant_left_of(float(x))
            v -= f_down
            m -= m_reducing

        shear[i] = v
        moment[i] = m

    return shear, moment


def _interpolate_displacements(
    nodes: np.ndarray, d: np.ndarray, xs: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Deflection and rotation at each sample position.

    Hermite interpolation within each element from the nodal solution.

    [ASSUMPTION] The interpolation captures the homogeneous solution exactly
                 and the particular solution under distributed load only
                 approximately. Nodal values are exact; between nodes the error
                 falls as the fourth power of element length, which at the
                 default mesh density is negligible.

    Returns the deflection in the EXTERNAL convention -- downward positive --
    so the sign is flipped here, once.
    """
    deflection = np.zeros_like(xs)
    rotation = np.zeros_like(xs)
    n_elem = len(nodes) - 1

    for i, x in enumerate(xs):
        e = int(np.searchsorted(nodes, x, side="right") - 1)
        e = min(max(e, 0), n_elem - 1)
        x1, x2 = nodes[e], nodes[e + 1]
        L = x2 - x1
        xi = min(max((x - x1) / L, 0.0), 1.0)

        de = d[[2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]]
        # [ASSUMPTION] Internal frame is upward positive; negate once, here.
        deflection[i] = -float(_shape_functions(xi, L) @ de)
        rotation[i] = -float(_shape_derivatives(xi, L) @ de)

    return deflection, rotation
