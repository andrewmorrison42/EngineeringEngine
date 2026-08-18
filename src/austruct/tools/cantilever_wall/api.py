"""``analyse`` -- the one entry point this tool exposes.

Takes a validated :class:`~.models.WallInput`, returns a validated
:class:`~.models.WallResult`. Everything between the two is plain Python in
this tool's own m/kN/kPa convention -- see :mod:`.engine` and
:mod:`.pressure.rankine`.
"""

from __future__ import annotations

from . import engine, member_design
from .checks import check_bearing, check_eccentricity, check_sliding
from .divergence import compare_thrust
from .factor_sets import load_factor_set
from .models import CheckSummary, DivergenceSummary, MethodResult, WallInput, WallResult
from .pressure.culmann import culmann_report, trial_wedge_thrust
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
        Every check plus both earth-pressure methods (where Method B could
        run), their divergence, and the full assumed-vs-supplied input
        list, in one serialisable, composable object -- see
        :mod:`austruct.tools.contracts.base` for what "composable" means
        here.

    Notes
    -----
    Method B (the Culmann trial wedge) does not yet model a water table --
    see ``pressure/culmann.py``. Where ``resolved_soil.water_table`` is set,
    ``method_b`` and ``divergence`` come back ``None`` rather than either
    raising or comparing a submerged Method A against a dry Method B, which
    would be misleading -- see ``notes`` for confirmation this happened.
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

    member_ledger = member_design.member_design_ledger(wall, resolved, design)
    stem = member_design.design_stem(wall, resolved, design)
    toe = member_design.design_toe(wall, member_ledger)
    heel = member_design.design_heel(wall, resolved, member_ledger)

    checks = {
        "sliding": _summarise(sliding_result),
        "eccentricity": _summarise(eccentricity_result),
        "bearing": _summarise(bearing_result),
        "stem_flexure": _summarise(stem.flexure),
        "stem_shear": _summarise(stem.shear),
        "toe_flexure": _summarise(toe.flexure),
        "toe_shear": _summarise(toe.shear),
        "heel_flexure": _summarise(heel.flexure),
        "heel_shear": _summarise(heel.shear),
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

    notes = [
        "Stem/heel/toe concrete design uses AS 1170.0-style load factors "
        "(1.35 permanent, 1.5 variable), NOT the AS 4678 stability factors "
        "above -- see member_design.py's module docstring for why.",
        "The global-stability geometry screen is not yet implemented.",
        "Shear key resistance is not modelled -- sliding resistance is "
        "friction, adhesion and passive only.",
    ]

    method_b: MethodResult | None = None
    divergence: DivergenceSummary | None = None
    try:
        wedge = trial_wedge_thrust(
            H, design, resolved.gamma.value, resolved.backslope.value,
            resolved.surcharge.value, resolved.water_table,
        )
        wedge_working = culmann_report(
            H, design, resolved.gamma.value, resolved.backslope.value,
            resolved.surcharge.value, resolved.water_table,
        )
        method_b = MethodResult(
            method="culmann",
            Ka=None,
            Kp=None,
            thrust_horizontal=wedge.thrust.horizontal,
            thrust_vertical=wedge.thrust.vertical,
            thrust_height=wedge.thrust.height,
            hydrostatic_horizontal=0.0,
            critical_wedge_angle=wedge.theta_deg,
            working=wedge_working.to_dict(),
        )
        d = compare_thrust(
            method_a.thrust_horizontal, method_b.thrust_horizontal,
            resolved.backslope.value, design.cohesion,
        )
        divergence = DivergenceSummary(
            quantity=d.quantity, value_a=d.value_a, value_b=d.value_b,
            divergence=d.divergence, band=d.band, cause=d.cause,
        )
        if divergence.band == "flag":
            notes.append(
                f"Methods A and B diverge by {divergence.divergence:.1%} on "
                "horizontal thrust -- over the adjudication threshold. See "
                "'divergence' for the likely cause; do not average the two."
            )
    except NotImplementedError as exc:
        notes.append(f"Method B not run: {exc}")

    governing = max(c.utilisation for c in checks.values())
    passed = all(c.passed for c in checks.values()) and (
        divergence is None or divergence.band != "flag"
    )

    return WallResult(
        framework=framework,
        resolved_soil=resolved,
        method_a=method_a,
        method_b=method_b,
        divergence=divergence,
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
