"""Example 8 -- AS 4100 steel design, and why section capacity is not the answer.

  1. The catalogue, and the cross-check that polices it.
  2. Classification: why Z_e is not a property of the geometry alone.
  3. The gate: section capacity refuses to answer for an unrestrained beam.
  4. Lateral-torsional buckling, and alpha_m off the real moment diagram.
  5. Choosing a section, with the restraint spacing as the design variable.
  6. A column, and combined actions.

Run:  OMP_NUM_THREADS=1 python examples/08_steel_beam.py

NOTE: the section dimensions and every AS 4100 constant here are UNVERIFIED.
"""

from austruct.analysis import UDL, analyse_combinations, simply_supported
from austruct.core.units import kN, kN_per_m, kNm, m
from austruct.design import as4100
from austruct.loads import ActionType, LoadCase, as1170_uls
from austruct.sections import steel_catalogue as cat

cat.allow_unverified(True)


def banner(text: str) -> None:
    print(f"\n{'=' * 76}\n{text}\n{'=' * 76}")


# ---------------------------------------------------------------------------
banner("1 | THE CATALOGUE CHECKS ITSELF")
# ---------------------------------------------------------------------------
print("Every other reference file here can only be checked against the printed")
print("source. This one holds the dimensions AND the published properties, and")
print("the second follows from the first -- so they can be compared.\n")

verification = cat.verify_catalogue("UB")
print(f"  Universal beams: {'PASS' if verification.passed else 'FAIL'}")
print("  Systematic error, computed against published:")
for prop in ("A", "Ix", "Sx", "Iy", "J"):
    print(f"    {prop:<4}{verification.mean_error(prop) * 100:>8.2f}%")
print("\n  All low on the major axis and barely moved on the minor -- that is")
print("  the signature of the unmodelled root radii, not of a mistake. J is")
print("  worst because torsion is most sensitive to material at the junction.")

whole = cat.verify_catalogue()
if whole.inconsistent_sections:
    print(f"\n  {len(whole.inconsistent_sections)} section(s) FAIL the three-way area check:")
    for check in whole.inconsistent_sections:
        print(f"    {check.implied_note()}")

# ---------------------------------------------------------------------------
banner("2 | CLASSIFICATION -- Z_e IS NOT GEOMETRY ALONE")
# ---------------------------------------------------------------------------
beam = cat.get("360UB50.7")
slenderness = as4100.classify(beam)
print("\n".join(slenderness.describe()))

print(f"\n  f_y flange {beam.fy_flange:.0f} MPa, web {beam.fy_web:.0f} MPa -- the web is")
print("  thinner, so it is stronger. Flexure uses the flange value, shear the web.")

stronger = as4100.classify(beam.with_grade("350"))
print(f"\n  In Grade 350 the same steel gets lambda_s = {stronger.lambda_s:.2f} "
      f"against {slenderness.lambda_s:.2f}:")
print("  a higher grade is MORE prone to local buckling for the same geometry.")

# ---------------------------------------------------------------------------
banner("3 | THE GATE")
# ---------------------------------------------------------------------------
try:
    as4100.check_flexure(beam, 200 * kNm)
except Exception as exc:
    print("check_flexure(beam, M*) raises:\n")
    print("\n".join("  " + line for line in str(exc).splitlines()[:4]))

# ---------------------------------------------------------------------------
banner("4 | LATERAL-TORSIONAL BUCKLING")
# ---------------------------------------------------------------------------
ms = as4100.section_moment_capacity(beam).get("Ms")
print(f"{beam.designation}:  M_s = {ms / kNm:.1f} kN.m\n")
print(f"  {'restraint':>10}{'l_e':>8}{'M_o':>10}{'alpha_s':>9}{'M_b':>10}{'M_b/M_s':>9}")
print(f"  {'spacing m':>10}{'m':>8}{'kN.m':>10}{'':>9}{'kN.m':>10}{'':>9}")
print("  " + "-" * 56)
for spacing in (1, 2, 3, 4, 6, 9, 12):
    state = as4100.buckling_state(beam, as4100.fully_restrained(spacing * m))
    print(f"  {spacing:>10.0f}{state.le / 1000:>8.1f}{state.Mo / kNm:>10.1f}"
          f"{state.alpha_s:>9.3f}{state.Mb / kNm:>10.1f}{state.reduction:>9.0%}")

print("\n  From 99% of the section capacity at 1 m to under a fifth at 12 m.")
print("  A design that stopped at M_s would be wrong by a factor of five.")

# -- alpha_m from the analysis layer ----------------------------------------
SPAN = 9.0 * m
member = simply_supported(SPAN, EI=beam.grade.E * beam.properties.Ix, name="B1")
cases = (
    LoadCase("G", ActionType.G, (UDL(magnitude=8 * kN_per_m),)),
    LoadCase("Q", ActionType.Q, (UDL(magnitude=6 * kN_per_m),)),
)
envelope = analyse_combinations(member, cases, as1170_uls())
m_star = envelope.M_star
v_star = envelope.V_star

