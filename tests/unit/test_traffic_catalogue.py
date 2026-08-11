"""Tests for the AS 5100.2 traffic load catalogue and model-aware dispersal.

The point of the catalogue is that a wheel spacing is stated ONCE, in the data
file, and every call site reads it from the model. So these tests check two
things above all: that nominating a model by name gives you everything it
carries, and that dispersal uses the model's own geometry rather than
whatever the caller happened to pass.
"""

from __future__ import annotations

import pytest

from austruct.analysis import moving_load_envelope, simply_supported
from austruct.core.units import m
from austruct.loads import FillDispersal
from austruct.loads import as5100_2 as traffic

SPAN = 6.0 * m
STRIP = 1000.0


@pytest.fixture(autouse=True)
def _permit():
    """Every test runs inside scoped permission.

    Using the context manager rather than the session setter means a test
    cannot leak permission into another test -- which would silently disable
    the guard test below.
    """
    with traffic.unverified_ok():
        yield


@pytest.fixture
def slab():
    return simply_supported(SPAN, EI=1e14, name="Top slab")


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_guard_refuses_without_permission():
    """The hardest fail-closed gate in the package."""
    with traffic.unverified_ok():
        assert traffic.get("M1600")

    # Outside the context manager permission is back to whatever it was.
    previous = traffic.allow_unverified()
    traffic.allow_unverified(False)
    try:
        assert not traffic.is_verified(), "data file should still be unverified"
        with pytest.raises(traffic.UnverifiedLoadModel, match="UNVERIFIED"):
            traffic.get("M1600")
    finally:
        traffic.allow_unverified(previous)


def test_guard_message_says_how_to_proceed():
    previous = traffic.allow_unverified()
    traffic.allow_unverified(False)
    try:
        with pytest.raises(traffic.UnverifiedLoadModel) as exc:
            traffic.get("W80")
        assert "allow_unverified" in str(exc.value)
    finally:
        traffic.allow_unverified(previous)


def test_context_manager_restores_on_exception():
    traffic.allow_unverified(False)
    try:
        with pytest.raises(RuntimeError), traffic.unverified_ok():
            raise RuntimeError("boom")
        assert traffic.allow_unverified() is False, "permission leaked"
    finally:
        traffic.allow_unverified(True)


def test_listing_the_catalogue_needs_no_permission():
    """Seeing what exists is not using it."""
    previous = traffic.allow_unverified()
    traffic.allow_unverified(False)
    try:
        assert "M1600" in traffic.names()
        assert "M1600" in traffic.catalogue()
        assert "NOT GIVEN" in traffic.catalogue()
    finally:
        traffic.allow_unverified(previous)


# ---------------------------------------------------------------------------
# Nominating by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["W80", "A160", "M1600", "S1600", "HLP320", "HLP400", "300LA"]
)
def test_every_catalogued_model_builds(name):
    model = traffic.get(name)
    assert model.name == name
    assert model.train.axles, "a model with no axles is not a load model"
    assert model.wheel.contact_length > 0
    assert model.wheel.contact_width > 0
    assert model.total_axle_load > 0


def test_names_are_case_insensitive():
    assert traffic.get("m1600").name == traffic.get("M1600").name
    assert traffic.get("  M1600 ").name == "M1600"


def test_unknown_name_lists_what_is_available():
    with pytest.raises(KeyError) as exc:
        traffic.get("M1700")
    message = str(exc.value)
    assert "M1600" in message and "300LA" in message


def test_road_and_rail_are_distinguished():
    assert traffic.get("M1600").kind is traffic.TrafficKind.ROAD
    assert traffic.get("300LA").kind is traffic.TrafficKind.RAIL
    assert "300LA" in traffic.names("rail")
    assert "300LA" not in traffic.names("road")


def test_convenience_constructors_match_the_catalogue():
    assert traffic.m1600().name == traffic.get("M1600").name
    assert traffic.s1600().name == "S1600"
    assert traffic.w80().name == "W80"
    assert traffic.a160().name == "A160"
    assert traffic.hlp(400).name == "HLP400"
    assert traffic.la(300).name == "300LA"


def test_models_are_cached_and_immutable():
    assert traffic.get("M1600") is traffic.get("M1600")
    with pytest.raises(AttributeError):
        traffic.get("M1600").name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# What the model carries
# ---------------------------------------------------------------------------


def test_model_carries_the_wheel_geometry_so_call_sites_need_not():
    m1600 = traffic.get("M1600")
    assert m1600.wheel.n_per_axle == 2
    assert m1600.wheel.spacing > 0
    # Per-wheel load follows from the axle load and the wheel count.
    assert m1600.wheel_load == pytest.approx(m1600.axle_load / 2)


