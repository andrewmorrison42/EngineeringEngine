"""Tests for the plane frame solver and the box culvert.

The frame solver is checked against closed-form beam results, because a
horizontal frame member with no axial load must reduce exactly to the beam
element -- if it does not, the transformation or the element matrix is wrong.

The culvert is checked against two things a hand calculation gives: the
free-bending identity (hogging at the ends plus sagging at midspan equals
wL^2/8 for a member with fixed ends) and symmetry.
"""

from __future__ import annotations

import pytest

from austruct.analysis.frame import (
    Frame,
    Member,
    MemberLoad,
    Node,
    NodeLoad,
    Restraint,
    gravity_load,
    solve_frame,
)
from austruct.core.exceptions import ModelError
from austruct.core.units import m
from austruct.structures import (
    BoxCulvert,
    CulvertGeometry,
    CulvertLoading,
    PerimeterLayout,
    Wall,
    inside_tension_sign,
)

E = 200000.0
I = 1e8  # noqa: E741
A = 1e4
EI = E * I
EA = E * A
L = 6.0 * m


# ---------------------------------------------------------------------------
# The frame element must reduce to the beam element
# ---------------------------------------------------------------------------


def test_simply_supported_beam_under_udl():
    """M = wL^2/8, delta = 5wL^4/384EI, R = wL/2. All three, exactly."""
    w = 10.0
    frame = Frame(
        nodes=(Node(0, 0, "A"), Node(L / 2, 0, "mid"), Node(L, 0, "B")),
        members=(Member(0, 1, EA, EI), Member(1, 2, EA, EI)),
        restraints=(Restraint(0, ux=True, uy=True), Restraint(2, uy=True)),
        member_loads=(MemberLoad(0, w_perp=-w), MemberLoad(1, w_perp=-w)),
    )
    r = solve_frame(frame)

    assert abs(r.member_forces[0].M_end) == pytest.approx(w * L**2 / 8)
    assert r.node_displacement(1)[1] == pytest.approx(-5 * w * L**4 / (384 * EI))
    assert r.reactions[0][1] == pytest.approx(w * L / 2)


def test_cantilever_with_a_tip_load():
    """M = PL at the root, delta = PL^3/3EI at the tip."""
    P = 5000.0
    frame = Frame(
        nodes=(Node(0, 0), Node(L, 0)),
        members=(Member(0, 1, EA, EI),),
        restraints=(Restraint(0, ux=True, uy=True, rz=True),),
        node_loads=(NodeLoad(1, fy=-P),),
    )
    r = solve_frame(frame)
    assert abs(r.member_forces[0].M_start) == pytest.approx(P * L)
    assert r.node_displacement(1)[1] == pytest.approx(-P * L**3 / (3 * EI))


def test_axial_shortening_of_a_column():
    """delta = PL/EA -- the degree of freedom a beam element does not have."""
    P = 5000.0
    frame = Frame(
        nodes=(Node(0, 0), Node(0, L)),
        members=(Member(0, 1, EA, EI),),
        restraints=(
            Restraint(0, ux=True, uy=True, rz=True),
            Restraint(1, ux=True, rz=True),
        ),
        node_loads=(NodeLoad(1, fy=-P),),
    )
    r = solve_frame(frame)
    assert r.node_displacement(1)[1] == pytest.approx(-P * L / EA)
    assert r.member_forces[0].axial == pytest.approx(-P)


def test_a_rotated_member_gives_the_same_answer_as_a_horizontal_one():
    """A cantilever is a cantilever whichever way it points. This is the test
    that catches a wrong transformation matrix."""
    P = 5000.0
    horizontal = Frame(
        nodes=(Node(0, 0), Node(L, 0)),
        members=(Member(0, 1, EA, EI),),
        restraints=(Restraint(0, ux=True, uy=True, rz=True),),
        node_loads=(NodeLoad(1, fy=-P),),
    )
    vertical = Frame(
        nodes=(Node(0, 0), Node(0, L)),
        members=(Member(0, 1, EA, EI),),
        restraints=(Restraint(0, ux=True, uy=True, rz=True),),
        node_loads=(NodeLoad(1, fx=P),),
    )
    a = solve_frame(horizontal)
    b = solve_frame(vertical)
    assert abs(a.member_forces[0].M_start) == pytest.approx(abs(b.member_forces[0].M_start))


