"""Tests for pattern loading and moment redistribution.

The anchor for pattern loading is the set of classic coefficients for equal
continuous spans, which every engineer knows: about 0.080 wL^2 sagging and
0.100 wL^2 hogging for three equal spans fully loaded. Patterning must never
produce LESS than that -- the fully loaded arrangement is one of the patterns,
so the envelope can only grow.

That last property is the one worth testing hardest. A bug in the restriction
logic shows up as an envelope that shrinks, and the number still looks
perfectly plausible.
"""

from __future__ import annotations

import numpy as np
import pytest

from austruct.analysis import (
    UDL,
    PartialUDL,
    PointLoad,
    VaryingUDL,
    analyse_combinations,
    continuous,
    redistribute,
    simply_supported,
    verify_equilibrium,
)
from austruct.analysis.loading import SelfWeight
from austruct.core.exceptions import ModelError
from austruct.core.units import kN, kN_per_m, m
from austruct.loads import (
    ActionType,
    LoadCase,
    LoadPattern,
    adjacent_pair,
    alternate_spans,
    analyse_patterns,
    apply_pattern,
    as1170_uls,
    patterned_case_sets,
    restrict_load,
    span_extents,
    standard_patterns,
)

L = 8.0 * m


@pytest.fixture
def three_span():
    return continuous((L, L, L), EI=1e14, name="CB1")


@pytest.fixture
def cases():
    return (
        LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),)),
        LoadCase("Q", ActionType.Q, (UDL(magnitude=15 * kN_per_m),)),
    )


# ---------------------------------------------------------------------------
# Restricting a load
# ---------------------------------------------------------------------------


def test_a_full_udl_becomes_a_partial_udl():
    piece = restrict_load(UDL(magnitude=10.0, length=24000.0), 8000.0, 16000.0)
    assert isinstance(piece, PartialUDL)
    assert piece.start == 8000.0
    assert piece.end == 16000.0
    assert piece.magnitude == 10.0


def test_an_unattached_udl_refuses_rather_than_vanishing():
    """Regression, and the most dangerous bug this module can have.

    A UDL built outside a Beam has length = 0. Restricting it used to return
    None for every span, which silently deleted the entire live load -- the
    patterned answer came back as dead load alone and looked perfectly
    plausible.
    """
    unattached = UDL(magnitude=10.0)  # no length
    assert unattached.length == 0.0

    with pytest.raises(ModelError, match="unknown extent"):
        restrict_load(unattached, 0.0, 8000.0)

    # With the member length supplied it works.
    piece = restrict_load(unattached, 0.0, 8000.0, member_length=24000.0)
    assert isinstance(piece, PartialUDL)
    assert piece.magnitude == 10.0


def test_self_weight_restricts_like_a_udl():
    sw = SelfWeight(area=300 * 600, length=24000.0)
    piece = restrict_load(sw, 0.0, 8000.0)
    assert isinstance(piece, PartialUDL)
    assert piece.magnitude == pytest.approx(sw.magnitude)


def test_a_partial_udl_is_clipped_to_the_overlap():
    load = PartialUDL(start=5000.0, end=20000.0, magnitude=10.0)
    piece = restrict_load(load, 8000.0, 16000.0)
    assert piece.start == 8000.0
    assert piece.end == 16000.0


def test_a_load_outside_the_interval_returns_none():
    load = PartialUDL(start=0.0, end=4000.0, magnitude=10.0)
    assert restrict_load(load, 8000.0, 16000.0) is None


def test_a_point_load_is_kept_only_if_it_lies_inside():
    inside = PointLoad(position=10000.0, magnitude=50 * kN)
    outside = PointLoad(position=2000.0, magnitude=50 * kN)
    assert restrict_load(inside, 8000.0, 16000.0) is inside
    assert restrict_load(outside, 8000.0, 16000.0) is None


