"""Course-to-course interface shear -- internal stability, FS-based.

Unique to modular/segmental gravity systems: a cantilever or gravity
concrete wall is one monolithic (or continuously reinforced) section, but a
block wall is a stack of discrete units, and nothing stops one course
sliding relative to the course below except the interface's own shear
capacity -- a pin, a lip, a keyway, or simple friction under the blocks
above. This tool models that capacity as a simple linear Mohr-Coulomb
interface law, ``capacity = c_interface + N.tan(delta_interface)``, checked
at EVERY interface up the wall and reported at whichever governs.

[VECTOR] This is a deliberate simplification of how these interfaces are
         actually characterised in practice: manufacturers test their own
         connector detail per ASTM D6916 and publish a bilinear
         peak/then-residual envelope (capacity does not keep rising
         linearly with normal load forever -- it peaks, then the connector
         itself becomes the limit). A single straight line is conservative
         at low normal load and potentially UNCONSERVATIVE at high normal
         load (tall walls, many courses above) if used past where the real
         envelope has gone bilinear -- do not extrapolate this check to a
         very tall wall without a manufacturer's actual test data.
"""

from __future__ import annotations

import math

from ....core.basis import NCMA_SRW_MANUAL, Basis, ClauseRef
from ....core.contract import CalcResult, Check, Value
from ....core.envelope import Envelope
from ....core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ....core.registry import REGISTRY
from ...cantilever_wall.models import ResolvedSoil
from ..engine import CourseWeight
from ..factors import FS_INTERFACE_SHEAR
from ..models import GravityWallInput
from ..pressure import active_thrust

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Course-to-course interface shear, FS-based -- internal stability",
    envelope_summary="Linear Mohr-Coulomb interface law -- see the module note",
)

CLAUSE_INTERFACE = ClauseRef(NCMA_SRW_MANUAL, note="Internal stability, interface shear")


def check_interface_shear(
    wall: GravityWallInput,
    resolved: ResolvedSoil,
    courses: tuple[CourseWeight, ...],
    omega_deg: float,
) -> CalcResult:
    """Interface shear at every course boundary; reports the governing one.

    ``omega_deg`` -- pass it straight through from whatever value was used
    for the wall's own :func:`~austruct.tools.gravity_wall.pressure.active_thrust`
    call (already in :func:`~austruct.tools.gravity_wall.pressure.Ka_coulomb`'s
    sign convention, i.e. already negated from ``batter_deg`` -- see
    :mod:`.api`); this function does not re-derive it.

    At interface ``i`` (between course ``i-1`` and course ``i``, counting
    from the base), the driving force is the horizontal earth-pressure
    thrust on the wall ABOVE that interface's elevation -- the shorter
    "wall" formed by every course above it, pushed on by the same Coulomb
    pressure diagram, integrated only over its own height. The resisting
    normal force is the self-weight of every course above the interface
    (its own gravity mass, clamping the interface below it).
    """
    env = Envelope(name="Interface shear")
    env.note("Linear Mohr-Coulomb interface law -- see the module note.")
    env.require()

    basis = Basis()
    basis.add(CLAUSE_INTERFACE)

    n = len(courses)
    rows: list[dict[str, float]] = []
    for i in range(1, n):
        # Courses i..n-1 sit above this interface; their combined height is
        # the "sub-wall" the pressure diagram integrates over.
        above = courses[i:]
        h_above = above[-1].elevation_top - above[0].elevation_bottom
        thrust_above = active_thrust(h_above, resolved, omega_deg)
        N = sum(c.weight for c in above)
        capacity = wall.c_interface + N * math.tan(math.radians(wall.delta_interface))
        demand = thrust_above.horizontal
        FS = capacity / demand if demand > 0 else float("inf")
        rows.append(
            {
                "interface": float(i),
                "elevation": above[0].elevation_bottom,
                "N": N,
                "demand": demand,
                "capacity": capacity,
                "FS": FS,
            }
        )

    governing = min(rows, key=lambda r: r["FS"]) if rows else {
        "interface": 0.0, "elevation": 0.0, "N": 0.0, "demand": 0.0,
        "capacity": float("inf"), "FS": float("inf"),
    }

    result = CalcResult(
        name="Course-to-course interface shear, FS-based -- internal stability",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )
    result.add_input(
        "delta_interface", Value(wall.delta_interface, "deg", "delta_i", "Interface friction angle")
    )
    result.add_input("c_interface", Value(wall.c_interface, "kN/m", "c_i", "Interface cohesion"))
    result.add_intermediate(
        "governing_interface", Value(governing["interface"], "-", "i", "Governing interface index")
    )
    result.add_intermediate(
        "governing_elevation", Value(governing["elevation"], "m", "z_i", "Elevation above base")
    )
    result.add_output("N", Value(governing["N"], "kN/m", "N", "Normal force above the governing interface"))
    result.add_output("demand", Value(governing["demand"], "kN/m", "H_i", "Shear demand at the governing interface"))
    result.add_output("capacity", Value(governing["capacity"], "kN/m", "R_i", "Interface shear capacity"))
    result.add_output("FS", Value(governing["FS"], "-", "FS", "Factor of safety, governing interface"))

    result.add_check(
        Check(
            label="Interface shear, FS >= 1.5 (governing interface)",
            actual=governing["FS"],
            limit=FS_INTERFACE_SHEAR,
            operator=">=",
            unit="-",
            basis=CLAUSE_INTERFACE,
        )
    )

    if not rows:
        result.note("Single-course wall -- no interface exists to check.")
    else:
        for r in rows:
            result.note(
                f"Interface {int(r['interface'])} (z={r['elevation']:.2f} m): "
                f"demand={r['demand']:.1f} kN/m, capacity={r['capacity']:.1f} kN/m, "
                f"FS={r['FS']:.2f}"
            )

    return result
