"""Example 12 -- running variations on a scheme, across two design domains.

  1. A hand-built list of schemes, ranked by cost.
  2. The same sweep, driven from a CSV -- the spreadsheet a client's brief
     actually arrives as.
  3. A scheme that doesn't even build, reported rather than crashing the run.
  4. The SAME engine, unmodified, sweeping a masonry wall instead of RC.
  5. A continuous scipy.optimize search, for "what's cheapest" rather than
     "which of these options passes".

Run:  python examples/12_optioneering.py
      (part 5 needs: pip install -e ".[optimise]")

NOTE: as throughout this package, every AS 3600/AS 3700 constant behind the
checks used here is UNVERIFIED. This example demonstrates the sweep
plumbing, not a checked design.
"""

from pathlib import Path

from austruct.core.units import kNm
from austruct.design.as3600 import check_flexure as check_rc_flexure
from austruct.design.as3700 import check_flexure as check_masonry_flexure
from austruct.materials import concrete
from austruct.materials.masonry import MortarClass, masonry_properties
from austruct.sections import rc_beam
from austruct.sections.masonry_section import masonry_wall
from austruct.study import Scheme, load_schemes_csv, run_sweep, save_schemes_csv


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


M_STAR = 300 * kNm


def build_rc(b, D, diameter=24):  # noqa: N803
    return rc_beam(b, D, concrete(32), cover=40, n_bars=4, diameter=diameter, fitment_spacing=200)


def check_rc(section):
    return check_rc_flexure(section, M_STAR)


def cost_rc(section):
    return section.geometry.area * 1e-6 * 180.0  # rough, $/m run


# ---------------------------------------------------------------------------
banner("1 | A HAND-BUILT LIST OF SCHEMES")
# ---------------------------------------------------------------------------
schemes = [
    Scheme("A - 300x600, N24", {"D": 600, "diameter": 24}),
    Scheme("B - 300x700, N20", {"D": 700, "diameter": 20}),
    Scheme("C - 300x300, N16", {"D": 300, "diameter": 16}),  # deliberately too shallow
]
result = run_sweep(schemes, build_rc, check_rc, base={"b": 300}, cost=cost_rc)
print("\n".join(result.describe()))
print(
    "\n  Three lines of scheme setup, no per-scheme calculation code -- "
    "run_sweep() calls the SAME check_flexure() every scheme in this "
    "package already has."
)

# ---------------------------------------------------------------------------
banner("2 | THE SAME SWEEP, FROM A CSV")
# ---------------------------------------------------------------------------
csv_path = Path("scheme_options.csv")
save_schemes_csv(schemes, csv_path)
print(f"Wrote {csv_path}:\n")
print(csv_path.read_text())

reloaded = load_schemes_csv(csv_path)
csv_result = run_sweep(reloaded, build_rc, check_rc, base={"b": 300}, cost=cost_rc)
print(
    f"Reloaded and re-run: governing = {csv_result.governing.scheme.name}, "
    f"same as before: {csv_result.governing.scheme.name == result.governing.scheme.name}"
)
print(
    "\n  This is the shape a client's brief actually arrives in -- a "
    "spreadsheet of options. A blank cell means 'use the base value', "
    "not 'override to nothing' -- see austruct.study.scheme's docstring."
)
csv_path.unlink()

# ---------------------------------------------------------------------------
banner("3 | A SCHEME THAT DOESN'T EVEN BUILD")
# ---------------------------------------------------------------------------
broken = [Scheme("negative depth", {"D": -100}), Scheme("fine", {"D": 700})]
broken_result = run_sweep(broken, build_rc, check_rc, base={"b": 300})
print("\n".join(broken_result.describe()))
print(
    "\n  The bad scheme is reported with its error, not raised -- one "
    "malformed row in a real options list should not kill the other five."
)

# ---------------------------------------------------------------------------
banner("4 | THE SAME ENGINE, A DIFFERENT DESIGN DOMAIN")
# ---------------------------------------------------------------------------
grade = masonry_properties(15.0, MortarClass.M3, grouted=True)


def build_wall(thickness):
    return masonry_wall(thickness, grade)


def check_wall(wall):
    return check_masonry_flexure(wall, 1.5 * kNm, direction="vertical", fd=0.1)


wall_schemes = [Scheme("90 series", {"thickness": 90}), Scheme("190 series", {"thickness": 190})]
wall_result = run_sweep(wall_schemes, build_wall, check_wall)
print("\n".join(wall_result.describe()))
print(
    "\n  Nothing in austruct.study imports design/, sections/ or materials/ "
    "-- build and check are supplied by the caller. This is the same "
    "run_sweep() call as part 1, pointed at masonry instead of RC."
)

# ---------------------------------------------------------------------------
banner("5 | A CONTINUOUS SEARCH: 'WHAT'S CHEAPEST', NOT 'WHICH PASSES'")
# ---------------------------------------------------------------------------
from austruct.study import SCIPY_AVAILABLE  # noqa: E402

if not SCIPY_AVAILABLE:
    print('scipy is not installed -- run: pip install -e ".[optimise]"')
else:
    from austruct.study import minimize_scheme  # noqa: E402

    opt = minimize_scheme(
        variables={"b": (200.0, 600.0), "D": (400.0, 1000.0)},
        build=build_rc,
        check=check_rc,
        cost=cost_rc,
    )
    print(opt.describe())
    print(
        "\n  scipy.optimize searched the CONTINUOUS dimensions (b, D); it "
        "knows nothing about bar catalogues or ductility limits. The "
        "result above is a REAL check_flexure() call at the optimiser's "
        "final point, re-verified rather than trusted -- round b and D to "
        "practical formwork sizes before this goes anywhere near a drawing."
    )

print("\n" + "=" * 76)
print("Reminder: every AS 3600/AS 3700 constant behind these checks is")
print("UNVERIFIED, as throughout this package. This example is the sweep")
print("plumbing, not a checked design.")
print("=" * 76)
