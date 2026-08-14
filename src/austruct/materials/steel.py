"""Structural steel grades -- ASET component 1, reference data.

The thing this module exists to stop
------------------------------------
Steel's yield stress depends on how thick the material is, not just on its
grade. A Grade 300 universal beam has a different ``f_y`` in its flange than in
its web because they are different thicknesses, and AS 4100 uses the flange
value for flexure and the web value for shear.

So there is deliberately **no** ``grade.fy`` on this module. Every strength
lookup takes a thickness, and asking for one without a thickness is a type
error rather than a silent average. That is a small inconvenience once and the
alternative is a whole-section capacity computed against a strength that
applies to part of it.

[UNITS] MPa, mm, kg/m^3.

[VECTOR] Every value is UNVERIFIED and lives in ``data/steel_grades.json``.
         The band BOUNDARIES are the least reliable part -- a boundary in the
         wrong place changes ``f_y`` by a whole step for sections near it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.basis import ClauseRef, Standard
from ..core.exceptions import ModelError
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
    description="Structural steel grades with thickness-banded yield strength",
    envelope_summary="Hot-rolled sections and plate to AS/NZS 3679.1 and AS/NZS 3678",
)

AS4100 = Standard(
    code="AS 4100",
    edition=2020,
    title="Steel structures",
)
"""[VECTOR] UNVERIFIED -- confirm the current edition year before citing it."""

DATA_FILE = "steel_grades.json"


def _load() -> dict:
    return _data.load(DATA_FILE)


def is_verified() -> bool:
    status, _, _ = _data.verification_status(DATA_FILE)
    return status.upper() == "VERIFIED"


@dataclass(frozen=True)
class SteelGrade:
    """A structural steel grade.

    Attributes
    ----------
    name:
        Grade designation, e.g. ``"300"`` for hot-rolled section.
    product:
        What the grade is supplied as -- ``"hot-rolled section"`` or
        ``"plate"``. The same nominal number means different strengths for
        different products, which is why plate grades are named separately.
    standard:
        The product standard the strengths come from.
    bands:
        ``((max_thickness, fy, fu), ...)`` ascending.
    E, G, poisson, density:
        Elastic properties, common to every grade.
    """

    name: str
    product: str
    standard: str
    bands: tuple[tuple[float, float, float], ...]
    E: float = 200000.0  # noqa: N815
    G: float = 80000.0  # noqa: N815
    poisson: float = 0.25
    density: float = 7850.0
    description: str = ""
    confidence: str = ""

    # -- strength lookups -----------------------------------------------------

    def fy(self, thickness: float) -> float:
        """Yield stress for material of this thickness (MPa).

        Raises
        ------
        ModelError
            If the thickness is beyond the largest band. The grade is not made
            that thick, and extrapolating the last band would invent a strength
            for a product that does not exist.
        """
        return self._band(thickness)[1]

    def fu(self, thickness: float) -> float:
        """Tensile strength for material of this thickness (MPa)."""
        return self._band(thickness)[2]

    def _band(self, thickness: float) -> tuple[float, float, float]:
        if thickness <= 0:
            raise ModelError(f"Thickness must be positive, got {thickness}")
        for band in self.bands:
            if thickness <= band[0]:
                return band
        raise ModelError(
            f"Grade {self.name} is tabulated only up to {self.bands[-1][0]:.0f} mm "
            f"and {thickness:.1f} mm was asked for. Extrapolating the last band "
            "would invent a strength for a product that is not made."
        )

    @property
    def fy_range(self) -> tuple[float, float]:
        """``(lowest, highest)`` yield stress across the grade's bands."""
        values = [b[1] for b in self.bands]
        return min(values), max(values)

    @property
    def is_placeholder(self) -> bool:
        return "PLACEHOLDER" in self.confidence.upper()

    # -- reporting ------------------------------------------------------------

    def describe(self) -> list[str]:
        lines = [
            f"Grade {self.name}  ({self.product}, {self.standard})",
            f"  {self.description}" if self.description else "",
            f"  E = {self.E:.0f} MPa, G = {self.G:.0f} MPa, "
            f"density {self.density:.0f} kg/m^3",
            "  Thickness bands:",
        ]
        lower = 0.0
        for upper, fy, fu in self.bands:
            lines.append(
                f"    {lower:>5.0f} < t <= {upper:>5.0f} mm : "
                f"f_y = {fy:.0f} MPa, f_u = {fu:.0f} MPa"
            )
            lower = upper
        if self.confidence:
            lines.append(f"  Confidence: {self.confidence}")
        return [line for line in lines if line]

    def _repr_markdown_(self) -> str:
        rows = ["| Thickness | f_y | f_u |", "|---|---|---|"]
        lower = 0.0
        for upper, fy, fu in self.bands:
            rows.append(f"| {lower:.0f} < t ≤ {upper:.0f} mm | {fy:.0f} | {fu:.0f} |")
            lower = upper
        warn = "" if is_verified() else "\n\n> Grade data UNVERIFIED.\n"
        return (
            f"**Grade {self.name}** — {self.product}, {self.standard}{warn}\n\n"
            + "\n".join(rows)
        )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

