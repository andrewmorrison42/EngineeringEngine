"""Example 10 -- a cantilever retaining wall, AS 4678:2002 + AS 3600:2018.

  1. Usable with geometry plus one soil type -- everything else defaults,
     and every default is tagged so it is visible, not hidden.
  2. AS 4678 material factors flow into the pressure calculation itself,
     not bolted on afterwards.
  3. The stability ledger -- every force, its factor, its arm.
  4. Sliding, eccentricity, bearing -- ranked by utilisation, not pass/fail.
  5. Stem/heel/toe concrete design -- and the check that actually governs.
  6. Method B (trial wedge): the degenerate case matches Method A exactly;
     backslope is a REAL divergence, not a bug -- and the divergence report
     says so.
  7. The same wall, undersized -- and WHICH check catches it.
  8. Composition: save the result, reload it, and the full working survives.

Run:  python examples/10_cantilever_wall.py

NOTE: every AS 4678/AS 3600 factor here is [VECTOR] UNVERIFIED, as is the
soil preset library and the Terzaghi/Meyerhof bearing capacity formula.
This example demonstrates the PLUMBING, not a checked design.
"""

from pathlib import Path

from austruct.tools.cantilever_wall import SoilInput, WallGeometry, WallInput, analyse
from austruct.tools.cantilever_wall.engine import (
    apply_material_factors,
    build_ledger,
    resolve_soil,
)
from austruct.tools.cantilever_wall.factor_sets import load_factor_set
from austruct.tools.cantilever_wall.models import WallResult
from austruct.tools.cantilever_wall.pressure.rankine import active_thrust, hydrostatic_thrust
from austruct.tools.contracts.base import load_result, save_result

STABILITY_CHECKS = ("sliding", "eccentricity", "bearing")
MEMBER_CHECKS = (
    "stem_flexure", "stem_shear", "toe_flexure", "toe_shear", "heel_flexure", "heel_shear",
)


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


def print_checks(result, keys) -> None:
    print(f"{'Check':<16}{'Utilisation':>12}{'Status':>10}")
    print("-" * 38)
    for name in sorted(keys, key=lambda k: -result.checks[k].utilisation):
        c = result.checks[name]
        print(f"{name:<16}{c.utilisation:>12.3f}{'PASS' if c.passed else 'FAIL':>10}")


# ---------------------------------------------------------------------------
banner("1 | GEOMETRY PLUS ONE SOIL TYPE -- EVERYTHING ELSE DEFAULTS")
# ---------------------------------------------------------------------------
geometry = WallGeometry(
    H_retained=4.0,
    base_length=3.6,
    base_thickness=0.55,
    toe_length=1.0,
    stem_thickness_top=0.3,
    stem_thickness_bottom=0.45,
)
soil = SoilInput(soil_type="clean_sand", surcharge=5.0, water_table=None)
wall = WallInput(geometry=geometry, soil=soil)

print(f"Heel length (derived)  = {geometry.heel_length:.2f} m")
print(f"Stem height (derived)  = {geometry.stem_height:.2f} m")

result = analyse(wall)
print("\nEvery value NOT explicitly supplied, tagged with where it came from:")
for line in result.assumptions:
    print(f"  {line}")
print(
    "\n  phi, gamma and cohesion came from the 'clean_sand' preset -- they "
    "would be tagged 'preset' here too if the assumptions list showed every "
    "field rather than only the ones this run left at a default; check "
    "result.resolved_soil directly for the full picture:"
)
for field in ("phi", "gamma", "cohesion", "delta", "backslope", "surcharge"):
    sourced = getattr(result.resolved_soil, field)
    print(f"    {field:<10} = {sourced.value:>6.2f}  ({sourced.source})")

# ---------------------------------------------------------------------------
banner("2 | MATERIAL FACTORS FLOW INTO THE PRESSURE CALCULATION")
# ---------------------------------------------------------------------------
factors = load_factor_set("as4678_class_b")
resolved = resolve_soil(soil)
design = apply_material_factors(resolved, factors)
print(f"Characteristic phi = {resolved.phi.value:.1f} deg")
print(f"Design phi         = {design.phi_deg:.1f} deg  "
      f"(tan(phi) x {factors.material.phi_ug_factor})")
print(
    "\n  This design phi -- not the characteristic value -- is what Ka in the "
    "Rankine calculation below actually used. AS 4678 factors soil strength "
    "before the pressure calculation, not the resulting thrust afterwards."
)

# ---------------------------------------------------------------------------
banner("3 | THE STABILITY LEDGER")
# ---------------------------------------------------------------------------
thrust = active_thrust(
    geometry.H_retained, design, resolved.gamma.value, resolved.backslope.value,
    resolved.surcharge.value, resolved.water_table,
)
hydro = hydrostatic_thrust(geometry.H_retained, resolved.water_table)
ledger = build_ledger(
    wall, resolved, design, thrust.horizontal, thrust.vertical, thrust.height,
    hydro.horizontal, hydro.height, factors,
)
print("\n".join(ledger.describe()))
print(f"\n  V*  = {ledger.V_star:.1f} kN/m")
print(f"  H*  = {ledger.H_star:.1f} kN/m")
print(f"  Mr* = {ledger.M_resisting_star:.1f} kN.m/m")
print(f"  Mo* = {ledger.M_overturning_star:.1f} kN.m/m")

