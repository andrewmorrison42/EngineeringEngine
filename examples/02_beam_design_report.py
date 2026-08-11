"""Example 2 -- end-to-end beam design with an audit report.

Analyse a beam, design it in flexure and shear to AS 3600:2018, then emit the
standard report artifact. This is the Type B workflow from the roadmap's
Phase 0 classification: design per job, calc with an audit trail, per-job
engineer sign-off.

Run:  python examples/02_beam_design_report.py
      python examples/02_beam_design_report.py > beam_design.md
"""

from datetime import date

from austruct.analysis import UDL, PointLoad, simply_supported
from austruct.core.units import kN, kN_per_m, kNm, m
from austruct.design import as3600
from austruct.materials import concrete, describe_options
from austruct.report import MarkdownRenderer, Report, SignatureBlock
from austruct.sections import rc_beam

# ---------------------------------------------------------------------------
# 1. Define the member
# ---------------------------------------------------------------------------
SPAN = 8.0 * m
DEAD = 20.0 * kN_per_m
LIVE = 15.0 * kN_per_m
POINT = 60.0 * kN

# [ASSUMPTION] Load factors applied by hand here. The load-combination module
#              (loads/combinations.py) is not built yet -- when it is, this
#              becomes a call rather than a literal.
W_ULS = 1.2 * DEAD + 1.5 * LIVE
P_ULS = 1.5 * POINT

section = rc_beam(
    b=350,
    D=650,
    concrete=concrete(40),
    cover=40,
    n_bars=4,
    diameter=28,
    fitment_diameter=12,
    fitment_spacing=200,
    name="B1 -- typical internal beam",
)

# ---------------------------------------------------------------------------
# 2. Analyse
# ---------------------------------------------------------------------------
beam = simply_supported(
    SPAN,
    loads=(UDL(magnitude=W_ULS), PointLoad(position=SPAN / 2, magnitude=P_ULS)),
    section=section,
    name="B1",
)
results = beam.solve()

M_star = results.max_moment
# Both standards permit the design shear at d from the support where the
# support introduces compression into the member.
V_star = max(results.shear_at_d_from_support(section.d))

# ---------------------------------------------------------------------------
# 3. Design checks
# ---------------------------------------------------------------------------
flexure = as3600.check_flexure(section, M_star)
shear = as3600.check_shear(section, V_star=V_star, M_star=M_star)

# ---------------------------------------------------------------------------
# 4. Assemble the report -- the fixed Phase 2 layout
# ---------------------------------------------------------------------------
report = Report(
    title="Beam B1 -- flexural and shear design",
    signature=SignatureBlock(
        job_number="24-1234",
        job_name="Example Project",
        element="Beam B1",
        designed_by="A. Morrison",
        designed_on=date.today(),
        revision="A",
    ),
    preamble=(
        f"Simply supported beam, {SPAN / 1000:.1f} m span. "
        f"Design actions from a ULS combination of "
        f"{DEAD / kN_per_m:.0f} kN/m dead and {LIVE / kN_per_m:.0f} kN/m live "
        f"plus a {POINT / kN:.0f} kN point load at midspan."
    ),
)
report.add(results.to_calc_result())
report.add(flexure)
report.add(shear)

print(report.render(MarkdownRenderer()))

# ---------------------------------------------------------------------------
# 5. Console summary and detailing options
# ---------------------------------------------------------------------------
print("\n---\n")
print("## Console summary\n")
print("```")
print(results.summary())
print()
print(f"M* = {M_star / kNm:7.1f} kN.m   phi.Muo = {flexure.get('phiMuo') / kNm:7.1f} kN.m "
      f"  utilisation {flexure.utilisation:.3f}   "
      f"{'PASS' if flexure.passed else 'FAIL'}")
print(f"V* = {V_star / kN:7.1f} kN     phi.Vu  = {shear.get('phiVu') / kN:7.1f} kN   "
      f"  utilisation {shear.utilisation:.3f}   "
      f"{'PASS' if shear.passed else 'FAIL'}")
print("```")

# The inverse problem: what steel would this moment actually need?
print("\n## Alternative bar arrangements\n")
required = as3600.required_steel_area(section, M_star)
print("```")
print(describe_options(required.get("Ast_req")))
print("```")
