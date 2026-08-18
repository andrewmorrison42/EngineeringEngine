"""Example 13 -- a modular gravity (segmental) block retaining wall,
NCMA-style allowable stress design.

  1. Usable with a course count plus a block series plus one soil type --
     everything else defaults.
  2. Coulomb active pressure on the wall's own battered back face -- and
     the sign convention that trips up every implementation of this
     formula, verified against Rankine at the degenerate case.
  3. The four FS-based checks: sliding, overturning, bearing, and the
     internal-stability check unique to a segmental wall -- interface
     shear between courses.
  4. The same wall, undersized -- and WHICH check catches it.
  5. A taller wall, same block series -- utilisation worsens, as it must.
  6. Composition: save the result, reload it, and the full working survives.

Run:  python examples/13_gravity_wall.py

NOTE: the block catalogue's course height and unit weight are documented
PLACEHOLDERS (the source PDF never states them -- see
``gravity_wall/data/block_catalogue.json``), the interface shear law is a
deliberate simplification of a real manufacturer's ASTM D6916 envelope, and
the FS minimums are transcribed from one manufacturer's design manual as
representative NCMA-style practice, not a specific project's spec. This
example demonstrates the PLUMBING, not a checked design.
"""

from pathlib import Path

from austruct.tools.contracts.base import load_result, save_result
from austruct.tools.gravity_wall import (
    GravityWallGeometry,
    GravityWallInput,
    GravityWallResult,
    SoilInput,
    analyse,
    block_series,
    block_series_names,
)
from austruct.tools.gravity_wall.pressure import Ka_coulomb

CHECKS = ("sliding", "overturning", "bearing", "interface_shear")


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


def print_checks(result, keys=CHECKS) -> None:
    print(f"{'Check':<18}{'Utilisation':>12}{'Status':>10}")
    print("-" * 40)
    for name in sorted(keys, key=lambda k: -result.checks[k].utilisation):
        c = result.checks[name]
        print(f"{name:<18}{c.utilisation:>12.3f}{'PASS' if c.passed else 'FAIL':>10}")


# ---------------------------------------------------------------------------
banner("1 | COURSES PLUS A BLOCK SERIES PLUS ONE SOIL TYPE")
# ---------------------------------------------------------------------------
print(f"Catalogue series available: {', '.join(block_series_names())}")
block = block_series("large_60in")
print(f"  {block.name}: width={block.width} m, height={block.height} m, "
      f"setback={block.setback} m -> batter {block.batter_deg:.2f} deg")

geometry = GravityWallGeometry(n_courses=8, block=block, embedment=0.4)
soil = SoilInput(soil_type="clean_sand", surcharge=5.0, water_table=None)
wall = GravityWallInput(geometry=geometry, soil=soil)

print(f"\nWall height H = {geometry.H:.2f} m ({geometry.n_courses} courses)")
result = analyse(wall)
print("\nEvery value NOT explicitly supplied, tagged with where it came from:")
for line in result.assumptions:
    print(f"  {line}")

# ---------------------------------------------------------------------------
banner("2 | COULOMB PRESSURE ON THE BATTERED BACK FACE")
# ---------------------------------------------------------------------------
print(f"Ka (battered, phi=32, delta=default) = {result.pressure.Ka:.4f}")
Ka_vertical = Ka_coulomb(32.0, omega_deg=0.0, beta_deg=0.0, delta_deg=result.resolved_soil.delta.value)
print(f"Ka (a hypothetical VERTICAL wall, same phi/delta) = {Ka_vertical:.4f}")
print(
    f"\n  The batter REDUCES Ka -- {result.pressure.Ka:.4f} < {Ka_vertical:.4f} -- because "
    "the wall recedes away from the retained soil as it rises. Coulomb's "
    "own sign convention is the opposite of that (positive omega tilts a "
    "wall INTO the backfill and increases Ka), which is why api.py passes "
    "'-geometry.batter_deg', not batter_deg itself -- see pressure.py's "
    "module docstring; getting this sign wrong silently OVER-predicts the "
    "pressure a real battered gravity wall sees."
)
print(f"P_h = {result.pressure.thrust_horizontal:.2f} kN/m, "
      f"P_v = {result.pressure.thrust_vertical:.2f} kN/m (acts downward, stabilising)")

