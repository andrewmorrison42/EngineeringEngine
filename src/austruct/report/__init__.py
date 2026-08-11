"""L5 -- the audit artifact.

The durable standard is the report LAYOUT (``template.py``), not any particular
rendering library. See the roadmap, Phase 2.

``plots`` is NOT imported eagerly: it needs matplotlib, which is an optional
dependency, so importing ``austruct.report`` must not require it. Both of these
work and neither pays the matplotlib import until reached::

    from austruct.report import plots
    austruct.report.plots.plot_diagrams(results)
"""

from importlib import import_module
from typing import Any

from .renderers import HtmlRenderer, MarkdownRenderer
from .template import (
    Figure,
    Narrative,
    NarrativeKind,
    Renderer,
    Report,
    SignatureBlock,
)

__all__ = [
    "Report",
    "SignatureBlock",
    "Narrative",
    "NarrativeKind",
    "Figure",
    "Renderer",
    "MarkdownRenderer",
    "HtmlRenderer",
    "plots",
]


def __getattr__(name: str) -> Any:
    """Lazy access to the optional plotting module.

    Uses ``import_module`` rather than ``from . import plots``: the latter goes
    through ``_handle_fromlist``, which calls ``getattr`` on this package, which
    re-enters this function -- an infinite recursion rather than an import.
    ``import_module`` also binds the submodule onto the package, so this runs
    once and later attribute access finds it directly.
    """
    if name == "plots":
        return import_module(f"{__name__}.plots")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
