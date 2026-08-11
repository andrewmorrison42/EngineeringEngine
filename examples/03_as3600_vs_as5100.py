"""Example 3 -- the same section checked to AS 3600:2018 and AS 5100.5:2017.

This example exists to make one architectural point visible:

- FLEXURE: both standards share the mechanics, so the nominal capacity M_uo is
  identical. Only the capacity reduction factor differs. That sharing is the
  job of ``design/rc_common``.

- SHEAR: the two are DIFFERENT MODELS. AS 3600:2018 uses a modified compression
  field theory formulation (k_v, d_v, theta_v). AS 5100.5:2017 uses the older
  AS 3600:2009 family (beta_1.beta_2.beta_3, f_cv, d_o, with theta_v
  interpolated on the web demand). They do not share code and must not be
  reconciled.

Run:  python examples/03_as3600_vs_as5100.py
"""

from austruct.core.units import kN, kNm
from austruct.design import as3600, as5100_5
from austruct.materials import concrete
from austruct.sections import rc_beam

section = rc_beam(
    b=400,
    D=900,
    concrete=concrete(40),
    cover=45,
    n_bars=6,
    diameter=32,
    fitment_diameter=16,
    fitment_spacing=150,
    fitment_legs=2,
    name="Bridge deck edge beam",
)

V_STAR = 600 * kN
M_STAR = 900 * kNm

print("=" * 74)
print("SECTION")
print("=" * 74)
for line in section.describe():
    print(" ", line)

# ---------------------------------------------------------------------------
print("\n" + "=" * 74)
print("FLEXURE -- shared mechanics, different phi")
print("=" * 74)
# ---------------------------------------------------------------------------
f3600 = as3600.moment_capacity(section)
f5100 = as5100_5.moment_capacity(section)

print(f"{'':<28}{'AS 3600:2018':>18}{'AS 5100.5:2017':>18}")
print("-" * 74)
print(f"{'k_uo':<28}{f3600.intermediates['kuo'].value:>18.4f}"
      f"{f5100.intermediates['kuo'].value:>18.4f}")
print(f"{'Neutral axis d_n (mm)':<28}{f3600.intermediates['dn'].value:>18.1f}"
      f"{f5100.intermediates['dn'].value:>18.1f}")
print(f"{'Lever arm z (mm)':<28}{f3600.intermediates['z'].value:>18.1f}"
      f"{f5100.intermediates['z'].value:>18.1f}")
print(f"{'M_uo (kN.m)':<28}{f3600.get('Muo') / kNm:>18.1f}"
      f"{f5100.get('Muo') / kNm:>18.1f}   <- identical")
print(f"{'phi':<28}{f3600.get('phi'):>18.3f}{f5100.get('phi'):>18.3f}   <- differs")
print(f"{'phi.M_uo (kN.m)':<28}{f3600.get('phiMuo') / kNm:>18.1f}"
      f"{f5100.get('phiMuo') / kNm:>18.1f}")

delta = (f5100.get("phiMuo") / f3600.get("phiMuo") - 1) * 100
print(f"\nAS 5100.5 design capacity is {delta:+.1f}% relative to AS 3600.")

# ---------------------------------------------------------------------------
print("\n" + "=" * 74)
print("SHEAR -- genuinely different models")
print("=" * 74)
# ---------------------------------------------------------------------------
s3600 = as3600.check_shear(section, V_star=V_STAR, M_star=M_STAR, method="simplified")
s3600g = as3600.check_shear(section, V_star=V_STAR, M_star=M_STAR, method="general")
s5100 = as5100_5.check_shear(section, V_star=V_STAR)

print(f"{'':<28}{'AS3600 simpl.':>16}{'AS3600 general':>16}{'AS5100.5':>14}")
print("-" * 74)


def row(label, a, b, c, fmt="{:>16.1f}", fmt_c="{:>14.1f}"):
    sa = fmt.format(a) if a is not None else f"{'--':>16}"
    sb = fmt.format(b) if b is not None else f"{'--':>16}"
    sc = fmt_c.format(c) if c is not None else f"{'--':>14}"
    print(f"{label:<28}{sa}{sb}{sc}")


def inter(result, key):
    """Look a quantity up wherever the module chose to file it.

    Some quantities are intermediates in one standard and echoed inputs in the
    other -- d_o is an input to the AS 5100.5 module because the whole model is
    written around it, and an intermediate in AS 3600 because d_v supersedes it.
    """
    v = result.intermediates.get(key) or result.inputs.get(key)
    return v.value if v else None


def out(result, key):
    return result.outputs[key].value if key in result.outputs else None


row("d_v (mm)", inter(s3600, "dv"), inter(s3600g, "dv"), None)
row("d_o (mm)", None, None, inter(s5100, "do"))
row("k_v", inter(s3600, "kv"), inter(s3600g, "kv"), None, "{:>16.4f}")
row("beta_1", None, None, inter(s5100, "beta1"), "{:>16.4f}", "{:>14.4f}")
row("f_cv (MPa)", None, None, inter(s5100, "fcv"), "{:>16.4f}", "{:>14.4f}")
row("theta_v (deg)", inter(s3600, "theta_v"), inter(s3600g, "theta_v"),
    inter(s5100, "theta_v"))
row("V_uc (kN)", out(s3600, "Vuc") / kN, out(s3600g, "Vuc") / kN, out(s5100, "Vuc") / kN)
row("V_us (kN)", out(s3600, "Vus") / kN, out(s3600g, "Vus") / kN, out(s5100, "Vus") / kN)
row("V_u,max (kN)", out(s3600, "Vumax") / kN, out(s3600g, "Vumax") / kN,
    out(s5100, "Vumax") / kN)
row("phi.V_u (kN)", out(s3600, "phiVu") / kN, out(s3600g, "phiVu") / kN,
    out(s5100, "phiVu") / kN)

print()
print(f"V* = {V_STAR / kN:.0f} kN")
for label, res in [
    ("AS 3600 simplified", s3600),
    ("AS 3600 general   ", s3600g),
    ("AS 5100.5         ", s5100),
]:
    status = "PASS" if res.passed else "FAIL"
    print(f"  {label}  utilisation {res.utilisation:.3f}   {status}")

# ---------------------------------------------------------------------------
print("\n" + "=" * 74)
print("BASIS -- what each result cites")
print("=" * 74)
# ---------------------------------------------------------------------------
for label, res in [("AS 3600:2018 shear", s3600), ("AS 5100.5:2017 shear", s5100)]:
    print(f"\n{label}:")
    for ref in res.basis:
        print(f"  - {ref}")

print("\n" + "=" * 74)
print("VERIFICATION STATUS")
print("=" * 74)
from austruct.core.registry import REGISTRY  # noqa: E402

print(REGISTRY.summary())
