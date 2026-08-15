"""``analyse`` -- the one entry point this tool exposes.

Takes a validated :class:`~.models.WallInput`, returns a validated
:class:`~.models.WallResult`. Everything between the two is plain Python in
this tool's own m/kN/kPa convention -- see :mod:`.engine` and
:mod:`.pressure.rankine`.
"""

from __future__ import annotations

from . import engine
from .checks import check_bearing, check_eccentricity, check_sliding
from .factor_sets import load_factor_set
from .models import CheckSummary, MethodResult, WallInput, WallResult
from .pressure.rankine import active_thrust, hydrostatic_thrust, rankine_report


def analyse(wall: WallInput, framework: str = "as4678_class_b") -> WallResult:
    """Run the full cantilever wall assessment.

    Parameters
    ----------
    wall:
        Validated input.
    framework:
        A name from :data:`~.factor_sets.KNOWN_FRAMEWORKS`.

    Returns
    -------
    WallResult
        Every check plus the earth-pressure method result and the full
        assumed-vs-supplied input list, in one serialisable, composable
        object -- see :mod:`austruct.tools.contracts.base` for what
        "composable" means here.

    Notes
    -----
    Only Method A (Rankine, closed form) is implemented -- see the package
    README for what a trial-wedge Method B and the resulting divergence
    report would add. ``WallResult`` carries one method result, not two,
    until that lands; nothing here silently claims agreement between methods
    that were never actually compared.
    """
    factors = load_factor_set(framework)

    resolved = engine.resolve_soil(wall.soil)
    design = engine.apply_material_factors(resolved, factors)

    H = wall.geometry.H_retained
    thrust = active_thrust(
        H, design, resolved.gamma.value, resolved.backslope.value,
        resolved.surcharge.value, resolved.water_table,
    )
    hydro = hydrostatic_thrust(H, resolved.water_table)
    pressure_working = rankine_report(
        H, design, resolved.gamma.value, resolved.backslope.value,
        resolved.surcharge.value, resolved.water_table,
    )

    ledger = engine.build_ledger(
        wall, resolved, design,
        thrust.horizontal, thrust.vertical, thrust.height,
        hydro.horizontal, hydro.height,
        factors,
    )

    sliding_result = check_sliding(wall, design, resolved.gamma.value, ledger, wall.passive_neglect_depth)
    eccentricity_result = check_eccentricity(wall, ledger)
    e = eccentricity_result.get("e")
    bearing_result = check_bearing(wall, design, resolved.gamma.value, ledger, e)

    checks = {
        "sliding": _summarise(sliding_result),
        "eccentricity": _summarise(eccentricity_result),
        "bearing": _summarise(bearing_result),
    }

    method_a = MethodResult(
        method="rankine",
        Ka=pressure_working.get("Ka"),
        Kp=None,
        thrust_horizontal=thrust.horizontal,
        thrust_vertical=thrust.vertical,
        thrust_height=thrust.height,
        hydrostatic_horizontal=hydro.horizontal,
        critical_wedge_angle=None,
        working=pressure_working.to_dict(),
    )

    governing = max(c.utilisation for c in checks.values())
    passed = all(c.passed for c in checks.values())

    notes = [
        "Only Method A (Rankine, closed form) has been run -- no Method B "
        "trial wedge yet, so no divergence report is produced.",
        "Stem/heel/toe reinforced-concrete design (AS 3600:2018) and the "
        "global-stability geometry screen are not yet implemented.",
        "Shear key resistance is not modelled -- sliding resistance is "
        "friction, adhesion and passive only.",
    ]

    return WallResult(
        framework=framework,
        resolved_soil=resolved,
        method_a=method_a,
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
