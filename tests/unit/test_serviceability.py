"""Tests for deflection and crack control.

The strategy is the same as the analysis tests: check against something an
engineer would verify by hand. For serviceability that means the bounding
cases -- an uncracked section must give the uncracked stiffness, a heavily
cracked one must approach the cracked stiffness, and the interpolation must be
monotonic between them.
"""

from __future__ import annotations

import pytest

from austruct.core.exceptions import ModelError
from austruct.core.units import MPa, kNm, m, mm
from austruct.design import as3600, as5100_5
from austruct.design.rc_common.serviceability import (
    creep_multiplier,
    long_term_deflection,
    scale_deflection_for_stiffness,
    service_steel_stress,
)
from austruct.materials import concrete
from austruct.sections import (
    cracked_properties,
    cracking_moment,
    layer_layout,
    max_bars_in_width,
    rc_beam,
    uncracked_properties,
)

SPAN = 8.0 * m


@pytest.fixture
def beam_section():
    """A 300x600 beam, 4-N24 bottom -- normally reinforced, p above 0.005."""
    return rc_beam(
        b=300, D=600, concrete=concrete(32), cover=40,
        n_bars=4, diameter=24, fitment_diameter=12, fitment_spacing=200,
        name="B1",
    )


@pytest.fixture
def lightly_reinforced():
    """Same beam with 2-N12 -- p below the 0.005 threshold."""
    return rc_beam(
        b=300, D=600, concrete=concrete(32), cover=40,
        n_bars=2, diameter=12, fitment_diameter=12, fitment_spacing=200,
        name="B2",
    )


# ---------------------------------------------------------------------------
# Effective second moment of area
# ---------------------------------------------------------------------------


def test_below_cracking_the_section_is_uncracked(beam_section):
    """The interpolation must not be evaluated below M_cr -- (M_cr/M_s)^3 > 1
    there, which would give a stiffness above the uncracked value."""
    m_cr = cracking_moment(beam_section)
    state = as3600.effective_stiffness(beam_section, 0.5 * m_cr)

    assert not state.cracked
    assert state.I_ef == pytest.approx(state.I_uncracked)
    assert state.I_ef <= state.I_uncracked


def test_at_the_cracking_moment_the_stiffness_is_still_uncracked(beam_section):
    m_cr = cracking_moment(beam_section)
    state = as3600.effective_stiffness(beam_section, m_cr)
    assert state.I_ef == pytest.approx(state.I_uncracked)


def test_far_above_cracking_the_stiffness_approaches_the_cracked_value(beam_section):
    m_cr = cracking_moment(beam_section)
    state = as3600.effective_stiffness(beam_section, 50.0 * m_cr)
    # (1/50)^3 = 8e-6, so I_ef should be within a whisker of I_cr.
    assert state.I_ef == pytest.approx(state.I_cracked, rel=1e-3)
    assert state.cracked


def test_ief_is_monotonic_in_the_applied_moment(beam_section):
    """More load can never leave a member stiffer."""
    m_cr = cracking_moment(beam_section)
    previous = float("inf")
    for factor in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0):
        state = as3600.effective_stiffness(beam_section, factor * m_cr)
        assert state.I_ef <= previous + 1e-6
        previous = state.I_ef


def test_ief_is_bracketed_by_the_cracked_and_uncracked_values(beam_section):
    m_cr = cracking_moment(beam_section)
    state = as3600.effective_stiffness(beam_section, 2.0 * m_cr)
    assert state.I_cracked < state.I_ef < state.I_uncracked


def test_branson_interpolation_matches_the_hand_formula(beam_section):
    """I_ef = I_cr + (I - I_cr)(M_cr/M_s)^3, evaluated independently."""
    m_cr = cracking_moment(beam_section)
    m_s = 2.5 * m_cr
    icr = cracked_properties(beam_section).I
    iun = uncracked_properties(beam_section).I

    expected = icr + (iun - icr) * (m_cr / m_s) ** 3
    state = as3600.effective_stiffness(beam_section, m_s)
    assert state.I_ef == pytest.approx(expected)


def test_light_reinforcement_attracts_the_reduced_cap(beam_section, lightly_reinforced):
    """p < 0.005 caps I_ef at 0.6 I rather than I."""
    heavy_cap, p_heavy = as3600.ief_max(
        beam_section, uncracked_properties(beam_section).I
    )
    light_cap, p_light = as3600.ief_max(
        lightly_reinforced, uncracked_properties(lightly_reinforced).I
    )

    assert p_heavy >= 0.005 > p_light
    assert heavy_cap == pytest.approx(uncracked_properties(beam_section).I)
    assert light_cap == pytest.approx(
        0.6 * uncracked_properties(lightly_reinforced).I
    )


