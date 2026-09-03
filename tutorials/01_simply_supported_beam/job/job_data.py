"""Job data for 25-0142 Northbank Depot -- roof beam B1.

This is YOUR file. Nothing in here calculates a capacity; it records what the
job is and converts the client's information into the numbers the vetted
library wants. That split is ASET component 2 ("project data"), and keeping it
in its own file is what lets `beam_B1.py` be read as a calculation rather than
as a pile of magic numbers.

[UNITS] The library works in N, mm, MPa, so 1 kN/m == 1 N/mm exactly.
        Areal loads below are stated in kPa because that is how a load
        schedule is written, and converted once, here.
"""

from austruct.core.units import kN, kPa, m
from austruct.project import (
    ExposureClassification,
    Occupancy,
    Project,
    StructureType,
)

# ---------------------------------------------------------------------------
# 1. The job record -- client-supplied facts, written down once
# ---------------------------------------------------------------------------
PROJECT = Project(
    job_number="25-0142",
    job_name="Northbank Depot",
    client="Northbank Logistics Pty Ltd",
    site_address="14 Kembla Street, Wollongong NSW",
    jurisdiction="NSW",
    structure_type=StructureType.BUILDING,
    occupancy=Occupancy.OFFICE,
    exposure=ExposureClassification.B1,
    design_life_years=50,
    importance_level=2,
    engineer="A. Morrison",
    checker="",
)

# ---------------------------------------------------------------------------
# 2. Geometry the loads depend on
# ---------------------------------------------------------------------------
SPAN = 7.2 * m
"""Centre-to-centre of the supporting blockwork corbels."""

TRIB_WIDTH = 3.6 * m
"""Half the bay each side of B1 -- one-way slab spanning onto it."""

PLANT_POSITION = 3.0 * m
"""Chainage of the condenser unit's nearer support foot, from grid A."""

# ---------------------------------------------------------------------------
# 3. Areal loads -> line loads on B1
# ---------------------------------------------------------------------------
# [ASSUMPTION] 180 mm one-way slab, 24 kN/m3 reinforced concrete.
G_AREAL = 4.32 * kPa + 0.90 * kPa
"""Permanent action on the roof: 180 slab (4.32 kPa) + membrane, insulation and
services (0.90 kPa). Does NOT include beam self weight -- the library derives
that from the section, see `SelfWeight` in beam_B1.py."""

Q_AREAL = 0.25 * kPa
"""Imposed action, non-trafficable roof, AS/NZS 1170.1 Table 3.2."""

Q_PLANT = 40.0 * kN
"""Rooftop condenser, operating weight, supplier data sheet NB-CD-04 Rev B."""


# ---------------------------------------------------------------------------
# 4. Wind, to AS/NZS 1170.2
# ---------------------------------------------------------------------------
# [VECTOR] Every factor below is transcribed from the standard for THIS site
#          and needs checking against the printed clause before issue.
V_R = 45.0
"""Regional wind speed V_500, Region A4, AS/NZS 1170.2 Table 3.1 (m/s)."""

M_D = 1.00      # wind direction multiplier, Cl 3.3
M_ZCAT = 0.91   # terrain/height multiplier, TC2, z = 9.0 m, Table 4.1
M_S = 1.00      # shielding, Cl 4.3
M_T = 1.00      # topographic, Cl 4.4

C_PE = -0.90    # external pressure coefficient, roof, Table 5.3(A)
C_PI = 0.20     # internal pressure coefficient, Table 5.1(A)
K_A = 1.00      # area reduction, Cl 5.4.2
K_L = 1.00      # local pressure, Cl 5.4.4
C_DYN = 1.00    # dynamic response, Cl 6.1

AIR_DENSITY = 1.2e-6
"""1.2 kg/m3 expressed in the library's N-mm system, so that
0.5 * rho * V^2 comes out in MPa (= N/mm2 = kPa/1000)."""


def design_wind_speed() -> float:
    """V_des,theta to AS/NZS 1170.2 Cl 2.3, in m/s.

    [BASIS] AS/NZS 1170.2 Cl 2.3:  V_sit = V_R * M_d * (M_z,cat M_s M_t)
    """
    return V_R * M_D * (M_ZCAT * M_S * M_T)


def net_uplift_pressure() -> float:
    """Net upward pressure on the roof, in the library's units (MPa).

    [BASIS] AS/NZS 1170.2 Cl 2.4.1:  p = 0.5 rho_air V_des^2 C_fig C_dyn
            with C_fig = C_p,e K_a K_c K_l K_p - C_p,i  (Cl 5.2)

    Returned POSITIVE for uplift; the sign convention is applied at the call
    site in beam_B1.py, where the load direction is visible next to the beam.
    """
    v_des = design_wind_speed()
    c_fig = (C_PE * K_A * K_L) - C_PI          # negative = suction/uplift
    p = 0.5 * AIR_DENSITY * v_des**2 * c_fig * C_DYN
    return abs(p)


# ---------------------------------------------------------------------------
# 5. Derived line loads -- what beam_B1.py actually consumes
# ---------------------------------------------------------------------------
W_G = G_AREAL * TRIB_WIDTH
"""Permanent UDL on B1, N/mm (= kN/m)."""

W_Q = Q_AREAL * TRIB_WIDTH
"""Imposed UDL on B1, N/mm."""

W_WU = net_uplift_pressure() * TRIB_WIDTH
"""Ultimate wind UDL on B1, N/mm, magnitude only (uplift)."""
