"""Reinforced concrete sections -- geometry plus materials plus reinforcement.

An :class:`RCSection` is the object the design layer consumes. It knows its
shape, its materials and where every bar is; it knows nothing about any design
standard. That separation is deliberate -- the same section object is checked
by the AS 3600 and the AS 5100.5 modules without modification.

[UNITS] mm, mm^2, MPa throughout.

Depth convention
----------------
All depths measured DOWNWARD from the extreme compression fibre, matching
``primitives.py`` and matching how ``d`` and ``d_o`` are written in the codes.
For hogging bending, flip the section (see :func:`primitives.inverted_tee`)
rather than negating anything -- the design modules assume compression at top.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..core.exceptions import ModelError
from ..materials.bar_catalogue import bar_area, layer_area
from ..materials.concrete import Concrete
from ..materials.reinforcement import D500N, Reinforcement
from .primitives import SectionGeometry, rectangle, tee


@dataclass(frozen=True)
class RebarLayer:
    """One layer of longitudinal reinforcement at a single depth.

    Parameters
    ----------
    area:
        Total steel area in the layer (mm^2).
    depth:
        Depth to the centroid of the layer, from the extreme compression fibre (mm).
    material:
        Reinforcement grade. Defaults to D500N.
    n_bars, diameter:
        Detailing information. Optional -- a layer can be specified by area
        alone during sizing, and by bars once detailed.
    label:
        Free text, e.g. ``"bottom main"``. Appears in reports.
    """

    area: float
    depth: float
    material: Reinforcement = D500N
    n_bars: int | None = None
    diameter: float | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.area <= 0:
            raise ModelError(f"Rebar layer area must be positive, got {self.area}")
        if self.depth < 0:
            raise ModelError(f"Rebar layer depth must be non-negative, got {self.depth}")

    @classmethod
    def from_bars(
        cls,
        n_bars: int,
        diameter: float,
        depth: float,
        material: Reinforcement = D500N,
        label: str = "",
    ) -> RebarLayer:
        """Build a layer from a bar count and diameter.

        [UNITS] diameter and depth in mm.
        """
        return cls(
            area=layer_area(n_bars, diameter),
            depth=depth,
            material=material,
            n_bars=n_bars,
            diameter=diameter,
            label=label,
        )

    @property
    def designation(self) -> str:
        """Detailing designation, e.g. ``"4-N20"``, or the area if undetailed."""
        if self.n_bars and self.diameter:
            return f"{self.n_bars}-N{self.diameter:.0f}"
        return f"As = {self.area:.0f} mm^2"

    def __str__(self) -> str:
        tag = f" ({self.label})" if self.label else ""
        return f"{self.designation} at d = {self.depth:.0f} mm{tag}"


@dataclass(frozen=True)
class Fitment:
    """Transverse (shear) reinforcement -- ligatures or stirrups.

    Parameters
    ----------
    area:
        A_sv -- total cross-sectional area of ALL legs crossing the shear
        plane at one location (mm^2). For a two-legged N12 ligature this is
        2 * 113 = 226 mm^2. Getting the leg count wrong here halves or doubles
        the shear capacity, so ``from_bars`` is the safer constructor.
    spacing:
        s -- longitudinal spacing along the member (mm).
    material:
        Grade. ``f_sy.f`` in the code expressions is this grade's ``fsy``.
    n_legs, diameter:
        Detailing information.
    angle:
        alpha_v -- inclination of the fitment to the member axis (radians).
        pi/2 (90 degrees) for vertical ligatures, which is the default and the
        only case the current shear modules handle.
    """

    area: float
    spacing: float
    material: Reinforcement = D500N
    n_legs: int | None = None
    diameter: float | None = None
    angle: float = math.pi / 2

    def __post_init__(self) -> None:
        if self.area <= 0:
            raise ModelError(f"Fitment area must be positive, got {self.area}")
        if self.spacing <= 0:
            raise ModelError(f"Fitment spacing must be positive, got {self.spacing}")

    @classmethod
    def from_bars(
        cls,
        diameter: float,
        spacing: float,
        n_legs: int = 2,
        material: Reinforcement = D500N,
        angle: float = math.pi / 2,
    ) -> Fitment:
        """Build a fitment from bar size, spacing and leg count.

        [UNITS] diameter, spacing in mm; angle in radians.

        Examples
        --------
        Two-legged N12 ligatures at 200 mm centres::

            Fitment.from_bars(12, 200)
        """
        return cls(
            area=n_legs * bar_area(diameter),
            spacing=spacing,
            material=material,
            n_legs=n_legs,
            diameter=diameter,
            angle=angle,
        )

    @property
    def asv_per_s(self) -> float:
        """A_sv / s -- the quantity the code expressions actually use (mm^2/mm)."""
        return self.area / self.spacing

    @property
    def designation(self) -> str:
        if self.n_legs and self.diameter:
            return f"N{self.diameter:.0f}-{self.n_legs}leg @ {self.spacing:.0f}"
        return f"Asv = {self.area:.0f} mm^2 @ {self.spacing:.0f}"

    def __str__(self) -> str:
        return self.designation


@dataclass(frozen=True)
class RCSection:
    """A reinforced concrete cross-section.

    Construct via :func:`rc_beam` for the common rectangular beam, or directly
    for anything else.
    """

    geometry: SectionGeometry
    concrete: Concrete
    layers: tuple[RebarLayer, ...] = ()
    fitment: Fitment | None = None
    bw_override: float | None = None
    """b_v -- explicit web width for shear. Defaults to the narrowest band."""

    name: str = ""
    metadata: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for layer in self.layers:
            if layer.depth > self.geometry.D:
                raise ModelError(
                    f"Rebar layer at depth {layer.depth} mm lies below the "
                    f"section soffit at {self.geometry.D} mm"
                )

    # -- geometry passthrough -------------------------------------------------

    @property
    def D(self) -> float:  # noqa: N802
        """Overall depth (mm)."""
        return self.geometry.D

    @property
    def b(self) -> float:
        """Width at the extreme compression fibre (mm)."""
        return self.geometry.b_top

    @property
    def bv(self) -> float:
        """b_v -- effective web width for shear (mm).

        Defaults to the narrowest band in the section, which is correct for a
        plain rectangle and conservative for a tee. Override via
        ``bw_override`` where the section has a local narrowing that is not the
        shear-critical web.

        [ASSUMPTION] No deduction for ducts. AS 3600 and AS 5100.5 both require
                     b_v to be reduced for grouted and ungrouted ducts; that
                     reduction is NOT applied here. Pass ``bw_override``
                     already reduced when ducts are present.
        """
        return self.bw_override if self.bw_override is not None else self.geometry.b_min

    # -- reinforcement --------------------------------------------------------

    @property
    def total_steel_area(self) -> float:
        """Sum of all longitudinal steel areas (mm^2)."""
        return sum(layer.area for layer in self.layers)

    def layers_below(self, depth: float) -> tuple[RebarLayer, ...]:
        """Layers whose centroid lies below ``depth`` -- i.e. in tension when
        ``depth`` is the neutral axis depth."""
        return tuple(layer for layer in self.layers if layer.depth > depth)

    def layers_above(self, depth: float) -> tuple[RebarLayer, ...]:
        """Layers whose centroid lies above ``depth`` -- i.e. in compression
        when ``depth`` is the neutral axis depth."""
        return tuple(layer for layer in self.layers if layer.depth <= depth)

    @property
    def d_o(self) -> float:
        """d_o -- depth to the centroid of the OUTERMOST layer of tensile
        reinforcement (mm).

        This is the depth the ductility limit ``k_uo <= 0.36`` is expressed
        against, and the depth the older shear provisions use. Distinct from
        ``d``, which is the centroid of all tensile reinforcement.

        [BASIS] AS 3600:2018 definitions, Section 1.7.
        """
        if not self.layers:
            raise ModelError("Section has no reinforcement; d_o is undefined")
        return max(layer.depth for layer in self.layers)

    def effective_depth(self, na_depth: float | None = None) -> float:
        """d -- area-weighted centroid of the tensile reinforcement (mm).

        Parameters
        ----------
        na_depth:
            Neutral axis depth. Layers below it are taken as tensile. When
            ``None``, the gross section centroid is used as the divider.

        [ASSUMPTION] With ``na_depth=None`` this classifies layers by the gross
                     centroid, which is a reasonable first estimate but is NOT
                     the neutral axis. The flexure solver re-evaluates ``d``
                     once it has converged on the true neutral axis, so this
                     default only affects preliminary sizing and reporting.
        """
        divider = na_depth if na_depth is not None else self.geometry.centroid
        tensile = self.layers_below(divider)
        if not tensile:
            raise ModelError(
                f"No reinforcement below depth {divider:.1f} mm -- section has "
                "no tensile reinforcement for this neutral axis position"
            )
        total = sum(layer.area for layer in tensile)
        return sum(layer.area * layer.depth for layer in tensile) / total

    @property
    def d(self) -> float:
        """Effective depth using the default layer classification.

        Shorthand for ``effective_depth()``. See its assumptions.
        """
        return self.effective_depth()

    @property
    def Ast(self) -> float:  # noqa: N802
        """A_st -- total tensile reinforcement area by the default split (mm^2)."""
        return sum(layer.area for layer in self.layers_below(self.geometry.centroid))

    @property
    def Asc(self) -> float:  # noqa: N802
        """A_sc -- total compressive reinforcement area by the default split (mm^2)."""
        return sum(layer.area for layer in self.layers_above(self.geometry.centroid))

    # -- modification ---------------------------------------------------------
    #
    # RCSection is frozen, so sizing loops build variants rather than mutating.
    # That keeps a section that has already been reported on from changing
    # underneath the report.

    def with_layers(self, layers: tuple[RebarLayer, ...]) -> RCSection:
        """Copy with different longitudinal reinforcement."""
        return replace(self, layers=layers)

    def with_fitment(self, fitment: Fitment | None) -> RCSection:
        """Copy with different shear reinforcement.

        The workhorse of a shear sizing loop::

            for s in (300, 250, 200, 150):
                trial = section.with_fitment(Fitment.from_bars(12, s))
                if shear_capacity(trial, ...).passed:
                    break
        """
        return replace(self, fitment=fitment)

    def add_layer(self, layer: RebarLayer) -> RCSection:
        """Copy with one more layer of longitudinal reinforcement."""
        return replace(self, layers=self.layers + (layer,))

    # -- reporting ------------------------------------------------------------

    def describe(self) -> list[str]:
        lines = [f"Section    = {self.name or self.geometry.name}"]
        lines.extend(self.geometry.describe()[1:])
        lines.append(f"b_v        = {self.bv:.0f} mm")
        lines.append("")
        lines.append("Concrete:")
        lines.extend(f"  {line}" for line in self.concrete.describe())
        lines.append("")
        lines.append("Longitudinal reinforcement:")
        if self.layers:
            for layer in sorted(self.layers, key=lambda x: x.depth):
                lines.append(f"  {layer}")
        else:
            lines.append("  none")
        lines.append("")
        lines.append(f"Fitments:  {self.fitment or 'none'}")
        return lines


# ---------------------------------------------------------------------------
# Convenience constructors -- the common cases, built the way an engineer
# describes them rather than the way the data model stores them.
# ---------------------------------------------------------------------------


def rc_beam(
    b: float,
    D: float,  # noqa: N803
    concrete: Concrete,
    cover: float = 40.0,
    n_bars: int = 0,
    diameter: float = 0.0,
    fitment_diameter: float = 12.0,
    fitment_spacing: float | None = None,
    fitment_legs: int = 2,
    n_top_bars: int = 0,
    top_diameter: float = 0.0,
    material: Reinforcement = D500N,
    name: str = "",
) -> RCSection:
    """Build a rectangular RC beam the way it is specified on a drawing.

    Bar depths are computed from the cover, the fitment diameter and half the
    main bar diameter, which is the arrangement in the overwhelming majority of
    beams and removes the most common source of arithmetic slips.

    [UNITS] all lengths mm.

    Parameters
    ----------
    b, D:
        Width and overall depth (mm).
    concrete:
        Concrete material.
    cover:
        Clear cover to the FITMENT (mm). Not cover to the main bar.
    n_bars, diameter:
        Bottom (tensile) reinforcement.
    fitment_diameter, fitment_spacing, fitment_legs:
        Ligatures. Pass ``fitment_spacing=None`` for an unreinforced-in-shear
        section; the fitment diameter is still used to locate the main bars.
    n_top_bars, top_diameter:
        Top (compressive) reinforcement. Omit for a singly reinforced section.
    material:
        Reinforcement grade for all layers.

    Returns
    -------
    RCSection

    Examples
    --------
    A 300 x 600 beam, 4-N24 bottom, N12 ligs at 200::

        rc_beam(300, 600, concrete(32), cover=40,
                n_bars=4, diameter=24, fitment_spacing=200)
    """
    geom = rectangle(b, D, name=name)
    layers: list[RebarLayer] = []

    if n_bars and diameter:
        # [ASSUMPTION] Single bottom layer, bars centred on cover + fitment + dia/2.
        depth = D - cover - fitment_diameter - diameter / 2.0
        layers.append(
            RebarLayer.from_bars(n_bars, diameter, depth, material, label="bottom main")
        )

    if n_top_bars and top_diameter:
        depth_top = cover + fitment_diameter + top_diameter / 2.0
        layers.append(
            RebarLayer.from_bars(n_top_bars, top_diameter, depth_top, material, label="top")
        )

    fit = (
        Fitment.from_bars(fitment_diameter, fitment_spacing, fitment_legs, material)
        if fitment_spacing
        else None
    )

    return RCSection(
        geometry=geom,
        concrete=concrete,
        layers=tuple(layers),
        fitment=fit,
        name=name or f"{b:.0f}x{D:.0f} RC beam",
    )


def rc_tee(
    bf: float,
    Df: float,  # noqa: N803
    bw: float,
    D: float,  # noqa: N803
    concrete: Concrete,
    cover: float = 40.0,
    n_bars: int = 0,
    diameter: float = 0.0,
    fitment_diameter: float = 12.0,
    fitment_spacing: float | None = None,
    fitment_legs: int = 2,
    material: Reinforcement = D500N,
    name: str = "",
) -> RCSection:
    """Build a tee-section RC beam with a single bottom reinforcement layer.

    [UNITS] all lengths mm.
    [ASSUMPTION] ``bf`` is the EFFECTIVE flange width. This function does not
                 compute it -- effective width depends on span and support
                 conditions and is the caller's responsibility.
    """
    geom = tee(bf, Df, bw, D, name=name)
    layers: list[RebarLayer] = []
    if n_bars and diameter:
        depth = D - cover - fitment_diameter - diameter / 2.0
        layers.append(
            RebarLayer.from_bars(n_bars, diameter, depth, material, label="bottom main")
        )
    fit = (
        Fitment.from_bars(fitment_diameter, fitment_spacing, fitment_legs, material)
        if fitment_spacing
        else None
    )
    return RCSection(
        geometry=geom,
        concrete=concrete,
        layers=tuple(layers),
        fitment=fit,
        bw_override=bw,
        name=name or f"T-beam {bf:.0f}/{bw:.0f} x {D:.0f}",
    )
