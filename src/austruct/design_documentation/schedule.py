"""Member schedules -- CSV in, sections out, and back again.

ASET component 4, the storage half. The designation grammar in
:mod:`.designation` describes ONE member; a schedule is how a job's worth of
them is held.

Two shapes, because real schedules come in both:

**Long form** -- one row per member. The natural shape for a beam schedule and
the one that round-trips cleanly::

    member,designation,notes
    B1,350 x 650 | C40 | BOT 4-N28 | LIG N12-2L@200,
    B2,300 x 600 | C32 | BOT 3-N24 | LIG N12-2L@250,typical internal

**Matrix form** -- rows are levels, columns are member types. This is the shape
in the ASET material's coupling-beam example, and the shape a drafter expects
for anything that repeats up a building::

    story,CB1,CB2
    Roof,900 x 350 | C50 | BOT 6-N20 | LIG N12-2L@100,900 x 350 | ...
    L15,900 x 350 | C50 | BOT 6-N20 | LIG N12-2L@100,900 x 350 | ...

Both are plain CSV, so both open in a spreadsheet for review by an engineer who
does not run Python, and both diff line-by-line in version control.

[UNITS] Whatever the designation grammar uses -- mm and MPa.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from ..materials.reinforcement import D500N, Reinforcement
from ..sections.rc_section import RCSection
from .designation import DesignationError, designate, parse

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.D_EXTRACTION,
        component=ASETComponent.DESIGN_DOCUMENTATION,
    ),
    description="CSV member schedules in long and matrix form, round-tripping to RCSections",
    envelope_summary="Members expressible in the designation grammar",
)

DEFAULT_COLUMNS = ("member", "designation", "notes")


@dataclass
class ScheduleEntry:
    """One member in a schedule.

    The designation string is the source of truth; :attr:`section` is derived
    from it on demand. Keeping it that way means the CSV and the objects cannot
    disagree -- there is only one place the design is recorded.
    """

    member: str
    designation: str
    notes: str = ""
    extra: dict[str, str] = field(default_factory=dict)
    _section: RCSection | None = field(default=None, repr=False, compare=False)

    def section(
        self, material: Reinforcement = D500N, force: bool = False
    ) -> RCSection:
        """Build (and cache) the :class:`RCSection` this entry describes.

        Raises
        ------
        DesignationError
            If the designation does not parse. The member name is added to the
            message so a bad row in a long schedule is findable.
        """
        if self._section is None or force:
            try:
                self._section = parse(self.designation, name=self.member, material=material)
            except DesignationError as exc:
                raise DesignationError(
                    f"Member {self.member!r}: {exc}",
                    designation=self.designation,
                ) from exc
        return self._section

    @classmethod
    def from_section(
        cls, member: str, section: RCSection, notes: str = ""
    ) -> ScheduleEntry:
        """Build an entry from a designed section."""
        return cls(
            member=member,
            designation=designate(section),
            notes=notes,
            _section=section,
        )

    def validate(self) -> str:
        """Empty string if the designation parses, else the error message."""
        try:
            self.section(force=True)
        except Exception as exc:  # noqa: BLE001 -- report anything
            return str(exc)
        return ""


# ---------------------------------------------------------------------------
# Long form -- one row per member
# ---------------------------------------------------------------------------


def read_schedule(
    path: str | Path,
    member_column: str = "member",
    designation_column: str = "designation",
    notes_column: str = "notes",
) -> list[ScheduleEntry]:
    """Read a long-form CSV schedule.

    Column names are matched case-insensitively and with surrounding whitespace
    stripped, because a schedule that has been through a spreadsheet usually
    has both.

    Parameters
    ----------
    path:
        CSV file.
    member_column, designation_column, notes_column:
        Header names to look for.

    Returns
    -------
    list[ScheduleEntry]
        In file order. Sections are NOT built -- call
        :meth:`ScheduleEntry.section` or :func:`to_sections`, so that a schedule
        can be read and inspected even when some rows do not parse.

    Raises
    ------
    ValueError
        If the required columns are absent.
    """
    path = Path(path)
    entries: list[ScheduleEntry] = []

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header row")

        lookup = {(name or "").strip().lower(): name for name in reader.fieldnames}
        for required in (member_column, designation_column):
            if required.lower() not in lookup:
                raise ValueError(
                    f"{path} has no {required!r} column. Found: "
                    f"{sorted(lookup)}"
                )

        member_key = lookup[member_column.lower()]
        designation_key = lookup[designation_column.lower()]
        notes_key = lookup.get(notes_column.lower())
        known = {member_key, designation_key, notes_key}

        for row in reader:
            member = (row.get(member_key) or "").strip()
            designation = (row.get(designation_key) or "").strip()
            if not member and not designation:
                continue  # blank separator row, common in hand-edited schedules
            entries.append(
                ScheduleEntry(
                    member=member,
                    designation=designation,
                    notes=(row.get(notes_key) or "").strip() if notes_key else "",
                    extra={
                        k: (v or "").strip()
                        for k, v in row.items()
                        if k not in known and k is not None
                    },
                )
            )
    return entries


def write_schedule(
    entries: list[ScheduleEntry],
    path: str | Path,
    columns: tuple[str, ...] = DEFAULT_COLUMNS,
) -> None:
    """Write a long-form CSV schedule.

    Any keys in an entry's ``extra`` are written as additional columns, so a
    schedule that came in with job-specific columns goes back out with them.
    """
    path = Path(path)
    extra_keys: list[str] = []
    for entry in entries:
        for key in entry.extra:
            if key not in extra_keys:
                extra_keys.append(key)

    header = list(columns) + extra_keys
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for entry in entries:
            row = {
                "member": entry.member,
                "designation": entry.designation,
                "notes": entry.notes,
                **entry.extra,
            }
            writer.writerow([row.get(col, "") for col in header])


# ---------------------------------------------------------------------------
# Matrix form -- rows are levels, columns are member types
# ---------------------------------------------------------------------------


def read_matrix_schedule(path: str | Path) -> list[ScheduleEntry]:
    """Read a matrix-form schedule into flat entries.

    The first column is the row label (story, gridline, span); every other
    column is a member type. Each populated cell becomes one entry named
    ``"<column>@<row>"``, e.g. ``"CB1@L15"``.

    Empty cells are skipped, so a member type that does not occur at every
    level does not produce phantom entries.
    """
    path = Path(path)
    entries: list[ScheduleEntry] = []

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        rows = [row for row in reader if any((cell or "").strip() for cell in row)]

    if not rows:
        raise ValueError(f"{path} is empty")

    header = [(cell or "").strip() for cell in rows[0]]
    member_types = header[1:]

    for row in rows[1:]:
        row_label = (row[0] if row else "").strip()
        for i, member_type in enumerate(member_types, start=1):
            cell = (row[i] if i < len(row) else "").strip()
            if not cell:
                continue
            entries.append(
                ScheduleEntry(
                    member=f"{member_type}@{row_label}",
                    designation=cell,
                    extra={"row": row_label, "type": member_type},
                )
            )
    return entries


def write_matrix_schedule(
    entries: list[ScheduleEntry],
    path: str | Path,
    row_key: str = "row",
    type_key: str = "type",
    row_header: str = "story",
) -> None:
    """Write entries back out in matrix form.

    Entries must carry ``row`` and ``type`` in their ``extra`` -- which they do
    if they came from :func:`read_matrix_schedule`, or can be given explicitly.
    Row and column order follow first appearance, so a schedule read and
    written back keeps its order.
    """
    rows: list[str] = []
    types: list[str] = []
    cells: dict[tuple[str, str], str] = {}

    for entry in entries:
        row = entry.extra.get(row_key, "")
        member_type = entry.extra.get(type_key, "")
        if not row or not member_type:
            raise ValueError(
                f"Entry {entry.member!r} has no {row_key!r}/{type_key!r} in its "
                "extra fields, so it cannot be placed in a matrix schedule."
            )
        if row not in rows:
            rows.append(row)
        if member_type not in types:
            types.append(member_type)
        cells[(row, member_type)] = entry.designation

    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([row_header] + types)
        for row in rows:
            writer.writerow([row] + [cells.get((row, t), "") for t in types])


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


def to_sections(
    entries: list[ScheduleEntry], material: Reinforcement = D500N
) -> dict[str, RCSection]:
    """Build every entry's section, keyed by member name.

    Raises on the first bad row. Use :func:`validate_schedule` first when the
    schedule is hand-edited and you want all the errors at once.
    """
    return {entry.member: entry.section(material=material) for entry in entries}


def validate_schedule(entries: list[ScheduleEntry]) -> list[tuple[str, str]]:
    """Check every entry, returning ``[(member, error), ...]`` for the failures.

    Reporting every bad row at once is the point: fixing a two-hundred-row
    schedule one exception per run is not a workflow.
    """
    problems: list[tuple[str, str]] = []
    for entry in entries:
        error = entry.validate()
        if error:
            problems.append((entry.member, error))
    return problems


def schedule_report(entries: list[ScheduleEntry]) -> str:
    """Fixed-width summary of a schedule, with parse status per row."""
    if not entries:
        return "Schedule is empty."

    width = max(len(e.member) for e in entries)
    width = max(width, len("Member"))
    lines = [f"{'Member'.ljust(width)}  {'Status':<8}  Designation", "-" * (width + 60)]
    for entry in entries:
        error = entry.validate()
        status = "OK" if not error else "ERROR"
        lines.append(f"{entry.member.ljust(width)}  {status:<8}  {entry.designation}")
        if error:
            lines.append(f"{' ' * width}            -> {error}")

    failures = sum(1 for e in entries if e.validate())
    lines.append("-" * (width + 60))
    lines.append(f"{len(entries)} member(s), {failures} not parsing.")
    return "\n".join(lines)
