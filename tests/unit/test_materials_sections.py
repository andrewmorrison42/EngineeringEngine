"""Unit tests for the materials and sections layers."""

from __future__ import annotations

import math

import pytest

from austruct.core.basis import AS5100_5_2017
from austruct.core.exceptions import ModelError, OutsideEnvelope
from austruct.materials import (
    STANDARD_GRADES,
    Ductility,
    bar_area,
    bars_for_area,
    concrete,
    elastic_modulus,
    options_for_area,
    reinforcement,
    spacing_for_area,
)
from austruct.sections import (
    cracked_properties,
    cracking_moment,
    from_bands,
    inverted_tee,
    modular_ratio,
    rc_beam,
    rc_tee,
    rectangle,
    tee,
    uncracked_properties,
)

# ---------------------------------------------------------------------------
# Concrete
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grade", STANDARD_GRADES)
def test_standard_grades_build(grade):
    c = concrete(grade)
    assert c.fc == grade
    assert c.Ec > 0
    assert c.ec_source == "table"


def test_stress_block_parameters_are_clipped():
    """alpha_2 and gamma are both bounded to [0.67, 0.85]."""
    for grade in STANDARD_GRADES:
        c = concrete(grade)
        assert 0.67 <= c.alpha2 <= 0.85
        assert 0.67 <= c.gamma <= 0.85


def test_high_strength_concrete_has_lower_stress_block_factors():
    assert concrete(100).alpha2 < concrete(25).alpha2
    assert concrete(100).gamma < concrete(25).gamma


def test_tensile_strength_scales_with_sqrt_fc():
    c = concrete(64)
    assert c.fctf == pytest.approx(0.6 * 8.0)
    assert c.fct == pytest.approx(0.36 * 8.0)


def test_concrete_outside_range_raises():
    with pytest.raises(OutsideEnvelope):
        concrete(15)
    with pytest.raises(OutsideEnvelope):
        concrete(120)


def test_as5100_minimum_grade_is_higher_than_as3600():
    concrete(20)  # fine for AS 3600
    with pytest.raises(OutsideEnvelope):
        concrete(20, standard=AS5100_5_2017)


def test_non_default_density_uses_the_formula_not_the_table():
    light = concrete(32, density=1900)
    normal = concrete(32)
    assert light.ec_source == "formula"
    assert light.Ec < normal.Ec


def test_elastic_modulus_switches_expression_at_40mpa():
    below = elastic_modulus(39.0)
    above = elastic_modulus(41.0)
    assert below > 0 and above > 0
    # Continuity check across the switch: the two branches should not disagree
    # wildly at the boundary.
    assert abs(elastic_modulus(40.0) - elastic_modulus(40.001)) / elastic_modulus(40.0) < 0.05


# ---------------------------------------------------------------------------
# Reinforcement
# ---------------------------------------------------------------------------


def test_reinforcement_lookup_and_unknown_grade():
    assert reinforcement("D500N").fsy == 500.0
    assert reinforcement("d500n").ductility is Ductility.N
    with pytest.raises(KeyError):
        reinforcement("D600X")


def test_steel_stress_is_elastic_perfectly_plastic():
    steel = reinforcement("D500N")
    assert steel.stress(0.001) == pytest.approx(200.0)
    assert steel.stress(0.01) == pytest.approx(500.0)
    assert steel.stress(-0.01) == pytest.approx(-500.0)
    assert steel.epsilon_sy == pytest.approx(0.0025)


# ---------------------------------------------------------------------------
# Bar catalogue -- the queryable reference layer
# ---------------------------------------------------------------------------


def test_bar_area_and_counts():
    assert bar_area(20) == pytest.approx(math.pi * 100)
    assert bars_for_area(1000, 20) == 4
    assert bars_for_area(1, 20) == 2  # practical minimum


def test_spacing_for_area():
    s = spacing_for_area(1000.0, 12)
    assert s == pytest.approx(bar_area(12) * 1000.0 / 1000.0)


def test_options_for_area_are_sufficient_and_sorted():
    required = 1800.0
    options = options_for_area(required)
    assert options
    assert all(o.area >= required for o in options)
    assert options == sorted(options, key=lambda o: o.area)
    assert all("-N" in o.label for o in options)


def test_options_respect_the_waste_limit():
    options = options_for_area(1000.0, max_waste=0.10)
    assert all(o.area <= 1100.0 for o in options)


# ---------------------------------------------------------------------------
# Section geometry
# ---------------------------------------------------------------------------


def test_rectangle_properties_match_hand_formulae():
    b, D = 300.0, 600.0
    r = rectangle(b, D)
    assert r.area == pytest.approx(b * D)
    assert r.centroid == pytest.approx(D / 2)
    assert r.I_gross == pytest.approx(b * D**3 / 12)
    assert r.Z_bottom == pytest.approx(b * D**2 / 6)


def test_area_above_and_centroid_above_for_rectangle():
    r = rectangle(300, 600)
    assert r.area_above(200) == pytest.approx(300 * 200)
    assert r.centroid_above(200) == pytest.approx(100)
    assert r.area_above(0) == 0.0
    assert r.area_above(1000) == pytest.approx(300 * 600), "must clamp at the soffit"


