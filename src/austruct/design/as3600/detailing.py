"""Detailing and anchorage to AS 3600:2018 Section 13 and Cl 8.1.10.

Public entry points
-------------------
:func:`development_length`
    ``L_sy.t`` -- the length needed to develop a bar's yield force in tension.
:func:`compression_development_length`
    ``L_sy.c``.
:func:`lap_length`
    Tension or compression lapped splice length.
:func:`curtailment_extension`
    How far past its theoretical cut-off a bar must run.
:func:`check_bar_fit`
    Whether the bars physically fit and the concrete can get between them.
:func:`check_detailing`
    All of the above applied to one section or one schedule row.

Why this belongs in a package that already computes capacity
------------------------------------------------------------
A flexural capacity is a statement about a section. It is only true if the bars
can actually reach their yield stress at that section, which requires a length
of bar either side to bond into. Anchorage failure is not a reduced capacity --
it is a different, more brittle failure mode, and nothing in the ``M_uo``
calculation can see it coming.

This is also the module that closes the loop with ASET component 4. The
designation grammar in ``design_documentation`` produces the text that reaches
the drawing; :func:`check_detailing` reads that same text back and asks whether
what was drawn can be built and will work. A schedule that parses is not
necessarily a schedule that is buildable.

[UNITS] mm, MPa, N.

[VECTOR] This module is UNVERIFIED. Every constant is in ``constants.py``.
         The k-factors in the development length expression are the ones to
         check first: they multiply together, so two mistaken factors compound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.exceptions import ModelError
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_LENGTH, U_NONE, U_STRESS
from ...sections.bar_layout import layer_layout
from ...sections.rc_section import RCSection
from . import constants as C

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.DESIGN_DOCUMENTATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Development length, laps, curtailment and bar fit to AS 3600:2018 Section 13",
    envelope_summary=(
        "Deformed bars, straight anchorage, no hooks or cogs; "
        "one row of bars per layer; normal-weight concrete"
    ),
)


def _envelope() -> Envelope:
    env = Envelope(name="AS 3600 detailing")
    env.note(
        "Deformed bars only. Plain bars, welded mesh and prestressing tendons "
        "have different anchorage provisions which are not implemented."
    )
    env.note(
        "STRAIGHT anchorage only. No credit is taken for a hook or cog, so a "
        "detail with one is treated conservatively -- the reduction the "
        "standard permits is not applied."
    )
    env.note("Normal-weight concrete. No lightweight-concrete modification.")
    return env


# ---------------------------------------------------------------------------
# The k factors
# ---------------------------------------------------------------------------


def k1_factor(concrete_cast_below: float) -> float:
    """Bond penalty for bars with deep concrete cast beneath them.

    Concrete below a horizontal bar settles and bleeds, leaving a weakened
    layer under the bar. Beyond about 300 mm of depth the effect is enough to
    warrant a 30% penalty on development length.

    Parameters
    ----------
    concrete_cast_below:
        Depth of concrete cast below the bar (mm). For bottom steel this is
        essentially the cover; for top steel in a deep beam it is most of the
        section depth.
    """
    return (
        C.K1_CAST_BELOW_300
        if concrete_cast_below > C.K1_DEPTH_THRESHOLD
        else C.K1_DEFAULT
    )


def k2_factor(bar_diameter: float) -> float:
    """``k2 = (132 - d_b)/100`` -- the bar size effect.

    Larger bars develop proportionally less bond per unit surface area, so the
    factor sits in the denominator and grows the length for big bars.
    """
    return (C.K2_NUMERATOR - bar_diameter) / C.K2_DIVISOR


def k3_factor(cd: float, bar_diameter: float) -> float:
    """``k3 = 1 - 0.15 (c_d - d_b)/d_b``, bounded to [0.7, 1.0].

    Credits generous cover and bar spacing, which delay the splitting failure
    that governs anchorage of a closely spaced group.

    Parameters
    ----------
    cd:
        The governing cover/spacing dimension (mm) -- see :func:`cd_dimension`.
    bar_diameter:
        Bar diameter (mm).
    """
    if bar_diameter <= 0:
        raise ModelError(f"Bar diameter must be positive, got {bar_diameter}")
    raw = C.K3_INTERCEPT - C.K3_SLOPE * (cd - bar_diameter) / bar_diameter
    return max(C.K3_MIN, min(C.K3_MAX, raw))


def cd_dimension(
    cover_to_bar: float,
    clear_spacing: float | None = None,
    side_cover: float | None = None,
) -> float:
    """``c_d`` -- the dimension controlling splitting, per Figure 13.1.2.3(A).

    Which dimension governs depends on how the bar is placed, and this is the
    input most often got wrong. The rule implemented is the conservative
    reading: the SMALLEST of the available cover and half-spacing dimensions,
    because splitting occurs on whichever plane is weakest.

    Parameters
    ----------
    cover_to_bar:
        Cover measured to the surface of the bar itself, not to the fitment.
    clear_spacing:
        Clear distance to the adjacent bar in the same layer (mm). Half of it
        is a candidate for ``c_d``.
    side_cover:
        Cover to the side face where that differs from ``cover_to_bar``.

    [VECTOR] UNVERIFIED -- Figure 13.1.2.3(A) distinguishes several bar
             arrangements and assigns c_d differently to each. Taking the
             minimum is safe but may be more conservative than the figure
             requires for a wide, well-spaced layer.
    """
    candidates = [cover_to_bar]
    if clear_spacing is not None and math.isfinite(clear_spacing):
        candidates.append(clear_spacing / 2.0)
    if side_cover is not None:
        candidates.append(side_cover)
    return min(candidates)


# ---------------------------------------------------------------------------
# Development length
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DevelopmentLength:
    """A development length with the factors that produced it.

    Kept as an object rather than a float because a reviewer checking an
    anchorage detail needs to see which factor drove the answer -- a 1.3 for
    top steel and a 0.7 for generous cover nearly cancel, and the bare length
    hides that.
    """

    length: float
    basic: float
    floor: float
    k1: float
    k2: float
    k3: float
    k4: float
    k5: float
    bar_diameter: float
    governed_by: str

    def describe(self) -> list[str]:
        return [
            f"d_b        = {self.bar_diameter:.0f} mm",
            f"k1         = {self.k1:.3f}",
            f"k2         = {self.k2:.3f}",
            f"k3         = {self.k3:.3f}",
            f"k4         = {self.k4:.3f}",
            f"k5         = {self.k5:.3f}",
            f"L_sy.tb    = {self.basic:.0f} mm  (floor {self.floor:.0f} mm)",
            f"L_sy.t     = {self.length:.0f} mm  -- governed by {self.governed_by}",
        ]


def development_length(
    bar_diameter: float,
    fc: float,
    fsy: float,
    *,
    cd: float | None = None,
    cover_to_bar: float | None = None,
    clear_spacing: float | None = None,
    concrete_cast_below: float = 0.0,
    k4: float = C.K4_NO_TRANSVERSE,
    k5: float = C.K5_NO_PRESSURE,
) -> DevelopmentLength:
    """``L_sy.t`` -- straight development length of a deformed bar in tension.

        L_sy.tb = 0.5 . k1 . k3 . f_sy . d_b / (k2 . sqrt(f'c))
               >= 0.058 . f_sy . k1 . d_b

        L_sy.t  = k4 . k5 . L_sy.tb

    Parameters
    ----------
    bar_diameter:
        ``d_b`` (mm).
    fc:
        Characteristic concrete strength ``f'c`` (MPa).
    fsy:
        Reinforcement yield strength (MPa).
    cd:
        The splitting dimension. Supply directly, or supply ``cover_to_bar``
        and optionally ``clear_spacing`` and let :func:`cd_dimension` derive it.
    cover_to_bar, clear_spacing:
        Used to derive ``cd`` when it is not given.
    concrete_cast_below:
        Depth of concrete cast below the bar (mm), for ``k1``.
    k4, k5:
        Transverse reinforcement and transverse pressure factors. Both default
        to 1.0, taking no credit, which is conservative.

    Returns
    -------
    DevelopmentLength

    [ASSUMPTION] Straight bar, fully stressed to f_sy. Where the bar is
                 stressed to less than yield the standard permits a
                 proportional reduction; that is not applied here.
    """
    if bar_diameter <= 0:
        raise ModelError(f"Bar diameter must be positive, got {bar_diameter}")
    if fc <= 0:
        raise ModelError(f"f'c must be positive, got {fc}")

    if cd is None:
        if cover_to_bar is None:
            raise ModelError(
                "development_length needs either cd, or cover_to_bar to derive "
                "it from. Neither was supplied."
            )
        cd = cd_dimension(cover_to_bar, clear_spacing)

    k1 = k1_factor(concrete_cast_below)
    k2 = k2_factor(bar_diameter)
    k3 = k3_factor(cd, bar_diameter)

    if k2 <= 0:
        raise ModelError(
            f"k2 = (132 - d_b)/100 is {k2:.3f} for d_b = {bar_diameter:.0f} mm. "
            "The expression is not valid for bars this large -- check the bar "
            "size, and check that AS 3600 covers it at all."
        )

    basic = C.LSY_TB_COEFFICIENT * k1 * k3 * fsy * bar_diameter / (k2 * math.sqrt(fc))
    floor = C.LSY_TB_FLOOR_COEFFICIENT * fsy * k1 * bar_diameter

    if floor > basic:
        basic_used, governed = floor, "the 0.058 f_sy k1 d_b floor"
    else:
        basic_used, governed = basic, "the main expression"

    length = k4 * k5 * basic_used
    if length < C.LSY_T_ABSOLUTE_MIN:
        length = C.LSY_T_ABSOLUTE_MIN
        governed = f"the {C.LSY_T_ABSOLUTE_MIN:.0f} mm absolute minimum"

    return DevelopmentLength(
        length=length,
        basic=basic,
        floor=floor,
        k1=k1,
        k2=k2,
        k3=k3,
        k4=k4,
        k5=k5,
        bar_diameter=bar_diameter,
        governed_by=governed,
    )


def compression_development_length(bar_diameter: float, fc: float, fsy: float) -> float:
    """``L_sy.c`` -- development length of a deformed bar in compression (mm).

        L_sy.c = 0.22 . f_sy . d_b / sqrt(f'c)  >=  0.0435 . f_sy . d_b  >= 200

    Shorter than the tension length because end bearing carries part of the
    force and there is no splitting-by-tension mechanism.
    """
    if bar_diameter <= 0 or fc <= 0:
        raise ModelError("Bar diameter and f'c must be positive")
    main = C.LSY_C_COEFFICIENT * fsy * bar_diameter / math.sqrt(fc)
    floor = C.LSY_C_FLOOR_COEFFICIENT * fsy * bar_diameter
    return max(main, floor, C.LSY_C_ABSOLUTE_MIN)


def lap_length(
    bar_diameter: float,
    fc: float,
    fsy: float,
    *,
    tension: bool = True,
    staggered: bool = False,
    generous_steel: bool = False,
    **development_kwargs: float,
) -> float:
    """Lapped splice length (mm).

    Parameters
    ----------
    tension:
        Tension lap when True, compression lap when False.
    staggered, generous_steel:
        Together these decide ``k7``. The reduction to 1.0 requires BOTH that
        the steel provided is at least twice that required AND that no more
        than half the bars are lapped at the section. Passing only one of them
        keeps ``k7 = 1.25``, because the clause makes them joint conditions --
        this is a common and unconservative slip.
    **development_kwargs:
        Passed to :func:`development_length` (``cd``, ``cover_to_bar``,
        ``clear_spacing``, ``concrete_cast_below``, ``k4``, ``k5``).

    Returns
    -------
    float
        Lap length in mm.
    """
    if not tension:
        lsy_c = compression_development_length(bar_diameter, fc, fsy)
        return max(
            C.LAP_COMPRESSION_DB_FACTOR * bar_diameter,
            lsy_c,
            C.LAP_COMPRESSION_ABSOLUTE_MIN,
        )

    lsy_t = development_length(bar_diameter, fc, fsy, **development_kwargs)  # type: ignore[arg-type]
    k7 = C.K7_GENEROUS_STEEL if (staggered and generous_steel) else C.K7_STAGGERED
    return max(k7 * lsy_t.length, C.LAP_TENSION_ABSOLUTE_MIN)


def curtailment_extension(section_depth: float, bar_diameter: float) -> float:
    """How far a bar must extend past its theoretical cut-off point (mm).

        extension >= max(D, 12 d_b)

    Diagonal cracking shifts the tensile force along the member, so the bar is
    still needed some distance past the point where the bending moment says it
    is not. This is the "shift rule" in its AS 3600 form.
    """
    return max(
        C.CURTAIL_EXTENSION_D_FACTOR * section_depth,
        C.CURTAIL_EXTENSION_DB_FACTOR * bar_diameter,
    )


def minimum_clear_spacing(bar_diameter: float, aggregate_size: float = 20.0) -> float:
    """Minimum permitted clear gap between parallel bars (mm).

        >= max(25 mm, d_b, 1.33 x maximum aggregate size)

    The aggregate term is about placing and compacting concrete, not bond --
    which is why it can govern in a member with large aggregate and small bars.
    """
    return max(
        C.MIN_CLEAR_SPACING_ABSOLUTE,
        bar_diameter,
        C.MIN_CLEAR_SPACING_AGGREGATE_FACTOR * aggregate_size,
    )


# ---------------------------------------------------------------------------
# Composite checks
# ---------------------------------------------------------------------------


def check_bar_fit(
    section: RCSection,
    cover: float,
    *,
    fitment_diameter: float | None = None,
    aggregate_size: float = 20.0,
    name: str = "",
) -> CalcResult:
    """Do the bars fit, and can concrete get between them?

    The check every schedule row should pass before it reaches a drawing, and
    the one a capacity calculation cannot make: ``M_uo`` is perfectly happy
    with twelve N32 bars in a 300 mm web that could never be built.

    Parameters
    ----------
    section:
        The RC section. Every layer with a recorded bar count and diameter is
        checked; layers specified by area alone are reported and skipped.
    cover:
        Clear cover to the fitment (mm).
    fitment_diameter:
        Overrides the diameter on the section's fitment.
    aggregate_size:
        Maximum nominal aggregate size (mm).
    """
    result = CalcResult(
        name=name or f"Bar fit -- {section.name or 'section'}",
        provenance=PROVENANCE,
        envelope=_envelope(),
        basis=Basis([C.CLAUSE_BAR_SPACING]),
    )

    fit_dia = fitment_diameter
    if fit_dia is None:
        fit_dia = section.fitment.diameter if section.fitment else 0.0
        if fit_dia is None:
            fit_dia = 0.0

    result.add_input("cover", Value(cover, U_LENGTH, "c", "Clear cover to fitment"))
    result.add_input("aggregate", Value(aggregate_size, U_LENGTH, "d_g", "Max aggregate size"))
    result.add_input("b", Value(section.b, U_LENGTH, "b", "Section width"))

    checked_any = False
    for i, layer in enumerate(sorted(section.layers, key=lambda x: x.depth)):
        tag = layer.label or f"layer {i + 1}"
        if not layer.n_bars or not layer.diameter:
            result.note(
                f"{tag}: specified by area alone, so bar fit cannot be checked. "
                "Detail the layer as a bar count and diameter to have it checked."
            )
            continue

        checked_any = True
        layout = layer_layout(section.b, layer.n_bars, layer.diameter, cover, fit_dia)
        required = minimum_clear_spacing(layer.diameter, aggregate_size)

        result.add_intermediate(
            f"clear_{i}",
            Value(layout.clear_spacing, U_LENGTH, f"a_c[{tag}]", f"Clear gap, {tag}"),
        )
        if layout.n_bars == 1:
            result.note(f"{tag}: a single bar, so there is no gap to check.")
            continue

        result.add_check(
            Check(
                label=f"Clear spacing >= minimum ({tag}, {layer.designation})",
                actual=layout.clear_spacing,
                limit=required,
                operator=">=",
                unit=U_LENGTH,
                basis=C.CLAUSE_BAR_SPACING,
            )
        )
        if not layout.fits:
            result.note(
                f"{tag}: {layer.designation} does NOT physically fit in "
                f"{section.b:.0f} mm at {cover:.0f} mm cover -- the bars "
                f"overlap by {-layout.clear_spacing:.0f} mm. This is a "
                "buildability failure, not a margin."
            )

    if not checked_any:
        result.note(
            "No layer carried both a bar count and a diameter, so nothing was "
            "checked. This result is not evidence that the section is buildable."
        )
    return result


def check_detailing(
    section: RCSection,
    cover: float,
    *,
    available_anchorage: float | None = None,
    aggregate_size: float = 20.0,
    top_steel_cast_below: float | None = None,
    name: str = "",
) -> CalcResult:
    """Bar fit, plus development length against the anchorage actually available.

    Parameters
    ----------
    section:
        The RC section.
    cover:
        Clear cover to the fitment (mm).
    available_anchorage:
        Length of bar available beyond the point of maximum stress (mm) -- for
        example the distance from the face of a support to the end of the bar,
        less the end cover. When supplied, each layer's required development
        length is checked against it. When omitted the lengths are reported but
        NOT checked, because this package cannot know the member's geometry
        beyond its cross-section.
    top_steel_cast_below:
        Depth of concrete cast below the top steel (mm), for ``k1``. Defaults
        to the section depth, which is the correct value for a beam cast in one
        pour and is the conservative choice.

    Returns
    -------
    CalcResult
    """
    result = check_bar_fit(
        section,
        cover,
        aggregate_size=aggregate_size,
        name=name or f"Detailing -- {section.name or 'section'}",
    )
    result.basis = Basis(
        [C.CLAUSE_BAR_SPACING, C.CLAUSE_DEVELOPMENT, C.CLAUSE_DEVELOPMENT_REFINED]
    )

    fit_dia = section.fitment.diameter if section.fitment else 0.0
    if fit_dia is None:
        fit_dia = 0.0
    fc = section.concrete.fc
    cast_below = (
        top_steel_cast_below if top_steel_cast_below is not None else section.geometry.D
    )

    result.add_intermediate("fc", Value(fc, U_STRESS, "f'c", "Concrete strength"))

    for i, layer in enumerate(sorted(section.layers, key=lambda x: x.depth)):
        if not layer.diameter:
            continue
        tag = layer.label or f"layer {i + 1}"
        is_top = layer.depth <= section.geometry.D / 2.0

        layout = (
            layer_layout(section.b, layer.n_bars, layer.diameter, cover, fit_dia)
            if layer.n_bars
            else None
        )
        cover_to_bar = cover + fit_dia
        dev = development_length(
            layer.diameter,
            fc,
            layer.material.fsy,
            cover_to_bar=cover_to_bar,
            clear_spacing=layout.clear_spacing if layout else None,
            concrete_cast_below=cast_below if is_top else cover_to_bar,
        )

        result.add_intermediate(
            f"Lsyt_{i}",
            Value(dev.length, U_LENGTH, f"L_sy.t[{tag}]", f"Development length, {tag}"),
        )
        result.add_intermediate(
            f"k1_{i}", Value(dev.k1, U_NONE, f"k1[{tag}]", "Cast-below factor")
        )

        if available_anchorage is not None:
            result.add_check(
                Check(
                    label=f"Anchorage available >= L_sy.t ({tag}, {layer.designation})",
                    actual=available_anchorage,
                    limit=dev.length,
                    operator=">=",
                    unit=U_LENGTH,
                    basis=C.CLAUSE_DEVELOPMENT,
                )
            )

    if available_anchorage is None:
        result.note(
            "Development lengths are REPORTED but NOT CHECKED -- no available "
            "anchorage length was supplied. This package sees a cross-section, "
            "not the member, so it cannot know how much bar runs past the "
            "point of maximum stress. Supply available_anchorage to have the "
            "check applied."
        )

    result.note(
        "Straight anchorage assumed throughout; no credit taken for hooks or "
        "cogs. Laps are not checked here -- see lap_length()."
    )
    return result
