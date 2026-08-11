"""Example 7 -- a crown (arch) culvert, and why it is not a box.

  1. The geometry: arched crown, tapered legs, haunch at the springing.
  2. Arch action -- thrust, and where the moment went.
  3. The springing thrust, which is what the footing has to hold.
  4. Why the UNBALANCED case governs an arch.
  5. Designing the crown, with the thrust reported alongside.

Run:  OMP_NUM_THREADS=1 python examples/07_crown_culvert.py

NOTE: the dimensions below are ILLUSTRATIVE. A real crown unit's span, rise,
thicknesses and haunch dimensions come from the manufacturer's catalogue --
Humes or otherwise -- and nothing in this package knows them.
"""

from austruct.core.units import kN, kNm, kPa, mm
from austruct.design import as3600
from austruct.materials import concrete
from austruct.sections import rc_beam
from austruct.structures import (
    BoxCulvert,
    CrownCulvert,
    CrownGeometry,
    CrownLoading,
    CulvertGeometry,
    CulvertLoading,
    Part,
    Wall,
)


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


# ---------------------------------------------------------------------------
banner("1 | THE UNIT")
# ---------------------------------------------------------------------------
geometry = CrownGeometry(
    span=4000 * mm,          # leg centreline to leg centreline at springing
    rise=1200 * mm,          # apex above springing
    leg_height=1500 * mm,    # springing above the footing
    crown_thickness=200 * mm,
    haunch_thickness=350 * mm,   # thickened where the crown meets the legs
    haunch_extent=0.18,          # over the outer 18% of each half-arc
    leg_thickness_base=300 * mm,  # tapered legs
    leg_thickness_top=225 * mm,
)
loading = CrownLoading(fill_depth=600 * mm, fill_density=2000, k0=0.5)
culvert = CrownCulvert(geometry=geometry, loading=loading, name="Crown unit CU1")

print("\n".join(culvert.describe()))

print("\n  The crown division count is not a round number -- it is chosen from")
print(f"  the subtended angle. {geometry.recommended_crown_divisions()} divisions puts about 5 degrees in")
print("  each chord. Eight divisions would look generous and be 12% wrong.")

results = culvert.solve()
print()
print("\n".join(results.describe()))

