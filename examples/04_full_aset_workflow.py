"""Example 4 -- all six ASET components in one workflow.

Walks a beam from a project record through to a signed report, touching every
component of the framework in the order the framework describes them:

    1. Reference data          concrete grade, bar catalogue -- from JSON
    2. Project data            job record -> psi factors -> load combinations
    3. Fast demand calculation analysis over every combination, enveloped
    4. Design documentation    the design as a plain-text designation + schedule
    5. Design verification     AS 3600 flexure and shear against the envelope
    6. Reporting               the fixed audit layout

Run:  python examples/04_full_aset_workflow.py
"""

from austruct.analysis import UDL, PointLoad, analyse_combinations, simply_supported
from austruct.core.registry import REGISTRY
from austruct.core.units import kN, kN_per_m, kNm, m
from austruct.design import as3600
from austruct.design_documentation import (
    ScheduleEntry,
    designate,
    parse,
    schedule_report,
)
from austruct.loads import ActionType, LoadCase
from austruct.materials import _data, concrete, describe_options
from austruct.project import (
    ExposureClassification,
    Occupancy,
    Project,
    StructureType,
)
from austruct.report import MarkdownRenderer, Report


def banner(n: int, text: str) -> None:
    print(f"\n{'=' * 74}\n{n} | {text}\n{'=' * 74}")


# ---------------------------------------------------------------------------
banner(1, "REFERENCE DATA -- looked up, not derived")
# ---------------------------------------------------------------------------
grade = concrete(40)
print("Concrete grade 40, from materials/data/concrete_grades.json:")
for line in grade.describe():
    print("   ", line)
print("\nVerification status of the reference data:")
print(_data.data_verification_report())

# ---------------------------------------------------------------------------
banner(2, "PROJECT DATA -- client information converted to design parameters")
# ---------------------------------------------------------------------------
project = Project(
    job_number="24-1234",
    job_name="Riverside Apartments",
    client="Acme Developments",
    site_address="12 River Road, Newcastle",
    jurisdiction="NSW",
    structure_type=StructureType.BUILDING,
    occupancy=Occupancy.RESIDENTIAL,
    exposure=ExposureClassification.B1,
    design_life_years=50,
    importance_level=2,
    engineer="A. Morrison",
)
for line in project.describe():
    print("   ", line)

combinations = project.load_combinations(sls=False)
print("\nCombinations derived from the stated occupancy:")
for combo in combinations:
    print("   ", combo)

# ---------------------------------------------------------------------------
banner(3, "FAST DEMAND CALCULATION -- analysed, then enveloped")
# ---------------------------------------------------------------------------
SPAN = 8.0 * m
cases = (
    LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),)),
    LoadCase(
        "Q",
        ActionType.Q,
        (UDL(magnitude=15 * kN_per_m), PointLoad(position=SPAN / 2, magnitude=60 * kN)),
    ),
)
beam = simply_supported(SPAN, EI=grade.Ec * (350 * 650**3 / 12), name="B1")
envelope = analyse_combinations(beam, cases, combinations)
print(envelope.summary())

print("\nQueryable factored forces (the ASET storage shape):")
forces = envelope.to_dict()
mz = forces["B1"]["moment"]["Mz"]
print(f'   forces["B1"]["moment"]["Mz"]["fact_max"]        = {mz["fact_max"]:.1f} kN.m')
print(f'   forces["B1"]["moment"]["Mz"]["fact_max_combo"]  = {mz["fact_max_combo"]}')

# ---------------------------------------------------------------------------
banner(4, "DESIGN DOCUMENTATION -- the decision, in plain text")
# ---------------------------------------------------------------------------
designation = "350 x 650 | C40 | COV 40 | BOT 4-N28 | LIG N12-2L@200"
section = parse(designation, name="B1")
print(f"   Designation : {designation}")
print(f"   Round trips : {designate(section) == designation}")
print(f"   -> b = {section.b:.0f}, D = {section.D:.0f}, d = {section.d:.0f} mm, "
      f"Ast = {section.Ast:.0f} mm2, fitments {section.fitment}")

schedule = [
    ScheduleEntry("B1", designation, notes="typical internal"),
    ScheduleEntry("B2", "300 x 600 | C32 | BOT 3-N24 | LIG N12-2L@250"),
    ScheduleEntry("B3", "400 x 900 | C50 | T 1200/150 | BOT 6-N32 | LIG N16-2L@150"),
]
print("\nMember schedule (this is what a drafter works from):")
print(schedule_report(schedule))

# ---------------------------------------------------------------------------
banner(5, "DESIGN VERIFICATION -- demand against capacity")
# ---------------------------------------------------------------------------
M_star = envelope.M_star
V_star = envelope.shear_at_d_from_support(section.d)

flexure = as3600.check_flexure(section, M_star)
shear = as3600.check_shear(section, V_star=V_star, M_star=M_star)

print(f"   M* = {M_star / kNm:7.1f} kN.m [{envelope.moment.governing_combo}]"
      f"   phi.Muo = {flexure.get('phiMuo') / kNm:7.1f} kN.m"
      f"   util {flexure.utilisation:.3f}   {'PASS' if flexure.passed else 'FAIL'}")
print(f"   V* = {V_star / kN:7.1f} kN   [{envelope.shear.governing_combo}]"
      f"   phi.Vu  = {shear.get('phiVu') / kN:7.1f} kN  "
      f"   util {shear.utilisation:.3f}   {'PASS' if shear.passed else 'FAIL'}")

print("\n   Alternative bar arrangements for the required area:")
required = as3600.required_steel_area(section, M_star)
for line in describe_options(required.get("Ast_req")).splitlines():
    print("     ", line)

# ---------------------------------------------------------------------------
banner(6, "REPORTING -- the fixed audit layout")
# ---------------------------------------------------------------------------
report = Report(
    title=f"Beam B1 -- {project.job_name}",
    signature=project.signature_block(element="Beam B1", revision="A"),
    preamble=(
        f"Simply supported beam, {SPAN / 1000:.1f} m span, {designation}. "
        f"Demands enveloped over {len(envelope.combinations)} ULS combinations "
        f"derived from the project record."
    ),
)
report.add(envelope.to_calc_result())
report.add(flexure)
report.add(shear)

markdown = report.render(MarkdownRenderer())
print(f"   Report rendered: {len(markdown.splitlines())} lines of markdown")
print(f"   All checks pass : {report.passed}")
print(f"   Issuable        : {report.issuable}")
print("\n   First 12 lines:")
for line in markdown.splitlines()[:12]:
    print("     ", line)

# ---------------------------------------------------------------------------
banner(0, "FRAMEWORK COVERAGE")
# ---------------------------------------------------------------------------
print(REGISTRY.coverage())
print()
print(REGISTRY.summary())
