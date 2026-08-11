"""Standard and clause references -- the ``basis`` half of the module contract.

Every number this toolkit produces from a design standard must be traceable to
the clause it came from. A :class:`ClauseRef` is that trace. It is deliberately
a value object with no behaviour beyond formatting: its job is to survive the
trip into a report and, per roadmap Phase 1, to resolve into the TS Reference
Library so a reviewer can jump from a result to the clause behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# [BASIS] Registered standards.
#
# `edition` is the year on the cover. `amendments` lists the amendments the
# implementation has actually been written against -- not the amendments that
# exist. If an amendment is published and the code here has not been reviewed
# against it, it does not go in this list.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Standard:
    """A design standard at a specific edition and amendment state."""

    code: str  # e.g. "AS 3600"
    edition: int  # e.g. 2018
    title: str
    amendments: tuple[str, ...] = ()

    def __str__(self) -> str:
        # Edition 0 marks a non-standard basis such as FIRST_PRINCIPLES, which
        # has no year on a cover to quote.
        base = f"{self.code}:{self.edition}" if self.edition else self.code
        if self.amendments:
            return f"{base} ({', '.join(self.amendments)})"
        return base

    @property
    def slug(self) -> str:
        """Filesystem/URL-safe identifier, e.g. ``as3600-2018``."""
        return f"{self.code.lower().replace(' ', '').replace('.', '_')}-{self.edition}"


# ---------------------------------------------------------------------------
# [BASIS] The three standards in scope for this toolkit.
#
# [TODO] Amendment tuples are empty pending confirmation of which amendments
#        the office works to. Populate them before any module leaves DRAFT --
#        the amendment state is part of the audit trail, not a detail.
# ---------------------------------------------------------------------------

AS3600_2018 = Standard(
    code="AS 3600",
    edition=2018,
    title="Concrete structures",
    amendments=(),
)

AS5100_5_2017 = Standard(
    code="AS 5100.5",
    edition=2017,
    title="Bridge design, Part 5: Concrete",
    amendments=(),
)

AS5100_2_2017 = Standard(
    code="AS 5100.2",
    edition=2017,
    title="Bridge design, Part 2: Design loads",
    amendments=(),
)

AS1170_0_2002 = Standard(
    code="AS/NZS 1170.0",
    edition=2002,
    title="Structural design actions, Part 0: General principles",
    amendments=(),
)

AS4671_2019 = Standard(
    code="AS/NZS 4671",
    edition=2019,
    title="Steel for the reinforcement of concrete",
    amendments=(),
)

# Used where a value comes from mechanics rather than a standard, so that the
# basis field is never empty and never silently implies code backing.
FIRST_PRINCIPLES = Standard(
    code="First principles",
    edition=0,
    title="Engineering mechanics, no code provision invoked",
)


@dataclass(frozen=True)
class ClauseRef:
    """A pointer to a specific provision within a standard.

    Parameters
    ----------
    standard:
        The :class:`Standard` the provision lives in.
    clause:
        Clause number as printed, e.g. ``"8.1.3"``. For a table or figure use
        the ``table``/``figure`` fields instead and leave this empty.
    table, figure, equation:
        Alternatives to ``clause`` for provisions cited by table, figure or
        equation number.
    note:
        Short free text describing what is being taken from the provision.
        This is what appears in the report, so write it for a reviewer.

    Examples
    --------
    >>> ClauseRef(AS3600_2018, "8.1.3", note="Rectangular stress block")
    >>> ClauseRef(AS3600_2018, table="3.1.2", note="Concrete grade properties")
    """

    standard: Standard
    clause: str = ""
    table: str = ""
    figure: str = ""
    equation: str = ""
    note: str = ""

    def __str__(self) -> str:
        parts = [str(self.standard)]
        if self.clause:
            parts.append(f"Cl {self.clause}")
        if self.table:
            parts.append(f"Table {self.table}")
        if self.figure:
            parts.append(f"Figure {self.figure}")
        if self.equation:
            parts.append(f"Eq {self.equation}")
        ref = " ".join(parts)
        return f"{ref} -- {self.note}" if self.note else ref

    @property
    def citation(self) -> str:
        """The reference without the explanatory note, for compact tables."""
        return str(self).split(" -- ")[0]

    @property
    def library_key(self) -> str:
        """Stable key for resolving into the TS Reference Library.

        Roadmap Phase 1 calls for ``basis`` clause references to resolve into
        the reference library so a reviewer can jump from a result to the
        clause. This is the join key for that lookup. Format::

            as3600-2018/cl/8.1.3
            as3600-2018/table/3.1.2

        [TODO] Confirm the key format the reference library actually indexes on
               and adjust here -- one place, not scattered through the modules.
        """
        if self.clause:
            return f"{self.standard.slug}/cl/{self.clause}"
        if self.table:
            return f"{self.standard.slug}/table/{self.table}"
        if self.figure:
            return f"{self.standard.slug}/figure/{self.figure}"
        if self.equation:
            return f"{self.standard.slug}/eq/{self.equation}"
        return self.standard.slug


@dataclass
class Basis:
    """An ordered collection of clause references backing one calculation.

    Order is the order the provisions were applied, which is the order a
    reviewer reads them in.
    """

    refs: list[ClauseRef] = field(default_factory=list)

    def add(self, ref: ClauseRef) -> ClauseRef:
        """Record a clause reference and return it unchanged.

        Returning the ref lets it be captured inline where it is used::

            cref = basis.add(ClauseRef(AS3600_2018, "8.1.3", note="..."))
        """
        self.refs.append(ref)
        return ref

    @property
    def standards(self) -> list[Standard]:
        """Distinct standards invoked, in first-use order."""
        seen: list[Standard] = []
        for r in self.refs:
            if r.standard not in seen:
                seen.append(r.standard)
        return seen

    def __iter__(self):
        return iter(self.refs)

    def __len__(self) -> int:
        return len(self.refs)
