"""Tests for steel geometry, materials and the self-verifying catalogue.

Two kinds of check here. The geometry is tested against closed-form results,
because a rectangle's plastic modulus is bd^2/4 and nothing is going to change
that. The catalogue is tested by cross-check: computed properties against
published ones, with the difference expected to sit inside the band the
unmodelled root radii explain.

The second kind is unusual and worth stating plainly. It does not confirm that
the catalogue is RIGHT -- it confirms that its two halves agree with each
other, which eliminates the single most likely error in a file of three hundred
hand-entered numbers.
"""

from __future__ import annotations

import pytest

from austruct.core.exceptions import ModelError
from austruct.materials.steel import steel
from austruct.sections import steel_catalogue as cat
from austruct.sections.steel_profile import (
    ShapeType,
    channel,
    i_section,
    plate_section,
)


@pytest.fixture(autouse=True)
def _permit():
    """Every test runs inside scoped permission, so the guard test below
    cannot be disabled by leakage from another test."""
    with cat.unverified_ok():
        yield


# ---------------------------------------------------------------------------
# Geometry against closed form
# ---------------------------------------------------------------------------


def test_a_rectangle_matches_every_hand_formula():
    """I = bd^3/12, Z = bd^2/6, S = bd^2/4, so S/Z = 1.5 exactly."""
    b, t = 300.0, 20.0
    p = plate_section(b, t).properties()

    assert p.A == pytest.approx(b * t)
    assert p.Ix == pytest.approx(t * b**3 / 12)
    assert p.Iy == pytest.approx(b * t**3 / 12)
    assert p.Zx == pytest.approx(t * b**2 / 6)
    assert p.Sx == pytest.approx(t * b**2 / 4)
    assert p.shape_factor_x == pytest.approx(1.5)
    assert p.rx == pytest.approx((b**2 / 12) ** 0.5)


def test_an_i_section_matches_the_hand_formulas():
    d, bf, tf, tw = 304.0, 165.0, 10.2, 6.1
    p = i_section(d, bf, tf, tw).properties()

    area = 2 * bf * tf + (d - 2 * tf) * tw
    ix = bf * d**3 / 12 - (bf - tw) * (d - 2 * tf) ** 3 / 12
    iy = 2 * (tf * bf**3 / 12) + (d - 2 * tf) * tw**3 / 12
    sx = 2 * bf * tf * (d - tf) / 2 + tw * (d - 2 * tf) ** 2 / 4

    assert p.A == pytest.approx(area)
    assert p.Ix == pytest.approx(ix)
    assert p.Iy == pytest.approx(iy)
    assert p.Sx == pytest.approx(sx)
    assert p.Iw == pytest.approx(iy * (d - tf) ** 2 / 4)


def test_a_rolled_i_section_has_a_shape_factor_near_1_1():
    """Between 1.10 and 1.20 for anything that looks like a UB. A value
    outside that means the plastic modulus is wrong."""
    p = i_section(304, 165, 10.2, 6.1).properties()
    assert 1.08 < p.shape_factor_x < 1.20


def test_the_channel_centroid_sits_away_from_the_web():
    """The reason steel needs its own geometry model: a channel is not
    symmetric about its vertical axis, and the banded RC model has no way to
    say so."""
    c = channel(250.0, 90.0, 15.0, 8.0)
    cx, cy = c.centroid

    assert cx > 8.0 / 2, "the centroid must lie outboard of the web"
    assert cy == pytest.approx(0.0), "but on the axis of symmetry vertically"


def test_a_channel_has_far_less_minor_axis_stiffness():
    p = channel(250.0, 90.0, 15.0, 8.0).properties()
    assert p.Iy < 0.2 * p.Ix
    assert p.ry < p.rx


def test_the_torsion_constant_is_the_thin_walled_sum():
    """sum(b.t^3/3), which for a rolled section is LOW -- the fillets are not
    modelled and torsion is acutely sensitive to them."""
    d, bf, tf, tw = 304.0, 165.0, 10.2, 6.1
    expected = 2 * bf * tf**3 / 3 + (d - 2 * tf) * tw**3 / 3
    assert i_section(d, bf, tf, tw).properties().J == pytest.approx(expected)


