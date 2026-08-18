"""Reference-data loader local to the gravity wall tool.

Same pattern as ``cantilever_wall/_data.py`` -- JSON via ``importlib.resources``,
cached -- but a separate loader pointed at this package's own ``data/``
directory rather than sharing the cantilever wall's.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any


@cache
def load_json(filename: str) -> dict[str, Any]:
    """Load a JSON reference-data file from ``gravity_wall/data/``."""
    text = (
        resources.files("austruct.tools.gravity_wall.data")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def reload() -> None:
    """Drop the cache so an edited data file is picked up without a restart."""
    load_json.cache_clear()