_CACHE: dict[str, SteelGrade] = {}


def steel(grade: str = "300") -> SteelGrade:
    """Look up a steel grade by name.

    Parameters
    ----------
    grade:
        ``"300"`` or ``"350"`` for hot-rolled section, ``"250"``, ``"350P"`` or
        ``"400P"`` for plate. The plate grades carry a ``P`` because a plate
        Grade 350 and a section Grade 350 are different materials with
        different strengths, and letting them share a name would let one be
        used where the other was meant.

    Returns
    -------
    SteelGrade

    Raises
    ------
    KeyError
        For an unknown grade, listing what is available.
    """
    key = str(grade).strip().upper()
    if key in _CACHE:
        return _CACHE[key]

    data = _load()
    grades = data["grades"]
    if key not in grades:
        raise KeyError(
            f"Unknown steel grade {grade!r}. Available: {', '.join(sorted(grades))}"
        )

    entry = grades[key]
    elastic = data["elastic"]
    built = SteelGrade(
        name=key,
        product=entry["product"],
        standard=entry["standard"],
        bands=tuple(tuple(b) for b in entry["bands"]),  # type: ignore[arg-type]
        E=elastic["E"],
        G=elastic["G"],
        poisson=elastic["poisson"],
        density=elastic["density"],
        description=entry.get("description", ""),
        confidence=entry.get("confidence", ""),
    )
    _CACHE[key] = built
    return built


def grade_names(product: str | None = None) -> tuple[str, ...]:
    """Available grade names, optionally filtered by product."""
    grades = _load()["grades"]
    if product is None:
        return tuple(sorted(grades))
    return tuple(
        sorted(k for k, v in grades.items() if v["product"] == product)
    )


def describe_grades() -> str:
    """Every grade and its bands, as a table."""
    data = _load()
    lines = [
        f"Structural steel grades -- {data['source']}",
        f"Status: {data['status']}",
        "",
        f"  {'grade':<8}{'product':<20}{'f_y range':>14}  confidence",
        "  " + "-" * 62,
    ]
    for name in sorted(data["grades"]):
        g = steel(name)
        lo, hi = g.fy_range
        span = f"{lo:.0f}" if lo == hi else f"{lo:.0f}-{hi:.0f}"
        lines.append(
            f"  {name:<8}{g.product:<20}{span + ' MPa':>14}  {g.confidence}"
        )
    if not is_verified():
        lines.extend(
            ["", "  *** THICKNESS BANDS NOT CONFIRMED AGAINST THE STANDARD. ***"]
        )
    return "\n".join(lines)


CLAUSE_MATERIAL = ClauseRef(AS4100, "2.1", note="Material properties")
