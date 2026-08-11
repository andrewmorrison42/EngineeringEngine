"""Reinforcing steel properties to AS/NZS 4671, as invoked by AS 3600 Section 3.2.

[UNITS] N, mm, MPa throughout.

[VECTOR] All numeric values UNVERIFIED. Check against AS/NZS 4671 and AS 3600
         Section 3.2 before issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..core.basis import AS3600_2018, AS4671_2019, ClauseRef
from ..core.provenance import ModuleType, Provenance
from ..core.registry import REGISTRY

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.A_TABULATED,
    ),
    description="Reinforcing steel grades and ductility classes to AS/NZS 4671",
    envelope_summary="Grades R250N, D500N, D500L as tabulated",
)


class Ductility(str, Enum):
    """Ductility class per AS/NZS 4671.

    The class is not a label -- it changes the capacity reduction factor and,
    for Class L, restricts where the reinforcement may be used at all. See
    :mod:`austruct.design.as3600.constants`.
    """

    N = "N"
    """Normal ductility. The default for deformed bar."""

    L = "L"
    """Low ductility. Typically mesh. Attracts a lower phi and is restricted
    in application -- AS 3600 Cl 1.1.2 excludes Class L from some uses, and
    AS 5100.5 is more restrictive again for bridgeworks."""

    E = "E"
    """Seismic/earthquake ductility. Not used by any module in this package
    yet; present so the enum does not need widening later."""


@dataclass(frozen=True)
class Reinforcement:
    """A reinforcing steel grade.

    [UNITS] fsy, fsu, Es in MPa; strains dimensionless.
    """

    name: str
    fsy: float
    """f_sy -- characteristic yield strength (MPa)."""

    Es: float
    """E_s -- modulus of elasticity (MPa)."""

    ductility: Ductility
    deformed: bool = True
    fsu: float = 0.0
    """Characteristic tensile strength (MPa). Not used by the flexure or shear
    modules -- present for future strut-and-tie and anchorage work."""

    uniform_elongation: float = 0.0
    """Characteristic uniform elongation. Informational."""

    @property
    def epsilon_sy(self) -> float:
        """Yield strain, f_sy / E_s.

        [BASIS] AS 3600:2018 Cl 3.2.2 -- elastic-plastic idealisation.
        """
        return self.fsy / self.Es

    def stress(self, strain: float) -> float:
        """Steel stress at a given strain, elastic-perfectly-plastic.

        Basis
        -----
        AS 3600:2018 Cl 3.2.2 -- the stress-strain curve may be taken as
        elastic-plastic with no strain hardening.

        [ASSUMPTION] No strain hardening. Conservative for capacity; note that
                     it is NOT conservative for capacity-design force
                     estimation, which this function must not be used for.

        Parameters
        ----------
        strain:
            Signed strain. Tension positive.

        Returns
        -------
        float
            Stress (MPa), signed, magnitude capped at f_sy.
        """
        elastic = strain * self.Es
        return max(-self.fsy, min(self.fsy, elastic))

    def describe(self) -> list[str]:
        return [
            f"Grade      = {self.name}",
            f"f_sy       = {self.fsy:.0f} MPa",
            f"E_s        = {self.Es:.0f} MPa",
            f"Ductility  = Class {self.ductility.value}",
            f"eps_sy     = {self.epsilon_sy:.5f}",
        ]


# ---------------------------------------------------------------------------
# [BASIS]  AS/NZS 4671 -- standard reinforcement grades.
# [BASIS]  AS 3600:2018 Cl 3.2.2 -- Es = 200 000 MPa for reinforcement.
# [VECTOR] UNVERIFIED. fsu and uniform elongation in particular are recorded
#          from the grade designation and need checking.
# ---------------------------------------------------------------------------

ES_DEFAULT = 200_000.0

D500N = Reinforcement(
    name="D500N",
    fsy=500.0,
    Es=ES_DEFAULT,
    ductility=Ductility.N,
    deformed=True,
    fsu=540.0,
    uniform_elongation=0.05,
)
"""Grade 500 MPa normal-ductility deformed bar. The default for everything."""

D500L = Reinforcement(
    name="D500L",
    fsy=500.0,
    Es=ES_DEFAULT,
    ductility=Ductility.L,
    deformed=True,
    fsu=515.0,
    uniform_elongation=0.015,
)
"""Grade 500 MPa low-ductility -- welded wire mesh. Restricted application."""

R250N = Reinforcement(
    name="R250N",
    fsy=250.0,
    Es=ES_DEFAULT,
    ductility=Ductility.N,
    deformed=False,
    fsu=320.0,
    uniform_elongation=0.05,
)
"""Grade 250 MPa plain round bar. Fitments and dowels."""

GRADES: dict[str, Reinforcement] = {g.name: g for g in (D500N, D500L, R250N)}

# The overwhelmingly common case, named so calling code reads clearly.
DEFAULT_MAIN_BAR = D500N
DEFAULT_FITMENT = D500N

CLAUSE_ES = ClauseRef(AS3600_2018, "3.2.2", note="Modulus of elasticity of reinforcement")
CLAUSE_GRADES = ClauseRef(AS4671_2019, note="Reinforcement grades and ductility classes")


def reinforcement(name: str = "D500N") -> Reinforcement:
    """Look up a standard reinforcement grade by designation.

    Parameters
    ----------
    name:
        Grade designation, e.g. ``"D500N"``. Case-insensitive.

    Raises
    ------
    KeyError
        If the grade is not tabulated -- deliberately, rather than defaulting,
        because a silently substituted grade is a silently wrong capacity.
    """
    key = name.upper().strip()
    if key not in GRADES:
        raise KeyError(f"Unknown reinforcement grade {name!r}. Known grades: {sorted(GRADES)}")
    return GRADES[key]
