"""Loader for the reference-data files in ``materials/data/``.

ASET component 1 says reference data should be "stored in a text-based format
(such as CSV or JSON) or an archival-quality binary format such as SQLite", and
that the characteristic quality is being able to "load, query, and envelope any
background data you need with one or two Python function calls".

So the tables live in JSON and this module is the one or two function calls.
The Python modules that consume them (``concrete.py``, ``reinforcement.py``,
``bar_catalogue.py``) present exactly the same API as before -- moving the data
out of Python changed where the numbers live, not how they are used.

Why this is worth doing
-----------------------
The numbers in those files are the highest-consequence, least-reviewed content
in the package. In a ``.py`` file they can only be checked by someone who reads
Python. In a ``.json`` file with a ``status`` and ``checked_by`` field, they can
be checked and signed off by the engineer who owns the standard -- which is the
person who should be doing it.

[UNITS] As declared in each file's ``units`` block: MPa and mm.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

DATA_PACKAGE = "austruct.materials.data"


@cache
def load(filename: str) -> dict[str, Any]:
    """Load one reference-data file.

    Cached, because these are static tables read many times per run and never
    written. Call :func:`reload` after editing a file in a live session.

    Parameters
    ----------
    filename:
        e.g. ``"concrete_grades.json"``.

    Raises
    ------
    FileNotFoundError
        If the file is not present in the data package -- which usually means
        the package was installed without its data files. See the
        ``package-data`` entry in ``pyproject.toml``.
    """
    try:
        text = resources.files(DATA_PACKAGE).joinpath(filename).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise FileNotFoundError(
            f"Reference data file {filename!r} not found in {DATA_PACKAGE}. "
            "If austruct was installed as a wheel, check that package-data is "
            "configured so the .json files ship with it."
        ) from exc
    return json.loads(text)


def reload() -> None:
    """Drop the cache so edited data files are picked up without a restart."""
    load.cache_clear()


def verification_status(filename: str) -> tuple[str, str | None, str | None]:
    """``(status, checked_by, checked_on)`` for a data file.

    Lets the module register report on the DATA as well as the code. A table
    can be wrong while the code that reads it is perfect, and that failure mode
    is invisible unless it is reported explicitly.
    """
    data = load(filename)
    return (
        data.get("status", "UNKNOWN"),
        data.get("checked_by"),
        data.get("checked_on"),
    )


def all_data_files() -> tuple[str, ...]:
    """Every reference-data file shipped with the package."""
    return ("concrete_grades.json", "reinforcement_grades.json", "bar_sizes.json")


def data_verification_report() -> str:
    """Verification status of every reference-data file, as a table.

    Printed alongside ``REGISTRY.summary()`` this completes the picture: the
    register covers the modules, this covers the numbers they read.
    """
    rows = []
    for filename in all_data_files():
        status, checker, checked_on = verification_status(filename)
        source = load(filename).get("source", "")
        rows.append((filename, status, checker or "-", checked_on or "-", source))

    headers = ("Data file", "Status", "Checked by", "Date", "Source")
    widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]
    line = "  ".join("-" * w for w in widths)
    out = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)), line]
    out.extend("  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows)
    out.append(line)
    unverified = sum(1 for f in all_data_files() if verification_status(f)[0] != "VERIFIED")
    out.append(f"{len(rows)} data file(s), {unverified} not verified.")
    return "\n".join(out)