def test_shrinkage_reduces_the_cracking_moment_and_the_stiffness(beam_section):
    """Shrinkage puts the section into tension before any load arrives."""
    plain = as3600.effective_stiffness(beam_section, 200 * kNm, sigma_cs=0.0)
    shrunk = as3600.effective_stiffness(beam_section, 200 * kNm, sigma_cs=1.5 * MPa)

    assert shrunk.M_cr < plain.M_cr
    assert shrunk.I_ef < plain.I_ef


def test_ief_never_falls_below_the_cracked_value(lightly_reinforced):
    """The 0.6 cap must not be allowed to push I_ef below I_cr, which would be
    a member softer than its own cracked section."""
    state = as3600.effective_stiffness(lightly_reinforced, 500 * kNm)
    assert state.I_ef >= state.I_cracked


# ---------------------------------------------------------------------------
# Steel stress
# ---------------------------------------------------------------------------


def test_steel_stress_matches_the_cracked_section_formula(beam_section):
    m_s = 150 * kNm
    props = cracked_properties(beam_section)
    expected = props.n * m_s * (beam_section.d_o - props.na_depth) / props.I
    assert service_steel_stress(beam_section, m_s, props) == pytest.approx(expected)


def test_steel_stress_is_linear_in_the_moment(beam_section):
    one = service_steel_stress(beam_section, 100 * kNm)
    two = service_steel_stress(beam_section, 200 * kNm)
    assert two == pytest.approx(2.0 * one)


