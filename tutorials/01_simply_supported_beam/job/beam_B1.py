"""25-0142 Northbank Depot -- roof beam B1.

Simply supported, 7.2 m, analysed over the AS/NZS 1170.0 ultimate combinations
and designed for flexure and shear to AS 3600:2018.

Run from this directory:

    python beam_B1.py

Nothing in this file calculates a capacity. Every number that comes from a
standard comes out of an imported, version-controlled module; this file only
says what the member is, what is on it, and what to check.
"""

from pathlib import Path

from austruct.analysis import UDL, PointLoad, SelfWeight, analyse_combinations, simply_supported
from austruct.core.units import kN, kN_per_m, kNm, kPa, m
from austruct.design import as3600
from austruct.design_documentation import designate, parse
from austruct.loads import ActionType, LoadCase
from austruct.materials import describe_options
from austruct.report import HtmlRenderer, MarkdownRenderer, Report, plots

# Your own job file, sitting next to this one. Same import machinery, no
# package install -- Python looks in the script's own directory first.
import job_data as job

# ---------------------------------------------------------------------------
# 1. The design decision, written the way it goes on the drawing
# ---------------------------------------------------------------------------
DESIGNATION = "350 x 650 | C32 | COV 40 | BOT 3-N24 | LIG N12-2L@250"
section = parse(DESIGNATION, name="B1")

assert designate(section) == DESIGNATION, "designation does not round-trip"

print("SECTION")
for line in section.describe():
    print("   ", line)

# ---------------------------------------------------------------------------
# 2. Load cases -- unfactored, each tagged with the action it represents
# ---------------------------------------------------------------------------
cases = (
    LoadCase(
        "G_roof",
        ActionType.G,
        (
            UDL(magnitude=job.W_G),
            SelfWeight(area=section.geometry.area, density=2400.0, length=job.SPAN),
        ),
    ),
    LoadCase(
        "Q_roof",
        ActionType.Q,
        (
            UDL(magnitude=job.W_Q),
            PointLoad(position=job.PLANT_POSITION, magnitude=job.Q_PLANT),
        ),
    ),
    LoadCase(
        "Wu_uplift",
        ActionType.Wu,
        # [UNITS] Upward is negative in this package's sign convention.
        (UDL(magnitude=-job.W_WU),),
    ),
)

# [UNITS] A UDL learns its own length when it is attached to a beam, so its
#         total force is not known yet here -- print the intensity instead.
print("\nLOAD CASES (unfactored)")
for case in cases:
    for load in case.loads:
        kind = type(load).__name__
        if kind == "PointLoad":
            what = f"{load.magnitude / kN:6.1f} kN at {load.position / m:.1f} m"
        else:
            what = f"{load.magnitude / kN_per_m:6.2f} kN/m"
        print(f"    {case.name:<10} {case.action.value:<3} {kind:<11} {what}")

# ---------------------------------------------------------------------------
# 3. Analyse over every ULS combination the project record implies
# ---------------------------------------------------------------------------
combinations = job.PROJECT.load_combinations(sls=False)

print("\nCOMBINATIONS (AS/NZS 1170.0 Cl 4.2.2, psi factors from the occupancy)")
for combo in combinations:
    print("   ", combo)

beam = simply_supported(job.SPAN, section=section, name="B1")
env = analyse_combinations(beam, cases, combinations)

print("\nENVELOPE")
print(env.summary())

# ---------------------------------------------------------------------------
# 4. Design verification to AS 3600:2018
# ---------------------------------------------------------------------------
M_star = env.M_star
V_star = env.shear_at_d_from_support(section.d)

flexure = as3600.check_flexure(section, M_star)
shear = as3600.check_shear(section, V_star=V_star, M_star=M_star)

print("\nAS 3600:2018 CHECKS")
print(f"    M* = {M_star / kNm:7.1f} kN.m  [{env.moment.governing_combo}]"
      f"   phi.Muo = {flexure.get('phiMuo') / kNm:7.1f} kN.m"
      f"   util {flexure.utilisation:.3f}  {'PASS' if flexure.passed else 'FAIL'}")
