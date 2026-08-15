"""Masonry unit and masonry material properties to AS 3700:2018 Section 3.

Mirrors :mod:`austruct.materials.concrete`'s shape: a small tabulated
reference-data layer (:class:`MasonryUnit`, loaded from
``data/masonry_units.json``) and a derived-properties factory
(:func:`masonry_properties`) that turns a unit strength and a mortar class
into the strengths the design layer actually consumes.

[UNITS] N, mm, MPa throughout.

[VECTOR] Every numeric value and every derivation in this module is a
         SIMPLIFICATION of AS 3700:2018 Section 3, not a transcription of the
         full tables (which vary by unit height, hollow/solid construction,
         and more detail than is reproduced here). Confirm f'm, f'mt and f'ms
         against the printed standard -- or, better, against a test report --
         before using them for an issued design. See ``design/as3700/constants.py``
         for the numeric coefficients this module's derivations use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from ..core.basis import AS3700_2018, ClauseRef
from ..core.envelope import Envelope
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from . import _data

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.A_TABULATED,
        component=ASETComponent.REFERENCE_DATA,
    ),
    description="Masonry unit sizes and derived masonry strengths to AS 3700:2018 Section 3",
    envelope_summary="Simplified derivation, not the full Table 3.1 -- see module docstring",
)


class MortarClass(str, Enum):
    """Mortar class per AS 3700:2018 Table 11.1.

    M4 is the strongest (cement-rich) mix, M1 the weakest. Only M2-M4 are
    normally used in structural masonry; M1 exists mainly for heritage
    repointing work.
    """

    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"


# ---------------------------------------------------------------------------
# [VECTOR] Mortar class strength multiplier -- a SIMPLIFIED stand-in for the
# mortar-class dependence AS 3700 Table 3.1 builds into f'm directly. Applied
# to the f'm derivation below. UNVERIFIED; the real table's dependence on
# mortar class is not a flat multiplier on a sqrt(f'uc) formula.
# ---------------------------------------------------------------------------
MORTAR_STRENGTH_FACTOR: dict[MortarClass, float] = {
    MortarClass.M4: 1.0,
    MortarClass.M3: 0.9,
    MortarClass.M2: 0.8,
    MortarClass.M1: 0.7,
}


@dataclass(frozen=True)
class MasonryUnit:
    """One catalogue entry from ``data/masonry_units.json``.

    [UNITS] f_uc MPa, work_size (length, height, thickness) mm.
    """

    name: str
    description: str
    category: str
    f_uc: float
    work_size: tuple[float, float, float]

    @property
    def thickness(self) -> float:
        """Work-size thickness, mm -- what governs wall thickness."""
        return self.work_size[2]


def unit_names() -> tuple[str, ...]:
    """Every masonry unit name in the catalogue."""
    return tuple(row["name"] for row in _data.load("masonry_units.json")["masonry_units"])


def get_unit(name: str) -> MasonryUnit:
    """Look up one masonry unit by name.

    Raises
    ------
    KeyError
        If ``name`` is not in :func:`unit_names`.
    """
    for row in _data.load("masonry_units.json")["masonry_units"]:
        if row["name"] == name:
            return MasonryUnit(
                name=row["name"],
                description=row["description"],
                category=row["category"],
                f_uc=float(row["f_uc"]),
                work_size=tuple(row["work_size"]),
            )
    raise KeyError(f"Unknown masonry unit {name!r}. Known: {', '.join(unit_names())}")


def unit_catalogue() -> str:
    """Formatted table of every masonry unit -- listing needs no permission."""
    lines = [f"{'Name':<20}{'Category':<18}{'f_uc':>7}{'Thickness':>11}"]
    lines.append("-" * 56)
    for name in unit_names():
        u = get_unit(name)
        lines.append(f"{u.name:<20}{u.category:<18}{u.f_uc:>7.1f}{u.thickness:>11.0f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Derived masonry properties
# ---------------------------------------------------------------------------

CLAUSE_FM = ClauseRef(AS3700_2018, "3.3.2", note="Characteristic compressive strength of masonry")
CLAUSE_FMT = ClauseRef(AS3700_2018, "3.3.4", note="Characteristic flexural tensile strength")
CLAUSE_FMS = ClauseRef(AS3700_2018, "3.3.3", note="Characteristic shear strength")

FMT_UNGROUTED = 0.20
FMT_GROUTED = 0.40
"""Default characteristic flexural tensile strength (tension perpendicular to
bed joints), MPa, used where not established by test. [VECTOR] UNVERIFIED
placeholder -- AS 3700 Table 3.3 gives values depending on unit category and
mortar class in more detail than this flat pair."""

KP_PARALLEL = 2.0
"""f'mt,parallel = KP_PARALLEL . f'mt -- the enhancement for bending with
tension PARALLEL to the bed joints (horizontal bending), over the
perpendicular value. [VECTOR] UNVERIFIED SIMPLIFICATION: AS 3700's real
treatment of horizontal bending is panel/aspect-ratio dependent (Cl 7.4.3),
not a flat multiplier -- see ``design/as3700/flexure.py``."""

FMS_UNGROUTED = 0.15
FMS_GROUTED = 0.25
"""Default characteristic shear bond strength, MPa. [VECTOR] UNVERIFIED
placeholder for AS 3700 Table 3.3's shear strength values."""


