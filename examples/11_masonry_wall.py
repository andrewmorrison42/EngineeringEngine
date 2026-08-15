"""Example 11 -- masonry flexure and shear to AS 3700:2018, one-way strip only.

  1. An unreinforced wall: vertical vs horizontal bending, and why they
     differ (fd enhancement, the kp factor).
  2. The same wall's out-of-plane shear -- and why vertical reinforcement
     does not change it.
  3. A reinforced wall: the strength check passes, the ductility check
     doesn't -- the governing utilisation comes from whichever is worse.
  4. Choosing a mortar class and grouting, and what that changes.

Run:  python examples/11_masonry_wall.py

NOTE: every AS 3700 constant here is UNVERIFIED, and more heavily simplified
than this package's AS 3600/AS 4100 modules -- see design/as3700/constants.py
and the flexure.py/shear.py module docstrings for exactly what is and is not
covered (one-way strip bending only, not the two-way panel method; bed-joint
shear only, not the in-plane shear-wall/racking check).
"""

from austruct.core.units import kN, kNm
from austruct.design import as3700
from austruct.materials.bar_catalogue import bar_area
from austruct.materials.masonry import MortarClass, get_unit, masonry_properties, unit_catalogue
from austruct.sections.masonry_section import masonry_wall


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


# ---------------------------------------------------------------------------
banner("0 | THE UNIT CATALOGUE")
# ---------------------------------------------------------------------------
print(unit_catalogue())
print("\n  Recalled typical values, not a manufacturer data sheet -- confirm")
print("  f'uc for the specified unit before relying on anything downstream.")

# ---------------------------------------------------------------------------
banner("1 | UNREINFORCED: VERTICAL VS HORIZONTAL BENDING")
# ---------------------------------------------------------------------------
unit = get_unit("block_190")
grade = masonry_properties(unit.f_uc, MortarClass.M3, grouted=True)
wall = masonry_wall(unit.thickness, grade, name="190 series, M3, grouted")

print(f"{wall.name}: f'mt = {grade.f_mt:.2f} MPa, f'mt,parallel = {grade.f_mt_parallel:.2f} MPa\n")

vertical = as3700.vertical_bending_capacity(wall, fd=0.15)
horizontal = as3700.horizontal_bending_capacity(wall)
print("  Vertical bending   (tension perp. to bed joints, fd=0.15 MPa credited):")
print(f"    phi.Muo = {vertical.get('phiMuo') / kNm:.2f} kN.m/m")
print("  Horizontal bending (tension parallel to bed joints, kp=2.0, no fd):")
print(f"    phi.Muo = {horizontal.get('phiMuo') / kNm:.2f} kN.m/m")
print(
    "\n  Horizontal bending is stronger here even without any fd credit --"
    "\n  bending parallel to the bed joints engages full-depth mortar bond"
    "\n  in this simplified model. A real panel would also gain from"
    "\n  two-way action this one-way strip does not capture -- see the"
    "\n  module docstring for that gap."
)

# ---------------------------------------------------------------------------
banner("2 | THE SAME WALL'S OUT-OF-PLANE SHEAR")
# ---------------------------------------------------------------------------
shear = as3700.shear_capacity(wall, fd=0.15)
print(f"phi.Vo = {shear.get('phiVo') / kN:.1f} kN/m  (f'ms = {grade.f_ms:.2f} MPa)")

reinforced_same_wall = masonry_wall(
    unit.thickness, grade, bar_area_per_metre=bar_area(16) * 1000 / 400, bar_depth=95
)
shear_reinforced = as3700.shear_capacity(reinforced_same_wall, fd=0.15)
print(
    f"\nSame masonry, WITH vertical bars: Vo (masonry only) = "
    f"{shear_reinforced.get('Vo') / kN:.1f} kN/m vs "
    f"{shear.get('Vo') / kN:.1f} kN/m unreinforced -- identical."
)
print(
    "  phi.Vo differs slightly only because the reinforced/unreinforced phi "
    "rows differ, not because the bars do anything for THIS mechanism. "
    "They resist flexure; a shear-sliding plane needs different "
    "reinforcement (horizontal bond-beam steel) to be credited, and that "
    "is not modelled -- see shear.py's docstring."
)

# ---------------------------------------------------------------------------
banner("3 | REINFORCED: STRENGTH PASSES, DUCTILITY DOESN'T")
# ---------------------------------------------------------------------------
over_reinforced = masonry_wall(
    unit.thickness, grade, bar_area_per_metre=bar_area(16) * 1000 / 600, bar_depth=95
)
result = as3700.check_flexure(over_reinforced, 6.0 * kNm)
print(f"Wall: N16 @ 600 -- {over_reinforced.reinforcement.area_per_metre:.0f} mm^2/m at d = 95 mm\n")
for check in result.checks:
    print(f"  {check.describe()}")
print(f"\nGoverning utilisation: {result.utilisation:.3f}  ({'PASS' if result.passed else 'FAIL'})")
print(
    "\n  The strength check passes with room to spare -- there is enough steel"
    "\n  to develop the moment comfortably. But ku = a/d breaches the"
    "\n  ductility limit: too much steel for the section to crush the"
    "\n  masonry gradually rather than fail suddenly when the bar yields."
    "\n  The GOVERNING check is the one that fails, not the one with margin --"
    "\n  same lesson as the RC and steel design packages."
)

# ---------------------------------------------------------------------------
banner("4 | MORTAR CLASS AND GROUTING")
# ---------------------------------------------------------------------------
print(f"{'Mortar':>8}{'Grouted':>10}{'f_m':>8}{'f_mt':>8}{'f_ms':>8}")
print("  " + "-" * 40)
for mc in (MortarClass.M2, MortarClass.M3, MortarClass.M4):
    for grouted in (False, True):
        g = masonry_properties(unit.f_uc, mc, grouted=grouted)
        print(f"  {mc.value:>6}{str(grouted):>10}{g.f_m:>8.2f}{g.f_mt:>8.2f}{g.f_ms:>8.2f}")

print(
    "\n  Mortar class changes f'm (compressive) only, in this simplified"
    "\n  derivation; grouting changes f'mt and f'ms (tensile/shear bond)"
    "\n  only. They are independent knobs -- confirm both against the"
    "\n  printed table before relying on either in isolation."
)

print("\n" + "=" * 76)
print("Reminder: this module covers ONE-WAY strip flexure and OUT-OF-PLANE")
print("bed-joint shear only. Two-way panel bending, in-plane shear walls,")
print("compression/buckling and detailing are NOT implemented -- see README.")
print("=" * 76)