def test_equilibrium_residual_is_zero_for_every_model():
    w = 10.0
    frame = Frame(
        nodes=(Node(0, 0), Node(L, 0), Node(L, L), Node(0, L)),
        members=(
            Member(0, 1, EA, EI),
            Member(1, 2, EA, EI),
            Member(2, 3, EA, EI),
            Member(3, 0, EA, EI),
        ),
        restraints=(Restraint(0, ux=True, uy=True), Restraint(1, uy=True)),
        member_loads=(MemberLoad(2, w_perp=w),),
    )
    fx, fy, mz = solve_frame(frame).check_equilibrium()
    scale = w * L
    assert abs(fx) < 1e-6 * scale
    assert abs(fy) < 1e-6 * scale
    assert abs(mz) < 1e-6 * scale * L


def test_gravity_load_resolves_into_local_axes():
    """A horizontal member takes it all perpendicular; a vertical one all
    axial. Getting this wrong silently rotates the self weight."""
    frame = Frame(
        nodes=(Node(0, 0), Node(L, 0), Node(0, L)),
        members=(Member(0, 1, EA, EI), Member(0, 2, EA, EI)),
        restraints=(Restraint(0, ux=True, uy=True, rz=True),),
    )
    horizontal = gravity_load(frame, 0, 10.0)
    vertical = gravity_load(frame, 1, 10.0)

    assert horizontal.w_perp == pytest.approx(-10.0)
    assert horizontal.w_axial == pytest.approx(0.0)
    assert vertical.w_perp == pytest.approx(0.0, abs=1e-12)
    assert vertical.w_axial == pytest.approx(-10.0)


# ---------------------------------------------------------------------------
# Springs and restraints
# ---------------------------------------------------------------------------


def test_a_spring_carries_load_in_proportion_to_its_stiffness():
    P = 5000.0
    k = 100.0
    frame = Frame(
        nodes=(Node(0, 0), Node(L, 0)),
        members=(Member(0, 1, EA, EI),),
        restraints=(Restraint(0, ux=True, uy=True, rz=True), Restraint(1, ky=k)),
        node_loads=(NodeLoad(1, fy=-P),),
    )
    r = solve_frame(frame)
    v = r.node_displacement(1)[1]
    assert r.reactions[1][1] == pytest.approx(-k * v)


def test_two_restraints_on_one_node_are_merged_not_overwritten():
    """Regression. A spring bed plus a single lateral restraint is the natural
    way to write a culvert base, and treating the two entries separately lost
    the spring reaction entirely -- which showed up as a 10 kN equilibrium
    residual and a zero bearing pressure at one corner."""
    P = 5000.0
    frame = Frame(
        nodes=(Node(0, 0), Node(L, 0)),
        members=(Member(0, 1, EA, EI),),
        restraints=(
            Restraint(0, ky=1e6),
            Restraint(0, ux=True),  # same node, second entry
            Restraint(1, ky=1e6),
        ),
        node_loads=(NodeLoad(0, fy=-P), NodeLoad(1, fy=-P)),
    )
    r = solve_frame(frame)

    assert r.reactions[0][1] != 0.0, "the spring reaction must survive the merge"
    fx, fy, mz = r.check_equilibrium()
    assert abs(fy) < 1e-6 * P


def test_a_mechanism_is_reported_as_such():
    frame = Frame(
        nodes=(Node(0, 0), Node(L, 0)),
        members=(Member(0, 1, EA, EI),),
        restraints=(Restraint(0, ux=True, uy=True),),
    )
    with pytest.raises(ModelError, match="mechanism"):
        solve_frame(frame)


def test_a_bad_node_reference_names_the_problem():
    with pytest.raises(ModelError, match="does not exist"):
        Frame(nodes=(Node(0, 0), Node(L, 0)), members=(Member(0, 5, EA, EI),))


def test_a_negative_spring_refuses():
    with pytest.raises(ModelError, match="non-negative"):
        Restraint(0, ky=-1.0)


