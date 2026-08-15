"""Cantilever (stem-on-footing) retaining wall assessment, AS 4678:2002.

Public surface::

    from austruct.tools.cantilever_wall import (
        WallInput, WallGeometry, SoilInput, analyse,
    )

    result = analyse(WallInput(geometry=..., soil=...))

See the package README section "Cantilever retaining walls" for the worked
example, and this package's module docstrings for what is and is not yet
implemented (Method B trial wedge, divergence reporting, stem/heel/toe
concrete design and the global-stability screen are not yet built).
"""

from __future__ import annotations

from .api import analyse
from .factor_sets import KNOWN_FRAMEWORKS, FactorSet, load_factor_set
from .models import (
    CheckSummary,
    MethodResult,
    ResolvedSoil,
    SoilInput,
    SoilPresetRecord,
    SourcedValue,
    WallGeometry,
    WallInput,
    WallResult,
    soil_preset,
    soil_preset_names,
)

__all__ = [
    "analyse",
    "WallInput",
    "WallGeometry",
    "SoilInput",
    "ResolvedSoil",
    "SourcedValue",
    "WallResult",
    "MethodResult",
    "CheckSummary",
    "SoilPresetRecord",
    "soil_preset",
    "soil_preset_names",
    "FactorSet",
    "load_factor_set",
    "KNOWN_FRAMEWORKS",
]
