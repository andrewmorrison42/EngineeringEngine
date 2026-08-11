"""Beam model -- geometry, supports, loads and flexural rigidity.

A :class:`Beam` is a pure description of a structural member. It carries no
results and no code provisions; calling :meth:`Beam.solve` hands it to the
stiffness solver and returns a :class:`~austruct.analysis.results.BeamResults`.

The named constructors at the bottom of this module -- :func:`simply_supported`,
:func:`cantilever`, :func:`propped_cantilever`, :func:`fixed_fixed`,
:func:`continuous` -- cover the cases that come up daily. They build the same
general model as anything else, so a beam that starts as a standard case can be
extended with extra supports or loads without being rebuilt.

[UNITS] Lengths mm, loads N and N/mm, EI in N.mm^2.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum

from ..core.exceptions import ModelError
from ..sections.rc_section import RCSection
from .loading import UDL, Load, SelfWeight
from .results import BeamResults


class SupportType(str, Enum):
    """Restraint provided by a support.

    Only vertical translation and rotation are modelled -- there is no axial
    degree of freedom, so PINNED and ROLLER are identical here. Both are
    provided because the distinction matters to the reader of a report even
    where it does not change the analysis.
    """

    ROLLER = "roller"
    """Vertical translation restrained. Free to rotate."""

    PINNED = "pinned"
    """Vertical translation restrained. Free to rotate. Same as ROLLER in this
    1D model; use it where the real detail is a pin."""

    FIXED = "fixed"
    """Vertical translation AND rotation restrained. Full moment connection."""

    GUIDED = "guided"
    """Rotation restrained, free to translate vertically. Rare, but it is the
    correct model for a symmetry plane through a span."""

    FREE = "free"
    """No restraint. Present so a member end can be named explicitly rather
    than by omission."""


@dataclass(frozen=True)
class Support:
    """A support at a position along the member.

    Parameters
    ----------
    position:
        Distance from the left end of the member (mm).
    type:
        Restraint condition.
    label:
        Free text, e.g. ``"Abutment A"``. Appears in reports.
    """

    position: float
    type: SupportType = SupportType.PINNED
    label: str = ""

    @property
    def restrains_vertical(self) -> bool:
        return self.type in {SupportType.ROLLER, SupportType.PINNED, SupportType.FIXED}

    @property
    def restrains_rotation(self) -> bool:
        return self.type in {SupportType.FIXED, SupportType.GUIDED}

    def __str__(self) -> str:
        tag = f" ({self.label})" if self.label else ""
        return f"{self.type.value} at x = {self.position / 1000:.3f} m{tag}"


@dataclass(frozen=True)
class Beam:
    """A prismatic or stepped beam with arbitrary supports and loads.

    Parameters
    ----------
    length:
        Overall length (mm).
    supports:
        Supports along the member. At least two vertical restraints, or one
        fixed support, are required for stability.
    loads:
        Applied loads. See :mod:`austruct.analysis.loading` for the sign
        convention.
    EI:
        Flexural rigidity (N.mm^2). Either a constant, or a callable
        ``EI(x) -> float`` for a member whose stiffness varies along its length.
    section:
        Optional RC section the beam is made from. When supplied, ``EI`` may be
        omitted and is taken as ``Ec * I_gross``; the section also travels with
        the beam into the design layer so the same object is analysed and
        designed.
    name:
        Member identifier for reports.
    """

    length: float
    supports: tuple[Support, ...] = ()
    loads: tuple[Load, ...] = ()
    EI: float | Callable[[float], float] | None = None
    section: RCSection | None = None
    name: str = ""
    extra_mesh_points: tuple[float, ...] = ()
    """Positions that must carry a mesh node regardless of the load set.

    Needed when several load combinations are enveloped against each other: if
    each combination meshed only around its own loads, the resulting diagrams
    would sit on different x grids and could only be compared by interpolating
    -- which loses exactly the discontinuities an envelope must capture. Giving
    every combination the union of all mesh points makes the envelope
    element-wise and exact. See :mod:`austruct.analysis.envelope`.
    """

    metadata: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ModelError(f"Beam length must be positive, got {self.length}")

        for s in self.supports:
            if not (-1e-9 <= s.position <= self.length + 1e-9):
                raise ModelError(
                    f"Support at x = {s.position} mm lies outside the member "
                    f"(0 to {self.length} mm)"
                )

        if self.EI is None and self.section is None:
            raise ModelError(
                "Beam needs either an EI value or a section to derive one from"
            )

        # [CHECK] Loads that carry their own extent need it filled in from the
        #         member. Doing it here means the user writes UDL(magnitude=...)
        #         and never has to repeat the span.
        fixed_loads = []
        changed = False
        for load in self.loads:
            if isinstance(load, (UDL, SelfWeight)) and load.length == 0.0:
                fixed_loads.append(replace(load, length=self.length))
                changed = True
            else:
                fixed_loads.append(load)
        if changed:
            object.__setattr__(self, "loads", tuple(fixed_loads))

    # -- derived properties ---------------------------------------------------

    def EI_at(self, x: float) -> float:  # noqa: N802
        """Flexural rigidity at position ``x`` (N.mm^2).

        [ASSUMPTION] Where the beam carries a section but no explicit EI, the
                     GROSS second moment of area is used. That is appropriate
                     for determining action effects in a linear elastic
                     analysis, and is NOT appropriate for deflection of a
                     cracked reinforced member -- for that, supply an effective
                     EI explicitly. See sections/properties.py.
        """
        if self.EI is not None:
            return float(self.EI(x)) if callable(self.EI) else float(self.EI)
        assert self.section is not None  # guaranteed by __post_init__
        return self.section.concrete.Ec * self.section.geometry.I_gross

    @property
    def total_load(self) -> float:
        """Total downward force applied to the member (N)."""
        return sum(load.total() for load in self.loads)

    @property
    def support_positions(self) -> tuple[float, ...]:
        return tuple(s.position for s in self.supports)

    @property
    def spans(self) -> tuple[float, ...]:
        """Clear distances between consecutive vertical supports (mm)."""
        verticals = sorted(s.position for s in self.supports if s.restrains_vertical)
        return tuple(b - a for a, b in zip(verticals, verticals[1:]))

    # -- modification ---------------------------------------------------------
    # Beam is frozen, so building variants is the idiom. That matters for load
    # combinations, where the same member is analysed under several load sets
    # and each result must stay associated with the loads that produced it.

    def with_loads(self, loads: tuple[Load, ...]) -> Beam:
        """Copy carrying a different load set."""
        return replace(self, loads=loads)

    def add_load(self, load: Load) -> Beam:
        """Copy with one more load applied."""
        return replace(self, loads=self.loads + (load,))

    def add_support(self, support: Support) -> Beam:
        """Copy with one more support."""
        return replace(self, supports=self.supports + (support,))

    # -- analysis -------------------------------------------------------------

    def solve(self, min_elements: int = 200) -> BeamResults:
        """Analyse the beam.

        Imported lazily so that ``beam.py`` and ``solver.py`` can reference each
        other's types without a circular import at module load.
        """
        from .solver import solve as _solve

        return _solve(self, min_elements=min_elements)

    def describe(self) -> list[str]:
        lines = [
            f"Beam       = {self.name or 'unnamed'}",
            f"Length     = {self.length / 1000:.3f} m",
            f"EI         = {self.EI_at(self.length / 2):.4g} N.mm^2",
            "",
            "Supports:",
        ]
        lines.extend(f"  {s}" for s in self.supports)
        lines.append("")
        lines.append("Loads:")
        if self.loads:
            for load in self.loads:
                tag = f" ({load.label})" if load.label else ""
                lines.append(f"  {type(load).__name__}{tag}: total {load.total() / 1e3:.2f} kN")
        else:
            lines.append("  none")
        return lines


# ---------------------------------------------------------------------------
# Named constructors for the standard support arrangements.
#
# These are conveniences over the general model, not a separate code path --
# which is what lets a "simply supported beam" grow a third support later
# without anything being rewritten.
# ---------------------------------------------------------------------------


def simply_supported(
    length: float,
    loads: tuple[Load, ...] = (),
    EI: float | None = None,  # noqa: N803
    section: RCSection | None = None,
    name: str = "",
) -> Beam:
    """Single span, pinned one end and roller the other.

    [UNITS] length in mm.
    """
    return Beam(
        length=length,
        supports=(
            Support(0.0, SupportType.PINNED, "A"),
            Support(length, SupportType.ROLLER, "B"),
        ),
        loads=loads,
        EI=EI,
        section=section,
        name=name or f"SS beam {length / 1000:.1f} m",
    )


def cantilever(
    length: float,
    loads: tuple[Load, ...] = (),
    EI: float | None = None,  # noqa: N803
    section: RCSection | None = None,
    fixed_at_left: bool = True,
    name: str = "",
) -> Beam:
    """Single span fixed at one end, free at the other.

    Parameters
    ----------
    fixed_at_left:
        True for the root at x = 0 (the usual drawing convention), False for
        the root at the far end.
    """
    root = 0.0 if fixed_at_left else length
    return Beam(
        length=length,
        supports=(Support(root, SupportType.FIXED, "root"),),
        loads=loads,
        EI=EI,
        section=section,
        name=name or f"Cantilever {length / 1000:.1f} m",
    )


def propped_cantilever(
    length: float,
    loads: tuple[Load, ...] = (),
    EI: float | None = None,  # noqa: N803
    section: RCSection | None = None,
    name: str = "",
) -> Beam:
    """Fixed at the left end, propped on a roller at the right.

    Singly statically indeterminate -- the case that shows why a solver beats a
    formula catalogue.
    """
    return Beam(
        length=length,
        supports=(
            Support(0.0, SupportType.FIXED, "A"),
            Support(length, SupportType.ROLLER, "B"),
        ),
        loads=loads,
        EI=EI,
        section=section,
        name=name or f"Propped cantilever {length / 1000:.1f} m",
    )


def fixed_fixed(
    length: float,
    loads: tuple[Load, ...] = (),
    EI: float | None = None,  # noqa: N803
    section: RCSection | None = None,
    name: str = "",
) -> Beam:
    """Encastre -- fully fixed at both ends."""
    return Beam(
        length=length,
        supports=(
            Support(0.0, SupportType.FIXED, "A"),
            Support(length, SupportType.FIXED, "B"),
        ),
        loads=loads,
        EI=EI,
        section=section,
        name=name or f"Fixed-fixed {length / 1000:.1f} m",
    )


def continuous(
    span_lengths: list[float],
    loads: tuple[Load, ...] = (),
    EI: float | None = None,  # noqa: N803
    section: RCSection | None = None,
    end_fixity: tuple[SupportType, SupportType] = (SupportType.PINNED, SupportType.ROLLER),
    name: str = "",
) -> Beam:
    """Multi-span continuous beam over simple internal supports.

    Parameters
    ----------
    span_lengths:
        Individual span lengths (mm). ``[8000, 10000, 8000]`` is a three-span
        beam 26 m long overall.
    end_fixity:
        Restraint at the two ends. Defaults to pinned/roller; pass
        ``(SupportType.FIXED, SupportType.FIXED)`` for a continuous beam built
        into abutments.

    Examples
    --------
    Three equal 8 m spans under a 30 kN/m UDL::

        continuous([8*m, 8*m, 8*m], loads=(UDL(magnitude=30*kN_per_m),), EI=EI)
    """
    if len(span_lengths) < 1:
        raise ModelError("continuous() needs at least one span")

    positions = [0.0]
    for L in span_lengths:
        positions.append(positions[-1] + L)
    total = positions[-1]

    supports = [Support(positions[0], end_fixity[0], "S1")]
    supports.extend(
        Support(p, SupportType.ROLLER, f"S{i + 2}")
        for i, p in enumerate(positions[1:-1])
    )
    supports.append(Support(positions[-1], end_fixity[1], f"S{len(positions)}"))

    return Beam(
        length=total,
        supports=tuple(supports),
        loads=loads,
        EI=EI,
        section=section,
        name=name or f"{len(span_lengths)}-span continuous {total / 1000:.1f} m",
    )