@dataclass(frozen=True)
class MasonryGrade:
    """Derived masonry strengths for a given unit strength, mortar class and
    grouting state. Construct via :func:`masonry_properties`.

    [UNITS] All stresses MPa.
    """

    f_uc: float
    mortar_class: MortarClass
    grouted: bool
    f_m: float
    f_mt: float
    f_ms: float
    envelope: Envelope = field(default_factory=Envelope, repr=False)

    @property
    def f_mt_parallel(self) -> float:
        """f'mt for bending with tension parallel to the bed joints
        (horizontal bending) -- see :data:`KP_PARALLEL`."""
        return KP_PARALLEL * self.f_mt

    def describe(self) -> list[str]:
        return [
            f"f'uc          = {self.f_uc:.1f} MPa",
            f"mortar class  = {self.mortar_class.value}",
            f"grouted       = {self.grouted}",
            f"f'm           = {self.f_m:.2f} MPa",
            f"f'mt (perp)   = {self.f_mt:.2f} MPa",
            f"f'mt (par)    = {self.f_mt_parallel:.2f} MPa",
            f"f'ms          = {self.f_ms:.2f} MPa",
        ]


def masonry_properties(
    f_uc: float,
    mortar_class: MortarClass = MortarClass.M3,
    grouted: bool = False,
) -> MasonryGrade:
    """Derive masonry strengths from unit strength, mortar class and grouting.

    Basis
    -----
    AS 3700:2018 Section 3, SIMPLIFIED -- see the module docstring and the
    [VECTOR] notes on each constant used here.

    ``f'm = 1.4 . sqrt(f'uc) . mortar_factor(mortar_class)``

    Parameters
    ----------
    f_uc:
        Characteristic unconfined compressive strength of the unit (MPa).
    mortar_class:
        AS 3700 mortar class M1-M4.
    grouted:
        Whether cores are filled with grout -- raises the default f'mt/f'ms
        (:data:`FMT_GROUTED`/:data:`FMS_GROUTED` vs the ungrouted defaults).
        Has NO effect on f'm in this simplified derivation; AS 3700's actual
        treatment of grouted compressive strength is more involved.

    Returns
    -------
    MasonryGrade
    """
    env = Envelope(name="Masonry properties")
    env.add("f'uc", f_uc, lower=5.0, upper=50.0, unit="MPa", basis=CLAUSE_FM)
    env.require()

    f_m = 1.4 * math.sqrt(f_uc) * MORTAR_STRENGTH_FACTOR[mortar_class]
    f_mt = FMT_GROUTED if grouted else FMT_UNGROUTED
    f_ms = FMS_GROUTED if grouted else FMS_UNGROUTED

    return MasonryGrade(
        f_uc=f_uc, mortar_class=mortar_class, grouted=grouted,
        f_m=f_m, f_mt=f_mt, f_ms=f_ms, envelope=env,
    )