def test_approximations_are_declared_not_hidden():
    p = i_section(304, 165, 10.2, 6.1).properties()
    assert any("J" in note for note in p.approximate)
    assert any("I_w" in note for note in p.approximate)


def test_a_welded_section_is_the_same_geometry_but_a_different_shape_type():
    rolled = i_section(400, 200, 16, 10)
    welded = i_section(400, 200, 16, 10, welded=True)
    assert rolled.properties().Ix == pytest.approx(welded.properties().Ix)
    assert welded.shape is ShapeType.WELDED_I


def test_impossible_geometry_refuses():
    with pytest.raises(ModelError, match="exceed twice"):
        i_section(20, 200, 16, 10)
    with pytest.raises(ModelError, match="positive"):
        plate_section(0, 10)


# ---------------------------------------------------------------------------
# Materials -- the thickness bands
# ---------------------------------------------------------------------------


def test_yield_stress_falls_as_the_section_gets_thicker():
    g = steel("300")
    assert g.fy(8) > g.fy(15) > g.fy(30)


def test_a_flange_and_a_web_can_have_different_yield_stresses():
    """The thing the module exists to stop being averaged away."""
    section = cat.get("610UB125")
    assert section.tf > section.tw
    assert section.fy_flange <= section.fy_web


def test_asking_for_a_thickness_beyond_the_range_refuses():
    with pytest.raises(ModelError, match="not made"):
        steel("300").fy(500)


def test_plate_and_section_grades_are_kept_apart():
    """A plate Grade 350 and a section Grade 350 are different materials with
    different band structures. They may coincide at some thicknesses -- which
    is exactly why they must not share a name."""
    section = steel("350")
    plate_grade = steel("350P")

    assert section.product == "hot-rolled section"
    assert plate_grade.product == "plate"
    assert section.standard != plate_grade.standard
    assert section.bands != plate_grade.bands
    assert section.fy(15) != plate_grade.fy(15)


def test_an_unknown_grade_lists_the_options():
    with pytest.raises(KeyError) as exc:
        steel("999")
    assert "300" in str(exc.value)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def test_a_section_can_be_nominated_by_its_drawing_designation():
    s = cat.get("310UB40.4")
    assert s.designation == "310UB40.4"
    assert s.kind == "UB"
    assert s.d == 304


def test_designations_are_case_insensitive():
    assert cat.get("310ub40.4").designation == cat.get("310UB40.4").designation


def test_an_unknown_designation_suggests_near_matches():
    with pytest.raises(KeyError) as exc:
        cat.get("310UB99")
    assert "310UB40.4" in str(exc.value)


def test_listing_the_catalogue_needs_no_permission():
    previous = cat.allow_unverified()
    cat.allow_unverified(False)
    try:
        assert "310UB40.4" in cat.names()
        assert "310UB40.4" in cat.catalogue()
        assert "NOT GIVEN" in cat.catalogue()
    finally:
        cat.allow_unverified(previous)


def test_the_guard_refuses_without_permission():
    previous = cat.allow_unverified()
    cat.allow_unverified(False)
    try:
        assert not cat.is_verified()
        with pytest.raises(cat.UnverifiedSectionData, match="UNVERIFIED"):
            cat.get("310UB40.4")
    finally:
        cat.allow_unverified(previous)


def test_filtering_by_type():
    assert all(n.endswith("PFC") for n in cat.names("PFC"))
    assert set(cat.names("UB")).isdisjoint(cat.names("UC"))


def test_a_plate_needs_no_permission_because_it_is_made_to_order():
    previous = cat.allow_unverified()
    cat.allow_unverified(False)
    try:
        p = cat.plate(200, 12)
        assert p.properties.A == pytest.approx(2400)
    finally:
        cat.allow_unverified(previous)


def test_grade_can_be_changed_without_rebuilding():
    s = cat.get("310UB40.4")
    higher = s.with_grade("350")
    assert higher.fy_flange > s.fy_flange
    assert higher.d == s.d


# ---------------------------------------------------------------------------
# The cross-check -- what makes this catalogue different
# ---------------------------------------------------------------------------


def test_verification_runs_without_permission():
    """Checking the data is not using it. Refusing to run the check until the
    data is verified would be exactly backwards."""
    previous = cat.allow_unverified()
    cat.allow_unverified(False)
    try:
        assert cat.verify_catalogue().comparisons
    finally:
        cat.allow_unverified(previous)