def test_a_varying_udl_is_re_interpolated_not_just_clipped():
    """Clipping the extent without recomputing the end intensities would
    change the load's slope and invent load."""
    load = VaryingUDL(start=0.0, end=10000.0, w_start=0.0, w_end=100.0)
    piece = restrict_load(load, 2000.0, 6000.0)
    assert piece.w_start == pytest.approx(20.0)
    assert piece.w_end == pytest.approx(60.0)


def test_an_unknown_load_type_refuses():
    class Weird(UDL):
        pass

    # A subclass of UDL still matches the UDL branch, so build something that
    # is a Load but none of the known types.
    from austruct.analysis.loading import Load

    class Unknown(Load):
        def mesh_points(self):
            return []

        def intensity(self, x):
            return 0.0

        def point_forces(self):
            return []

        def point_moments(self):
            return []

        def resultant_left_of(self, x):
            return 0.0, 0.0

        def total(self):
            return 0.0

    with pytest.raises(ModelError, match="does not know how to restrict"):
        restrict_load(Unknown(), 0.0, 1000.0)


def test_a_reversed_interval_refuses():
    with pytest.raises(ModelError, match="must exceed"):
        restrict_load(UDL(magnitude=10.0, length=1000.0), 500.0, 500.0)


# ---------------------------------------------------------------------------
# The patterns themselves
# ---------------------------------------------------------------------------


def test_span_extents_from_supports():
    assert span_extents((0.0, 8000.0, 16000.0)) == ((0.0, 8000.0), (8000.0, 16000.0))


def test_a_single_support_is_not_a_continuous_member():
    with pytest.raises(ModelError, match="at least two"):
        span_extents((0.0,))


def test_alternate_patterns_are_complementary():
    odd = alternate_spans(4, start_loaded=True)
    even = alternate_spans(4, start_loaded=False)
    assert odd.loaded == (True, False, True, False)
    assert even.loaded == (False, True, False, True)
    assert all(a != b for a, b in zip(odd.loaded, even.loaded))


def test_adjacent_pair_loads_the_two_spans_either_side():
    assert adjacent_pair(3, 1).loaded == (True, True, False)
    assert adjacent_pair(3, 2).loaded == (False, True, True)


def test_an_end_support_is_not_an_interior_one():
    with pytest.raises(ModelError, match="interior support"):
        adjacent_pair(3, 3)
    with pytest.raises(ModelError, match="interior support"):
        adjacent_pair(3, 0)


def test_standard_set_covers_all_spans_and_every_interior_support():
    patterns = standard_patterns(4)
    names = [p.name for p in patterns]
    assert "all spans" in names
    assert "alternate odd" in names and "alternate even" in names
    assert sum("pair at support" in n for n in names) == 3


def test_a_single_span_has_nothing_to_pattern():
    patterns = standard_patterns(1)
    assert len(patterns) == 1
    assert patterns[0].loaded == (True,)


def test_pattern_str_is_readable():
    assert "X.X" in str(alternate_spans(3, start_loaded=True))


# ---------------------------------------------------------------------------
# Applying a pattern to a case
# ---------------------------------------------------------------------------


def test_apply_pattern_keeps_only_the_loaded_spans():
    spans = span_extents((0.0, 8000.0, 16000.0, 24000.0))
    case = LoadCase("Q", ActionType.Q, (UDL(magnitude=10.0, length=24000.0),))
    patterned = apply_pattern(case, alternate_spans(3, True), spans)

    assert len(patterned.loads) == 2  # spans 1 and 3
    assert patterned.action is ActionType.Q
    assert "alternate odd" in patterned.name
    total = sum(load.total() for load in patterned.loads)
    assert total == pytest.approx(10.0 * 16000.0)


def test_a_pattern_built_for_another_member_refuses():
    spans = span_extents((0.0, 8000.0, 16000.0))
    case = LoadCase("Q", ActionType.Q, (UDL(magnitude=10.0, length=16000.0),))
    with pytest.raises(ModelError, match="different member"):
        apply_pattern(case, LoadPattern("x", (True,) * 5), spans)


