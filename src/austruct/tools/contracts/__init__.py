"""The shared contracts layer every tool's input/output models build on.

Each tool owns its own contracts (e.g. ``tools.cantilever_wall.models``) --
this package holds only the generic plumbing every tool's models share:
versioning, strict-extra validation, and the save/load round trip. Domain
bounds and cross-field engineering judgement (``Field(gt=..., le=...)``,
``model_validator``) belong in the tool's own contracts module, not here --
see :class:`~.base.ToolkitModel`'s docstring for why.
"""

from __future__ import annotations

from .base import ToolkitModel, load_result, save_result

__all__ = ["ToolkitModel", "save_result", "load_result"]
