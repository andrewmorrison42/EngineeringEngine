"""Input and result contracts for the gravity (modular block) wall tool.

[UNITS] Same convention as ``cantilever_wall`` -- m, kN/m^3, kPa, kN/m,
kN.m/m, degrees. See that package's ``models.py`` for the rationale.

This tool deliberately REUSES ``cantilever_wall``'s soil model
(:class:`~austruct.tools.cantilever_wall.models.SoilInput`, its preset
library and :func:`~austruct.tools.cantilever_wall.engine.resolve_soil`)
rather than duplicating it -- soil resolution ("what phi, what gamma, where
did it come from") is not specific to either wall type. What it does NOT
reuse is ``cantilever_wall``'s AS 4678 material-factor machinery
(:func:`~austruct.tools.cantilever_wall.engine.apply_material_factors`,
:class:`~austruct.tools.cantilever_wall.factor_sets.FactorSet`) -- this
tool is allowable-stress design (a factor of safety on the whole system
response, against CHARACTERISTIC soil strength), not limit-state design
(a material factor on soil strength before the pressure calculation). See
the package README section for why these are genuinely different design
philosophies, not two ways of writing the same thing.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from ..cantilever_wall.models import CheckSummary, ResolvedSoil, SoilInput, SourcedValue
from ..contracts.base import ToolkitModel
from .blocks import BlockSeries

__all__ = [
    "GravityWallGeometry",
    "GravityWallInput",
    "PressureSummary",
    "CheckSummary",
    "GravityWallResult",
    "ResolvedSoil",
    "SoilInput",
    "SourcedValue",
]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class GravityWallGeometry(ToolkitModel):
    """Course-stack geometry for a modular gravity block wall.

    A stack of ``n_courses`` identical-width blocks, each course's front
    face set back ``block.setback`` from the course below -- the batter
    mechanism, uniform up the wall (see :class:`~.blocks.BlockSeries`).
    Unlike :class:`~austruct.tools.cantilever_wall.models.WallGeometry`
    there is no separate stem/footing/heel -- the blocks themselves ARE
    the gravity mass, and there is no reinforced-concrete member design
    for this tool to do.
    """

    n_courses: int = Field(..., ge=1, le=40, description="Number of block courses, base to top")
    block: BlockSeries
    embedment: float = Field(
        0.0, ge=0.0, le=1.0,
        description="m of the bottom course buried below finished front grade. "
        "Feeds the bearing check's founding depth only -- NO passive "
        "resistance credit is taken anywhere in this tool regardless of "
        "embedment (see checks/sliding.py), a deliberately conservative "
        "simplification for a system whose toe is rarely a formed key.",
    )

    @property
    def H(self) -> float:  # noqa: N802
        """Total wall height, base of the bottom course to the top of the top course, m."""
        return self.n_courses * self.block.height

    @property
    def batter_deg(self) -> float:
        """Wall batter from vertical, degrees -- see :attr:`.blocks.BlockSeries.batter_deg`."""
        return self.block.batter_deg

    @property
    def base_width(self) -> float:
        """Front-to-back footprint of the BOTTOM course, m -- this tool's
        base width for sliding/overturning/bearing, analogous to
        ``WallGeometry.base_length`` in the cantilever wall tool."""
        return self.block.width


# ---------------------------------------------------------------------------
# Wall input and result
# ---------------------------------------------------------------------------


class GravityWallInput(ToolkitModel):
    """The complete input to :func:`~austruct.tools.gravity_wall.api.analyse`."""

    geometry: GravityWallGeometry
    soil: SoilInput
    delta_interface: float = Field(
        32.0, gt=0.0, le=45.0,
        description="deg -- course-to-course interface friction angle. "
        "[VECTOR] UNVERIFIED typical value; real segmental systems are "
        "tested per ASTM D6916 and publish a peak/residual envelope "
        "specific to the block's connector detail -- replace with that "
        "manufacturer data before issuing a design.",
    )
    c_interface: float = Field(
        10.0, ge=0.0, le=50.0,
        description="kN/m -- course-to-course interface cohesion/shear-connector "
        "capacity at zero normal load. [VECTOR] UNVERIFIED typical value, "
        "same caveat as delta_interface.",
    )
    base_friction_override: float | None = Field(
        None, gt=0.0, le=45.0,
        description="deg -- bypasses the derived base friction angle (which "
        "otherwise takes the full characteristic soil phi, on the "
        "assumption of a granular levelling pad under the base course)",
    )
    bearing_capacity_override: float | None = Field(
        None, gt=0.0, le=2000.0,
        description="kPa -- ultimate bearing capacity from a geotechnical report, "
        "bypasses the Terzaghi/Meyerhof estimate computed internally",
    )
    name: str = ""

    @model_validator(mode="after")
    def _no_water_table(self) -> GravityWallInput:
        if self.soil.water_table is not None:
            raise ValueError(
                "gravity_wall does not model a water table (unlike "
                "cantilever_wall) -- pass soil.water_table=None. A submerged "
                "or partially submerged modular block wall needs a "
                "geotechnical review this tool does not attempt to automate."
            )
        return self


class PressureSummary(ToolkitModel):
    """The Coulomb active-pressure result for one wall."""

    Ka: float
    thrust_horizontal: float = Field(..., description="kN/m")
    thrust_vertical: float = Field(
        ..., description="kN/m, acting DOWNWARD on the wall (wall friction credit)"
    )
    thrust_height: float = Field(..., description="m above the base, line of action")
    working: dict[str, Any]


class GravityWallResult(ToolkitModel):
    """Everything :func:`analyse` produces for one gravity wall."""

    framework: str
    resolved_soil: ResolvedSoil
    pressure: PressureSummary
    checks: dict[str, CheckSummary]
    governing_utilisation: float
    passed: bool
    assumptions: list[str]
    notes: list[str] = Field(default_factory=list)