alpha_m = as4100.alpha_m_from_diagram(
    envelope.moment.x, envelope.moment.max_values, 0.0, SPAN
)
print(f"\n  A {SPAN / 1000:.0f} m simply supported beam, M* = {m_star / kNm:.1f} kN.m:")
print(f"    alpha_m read off the solved moment diagram = {alpha_m:.3f}")
print(f"    (uniform moment would be {as4100.alpha_m_from_moments(1, 1, 1, 1):.3f})")
print("\n  The solver already produces the quarter-point moments alpha_m needs,")
print("  so the real diagram is used rather than the nearest textbook case.")

# ---------------------------------------------------------------------------
banner("5 | CHOOSING A SECTION -- RESTRAINT SPACING IS THE VARIABLE")
# ---------------------------------------------------------------------------
print(f"M* = {m_star / kNm:.1f} kN.m over {SPAN / 1000:.0f} m.\n")
print(f"  {'restraint':>10}{'section needed':>18}{'mass':>9}{'phi.M_b':>10}{'util':>8}")
print(f"  {'spacing':>10}{'':>18}{'kg/m':>9}{'kN.m':>10}{'':>8}")
print("  " + "-" * 55)

candidates = [n for n in cat.names("UB")]
for spacing in (SPAN, SPAN / 2, SPAN / 3, SPAN / 6):
    seg = as4100.fully_restrained(spacing)
    chosen = None
    for designation in sorted(candidates, key=lambda d: cat.get(d).mass):
        candidate = cat.get(designation)
        result = as4100.check_member_flexure(candidate, m_star, seg, alpha_m=alpha_m)
        if result.passed:
            chosen = (candidate, result)
            break
    if chosen:
        section, result = chosen
        print(f"  {spacing / 1000:>8.1f} m{section.designation:>18}"
              f"{section.mass:>9.1f}{result.get('phiMb') / kNm:>10.1f}"
              f"{result.utilisation:>8.3f}")
    else:
        print(f"  {spacing / 1000:>8.1f} m{'none in catalogue':>18}")

print("\n  Halving the restraint spacing is worth more than two section sizes.")
print("  On a steel beam the bracing is a design decision, not a detail.")

# -- and the shear check, which is rarely critical on a rolled beam ---------
final = cat.get("360UB50.7")
shear = as4100.check_shear(final, v_star)
print(f"\n  Shear: V* = {v_star / kN:.1f} kN vs phi.V_v = "
      f"{shear.get('phiVv') / kN:.1f} kN -> "
      f"{'PASS' if shear.passed else 'FAIL'} (util {shear.utilisation:.3f})")
print("  Rolled beams are rarely shear-critical -- the web is stocky and yields")
print("  rather than buckling. Plate girders are a different matter.")

# ---------------------------------------------------------------------------
banner("6 | A COLUMN, AND COMBINED ACTIONS")
# ---------------------------------------------------------------------------
column = cat.get("200UC46.2")
ns = as4100.section_compression_capacity(column).get("Ns")
print(f"{column.designation}:  N_s = {ns / kN:.0f} kN\n")
print(f"  {'height':>8}{'lambda_n':>11}{'alpha_c':>9}{'phi.N_c kN':>13}")
print("  " + "-" * 41)
for height in (2, 3, 4, 6):
    result = as4100.member_compression_capacity(column, height * m)
    print(f"  {height:>6.0f} m{result.get('lambda_n'):>11.1f}"
          f"{result.get('alpha_c'):>9.3f}{result.get('phiNc') / kN:>13.0f}")

print("\n  Combined bending and compression at 4 m -- the check that stops two")
print("  separate 'passes' adding up to a failure:\n")

seg = as4100.fully_restrained(4 * m)
phi_nc = as4100.member_compression_capacity(column, 4 * m).get("phiNc")
phi_mb = as4100.member_moment_capacity(column, seg).get("phiMb")

for label, n_frac, m_frac in (
    ("light", 0.30, 0.30),
    ("moderate", 0.50, 0.40),
    ("both at 70%", 0.70, 0.70),
):
    combined = as4100.check_combined_member(
        column, n_frac * phi_nc, m_frac * phi_mb, seg, 4 * m
    )
    print(f"  {label:<14} N* {n_frac:.0%} of capacity, M* {m_frac:.0%} "
          f"-> interaction {combined.get('interaction'):.2f}  "
          f"{'PASS' if combined.passed else 'FAIL'}")

print("\n  Seventy per cent plus seventy per cent is not seventy per cent.")

print("\n" + "=" * 76)
print("Reminder: the section dimensions are RECALLED, not transcribed, and")
print("every AS 4100 constant is UNVERIFIED. The cross-check confirms the")
print("catalogue is self-consistent -- not that it is right.")
print("=" * 76)