print(f"    V* = {V_star / kN:7.1f} kN    [{env.shear.governing_combo}]"
      f"   phi.Vu  = {shear.get('phiVu') / kN:7.1f} kN  "
      f"   util {shear.utilisation:.3f}  {'PASS' if shear.passed else 'FAIL'}")

print(f"\n    Reversal check: M*_hogging = {env.M_star_hogging / kNm:.1f} kN.m"
      f"  ->  {'top steel required' if env.M_star_hogging < 0 else 'no reversal, section as detailed'}")

print("\n    Bar arrangements that would satisfy the required area:")
required = as3600.required_steel_area(section, M_star)
for line in describe_options(required.get("Ast_req")).splitlines():
    print("     ", line)

# ---------------------------------------------------------------------------
# 5. Figures
# ---------------------------------------------------------------------------
# A path relative to THIS file, not to whatever directory you happen to be
# standing in when you run it. `python job/beam_B1.py` from one level up would
# break a bare "../outputs".
OUT = Path(__file__).resolve().parent.parent / "outputs"

# The governing combination on its own, so the shear, moment and deflection
# diagrams can be read the way they are drawn by hand. `combo.apply(cases)`
# is the same factoring the envelope did -- done once here, visibly.
governing_combo = next(c for c in combinations if c.name == env.moment.governing_combo)
governing_beam = simply_supported(
    job.SPAN, loads=governing_combo.apply(cases), section=section, name=f"B1 -- {governing_combo.name}"
)
fig_dia = plots.plot_diagrams(governing_beam.solve())
plots.save(fig_dia, f"{OUT}/B1_diagrams.png")

fig_env = plots.plot_envelope(env, show_cases=True)
plots.save(fig_env, f"{OUT}/B1_envelope.png")

fig_sec = plots.plot_section(section)
plots.save(fig_sec, f"{OUT}/B1_section.png")

# ---------------------------------------------------------------------------
# 6. The report
# ---------------------------------------------------------------------------
report = Report(
    title=f"Roof beam B1 -- {job.PROJECT.job_name}",
    signature=job.PROJECT.signature_block(element="Roof beam B1", revision="A"),
    preamble=(
        f"Simply supported roof beam, {job.SPAN / m:.1f} m clear span, {DESIGNATION}. "
        f"Demands enveloped over {len(env.combinations)} ultimate combinations to "
        f"AS/NZS 1170.0; capacities to AS 3600:2018."
    ),
)
report.add_scope(
    "Flexural and shear strength of B1 at the ultimate limit state only. "
    "Deflection, crack control, anchorage and the supporting blockwork are "
    "outside this calculation."
)
report.add_assumption(
    f"Permanent action {job.G_AREAL / kPa:.2f} kPa over a {job.TRIB_WIDTH / m:.1f} m "
    f"tributary width, plus beam self weight at 24 kN/m3. Imposed action "
    f"{job.Q_AREAL / kPa:.2f} kPa (AS/NZS 1170.1 Table 3.2, non-trafficable roof) "
    f"with a {job.Q_PLANT / kN:.0f} kN plant load at {job.PLANT_POSITION / m:.1f} m. "
    f"Ultimate wind uplift {job.W_WU / kN_per_m:.2f} kN/m from "
    f"V_des = {job.design_wind_speed():.1f} m/s to AS/NZS 1170.2."
)
report.add(env.to_calc_result())
report.add_figure(f"Shear, moment and deflection under the governing combination ({governing_combo.name})", "B1_diagrams.png")
report.add_figure("Moment and shear envelopes over all ULS combinations", "B1_envelope.png")
report.add(flexure)
report.add(shear)
report.add_figure("Section as detailed", "B1_section.png")
report.add_conclusion(
    f"B1 as detailed ({DESIGNATION}) is adequate in flexure "
    f"(utilisation {flexure.utilisation:.2f}) and in shear "
    f"(utilisation {shear.utilisation:.2f}) at the ultimate limit state."
)

with open(f"{OUT}/B1_report.md", "w") as f:
    f.write(report.render(MarkdownRenderer()))
with open(f"{OUT}/B1_report.html", "w") as f:
    f.write(report.render(HtmlRenderer()))

print(f"\nREPORT   all checks pass: {report.passed}   issuable: {report.issuable}")
print(f"         figures and report written to {OUT.name}/")