# ---------------------------------------------------------------------------
# The perimeter layout
# ---------------------------------------------------------------------------


def test_uniform_divisions_give_evenly_spaced_nodes():
    layout = PerimeterLayout(default_divisions=4)
    assert layout.fractions(Wall.TOP) == (0.0, 0.25, 0.5, 0.75, 1.0)


def test_a_pinned_node_is_merged_into_the_uniform_set():
    layout = PerimeterLayout(default_divisions=2).with_node_at(Wall.TOP, 0.3, "why")
    assert layout.fractions(Wall.TOP) == (0.0, 0.3, 0.5, 1.0)
    assert layout.reasons_for(Wall.TOP) == {0.3: "why"}


def test_the_corners_are_always_nodes():
    layout = PerimeterLayout(default_divisions=1).with_node_at(Wall.TOP, 0.5)
    fracs = layout.fractions(Wall.TOP)
    assert fracs[0] == 0.0
    assert fracs[-1] == 1.0


def test_near_coincident_nodes_are_merged():
    """Two nodes a hair apart make an element of vanishing length, which
    wrecks the conditioning of the stiffness matrix."""
    layout = PerimeterLayout(default_divisions=2).with_node_at(Wall.TOP, 0.5 + 1e-9)
    assert layout.fractions(Wall.TOP) == (0.0, 0.5, 1.0)


def test_a_node_just_inside_a_corner_does_not_displace_the_corner():
    layout = PerimeterLayout(default_divisions=2).with_node_at(Wall.TOP, 1e-9)
    assert layout.fractions(Wall.TOP)[0] == 0.0


def test_a_fraction_outside_the_wall_refuses():
    with pytest.raises(ModelError, match="between 0 and 1"):
        PerimeterLayout().with_node_at(Wall.TOP, 1.4)


def test_placement_by_distance_converts_to_a_fraction():
    layout = PerimeterLayout().with_node_at_distance(Wall.TOP, 750.0, 3000.0, "joint")
    assert 0.25 in layout.fractions(Wall.TOP)


def test_a_distance_off_the_end_refuses():
    with pytest.raises(ModelError, match="outside"):
        PerimeterLayout().with_node_at_distance(Wall.TOP, 5000.0, 3000.0)


def test_per_wall_divisions_override_the_default():
    layout = PerimeterLayout(default_divisions=4).with_divisions(Wall.LEFT, 10)
    assert layout.divisions_for(Wall.LEFT) == 10
    assert layout.divisions_for(Wall.TOP) == 4


def test_without_pinned_keeps_the_uniform_mesh():
    layout = PerimeterLayout(default_divisions=4).with_node_at(Wall.TOP, 0.3)
    assert layout.without_pinned().fractions(Wall.TOP) == (0.0, 0.25, 0.5, 0.75, 1.0)


# ---------------------------------------------------------------------------
# The culvert
# ---------------------------------------------------------------------------


@pytest.fixture
def geometry():
    return CulvertGeometry(
        clear_span=3000, clear_height=2400,
        top_thickness=300, base_thickness=350, wall_thickness=300,
    )


@pytest.fixture
def culvert(geometry):
    return BoxCulvert(
        geometry=geometry,
        loading=CulvertLoading(fill_depth=1000, fill_density=2000, k0=0.5),
        name="C1",
    )


def test_centreline_dimensions_add_the_thicknesses(geometry):
    assert geometry.span == 3300.0
    assert geometry.height == 2400 + 0.5 * (300 + 350)


def test_the_box_is_closed(culvert):
    """Four walls sharing four corners. A duplicated corner leaves the box
    open and every result is wrong."""
    frame, by_wall = culvert.build()
    n_per_wall = [len(by_wall[w]) for w in Wall]
    # Nodes = sum of members, because each wall shares both its end nodes.
    assert len(frame.nodes) == sum(n_per_wall)


def test_equilibrium_holds(culvert):
    r = culvert.solve()
    fx, fy, mz = r.frame_results.check_equilibrium()
    scale = abs(r.frame_results.reactions[min(r.frame_results.reactions)][1]) + 1e3
    assert abs(fx) < 1e-6 * scale
    assert abs(fy) < 1e-6 * scale


