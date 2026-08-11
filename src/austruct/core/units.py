"""Unit convention and conversion constants.

THE CONVENTION
--------------
Every number crossing a module boundary in ``austruct`` is a plain ``float`` in
the **N, mm, MPa** system. There is no units library and no runtime dimensional
analysis. The convention is:

    ==================  ============  =======================================
    Quantity            Base unit     Notes
    ==================  ============  =======================================
    Length              mm
    Force               N
    Stress / modulus    MPa           identically N/mm^2
    Moment              N.mm
    Distributed load    N/mm          identically kN/m -- see note below
    Area                mm^2
    Second moment       mm^4
    Angle               radian        degrees only at the user interface
    Density             kg/m^3        the one deliberate exception, see below
    ==================  ============  =======================================

Why not a units library
-----------------------
Dimensional analysis at runtime is genuinely useful, but it costs on three axes
that matter for this toolkit: solver inner-loop performance, clean serialisation
of the calculation contract, and freezing into a compiled ``.exe`` for factory
users. The mitigation is not "be careful" -- it is that every function carries a
``[UNITS]`` callout, every reported quantity is wrapped in a
:class:`austruct.core.contract.Value` that declares its unit as a string, and
the golden vectors in ``tests/golden`` would fail loudly on a factor-of-1000
error.

The kN/m coincidence
--------------------
1 kN/m = 1000 N / 1000 mm = 1 N/mm exactly. A UDL of 25 kN/m is the float
``25.0``. This is a convenience, not a coincidence to rely on silently, so UDL
inputs still declare their unit as ``"N/mm"`` in the contract.

Density
-------
Density stays in kg/m^3 because that is the unit AS 3600 Cl 3.1.2 uses in the
elastic modulus expression, and converting it to the N/mm system produces a
number (2.4e-6) that no engineer will recognise on a printout. It is the single
exception and it is confined to :mod:`austruct.materials.concrete`.

Usage
-----
Multiply to convert *into* base units, divide to convert *out of* them::

    span   = 8.0 * m          # 8000.0  (mm)
    udl    = 25.0 * kN_per_m  # 25.0    (N/mm)
    moment = M / kNm          # N.mm -> kN.m for display
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# [UNITS] Base units. These are 1.0 by definition -- they exist so that calling
#         code can be explicit rather than relying on the reader knowing.
# ---------------------------------------------------------------------------
mm = 1.0
N = 1.0
MPa = 1.0  # identically N/mm^2

# ---------------------------------------------------------------------------
# [UNITS] Length
# ---------------------------------------------------------------------------
m = 1000.0 * mm
cm = 10.0 * mm
km = 1e6 * mm

# ---------------------------------------------------------------------------
# [UNITS] Force
# ---------------------------------------------------------------------------
kN = 1e3 * N
MN = 1e6 * N

# ---------------------------------------------------------------------------
# [UNITS] Stress and modulus
# ---------------------------------------------------------------------------
kPa = 1e-3 * MPa
GPa = 1e3 * MPa

# ---------------------------------------------------------------------------
# [UNITS] Moment
# ---------------------------------------------------------------------------
Nmm = N * mm
kNm = kN * m  # 1e6 N.mm

# ---------------------------------------------------------------------------
# [UNITS] Distributed load along a member.
#         Note kN_per_m == N_per_mm == 1.0 exactly; see module docstring.
# ---------------------------------------------------------------------------
N_per_mm = N / mm
kN_per_m = kN / m

# ---------------------------------------------------------------------------
# [UNITS] Area and second moment of area
# ---------------------------------------------------------------------------
mm2 = mm**2
mm3 = mm**3
mm4 = mm**4
m2 = m**2
m4 = m**4

# ---------------------------------------------------------------------------
# [UNITS] Canonical unit strings, for the `unit` field of contract Values.
#         Using these constants rather than raw literals keeps the strings
#         identical across every module, which is what makes report tables and
#         golden-vector diffs line up.
# ---------------------------------------------------------------------------
U_LENGTH = "mm"
U_FORCE = "N"
U_STRESS = "MPa"
U_MOMENT = "N.mm"
U_UDL = "N/mm"
U_AREA = "mm^2"
U_I = "mm^4"
U_Z = "mm^3"
U_ANGLE = "rad"
U_DENSITY = "kg/m^3"
U_NONE = "-"  # dimensionless: ratios, factors, utilisations


def deg(degrees: float) -> float:
    """Convert degrees to radians.

    [UNITS] Angles are radians internally. Code standards quote shear crack
            angles in degrees (e.g. theta_v = 36 deg), so conversion happens at
            the point the clause value is written down, not deeper.
    """
    return math.radians(degrees)


def to_deg(radians: float) -> float:
    """Convert radians to degrees, for display and reporting only."""
    return math.degrees(radians)
