"""Stem, heel and toe reinforced-concrete design, AS 3600:2018.

The stability checks (sliding, eccentricity, bearing) answer "does this
wall stand up". This module answers the question that follows from a
passing stability check: "what reinforcement does the concrete need". Every
mechanism here is `design.as3600` unmodified -- `required_steel_area`,
`check_shear`, `rc_beam` -- called with the actions this tool's own
geometry and pressure methods derive; nothing here is new concrete
mechanics.

A DIFFERENT factor regime from the stability checks -- on purpose
------------------------------------------------------------------
`checks/sliding.py`, `checks/eccentricity.py` and `checks/bearing.py` all
read a `StabilityLedger` built with the AS 4678 FRAMEWORK's factors
(`FactorSet.actions.stabilising`/`.destabilising`), because those factors
are calibrated for the OVERALL STABILITY question -- does self-weight
resist overturning enough. That classification is meaningless for a local
member: heel self-weight does not "resist" anything from the heel slab's
own point of view, it is simply a load the slab bends under. So member
design here uses its own, much simpler pair of load factors --
`DEAD_LOAD_FACTOR` (self-weight, retained soil weight) and
`VARIABLE_LOAD_FACTOR` (surcharge, and via the bearing pressure, the earth
pressure that put it there) -- in the AS 1170.0 sense, not the AS 4678
sense. `member_design_ledger()` still reuses `engine.build_ledger` for the
one thing that genuinely is a whole-footing question either way -- the
design vertical force and eccentricity that set the bearing pressure
distribution -- via an ad-hoc `FactorSet` built from these two factors, not
loaded from a YAML file (it is not a verification framework a client
specifies, it is this module's own AS 1170.0-style load combination).

Two simplifications, stated plainly
------------------------------------
- The bearing pressure under the footing is taken as fully linear
  (`q(x)` triangular/trapezoidal) even where the member-design eccentricity
  exceeds B/6 (partial uplift). The geotechnical `check_eccentricity` in
  `checks/` already flags e/B > the framework's limit as a FAILING check
  using the AS 4678-factored ledger -- a wall that reaches this module with
  that check failing has a governing result elsewhere in `WallResult`, and
  the heel/toe numbers here are informative, not the wall's governing
  answer, in that regime.
- ``required_steel_area`` bisects on STRENGTH (M* <= phi.M_uo) only -- it
  does not iterate further for AS 3600 Cl 8.1.6.1's minimum-strength check
  (M_uo >= 1.2 M_cr), which `check_flexure` still applies and reports. A
  thick, lightly-loaded footing slab -- routinely the case for a toe or
  heel sized by geotechnical bearing rather than by its own bending -- can
  therefore come back with a FAILING flexure result even though the
  strength check alone passes at exactly 1.000: the minimum-strength check
  is the one that governs, and it is asking for more steel than the applied
  moment alone would. This is real, common behaviour for a retaining wall
  footing, not a bug to route around -- see the check breakdown in
  ``examples/10_cantilever_wall.py``.
- Tension is assumed on the soil-facing (top) side for BOTH the heel and
  the toe, matching the case where upward bearing pressure governs over
  self-weight relief -- the common case. This module does not detect the
  opposite (a very lightly loaded footing where self-weight relief
  dominates); check that case by hand if it looks close.

[UNITS] This module's inputs are the tool's own convention (m, kN/m^3, kPa,
degrees) -- see :mod:`.models`. It converts to mm/N/MPa at the boundary
with `design.as3600`, and only there.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.contract import CalcResult
from ...core.units import kN, kNm
from ...design.as3600.flexure import required_steel_area
from ...design.as3600.shear import check_shear
from ...materials.concrete import concrete as concrete_grade
from ...sections.rc_section import RebarLayer, rc_beam
from .engine import CONCRETE_UNIT_WEIGHT, DesignSoil, StabilityLedger, build_ledger
from .factor_sets import (
    ActionFactors,
    BearingFactors,
    EccentricityFactors,
    FactorSet,
    MaterialFactors,
    SlidingFactors,
)
from .models import ResolvedSoil, WallInput
from .pressure.rankine import active_thrust, hydrostatic_thrust

DEAD_LOAD_FACTOR = 1.35
"""AS 1170.0-style factor on permanent actions (self-weight, retained soil
weight) for MEMBER strength design. [VECTOR] UNVERIFIED, and a genuinely
different number from anything in `factor_sets.py` -- see the module note
on why member design does not reuse the AS 4678 stability factors."""

VARIABLE_LOAD_FACTOR = 1.5
"""AS 1170.0-style factor on variable/environmental actions (surcharge,
earth pressure, hydrostatic thrust) for MEMBER strength design. [VECTOR]
UNVERIFIED."""

MEMBER_DESIGN_FACTORS = FactorSet(
    name="Member design (AS 1170.0-style)",
    standard="AS 1170.0:2002 (illustrative combination, not a cited clause)",
    material=MaterialFactors(phi_ug_factor=1.0, cohesion_factor=1.0),
    actions=ActionFactors(stabilising=DEAD_LOAD_FACTOR, destabilising=VARIABLE_LOAD_FACTOR),
    # Unused by member design -- present only because FactorSet requires
    # them. 1.0 reads as "no reduction", which is correct: nothing in this
    # module calls check_sliding/check_bearing/check_eccentricity against
    # this factor set, so these values are never actually applied to anything.
    sliding=SlidingFactors(friction_reduction=1.0),
    bearing=BearingFactors(geotechnical_reduction=1.0),
    eccentricity=EccentricityFactors(max_e_over_b=1.0),
)


def member_design_ledger(wall: WallInput, resolved: ResolvedSoil, design: DesignSoil) -> StabilityLedger:
    """The whole-footing force/moment ledger, on MEMBER_DESIGN_FACTORS
    rather than the framework's factors -- used only to get the design
    vertical force and eccentricity that set the bearing pressure
    distribution :func:`bearing_pressure` needs."""
    H = wall.geometry.H_retained
    thrust = active_thrust(
        H, design, resolved.gamma.value, resolved.backslope.value,
        resolved.surcharge.value, resolved.water_table,
    )
    hydro = hydrostatic_thrust(H, resolved.water_table)
    return build_ledger(
        wall, resolved, design,
        thrust.horizontal, thrust.vertical, thrust.height,
        hydro.horizontal, hydro.height,
        MEMBER_DESIGN_FACTORS,
    )


def eccentricity(ledger: StabilityLedger, base_length: float) -> float:
    """e = B/2 - x_bar, the same formula `checks/eccentricity.py` uses --
    duplicated rather than imported because that module's CalcResult is
    tied to the AS 4678 clause basis, which does not apply to this
    member-design ledger."""
    x_bar = (ledger.M_resisting_star - ledger.M_overturning_star) / ledger.V_star
    return base_length / 2.0 - x_bar


def bearing_pressure(x: float, V_star: float, e: float, base_length: float) -> float:  # noqa: N803
    """Linear bearing pressure at ``x`` (m from the toe), kPa.

    Standard trapezoidal/triangular distribution: q(0) = V*/B.(1+6e/B) at
    the toe (nearer the resultant when e > 0), q(B) = V*/B.(1-6e/B) at the
    heel. See the module docstring for the e/B > 1/6 (partial uplift)
    caveat.
    """
    B = base_length
    q_toe = V_star / B * (1.0 + 6.0 * e / B)
    q_heel = V_star / B * (1.0 - 6.0 * e / B)
    return q_toe + (q_heel - q_toe) * (x / B)


@dataclass(frozen=True)
class MemberDesign:
    """Flexure and shear results for one member (stem, heel or toe)."""

    flexure: CalcResult
    shear: CalcResult

    @property
    def passed(self) -> bool:
        return self.flexure.passed and self.shear.passed

    @property
    def utilisation(self) -> float:
        return max(self.flexure.utilisation, self.shear.utilisation)


def _template_section(thickness_m: float, wall: WallInput):
    """A trial 1 m strip section, thickness converted from this tool's
    metres convention to austruct core's mm convention."""
    return rc_beam(
        b=1000.0, D=thickness_m * 1000.0, concrete=concrete_grade(wall.concrete_fc),
        cover=wall.cover,
    )


