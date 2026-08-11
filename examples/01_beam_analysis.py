"""Example 1 -- beam analysis under a range of loading conditions.

Demonstrates the analysis layer on its own: no materials, no design standard.
Shows that one general solver handles every support arrangement and load type,
and that the closed-form solutions agree with it.

Run:  python examples/01_beam_analysis.py
"""

from austruct.analysis import (
    UDL,
    AppliedMoment,
    Beam,
    PartialUDL,
    PointLoad,
    Support,
    SupportType,
    VaryingUDL,
    cantilever,
    continuous,
    fixed_fixed,
    propped_cantilever,
    simply_supported,
    ss_udl,
)
from austruct.core.units import kN, kN_per_m, kNm, m

# [UNITS] N, mm, MPa. The multipliers below make the units explicit at the
#         point of entry, which is where unit errors actually happen.
EI = 30_100.0 * (300.0 * 600.0**3 / 12.0)  # N.mm^2 -- Ec.Ig for a 300x600, f'c=32
SPAN = 8.0 * m


def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


# ---------------------------------------------------------------------------
banner("1. Support arrangements, all under the same 25 kN/m UDL")
# ---------------------------------------------------------------------------
udl = (UDL(magnitude=25.0 * kN_per_m),)

for label, beam in [
    ("Simply supported", simply_supported(SPAN, udl, EI=EI)),
    ("Cantilever", cantilever(SPAN, udl, EI=EI)),
    ("Propped cantilever", propped_cantilever(SPAN, udl, EI=EI)),
    ("Fixed both ends", fixed_fixed(SPAN, udl, EI=EI)),
    ("Two-span continuous", continuous([SPAN, SPAN], udl, EI=EI)),
]:
    r = beam.solve()
    print(
        f"{label:22s}  M_sag {r.max_moment / kNm:8.1f}   "
        f"M_hog {r.min_moment / kNm:8.1f}   "
        f"V_max {r.max_shear / kN:7.1f}   "
        f"delta {r.max_deflection:6.2f} mm"
    )

# ---------------------------------------------------------------------------
banner("2. Load types, all on the same simply supported span")
# ---------------------------------------------------------------------------
cases = {
    "Full UDL 25 kN/m": (UDL(magnitude=25 * kN_per_m),),
    "Central point 100 kN": (PointLoad(position=SPAN / 2, magnitude=100 * kN),),
    "Offset point 100 kN at 5 m": (PointLoad(position=5 * m, magnitude=100 * kN),),
    "Partial UDL 30 kN/m, 2-6 m": (
        PartialUDL(start=2 * m, end=6 * m, magnitude=30 * kN_per_m),
    ),
    "Triangular 0 to 40 kN/m": (
        VaryingUDL(start=0, end=SPAN, w_start=0, w_end=40 * kN_per_m),
    ),
    "Applied moment 100 kN.m at 3 m": (
        AppliedMoment(position=3 * m, magnitude=100 * kNm),
    ),
    "Combined UDL + 2 point loads": (
        UDL(magnitude=15 * kN_per_m),
        PointLoad(position=SPAN / 3, magnitude=50 * kN),
        PointLoad(position=2 * SPAN / 3, magnitude=50 * kN),
    ),
}

for label, loads in cases.items():
    r = simply_supported(SPAN, loads, EI=EI).solve()
    print(
        f"{label:32s}  R_A {r.reactions[0].force / kN:7.1f}   "
        f"M_max {r.max_moment / kNm:7.1f}   "
        f"V_max {r.max_shear / kN:6.1f}   "
        f"delta {r.max_deflection:6.2f} mm"
    )

# ---------------------------------------------------------------------------
banner("3. Solver checked against the closed-form solution")
# ---------------------------------------------------------------------------
w = 25 * kN_per_m
solved = simply_supported(SPAN, (UDL(magnitude=w),), EI=EI).solve()
exact = ss_udl(w, SPAN, EI)

print(f"{'Quantity':<24}{'Solver':>14}{'Closed form':>14}{'Rel. error':>14}")
print("-" * 66)
for name, got, want in [
    ("Reaction (kN)", solved.reactions[0].force / kN, exact.R_left / kN),
    ("M_max (kN.m)", solved.max_moment / kNm, exact.M_max / kNm),
    ("Deflection (mm)", solved.max_deflection, exact.deflection_max),
]:
    print(f"{name:<24}{got:>14.6f}{want:>14.6f}{abs(got - want) / abs(want):>14.2e}")

# ---------------------------------------------------------------------------
banner("4. An arrangement no formula catalogue covers")
# ---------------------------------------------------------------------------
# Three unequal spans, one end built in, a cantilever overhang, mixed loading.
beam = Beam(
    length=26.0 * m,
    supports=(
        Support(0.0, SupportType.FIXED, "Abutment A"),
        Support(9.0 * m, SupportType.ROLLER, "Pier 1"),
        Support(18.0 * m, SupportType.ROLLER, "Pier 2"),
        Support(24.0 * m, SupportType.ROLLER, "Abutment B"),
        # 2 m overhang beyond the last support
    ),
    loads=(
        UDL(magnitude=20 * kN_per_m),
        PartialUDL(start=9 * m, end=18 * m, magnitude=15 * kN_per_m),
        PointLoad(position=26 * m, magnitude=80 * kN),
        PointLoad(position=4.5 * m, magnitude=120 * kN),
    ),
    EI=EI,
    name="Four-support beam with overhang",
)
r = beam.solve()
print(r.summary())