def test_permanent_actions_are_never_patterned(cases):
    """Self weight does not go away when the live load does. Patterning it
    would model a beam with sections of itself missing."""
    spans = span_extents((0.0, 8000.0, 16000.0, 24000.0))
    sets = patterned_case_sets(
        cases, standard_patterns(3), spans, member_length=24000.0
    )
    original = next(c for c in cases if c.action is ActionType.G)
    for _, built in sets:
        permanent = [c for c in built if c.action is ActionType.G]
        assert len(permanent) == 1
        # Passed through by identity, not rebuilt: the name carries no pattern
        # tag and the loads are the very same objects.
        assert permanent[0] is original
        assert permanent[0].name == "G"
        assert permanent[0].loads == original.loads

    # And the live case IS rearranged, so the two are genuinely treated
    # differently rather than everything being passed through.
    imposed_counts = {
        name: len([c for c in built if c.action is ActionType.Q])
        for name, built in sets
    }
    assert all(n == 1 for n in imposed_counts.values())
    alternate = dict(sets)["alternate odd"]
    live = next(c for c in alternate if c.action is ActionType.Q)
    assert live is not next(c for c in cases if c.action is ActionType.Q)
    assert sum(load.total() for load in live.loads) == pytest.approx(
        15 * kN_per_m * 16000.0
    )


# ---------------------------------------------------------------------------
# Analysing with patterns
# ---------------------------------------------------------------------------


def test_unpatterned_matches_the_classic_coefficients(three_span, cases):
    """Three equal spans, fully loaded: about 0.080 wL^2 and 0.100 wL^2."""
    env = analyse_combinations(three_span, cases, as1170_uls())
    w = 1.2 * 20 * kN_per_m + 1.5 * 15 * kN_per_m
    assert env.M_star_sagging == pytest.approx(0.080 * w * L**2, rel=0.02)
    assert env.M_star_hogging == pytest.approx(-0.100 * w * L**2, rel=0.02)


def test_patterning_can_only_increase_the_envelope(three_span, cases):
    """The fully loaded arrangement is one of the patterns, so the patterned
    envelope contains the unpatterned one. This is the test that catches a
    restriction bug -- a shrinking envelope still looks plausible."""
    plain = analyse_combinations(three_span, cases, as1170_uls())
    patterned = analyse_patterns(three_span, cases, as1170_uls())

    assert patterned.M_star_sagging >= plain.M_star_sagging - 1.0
    assert patterned.M_star_hogging <= plain.M_star_hogging + 1.0


def test_patterning_actually_finds_something_worse(three_span, cases):
    """If it never found anything worse, there would be no point doing it."""
    plain = analyse_combinations(three_span, cases, as1170_uls())
    patterned = analyse_patterns(three_span, cases, as1170_uls())
    assert patterned.M_star_sagging > plain.M_star_sagging * 1.05


