"""Tests for arc geometry, variable thickness and the crown (arch) culvert.

An arch is checked differently from a box. The things that must be true:

- it pushes its supports APART under vertical load;
- the thrust is compression everywhere it is working;
- the thrust is greatest at the springing and least at the apex;
- horizontal equilibrium of half the structure closes by hand.

The last one is the real test. It ties the apex thrust, the lateral earth
pressure and the foot reaction together, and it fails if any of the three is
resolved into the wrong axis.
"""

from __future__ import annotations

import math

import pytest

from austruct.core.exceptions import ModelError
from austruct.core.units import g
from austruct.structures import (
    Arc,
    BaseFixity,
    BoxCulvert,
    Constant,
    CrownCulvert,
    CrownGeometry,
    CrownLoading,
    CulvertGeometry,
    CulvertLoading,
    Haunched,
    Line,
    Part,
    PerimeterLayout,
    Segment,
    Tapered,
    Wall,
)

SPAN = 4000.0
RISE = 1200.0
LEG = 1500.0


@pytest.fixture
def geometry():
    return CrownGeometry(
        span=SPAN, rise=RISE, leg_height=LEG,
        crown_thickness=200, haunch_thickness=350, haunch_extent=0.18,
        leg_thickness_base=300, leg_thickness_top=225,
    )


@pytest.fixture
def crown(geometry):
    return CrownCulvert(
        geometry=geometry,
        loading=CrownLoading(fill_depth=600, fill_density=2000, k0=0.5),
        name="C1",
    )


# ---------------------------------------------------------------------------
# Arc geometry
# ---------------------------------------------------------------------------


def test_a_semicircle_has_radius_equal_to_the_rise():
    arc = Arc((0, 0), (4000, 0), rise=2000)
    assert arc.radius == pytest.approx(2000.0)
    assert arc.length == pytest.approx(math.pi * 2000.0)
    assert arc.half_angle == pytest.approx(math.pi / 2)


def test_radius_follows_the_span_and_rise():
    """R = (a^2 + r^2) / 2r. Half-chord 1500, rise 500 -> 2500."""
    arc = Arc((0, 0), (3000, 0), rise=500)
    assert arc.radius == pytest.approx(2500.0)


def test_the_arc_passes_through_its_own_ends_and_apex():
    arc = Arc((0, 0), (3000, 0), rise=500)
    assert arc.point_at(0.0) == pytest.approx((0.0, 0.0))
    assert arc.point_at(1.0) == pytest.approx((3000.0, 0.0))
    assert arc.point_at(0.5) == pytest.approx((1500.0, 500.0))


def test_arc_length_is_the_limit_of_the_chords():
    """The frame models the arc as chords, so the chord sum must converge on
    the arc length -- second order, which is what makes divisions the control."""
    arc = Arc((0, 0), (3000, 0), rise=500)
    errors = []
    for n in (4, 16, 64):
        pts = [arc.point_at(i / n) for i in range(n + 1)]
        poly = sum(math.dist(pts[i], pts[i + 1]) for i in range(n))
        errors.append(abs(poly - arc.length))
    assert errors == sorted(errors, reverse=True)
    # Second order: quartering the element length should cut the error ~16x.
    assert errors[0] / errors[1] > 8


def test_the_tangent_is_horizontal_at_the_apex():
    arc = Arc((0, 0), (3000, 0), rise=500)
    tx, ty = arc.tangent_at(0.5)
    assert ty == pytest.approx(0.0, abs=1e-9)
    assert tx == pytest.approx(1.0)


def test_a_zero_rise_arc_refuses_and_points_at_line():
    with pytest.raises(ModelError, match="straight line"):
        Arc((0, 0), (3000, 0), rise=0.0)


def test_a_line_reports_a_constant_tangent():
    line = Line((0, 0), (0, 1000))
    assert line.length == pytest.approx(1000.0)
    assert line.tangent_at(0.3) == pytest.approx((0.0, 1.0))


