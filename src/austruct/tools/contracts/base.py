"""``ToolkitModel`` -- the common base every tool's Input and Result inherit.

Kept deliberately thin. This class handles three things and nothing else:

1. **Strict extra fields.** A field that doesn't belong -- a typo from a
   hand-built dict, a renamed key from an old schema version -- is REJECTED
   at construction, not silently dropped. For engineering input, a silently
   ignored field is worse than a loud error: the calculation runs anyway, on
   the wrong assumption.
2. **Schema versioning.** Every model carries ``schema_version``, bumped
   whenever a field is added, removed, renamed, or has its bounds tightened
   in a way that could invalidate previously serialised data. This is what
   makes a result saved against an old schema fail to *load* loudly, months
   later, instead of silently misloading into a newer model.
3. **The save/load round trip.** One mechanism, used the same way by every
   tool, for the actual composition case this layer exists for: a smaller
   tool's ``Result`` becomes a larger tool's ``Input`` by serialising once at
   the boundary and re-validating on the way back in -- not by trusting an
   in-memory object to still mean what it meant when it was built.

What does NOT belong here: engineering bounds (``Field(gt=..., le=...)``) and
cross-field judgement calls (``model_validator``) are domain logic specific to
one tool's inputs, and stay in that tool's own contracts module. Centralising
them here would make a bound on, say, a retaining wall's backslope look like
toolkit-wide policy rather than what it actually is -- one tool's engineering
judgement, owned and changeable by that tool alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound="ToolkitModel")


class ToolkitModel(BaseModel):
    """Shared base for every ``*Input`` and ``*Result`` model in ``tools/``."""

    schema_version: str = "1.0"

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )


def save_result(model: ToolkitModel, path: Path | str) -> None:
    """Serialise ``model`` to ``path`` as indented JSON.

    The one write path every tool uses -- so a result saved by one tool and
    read by another (or by a later run of the same tool) always round-trips
    the same way, rather than each call site inventing its own.
    """
    Path(path).write_text(model.model_dump_json(indent=2))


def load_result(model_cls: type[T], path: Path | str) -> T:
    """Load and RE-VALIDATE a model previously written by :func:`save_result`.

    Re-validation on the way in is the point, not a formality: it is what
    turns a stale field, a tightened bound, or a bumped ``schema_version``
    into a loud failure here, rather than a value silently reused months
    after the model that produced it changed.
    """
    return model_cls.model_validate_json(Path(path).read_text())
