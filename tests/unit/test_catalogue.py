"""``CATALOGUE.md`` is a GENERATED file (see ``scripts/generate_catalogue.py``)
-- this test is the drift guard: it rebuilds the catalogue from
``REGISTRY`` right now and fails if that doesn't match what's committed.
Exactly the mechanism the README's own "Not built yet" table never had,
which is why that table went stale for several sessions before anyone
noticed -- see the script's module docstring.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CATALOGUE_PATH = REPO_ROOT / "CATALOGUE.md"
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_catalogue.py"


def _load_generator():
    """``scripts/`` isn't an installed package -- load the module by path."""
    spec = importlib.util.spec_from_file_location("generate_catalogue", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not SCRIPT_PATH.exists(), reason="generator script not found")
def test_catalogue_matches_the_registry_right_now():
    generator = _load_generator()
    current = generator.build_catalogue()
    assert CATALOGUE_PATH.exists(), (
        "CATALOGUE.md is missing -- run `python scripts/generate_catalogue.py`"
    )
    on_disk = CATALOGUE_PATH.read_text()
    assert on_disk == current, (
        "CATALOGUE.md is stale -- a module's Provenance/description changed, "
        "or a new module registered, without re-running "
        "`python scripts/generate_catalogue.py`"
    )


def test_every_registered_module_has_a_non_empty_description():
    """A blank description would still pass the drift check above but be
    useless as a catalogue entry -- this catches that separately."""
    generator = _load_generator()
    generator._import_everything()
    from austruct.core.registry import REGISTRY

    assert REGISTRY.entries, "REGISTRY is empty -- nothing imported?"
    for entry in REGISTRY.entries.values():
        assert entry.description, f"{entry.key} registered with no description"