def test_the_governing_label_names_both_combination_and_pattern(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    label = env.moment.max_combo[env.moment.peak_max_index]
    assert "[" in label and "]" in label
    assert any(k in label for k in ("ULS1", "ULS2", "ULS"))


def test_alternate_spans_governs_the_sagging(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    assert "alternate" in env.moment.max_combo[env.moment.peak_max_index]


def test_adjacent_pair_governs_the_hogging(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    assert "pair at support" in env.moment.min_combo[env.moment.peak_min_index]


def test_every_pattern_shares_one_sample_grid(three_span, cases):
    """Different patterns put load boundaries in different places. Without a
    single union grid the envelopes cannot be compared position by position."""
    env = analyse_patterns(three_span, cases, as1170_uls())
    grids = {tuple(r.x) for r in env.case_results.values()}
    assert len(grids) == 1
    assert len(env.case_results) > len(as1170_uls())


def test_custom_patterns_are_honoured(three_span, cases):
    only_middle = LoadPattern("middle only", (False, True, False))
    env = analyse_patterns(three_span, cases, as1170_uls(), patterns=(only_middle,))
    assert all("middle only" in k for k in env.case_results)


# ---------------------------------------------------------------------------
# Redistribution
# ---------------------------------------------------------------------------


def test_redistribution_reduces_the_support_moment_by_the_percentage(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    r = redistribute(env, three_span.support_positions, 30.0)

    for before, after in zip(r.support_moments_before, r.support_moments_after):
        assert after == pytest.approx(0.70 * before, rel=1e-6)


def test_redistribution_raises_the_span_moment(three_span, cases):
    """Moment shed from a support has to go somewhere. This is the price, and
    it is why the spans must be designed on the redistributed envelope."""
    env = analyse_patterns(three_span, cases, as1170_uls())
    r = redistribute(env, three_span.support_positions, 30.0)
    assert r.sagging_increase > 0
    assert r.envelope.M_star_sagging > env.M_star_sagging


def test_redistribution_preserves_equilibrium(three_span, cases):
    """The correction is linear within each span, which is exactly the
    condition for it to carry no load."""
    env = analyse_patterns(three_span, cases, as1170_uls())
    r = redistribute(env, three_span.support_positions, 30.0)
    assert verify_equilibrium(env.moment, r.envelope.moment, three_span.support_positions)


def test_zero_percent_changes_nothing(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    r = redistribute(env, three_span.support_positions, 0.0)
    assert np.allclose(r.envelope.moment.max_values, env.moment.max_values)
    assert r.sagging_increase == pytest.approx(0.0)


def test_per_support_percentages_are_applied_independently(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    r = redistribute(env, three_span.support_positions, (30.0, 10.0))
    assert r.percentages == (30.0, 10.0)
    assert r.support_moments_after[0] == pytest.approx(0.70 * r.support_moments_before[0])
    assert r.support_moments_after[1] == pytest.approx(0.90 * r.support_moments_before[1])


def test_wrong_number_of_percentages_refuses(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    with pytest.raises(ModelError, match="interior supports"):
        redistribute(env, three_span.support_positions, (30.0, 10.0, 5.0))


def test_a_percentage_outside_0_to_100_refuses(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    with pytest.raises(ModelError, match="0-100"):
        redistribute(env, three_span.support_positions, 150.0)


def test_a_simply_supported_span_has_nothing_to_redistribute(cases):
    beam = simply_supported(L, EI=1e14)
    env = analyse_combinations(beam, cases, as1170_uls())
    with pytest.raises(ModelError, match="at least three supports"):
        redistribute(env, beam.support_positions, 30.0)


def test_the_end_supports_are_pinned_at_zero_change(three_span, cases):
    """Moving the end moments would move the reactions, which is not
    redistribution -- it is a different structure."""
    env = analyse_patterns(three_span, cases, as1170_uls())
    r = redistribute(env, three_span.support_positions, 30.0)

    correction = r.envelope.moment.max_values - env.moment.max_values
    x = env.moment.x
    assert correction[int(np.argmin(np.abs(x - 0.0)))] == pytest.approx(0.0, abs=1.0)
    assert correction[int(np.argmin(np.abs(x - 3 * L)))] == pytest.approx(0.0, abs=1.0)


def test_describe_reports_before_and_after(three_span, cases):
    env = analyse_patterns(three_span, cases, as1170_uls())
    r = redistribute(env, three_span.support_positions, 30.0)
    text = "\n".join(r.describe())
    assert "30% reduction" in text
    assert "peak sagging" in text


# ---------------------------------------------------------------------------
# The code limit on how much may be redistributed
# ---------------------------------------------------------------------------


def test_redistribution_limit_tapers_with_neutral_axis_depth():
    from austruct.design import as3600

    assert as3600.redistribution_limit(0.10) == pytest.approx(30.0)
    assert as3600.redistribution_limit(0.20) == pytest.approx(30.0)
    assert as3600.redistribution_limit(0.30) == pytest.approx(15.0)
    assert as3600.redistribution_limit(0.40) == pytest.approx(0.0)
    assert as3600.redistribution_limit(0.60) == pytest.approx(0.0)


def test_class_l_reinforcement_may_not_be_redistributed():
    """Class L cannot form a reliable plastic hinge."""
    from austruct.design import as3600
    from austruct.materials.reinforcement import Ductility

    assert as3600.redistribution_limit(0.10, Ductility.L) == 0.0