def test_wheel_transverse_positions_are_symmetric():
    wheel = traffic.get("A160").wheel
    positions = wheel.transverse_positions()
    assert len(positions) == 2
    assert positions[0] == pytest.approx(-positions[1])
    assert positions[1] - positions[0] == pytest.approx(wheel.spacing)

    single = traffic.get("W80").wheel
    assert single.transverse_positions() == (0.0,)


def test_axle_layout_matches_the_data_file():
    spec = traffic.load_data()["models"]["M1600"]["geometry"]
    model = traffic.get("M1600")
    assert len(model.train.axles) == spec["n_axles"] * spec["n_groups"]
    offsets = [o for o, _ in model.train.axles]
    assert offsets[1] - offsets[0] == pytest.approx(spec["axle_spacing"])


def test_s1600_is_heavier_in_udl_and_lighter_in_axles():
    m, s = traffic.get("M1600"), traffic.get("S1600")
    assert s.udl > m.udl
    assert s.total_axle_load < m.total_axle_load


def test_dla_applies_to_loads_not_geometry():
    model = traffic.get("M1600")
    with_dla = model.train_with_dla()
    assert with_dla.total_axle_load == pytest.approx(
        model.total_axle_load * (1 + model.dla)
    )
    assert [o for o, _ in with_dla.axles] == [o for o, _ in model.train.axles]


def test_stationary_traffic_attracts_no_dla():
    model = traffic.get("S1600")
    assert model.dla == 0.0
    assert model.train_with_dla() is model.train


def test_rail_dla_refuses_rather_than_guessing():
    """A span-dependent allowance must not be silently replaced by a constant."""
    model = traffic.get("300LA")
    assert model.dla is None
    with pytest.raises(NotImplementedError, match="loaded length"):
        model.train_with_dla()
    with pytest.raises(NotImplementedError):
        traffic.dla("300LA")
    with pytest.raises(NotImplementedError, match="span-dependent"):
        traffic.rail_dla(20 * m)


def test_la_family_scales_from_300la():
    base = traffic.la(300)
    lighter = traffic.la(250)
    assert lighter.name == "250LA"
    assert lighter.total_axle_load == pytest.approx(base.total_axle_load * 250 / 300)
    # Geometry is common to the family.
    assert [o for o, _ in lighter.train.axles] == [o for o, _ in base.train.axles]


def test_hlp_entries_flag_themselves_as_placeholders():
    """The data file admits these are not trusted; the model must say so too."""
    assert traffic.get("HLP320").is_placeholder
    assert traffic.get("HLP400").is_placeholder
    assert not traffic.get("M1600").is_placeholder
    assert "Placeholder" in traffic.get("HLP320")._repr_markdown_()


def test_lane_factors_decrease_and_first_lane_is_unreduced():
    assert traffic.lane_factor(3, 1) == 1.0
    assert traffic.lane_factor(3, 3) <= traffic.lane_factor(3, 2)
    assert traffic.total_lane_factor(3) < 3.0
    with pytest.raises(KeyError):
        traffic.lane_factor(99)


# ---------------------------------------------------------------------------
# Model-aware dispersal
# ---------------------------------------------------------------------------


def test_dispersal_reads_geometry_from_the_model():
    """No contact dimensions passed anywhere in this test -- that is the point."""
    fill = FillDispersal(depth=600, effective_width=STRIP)
    model = traffic.get("W80")
    loads = fill.disperse_model(model, datum=SPAN / 2, member_length=SPAN)
    assert loads
    expected_length = fill.spread(model.wheel.contact_length)
    assert loads[0].extent == pytest.approx(expected_length)


def test_single_wheel_model_puts_its_whole_load_on_the_strip():
    fill = FillDispersal(depth=0.0, effective_width=STRIP)
    model = traffic.get("W80")
    loads = fill.disperse_model(model, SPAN / 2, SPAN)
    assert sum(load.total() for load in loads) == pytest.approx(
        model.total_axle_load, rel=1e-9
    )


def test_load_is_conserved_across_adjacent_strips():
    """Summed over every strip the axle passes over, the total is the axle."""
    fill = FillDispersal(depth=1000, effective_width=STRIP)
    model = traffic.get("A160")

    total = 0.0
    offset = -8000.0
    while offset <= 8000.0:
        total += sum(
            load.total()
            for load in fill.disperse_model(model, SPAN / 2, SPAN, strip_offset=offset)
        )
        offset += STRIP

    assert total == pytest.approx(model.axle_load, rel=1e-9)


