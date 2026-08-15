"""Soil resolution, material factoring, and the stability ledger.

The mechanics that sit between the validated Pydantic input and the checks:
resolving a :class:`SoilInput` into a fully-sourced :class:`ResolvedSoil`,
applying AS 4678-style material factors to get the DESIGN soil strength that
must flow into every pressure method, and building the vertical/horizontal
force-and-moment ledger every check reads from.

[UNITS] This tool's own convention -- m, kN/m^3, kPa, kN/m, kN.m/m, degrees.
See :mod:`.models` for why this differs from ``austruct.core.units``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ...core.units import GRAVITY
from ...materials.concrete import DENSITY_NORMAL
from .factor_sets import FactorSet
from .models import ResolvedSoil, SoilInput, SourcedValue, WallGeometry, WallInput

GAMMA_WATER = 9.81
"""Unit weight of water, kN/m^3."""

CONCRETE_UNIT_WEIGHT = DENSITY_NORMAL * GRAVITY / 1000.0
"""Reinforced concrete unit weight, kN/m^3 -- derived from the SAME normal
density (2400 kg/m^3) `austruct.materials.concrete` uses elsewhere, rather
than a second hardcoded number. [ASSUMPTION] Plain-concrete density; some
offices add an allowance (~0.5-1 kN/m^3) for reinforcement -- not applied
here."""

DEFAULT_DELTA_FRACTION = 2.0 / 3.0
DEFAULT_DELTA_CAP = 20.0
"""delta = (2/3).phi, capped at 20 deg -- the default for a smooth precast
panel. [VECTOR] Typical guidance value, UNVERIFIED against an office
standard or AS 4678 commentary."""


def resolve_soil(soil: SoilInput) -> ResolvedSoil:
    """Fill every soil property, tagging where each one came from.

    This is the ONLY place preset values are substituted -- everything
    downstream reads a fully-resolved, fully-sourced :class:`ResolvedSoil`
    and never touches the preset library itself.
    """
    from .models import soil_preset  # local import: avoids a cycle with models

    preset = soil_preset(soil.soil_type) if soil.soil_type else None

    def sourced(supplied: float | None, preset_value: float | None, default: float) -> SourcedValue:
        if supplied is not None:
            return SourcedValue(value=supplied, source="supplied")
        if preset_value is not None:
            return SourcedValue(value=preset_value, source="preset")
        return SourcedValue(value=default, source="default")

    phi = sourced(soil.phi, preset.phi if preset else None, default=30.0)
    gamma = sourced(soil.gamma, preset.gamma if preset else None, default=18.0)
    cohesion = sourced(soil.cohesion, preset.cohesion if preset else None, default=0.0)

    if soil.delta is not None:
        delta = SourcedValue(value=soil.delta, source="supplied")
    else:
        delta = SourcedValue(
            value=min(DEFAULT_DELTA_FRACTION * phi.value, DEFAULT_DELTA_CAP),
            source="default",
        )

    backslope = SourcedValue(
        value=soil.backslope,
        source="supplied" if "backslope" in soil.model_fields_set else "default",
    )
    surcharge = SourcedValue(
        value=soil.surcharge,
        source="supplied" if "surcharge" in soil.model_fields_set else "default",
    )

    return ResolvedSoil(
        phi=phi,
        gamma=gamma,
        cohesion=cohesion,
        delta=delta,
        backslope=backslope,
        surcharge=surcharge,
        water_table=soil.water_table,
    )


@dataclass(frozen=True)
class DesignSoil:
    """Soil strength AFTER the framework's material factors -- this, not the
    characteristic :class:`ResolvedSoil`, is what every pressure method and
    every check must use for phi and cohesion.

    [BASIS] AS 4678:2002 applies its material factor to tan(phi), not to phi
    directly -- see :mod:`.factor_sets`.
    """

    phi_deg: float
    cohesion: float
    gamma: float  # NOT factored -- self-weight/unit weight is not a strength


def apply_material_factors(soil: ResolvedSoil, factors: FactorSet) -> DesignSoil:
    """Factor the characteristic soil strength down to the design values.

    Deliberately separate from :func:`resolve_soil`: resolution is about
    WHERE a number came from, factoring is about WHAT THE FRAMEWORK does to
    it once resolved. Keeping them apart means adding a framework never
    touches how presets are read, and changing the preset library never
    touches the AS 4678 factors.
    """
    phi_rad = math.radians(soil.phi.value)
    tan_phi_design = math.tan(phi_rad) * factors.material.phi_ug_factor
    phi_design_deg = math.degrees(math.atan(tan_phi_design))
    cohesion_design = soil.cohesion.value * factors.material.cohesion_factor
    return DesignSoil(phi_deg=phi_design_deg, cohesion=cohesion_design, gamma=soil.gamma.value)


@dataclass(frozen=True)
class ConcreteWeight:
    """One concrete element's self-weight and its lever arm from the toe.

    [UNITS] weight kN/m (per metre run of wall), arm m.
    """

    label: str
    weight: float
    arm: float


def concrete_self_weight(geometry: WallGeometry) -> tuple[ConcreteWeight, ConcreteWeight]:
    """Footing and stem self-weight, per metre run of wall.

    [ASSUMPTION] Stem taken as a linear taper from ``stem_thickness_bottom``
    to ``stem_thickness_top`` -- its weight is the trapezoidal area times
    ``CONCRETE_UNIT_WEIGHT``, and its centroid (hence its arm from the toe)
    follows the trapezoid centroid formula, not the rectangle midpoint.
    """
    footing = ConcreteWeight(
        label="Footing self-weight",
        weight=geometry.base_length * geometry.base_thickness * CONCRETE_UNIT_WEIGHT,
        arm=geometry.base_length / 2.0,
    )

    # [ASSUMPTION] The BACK face of the stem (retained-soil side) is held
    # vertical, consistent with the virtual-plane-through-the-heel method --
    # any taper is on the FRONT (exposed) face. So the back face sits at a
    # fixed x for the full stem height, and only the front face moves.
    back_x = geometry.toe_length + geometry.stem_thickness_bottom
    b_bot = geometry.stem_thickness_bottom
    b_top = geometry.stem_thickness_top
    stem_area = 0.5 * (b_bot + b_top) * geometry.stem_height
    # Area centroid's distance FROM THE BACK FACE, for a trapezoid whose
    # thickness varies linearly with height between b_bot and b_top:
    #   offset = (1/2) . integral(t(y)^2 dy) / integral(t(y) dy)
    #          = (b_bot^2 + b_bot.b_top + b_top^2) / (3.(b_bot + b_top))
    # Reduces to b/2 for a uniform rectangle (b_bot = b_top = b), as expected.
    if b_bot + b_top > 0:
        centroid_offset = (b_bot**2 + b_bot * b_top + b_top**2) / (3.0 * (b_bot + b_top))
    else:  # pragma: no cover -- geometry validators already exclude this
        centroid_offset = 0.0
    stem = ConcreteWeight(
        label="Stem self-weight",
        weight=stem_area * CONCRETE_UNIT_WEIGHT,
        arm=back_x - centroid_offset,
    )
    return footing, stem


@dataclass(frozen=True)
class SoilWeight:
    """Soil (plus any surcharge) resting on the heel, per metre run.

    Includes the surcharge sitting on top of the heel-soil column deliberately
    -- see the module note on why the closed-form method double-counts
    surcharge relative to the trial wedge, which is one of the documented
    divergence sources between the two methods.
    """

    soil_weight: ConcreteWeight
    surcharge_weight: ConcreteWeight


def heel_soil_weight(geometry: WallGeometry, gamma: float, surcharge: float) -> SoilWeight:
    heel_x_start = geometry.toe_length + geometry.stem_thickness_bottom
    arm = heel_x_start + geometry.heel_length / 2.0
    soil = ConcreteWeight(
        label="Soil on heel",
        weight=geometry.heel_length * geometry.stem_height * gamma,
        arm=arm,
    )
    surcharge_load = ConcreteWeight(
        label="Surcharge on heel",
        weight=geometry.heel_length * surcharge,
        arm=arm,
    )
    return SoilWeight(soil_weight=soil, surcharge_weight=surcharge_load)


def base_friction_angle(wall: WallInput, design_soil: DesignSoil) -> float:
    """Base-soil interface friction angle, degrees.

    Full design phi for a cast in-situ footing (rough interface, effectively
    as rough as the soil itself); 2/3 of it for a precast panel on a
    prepared surface. An explicit override always wins.

    [VECTOR] The 2/3 factor for precast is typical guidance, UNVERIFIED
    against an office standard.
    """
    if wall.base_friction_override is not None:
        return wall.base_friction_override
    if wall.construction == "precast":
        return DEFAULT_DELTA_FRACTION * design_soil.phi_deg
    return design_soil.phi_deg


# ---------------------------------------------------------------------------
# The stability ledger
# ---------------------------------------------------------------------------
#
# Every row carries TWO independent classifications, because they are not
# the same question:
#   force_kind      which AS 4678 action factor applies to its MAGNITUDE
#   moment_effect   which side of the overturning-moment balance about the
#                   toe its ARM puts it on
#
# The two can disagree. The vertical component of earth pressure (present
# only with a backslope) is classified `destabilising` for its factor --
# it is part of the earth-pressure action, factored up like the rest of it,
# even though the force itself, acting at the back of the footing, RESISTS
# overturning about the toe. Collapsing these into one classification would
# either under-factor the earth pressure or wrongly credit it as a resisting
# action -- see the note on this in `build_ledger`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerRow:
    """One force in the stability ledger.

    [UNITS] force kN/m (vertical rows) or kN/m (horizontal rows, same unit,
    different direction); arm m (from the toe for vertical rows, above the
    base for horizontal rows).
    """

    label: str
    force: float
    arm: float
    axis: Literal["vertical", "horizontal"]
    force_kind: Literal["stabilising", "destabilising"]
    moment_effect: Literal["resists", "overturns"]


@dataclass(frozen=True)
class StabilityLedger:
    """Every force and moment contribution, with the framework's action
    factors already resolvable per row -- :func:`~.checks` (sliding,
    eccentricity, bearing) all read from one of these rather than
    re-deriving the force balance independently."""

    rows: tuple[LedgerRow, ...]
    factors: FactorSet

    def _factor(self, row: LedgerRow) -> float:
        return (
            self.factors.actions.stabilising
            if row.force_kind == "stabilising"
            else self.factors.actions.destabilising
        )

    @property
    def V_star(self) -> float:  # noqa: N802
        """Total design vertical force, kN/m -- the normal force on the base."""
        return sum(row.force * self._factor(row) for row in self.rows if row.axis == "vertical")

    @property
    def H_star(self) -> float:  # noqa: N802
        """Total design horizontal driving force, kN/m."""
        return sum(row.force * self._factor(row) for row in self.rows if row.axis == "horizontal")

    @property
    def M_resisting_star(self) -> float:  # noqa: N802
        """Design resisting moment about the toe, kN.m/m."""
        return sum(
            row.force * self._factor(row) * row.arm
            for row in self.rows
            if row.moment_effect == "resists"
        )

    @property
    def M_overturning_star(self) -> float:  # noqa: N802
        """Design overturning moment about the toe, kN.m/m."""
        return sum(
            row.force * self._factor(row) * row.arm
            for row in self.rows
            if row.moment_effect == "overturns"
        )

    def describe(self) -> list[str]:
        lines = [f"{'Row':<24}{'Force':>10}{'Factor':>8}{'Arm':>8}{'kind':>14}"]
        for row in self.rows:
            lines.append(
                f"{row.label:<24}{row.force:>10.2f}{self._factor(row):>8.2f}"
                f"{row.arm:>8.2f}  {row.force_kind}/{row.moment_effect}"
            )
        return lines


def build_ledger(
    wall: WallInput,
    resolved: ResolvedSoil,
    design: DesignSoil,
    thrust_horizontal: float,
    thrust_vertical: float,
    thrust_height: float,
    hydrostatic_horizontal: float,
    hydrostatic_height: float,
    factors: FactorSet,
) -> StabilityLedger:
    """Assemble every row of the stability ledger for one wall.

    Takes the earth-pressure thrust as plain floats rather than importing
    :mod:`.pressure.rankine`'s result type -- that module depends on this
    one for :class:`DesignSoil`, so the dependency only runs one way.
    """
    geometry = wall.geometry
    footing, stem = concrete_self_weight(geometry)
    heel = heel_soil_weight(geometry, resolved.gamma.value, resolved.surcharge.value)

    rows = [
        LedgerRow(footing.label, footing.weight, footing.arm, "vertical", "stabilising", "resists"),
        LedgerRow(stem.label, stem.weight, stem.arm, "vertical", "stabilising", "resists"),
        LedgerRow(
            heel.soil_weight.label, heel.soil_weight.weight, heel.soil_weight.arm,
            "vertical", "stabilising", "resists",
        ),
        LedgerRow(
            heel.surcharge_weight.label, heel.surcharge_weight.weight, heel.surcharge_weight.arm,
            "vertical", "stabilising", "resists",
        ),
        LedgerRow(
            "Earth pressure, horizontal", thrust_horizontal, thrust_height,
            "horizontal", "destabilising", "overturns",
        ),
        LedgerRow(
            "Hydrostatic thrust", hydrostatic_horizontal, hydrostatic_height,
            "horizontal", "destabilising", "overturns",
        ),
    ]
    if thrust_vertical != 0.0:
        # Present only with a backslope. Classified `destabilising` for its
        # FACTOR (it is part of the earth-pressure action) but `resists` for
        # its MOMENT (it acts at the back of the footing, which helps against
        # overturning about the toe) -- see the module note above.
        rows.append(
            LedgerRow(
                "Earth pressure, vertical component", thrust_vertical, geometry.base_length,
                "vertical", "destabilising", "resists",
            )
        )

    return StabilityLedger(rows=tuple(rows), factors=factors)
