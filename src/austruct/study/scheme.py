"""``Scheme`` -- one named variation on a base design, and its CSV round trip.

A design engineer's actual variations arrive as a spreadsheet: one row per
option, one column per thing that changes. This module is that spreadsheet
in code -- see :mod:`.sweep` for what runs each row against a design check.

[UNITS] Whatever the caller's ``build`` function expects -- this module does
not know or care what a "b" or a "diameter" column means, only how to turn a
spreadsheet cell into a Python value.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RESERVED_COLUMNS = ("scheme", "notes")


@dataclass(frozen=True)
class Scheme:
    """One named variation.

    ``overrides`` is merged onto a sweep's ``base`` kwargs -- a key present
    here wins, a key absent here falls back to the base value. That is the
    entire semantics: there is no per-scheme "delete this base value" or
    "reset to default", by design, so a scheme reads the same way a
    spreadsheet row does.
    """

    name: str
    overrides: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def merged(self, base: dict[str, Any]) -> dict[str, Any]:
        """``base`` with this scheme's overrides applied on top."""
        return {**base, **self.overrides}


def _coerce(raw: str) -> Any:
    """Turn one spreadsheet cell into a Python value.

    Tries int, then float, then a case-insensitive true/false, and falls
    back to the trimmed string. There is no way to ask for a value that is
    literally the text ``"true"`` -- that is the trade a spreadsheet-shaped
    input makes, and it matches how every other CSV surface in this package
    (``design_documentation/schedule.py``) already behaves: plain text in,
    no escaping convention to teach an engineer filling in cells.
    """
    text = raw.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text


def load_schemes_csv(path: str | Path) -> list[Scheme]:
    """Read a CSV of variations, one row per scheme.

    Column layout::

        scheme,b,D,diameter,notes
        A,300,600,24,
        B,300,700,20,deeper and leaner
        C,,,,identical to the base scenario

    ``scheme`` (case-insensitive) is required and becomes :attr:`Scheme.name`.
    ``notes`` is optional. Every other column becomes an override key; a
    BLANK cell means "no override for this scheme" (inherits the sweep's
    base value), not "override to an empty string" -- so a scheme that
    changes only one of several columns is a normal, common row, not a
    sparse edge case to work around.

    Raises
    ------
    ValueError
        If there is no ``scheme`` column, or two rows share a name.
    """
    path = Path(path)
    schemes: list[Scheme] = []
    seen: set[str] = set()

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header row")

        lookup = {(name or "").strip().lower(): name for name in reader.fieldnames}
        if "scheme" not in lookup:
            raise ValueError(f"{path} has no 'scheme' column. Found: {sorted(lookup)}")

        scheme_key = lookup["scheme"]
        notes_key = lookup.get("notes")
        override_keys = [
            raw for norm, raw in lookup.items() if norm not in RESERVED_COLUMNS
        ]

        for row in reader:
            name = (row.get(scheme_key) or "").strip()
            if not name:
                continue  # blank separator row
            if name in seen:
                raise ValueError(f"{path}: scheme name {name!r} appears more than once")
            seen.add(name)

            overrides = {}
            for key in override_keys:
                raw = row.get(key)
                if raw is None or not raw.strip():
                    continue
                overrides[key] = _coerce(raw)

            schemes.append(
                Scheme(
                    name=name,
                    overrides=overrides,
                    notes=(row.get(notes_key) or "").strip() if notes_key else "",
                )
            )
    return schemes


def save_schemes_csv(schemes: list[Scheme], path: str | Path) -> None:
    """Write schemes back out as CSV, columns as first-appearance order.

    A scheme that does not override a given column leaves that cell blank --
    the inverse of :func:`load_schemes_csv`'s blank-means-no-override rule,
    so a save/load round trip is exact.
    """
    columns: list[str] = []
    for scheme in schemes:
        for key in scheme.overrides:
            if key not in columns:
                columns.append(key)

    header = ["scheme", *columns, "notes"]
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for scheme in schemes:
            row = [scheme.name]
            row.extend(str(scheme.overrides[c]) if c in scheme.overrides else "" for c in columns)
            row.append(scheme.notes)
            writer.writerow(row)
