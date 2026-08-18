"""``analyse`` -- the one entry point this tool exposes.

Takes a validated :class:`~.models.GravityWallInput`, returns a validated
:class:`~.models.GravityWallResult`. See :mod:`.models`'s module docstring
for why this tool's methodology (FS-based, characteristic soil throughout)
is deliberately different from ``cantilever_wall``'s (limit-state, factored
soil strength), even though both are "a retaining wall assessment" and
both reuse the same soil model.
"""

from __future__ import annotations

from ..cantilever_wall.engine import resolve_soil
from . import engine
from .checks import check_bearing, check_interface_shear, check_overturning, check_sliding
from .factors import FS_GLOBAL_STABILITY
from .models import CheckSummary, GravityWallInput, GravityWallResult, PressureSummary
from .pressure import active_thrust, coulomb_report

FRAMEWORK = "ncma_style_asd"


def analyse(wall: GravityWallInput) -> GravityWallResult:
    """Run the full gravity (modular block) wall assessment.

    Returns
    -------
    GravityWallResult
        The Coulomb active-pressure working, every FS-based check
        (sliding, overturning, bearing, interface shear), and the full
        assumed-vs-supplied soil input list, in one serialisable,
        composable object -- see :mod:`austruct.tools.contracts.base` for
        what "composable" means here.
    """
    resolved = resolve_soil(wall.soil)
    geometry = wall.geometry
    # Ka_coulomb's omega is positive INTO the backfill; a block wall's
    # physical batter (always positive, see BlockSeries.batter_deg) recedes
    # AWAY from the backfill, so it is passed here negated -- see
    # pressure.Ka_coulomb's docstring for the sign convention and the
    # regression test that pins the direction.
    omega_deg = -geometry.batter_deg

    thrust = active_thrust(geometry.H, resolved, omega_deg)
    pressure_working = coulomb_report(geometry.H, resolved, omega_deg)

    ledger = engine.build_ledger(geometry, thrust)

    sliding_result = check_sliding(wall, resolved, ledger)
    overturning_result = check_overturning(ledger)
    bearing_result = check_bearing(wall, resolved, ledger)
    interface_result = check_interface_shear(wall, resolved, ledger.courses, omega_deg)

    checks = {
        "sliding": _summarise(sliding_result),
        "overturning": _summarise(overturning_result),
        "bearing": _summarise(bearing_result),
        "interface_shear": _summarise(interface_result),
    }

    pressure = PressureSummary(
        Ka=pressure_working.get("Ka"),
        thrust_horizontal=thrust.horizontal,
        thrust_vertical=thrust.vertical,
        thrust_height=thrust.height,
        working=pressure_working.to_dict(),
    )

    notes = [
        f"Global stability (deep-seated slip circle through and behind the "
        f"wall, FS >= {FS_GLOBAL_STABILITY}) is not computed -- no geometry "
        "screen exists for it, the same limitation cantilever_wall has. "
        "Engineer to check externally, especially for a tall wall on a "
        "sloping site.",
        "Geogrid soil reinforcement is out of scope -- this tool models a "
        "GRAVITY block wall (mass alone provides stability); a reinforced "
        "segmental retaining wall (geogrid layers extending into the "
        "backfill) is a materially different design problem, not covered "
        "here.",
        "Interface shear uses a simplified linear Mohr-Coulomb interface "
        "law -- see checks/interface_shear.py's module note on why a real "
        "manufacturer's ASTM D6916 envelope may diverge from this at high "
        "normal load (a tall wall's lower courses).",
    ]

    governing = max(c.utilisation for c in checks.values())
    passed = all(c.passed for c in checks.values())

    return GravityWallResult(
        framework=FRAMEWORK,
        resolved_soil=resolved,
        pressure=pressure,
        checks=checks,
        governing_utilisation=governing,
        passed=passed,
        assumptions=resolved.assumptions(),
        notes=notes,
    )


def _summarise(result) -> CheckSummary:  # CalcResult, not type-hinted to avoid a core.contract import cycle here
    return CheckSummary(
        label=result.name,
        passed=result.passed,
        utilisation=result.utilisation,
        working=result.to_dict(),
    )