def test_shallow_fill_the_wheel_lines_govern_not_the_centreline():
    """Regression on the default. A 1 m strip on the centreline of a 2 m axle
    under shallow fill carries NOTHING -- the patches sit either side of it."""
    fill = FillDispersal(depth=300, effective_width=STRIP)
    model = traffic.get("A160")

    centre = sum(
        load.total()
        for load in fill.disperse_model(model, SPAN / 2, SPAN, strip_offset=0.0)
    )
    worst = sum(load.total() for load in fill.disperse_model(model, SPAN / 2, SPAN))

    assert centre == pytest.approx(0.0, abs=1.0)
    assert worst > 0.5 * model.wheel_load
    assert worst > centre


def test_deep_fill_the_centreline_catches_both_wheels():
    fill = FillDispersal(depth=3000, effective_width=STRIP)
    model = traffic.get("A160")
    offset = fill.worst_strip_offset(model)
    assert abs(offset) < model.wheel.spacing / 2, "patches have merged"


def test_worst_offset_is_at_least_as_bad_as_any_other():
    fill = FillDispersal(depth=800, effective_width=STRIP)
    model = traffic.get("A160")
    worst = sum(load.total() for load in fill.disperse_model(model, SPAN / 2, SPAN))

    for offset in (-2000.0, -1000.0, 0.0, 1000.0, 2000.0):
        trial = sum(
            load.total()
            for load in fill.disperse_model(model, SPAN / 2, SPAN, strip_offset=offset)
        )
        assert trial <= worst + 1.0


def test_bad_strip_offset_raises():
    fill = FillDispersal(depth=600, effective_width=STRIP)
    with pytest.raises(ValueError, match="worst"):
        fill.disperse_model(traffic.get("W80"), SPAN / 2, SPAN, strip_offset="middle")


def test_axles_off_the_member_are_dropped():
    fill = FillDispersal(depth=300, effective_width=STRIP)
    model = traffic.get("M1600")
    on = fill.disperse_model(model, 0.0, SPAN)
    assert len(on) < len(model.train.axles), "a 13.75 m vehicle cannot fit on 6 m"


# ---------------------------------------------------------------------------
# Sweeping a dispersed model
# ---------------------------------------------------------------------------


def test_dispersed_model_train_is_positionable(slab):
    fill = FillDispersal(depth=600, effective_width=STRIP)
    model = traffic.get("M1600")
    dispersed = fill.dispersed_model_train(model)

    assert not dispersed.axles, "axles become patches"
    assert dispersed.udl_segments
    assert dispersed.length == model.train.length

    result = moving_load_envelope(slab, dispersed, step=250.0)
    assert result.M_star > 0


def test_lane_udl_is_shared_onto_the_strip_by_width():
    fill = FillDispersal(depth=600, effective_width=STRIP)
    model = traffic.get("M1600")
    dispersed = fill.dispersed_model_train(model)

    expected = model.udl * STRIP / model.loaded_width
    assert dispersed.trailing_udl == pytest.approx(expected)
    assert dispersed.trailing_udl < model.udl, "a 1 m strip sees part of a 3.2 m lane"


def test_strip_wider_than_the_lane_gets_one_lane_not_more():
    """A second lane needs the accompanying lane factors, which are a separate
    decision -- so the share is capped at one lane."""
    fill = FillDispersal(depth=600, effective_width=10_000.0)
    model = traffic.get("M1600")
    dispersed = fill.dispersed_model_train(model)
    assert dispersed.trailing_udl == pytest.approx(model.udl)


def test_sweeping_a_dispersed_model_shares_one_grid(slab):
    """Regression: the trailing UDL ends at the rear of the train, and that end
    moves -- so it must be a shared mesh point or the envelope cannot compare
    the positions."""
    fill = FillDispersal(depth=600, effective_width=STRIP)
    dispersed = fill.dispersed_model_train(traffic.get("M1600"))
    result = moving_load_envelope(slab, dispersed, step=250.0)

    grids = {tuple(r.x) for r in result.envelope.case_results.values()}
    assert len(grids) == 1


def test_end_to_end_buried_slab_under_a_named_model(slab):
    """The whole point: name a model, get a design action, state no geometry."""
    fill = FillDispersal(depth=600, density=2000, slope=2.0, effective_width=STRIP)
    model = traffic.get("W80")

    dispersed = fill.dispersed_model_train(model)
    result = moving_load_envelope(
        slab, dispersed, step=200.0, static_loads=(fill.earth_pressure_udl(),)
    )
    assert result.M_star > 0
    assert result.V_star > 0
