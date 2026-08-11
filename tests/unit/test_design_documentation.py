"""Unit tests for the design documentation layer -- ASET component 4.

The property that matters most is the round trip: ``parse(designate(s))``
must reproduce the section. A format that can be written but not read back
cannot be the record of a design.
"""

from __future__ import annotations

import pytest

from austruct.design_documentation import (
    DesignationError,
    ScheduleEntry,
    designate,
    parse,
    parse_fields,
    read_matrix_schedule,
    read_schedule,
    schedule_report,
    to_sections,
    validate,
    validate_schedule,
    write_matrix_schedule,
    write_schedule,
)
from austruct.materials import concrete
from austruct.sections import rc_beam

DESIGNATIONS = [
    "350 x 650 | C40 | COV 40 | BOT 4-N28 | LIG N12-2L@200",
    "300 x 600 | C32 | BOT 3-N24",
    "300 x 900 | C50 | T 1200/150 | COV 45 | BOT 6-N32 | TOP 3-N20 | LIG N16-2L@150",
    "900 x 550 | C50 | BOT 8-N28 | TOP 8-N28 | LIG N12-4L@100",
]


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", DESIGNATIONS)
def test_round_trip_is_stable(text):
    """parse -> designate -> parse must reach a fixed point."""
    once = designate(parse(text))
    twice = designate(parse(once))
    assert once == twice


@pytest.mark.parametrize("text", DESIGNATIONS)
def test_round_trip_preserves_the_section(text):
    a = parse(text)
    b = parse(designate(a))
    assert a.geometry.D == pytest.approx(b.geometry.D)
    assert a.geometry.area == pytest.approx(b.geometry.area)
    assert a.concrete.fc == pytest.approx(b.concrete.fc)
    assert a.total_steel_area == pytest.approx(b.total_steel_area)
    assert a.d == pytest.approx(b.d)
    assert a.bv == pytest.approx(b.bv)
    if a.fitment:
        assert a.fitment.area == pytest.approx(b.fitment.area)
        assert a.fitment.spacing == pytest.approx(b.fitment.spacing)


def test_bar_depths_follow_from_cover_and_fitment():
    section = parse("350 x 650 | C40 | COV 40 | BOT 4-N28 | LIG N12-2L@200")
    assert section.d_o == pytest.approx(650 - 40 - 12 - 14)


def test_fields_are_order_independent():
    a = parse("300 x 600 | C32 | COV 30 | BOT 4-N24 | LIG N12-2L@150")
    b = parse("300 x 600 | LIG N12-2L@150 | BOT 4-N24 | COV 30 | C32")
    assert designate(a) == designate(b)


def test_grammar_is_case_insensitive_and_whitespace_tolerant():
    a = parse("300 x 600 | C32 | bot 4-n24 | lig n12-2l@150")
    b = parse("300x600|C32|BOT 4-N24|LIG N12-2L@150")
    assert designate(a) == designate(b)


def test_tee_web_width_and_flange_are_distinguished():
    section = parse("300 x 900 | C50 | T 1200/150 | BOT 6-N32")
    assert section.b == 1200, "flexure uses the flange"
    assert section.bv == 300, "shear uses the web"


def test_parse_fields_without_building_a_section():
    fields = parse_fields("350 x 650 | C40 | BOT 4-N28 | LIG N12-2L@200")
    assert fields.width == 350
    assert fields.depth == 650
    assert fields.grade == 40
    assert fields.n_bottom == 4
    assert fields.dia_bottom == 28
    assert fields.fitment_legs == 2
    assert fields.has_fitments
    assert not fields.is_tee


# ---------------------------------------------------------------------------
# Failing loudly
# ---------------------------------------------------------------------------


def test_missing_grade_raises():
    with pytest.raises(DesignationError, match="no concrete grade"):
        parse("350 x 650 | BOT 4-N28")


def test_unrecognised_field_raises_and_quotes_it():
    with pytest.raises(DesignationError) as exc:
        parse("350 x 650 | C40 | BOTTOM 4-N28")
    assert "BOTTOM 4-N28" in str(exc.value)
    assert exc.value.field == "BOTTOM 4-N28"


def test_unrecognised_field_is_never_silently_ignored():
    """Dropping 'TOP 2-N16' would give a singly reinforced capacity for a
    doubly reinforced beam -- the failure mode this rule exists to prevent."""
    good = parse("350 x 650 | C40 | BOT 4-N28 | TOP 2-N16")
    assert len(good.layers) == 2
    with pytest.raises(DesignationError):
        parse("350 x 650 | C40 | BOT 4-N28 | TP 2-N16")


def test_dimensions_must_come_first():
    with pytest.raises(DesignationError, match="First field"):
        parse("C40 | 350 x 650 | BOT 4-N28")


def test_empty_designation_raises():
    with pytest.raises(DesignationError, match="Empty"):
        parse("")


def test_flange_thicker_than_the_section_raises():
    with pytest.raises(DesignationError, match="Flange thickness"):
        parse("300 x 400 | C40 | T 1200/500 | BOT 4-N28")


def test_validate_reports_without_raising():
    ok, message = validate("350 x 650 | C40 | BOT 4-N28")
    assert ok and not message
    ok, message = validate("garbage")
    assert not ok and message


def test_section_with_undetailed_layer_cannot_be_designated():
    from austruct.sections import RCSection, RebarLayer, rectangle

    section = RCSection(
        geometry=rectangle(300, 600),
        concrete=concrete(32),
        layers=(RebarLayer(area=1200.0, depth=540.0),),  # area only, no bar count
    )
    with pytest.raises(DesignationError, match="rather than by bars"):
        designate(section)


