"""The steel section catalogue, and the cross-check that polices it.

Nominating a section
--------------------
::

    section = steel_catalogue.get("310UB40.4")
    section.properties.Zx          # computed from the geometry
    section.published.Zx           # as tabulated
    section.grade.fy(section.tf)   # flange yield stress

Same surface as the AS 5100.2 traffic catalogue -- ``get()``, ``names()``,
``catalogue()``, and the same permission guard -- because the failure mode is
the same. A mis-transcribed axle spacing and a mis-transcribed flange thickness
are both invisible downstream, and both produce answers that look entirely
reasonable.

Why this catalogue can do something the others cannot
-----------------------------------------------------
The traffic models hold geometry alone. This file holds geometry **and** the
properties that follow from it, and those two are not independent. So
:func:`verify_catalogue` computes A, Ix, Zx, Sx, Iy and ry from the dimensions
and compares them against the tabulated values.

That is a genuine check with real diagnostic power: a transcription error in
either the dimensions or the properties breaks the agreement, and it would take
an unlucky pair of compensating errors to preserve it.

It is NOT proof. Mutual consistency means the two halves of each row tell the
same story; a section family misremembered consistently would pass. What the
check buys is the elimination of the single most likely error -- a typo -- from
a file with three hundred numbers in it.

Expected disagreement, and why it is not a failure
--------------------------------------------------
The geometry model is three rectangles. A rolled section has root radii where
the flanges meet the web, and they are not modelled, so computed values run
systematically LOW. Roughly:

=========  ==========  ==========================================
Property   Expected    Because
=========  ==========  ==========================================
``A``      1-3% low    Fillet material near the web.
``Ix``     1-3% low    Same material, close to the neutral axis.
``Iy``     <1% low     Fillets sit near the minor axis.
``Sx``     1-3% low    As ``Ix``.
``J``      10-30% low  Torsion is acutely sensitive to the junction.
=========  ==========  ==========================================

The pattern is diagnostic in itself. An ``Ix`` 6% out is a transcription error;
a ``J`` 20% out is the model behaving exactly as documented. That is why the
tolerances differ per property rather than being one number.

[UNITS] mm, mm^2, mm^3, mm^4, mm^6.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..core.exceptions import AustructError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from ..materials import _data
from ..materials.steel import SteelGrade, steel
from .steel_profile import (
    SectionProperties,
    SteelProfile,
    channel,
    i_section,
    plate_section,
)

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.A_TABULATED,
        component=ASETComponent.REFERENCE_DATA,
    ),
    description="Australian hot-rolled steel section catalogue with a self-verifying cross-check",
    envelope_summary="UB, UC and PFC; dimensions recalled, properties cross-checked against them",
)

DATA_FILE = "steel_sections.json"


class UnverifiedSectionData(AustructError):
    """The section catalogue has not been checked against a published table."""


# ---------------------------------------------------------------------------
# The permission guard
# ---------------------------------------------------------------------------

_ALLOW_UNVERIFIED = os.environ.get(
    "AUSTRUCT_ALLOW_UNVERIFIED_SECTIONS", ""
).lower() in {"1", "true", "yes"}


def allow_unverified(enabled: bool | None = None) -> bool:
    """Get or set permission to use the unverified catalogue for this session.

    Called with no argument it reports the current setting; with a boolean it
    sets it and returns the new value.
    """
    global _ALLOW_UNVERIFIED
    if enabled is not None:
        _ALLOW_UNVERIFIED = bool(enabled)
    return _ALLOW_UNVERIFIED


@contextmanager
def unverified_ok() -> Iterator[None]:
    """Scoped permission that cannot leak past the block."""
    global _ALLOW_UNVERIFIED
    previous = _ALLOW_UNVERIFIED
    _ALLOW_UNVERIFIED = True
    try:
        yield
    finally:
        _ALLOW_UNVERIFIED = previous


def _load() -> dict:
    return _data.load(DATA_FILE)


def is_verified() -> bool:
    status, _, _ = _data.verification_status(DATA_FILE)
    return status.upper() == "VERIFIED"


def _guard(designation: str) -> None:
    if is_verified() or _ALLOW_UNVERIFIED:
        return
    raise UnverifiedSectionData(
        f"The dimensions of {designation} in {DATA_FILE} are UNVERIFIED -- they "
        "have been recalled rather than transcribed from a published table. A "
        "wrong flange thickness is invisible in every number downstream.\n\n"
        "For development, call sections.steel_catalogue.allow_unverified(True) "
        "once, or use the unverified_ok() context manager. Then run "
        "verify_catalogue() to see whether the dimensions and the published "
        "properties at least agree with each other."
    )


# ---------------------------------------------------------------------------
# A catalogued section
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishedProperties:
    """The tabulated properties of a section, as a plain record.

    Every field may be ``None`` -- the catalogue records what is known and the
    cross-check skips the rest rather than inventing a comparison.
    """

    A: float | None = None  # noqa: N815
    Ix: float | None = None  # noqa: N815
    Zx: float | None = None  # noqa: N815
    Sx: float | None = None  # noqa: N815
    rx: float | None = None
    Iy: float | None = None  # noqa: N815
    Zy: float | None = None  # noqa: N815
    Sy: float | None = None  # noqa: N815
    ry: float | None = None
    J: float | None = None  # noqa: N815
    Iw: float | None = None  # noqa: N815

    def get(self, name: str) -> float | None:
        return getattr(self, name, None)


@dataclass(frozen=True)
class CatalogueSection:
    """One section from the catalogue: dimensions, geometry and properties.

    Attributes
    ----------
    designation:
        As written on a drawing, e.g. ``"310UB40.4"``.
    kind:
        ``"UB"``, ``"UC"`` or ``"PFC"``.
    d, bf, tf, tw, r:
        Overall depth, flange width, flange and web thickness, root radius.
        The radius is recorded but NOT modelled -- see the module docstring.
    mass:
        Mass per metre (kg/m). A useful independent check on the area: mass and
        area are related by the density, so a section whose mass and area
        disagree has one of them wrong.
    profile:
        The plate assembly.
    published:
        The tabulated properties.
    grade:
        Steel grade. Defaults to 300 for hot-rolled sections.
    """

    designation: str
    kind: str
    d: float
    bf: float  # noqa: N815
    tf: float
    tw: float
    r: float
    mass: float
    profile: SteelProfile
    published: PublishedProperties
    grade: SteelGrade
    confidence: str = ""

    @property
    def properties(self) -> SectionProperties:
        """Properties computed from the geometry."""
        return self.profile.properties()

    @property
    def fy_flange(self) -> float:
        """Yield stress of the flange -- what flexure uses."""
        return self.grade.fy(self.tf)

    @property
    def fy_web(self) -> float:
        """Yield stress of the web -- what shear uses.

        Usually higher than the flange value, because the web is thinner. A
        capacity expression that uses one f_y for both is wrong in a direction
        that depends on which one it picked.
        """
        return self.grade.fy(self.tw)

    @property
    def mass_implied_area(self) -> float:
        """Area implied by the tabulated mass per metre (mm^2).

        An independent check on the published area, using nothing but the mass
        and the density. Two different routes to the same number.
        """
        return self.mass * 1e6 / self.grade.density

    def with_grade(self, grade: str) -> CatalogueSection:
        """Copy using a different steel grade."""
        from dataclasses import replace

        return replace(self, grade=steel(grade))

    def describe(self) -> list[str]:
        p = self.properties
        lines = [
            f"{self.designation}  ({self.kind}, grade {self.grade.name})",
            f"  d = {self.d:.0f}, b_f = {self.bf:.0f}, "
            f"t_f = {self.tf:.1f}, t_w = {self.tw:.1f}, r = {self.r:.1f} mm",
            f"  mass {self.mass:.1f} kg/m",
            f"  f_y flange {self.fy_flange:.0f} MPa, web {self.fy_web:.0f} MPa",
            "",
        ]
        lines.extend("  " + line for line in p.describe())
        if self.confidence:
            lines.append(f"  Confidence: {self.confidence}")
        return lines

    def _repr_markdown_(self) -> str:
        p = self.properties
        rows = [
            "| Property | Computed | Published |",
            "|---|---|---|",
        ]
        for name, fmt in (
            ("A", "{:.0f}"), ("Ix", "{:.4g}"), ("Zx", "{:.4g}"),
            ("Sx", "{:.4g}"), ("Iy", "{:.4g}"), ("ry", "{:.1f}"),
        ):
            pub = self.published.get(name)
            rows.append(
                f"| {name} | {fmt.format(getattr(p, name))} | "
                f"{fmt.format(pub) if pub else '—'} |"
            )
        warn = "" if is_verified() else "\n\n> Section data UNVERIFIED.\n"
        return (
            f"**{self.designation}** — grade {self.grade.name}, "
            f"f_y {self.fy_flange:.0f}/{self.fy_web:.0f} MPa{warn}\n\n"
            + "\n".join(rows)
        )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

_CACHE: dict[tuple[str, str], CatalogueSection] = {}


def _build(entry: dict, grade_name: str) -> CatalogueSection:
    kind = entry["type"]
    d, bf = entry["d"], entry["bf"]
    tf, tw = entry["tf"], entry["tw"]
    designation = entry["designation"]

    if kind in ("UB", "UC"):
        profile = i_section(d, bf, tf, tw, name=designation)
    elif kind == "PFC":
        profile = channel(d, bf, tf, tw, name=designation)
    else:
        raise KeyError(
            f"Section type {kind!r} for {designation} is not one this module "
            "knows how to build. Add a branch rather than letting it fall "
            "through to a wrong shape."
        )

    published = PublishedProperties(**entry.get("published", {}))
    return CatalogueSection(
        designation=designation,
        kind=kind,
        d=d,
        bf=bf,
        tf=tf,
        tw=tw,
        r=entry.get("r", 0.0),
        mass=entry.get("mass", 0.0),
        profile=profile,
        published=published,
        grade=steel(grade_name),
        confidence=entry.get("confidence", ""),
    )


def get(designation: str, grade: str = "300") -> CatalogueSection:
    """Look up a section by its designation.

    Parameters
    ----------
    designation:
        As written on a drawing -- ``"310UB40.4"``. Case-insensitive, and
        whitespace is stripped.
    grade:
        Steel grade. Defaults to 300, the standard grade for hot-rolled
        sections.

    Raises
    ------
    UnverifiedSectionData
        Unless permission has been given for this session.
    KeyError
        For an unknown designation, listing the nearest matches.
    """
    key = designation.strip().upper()
    cache_key = (key, grade)
    if cache_key in _CACHE:
        _guard(key)
        return _CACHE[cache_key]

    data = _load()
    for entry in data["sections"]:
        if entry["designation"].upper() == key:
            _guard(key)
            built = _build(entry, grade)
            _CACHE[cache_key] = built
            return built

    available = [e["designation"] for e in data["sections"]]
    prefix = key[:3]
    near = [a for a in available if a.upper().startswith(prefix)]
    hint = f" Did you mean one of: {', '.join(near)}?" if near else ""
    raise KeyError(
        f"No section {designation!r} in the catalogue. "
        f"{len(available)} sections available.{hint}"
    )


def names(kind: str | None = None) -> tuple[str, ...]:
    """Every designation in the catalogue, optionally filtered by type.

    Needs no permission. Seeing what exists is not using it.
    """
    entries = _load()["sections"]
    if kind is not None:
        entries = [e for e in entries if e["type"].upper() == kind.upper()]
    return tuple(e["designation"] for e in entries)


def catalogue(kind: str | None = None) -> str:
    """The catalogue as a table. Needs no permission."""
    data = _load()
    entries = data["sections"]
    if kind is not None:
        entries = [e for e in entries if e["type"].upper() == kind.upper()]

    lines = [
        f"Steel section catalogue -- {data['source']}",
        f"Status: {data['status']}   "
        f"checked by: {data['checked_by'] or '-'}   on: {data['checked_on'] or '-'}",
        "",
    ]
    if not is_verified():
        lines.append("  *** DIMENSIONS RECALLED, NOT TRANSCRIBED. NOT FOR DESIGN. ***")
        if not _ALLOW_UNVERIFIED:
            lines.append("  *** Permission NOT GIVEN for this session. ***")
        lines.append("")

    lines.append(
        f"  {'designation':<14}{'type':<6}{'d':>6}{'b_f':>6}{'t_f':>7}{'t_w':>7}"
        f"{'mass':>8}{'Z_x 10^3':>11}"
    )
    lines.append("  " + "-" * 65)
    for e in entries:
        zx = e.get("published", {}).get("Zx")
        lines.append(
            f"  {e['designation']:<14}{e['type']:<6}{e['d']:>6.0f}{e['bf']:>6.0f}"
            f"{e['tf']:>7.1f}{e['tw']:>7.1f}{e.get('mass', 0):>8.1f}"
            f"{(zx / 1e3 if zx else 0):>11.0f}"
        )
    lines.append("")
    lines.append("  Run verify_catalogue() to cross-check dimensions against properties.")
    return "\n".join(lines)


def plate(b: float, t: float, grade: str = "250") -> CatalogueSection:
    """A rectangular plate, built rather than looked up.

    Plates are made to order, so there is no catalogue to check against and no
    permission needed -- the geometry is exactly what the caller stated.
    """
    profile = plate_section(b, t)
    return CatalogueSection(
        designation=f"{b:.0f}x{t:.0f} PL",
        kind="plate",
        d=b,
        bf=t,
        tf=t,
        tw=t,
        r=0.0,
        mass=b * t * steel(grade).density / 1e6,
        profile=profile,
        published=PublishedProperties(),
        grade=steel(grade),
        confidence="exact -- built from the stated dimensions",
    )


# ---------------------------------------------------------------------------
# The cross-check
# ---------------------------------------------------------------------------

TOLERANCES: dict[str, float] = {
    "A": 0.05,
    "Ix": 0.05,
    "Zx": 0.05,
    "Sx": 0.05,
    "rx": 0.03,
    "Iy": 0.03,
    "ry": 0.03,
    "J": 0.40,
    "Iw": 0.05,
}
"""Per-property tolerance on |computed - published| / published.

