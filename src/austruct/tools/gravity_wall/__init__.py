"""Modular gravity (segmental) block retaining wall assessment.

NCMA-style allowable stress design -- see the package README section
"Modular gravity block walls" for why this tool uses factors of safety
against characteristic soil strength rather than ``cantilever_wall``'s
AS 4678 limit-state approach, even though both tools share the same soil
model.

Public surface::

    from austruct.tools.gravity_wall import (
        GravityWallInput, GravityWallGeometry, SoilInput, analyse,
        block_series, block_series_names,
    )

    result = analyse(GravityWallInput(geometry=..., soil=...))

See this package's module docstrings for what is and is not yet
implemented (a global-stability geometry screen is not built -- the same
gap ``cantilever_wall`` has).
"""

from __future__ import annotations

from ..cantilever_wall.models import (
    ResolvedSoil,
    SoilInput,
    SourcedValue,
    soil_preset,
    soil_preset_names,
)
from .api import analyse
from .blocks import BlockSeries, block_series, block_series_names
from .factors import FS_BEARING, FS_GLOBAL_STABILITY, FS_INTERFACE_SHEAR, FS_OVERTURNING, FS_SLIDING
from .models import (
    CheckSummary,
    GravityWallGeometry,
    GravityWallInput,
    GravityWallResult,
    PressureSummary,
)

__all__ = [
    "analyse",
    "GravityWallInput",
    "GravityWallGeometry",
    "GravityWallResult",
    "PressureSummary",
    "CheckSummary",
    "SoilInput",
    "ResolvedSoil",
    "SourcedValue",
    "soil_preset",
    "soil_preset_names",
    "BlockSeries",
    "block_series",
    "block_series_names",
    "FS_SLIDING",
    "FS_OVERTURNING",
    "FS_BEARING",
    "FS_INTERFACE_SHEAR",
    "FS_GLOBAL_STABILITY",
]