def test_a_symmetric_culvert_gives_symmetric_walls(culvert):
    """The test that the reporting sign convention is right."""
    r = culvert.solve()
    left = r.wall_moments(Wall.LEFT)
    right = r.wall_moments(Wall.RIGHT)
    for (fa, ma), (fb, mb) in zip(left, right):
        assert fa == pytest.approx(fb)
        assert ma == pytest.approx(mb, abs=1.0)


def test_the_top_slab_corners_are_equal_and_hogging(culvert):
    r = culvert.solve()
    moments = dict(r.wall_moments(Wall.TOP))
    left_corner = moments[0.0]
    right_corner = moments[1.0]
    assert left_corner == pytest.approx(right_corner, abs=1.0)
    assert left_corner < 0, "a corner hogs, so the OUTSIDE face is in tension"


def test_hogging_plus_sagging_equals_the_free_bending_moment(culvert, geometry):
    """The identity every engineer checks a fixed-ended member against:
    |M_end| + M_mid = wL^2/8, whatever the end fixity actually is."""
    r = culvert.solve()
    moments = dict(r.wall_moments(Wall.TOP))
    hog = abs(moments[0.0])
    sag = moments[0.5]

    loading = culvert.loading
    w = (
        loading.vertical_pressure_at(loading.fill_depth)
        + loading.concrete_density * 9.81e-9 * geometry.top_thickness
    ) * geometry.transverse_width
    free = w * geometry.span**2 / 8

    assert hog + sag == pytest.approx(free, rel=0.01)


def test_the_simply_supported_model_misses_the_corner_moment(culvert):
    """The reason the frame exists. A simply supported top slab reports zero
    moment at the corners, where the frame finds substantial hogging -- and
    hogging means top steel that the simpler model never asks for."""
    r = culvert.solve()
    corner = dict(r.wall_moments(Wall.TOP))[0.0]
    assert abs(corner) > 0.3 * abs(dict(r.wall_moments(Wall.TOP))[0.5])


def test_lateral_pressure_bends_the_walls(culvert):
    no_lateral = BoxCulvert(
        geometry=culvert.geometry,
        loading=CulvertLoading(fill_depth=1000, k0=1e-6),
    )
    with_lateral = culvert

    a = abs(no_lateral.solve().peak_moment(Wall.LEFT)[1])
    b = abs(with_lateral.solve().peak_moment(Wall.LEFT)[1])
    assert b > a


def test_bearing_pressure_is_positive_and_sums_to_the_weight(culvert):
    r = culvert.solve()
    pressures = r.bearing_pressure()
    assert pressures
    assert all(p > 0 for _, p in pressures), "the culvert should not be lifting off"


def test_inside_tension_sign_covers_every_wall():
    assert {inside_tension_sign(w) for w in Wall} == {1.0, -1.0}


# ---------------------------------------------------------------------------
# Directed refinement -- the point of the perimeter layout
# ---------------------------------------------------------------------------


def _converged_sagging(culvert) -> float:
    fine = culvert.with_layout(PerimeterLayout(default_divisions=200)).solve()
    return max(m for _, m in fine.wall_moments(Wall.TOP))


def test_a_coarse_mesh_understates_the_peak(culvert):
    """No node at the peak means the peak is never reported."""
    coarse = culvert.with_layout(PerimeterLayout(default_divisions=3)).solve()
    nodal = max(m for _, m in coarse.wall_moments(Wall.TOP))
    assert nodal < 0.9 * _converged_sagging(culvert)


def test_refinement_lands_a_node_on_the_peak(culvert):
    coarse = culvert.with_layout(PerimeterLayout(default_divisions=3))
    refined = coarse.refined()

    before = max(m for _, m in coarse.solve().wall_moments(Wall.TOP))
    after = max(m for _, m in refined.solve().wall_moments(Wall.TOP))
    target = _converged_sagging(culvert)

    assert after > before
    assert abs(after - target) < abs(before - target)
    assert after == pytest.approx(target, rel=0.05)