# ---------------------------------------------------------------------------
# Outward normals -- the thing that must not be backwards
# ---------------------------------------------------------------------------


def test_the_crown_normal_points_up_and_out():
    """Earth pressure acts against it. Backwards points the fill into the
    hole, which gives a symmetric and entirely wrong answer."""
    seg = Segment("crown", Arc((0, 0), (3000, 0), rise=500), Constant(200), normal_sign=+1)
    assert seg.outward_normal_at(0.5) == pytest.approx((0.0, 1.0), abs=1e-9)
    left = seg.outward_normal_at(0.0)
    right = seg.outward_normal_at(1.0)
    assert left[1] > 0 and right[1] > 0, "both ends still point upward"
    assert left[0] < 0 < right[0], "and outward, away from the crown centre"


def test_the_two_legs_point_in_opposite_directions():
    left = Segment("l", Line((0, 0), (0, 1000)), Constant(300), normal_sign=+1)
    right = Segment("r", Line((3000, 0), (3000, 1000)), Constant(300), normal_sign=-1)
    assert left.outward_normal_at(0.5)[0] == pytest.approx(-1.0)
    assert right.outward_normal_at(0.5)[0] == pytest.approx(+1.0)


def test_a_bad_normal_sign_refuses():
    with pytest.raises(ModelError, match=r"\+1 or -1"):
        Segment("x", Line((0, 0), (0, 100)), Constant(200), normal_sign=2.0)


# ---------------------------------------------------------------------------
# Thickness profiles
# ---------------------------------------------------------------------------


def test_a_taper_is_linear_end_to_end():
    t = Tapered(start=400, end=250)
    assert t.at(0.0) == pytest.approx(400)
    assert t.at(0.5) == pytest.approx(325)
    assert t.at(1.0) == pytest.approx(250)


def test_a_haunch_is_thick_at_the_ends_and_constant_in_the_middle():
    h = Haunched(mid=200, haunch=400, extent=0.2)
    assert h.at(0.0) == pytest.approx(400)
    assert h.at(0.1) == pytest.approx(300)
    assert h.at(0.2) == pytest.approx(200)
    assert h.at(0.5) == pytest.approx(200)
    assert h.at(0.8) == pytest.approx(200)
    assert h.at(1.0) == pytest.approx(400), "symmetric -- both ends haunched"


def test_a_haunch_can_be_one_ended():
    h = Haunched(mid=200, haunch=400, extent=0.2, both_ends=False)
    assert h.at(0.0) == pytest.approx(400)
    assert h.at(1.0) == pytest.approx(200)


def test_overlapping_haunches_refuse():
    with pytest.raises(ModelError, match="overlap"):
        Haunched(mid=200, haunch=400, extent=0.7)


def test_thickness_extremes_are_reported():
    h = Haunched(mid=200, haunch=400, extent=0.2)
    assert h.maximum == pytest.approx(400)
    assert h.minimum == pytest.approx(200)


# ---------------------------------------------------------------------------
# The geometry of a crown unit
# ---------------------------------------------------------------------------


def test_crown_radius_and_rise_to_span(geometry):
    assert geometry.crown_radius == pytest.approx(
        (SPAN / 2) ** 2 / (2 * RISE) + RISE / 2
    )
    assert geometry.rise_to_span == pytest.approx(RISE / SPAN)


def test_three_segments_with_legs_and_one_without(geometry):
    assert len(geometry.segments()) == 3
    no_legs = CrownGeometry(span=SPAN, rise=RISE, leg_height=0)
    assert len(no_legs.segments()) == 1
    assert no_legs.segments()[0].name == Part.CROWN.value