These are NOT accuracy claims. They are the width of the band inside which the
disagreement is explained by the unmodelled root radii, so that anything
outside the band is a transcription error rather than a modelling one.

``J`` gets 40% because torsional stiffness is acutely sensitive to material at
the flange-web junction, which is exactly what is not modelled. ``Iy`` and
``ry`` get 3% because the fillets sit close to the minor axis and barely affect
it -- so a minor-axis disagreement has nowhere to hide.
"""


@dataclass(frozen=True)
class PropertyComparison:
    """One computed-versus-published comparison."""

    designation: str
    prop: str
    computed: float
    published: float
    tolerance: float

    @property
    def error(self) -> float:
        """Signed relative error. Negative means the computed value is low,
        which is what the unmodelled fillets predict."""
        return (self.computed - self.published) / self.published

    @property
    def within(self) -> bool:
        return abs(self.error) <= self.tolerance

    def __str__(self) -> str:
        flag = "" if self.within else "   <-- OUTSIDE TOLERANCE"
        return (
            f"{self.designation:<14}{self.prop:<5}"
            f"{self.computed:>12.5g}{self.published:>12.5g}"
            f"{self.error * 100:>9.2f}%{flag}"
        )


@dataclass(frozen=True)
class MassCheck:
    """A three-way check on the area, which localises where an error is.

    There are three independent routes to a section's area: compute it from the
    dimensions, read it from the published table, or divide the published mass
    per metre by the density. Any two agreeing tells you the third is the odd
    one out -- which turns "these numbers disagree" into "the DIMENSIONS are
    wrong", and that is the difference between a puzzle and a fix.
    """

    designation: str
    from_dimensions: float
    published: float
    from_mass: float

    @property
    def published_vs_mass(self) -> float:
        return abs(self.published - self.from_mass) / self.published

    @property
    def computed_vs_published(self) -> float:
        return abs(self.from_dimensions - self.published) / self.published

    @property
    def verdict(self) -> str:
        """Which of the three sources is the outlier."""
        # Published mass and published area come from the same table and should
        # agree closely -- they are two ways of writing the same fact.
        table_agrees = self.published_vs_mass < 0.02
        geometry_agrees = self.computed_vs_published < 0.05

        if geometry_agrees:
            return "consistent"
        if table_agrees:
            return "DIMENSIONS disagree with the table"
        return "published area and mass disagree with each other"

    @property
    def consistent(self) -> bool:
        return self.verdict == "consistent"

    def implied_note(self) -> str:
        """What the mass implies, for whoever opens the real table."""
        return (
            f"{self.designation}: dimensions give A = {self.from_dimensions:.0f} mm^2, "
            f"but the table's own area ({self.published:.0f}) and mass "
            f"({self.from_mass:.0f}) agree. The recorded d/bf/tf/tw are too "
            f"{'thick' if self.from_dimensions > self.published else 'thin'}."
        )


@dataclass
class CatalogueVerification:
    """The result of cross-checking the whole catalogue."""

    comparisons: list[PropertyComparison]
    skipped: list[str]
    mass_checks: list[MassCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[PropertyComparison]:
        return [c for c in self.comparisons if not c.within]

    @property
    def inconsistent_sections(self) -> list[MassCheck]:
        """Sections whose three routes to the area do not agree."""
        return [m for m in self.mass_checks if not m.consistent]

    @property
    def passed(self) -> bool:
        return not self.failures

    def mean_error(self, prop: str) -> float:
        """Mean signed error for one property, across the catalogue.

        The number to look at when deciding whether a discrepancy is systematic
        or a typo. A mean of -2% on ``A`` across every section is the fillets; a
        single section at -9% is a mistake.
        """
        values = [c.error for c in self.comparisons if c.prop == prop]
        return sum(values) / len(values) if values else 0.0

    def report(self) -> str:
        lines = [
            "Steel catalogue cross-check: computed geometry vs published properties",
            "",
            "This checks that the two halves of each row agree with each other.",
            "It does NOT confirm either against a published table.",
            "",
            f"  {len(self.comparisons)} comparisons over "
            f"{len({c.designation for c in self.comparisons})} sections",
        ]
        if self.skipped:
            lines.append(f"  {len(self.skipped)} property values not tabulated, skipped")
        lines.append("")

        lines.append("  Systematic error by property (negative = computed low):")
        lines.append(f"    {'prop':<6}{'mean':>9}{'tol':>8}   expected cause")
        lines.append("    " + "-" * 56)
        causes = {
            "A": "fillet material at the web",
            "Ix": "as A, close to the neutral axis",
            "Zx": "as Ix",
            "Sx": "as Ix",
            "rx": "ratio -- errors partly cancel",
            "Iy": "fillets barely affect the minor axis",
            "ry": "ratio -- errors partly cancel",
            "J": "acutely sensitive to the junction",
            "Iw": "flange-centroid idealisation",
        }
        for prop in TOLERANCES:
            if not any(c.prop == prop for c in self.comparisons):
                continue
            lines.append(
                f"    {prop:<6}{self.mean_error(prop) * 100:>8.2f}%"
                f"{TOLERANCES[prop] * 100:>7.0f}%   {causes.get(prop, '')}"
            )
        lines.append("")

        if self.inconsistent_sections:
            lines.append("  THREE-WAY AREA CHECK -- which source is wrong:")
            lines.append(
                f"    {'section':<12}{'from dims':>11}{'published':>11}"
                f"{'from mass':>11}   verdict"
            )
            lines.append("    " + "-" * 62)
            for m in self.mass_checks:
                if m.consistent:
                    continue
                lines.append(
                    f"    {m.designation:<12}{m.from_dimensions:>11.0f}"
                    f"{m.published:>11.0f}{m.from_mass:>11.0f}   {m.verdict}"
                )
            lines.append("")

        if self.passed:
            lines.append("  PASS -- every comparison inside its tolerance.")
        else:
            lines.append(f"  {len(self.failures)} COMPARISON(S) OUTSIDE TOLERANCE:")
            lines.append("")
            lines.append(
                f"  {'section':<14}{'prop':<5}{'computed':>12}{'published':>12}{'error':>9}"
            )
            lines.append("  " + "-" * 56)
            lines.extend("  " + str(f) for f in self.failures)
            lines.append("")
            lines.append(
                "  A property outside its band means the dimensions and the "
                "published value\n  disagree. One of them is wrong -- check both "
                "against the source table."
            )
        return "\n".join(lines)

    def _repr_markdown_(self) -> str:
        status = "PASS" if self.passed else f"**{len(self.failures)} FAILURES**"
        return f"**Catalogue cross-check** — {status}\n\n```\n{self.report()}\n```"


def verify_catalogue(kind: str | None = None) -> CatalogueVerification:
    """Compute every section's properties and compare against the tabulated ones.

    Needs no permission: checking the data is not using it, and refusing to run
    the check until the data is verified would be exactly backwards.

    Returns
    -------
    CatalogueVerification
    """
    data = _load()
    entries = data["sections"]
    if kind is not None:
        entries = [e for e in entries if e["type"].upper() == kind.upper()]

    comparisons: list[PropertyComparison] = []
    skipped: list[str] = []
    mass_checks: list[MassCheck] = []

    for entry in entries:
        section = _build(entry, "300")
        computed = section.properties
        published = section.published

        if published.A and section.mass:
            mass_checks.append(
                MassCheck(
                    designation=section.designation,
                    from_dimensions=computed.A,
                    published=published.A,
                    from_mass=section.mass_implied_area,
                )
            )

        for prop, tol in TOLERANCES.items():
            value = published.get(prop)
            if value is None or value == 0:
                skipped.append(f"{entry['designation']}.{prop}")
                continue
            comparisons.append(
                PropertyComparison(
                    designation=entry["designation"],
                    prop=prop,
                    computed=getattr(computed, prop),
                    published=value,
                    tolerance=tol,
                )
            )

    return CatalogueVerification(
        comparisons=comparisons, skipped=skipped, mass_checks=mass_checks
    )