def test_multi_layer_section_cannot_be_designated():
    from austruct.sections import RebarLayer

    section = rc_beam(300, 600, concrete(32), n_bars=3, diameter=24, fitment_spacing=200)
    section = section.add_layer(RebarLayer.from_bars(3, 24, depth=470.0))
    with pytest.raises(DesignationError, match="one layer per face"):
        designate(section)


# ---------------------------------------------------------------------------
# Designed section -> designation -> capacity
# ---------------------------------------------------------------------------


def test_designed_section_round_trips_to_the_same_capacity():
    from austruct.design import as3600

    original = rc_beam(
        350, 650, concrete(40), cover=40, n_bars=4, diameter=28,
        fitment_diameter=12, fitment_spacing=200,
    )
    recovered = parse(designate(original))
    assert as3600.moment_capacity(recovered).get("phiMuo") == pytest.approx(
        as3600.moment_capacity(original).get("phiMuo"), rel=1e-9
    )


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


@pytest.fixture
def entries():
    return [
        ScheduleEntry("B1", DESIGNATIONS[0], notes="typical internal"),
        ScheduleEntry("B2", DESIGNATIONS[1]),
        ScheduleEntry("B3", DESIGNATIONS[3]),
    ]


def test_long_schedule_round_trips(tmp_path, entries):
    path = tmp_path / "beams.csv"
    write_schedule(entries, path)
    back = read_schedule(path)
    assert [e.member for e in back] == ["B1", "B2", "B3"]
    assert [e.designation for e in back] == [e.designation for e in entries]
    assert back[0].notes == "typical internal"


def test_schedule_builds_sections(tmp_path, entries):
    path = tmp_path / "beams.csv"
    write_schedule(entries, path)
    sections = to_sections(read_schedule(path))
    assert set(sections) == {"B1", "B2", "B3"}
    assert sections["B1"].geometry.D == 650


def test_schedule_columns_are_matched_case_insensitively(tmp_path):
    path = tmp_path / "beams.csv"
    path.write_text("Member, Designation ,Notes\nB1,300 x 600 | C32 | BOT 3-N24,x\n")
    entries = read_schedule(path)
    assert entries[0].member == "B1"
    assert entries[0].designation.startswith("300 x 600")


def test_schedule_missing_required_column_raises(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("member,section\nB1,300 x 600\n")
    with pytest.raises(ValueError, match="designation"):
        read_schedule(path)


def test_extra_columns_survive_a_round_trip(tmp_path):
    path = tmp_path / "beams.csv"
    path.write_text("member,designation,notes,level\nB1,300 x 600 | C32 | BOT 3-N24,,L3\n")
    entries = read_schedule(path)
    assert entries[0].extra["level"] == "L3"
    out = tmp_path / "out.csv"
    write_schedule(entries, out)
    assert "level" in out.read_text().splitlines()[0]


def test_blank_rows_are_skipped(tmp_path):
    path = tmp_path / "beams.csv"
    path.write_text(
        "member,designation\nB1,300 x 600 | C32 | BOT 3-N24\n,\nB2,300 x 600 | C32 | BOT 4-N24\n"
    )
    assert len(read_schedule(path)) == 2


def test_validate_schedule_reports_every_bad_row(tmp_path):
    bad = [
        ScheduleEntry("B1", DESIGNATIONS[0]),
        ScheduleEntry("B2", "nonsense"),
        ScheduleEntry("B3", "350 x 650 | BOT 4-N28"),
    ]
    problems = validate_schedule(bad)
    assert {member for member, _ in problems} == {"B2", "B3"}
    assert "B2" in schedule_report(bad)
    assert "ERROR" in schedule_report(bad)


def test_bad_row_error_names_the_member():
    entry = ScheduleEntry("B7", "350 x 650 | BOT 4-N28")
    with pytest.raises(DesignationError, match="B7"):
        entry.section()


def test_matrix_schedule_round_trips(tmp_path):
    """Ferster's coupling-beam schedule shape: rows are levels, columns are
    member types."""
    path = tmp_path / "coupling_beams.csv"
    path.write_text(
        "story,CB1,CB2\n"
        "Roof,900 x 350 | C50 | BOT 6-N20 | LIG N12-2L@100,"
        "900 x 350 | C50 | BOT 6-N20 | LIG N12-2L@100\n"
        "L15,900 x 550 | C50 | BOT 8-N28 | LIG N12-2L@100,\n"
    )
    entries = read_matrix_schedule(path)
    assert [e.member for e in entries] == ["CB1@Roof", "CB2@Roof", "CB1@L15"]
    assert entries[0].extra["type"] == "CB1"

    out = tmp_path / "out.csv"
    write_matrix_schedule(entries, out)
    again = read_matrix_schedule(out)
    assert [e.member for e in again] == [e.member for e in entries]
    assert [e.designation for e in again] == [e.designation for e in entries]


def test_matrix_schedule_skips_empty_cells(tmp_path):
    path = tmp_path / "m.csv"
    path.write_text("story,CB1,CB2\nL1,300 x 600 | C32 | BOT 3-N24,\n")
    assert len(read_matrix_schedule(path)) == 1


def test_entry_from_designed_section():
    section = rc_beam(350, 650, concrete(40), n_bars=4, diameter=28, fitment_spacing=200)
    entry = ScheduleEntry.from_section("B1", section, notes="edge beam")
    assert entry.member == "B1"
    assert "350 x 650" in entry.designation
    assert entry.validate() == ""