# ---------------------------------------------------------------------------
banner("2 | ARCH ACTION -- WHERE THE MOMENT WENT")
# ---------------------------------------------------------------------------
print("Crown, springing to springing:\n")
print(f"  {'fraction':>9}{'M kN.m':>10}{'N kN':>10}   {'':<20}")
moments = dict(results.segment_moments(Part.CROWN))
thrusts = dict(results.segment_thrust(Part.CROWN))
for f in sorted(moments)[:: max(1, len(moments) // 9)]:
    tag = ""
    if abs(f - 0.5) < 0.03:
        tag = "<- apex"
    elif f < 0.02 or f > 0.98:
        tag = "<- springing"
    print(f"  {f:>9.3f}{moments[f] / kNm:>10.2f}{thrusts[f] / kN:>10.1f}   {tag}")

print("\n  Thrust is greatest at the springing and least at the apex, because")
print("  an arch's axial force is H/cos(theta) and the apex is flat.")
print(f"  M/(N.t) at the apex = {results.arch_efficiency:.3f}; below 0.167 means")
print("  the line of thrust is inside the middle third, i.e. it is arching.")

# The comparison that justifies the shape.
t = 250 * mm
box = BoxCulvert(
    geometry=CulvertGeometry(
        clear_span=4000 * mm - t, clear_height=2700 * mm - t,
        top_thickness=t, base_thickness=t, wall_thickness=t,
    ),
    loading=CulvertLoading(fill_depth=600 * mm, fill_density=2000, k0=0.5),
).solve()
arch = CrownCulvert(
    geometry=CrownGeometry(
        span=4000 * mm, rise=1200 * mm, leg_height=1500 * mm,
        crown_thickness=t, haunch_thickness=t,
        leg_thickness_base=t, leg_thickness_top=t,
    ),
    loading=loading,
).solve()

print(f"\n  Same span, same cover, same {t:.0f} mm thickness:")
print(f"    box top slab peak M   = {abs(box.peak_moment(Wall.TOP)[1]) / kNm:7.2f} kN.m")
print(f"    arch crown  peak M    = {abs(arch.peak_moment(Part.CROWN)[1]) / kNm:7.2f} kN.m")
print(f"    arch crown  max thrust= {arch.max_thrust / kN:7.1f} kN")
print("\n  The arch carries the same load with a fraction of the bending, by")
print("  converting it to thrust. That is the whole reason for the shape --")
print("  and the reason the footing has to be able to hold that thrust.")

# ---------------------------------------------------------------------------
banner("3 | THE SPRINGING THRUST, AND A SURPRISE")
# ---------------------------------------------------------------------------
print("An arch pushes its supports apart. Backfill pushes the legs together.")
print("Which wins depends on the leg height and the earth pressure:\n")
print(f"  {'k0':>6}{'H at left foot':>17}{'direction':>12}")
print("  " + "-" * 35)
for k0 in (0.001, 0.1, 0.2, 0.3, 0.5, 0.8):
    r = CrownCulvert(
        geometry=geometry, loading=CrownLoading(fill_depth=600 * mm, k0=k0)
    ).solve()
    h, _ = r.springing_thrust()
    print(f"  {k0:>6.3f}{h / kN:>14.1f} kN{'OUTWARD' if h > 0 else 'inward':>12}")

h, v = results.springing_thrust()
print(f"\n  At k0 = {loading.k0}, this unit's feet are pushed INWARD by "
      f"{abs(h) / kN:.1f} kN,")
print(f"  not outward. With {geometry.leg_height:.0f} mm legs under "
      f"{loading.fill_depth + geometry.rise:.0f} mm of cover the lateral")
print("  earth pressure more than cancels the arch thrust. A footing designed")
print("  for outward thrust alone would be resisting the wrong direction.")
print(f"\n  Vertical reaction per foot = {v / kN:.1f} kN")

# ---------------------------------------------------------------------------
banner("4 | THE UNBALANCED CASE GOVERNS")
# ---------------------------------------------------------------------------
print("Symmetric lateral pressure largely cancels. Asymmetric pressure does")
print("not, and an arch is far more sensitive to it than a box is.\n")

print(f"  {'case':<28}{'left leg M':>13}{'right leg M':>13}{'max M':>10}")
print("  " + "-" * 64)
for label, extra in (
    ("balanced", {}),
    ("20 kPa surcharge, one side", {"surcharge_left": 20 * kPa}),
    ("40 kPa surcharge, one side", {"surcharge_left": 40 * kPa}),
):
    r = CrownCulvert(
        geometry=geometry,
        loading=CrownLoading(fill_depth=600 * mm, k0=0.5, **extra),
    ).solve()
    left = r.peak_moment(Part.LEFT_LEG)[1]
    right = r.peak_moment(Part.RIGHT_LEG)[1]
    print(f"  {label:<28}{left / kNm:>10.2f} kN.m{right / kNm:>10.2f} kN.m"
          f"{r.max_moment / kNm:>9.2f}")

print("\n  Construction sequence matters for the same reason: backfilling one")
print("  side ahead of the other is the unbalanced case, applied to a unit")
print("  that has no fill on top to hold it down.")

# ---------------------------------------------------------------------------
banner("5 | DESIGNING THE CROWN")
# ---------------------------------------------------------------------------
frac, m_crown = results.peak_moment(Part.CROWN)
n_at_peak = dict(results.segment_thrust(Part.CROWN))[
    min(results.segment_thrust(Part.CROWN), key=lambda p: abs(p[0] - frac))[0]
]

# The peak is at the springing, where the haunch is -- so the section checked
# is the HAUNCH thickness, not the crown thickness.
haunch_section = rc_beam(
    b=geometry.transverse_width, D=geometry.haunch_thickness,
    concrete=concrete(50), cover=40,
    n_bars=6, diameter=16, fitment_diameter=0, fitment_spacing=None,
    name="Crown at haunch",
)
flexure = as3600.check_flexure(haunch_section, abs(m_crown))

print(f"Peak crown moment {m_crown / kNm:.2f} kN.m at fraction {frac:.3f}")
print("  -- that is the SPRINGING, where the haunch is, so the section")
print(f"     checked is {geometry.haunch_thickness:.0f} mm, not the "
      f"{geometry.crown_thickness:.0f} mm crown.")
print(f"\n  6-N16 per metre: phi.Muo = {flexure.get('phiMuo') / kNm:.1f} kN.m, "
      f"utilisation {flexure.utilisation:.3f} -> "
      f"{'PASS' if flexure.passed else 'FAIL'}")
print(f"\n  Coincident thrust N = {abs(n_at_peak) / kN:.1f} kN compression.")
print("  IMPORTANT: check_flexure takes NO account of axial force. For a")
print("  section below the balance point the compression would INCREASE the")
print("  moment capacity, so ignoring it is conservative here -- but the")
print("  section has NOT been checked for combined bending and compression,")
print("  which needs an N-M interaction this package does not implement.")

print("\n" + "=" * 76)
print("Reminder: the dimensions here are illustrative, not a Humes unit. Take")
print("span, rise, thicknesses and haunch dimensions from the manufacturer.")
print("K0, the subgrade modulus and the arching factor are UNVERIFIED, and")
print("soil-structure interaction (arching onto a rigid unit) is NOT modelled.")
print("=" * 76)