def test_the_haunch_and_taper_reach_the_model(geometry):
    crown = next(s for s in geometry.segments() if s.name == Part.CROWN.value)
    leg = next(s for s in geometry.segments() if s.name == Part.LEFT_LEG.value)

    assert crown.thickness.at(0.0) == pytest.approx(350), "haunched at the springing"
    assert crown.thickness.at(0.5) == pytest.approx(200), "thin at the apex"
    assert leg.thickness.at(0.0) == pytest.approx(300), "thick at the base"
    assert leg.thickness.at(1.0) == pytest.approx(225), "tapering to the springing"


def test_a_zero_rise_crown_refuses_and_points_at_the_box():
    with pytest.raises(ModelError, match="BoxCulvert"):
        CrownGeometry(span=SPAN, rise=0.0)


def test_thicker_elements_appear_where_the_haunch_is(crown):
    """The frame must actually carry the varying thickness, not just record it.

    Each element takes the thickness at its OWN MIDPOINT, so the first element
    is a little thinner than the 350 mm at the springing itself. With a fine
    mesh its midpoint approaches the end and the ratio approaches (350/200)^3.
    """
    names = tuple(s.name for s in crown.geometry.segments())
    # The crown count must be set EXPLICITLY: a bare default_divisions is
    # overridden by the curvature-driven recommendation in __post_init__.
    fine = crown.with_layout(
        PerimeterLayout(
            divisions={Part.CROWN.value: 200}, default_divisions=100
        ).for_segments(names)
    )
    frame, by_segment = fine.build()
    members = [frame.members[i] for i in by_segment[Part.CROWN.value]]
    first = members[0].EI
    middle = members[len(members) // 2].EI

    assert first / middle == pytest.approx((350 / 200) ** 3, rel=0.05)


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------


def test_equilibrium_holds(crown):
    r = crown.solve()
    fx, fy, mz = r.frame_results.check_equilibrium()
    _, v = r.springing_thrust()
    assert abs(fx) < 1e-6 * abs(v)
    assert abs(fy) < 1e-6 * abs(v)


def test_the_vertical_reaction_carries_the_soil_and_the_structure(crown, geometry):
    """Half the total weight at each foot. Checked against the soil area above
    the crown computed independently from the circular segment area."""
    r = crown.solve()
    _, v = r.springing_thrust()

    arc = Arc((0, geometry.springing_level), (SPAN, geometry.springing_level), rise=RISE)
    theta = 2 * arc.half_angle
    segment_area = arc.radius**2 * (theta - math.sin(theta)) / 2
    soil_area = SPAN * (RISE + crown.loading.fill_depth) - segment_area
    soil = soil_area * geometry.transverse_width * crown.loading.fill_density * g * 1e-9

    # Self weight is extra, so the reaction exceeds the soil alone but not by
    # more than the concrete could plausibly weigh.
    assert v > soil / 2
    assert v < soil / 2 * 1.8


def test_an_arch_pushes_its_supports_apart(geometry):
    """With no lateral earth pressure there is nothing to push back, so the
    foot reaction must act inward -- resisting an outward thrust."""
    culvert = CrownCulvert(
        geometry=geometry, loading=CrownLoading(fill_depth=600, k0=1e-6)
    )
    h, _ = culvert.solve().springing_thrust()
    assert h > 0, "the support must push the left foot inward"


def test_lateral_earth_pressure_opposes_the_thrust(geometry):
    """The design consequence: on a unit with tall legs the lateral pressure
    can reverse the springing thrust entirely, so the footing sees the
    opposite of what an arch calculation alone would predict."""
    thrusts = []
    for k0 in (0.001, 0.2, 0.5, 0.8):
        culvert = CrownCulvert(
            geometry=geometry, loading=CrownLoading(fill_depth=600, k0=k0)
        )
        thrusts.append(culvert.solve().springing_thrust()[0])

    assert thrusts == sorted(thrusts, reverse=True), "more k0, less outward thrust"
    assert thrusts[0] > 0 > thrusts[-1], "and it changes sign"


def test_horizontal_equilibrium_of_half_the_structure_closes(crown, geometry):
    """The test that ties everything together.

    Apex thrust, the lateral soil force on the left half, and the foot
    reaction must balance. It fails if any of the three is resolved into the
    wrong axis, which is the easiest mistake to make on a curved member.
    """
    r = crown.solve()
    h_foot, _ = r.springing_thrust()

    thrusts = dict(r.segment_thrust(Part.CROWN))
    apex_f = min(thrusts, key=lambda f: abs(f - 0.5))
    apex_thrust = thrusts[apex_f]

    load = crown.loading
    width = geometry.transverse_width

    # Lateral force on the left leg, at its mid-height.
    leg_mid_depth = load.fill_depth + RISE + LEG / 2
    leg_force = load.horizontal_stress(leg_mid_depth, 0.0) * LEG * width

    # Lateral force on the left half of the crown, over its vertical projection.
    crown_mid_depth = load.fill_depth + RISE / 2
    crown_force = load.horizontal_stress(crown_mid_depth, 0.0) * RISE * width

    net_inward = leg_force + crown_force - apex_thrust
    assert -h_foot == pytest.approx(net_inward, rel=0.05)


def test_the_thrust_is_compression_everywhere(crown):
    r = crown.solve()
    for part in (Part.CROWN, Part.LEFT_LEG, Part.RIGHT_LEG):
        for _, n in r.segment_thrust(part):
            assert n > 0, f"{part.value} must be in compression"
    assert r.max_thrust > 0


def test_the_thrust_is_greatest_at_the_springing_and_least_at_the_apex(crown):
    """An arch's axial force is H/cos(theta): smallest where it is flat."""
    r = crown.solve()
    thrusts = dict(r.segment_thrust(Part.CROWN))
    apex = thrusts[min(thrusts, key=lambda f: abs(f - 0.5))]
    springing = thrusts[min(thrusts)]
    assert springing > apex


def test_a_symmetric_unit_gives_symmetric_results(crown):
    r = crown.solve()
    left = r.segment_moments(Part.LEFT_LEG)
    right = r.segment_moments(Part.RIGHT_LEG)
    for (fa, ma), (fb, mb) in zip(left, right):
        assert fa == pytest.approx(fb)
        assert ma == pytest.approx(mb, abs=1.0)


def test_the_crown_moment_is_symmetric_about_the_apex(crown):
    r = crown.solve()
    moments = r.segment_moments(Part.CROWN)
    for (fa, ma), (fb, mb) in zip(moments, reversed(moments)):
        assert fa == pytest.approx(1.0 - fb)
        assert ma == pytest.approx(mb, abs=1.0)


def test_unbalanced_surcharge_breaks_the_symmetry(geometry):
    """And it is the unbalanced case that governs an arch."""
    balanced = CrownCulvert(
        geometry=geometry, loading=CrownLoading(fill_depth=600, k0=0.5)
    ).solve()
    skewed = CrownCulvert(
        geometry=geometry,
        loading=CrownLoading(fill_depth=600, k0=0.5, surcharge_left=0.02),
    ).solve()

    assert balanced.peak_moment(Part.LEFT_LEG)[1] == pytest.approx(
        balanced.peak_moment(Part.RIGHT_LEG)[1], abs=1.0
    )
    assert abs(
        skewed.peak_moment(Part.LEFT_LEG)[1] - skewed.peak_moment(Part.RIGHT_LEG)[1]
    ) > 1e6
    assert abs(skewed.max_moment) > abs(balanced.max_moment)


def test_the_arching_factor_increases_the_load(crown):
    plain = crown.solve()
    arched = CrownCulvert(
        geometry=crown.geometry,
        loading=CrownLoading(fill_depth=600, k0=0.5, vertical_arching_factor=1.3),
    ).solve()
    assert arched.springing_thrust()[1] > plain.springing_thrust()[1]


def test_base_fixity_changes_the_base_moment(geometry):
    pinned = CrownCulvert(geometry=geometry, base_fixity=BaseFixity.PINNED).solve()
    fixed = CrownCulvert(geometry=geometry, base_fixity=BaseFixity.FIXED).solve()

    base_pinned = dict(pinned.segment_moments(Part.LEFT_LEG))[0.0]
    base_fixed = dict(fixed.segment_moments(Part.LEFT_LEG))[0.0]
    assert abs(base_pinned) < 1.0, "a pin cannot carry moment"
    assert abs(base_fixed) > abs(base_pinned)


def test_a_sprung_base_still_solves(geometry):
    r = CrownCulvert(geometry=geometry, base_fixity=BaseFixity.SPRUNG).solve()
    assert r.springing_thrust()[1] != 0.0


# ---------------------------------------------------------------------------
# An arch beats a box, which is why the shape exists
# ---------------------------------------------------------------------------


def test_the_arch_carries_less_moment_than_an_equivalent_box():
    """Same span, same cover, same wall thickness. The arch converts most of
    the load into thrust, so what is left in bending is far smaller."""
    span, height, t = 4000.0, 2700.0, 250.0

    box = BoxCulvert(
        geometry=CulvertGeometry(
            clear_span=span - t, clear_height=height - t,
            top_thickness=t, base_thickness=t, wall_thickness=t,
        ),
        loading=CulvertLoading(fill_depth=600, fill_density=2000, k0=0.5),
    ).solve()

    arch = CrownCulvert(
        geometry=CrownGeometry(
            span=span, rise=1200, leg_height=1500,
            crown_thickness=t, haunch_thickness=t,
            leg_thickness_base=t, leg_thickness_top=t,
        ),
        loading=CrownLoading(fill_depth=600, fill_density=2000, k0=0.5),
    ).solve()

    box_peak = abs(box.peak_moment(Wall.TOP)[1])
    arch_peak = abs(arch.peak_moment(Part.CROWN)[1])
    assert arch_peak < 0.5 * box_peak


# ---------------------------------------------------------------------------
# Directed nodes, on a curve
# ---------------------------------------------------------------------------


def test_the_layout_adopts_the_crown_segment_names(crown):
    assert tuple(crown.layout.segments) == tuple(
        s.name for s in crown.geometry.segments()
    )


def test_a_node_can_be_placed_along_the_arc_not_the_chord(crown, geometry):
    """A precast unit is made to its arc length, and that is what a drawing
    dimensions -- so a distance along the crown means along the curve."""
    arc_length = next(
        s for s in geometry.segments() if s.name == Part.CROWN.value
    ).length
    directed = crown.with_node_at_distance(Part.CROWN, 1000.0, "lifting point")
    assert 1000.0 / arc_length == pytest.approx(
        min(
            directed.layout.fractions(Part.CROWN.value),
            key=lambda f: abs(f - 1000.0 / arc_length),
        )
    )
    assert arc_length > SPAN, "the arc is longer than the span it covers"


def test_a_node_can_be_placed_by_fraction(crown):
    directed = crown.with_node_at(Part.CROWN, 0.5, "apex")
    assert 0.5 in directed.layout.fractions(Part.CROWN.value)
    assert directed.layout.reasons_for(Part.CROWN.value)[0.5] == "apex"


def test_refinement_lands_nodes_on_the_peaks(crown):
    coarse = crown.with_layout(
        PerimeterLayout(default_divisions=3).for_segments(
            tuple(s.name for s in crown.geometry.segments())
        )
    )
    fine = crown.with_layout(
        PerimeterLayout(default_divisions=120).for_segments(
            tuple(s.name for s in crown.geometry.segments())
        )
    ).solve()
    target = max(m for _, m in fine.segment_moments(Part.CROWN))

    before = max(m for _, m in coarse.solve().segment_moments(Part.CROWN))
    after = max(m for _, m in coarse.refined().solve().segment_moments(Part.CROWN))

    assert abs(after - target) <= abs(before - target)


def test_refinement_converges_rather_than_being_idempotent(crown):
    """The difference between a curved segment and a straight one.

    On a box, refinement is idempotent: the geometry is exact, so once a node
    sits on the peak the answer stops moving. On a crown the geometry is a
    chain of chords, so each pass improves the SHAPE as well as the sampling
    and the answer keeps moving -- but by less each time, toward the converged
    value. Asserting idempotence here would be asserting something false.
    """
    names = tuple(s.name for s in crown.geometry.segments())
    coarse = crown.with_layout(
        PerimeterLayout(divisions={Part.CROWN.value: 3}, default_divisions=3)
        .for_segments(names)
    )
    target = crown.with_layout(
        PerimeterLayout(divisions={Part.CROWN.value: 400}, default_divisions=200)
        .for_segments(names)
    ).solve().peak_moment(Part.CROWN)[1]

    values = [
        coarse.refined(passes=p).solve().peak_moment(Part.CROWN)[1]
        for p in (1, 2, 3, 4)
    ]
    errors = [abs(v - target) for v in values]
    changes = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]

    assert errors == sorted(errors, reverse=True), "each pass must get closer"
    assert changes == sorted(changes, reverse=True), "and move less than the last"