def test_every_universal_beam_is_internally_consistent():
    """Computed geometry agrees with published properties across the whole UB
    range, inside the band the unmodelled fillets explain."""
    result = cat.verify_catalogue("UB")
    assert result.passed, result.report()


def test_the_fillet_error_has_the_predicted_sign_and_size():
    """Not just 'within tolerance' -- the DIRECTION and MAGNITUDE are what say
    the disagreement is the fillets rather than a mistake."""
    result = cat.verify_catalogue("UB")

    # Computed low on the major axis: the fillets add material near the web.
    assert -0.04 < result.mean_error("A") < 0.0
    assert -0.04 < result.mean_error("Ix") < 0.0
    assert -0.04 < result.mean_error("Sx") < 0.0

    # Barely affected on the minor axis: the fillets sit close to it.
    assert abs(result.mean_error("Iy")) < 0.03

    # And badly low in torsion, which is why J carries a 40% tolerance.
    assert result.mean_error("J") < -0.05


def _corrupted_comparison(prop: str, profile, published_value: float):  # noqa: ANN001, ANN202
    from austruct.sections.steel_catalogue import TOLERANCES, PropertyComparison

    return PropertyComparison(
        designation="corrupted",
        prop=prop,
        computed=getattr(profile.properties(), prop),
        published=published_value,
        tolerance=TOLERANCES[prop],
    )


def test_the_check_catches_a_corrupted_flange_width():
    """The test that the cross-check has any power at all.

    A flange width error is the easiest to catch, because I_y goes as b^3 --
    a 10% error becomes 33% -- against the tightest tolerance in the table.
    """
    good = cat.get("310UB40.4")
    corrupted = i_section(good.d, good.bf * 1.10, good.tf, good.tw)

    assert not _corrupted_comparison("Iy", corrupted, good.published.Iy).within
    assert not _corrupted_comparison("ry", corrupted, good.published.ry).within


def test_a_large_thickness_error_is_caught_but_a_small_one_can_hide():
    """The check's sensitivity limit, stated rather than assumed.

    The area tolerance has to be wide enough to absorb the unmodelled fillets,
    and that width is exactly what a small thickness error can hide inside.
    For a 310UB40.4 the computed area already sits about 2% low, so a flange
    10% too thick lands at +4% -- inside the 5% band.

    A 25% error does not fit, and neither does any flange-WIDTH error worth
    the name. Knowing where the floor is matters more than pretending there
    is not one.
    """
    good = cat.get("310UB40.4")

    small = i_section(good.d, good.bf, good.tf * 1.10, good.tw)
    assert _corrupted_comparison("A", small, good.published.A).within, (
        "a 10% flange thickness error hides inside the fillet band -- this is "
        "the documented limit, not a bug"
    )

    large = i_section(good.d, good.bf, good.tf * 1.25, good.tw)
    assert not _corrupted_comparison("A", large, good.published.A).within


def test_the_three_way_area_check_localises_the_error():
    """Dimensions, tabulated area and tabulated mass are three independent
    routes to the same number. Two agreeing identifies the third."""
    result = cat.verify_catalogue()
    bad = {m.designation for m in result.inconsistent_sections}

    # Known-bad channels, recorded as such in the data file rather than tuned
    # until they pass.
    assert "100PFC" in bad
    assert "125PFC" in bad

    for check in result.inconsistent_sections:
        assert check.verdict != "consistent"
        assert "DIMENSIONS" in check.verdict or "disagree" in check.verdict


def test_the_known_bad_channels_are_flagged_in_the_data_file():
    """The file admits what the check found, so nobody has to rediscover it."""
    for designation in ("100PFC", "125PFC", "200PFC"):
        assert "INCONSISTENT" in cat.get(designation).confidence


def test_mass_and_area_agree_for_every_consistent_section():
    """Two ways of writing the same fact, from the same table."""
    result = cat.verify_catalogue()
    for check in result.mass_checks:
        if check.consistent:
            assert check.published_vs_mass < 0.02


def test_the_report_explains_rather_than_just_failing():
    text = cat.verify_catalogue().report()
    assert "does NOT confirm" in text
    assert "Systematic error by property" in text
    assert "fillet" in text
