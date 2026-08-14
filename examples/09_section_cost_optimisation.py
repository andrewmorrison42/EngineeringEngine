"""Example 9 -- searching for the cheapest RC section, not just a valid one.

Given a design moment, a concrete grade and a grid of practical sizes, find
the section that carries M* for the least cost -- and see WHY it is cheapest,
not just what it is.

  1. A search at typical relative costs.
  2. The economics: what happens as steel gets relatively more expensive.
  3. Why the cheapest arrangement is not always the least-steel one.
  4. An infeasible grid -- the search says so rather than guessing.

Run:  python examples/09_section_cost_optimisation.py

NOTE: every AS 3600 constant behind check_flexure is UNVERIFIED, as in the
rest of this package. The optimiser adds no new code values -- it only
searches over sections that check_flexure has already approved.
"""

from austruct.core.units import kNm
from austruct.design import as3600
from austruct.materials.concrete import concrete


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


M_STAR = 300 * kNm
CONCRETE = concrete(32)

# ---------------------------------------------------------------------------
banner("1 | A SEARCH AT TYPICAL RELATIVE COSTS")
# ---------------------------------------------------------------------------
bounds = as3600.SearchBounds(
    width=as3600.SizeRange(250, 500, 50),
    depth=as3600.SizeRange(400, 900, 50),
)
rates = as3600.CostRates(concrete_per_m3=180.0, steel_per_tonne=2200.0)

result = as3600.minimum_cost_section(M_STAR, CONCRETE, bounds, rates)
print(f"M* = {M_STAR / kNm:.0f} kN.m, f'c = {CONCRETE.fc:.0f} MPa\n")
print("\n".join(result.describe(top=5)))

print(
    "\n  The winner is not the shallowest section that passes, and it is not "
    "the one with the least steel either -- it is the point where a deeper, "
    "leaner section stops being worth the extra concrete."
)

# ---------------------------------------------------------------------------
banner("2 | THE ECONOMICS -- STEEL PRICE DRIVES THE SHAPE OF THE ANSWER")
# ---------------------------------------------------------------------------
print(f"{'steel $/t':>12}{'section':>14}{'bars':>10}{'cost':>12}")
print("  " + "-" * 46)
for steel_rate in (800.0, 1500.0, 2200.0, 4000.0, 8000.0):
    trial_rates = as3600.CostRates(concrete_per_m3=180.0, steel_per_tonne=steel_rate)
    trial = as3600.minimum_cost_section(M_STAR, CONCRETE, bounds, trial_rates)
    g = trial.governing
    section_label = f"{g.section.geometry.b_top:.0f}x{g.section.geometry.D:.0f}"
    bars = g.section.layers[0].designation
    print(f"  {steel_rate:>10.0f}{section_label:>14}{bars:>10}{g.total_cost:>12,.1f}")

print(
    "\n  Cheap steel buys a shallow section with more bars; expensive steel "
    "buys depth instead, because lever arm is free and steel mass is not. "
    "This table is the reason the search runs over BOTH sizes and bar "
    "arrangements together, rather than fixing a depth and only picking bars."
)

# ---------------------------------------------------------------------------
banner("3 | WHY THE CHEAPEST ARRANGEMENT IS NOT ALWAYS LEAST-STEEL")
# ---------------------------------------------------------------------------
governing = result.governing
print(f"Governing section: {governing.describe()}\n")
print("Every other feasible size at the SAME width, for comparison:")
print(f"  {'depth':>8}{'bars':>10}{'util':>8}{'cost':>10}")
same_width = [
    c
    for c in result.candidates
    if c.section.geometry.b_top == governing.section.geometry.b_top
]
for c in sorted(same_width, key=lambda c: c.section.geometry.D):
    print(
        f"  {c.section.geometry.D:>7.0f}{c.section.layers[0].designation:>10}"
        f"{c.check.utilisation:>8.3f}{c.total_cost:>10,.1f}"
    )
print(
    "\n  A shallower candidate at this width would need enough extra steel "
    "to cost more overall, even though it uses less concrete -- that is the "
    "trade-off the search is actually making at every step."
)

# ---------------------------------------------------------------------------
banner("4 | AN INFEASIBLE GRID SAYS SO")
# ---------------------------------------------------------------------------
too_shallow = as3600.SearchBounds(
    width=as3600.SizeRange(250, 300, 50),
    depth=as3600.SizeRange(150, 250, 50),
)
infeasible = as3600.minimum_cost_section(M_STAR, CONCRETE, too_shallow, rates)
print("\n".join(infeasible.describe()))
print(
    "\n  No candidate is silently accepted at reduced strength, and no size "
    "outside the requested grid is tried. Widen the bounds; the search will "
    "not guess on the engineer's behalf."
)

print("\n" + "=" * 76)
print("Reminder: shear reinforcement, formwork and wastage are NOT priced or")
print("sized here -- see README for what this search deliberately leaves out.")
print("=" * 76)