# ---------------------------------------------------------------------------
banner("4 | SLIDING, ECCENTRICITY, BEARING -- RANKED BY UTILISATION")
# ---------------------------------------------------------------------------
print_checks(result, STABILITY_CHECKS)
print(
    "\n  utilisation ranks the checks for free -- no separate 'which one "
    "governs' logic, the highest number already is the answer."
)

# ---------------------------------------------------------------------------
banner("5 | STEM/HEEL/TOE CONCRETE DESIGN -- AND WHAT ACTUALLY GOVERNS")
# ---------------------------------------------------------------------------
print_checks(result, MEMBER_CHECKS)
print(f"\nOverall (stability + member design): "
      f"{'PASS' if result.passed else 'FAIL'}, "
      f"governing utilisation {result.governing_utilisation:.3f}")

toe_flexure = result.checks["toe_flexure"].working
strength = next(c for c in toe_flexure["checks"] if "M* <=" in c["label"])
min_strength = next(c for c in toe_flexure["checks"] if "Minimum strength" in c["label"])
print(
    f"\n  The toe's own strength check passes at {strength['utilisation']:.3f} "
    f"utilisation -- plenty of margin for the moment it actually carries. "
    f"But AS 3600 Cl 8.1.6.1's minimum-strength check (M_uo >= 1.2 M_cr) "
    f"reads {min_strength['utilisation']:.3f}: a footing this thick, sized "
    "for bearing rather than for its own bending, needs more steel than "
    "pure strength design would ask for, to avoid a brittle first-crack "
    "failure. required_steel_area() does not iterate for this -- see "
    "member_design.py's docstring."
)

# ---------------------------------------------------------------------------
banner("6 | METHOD B: EXACT MATCH AT ZERO BACKSLOPE, REAL DIVERGENCE WITH IT")
# ---------------------------------------------------------------------------
print(f"Method A (Rankine):  P_h = {result.method_a.thrust_horizontal:.2f} kN/m")
print(f"Method B (Culmann):  P_h = {result.method_b.thrust_horizontal:.2f} kN/m  "
      f"(critical plane {result.method_b.critical_wedge_angle:.1f} deg)")
print(f"Divergence: {result.divergence.describe()}")

sloped_soil = SoilInput(soil_type="clean_sand", surcharge=5.0, water_table=None, backslope=15.0)
sloped = analyse(WallInput(geometry=geometry, soil=sloped_soil))
print("\nSame wall, 15 deg backslope:")
print(f"  Method A:  P_h = {sloped.method_a.thrust_horizontal:.2f} kN/m")
print(f"  Method B:  P_h = {sloped.method_b.thrust_horizontal:.2f} kN/m  "
      f"(critical plane {sloped.method_b.critical_wedge_angle:.1f} deg)")
print(f"  {sloped.divergence.describe()}")
print(
    "\n  This is not noise. Rankine's backslope solution assumes the "
    "resultant acts parallel to the sloping ground; the Culmann wedge "
    "search at zero wall friction assumes a horizontal wall reaction -- "
    "two different, both textbook-correct, boundary conditions that "
    "coincide exactly at zero backslope and genuinely diverge once the "
    "ground slopes. See pressure/culmann.py for the derivation and the "
    "closed-form cross-check against Coulomb's own Ka formula."
)

# ---------------------------------------------------------------------------
banner("7 | THE SAME WALL, UNDERSIZED")
# ---------------------------------------------------------------------------
undersized_geometry = WallGeometry(
    H_retained=4.0, base_length=2.2, base_thickness=0.35,
    toe_length=0.5, stem_thickness_top=0.3, stem_thickness_bottom=0.35,
)
undersized = analyse(WallInput(geometry=undersized_geometry, soil=soil))
print_checks(undersized, STABILITY_CHECKS + MEMBER_CHECKS)
print(f"\nGoverning utilisation: {undersized.governing_utilisation:.3f}  "
      f"({'PASS' if undersized.passed else 'FAIL'})")

# ---------------------------------------------------------------------------
banner("8 | COMPOSITION -- SAVE, RELOAD, THE WORKING SURVIVES")
# ---------------------------------------------------------------------------
out = Path("cantilever_wall_result.json")
save_result(result, out)
print(f"Saved to {out} ({out.stat().st_size:,} bytes)")

reloaded = load_result(WallResult, out)
print(f"Reloaded: passed={reloaded.passed}, governing={reloaded.governing_utilisation:.3f}")
print(f"Method B critical plane survived the round trip: "
      f"{reloaded.method_b.critical_wedge_angle:.1f} deg")
print(
    "\n  The sliding check's full basis/intermediates/messages are still "
    "there after the round trip -- this is what lets a LARGER tool consume "
    "this result later and still show a reviewer the working, not just the "
    "numbers this run happened to keep in memory:"
)
sliding_working = reloaded.checks["sliding"].working
for line in sliding_working["messages"]:
    print(f"    note: {line}")
out.unlink()

print("\n" + "=" * 76)
print("NOT yet implemented: the global-stability geometry screen, a shear")
print("key contribution to sliding, and the AS 5100.3 / working-stress")
print("factor sets. See the README section.")
print("=" * 76)
