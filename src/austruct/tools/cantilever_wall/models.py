"""Input and result contracts for the cantilever wall tool.

[UNITS] This module's own convention, not ``austruct.core.units``'s mm/N/MPa:
lengths in **m**, unit weight in **kN/m^3**, pressure in **kPa**, force per
unit wall length in **kN/m**, moment per unit wall length in **kN.m/m**,
angles in **degrees**. This matches how a geotechnical input is actually
specified and reported, and it is the input LAYER's convention -- the
mechanics underneath still call into ``austruct.materials``/``design.as3600``
in their own mm/N/MPa convention where this tool eventually reaches concrete
design (stem/heel/toe), converting explicitly at that boundary.

Pydantic's job here is guardrails on values that are an ENGINEERING JUDGEMENT
CALL -- see ``tools/__init__.py``. It is not re-implementing AS 4678; the
factor VALUES live in :mod:`.factor_sets`, loaded from YAML, same as every
other standard in this package.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..contracts.base import ToolkitModel
from . import _data

# ---------------------------------------------------------------------------
# Soil presets
# ---------------------------------------------------------------------------


class SoilPresetRecord(ToolkitModel):
    """One row of ``data/soil_presets.json``."""

    name: str
    description: str
    phi: float
    gamma: float
    cohesion: float


def soil_preset_names() -> tuple[str, ...]:
    """Every preset name available to ``SoilInput.soil_type``."""
    return tuple(row["name"] for row in _data.load_json("soil_presets.json")["presets"])


def soil_preset(name: str) -> SoilPresetRecord:
    """Look up one soil preset by name.

    Raises
    ------
    KeyError
        If ``name`` is not in :func:`soil_preset_names`.
    """
    for row in _data.load_json("soil_presets.json")["presets"]:
        if row["name"] == name:
            return SoilPresetRecord.model_validate(row)
    raise KeyError(
        f"Unknown soil preset {name!r}. Known presets: {', '.join(soil_preset_names())}"
    )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class WallGeometry(ToolkitModel):
    """Wall and footing geometry.

    [UNITS] metres. Vertical stem, single uniform backfill -- a battered stem
    is not yet modelled; see :mod:`.pressure.rankine` for the clearance
    assertion this implies.
    """

    H_retained: float = Field(
        ..., gt=0.5, le=15.0,
        description="Total retained height, underside of footing to top of retained soil, m",
    )
    base_length: float = Field(..., gt=0.5, le=12.0, description="Footing width, m")
    base_thickness: float = Field(..., gt=0.15, le=2.0, description="Footing thickness, m")
    toe_length: float = Field(..., ge=0.0, le=6.0, description="Toe projection in front of the stem, m")
    stem_thickness_top: float = Field(..., gt=0.05, le=1.0, description="Stem thickness at the top, m")
    stem_thickness_bottom: float = Field(
        ..., gt=0.05, le=1.5, description="Stem thickness at the base, m"
    )

    @property
    def heel_length(self) -> float:
        """Footing projection behind the stem, m -- DERIVED, not an input."""
        return self.base_length - self.toe_length - self.stem_thickness_bottom

    @property
    def stem_height(self) -> float:
        """Stem height above the top of the footing, m."""
        return self.H_retained - self.base_thickness

    @model_validator(mode="after")
    def _geometry_is_buildable(self) -> WallGeometry:
        if self.heel_length <= 0:
            raise ValueError(
                f"toe_length ({self.toe_length} m) + stem_thickness_bottom "
                f"({self.stem_thickness_bottom} m) leaves no heel within "
                f"base_length ({self.base_length} m) -- the virtual-plane-"
                "through-the-heel method this tool uses cannot be applied to "
                "a wall with no heel. Increase base_length, or reduce "
                "toe_length/stem_thickness_bottom. (A stem-back Coulomb "
                "fallback for this geometry is not yet implemented.)"
            )
        if self.stem_height <= 0:
            raise ValueError(
                f"base_thickness ({self.base_thickness} m) >= H_retained "
                f"({self.H_retained} m) leaves no stem above the footing"
            )
        return self


# ---------------------------------------------------------------------------
# Soil
# ---------------------------------------------------------------------------


class SoilInput(ToolkitModel):
    """What the engineer actually supplies. Usable with just ``phi`` or just
    ``soil_type`` -- everything else defaults, and every default is surfaced
    in :class:`ResolvedSoil` tagged with where it came from.
    """

    phi: float | None = Field(
        None, gt=15.0, le=45.0, description="Effective friction angle, degrees"
    )
    soil_type: str | None = Field(
        None, description="A preset name -- see soil_preset_names()"
    )
    gamma: float | None = Field(None, gt=14.0, le=22.0, description="Unit weight, kN/m^3")
    cohesion: float | None = Field(
        None, ge=0.0, le=15.0,
        description="Effective cohesion, kPa. Capped low -- never rely on this for retained fill",
    )
    delta: float | None = Field(
        None, ge=0.0, le=30.0, description="Wall friction angle, degrees"
    )
    backslope: float = Field(
        0.0, ge=-10.0, le=25.0, description="Backslope, degrees, +ve rising away from the wall"
    )
    surcharge: float = Field(5.0, ge=0.0, le=50.0, description="Uniform surcharge, kPa")
    water_table: float | None = Field(
        None, ge=0.0,
        description="Depth of water table below the top of retained soil, m. "
        "Pass None explicitly for a drained design -- see the model validator.",
    )

    @model_validator(mode="after")
    def _at_least_one_strength_source(self) -> SoilInput:
        if self.phi is None and self.soil_type is None:
            raise ValueError(
                "Provide soil.phi or soil.soil_type (or both) -- the tool is "
                "usable with geometry plus one soil type, but needs at least one"
            )
        if self.soil_type is not None and self.soil_type not in soil_preset_names():
            raise ValueError(
                f"Unknown soil_type {self.soil_type!r}. "
                f"Known presets: {', '.join(soil_preset_names())}"
            )
        if "water_table" not in self.model_fields_set:
            raise ValueError(
                "water_table must be given explicitly -- pass water_table=None "
                "for a drained design (the default assumption elsewhere in "
                "this tool is always stated; water table is deliberately not "
                "silently assumed) or a depth in m below the top of the "
                "retained soil"
            )
        return self


class SourcedValue(ToolkitModel):
    """A resolved input value plus where it came from -- the mechanism that
    makes every preset-derived or defaulted value visible in the output."""

    value: float
    source: Literal["supplied", "preset", "default"]

    def __str__(self) -> str:
        return f"{self.value:g} ({self.source})"


class ResolvedSoil(ToolkitModel):
    """Every soil property the engine needs, fully resolved and sourced.

    Built by :func:`.engine.resolve_soil` from a :class:`SoilInput` -- never
    constructed by hand, so every field genuinely reflects what was supplied,
    what came from a preset, and what fell back to a bare default.
    """

    phi: SourcedValue
    gamma: SourcedValue
    cohesion: SourcedValue
    delta: SourcedValue
    backslope: SourcedValue
    surcharge: SourcedValue
    water_table: float | None

    def assumptions(self) -> list[str]:
        """Human-readable lines for every field NOT directly supplied --
        the "assumed vs supplied" list :class:`WallResult` carries."""
        labels = {
            "phi": "Friction angle phi",
            "gamma": "Unit weight gamma",
            "cohesion": "Cohesion c'",
            "delta": "Wall friction delta",
            "backslope": "Backslope",
            "surcharge": "Surcharge",
        }
        out = []
        for field_name, label in labels.items():
            sourced: SourcedValue = getattr(self, field_name)
            if sourced.source != "supplied":
                out.append(f"{label} = {sourced}")
        return out


# ---------------------------------------------------------------------------
# Wall input and result
# ---------------------------------------------------------------------------


class WallInput(ToolkitModel):
    """The complete input to :func:`~austruct.tools.cantilever_wall.api.analyse`."""

    geometry: WallGeometry
    soil: SoilInput
    passive_neglect_depth: float = Field(
        1.0, ge=0.0, le=3.0,
        description="m of toe embedment ignored for passive resistance. ON by "
        "default -- services trenching routinely removes the toe cover",
    )
    construction: Literal["cast_in_situ", "precast"] = Field(
        "cast_in_situ",
        description="Governs the default base-soil interface friction: full "
        "phi cast in-situ, 2/3 phi precast",
    )
    base_friction_override: float | None = Field(
        None, gt=0.0, le=45.0, description="deg -- bypasses the derived base friction angle"
    )
    bearing_capacity_override: float | None = Field(
        None, gt=0.0, le=2000.0,
        description="kPa -- ultimate bearing capacity from a geotechnical report, "
        "bypasses the Terzaghi/Meyerhof estimate computed internally",
    )
    name: str = ""


class CheckSummary(ToolkitModel):
    """One check, condensed to plain serialisable data plus its full working.

    ``working`` is the underlying ``CalcResult.to_dict()`` -- basis,
    intermediates, checks and messages all survive a save/load round trip,
    not just the pass/fail number. This is what lets a saved ``WallResult``
    still be rendered as a readable report later, without the live
    ``CalcResult`` objects that produced it.
    """

    label: str
    passed: bool
    utilisation: float
    working: dict[str, Any]


class MethodResult(ToolkitModel):
    """One earth-pressure method's result for one wall."""

    method: Literal["rankine"]
    Ka: float
    Kp: float | None = None
    thrust_horizontal: float = Field(..., description="kN/m, earth pressure only")
    thrust_vertical: float = Field(..., description="kN/m, earth pressure only")
    thrust_height: float = Field(..., description="m above the base, line of action")
    hydrostatic_horizontal: float = Field(
        0.0, description="kN/m -- reported separately, never lumped into thrust_horizontal"
    )
    critical_wedge_angle: float | None = Field(
        None, description="degrees -- trial-wedge methods only, None for Rankine"
    )
    working: dict[str, Any]


class WallResult(ToolkitModel):
    """Everything :func:`analyse` produces for one wall, one framework."""

    framework: str
    resolved_soil: ResolvedSoil
    method_a: MethodResult
    checks: dict[str, CheckSummary]
    governing_utilisation: float
    passed: bool
    assumptions: list[str]
    notes: list[str] = Field(default_factory=list)