def test_refinement_is_idempotent(culvert):
    """Regression. Clearing the pinned nodes on every pass made the second
    pass discard exactly the nodes the first had correctly placed, and the
    answer fell back to the coarse one."""
    coarse = culvert.with_layout(PerimeterLayout(default_divisions=3))
    one = max(m for _, m in coarse.refined(passes=1).solve().wall_moments(Wall.TOP))
    two = max(m for _, m in coarse.refined(passes=2).solve().wall_moments(Wall.TOP))
    three = max(m for _, m in coarse.refined(passes=3).solve().wall_moments(Wall.TOP))

    assert two == pytest.approx(one, rel=1e-3)
    assert three == pytest.approx(one, rel=1e-3)


def test_refinement_records_why_each_node_is_there(culvert):
    refined = culvert.with_layout(PerimeterLayout(default_divisions=3)).refined()
    assert any(
        "peak moment" in reason
        for wall in Wall
        for reason in refined.layout.reasons_for(wall).values()
    )


def test_refinement_can_keep_a_hand_placed_node(culvert):
    directed = culvert.with_node_at(Wall.TOP, 0.22, "construction joint")
    kept = directed.refined(keep_existing=True)
    dropped = directed.refined(keep_existing=False)

    assert 0.22 in kept.layout.fractions(Wall.TOP)
    assert 0.22 not in dropped.layout.fractions(Wall.TOP)


def test_peak_moment_is_accurate_even_without_refinement(culvert):
    """peak_moment adds the interior extrema, computed by statics, so it is
    right whether or not a node happens to sit on the peak."""
    target = _converged_sagging(culvert)
    for divisions in (3, 4, 8):
        r = culvert.with_layout(PerimeterLayout(default_divisions=divisions)).solve()
        candidates = [m for _, m in r.wall_moments(Wall.TOP)]
        candidates += [m for _, m in r.interior_peaks().get(Wall.TOP, [])]
        assert max(candidates) == pytest.approx(target, rel=0.05)


def test_the_stepped_pressure_approximation_converges(culvert):
    """Wall pressure varies with depth but a member load is uniform, so each
    element takes its mid-height value. The error must vanish with refinement
    rather than sitting there as a fixed inaccuracy."""
    target = _converged_sagging(culvert)
    errors = []
    for divisions in (3, 8, 40):
        r = culvert.with_layout(PerimeterLayout(default_divisions=divisions)).solve()
        cands = [m for _, m in r.wall_moments(Wall.TOP)]
        cands += [m for _, m in r.interior_peaks().get(Wall.TOP, [])]
        errors.append(abs(max(cands) - target))
    assert errors == sorted(errors, reverse=True)


def test_a_directed_node_appears_in_the_model(culvert):
    directed = culvert.with_node_at_distance(Wall.TOP, 750.0, "construction joint")
    fractions = directed.layout.fractions(Wall.TOP)
    assert 750.0 / culvert.geometry.span == pytest.approx(
        min(fractions, key=lambda f: abs(f - 750.0 / culvert.geometry.span))
    )
    # wall_moments rounds fractions to 6 dp to deduplicate shared nodes, which
    # on a 3.3 m wall is about 3 microns -- far below anything that matters.
    r = directed.solve()
    target = 750.0 / culvert.geometry.span
    assert any(abs(f - target) < 1e-6 for f, _ in r.wall_moments(Wall.TOP))


def test_a_dispersed_wheel_increases_the_span_moment(culvert):
    plain = culvert.solve()
    loaded = culvert.with_dispersed_wheel(1200.0, 2100.0, 0.05).solve()
    assert loaded.peak_moment(Wall.TOP)[1] != plain.peak_moment(Wall.TOP)[1]
    assert max(m for _, m in loaded.wall_moments(Wall.TOP)) > max(
        m for _, m in plain.wall_moments(Wall.TOP)
    )


def test_a_reversed_wheel_patch_refuses(culvert):
    with pytest.raises(ModelError, match="must exceed"):
        culvert.with_dispersed_wheel(2000.0, 1000.0, 0.05)


def test_bad_geometry_refuses():
    with pytest.raises(ModelError, match="positive"):
        CulvertGeometry(
            clear_span=0, clear_height=2400,
            top_thickness=300, base_thickness=350, wall_thickness=300,
        )
