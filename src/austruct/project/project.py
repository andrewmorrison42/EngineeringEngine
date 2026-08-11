"""The project record -- ASET component 2.

Ferster's component 2 is "a combination of client-supplied information -- such
as the site location, desired usage, and assemblies -- and information
generated from client-supplied information, such as climatic data,
environmental loads, dead loads, load combinations (jurisdiction specific)".

The core task he sets is threefold: store and retrieve client-supplied data,
*convert that data into structural parameters*, and design a format that is
both machine read/write-able and convenient for visual review and editing.

This module does all three:

- :class:`Project` holds the record, and round-trips to JSON that a person can
  read and edit.
- :meth:`Project.combination_factors` converts a stated occupancy into the psi
  factors the load combinations need.
- :meth:`Project.load_combinations` returns the right combination set for the
  jurisdiction and structure type.
- :meth:`Project.signature_block` feeds the reporting layer, so the job number
  on a calculation sheet comes from the project record rather than being
  retyped per calculation.

That last point is the whole argument for this component existing. Without it
the job number, the client name and the design life are retyped into every
script, and drift.

[UNITS] Design life in years. Everything else is categorical.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from ..loads.combinations import (
    LoadCombination,
    as1170_sls,
    as1170_uls,
    as5100_sls,
    as5100_uls,
)

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.D_EXTRACTION,
        component=ASETComponent.PROJECT_DATA,
    ),
    description="Project record: job data, site, occupancy, exposure, derived design parameters",
    envelope_summary="Australian jurisdictions; buildings to AS/NZS 1170, bridges to AS 5100",
)


class StructureType(str, Enum):
    """What kind of structure, which decides which suite of standards applies."""

    BUILDING = "building"
    """AS/NZS 1170 actions, AS 3600 concrete."""

    BRIDGE = "bridge"
    """AS 5100.2 actions, AS 5100.5 concrete."""

    OTHER = "other"


class Occupancy(str, Enum):
    """Imposed-action category, per AS/NZS 1170.1.

    Recorded on the project because it is client-supplied information -- "what
    is the building for" -- and it determines the psi combination factors,
    which is the conversion component 2 exists to perform.
    """

    RESIDENTIAL = "residential"
    OFFICE = "office"
    PARKING = "parking"
    RETAIL = "retail"
    STORAGE = "storage"
    ROOF = "roof"
    OTHER = "other"


class ExposureClassification(str, Enum):
    """Exposure classification per AS 3600 Section 4 / AS 5100.5 Section 4.

    Drives cover and minimum grade. The durability module is not built yet, so
    this is currently recorded rather than acted on -- but recording it now
    means the record is already right when that module arrives.
    """

    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"
    U = "U"


# ---------------------------------------------------------------------------
# [BASIS]  AS/NZS 1170.0 Table 4.1 -- combination factors psi.
# [VECTOR] UNVERIFIED. These vary by occupancy and are commonly got wrong by
#          being taken from the wrong row. Check every value against the table
#          before use, and prefer stating them explicitly on the project where
#          the occupancy does not match one of these categories cleanly.
#
# Columns: (psi_c combination, psi_s short-term, psi_l long-term)
# ---------------------------------------------------------------------------
_PSI_FACTORS: dict[Occupancy, tuple[float, float, float]] = {
    Occupancy.RESIDENTIAL: (0.4, 0.7, 0.4),
    Occupancy.OFFICE: (0.4, 0.7, 0.4),
    Occupancy.PARKING: (0.4, 0.7, 0.6),
    Occupancy.RETAIL: (0.6, 0.7, 0.6),
    Occupancy.STORAGE: (0.6, 1.0, 0.8),
    Occupancy.ROOF: (0.0, 0.7, 0.0),
    Occupancy.OTHER: (0.4, 0.7, 0.4),
}


@dataclass
class Project:
    """A job's client-supplied and derived data, in one place.

    Everything is optional so a project can be created early and filled in as
    the information arrives -- which is how projects actually work. What is
    NOT optional is that nothing here is guessed: an unstated design life is
    ``None``, not a default, so a report can say "not stated" rather than
    printing a number nobody chose.

    Examples
    --------
    >>> project = Project(
    ...     job_number="24-1234",
    ...     job_name="Riverside Apartments",
    ...     client="Acme Developments",
    ...     structure_type=StructureType.BUILDING,
    ...     occupancy=Occupancy.RESIDENTIAL,
    ...     exposure=ExposureClassification.B1,
    ...     design_life_years=50,
    ...     engineer="A. Morrison",
    ... )
    >>> project.save("project.json")
    >>> combos = project.load_combinations()
    """

    job_number: str = ""
    job_name: str = ""
    client: str = ""

    # -- site and usage: client-supplied ---------------------------------------
    site_address: str = ""
    jurisdiction: str = ""
    """State or territory, e.g. ``"NSW"``. Relevant to wind/snow region and to
    which road authority supplement applies for bridgeworks."""

    structure_type: StructureType = StructureType.BUILDING
    occupancy: Occupancy = Occupancy.OTHER
    exposure: ExposureClassification | None = None
    design_life_years: int | None = None
    importance_level: int | None = None
    """Importance level 1-4 per the Building Code of Australia. Drives annual
    probability of exceedance for wind and earthquake."""

    # -- people ----------------------------------------------------------------
    engineer: str = ""
    checker: str = ""
    started_on: date | None = None

    # -- explicit overrides ----------------------------------------------------
    psi_c: float | None = None
    psi_s: float | None = None
    psi_l: float | None = None
    """Combination factors. When ``None`` they are derived from the occupancy;
    set them explicitly where the occupancy does not map cleanly, and the
    stated values are used and reported instead."""

    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- derived structural parameters -----------------------------------------

    def combination_factors(self) -> tuple[float, float, float]:
        """``(psi_c, psi_s, psi_l)`` for this project.

        The component-2 conversion: client-supplied occupancy in, structural
        parameters out. Explicit overrides win over the occupancy lookup.

        [VECTOR] UNVERIFIED -- see ``_PSI_FACTORS``.
        """
        default_c, default_s, default_l = _PSI_FACTORS[self.occupancy]
        return (
            self.psi_c if self.psi_c is not None else default_c,
            self.psi_s if self.psi_s is not None else default_s,
            self.psi_l if self.psi_l is not None else default_l,
        )

    def load_combinations(
        self, uls: bool = True, sls: bool = True
    ) -> tuple[LoadCombination, ...]:
        """The combination set this project's jurisdiction and type require.

        A bridge gets the AS 5100.2 set and a building the AS/NZS 1170.0 set.
        Routing on the recorded structure type is the point of the record: a
        bridge silently receiving building combinations is exactly the error
        this is here to prevent.

        [ENVELOPE] The AS 5100.2 set covers gravity and road traffic only --
                   no wind, thermal, shrinkage, earthquake or collision. See
                   :func:`austruct.loads.combinations.as5100_uls`.
        """
        if self.structure_type is StructureType.BRIDGE:
            out: tuple[LoadCombination, ...] = ()
            if uls:
                out += as5100_uls()
            if sls:
                out += as5100_sls()
            return out

        psi_c, psi_s, psi_l = self.combination_factors()
        out: tuple[LoadCombination, ...] = ()
        if uls:
            out += as1170_uls(psi_c=psi_c, psi_l=psi_l)
        if sls:
            out += as1170_sls(psi_s=psi_s, psi_l=psi_l)
        return out

    def signature_block(self, element: str = "", revision: str = ""):
        """A :class:`~austruct.report.template.SignatureBlock` for this project.

        Imported lazily so the project layer does not depend on the reporting
        layer at import -- component 2 should not need component 6 to exist.
        """
        from ..report.template import SignatureBlock

        return SignatureBlock(
            job_number=self.job_number,
            job_name=self.job_name,
            element=element,
            designed_by=self.engineer,
            designed_on=date.today(),
            checked_by=self.checker,
            revision=revision,
        )

    # -- persistence -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form, with the derived parameters included.

        The derived values are written out as well as the inputs, so that the
        stored record shows what was actually used -- a reader should not have
        to rerun the code to find out which psi factors a job was designed to.
        """
        data = asdict(self)
        for key in ("structure_type", "occupancy", "exposure"):
            value = data.get(key)
            if isinstance(value, Enum):
                data[key] = value.value
        if isinstance(data.get("started_on"), date):
            data["started_on"] = data["started_on"].isoformat()

        psi_c, psi_s, psi_l = self.combination_factors()
        data["_derived"] = {
            "psi_c": psi_c,
            "psi_s": psi_s,
            "psi_l": psi_l,
            "psi_source": "explicit" if self.psi_c is not None else f"occupancy:{self.occupancy.value}",
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        """Rebuild from :meth:`to_dict` output. ``_derived`` is ignored on read."""
        data = {k: v for k, v in data.items() if not k.startswith("_")}

        if isinstance(data.get("structure_type"), str):
            data["structure_type"] = StructureType(data["structure_type"])
        if isinstance(data.get("occupancy"), str):
            data["occupancy"] = Occupancy(data["occupancy"])
        if isinstance(data.get("exposure"), str):
            data["exposure"] = ExposureClassification(data["exposure"])
        if isinstance(data.get("started_on"), str):
            data["started_on"] = date.fromisoformat(data["started_on"])

        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            # Preserve rather than discard -- a project file may carry fields a
            # later version of this class added, and dropping them on a
            # read-modify-write cycle would lose data silently.
            data.setdefault("metadata", {})
            for key in unknown:
                data["metadata"][key] = data.pop(key)

        return cls(**data)

    def save(self, path: str | Path) -> None:
        """Write the project record as human-readable JSON."""
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Project:
        """Read a project record written by :meth:`save`."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # -- reporting -------------------------------------------------------------

    def describe(self) -> list[str]:
        psi_c, psi_s, psi_l = self.combination_factors()
        life = f"{self.design_life_years} years" if self.design_life_years else "not stated"
        return [
            f"Job         {self.job_number or 'not stated'}  {self.job_name}",
            f"Client      {self.client or 'not stated'}",
            f"Site        {self.site_address or 'not stated'}  ({self.jurisdiction or '-'})",
            f"Type        {self.structure_type.value}",
            f"Occupancy   {self.occupancy.value}",
            f"Exposure    {self.exposure.value if self.exposure else 'not stated'}",
            f"Design life {life}",
            f"Importance  {self.importance_level if self.importance_level else 'not stated'}",
            f"psi factors psi_c={psi_c:g}  psi_s={psi_s:g}  psi_l={psi_l:g}",
            f"Engineer    {self.engineer or 'not stated'}",
            f"Checker     {self.checker or 'NOT CHECKED'}",
        ]