def _flexure_then_shear(section, M_star_kNm: float, V_star_kN: float) -> MemberDesign:  # noqa: N803
    """Size the tensile steel for ``M_star_kNm``, then check shear on the
    ACTUAL designed section (a real reinforcement layer at the flexural
    solution's area and depth) rather than an empty template -- `d_o`
    (needed by the shear provisions' k_v term) is only defined once a
    section has reinforcement.
    """
    flexure = required_steel_area(section, abs(M_star_kNm) * kNm)
    designed = section.add_layer(
        RebarLayer(area=flexure.get("Ast_req"), depth=flexure.get("d"))
    )
    shear = check_shear(designed, abs(V_star_kN) * kN)
    return MemberDesign(flexure=flexure, shear=shear)


def design_stem(wall: WallInput, resolved: ResolvedSoil, design: DesignSoil) -> MemberDesign:
    """Stem flexure and shear at the top of the footing, from the earth
    pressure acting over the STEM HEIGHT ONLY -- the same
    :func:`~.pressure.rankine.active_thrust` call used for the whole wall,
    with ``H = stem_height`` instead of ``H_retained``, which is valid
    because the pressure intensity at a given depth does not depend on the
    total height being integrated over (see that function's docstring).
    """
    geometry = wall.geometry
    H = geometry.stem_height
    thrust = active_thrust(
        H, design, resolved.gamma.value, resolved.backslope.value,
        resolved.surcharge.value, resolved.water_table,
    )
    hydro = hydrostatic_thrust(H, resolved.water_table)

    M_star = VARIABLE_LOAD_FACTOR * (thrust.horizontal * thrust.height + hydro.horizontal * hydro.height)
    V_star = VARIABLE_LOAD_FACTOR * (thrust.horizontal + hydro.horizontal)

    section = _template_section(geometry.stem_thickness_bottom, wall)
    return _flexure_then_shear(section, M_star, V_star)


