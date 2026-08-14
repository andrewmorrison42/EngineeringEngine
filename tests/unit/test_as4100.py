"""Tests for AS 4100 classification, section capacity and member buckling.

The property that matters most here is one the reinforced concrete tests never
have to make: **the member capacity must fall away with length**. A steel beam
that reports the same capacity at 12 m as at 1 m has not had its buckling check
done, and the number it returns is several times the real one.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from austruct.core.exceptions import ModelError
from austruct.core.units import kN, kNm, m
from austruct.design import as4100
from austruct.design.as4100 import constants as C
from austruct.sections import steel_catalogue as cat


@pytest.fixture(autouse=True)
def _permit():
    with cat.unverified_ok():
        yield


@pytest.fixture
def beam():
    return cat.get("310UB40.4")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_a_rolled_universal_beam_is_compact(beam):
    """Which is why rolled sections are convenient: they reach the plastic
    moment without local buckling."""
    assert as4100.classify(beam).compactness is as4100.Compactness.COMPACT


def test_the_flange_outstand_is_measured_from_the_web_not_the_centreline(beam):
    """(b_f - t_w)/2, not b_f/2. Using half the flange width would include half
    the web thickness and understate the slenderness."""
    flange = next(
        e for e in as4100.plate_elements(beam) if e.name == "flange outstand"
    )
    assert flange.b == pytest.approx((beam.bf - beam.tw) / 2)
    assert flange.b < beam.bf / 2


def test_a_channel_flange_outstand_is_the_whole_projection():
    """A channel flange is held at the web and free at its toe, so the whole
    projection is the outstand -- roughly twice an I-section's for the same
    overall width."""
    pfc = cat.get("250PFC")
    flange = next(
        e for e in as4100.plate_elements(pfc) if e.name == "flange outstand"
    )
    assert flange.b == pytest.approx(pfc.bf - pfc.tw)


def test_slenderness_carries_the_yield_stress(beam):
    """lambda_e = (b/t) sqrt(f_y/250). A higher grade is MORE prone to local
    buckling for the same geometry -- the plate does not care what grade it is,
    it is being asked to carry more stress."""
    normal = as4100.classify(beam)
    stronger = as4100.classify(beam.with_grade("350"))
    assert stronger.lambda_s > normal.lambda_s


def test_the_worst_element_governs(beam):
    slenderness = as4100.classify(beam)
    worst = max(slenderness.elements, key=lambda e: e.utilisation)
    assert slenderness.governing is worst


def test_a_slender_section_gets_a_reduced_modulus():
    """Ze < Z once the element buckles before yield."""
    ze = as4100.effective_modulus(
        as4100.Compactness.SLENDER,
        lambda_s=200.0, lambda_sp=9.0, lambda_sy=16.0,
        Z=1e6, S=1.12e6,
    )
    assert ze < 1e6


def test_a_compact_section_uses_the_plastic_modulus_but_capped_at_1_5_Z():
    """The cap stops a rectangle, whose shape factor is 1.5, from claiming
    more reserve than the standard allows."""
    modest = as4100.effective_modulus(
        as4100.Compactness.COMPACT, 8.0, 9.0, 16.0, Z=1e6, S=1.12e6
    )
    assert modest == pytest.approx(1.12e6)

    extreme = as4100.effective_modulus(
        as4100.Compactness.COMPACT, 8.0, 9.0, 16.0, Z=1e6, S=1.8e6
    )
    assert extreme == pytest.approx(1.5e6)


def test_the_non_compact_interpolation_is_continuous_at_both_ends():
    """A discontinuity here would let a section get STRONGER by being made
    more slender, which would be visible only as a strange answer."""
    z, s = 1e6, 1.12e6
    at_plastic = as4100.effective_modulus(
        as4100.Compactness.NON_COMPACT, 9.0, 9.0, 16.0, z, s
    )
    at_yield = as4100.effective_modulus(
        as4100.Compactness.NON_COMPACT, 16.0, 9.0, 16.0, z, s
    )
    assert at_plastic == pytest.approx(min(s, 1.5 * z))
    assert at_yield == pytest.approx(z)


def test_a_welded_section_may_not_use_hot_rolled_limits():
    """Welded limits are tighter, so defaulting one to HR is unconservative."""
    from austruct.sections.steel_profile import i_section

    welded = cat.get("310UB40.4")
    welded = type(welded)(
        **{**welded.__dict__, "profile": i_section(304, 165, 10.2, 6.1, welded=True)}
    )
    with pytest.raises(ModelError, match="unconservative"):
        as4100.classify(welded, residual="HR")


def test_classification_reports_without_passing_or_failing(beam):
    """A slender section is legitimate -- it just has a lower Z_e."""
    result = as4100.check_classification(beam)
    assert result.checks == []
    assert "Ze" in result.outputs


# ---------------------------------------------------------------------------
# Section capacity
# ---------------------------------------------------------------------------


def test_section_moment_capacity_is_fy_times_Ze(beam):
    result = as4100.section_moment_capacity(beam)
    slenderness = as4100.classify(beam)
    assert result.get("Ms") == pytest.approx(beam.fy_flange * slenderness.Ze)
    assert result.get("phiMs") == pytest.approx(C.PHI * result.get("Ms"))


def test_flexure_uses_the_flange_yield_stress_not_the_web(beam):
    """The flange carries the extreme-fibre stress. The web is thinner and
    therefore stronger; using its f_y here would overstate the capacity."""
    assert beam.fy_web >= beam.fy_flange
    result = as4100.section_moment_capacity(beam)
    assert result.inputs["fy"].value == pytest.approx(beam.fy_flange)


def test_a_higher_grade_gives_more_capacity(beam):
    normal = as4100.section_moment_capacity(beam).get("Ms")
    stronger = as4100.section_moment_capacity(beam.with_grade("350")).get("Ms")
    assert stronger > normal


# ---------------------------------------------------------------------------
# The gate -- the most important behaviour in the package
# ---------------------------------------------------------------------------


def test_check_flexure_refuses_without_a_restraint_declaration(beam):
    """Returning M_s for an unrestrained beam would hand back a number that
    can be several times the real capacity, with nothing to flag it."""
    with pytest.raises(ModelError, match="fully restrained"):
        as4100.check_flexure(beam, 100 * kNm)


def test_the_refusal_points_at_the_member_check(beam):
    with pytest.raises(ModelError) as exc:
        as4100.check_flexure(beam, 100 * kNm)
    assert "check_member_flexure" in str(exc.value)


def test_a_declared_restrained_segment_is_checked(beam):
    result = as4100.check_flexure(beam, 100 * kNm, fully_restrained=True)
    assert result.checks
    assert result.passed


def test_minor_axis_bending_needs_no_restraint_declaration(beam):
    """A beam bent about its minor axis cannot buckle laterally -- there is no
    weaker axis to buckle into."""
    result = as4100.check_flexure(beam, 20 * kNm, axis="y")
    assert result.checks


# ---------------------------------------------------------------------------
# Shear
# ---------------------------------------------------------------------------


def test_shear_capacity_is_0_6_fy_times_the_web_area(beam):
    result = as4100.shear_capacity(beam)
    expected = 0.6 * beam.fy_web * beam.d * beam.tw
    assert result.get("Vv") == pytest.approx(expected)


def test_shear_uses_the_web_yield_stress(beam):
    result = as4100.shear_capacity(beam)
    assert result.inputs["fy_web"].value == pytest.approx(beam.fy_web)


def test_a_stocky_web_yields_rather_than_buckling(beam):
    """Almost every rolled UB is comfortably stocky."""
    assert as4100.web_slenderness(beam) < C.WEB_SLENDERNESS_YIELD_LIMIT
    result = as4100.shear_capacity(beam)
    assert result.get("Vv") == pytest.approx(result.get("Vw"))


def test_a_slender_web_loses_capacity_to_buckling():
    """Falls with the SQUARE of slenderness, so it drops quickly past the
    limit -- which is where plate girders live."""
    from austruct.sections.steel_profile import i_section

    beam = cat.get("310UB40.4")
    slender = type(beam)(
        **{
            **beam.__dict__,
            "d": 1200.0,
            "tw": 4.0,
            "profile": i_section(1200, 165, 10.2, 4.0),
        }
    )
    assert as4100.web_slenderness(slender) > C.WEB_SLENDERNESS_YIELD_LIMIT
    result = as4100.shear_capacity(slender)
    assert result.get("Vv") < result.get("Vw")
    assert any("SLENDER" in note for note in result.messages)


def test_the_shear_area_and_the_slenderness_use_different_depths(beam):
    """Overall depth for the area, clear depth for the slenderness. Different
    purposes, and homogenising them is an easy mistake."""
    assert as4100.web_area(beam) == pytest.approx(beam.d * beam.tw)
    clear = beam.d - 2 * beam.tf
    assert as4100.web_slenderness(beam) == pytest.approx(
        (clear / beam.tw) * math.sqrt(beam.fy_web / 250)
    )


def test_low_shear_does_not_reduce_the_moment_capacity(beam):
    result = as4100.check_shear_and_moment(
        beam, 50 * kN, 100 * kNm, fully_restrained=True
    )
    assert result.get("Vvm") == pytest.approx(result.get("Vv"))
    assert any("not reduced" in note for note in result.messages)


def test_high_shear_reduces_the_moment_capacity(beam):
    capacity = as4100.shear_capacity(beam).get("phiVv")
    result = as4100.check_shear_and_moment(
        beam, 0.9 * capacity, 150 * kNm, fully_restrained=True
    )
    assert result.get("Vvm") < result.get("Vv")


def test_the_combined_check_also_requires_a_restraint_declaration(beam):
    with pytest.raises(ModelError, match="fully restrained"):
        as4100.check_shear_and_moment(beam, 50 * kN, 100 * kNm)


# ---------------------------------------------------------------------------
# Restraints and effective length
# ---------------------------------------------------------------------------


def test_a_fully_restrained_segment_has_le_equal_to_L():
    seg = as4100.fully_restrained(6 * m)
    assert as4100.effective_length(seg) == pytest.approx(6 * m)


def test_a_top_flange_load_lengthens_the_effective_length():
    """The one people forget. As the beam twists, a load on the top flange
    moves outboard and drives it further -- about 40% more effective length."""
    centre = as4100.segment(6 * m, "FF", load_height="shear centre")
    top = as4100.segment(6 * m, "FF", load_height="top flange")
    assert as4100.effective_length(top) == pytest.approx(
        1.4 * as4100.effective_length(centre)
    )


def test_kt_is_refused_rather_than_guessed_for_partial_restraint():
    """AS 4100 gives k_t as an expression in the section geometry, not a
    constant. Defaulting to 1.0 would treat partial restraint as full."""
    with pytest.raises(ModelError, match="will not guess"):
        as4100.effective_length(as4100.segment(6 * m, "FP"))


def test_a_supplied_kt_is_used():
    seg = as4100.segment(6 * m, "FP", kt=1.15)
    assert as4100.effective_length(seg) == pytest.approx(1.15 * 6 * m)


def test_kt_below_one_refuses():
    """k_t lengthens the effective length; it never shortens it."""
    with pytest.raises(ModelError, match="at least 1.0"):
        as4100.segment(6 * m, "FP", kt=0.9)


def test_a_bad_restraint_code_explains_the_letters():
    with pytest.raises(ModelError, match="two letters"):
        as4100.segment(6 * m, "FFF")
    with pytest.raises(ModelError, match="Valid letters"):
        as4100.segment(6 * m, "XY")


def test_lateral_rotation_restraint_shortens_the_effective_length():
    plain = as4100.segment(6 * m, "FF")
    restrained = as4100.segment(6 * m, "FF", kr=0.85)
    assert as4100.effective_length(restrained) < as4100.effective_length(plain)


# ---------------------------------------------------------------------------
# Lateral-torsional buckling -- the check that governs
# ---------------------------------------------------------------------------


def test_member_capacity_falls_away_with_length(beam):
    """The defining behaviour. A beam that reports the same capacity at 12 m as
    at 1 m has not had its buckling check done."""
    capacities = [
        as4100.buckling_state(beam, as4100.fully_restrained(L * m)).Mb
        for L in (1, 2, 4, 8, 12)
    ]
    assert capacities == sorted(capacities, reverse=True)
    assert capacities[-1] < 0.25 * capacities[0]


def test_a_short_segment_reaches_the_section_capacity(beam):
    state = as4100.buckling_state(beam, as4100.fully_restrained(0.5 * m))
    assert state.reduction > 0.95
    assert state.governed_by_section


def test_member_capacity_never_exceeds_the_section_capacity(beam):
    """M_b <= M_s, even with a generous alpha_m."""
    state = as4100.buckling_state(
        beam, as4100.fully_restrained(0.5 * m), alpha_m=2.5
    )
    assert state.Mb <= state.Ms * (1 + 1e-9)


def test_the_buckling_moment_has_both_torsion_and_warping_terms(beam):
    """M_o = sqrt[(pi^2 E Iy/le^2)(GJ + pi^2 E Iw/le^2)]. Warping falls away
    with length squared, so it dominates short segments and vanishes on long
    ones -- which means M_o must fall FASTER than 1/le at short lengths."""
    short = as4100.reference_buckling_moment(beam, 1000.0)
    doubled = as4100.reference_buckling_moment(beam, 2000.0)
    assert doubled < short / 2, "warping should make the fall steeper than 1/le"


def test_the_buckling_moment_matches_the_closed_form(beam):
    le = 6000.0
    p = beam.properties
    e, g = beam.grade.E, beam.grade.G
    expected = math.sqrt(
        (math.pi**2 * e * p.Iy / le**2)
        * (g * p.J + math.pi**2 * e * p.Iw / le**2)
    )
    assert as4100.reference_buckling_moment(beam, le) == pytest.approx(expected)


def test_alpha_s_is_bounded_above_by_one():
    """A member can never be stronger than its own section."""
    assert as4100.slenderness_reduction(100e6, 1e12) == pytest.approx(1.0)


def test_alpha_s_falls_as_the_buckling_moment_falls():
    strong = as4100.slenderness_reduction(100e6, 1000e6)
    weak = as4100.slenderness_reduction(100e6, 20e6)
    assert strong > weak


def test_uniform_moment_gives_alpha_m_of_about_one():
    """The reference case: the whole segment at peak, nothing to brace it.
    1.7/sqrt(3) = 0.98."""
    assert as4100.alpha_m_from_moments(100, 100, 100, 100) == pytest.approx(
        1.7 / math.sqrt(3), rel=1e-6
    )


def test_a_peaked_moment_diagram_earns_more_than_a_uniform_one():
    """The highly stressed part is short and the rest braces it."""
    uniform = as4100.alpha_m_from_moments(100, 100, 100, 100)
    udl = as4100.alpha_m_from_moments(100, 75, 100, 75)
    point = as4100.alpha_m_from_moments(100, 50, 100, 50)
    assert point > udl > uniform


def test_alpha_m_is_capped():
    assert as4100.alpha_m_from_moments(100, 1, 1, 1) == pytest.approx(C.ALPHA_M_MAX)


def test_alpha_m_comes_off_a_real_moment_diagram():
    """The integration win: the solver already produces what alpha_m needs."""
    x = np.linspace(0, 6000, 201)
    # Parabolic diagram, as a UDL on a simple span.
    moments = 100e6 * (4 * x / 6000) * (1 - x / 6000)

    from_diagram = as4100.alpha_m_from_diagram(x, moments, 0.0, 6000.0)
    by_hand = as4100.alpha_m_from_moments(100e6, 75e6, 100e6, 75e6)
    assert from_diagram == pytest.approx(by_hand, rel=1e-3)


def test_alpha_m_takes_the_peak_over_the_whole_segment():
    """A peak between the sample points must not be missed -- that would
    overstate alpha_m and the capacity."""
    x = np.linspace(0, 1000, 501)
    moments = np.where((x > 300) & (x < 400), 200e6, 50e6)
    result = as4100.alpha_m_from_diagram(x, moments, 0.0, 1000.0)
    # Peak is 200e6 even though no quarter point lands on it.
    assert result > as4100.alpha_m_from_moments(50e6, 50e6, 50e6, 50e6)


def test_a_segment_outside_the_diagram_refuses():
    x = np.linspace(0, 1000, 11)
    with pytest.raises(ModelError, match="must exceed"):
        as4100.alpha_m_from_diagram(x, x * 0, 500.0, 500.0)


def test_the_member_check_is_the_one_to_use_for_a_real_beam(beam):
    seg = as4100.fully_restrained(6 * m)
    result = as4100.check_member_flexure(beam, 60 * kNm, seg)
    assert result.checks
    assert "Mb" in result.outputs
    assert result.get("Mb") < result.get("Ms")


def test_a_beam_that_passes_the_section_check_can_fail_the_member_check(beam):
    """The whole reason S6 exists."""
    demand = 120 * kNm
    section_ok = as4100.check_flexure(beam, demand, fully_restrained=True)
    member = as4100.check_member_flexure(
        beam, demand, as4100.fully_restrained(8 * m)
    )
    assert section_ok.passed
    assert not member.passed


def test_the_default_alpha_m_is_flagged_as_conservative(beam):
    result = as4100.member_moment_capacity(beam, as4100.fully_restrained(6 * m))
    assert any("CONSERVATIVE" in note for note in result.messages)


def test_the_thin_walled_torsion_constant_is_flagged(beam):
    result = as4100.member_moment_capacity(beam, as4100.fully_restrained(6 * m))
    assert any("root radii" in note for note in result.messages)


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------


@pytest.fixture
def column():
    return cat.get("200UC46.2")


def test_section_compression_capacity_is_kf_times_area_times_fy(column):
    result = as4100.section_compression_capacity(column)
    expected = result.get("kf") * column.properties.A * column.fy_flange
    assert result.get("Ns") == pytest.approx(expected)


def test_a_rolled_section_has_a_form_factor_of_one(column):
    """Rolled sections are compact in compression too, so nothing is
    discounted."""
    assert as4100.form_factor(column) == pytest.approx(1.0)


def test_member_compression_capacity_falls_away_with_length(column):
    capacities = [
        as4100.member_compression_capacity(column, L * m).get("Nc")
        for L in (0.5, 2, 4, 6, 9)
    ]
    assert capacities == sorted(capacities, reverse=True)
    assert capacities[-1] < 0.25 * capacities[0]


def test_a_stub_column_reaches_its_squash_load(column):
    result = as4100.member_compression_capacity(column, 200.0)
    assert result.get("Nc") == pytest.approx(result.get("Ns"), rel=0.02)


def test_compression_member_capacity_never_exceeds_the_section_capacity(column):
    for L in (0.1, 1, 5, 10):
        result = as4100.member_compression_capacity(column, L * m)
        assert result.get("Nc") <= result.get("Ns") * (1 + 1e-9)


def test_the_minor_axis_governs_unless_it_is_braced(column):
    """Which is why axis defaults to 'y' -- defaulting to the major axis would
    be unconservative."""
    major = as4100.member_compression_capacity(column, 4 * m, axis="x", alpha_b=0.0)
    minor = as4100.member_compression_capacity(column, 4 * m, axis="y", alpha_b=0.5)
    assert minor.get("Nc") < major.get("Nc")


def test_alpha_b_matters_and_lower_is_better(column):
    good = as4100.compression_factor(80.0, alpha_b=0.0)
    bad = as4100.compression_factor(80.0, alpha_b=1.0)
    assert good > bad


def test_the_compression_factor_is_bounded_by_one():
    assert as4100.compression_factor(1.0, 0.5) <= 1.0
    assert as4100.compression_factor(0.0, 0.5) == pytest.approx(1.0)


def test_modified_slenderness_carries_grade_and_form_factor():
    base = as4100.modified_slenderness(4000, 50, 1.0, 250)
    stronger = as4100.modified_slenderness(4000, 50, 1.0, 320)
    assert stronger > base
    assert base == pytest.approx(4000 / 50)


def test_a_zero_radius_of_gyration_refuses():
    with pytest.raises(ModelError, match="Radius of gyration"):
        as4100.modified_slenderness(4000, 0, 1.0, 300)


def test_compression_check_flags_the_missing_torsional_mode(column):
    result = as4100.check_compression(column, 500 * kN, 4 * m)
    assert any("flexural-torsional" in note for note in result.messages)


# ---------------------------------------------------------------------------
# Combined actions
# ---------------------------------------------------------------------------


def test_a_small_axial_force_costs_no_moment_capacity(column):
    """The 1.18 factor is still capped at M_s below about 15% of the squash
    load, so the axial force is free."""
    ms = as4100.section_moment_capacity(column).get("Ms")
    phi_ns = C.PHI * as4100.section_compression_capacity(column).get("Ns")

    assert as4100.reduced_section_moment_capacity(ms, 0.0, phi_ns) == pytest.approx(ms)
    assert as4100.reduced_section_moment_capacity(
        ms, 0.10 * phi_ns, phi_ns
    ) == pytest.approx(ms)


def test_a_large_axial_force_does_reduce_the_moment_capacity(column):
    ms = as4100.section_moment_capacity(column).get("Ms")
    phi_ns = C.PHI * as4100.section_compression_capacity(column).get("Ns")
    reduced = as4100.reduced_section_moment_capacity(ms, 0.6 * phi_ns, phi_ns)
    assert reduced < 0.6 * ms


def test_the_reduced_capacity_is_never_negative(column):
    ms = as4100.section_moment_capacity(column).get("Ms")
    phi_ns = C.PHI * as4100.section_compression_capacity(column).get("Ns")
    assert as4100.reduced_section_moment_capacity(ms, 2.0 * phi_ns, phi_ns) == 0.0


def test_the_combined_section_check_covers_both_actions(column):
    result = as4100.check_combined_section(column, 400 * kN, 60 * kNm)
    labels = [c.label for c in result.checks]
    assert any("N*" in label for label in labels)
    assert any("M*" in label for label in labels)


def test_two_checks_each_under_100_percent_can_still_fail_combined(column):
    """The whole reason combined actions exist: 70% plus 70% is not 70%."""
    ns = as4100.section_compression_capacity(column).get("Ns")
    seg = as4100.fully_restrained(4 * m)
    mb = as4100.member_moment_capacity(column, seg).get("phiMb")
    nc = as4100.member_compression_capacity(column, 4 * m).get("phiNc")

    n_star = 0.7 * nc
    m_star = 0.7 * mb

    assert n_star < nc
    assert m_star < mb

    combined = as4100.check_combined_member(column, n_star, m_star, seg, 4 * m)
    assert combined.get("interaction") == pytest.approx(1.4, rel=0.01)
    assert not combined.passed
    _ = ns


def test_the_two_effective_lengths_are_separate_inputs(column):
    """Bracing that restrains a beam against lateral-torsional buckling is
    often not the bracing that holds a column."""
    seg = as4100.fully_restrained(2 * m)
    braced = as4100.check_combined_member(column, 300 * kN, 30 * kNm, seg, 2 * m)
    unbraced = as4100.check_combined_member(column, 300 * kN, 30 * kNm, seg, 8 * m)
    assert unbraced.get("interaction") > braced.get("interaction")


def test_the_linear_interaction_is_flagged_as_conservative(column):
    result = as4100.check_combined_member(
        column, 200 * kN, 20 * kNm, as4100.fully_restrained(3 * m), 3 * m
    )
    assert any("conservative" in note.lower() for note in result.messages)