# ---------------------------------------------------------------------------
banner("3 | FOUR FS-BASED CHECKS -- EXTERNAL STABILITY PLUS INTERNAL STABILITY")
# ---------------------------------------------------------------------------
print_checks(result)
print(f"\nGoverning utilisation: {result.governing_utilisation:.3f} "
      f"({'PASS' if result.passed else 'FAIL'})")

interface = result.checks["interface_shear"]
print(
    "\n  Interface shear is the check a cantilever/gravity CONCRETE wall "
    "does not need at all -- it is a stack of discrete blocks, not one "
    "monolithic section, and the course-by-course breakdown is in the "
    "working's messages:"
)
for line in interface.working["messages"][:3]:
    print(f"    {line}")
print("    ...")

# ---------------------------------------------------------------------------
banner("4 | THE SAME WALL, UNDERSIZED")
# ---------------------------------------------------------------------------
undersized_geometry = GravityWallGeometry(
    n_courses=8, block=block_series("standard_41in"), embedment=0.0,
)
undersized = analyse(GravityWallInput(geometry=undersized_geometry, soil=soil))
print_checks(undersized)
print(f"\nGoverning utilisation: {undersized.governing_utilisation:.3f} "
      f"({'PASS' if undersized.passed else 'FAIL'})")
print(
    "\n  Bearing governs here, not sliding or overturning -- a narrower "
    "block series with no embedment gives the Meyerhof effective width "
    "very little room, and the Terzaghi/Meyerhof Nq overburden term is "
    "zero at zero embedment. This is the same 'which check actually "
    "governs' lesson cantilever_wall's example makes, for a different "
    "reason: there it was a reinforced-concrete minimum-strength clause, "
    "here it is a shallow founding depth."
)

# ---------------------------------------------------------------------------
banner("5 | A TALLER WALL, SAME BLOCK SERIES")
# ---------------------------------------------------------------------------
tall_geometry = GravityWallGeometry(n_courses=14, block=block, embedment=0.4)
tall = analyse(GravityWallInput(geometry=tall_geometry, soil=soil))
print(f"8 courses (H={geometry.H:.2f} m):  governing = {result.governing_utilisation:.3f}")
print(f"14 courses (H={tall_geometry.H:.2f} m): governing = {tall.governing_utilisation:.3f}")
print(
    "\n  Same block series, same soil, same embedment -- more courses is "
    "strictly worse, as it must be: the retained height (hence the earth "
    "pressure resultant, which grows with H^2) grows faster than the "
    "self-weight (which grows linearly with H)."
)

# ---------------------------------------------------------------------------
banner("6 | COMPOSITION -- SAVE, RELOAD, THE WORKING SURVIVES")
# ---------------------------------------------------------------------------
out = Path("gravity_wall_result.json")
save_result(result, out)
print(f"Saved to {out} ({out.stat().st_size:,} bytes)")

reloaded = load_result(GravityWallResult, out)
print(f"Reloaded: passed={reloaded.passed}, governing={reloaded.governing_utilisation:.3f}")
sliding_working = reloaded.checks["sliding"].working
print(f"Sliding FS survived the round trip: {sliding_working['outputs']['FS']['value']:.3f}")
out.unlink()

print("\n" + "=" * 76)
print("NOT yet implemented: global stability (deep-seated slip circle),")
print("geogrid-reinforced segmental walls (a different design problem --")
print("this tool is GRAVITY, mass-only, stability), and a water table.")
print("See the README section.")
print("=" * 76)