def test_zero_moment_gives_zero_stress(beam_section):
    assert service_steel_stress(beam_section, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Creep and the long-term total
# ---------------------------------------------------------------------------


def test_kcs_is_2_for_a_singly_reinforced_section(beam_section):
    """No compression steel -> no creep restraint -> the full multiplier."""
    assert creep_multiplier(
        beam_section, intercept=2.0, slope=1.2, minimum=0.8
    ) == pytest.approx(2.0)


def test_compression_steel_reduces_creep():
    doubly = rc_beam(
        b=300, D=600, concrete=concrete(32), cover=40,
        n_bars=4, diameter=24, n_top_bars=4, top_diameter=24,
        fitment_diameter=12, fitment_spacing=200,
    )
    kcs = creep_multiplier(doubly, intercept=2.0, slope=1.2, minimum=0.8)
    # Asc/Ast = 1.0 -> 2 - 1.2 = 0.8
    assert kcs == pytest.approx(0.8)


def test_kcs_is_floored():
    """A large slope on a section that HAS compression steel must not drive the
    multiplier below the floor. The section must be doubly reinforced for the
    slope term to bite at all -- with A_sc = 0 the floor is unreachable."""
    doubly = rc_beam(
        b=300, D=600, concrete=concrete(32), cover=40,
        n_bars=4, diameter=24, n_top_bars=4, top_diameter=24,
        fitment_diameter=12, fitment_spacing=200,
    )
    assert doubly.Asc > 0
    assert creep_multiplier(
        doubly, intercept=2.0, slope=99.0, minimum=0.8
    ) == pytest.approx(0.8)


def test_long_term_total_applies_creep_only_to_the_sustained_part():
    parts = long_term_deflection(
        delta_sustained_immediate=10.0, delta_transient=4.0, kcs=2.0
    )
    assert parts["immediate"] == pytest.approx(14.0)
    assert parts["creep"] == pytest.approx(20.0)  # 2.0 x 10, not 2.0 x 14
    assert parts["total"] == pytest.approx(34.0)


def test_deflection_scales_inversely_with_stiffness():
    assert scale_deflection_for_stiffness(10.0, I_gross=2e9, I_ef=1e9) == pytest.approx(20.0)
    assert scale_deflection_for_stiffness(10.0, I_gross=1e9, I_ef=1e9) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# The deflection check
# ---------------------------------------------------------------------------


def test_deflection_check_produces_a_contract_result(beam_section):
    result = as3600.check_deflection(
        beam_section, span=SPAN,
        delta_sustained=8.0 * mm, delta_transient=3.0 * mm,
        M_s_max=180 * kNm,
    )
    assert result.name
    assert result.checks
    assert "I_ef" in result.outputs
    assert "delta_total" in result.outputs
    assert not result.provenance.issuable, "module is unverified"


def test_a_stiff_beam_passes_and_a_flexible_one_fails(beam_section):
    stiff = as3600.check_deflection(
        beam_section, span=SPAN,
        delta_sustained=2.0 * mm, delta_transient=1.0 * mm,
        M_s_max=100 * kNm,
    )
    flexible = as3600.check_deflection(
        beam_section, span=SPAN,
        delta_sustained=40.0 * mm, delta_transient=10.0 * mm,
        M_s_max=300 * kNm,
    )
    assert stiff.passed
    assert not flexible.passed
    assert flexible.utilisation > 1.0


def test_total_deflection_limit_is_span_over_the_ratio(beam_section):
    result = as3600.check_deflection(
        beam_section, span=SPAN,
        delta_sustained=5.0 * mm, delta_transient=2.0 * mm,
        M_s_max=150 * kNm, total_limit_ratio=250.0,
    )
    check = next(c for c in result.checks if "Total" in c.label)
    assert check.limit == pytest.approx(SPAN / 250.0)


def test_cantilever_doubles_the_span_used_in_the_limit(beam_section):
    plain = as3600.check_deflection(
        beam_section, span=SPAN, delta_sustained=5 * mm, delta_transient=0.0,
        M_s_max=150 * kNm,
    )
    canti = as3600.check_deflection(
        beam_section, span=SPAN, delta_sustained=5 * mm, delta_transient=0.0,
        M_s_max=150 * kNm, cantilever=True,
    )
    plain_limit = next(c for c in plain.checks if "Total" in c.label).limit
    canti_limit = next(c for c in canti.checks if "Total" in c.label).limit
    assert canti_limit == pytest.approx(2.0 * plain_limit)


def test_incremental_check_is_added_only_when_asked(beam_section):
    without = as3600.check_deflection(
        beam_section, span=SPAN, delta_sustained=5 * mm, delta_transient=2 * mm,
        M_s_max=150 * kNm,
    )
    with_inc = as3600.check_deflection(
        beam_section, span=SPAN, delta_sustained=5 * mm, delta_transient=2 * mm,
        M_s_max=150 * kNm, incremental_limit_ratio=500.0,
    )
    assert len(with_inc.checks) == len(without.checks) + 1
    assert "delta_incremental" in with_inc.outputs


def test_deflection_before_finishes_is_deducted_from_the_increment(beam_section):
    result = as3600.check_deflection(
        beam_section, span=SPAN, delta_sustained=10 * mm, delta_transient=0.0,
        M_s_max=150 * kNm, incremental_limit_ratio=500.0,
        delta_before_finishes=4.0 * mm,
    )
    total = result.get("delta_total")
    increment = result.get("delta_incremental")
    assert increment < total


def test_zero_shrinkage_is_flagged_as_unconservative(beam_section):
    result = as3600.check_deflection(
        beam_section, span=SPAN, delta_sustained=5 * mm, delta_transient=0.0,
        M_s_max=150 * kNm,
    )
    assert any("UNCONSERVATIVE" in note for note in result.messages)


def test_a_bad_span_raises(beam_section):
    with pytest.raises(ModelError, match="Span"):
        as3600.check_deflection(
            beam_section, span=0.0, delta_sustained=1.0, delta_transient=0.0,
            M_s_max=100 * kNm,
        )


# ---------------------------------------------------------------------------
# Crack control
# ---------------------------------------------------------------------------


def test_crack_control_reports_the_steel_stress(beam_section):
    result = as3600.check_crack_control(beam_section, 120 * kNm, cover=40, fitment_diameter=12)
    assert result.get("f_s") > 0
    assert result.checks


def test_low_stress_permits_a_large_bar(beam_section):
    """At a low service stress the table allows the biggest bars."""
    low = as3600.check_crack_control(beam_section, 40 * kNm, cover=40, fitment_diameter=12)
    assert low.get("max_bar_diameter") >= 32.0


def test_high_stress_restricts_the_bar_diameter(beam_section):
    low = as3600.check_crack_control(beam_section, 40 * kNm, cover=40, fitment_diameter=12)
    high = as3600.check_crack_control(beam_section, 260 * kNm, cover=40, fitment_diameter=12)
    assert high.get("max_bar_diameter") < low.get("max_bar_diameter")


def test_stress_beyond_the_table_fails_rather_than_extrapolating(beam_section):
    """The deemed-to-comply route simply does not extend past the last row."""
    result = as3600.check_crack_control(beam_section, 900 * kNm, cover=40, fitment_diameter=12)
    assert result.get("max_bar_diameter") == 0.0
    assert not result.passed
    assert any("beyond the end" in note for note in result.messages)


def test_spacing_check_is_omitted_when_it_cannot_be_derived(beam_section):
    result = as3600.check_crack_control(beam_section, 120 * kNm)
    assert any("SPACING CHECK HAS BEEN OMITTED" in note for note in result.messages)
    assert not any("spacing" in c.label for c in result.checks)


def test_explicit_spacing_is_used_when_given(beam_section):
    result = as3600.check_crack_control(beam_section, 120 * kNm, bar_spacing=150.0)
    assert any("spacing" in c.label for c in result.checks)
    assert result.inputs["bar_spacing"].value == pytest.approx(150.0)


def test_wide_spacing_fails_the_check(beam_section):
    tight = as3600.check_crack_control(beam_section, 120 * kNm, bar_spacing=90.0)
    wide = as3600.check_crack_control(beam_section, 120 * kNm, bar_spacing=400.0)
    spacing_check = next(c for c in wide.checks if "spacing" in c.label)
    assert not spacing_check.passed
    assert next(c for c in tight.checks if "spacing" in c.label).passed


def test_section_without_reinforcement_refuses():
    plain = rc_beam(b=300, D=600, concrete=concrete(32))
    with pytest.raises((ModelError, ValueError)):
        as3600.check_crack_control(plain, 50 * kNm)


# ---------------------------------------------------------------------------
# Bar layout geometry
# ---------------------------------------------------------------------------


def test_bar_layout_spacing_matches_hand_arithmetic():
    """300 wide, 40 cover, 12 fitment, 4-N24.

    Available between fitments = 300 - 2(40+12) = 196.
    Centres span 196 - 24 = 172, over 3 gaps -> 57.33 c/c, clear 33.33.
    """
    layout = layer_layout(width=300, n_bars=4, diameter=24, cover=40, fitment_diameter=12)
    assert layout.available_width == pytest.approx(196.0)
    assert layout.centre_spacing == pytest.approx(172.0 / 3.0)
    assert layout.clear_spacing == pytest.approx(172.0 / 3.0 - 24.0)
    assert layout.fits


def test_too_many_bars_reports_a_negative_clear_gap():
    layout = layer_layout(width=300, n_bars=12, diameter=24, cover=40, fitment_diameter=12)
    assert not layout.fits
    assert layout.clear_spacing < 0


def test_a_single_bar_has_no_spacing():
    layout = layer_layout(width=300, n_bars=1, diameter=24, cover=40, fitment_diameter=12)
    assert layout.centre_spacing == float("inf")
    assert layout.edge_distance == pytest.approx(150.0)


def test_max_bars_respects_the_minimum_clear_gap():
    n = max_bars_in_width(width=300, diameter=24, cover=40, fitment_diameter=12,
                          min_clear_spacing=25.0)
    layout = layer_layout(300, n, 24, 40, 12)
    assert layout.clear_spacing >= 25.0
    over = layer_layout(300, n + 1, 24, 40, 12)
    assert over.clear_spacing < 25.0


def test_no_bars_fit_in_a_narrow_section():
    assert max_bars_in_width(width=80, diameter=32, cover=40, fitment_diameter=12) == 0


# ---------------------------------------------------------------------------
# AS 5100.5 serviceability -- the bridge route
# ---------------------------------------------------------------------------


def test_bridge_stress_limit_tightens_with_exposure():
    """A coastal structure must not be checked against an inland limit."""
    assert as5100_5.steel_stress_limit("A1") > as5100_5.steel_stress_limit("B2")
    assert as5100_5.steel_stress_limit("B2") >= as5100_5.steel_stress_limit("C2")


def test_unknown_exposure_refuses_and_lists_the_options():
    with pytest.raises(KeyError) as exc:
        as5100_5.steel_stress_limit("Z9")
    assert "B2" in str(exc.value)


def test_exposure_lookup_is_case_insensitive():
    assert as5100_5.steel_stress_limit("b2") == as5100_5.steel_stress_limit("B2")


def test_bridge_steel_stress_check(beam_section):
    result = as5100_5.check_steel_stress(beam_section, 120 * kNm, "B2")
    assert result.get("f_s") > 0
    assert result.checks


def test_severe_exposure_can_fail_what_mild_exposure_passes(beam_section):
    mild = as5100_5.check_steel_stress(beam_section, 190 * kNm, "A1")
    severe = as5100_5.check_steel_stress(beam_section, 190 * kNm, "C2")
    assert severe.utilisation > mild.utilisation


def test_bridge_and_building_stiffness_agree_mechanically(beam_section):
    """Same mechanics, different constants -- with the constants currently
    equal, the two must give the same I_ef. If they ever diverge, one of the
    two constant sets has been changed and the other has not."""
    a = as3600.effective_stiffness(beam_section, 200 * kNm)
    b = as5100_5.effective_stiffness(beam_section, 200 * kNm)
    assert a.I_ef == pytest.approx(b.I_ef)


def test_concrete_stress_check_is_conservative_on_the_cracked_section(beam_section):
    result = as5100_5.check_concrete_stress(beam_section, 150 * kNm)
    assert result.get("f_c") > 0
    assert result.checks[0].limit == pytest.approx(0.4 * beam_section.concrete.fc)


def test_missing_bar_spacing_is_flagged_not_silently_skipped(beam_section):
    result = as5100_5.check_steel_stress(beam_section, 120 * kNm, "B2")
    assert any("NOT" in note and "spacing" in note for note in result.messages)