def design_toe(wall: WallInput, ledger: StabilityLedger) -> MemberDesign:
    """Toe flexure and shear at the front face of the stem: upward bearing
    pressure over the toe, less the toe's own self-weight."""
    geometry = wall.geometry
    B = geometry.base_length
    L = geometry.toe_length
    V_star = ledger.V_star
    e = eccentricity(ledger, B)

    q_toe_edge = bearing_pressure(0.0, V_star, e, B)
    q_junction = bearing_pressure(L, V_star, e, B)
    M_bearing = L**2 * (q_junction + 2.0 * q_toe_edge) / 6.0
    V_bearing = (q_toe_edge + q_junction) / 2.0 * L

    self_weight = DEAD_LOAD_FACTOR * (L * geometry.base_thickness * CONCRETE_UNIT_WEIGHT)
    M_self_weight = self_weight * (L / 2.0)

    M_star = M_bearing - M_self_weight
    V_star_toe = V_bearing - self_weight

    section = _template_section(geometry.base_thickness, wall)
    return _flexure_then_shear(section, M_star, V_star_toe)


def design_heel(wall: WallInput, resolved: ResolvedSoil, ledger: StabilityLedger) -> MemberDesign:
    """Heel flexure and shear at the back face of the stem: soil, surcharge
    and heel self-weight, less the upward bearing pressure over the heel."""
    geometry = wall.geometry
    B = geometry.base_length
    L = geometry.heel_length
    x_junction = geometry.toe_length + geometry.stem_thickness_bottom
    V_star = ledger.V_star
    e = eccentricity(ledger, B)

    q_junction = bearing_pressure(x_junction, V_star, e, B)
    q_heel_edge = bearing_pressure(B, V_star, e, B)
    M_bearing = L**2 * (q_junction + 2.0 * q_heel_edge) / 6.0
    V_bearing = (q_junction + q_heel_edge) / 2.0 * L

    soil_weight = L * geometry.stem_height * resolved.gamma.value
    concrete_weight = L * geometry.base_thickness * CONCRETE_UNIT_WEIGHT
    surcharge_weight = L * resolved.surcharge.value

    M_downward = (
        DEAD_LOAD_FACTOR * (soil_weight + concrete_weight) * (L / 2.0)
        + VARIABLE_LOAD_FACTOR * surcharge_weight * (L / 2.0)
    )
    V_downward = DEAD_LOAD_FACTOR * (soil_weight + concrete_weight) + VARIABLE_LOAD_FACTOR * surcharge_weight

    M_star = M_downward - M_bearing
    V_star_heel = V_downward - V_bearing

    section = _template_section(geometry.base_thickness, wall)
    return _flexure_then_shear(section, M_star, V_star_heel)
