"""Reference-data loaders local to the cantilever wall tool.

Small, deliberately separate from :mod:`austruct.materials._data`: that
loader's package search list is materials/sections reference data, and this
tool's soil presets and factor sets are a different kind of thing, owned by a
different part of the toolkit. Same pattern (JSON/YAML via
``importlib.resources``, cached), not the same registry.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

import yaml


@cache
def load_json(filename: str) -> dict[str, Any]:
    """Load a JSON reference-data file from ``cantilever_wall/data/``."""
    text = (
        resources.files("austruct.tools.cantilever_wall.data")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


@cache
def load_yaml(filename: str) -> dict[str, Any]:
    """Load a YAML factor-set file from ``cantilever_wall/factors/``."""
    text = (
        resources.files("austruct.tools.cantilever_wall.factors")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )
    return yaml.safe_load(text)


def reload() -> None:
    """Drop the cache so edited data files are picked up without a restart."""
    load_json.cache_clear()
    load_yaml.cache_clear()
