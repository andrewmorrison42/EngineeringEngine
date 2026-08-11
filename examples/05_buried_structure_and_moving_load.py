"""Example 5 -- moving loads, AS 5100.2 traffic, and load dispersal through fill.

Three things, in the order they build on each other:

  1. A moving load over a simply supported beam, checked against closed-form
     results, and the influence lines that explain where the load wants to be.
  2. The AS 5100.2 traffic models swept over a bridge span.
  3. A buried culvert top slab under fill: earth pressure plus wheel loads
     dispersed through the fill, swept over a range of fill depths.

Run:  python examples/05_buried_structure_and_moving_load.py

NOTE: the AS 5100.2 traffic geometry in this package is UNVERIFIED -- it has
not been transcribed from the printed standard. Every call below therefore
passes allow_unverified=True, which is the switch that makes that explicit.
Do not use these numbers for a bridge.
"""

from austruct.analysis import (
    LoadTrain,
    influence_line,
    moving_load_envelope,
    simply_supported,
)
from austruct.core.units import kN, kN_per_m, kNm, m
from austruct.design import as5100_5
from austruct.loads import FillDispersal, buried_structure_loads
from austruct.loads import as5100_2 as traffic
from austruct.materials import concrete
from austruct.sections import rc_beam

DEV = {"allow_unverified": True}  # see the module docstring


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


# ---------------------------------------------------------------------------
banner("1 | A MOVING LOAD OVER A SIMPLY SUPPORTED BEAM")
# ---------------------------------------------------------------------------
L = 20.0 * m
beam = simply_supported(L, EI=1e15, name="BR1")

print("Single 100 kN load, swept in 100 mm steps:\n")
P = 100 * kN
result = moving_load_envelope(beam, LoadTrain("P", axles=((0.0, P),)), step=100.0)
print(f"  M*  = {result.M_star / kNm:8.2f} kN.m   exact PL/4 = {P * L / 4 / kNm:8.2f}")
print(f"  at datum x = {result.critical_position('moment') / 1000:.3f} m   (exact L/2 = {L / 2000:.3f})")

print("\nTwo 100 kN axles at 4 m -- the maximum is NOT at midspan:\n")
a = 4.0 * m
two = LoadTrain("2-axle", axles=((0.0, P), (a, P)), length=a)
r2 = moving_load_envelope(beam, two, step=50.0)
exact = P * (2 * L - a) ** 2 / (8 * L)
print(f"  M*  = {r2.M_star / kNm:8.2f} kN.m   exact P(2L-a)^2/8L = {exact / kNm:8.2f}")
print(f"  leading axle at x = {r2.critical_position('moment') / 1000:.3f} m")
print(f"  V*  = {r2.V_star / kN:8.2f} kN at datum {r2.critical_position('shear') / 1000:.3f} m")
print(f"\n  {r2.notes[-1]}")

# ---------------------------------------------------------------------------
banner("2 | INFLUENCE LINES -- WHERE THE LOAD WANTS TO BE")
# ---------------------------------------------------------------------------
il_m = influence_line(beam, "moment", location=L / 2, n_points=81)
il_v = influence_line(beam, "shear", location=L / 4, n_points=81, side="right")
il_r = influence_line(beam, "reaction", location=0.0, n_points=41)

print(f"  Moment at midspan : peak {il_m.peak / 1000:6.3f} m at x = "
      f"{il_m.peak_position / 1000:.2f} m   (exact L/4 = {L / 4000:.2f})")
print(f"  Reaction at A     : {il_r.at(0.0):.3f} at x=0, {il_r.at(L / 2):.3f} at midspan, "
      f"{il_r.at(L):.3f} at x=L")
delta = max(1.0, L * 1e-4)
print(f"  Shear at L/4      : {il_v.at(L / 4 - delta):+.3f} just left, "
      f"{il_v.at(L / 4 + delta):+.3f} just right -- a step of 1.0 across the section")

w = 10 * kN_per_m
print(f"\n  Hand check: a {w / kN_per_m:.0f} kN/m UDL over the whole span gives")
print(f"    intensity x IL area = {w * il_m.area / kNm:.2f} kN.m")
print(f"    exact wL^2/8        = {w * L**2 / 8 / kNm:.2f} kN.m")

# ---------------------------------------------------------------------------
banner("3 | AS 5100.2 TRAFFIC MODELS")
# ---------------------------------------------------------------------------
print(traffic.describe_models())

print("\nThe guard, before anything else:")
try:
    traffic.m1600()
except traffic.UnverifiedLoadModel as exc:
    print(f"  traffic.m1600() -> {type(exc).__name__}")
    print(f"    {str(exc).splitlines()[0]}")

print("\nM1600 swept over the 20 m span (dev override, DLA applied):\n")
m1600 = traffic.with_dla(traffic.m1600(**DEV))
print(f"  {m1600.name}: {len(m1600.axles)} axles, {m1600.total_axle_load / 1e3:.0f} kN total, "
      f"{m1600.length / 1000:.2f} m long, UDL {m1600.trailing_udl * 1000 / 1e3:.2f} kN/m")

res_m = moving_load_envelope(beam, m1600, step=250.0)
res_s = moving_load_envelope(beam, traffic.s1600(**DEV), step=250.0)
print(f"\n  {'model':<10}{'M* kN.m':>12}{'V* kN':>10}{'critical x':>13}")
print("  " + "-" * 45)
for label, r in (("M1600", res_m), ("S1600", res_s)):
    print(f"  {label:<10}{r.M_star / kNm:>12.1f}{r.V_star / kN:>10.1f}"
          f"{r.critical_position('moment') / 1000:>12.2f} m")
