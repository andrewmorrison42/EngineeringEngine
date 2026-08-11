"""Example 6 -- box culvert as a closed frame, with a reviewer-ready report.

Five things, in the order they build on each other:

  1. The culvert as a closed frame on soil springs, and why that differs from
     the simply supported top slab of example 5.
  2. Directing where the nodes go, so the reported peak IS the peak.
  3. Serviceability -- deflection and crack control.
  4. Detailing -- can the bars actually be built?
  5. A report with the engineer's own words between the calculations, rendered
     to HTML for issue.

Run:  OMP_NUM_THREADS=1 python examples/06_box_culvert_frame.py

NOTE: every code constant in this package is UNVERIFIED, and so are the earth
pressure coefficient and the subgrade modulus. Do not use these numbers.
"""

from pathlib import Path

from austruct.core.units import kNm, mm
from austruct.design import as3600
from austruct.materials import concrete
from austruct.report import HtmlRenderer, Report, SignatureBlock
from austruct.sections import rc_beam
from austruct.structures import (
    BoxCulvert,
    CulvertGeometry,
    CulvertLoading,
    PerimeterLayout,
    Wall,
)


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


# ---------------------------------------------------------------------------
banner("1 | THE CULVERT AS A CLOSED FRAME")
# ---------------------------------------------------------------------------
geometry = CulvertGeometry(
    clear_span=3000 * mm,
    clear_height=2400 * mm,
    top_thickness=300 * mm,
    base_thickness=350 * mm,
    wall_thickness=300 * mm,
)
loading = CulvertLoading(fill_depth=1000 * mm, fill_density=2000, k0=0.5)
culvert = BoxCulvert(geometry=geometry, loading=loading, name="Culvert C1")

print("\n".join(culvert.describe()))

results = culvert.solve()
print()
print("\n".join(results.describe()))

top = dict(results.wall_moments(Wall.TOP))
hog, sag = top[0.0], top[0.5]
w = (
    loading.vertical_pressure_at(loading.fill_depth)
    + loading.concrete_density * 9.81e-9 * geometry.top_thickness
) * geometry.transverse_width
free = w * geometry.span**2 / 8

print("\n  Hand check on the top slab (sagging positive, inside face):")
print(f"    corner hogging   {hog / kNm:8.2f} kN.m")
print(f"    midspan sagging  {sag / kNm:8.2f} kN.m")
print(f"    sum              {(abs(hog) + sag) / kNm:8.2f} kN.m")
print(f"    free bending wL^2/8 = {free / kNm:8.2f} kN.m   <- must match the sum")
print("\n  A simply supported model would report ZERO at the corners, where")
print(f"  this frame finds {abs(hog) / kNm:.1f} kN.m of hogging -- that is top steel")
print("  the simpler model never asks for.")

# ---------------------------------------------------------------------------
banner("2 | DIRECTING THE NODES ONTO THE PEAKS")
# ---------------------------------------------------------------------------
print("A frame reports actions at nodes. A peak between two nodes is invisible.\n")

fine = culvert.with_layout(PerimeterLayout(default_divisions=200)).solve()
target = max(m_ for _, m_ in fine.wall_moments(Wall.TOP))

coarse = culvert.with_layout(PerimeterLayout(default_divisions=3))
print(f"  {'mesh':<22}{'nodes':>7}{'reported sagging':>19}{'error':>9}")
print("  " + "-" * 57)
for label, model in (
    ("3 divisions", coarse),
    ("3 divisions, refined", coarse.refined()),
    ("8 divisions", culvert),
    ("200 divisions", culvert.with_layout(PerimeterLayout(default_divisions=200))),
):
    solved = model.solve()
    reported = max(m_ for _, m_ in solved.wall_moments(Wall.TOP))
    n = len(model.build()[0].nodes)
    err = abs(reported - target) / abs(target) * 100
    print(f"  {label:<22}{n:>7}{reported / kNm:>16.2f} kN.m{err:>8.2f}%")

print("\n  refined() solves, finds the zero-shear point inside every member by")
print("  statics, and pins a node exactly there. Four extra nodes take the error")
print("  from 26% to 2% -- a factor of twelve for a third more model.")

print("\n  Placing a node by hand, in the terms the drawing uses:\n")
directed = (
    culvert.with_node_at_distance(Wall.TOP, 750 * mm, "construction joint")
    .with_node_at(Wall.LEFT, 0.5, "mid-height check")
    .refined(keep_existing=True)
)
print("\n".join("  " + line for line in directed.layout.describe()))

# ---------------------------------------------------------------------------
banner("3 | DESIGNING THE TOP SLAB")
# ---------------------------------------------------------------------------
design = culvert.refined()
solved = design.solve()
sag_frac, m_sag = max(solved.wall_moments(Wall.TOP), key=lambda p: p[1])
hog_frac, m_hog = min(solved.wall_moments(Wall.TOP), key=lambda p: p[1])

STRIP = geometry.transverse_width
section = rc_beam(
    b=STRIP, D=geometry.top_thickness, concrete=concrete(40), cover=45,
    n_bars=5, diameter=20, fitment_diameter=0, fitment_spacing=None,
    name="Top slab, sagging",
)