def test_tee_partial_integrals_span_the_flange_boundary():
    t = tee(bf=1200, Df=150, bw=300, D=600)
    assert t.width_at(100) == 1200
    assert t.width_at(150) == 300, "at the boundary the lower band governs"
    assert t.width_at(400) == 300
    # Area above 300 mm = full flange + 150 mm of web
    assert t.area_above(300) == pytest.approx(1200 * 150 + 300 * 150)


def test_tee_gross_properties_against_hand_calculation():
    bf, Df, bw, D = 1200.0, 150.0, 300.0, 600.0
    t = tee(bf, Df, bw, D)
    a_flange, a_web = bf * Df, bw * (D - Df)
    area = a_flange + a_web
    yc = (a_flange * Df / 2 + a_web * (Df + (D - Df) / 2)) / area
    assert t.area == pytest.approx(area)
    assert t.centroid == pytest.approx(yc)


def test_inverted_tee_is_the_mirror_of_a_tee():
    t = tee(1200, 150, 300, 600)
    it = inverted_tee(300, 600, 1200, 150)
    assert it.area == pytest.approx(t.area)
    assert it.centroid == pytest.approx(t.D - t.centroid)


def test_from_bands_builds_arbitrary_stepped_sections():
    s = from_bands([(300, 200), (150, 400)])
    assert s.D == 600
    assert s.area == pytest.approx(300 * 200 + 150 * 400)
    assert s.b_min == 150


def test_non_contiguous_bands_raise():
    from austruct.sections import Band, SectionGeometry

    with pytest.raises(ModelError, match="contiguous"):
        SectionGeometry(bands=(Band(0, 100, 300), Band(150, 300, 300)))


def test_section_must_start_at_zero():
    from austruct.sections import Band, SectionGeometry

    with pytest.raises(ModelError, match="extreme compression fibre"):
        SectionGeometry(bands=(Band(50, 300, 300),))


# ---------------------------------------------------------------------------
# RC sections
# ---------------------------------------------------------------------------


def test_rc_beam_places_bars_from_cover_and_fitment():
    s = rc_beam(300, 600, concrete(32), cover=40, n_bars=4, diameter=24,
                fitment_diameter=12, fitment_spacing=200)
    assert s.layers[0].depth == pytest.approx(600 - 40 - 12 - 12)
    assert s.d_o == pytest.approx(536)
    assert s.fitment.area == pytest.approx(2 * bar_area(12))
    assert s.fitment.asv_per_s == pytest.approx(2 * bar_area(12) / 200)


def test_rc_section_is_immutable_and_copies_cleanly():
    s = rc_beam(300, 600, concrete(32), n_bars=4, diameter=24, fitment_spacing=200)
    tighter = s.with_fitment(s.fitment.__class__.from_bars(12, 100))
    assert s.fitment.spacing == 200, "original must be unchanged"
    assert tighter.fitment.spacing == 100


def test_bar_below_soffit_raises():
    from austruct.sections import RCSection, RebarLayer

    with pytest.raises(ModelError, match="soffit"):
        RCSection(
            geometry=rectangle(300, 600),
            concrete=concrete(32),
            layers=(RebarLayer(area=1000, depth=700),),
        )


def test_tee_web_width_is_used_for_shear():
    t = rc_tee(1200, 150, 300, 600, concrete(32), n_bars=4, diameter=24,
               fitment_spacing=200)
    assert t.bv == 300, "shear must use the web, not the flange"
    assert t.b == 1200, "flexure must use the flange"


# ---------------------------------------------------------------------------
# Transformed and cracked section properties
# ---------------------------------------------------------------------------


def test_modular_ratio():
    s = rc_beam(300, 600, concrete(32), n_bars=4, diameter=24, fitment_spacing=200)
    assert modular_ratio(s) == pytest.approx(200_000 / 30_100)


def test_cracked_inertia_is_less_than_uncracked():
    s = rc_beam(300, 600, concrete(32), n_bars=4, diameter=24, fitment_spacing=200)
    un = uncracked_properties(s)
    cr = cracked_properties(s)
    assert cr.I < un.I
    assert cr.na_depth < un.na_depth
    assert cr.cracked and not un.cracked


def test_more_steel_raises_the_cracked_neutral_axis_and_inertia():
    light = rc_beam(300, 600, concrete(32), n_bars=2, diameter=16, fitment_spacing=200)
    heavy = rc_beam(300, 600, concrete(32), n_bars=6, diameter=28, fitment_spacing=200)
    assert cracked_properties(heavy).na_depth > cracked_properties(light).na_depth
    assert cracked_properties(heavy).I > cracked_properties(light).I


def test_cracking_moment_is_positive_and_scales_with_fctf():
    weak = rc_beam(300, 600, concrete(25), n_bars=4, diameter=24, fitment_spacing=200)
    strong = rc_beam(300, 600, concrete(50), n_bars=4, diameter=24, fitment_spacing=200)
    assert cracking_moment(weak) > 0
    assert cracking_moment(strong) > cracking_moment(weak)


def test_shrinkage_stress_reduces_the_cracking_moment():
    s = rc_beam(300, 600, concrete(32), n_bars=4, diameter=24, fitment_spacing=200)
    assert cracking_moment(s, sigma_cs=1.0) < cracking_moment(s)