print(f"\n  Lane factors, 3 loaded lanes: "
      f"{[traffic.lane_factor(3, i) for i in (1, 2, 3)]} "
      f"-> {traffic.total_lane_factor(3):.1f} effective lanes")

# ---------------------------------------------------------------------------
banner("4 | BURIED CULVERT TOP SLAB -- FILL + DISPERSED WHEELS")
# ---------------------------------------------------------------------------
SPAN = 6.0 * m
STRIP = 1000.0  # analyse a 1 m wide strip
wheel, contact_len, contact_wid = traffic.w80_wheel(**DEV)

print(f"Top slab: {SPAN / 1000:.1f} m clear span, analysed as a {STRIP / 1000:.0f} m strip.")
print(f"Live load: W80 = {wheel / kN:.0f} kN on a "
      f"{contact_len:.0f} x {contact_wid:.0f} mm contact patch.\n")

print(f"  {'fill':>6}{'earth':>9}{'patch':>8}{'pressure':>10}{'M_earth':>10}"
      f"{'M_wheel':>10}{'M_total':>10}{'cover':>8}")
print(f"  {'mm':>6}{'kPa':>9}{'mm':>8}{'kPa':>10}{'kN.m':>10}{'kN.m':>10}{'kN.m':>10}{'-':>8}")
print("  " + "-" * 71)

slab = simply_supported(SPAN, EI=1e14, name="Top slab")
rows = []
for depth in (300, 600, 900, 1200, 2000, 3000):
    fill = FillDispersal(depth=depth, density=2000, slope=2.0, effective_width=STRIP)
    m_earth = slab.with_loads((fill.earth_pressure_udl(),)).solve().max_moment
    patch = fill.disperse_wheel(wheel, SPAN / 2, contact_len, contact_wid, SPAN)
    m_wheel = slab.with_loads((patch,)).solve().max_moment
    loads = buried_structure_loads(
        fill, SPAN, wheel, contact_len, contact_wid, (SPAN / 2,)
    )
    m_total = slab.with_loads(loads).solve().max_moment
    rows.append((depth, m_total))
    print(f"  {depth:>6.0f}{fill.vertical_pressure * 1e3:>9.2f}{fill.spread(contact_len):>8.0f}"
          f"{fill.wheel_pressure(wheel, contact_len, contact_wid) * 1e3:>10.1f}"
          f"{m_earth / kNm:>10.2f}{m_wheel / kNm:>10.2f}{m_total / kNm:>10.2f}"
          f"{fill.transverse_coverage(contact_wid):>8.2f}")

best = min(rows, key=lambda r: r[1])
print("\n  Shallow fill governs the WHEEL; deep fill governs the EARTH PRESSURE.")
print(f"  The total has a minimum near {best[0]:.0f} mm, so BOTH extremes of the")
print("  fill range must be checked -- neither end is automatically the worst.")

# ---------------------------------------------------------------------------
banner("5 | THE WHEEL AS A MOVING LOAD, AND A DESIGN CHECK")
# ---------------------------------------------------------------------------
fill = FillDispersal(depth=600, density=2000, slope=2.0, effective_width=STRIP)
print("\n".join("  " + line for line in fill.describe()))

w80_train = traffic.with_dla(traffic.w80(**DEV))
dispersed = fill.dispersed_train(w80_train, SPAN, contact_len, contact_wid)
res = moving_load_envelope(
    slab, dispersed, step=100.0, static_loads=(fill.earth_pressure_udl(),)
)
print(f"\n  Swept: {dispersed.name}")
print(f"  M* = {res.M_star / kNm:7.2f} kN.m at datum "
      f"{res.critical_position('moment') / 1000:.3f} m")
print(f"  V* = {res.V_star / kN:7.2f} kN")

# A 400 mm top slab, checked to AS 5100.5 since this is bridgeworks -- note
# the bridge standard, not AS 3600, because the structure carries road traffic.
section = rc_beam(
    b=STRIP, D=400, concrete=concrete(40), cover=40,
    n_bars=6, diameter=20, fitment_spacing=None, fitment_diameter=0,
    name="Top slab strip",
)
flexure = as5100_5.check_flexure(section, res.M_star)
print(f"\n  Section: {section.name}, 400 mm deep, 6-N20 per metre "
      f"(A_st = {section.Ast:.0f} mm2/m, d = {section.d:.0f} mm)")
print(f"  M*      = {res.M_star / kNm:7.2f} kN.m")
print(f"  phi.Muo = {flexure.get('phiMuo') / kNm:7.2f} kN.m   "
      f"utilisation {flexure.utilisation:.3f}   "
      f"{'PASS' if flexure.passed else 'FAIL'}")
for note in flexure.messages:
    print(f"  NOTE: {note}")

print("\n  This is the load path end to end: a wheel on the road surface,")
print("  spread through the fill, swept to its worst position, combined with")
print("  the earth pressure, and checked against an AS 5100.5 capacity.")

print("\n" + "=" * 76)
print("Reminder: the traffic geometry and the dispersal slope are both")
print("UNVERIFIED. Check them against AS 5100.2 before using any of this.")
print("=" * 76)