def test_the_default_crown_divisions_follow_the_subtended_angle(crown, geometry):
    """A default that ignores curvature is wrong by more than 10% on a deep
    arch, silently. The recommendation aims at 5 degrees per chord."""
    recommended = geometry.recommended_crown_divisions()
    assert recommended > 20, "124 degrees at 5 per chord"
    assert crown.layout.divisions_for(Part.CROWN.value) == recommended

    names = tuple(s.name for s in geometry.segments())
    target = crown.with_layout(
        PerimeterLayout(divisions={Part.CROWN.value: 400}, default_divisions=200)
        .for_segments(names)
    ).solve().peak_moment(Part.CROWN)[1]
    actual = crown.solve().peak_moment(Part.CROWN)[1]
    assert abs(actual - target) < 0.02 * abs(target)


def test_an_explicit_crown_division_count_is_respected(geometry):
    layout = PerimeterLayout(divisions={Part.CROWN.value: 6})
    culvert = CrownCulvert(geometry=geometry, layout=layout)
    assert culvert.layout.divisions_for(Part.CROWN.value) == 6


def test_a_flatter_arch_needs_fewer_divisions():
    deep = CrownGeometry(span=4000, rise=1600)
    shallow = CrownGeometry(span=4000, rise=400)
    assert deep.recommended_crown_divisions() > shallow.recommended_crown_divisions()


def test_the_chord_approximation_converges(crown):
    """A curved member is a chain of straight chords, so the answer must settle
    as the crown is divided -- the error is controlled, not baked in."""
    names = tuple(s.name for s in crown.geometry.segments())
    values = []
    for divisions in (4, 8, 16, 32, 64):
        r = crown.with_layout(
            PerimeterLayout(default_divisions=divisions).for_segments(names)
        ).solve()
        values.append(r.springing_thrust()[0])

    diffs = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
    assert diffs == sorted(diffs, reverse=True), "successive changes must shrink"
    assert diffs[-1] < 0.01 * abs(values[-1])


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_describe_reports_the_thrust_and_the_efficiency(crown):
    text = "\n".join(crown.solve().describe())
    assert "horizontal thrust" in text
    assert "Arch efficiency" in text
    assert "Equilibrium residual" in text


def test_arch_efficiency_is_small_for_a_working_arch(crown):
    """A low M/(N.t) means the line of thrust is inside the section."""
    assert 0 < crown.solve().arch_efficiency < 1.0 / 6.0


def test_geometry_describe_mentions_the_haunch_and_taper(geometry):
    text = "\n".join(geometry.describe())
    assert "Haunch" in text
    assert "tapering" in text
    assert "rise/span" in text