flexure = as3600.check_flexure(section, abs(m_sag))
print(f"Sagging {m_sag / kNm:.1f} kN.m at fraction {sag_frac:.3f} (midspan)")
print(f"Hogging {m_hog / kNm:.1f} kN.m at fraction {hog_frac:.3f} (corner)")
print(f"\n  5-N20 per metre: phi.Muo = {flexure.get('phiMuo') / kNm:.1f} kN.m, "
      f"utilisation {flexure.utilisation:.3f} -> "
      f"{'PASS' if flexure.passed else 'FAIL'}")

# ---------------------------------------------------------------------------
banner("4 | SERVICEABILITY AND DETAILING")
# ---------------------------------------------------------------------------
# Service moment: strip the load factors off, roughly, for the illustration.
m_service = abs(m_sag) / 1.35

crack = as3600.check_crack_control(
    section, m_service, cover=45, fitment_diameter=0
)
print(f"Crack control: f_s = {crack.get('f_s'):.0f} MPa, "
      f"max bar {crack.get('max_bar_diameter'):.0f} mm -> "
      f"{'PASS' if crack.passed else 'FAIL'}")

deflection = as3600.check_deflection(
    section,
    span=geometry.span,
    delta_sustained=3.0 * mm,
    delta_transient=1.0 * mm,
    M_s_max=m_service,
    sigma_cs=1.0,
)
print(f"Deflection:    I_ef/I = {deflection.get('I_ef') / deflection.get('I_uncracked'):.2f}, "
      f"total {deflection.get('delta_total'):.1f} mm vs limit "
      f"{geometry.span / 250:.1f} mm -> "
      f"{'PASS' if deflection.passed else 'FAIL'}")

detailing = as3600.check_detailing(section, cover=45, available_anchorage=900 * mm)
print(f"Detailing:     {'PASS' if detailing.passed else 'FAIL'} "
      f"(utilisation {detailing.utilisation:.3f})")
for note in detailing.messages[:2]:
    print(f"  NOTE: {note}")

# ---------------------------------------------------------------------------
banner("5 | A REPORT SOMEONE ELSE CAN READ")
# ---------------------------------------------------------------------------
report = Report(
    title="Culvert C1 -- top slab design",
    signature=SignatureBlock(
        job_number="24-001",
        job_name="Example Road Upgrade",
        element="Culvert C1, top slab",
        designed_by="A. Morrison",
        revision="A",
    ),
)

# The engineer's words go WHERE THEY BELONG -- between the calculations they
# explain, not appended at the end where nobody reads them.
report.add_scope(
    "This calculation covers the top slab of culvert C1 in flexure, crack "
    "control and deflection. The walls and base slab are covered separately. "
    "Fatigue is not assessed: the structure carries no rail traffic and the "
    "fill depth exceeds 1 m, so the live load stress range is small."
)
report.add_assumption(
    "The culvert is founded on competent granular material with a modulus of "
    "subgrade reaction of 30 MPa/m, taken from the geotechnical report. "
    "Backfill is compacted granular fill at 20 kN/m3 with an at-rest earth "
    "pressure coefficient of 0.5.\n\n"
    "The structure is analysed as a closed frame on member centrelines. "
    "Haunches are present on the drawing but are not modelled, which is "
    "conservative for the corner moments."
)

report.add(flexure)
report.add_narrative(
    "The corner hogging moment governs the top face reinforcement. A simply "
    "supported idealisation of the top slab reports zero moment there, which "
    "is why the closed frame analysis was used."
)
report.add(crack)
report.add(deflection)
report.add_narrative(
    "Deflection is not critical for this member -- the slab is short and deep "
    "-- but it is reported because the shrinkage assumption drives the "
    "cracking moment and therefore the crack control check above."
)
report.add(detailing)
report.add_limitation(
    "Every code constant used by this package is currently UNVERIFIED against "
    "the printed standard, and the report is marked accordingly. It must not "
    "be issued until that verification is complete and recorded."
)
report.add_conclusion(
    "The 300 mm top slab with 5-N20 per metre is adequate in flexure, crack "
    "control and deflection, subject to the verification noted above."
)

print(f"Report: {len(report.results)} calculations, "
      f"{len(report.narratives)} narrative blocks, in one ordered body.")
print(f"  passed   = {report.passed}")
print(f"  issuable = {report.issuable}   <- no module is verified yet")
print(f"  states its assumptions  = {report.has_narrative(report.narratives[1].kind)}")

out = Path("culvert_c1_report.html")
out.write_text(report.render(HtmlRenderer()), encoding="utf-8")
print(f"\n  Written to {out} -- one self-contained file, no external requests,")
print("  prints to PDF from any browser, and carries the NOT VERIFIED banner")
print("  on every printed page.")

print("\n" + "=" * 76)
print("Reminder: the code constants, the earth pressure coefficient and the")
print("subgrade modulus are all UNVERIFIED. Check them before using any of this.")
print("=" * 76)
