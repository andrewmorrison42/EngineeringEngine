"""The design designation grammar -- ASET component 4.

Why this module exists
----------------------
Ferster's fourth component is about describing a *design decision* in plain
text, because plain text is both human- and machine-readable. His example is a
coupling beam schedule where every cell follows one strict pattern::

    900 x 550 DP r/w 8-25M e/w

which a technician can read and draft from, and a program can parse into
``{'length': 900, 'depth': 550, 'num_bars': 8, 'bar_area': 1000}``.

That is the artifact that actually reaches the drawing. Everything else in this
toolkit produces numbers; this produces the thing a drafter works from and a
checking engineer reads -- and it does so without the design being written down
twice, once for people and once for the computer.

The grammar
-----------
Pipe-separated fields. The first field is always the dimensions; the rest are
keyword-led and order-independent. Case-insensitive::

    350 x 650 | C40 | COV 40 | BOT 4-N28 | TOP 2-N16 | LIG N12-2L@200

    ==================  ====================================================
    ``<b> x <D>``       Width x overall depth, mm. REQUIRED, must be first.
    ``C<f'c>``          Concrete grade, MPa. REQUIRED.
    ``T <bf>/<Df>``     Tee section: flange width / flange thickness, mm.
                        When present, ``<b>`` is read as the WEB width.
    ``COV <c>``         Cover to the fitment, mm. Default 40.
    ``BOT <n>-N<dia>``  Bottom (tensile) reinforcement.
    ``TOP <n>-N<dia>``  Top (compressive) reinforcement.
    ``LIG N<dia>-<k>L@<s>``  Fitments: bar size, legs, spacing in mm.
    ==================  ====================================================

Design rules for the grammar itself, worth stating because they are what make
it survive contact with a real schedule:

1. **Every field is self-identifying.** No positional fields after the
   dimensions, so a cell missing its top steel cannot be misread as one missing
   its ligatures.
2. **It round-trips.** ``parse(designate(section))`` reproduces the section.
   A format that can be written but not read back is a dead end.
3. **It fails loudly.** An unrecognised field raises with the offending text
   quoted, rather than being silently ignored -- silently dropping ``TOP 2-N16``
   would produce a singly reinforced capacity for a doubly reinforced beam.

[UNITS] All dimensions mm, grades MPa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.exceptions import AustructError
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from ..materials.concrete import Concrete, concrete
from ..materials.reinforcement import D500N, Reinforcement
from ..sections.rc_section import RCSection, RebarLayer, rc_beam, rc_tee

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.D_EXTRACTION,
        component=ASETComponent.DESIGN_DOCUMENTATION,
    ),
    description="Plain-text design designation grammar for RC beams, with round-trip parsing",
    envelope_summary="Rectangular and tee RC beams; one top and one bottom bar layer",
)


class DesignationError(AustructError):
    """A designation string could not be parsed.

    Carries the offending text so the error points at the cell, which matters
    when the failure is one row of a two-hundred-row schedule.
    """

    def __init__(self, message: str, designation: str = "", field: str = ""):
        super().__init__(message)
        self.designation = designation
        self.field = field


# ---------------------------------------------------------------------------
# Field patterns. Each is anchored and case-insensitive.
# ---------------------------------------------------------------------------

_DIMENSIONS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*$")
_GRADE = re.compile(r"^\s*C\s*(\d+(?:\.\d+)?)\s*$", re.IGNORECASE)
_TEE = re.compile(r"^\s*T\s+(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$", re.IGNORECASE)
_COVER = re.compile(r"^\s*COV\s*(\d+(?:\.\d+)?)\s*$", re.IGNORECASE)
_BARS = re.compile(r"^\s*(BOT|TOP)\s+(\d+)\s*-\s*N\s*(\d+(?:\.\d+)?)\s*$", re.IGNORECASE)
_LIGS = re.compile(
    r"^\s*LIG\s+N\s*(\d+(?:\.\d+)?)\s*-\s*(\d+)\s*L\s*@\s*(\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)

DEFAULT_COVER = 40.0
DEFAULT_FITMENT_DIAMETER = 12.0


@dataclass(frozen=True)
class ParsedDesignation:
    """The fields recovered from a designation string, before a section is built.

    Exposed separately from :func:`parse` so a schedule can be validated,
    diffed or reported on without materialising materials and geometry -- which
    matters when checking a schedule of two hundred members.
    """

    width: float
    depth: float
    grade: float
    cover: float = DEFAULT_COVER
    flange_width: float | None = None
    flange_depth: float | None = None
    n_bottom: int = 0
    dia_bottom: float = 0.0
    n_top: int = 0
    dia_top: float = 0.0
    fitment_diameter: float = 0.0
    fitment_legs: int = 0
    fitment_spacing: float = 0.0

    @property
    def is_tee(self) -> bool:
        return self.flange_width is not None and self.flange_depth is not None

    @property
    def has_fitments(self) -> bool:
        return self.fitment_spacing > 0.0


def parse_fields(designation: str) -> ParsedDesignation:
    """Parse a designation string into its fields, without building a section.

    Parameters
    ----------
    designation:
        e.g. ``"350 x 650 | C40 | COV 40 | BOT 4-N28 | LIG N12-2L@200"``

    Raises
    ------
    DesignationError
        On a missing or unrecognised field. The message quotes the offending
        text and the whole designation.
    """
    if not designation or not designation.strip():
        raise DesignationError("Empty designation", designation=designation)

    fields = [f.strip() for f in designation.split("|") if f.strip()]
    if not fields:
        raise DesignationError("Designation has no fields", designation=designation)

    # -- field 1: dimensions, positional --------------------------------------
    dims = _DIMENSIONS.match(fields[0])
    if not dims:
        raise DesignationError(
            f"First field must be the dimensions as '<b> x <D>', got {fields[0]!r}",
            designation=designation,
            field=fields[0],
        )
    width, depth = float(dims.group(1)), float(dims.group(2))

    grade: float | None = None
    cover = DEFAULT_COVER
    flange_width = flange_depth = None
    n_bottom = n_top = 0
    dia_bottom = dia_top = 0.0
    fit_dia = fit_legs = 0
    fit_spacing = 0.0

    # -- remaining fields: keyword-led, order-independent ----------------------
    for text in fields[1:]:
        if m := _GRADE.match(text):
            grade = float(m.group(1))
        elif m := _TEE.match(text):
            flange_width, flange_depth = float(m.group(1)), float(m.group(2))
        elif m := _COVER.match(text):
            cover = float(m.group(1))
        elif m := _BARS.match(text):
            face, count, dia = m.group(1).upper(), int(m.group(2)), float(m.group(3))
            if face == "BOT":
                n_bottom, dia_bottom = count, dia
            else:
                n_top, dia_top = count, dia
        elif m := _LIGS.match(text):
            fit_dia = float(m.group(1))
            fit_legs = int(m.group(2))
            fit_spacing = float(m.group(3))
        else:
            raise DesignationError(
                f"Unrecognised field {text!r}. Expected one of: C<grade>, "
                "T <bf>/<Df>, COV <c>, BOT <n>-N<dia>, TOP <n>-N<dia>, "
                "LIG N<dia>-<legs>L@<spacing>.",
                designation=designation,
                field=text,
            )

    # [CHECK] The grade is not optional. Defaulting it would produce a capacity
    #         from a concrete nobody specified.
    if grade is None:
        raise DesignationError(
            "Designation has no concrete grade. Add a field like 'C40'.",
            designation=designation,
        )

    if flange_width is not None and flange_depth is not None and flange_depth >= depth:
        raise DesignationError(
            f"Flange thickness {flange_depth} must be less than the overall "
            f"depth {depth}",
            designation=designation,
        )

    return ParsedDesignation(
        width=width,
        depth=depth,
        grade=grade,
        cover=cover,
        flange_width=flange_width,
        flange_depth=flange_depth,
        n_bottom=n_bottom,
        dia_bottom=dia_bottom,
        n_top=n_top,
        dia_top=dia_top,
        fitment_diameter=float(fit_dia),
        fitment_legs=fit_legs,
        fitment_spacing=fit_spacing,
    )


def parse(
    designation: str,
    name: str = "",
    material: Reinforcement = D500N,
    concrete_material: Concrete | None = None,
) -> RCSection:
    """Build an :class:`RCSection` from a designation string.

    Parameters
    ----------
    designation:
        The designation, e.g. ``"350 x 650 | C40 | BOT 4-N28 | LIG N12-2L@200"``.
    name:
        Member name to attach, e.g. ``"B1"``.
    material:
        Reinforcement grade for all bars. The grammar does not encode grade
        because a mixed-grade beam is rare enough that it belongs in a note.
    concrete_material:
        Override the concrete built from the ``C<grade>`` field -- for a
        non-default density, say.

    Returns
    -------
    RCSection
        With ``metadata`` carrying the cover and fitment diameter so that
        :func:`designate` can round-trip it exactly.

    Examples
    --------
    >>> section = parse("350 x 650 | C40 | COV 40 | BOT 4-N28 | LIG N12-2L@200", name="B1")
    >>> section.d
    584.0
    """
    fields = parse_fields(designation)
    conc = concrete_material if concrete_material is not None else concrete(fields.grade)

    fit_dia = fields.fitment_diameter or DEFAULT_FITMENT_DIAMETER

    if fields.is_tee:
        section = rc_tee(
            bf=fields.flange_width,
            Df=fields.flange_depth,
            bw=fields.width,
            D=fields.depth,
            concrete=conc,
            cover=fields.cover,
            n_bars=fields.n_bottom,
            diameter=fields.dia_bottom,
            fitment_diameter=fit_dia,
            fitment_spacing=fields.fitment_spacing or None,
            fitment_legs=fields.fitment_legs or 2,
            material=material,
            name=name,
        )
        # rc_tee does not take top steel; add it here rather than widening a
        # constructor for a case the grammar supports and it does not.
        if fields.n_top and fields.dia_top:
            depth_top = fields.cover + fit_dia + fields.dia_top / 2.0
            section = section.add_layer(
                RebarLayer.from_bars(
                    fields.n_top, fields.dia_top, depth_top, material, label="top"
                )
            )
    else:
        section = rc_beam(
            b=fields.width,
            D=fields.depth,
            concrete=conc,
            cover=fields.cover,
            n_bars=fields.n_bottom,
            diameter=fields.dia_bottom,
            fitment_diameter=fit_dia,
            fitment_spacing=fields.fitment_spacing or None,
            fitment_legs=fields.fitment_legs or 2,
            n_top_bars=fields.n_top,
            top_diameter=fields.dia_top,
            material=material,
            name=name,
        )

    # Record what the grammar supplied so designate() can reproduce it exactly
    # rather than inferring cover back out of the bar depths.
    section.metadata["cover"] = fields.cover
    section.metadata["fitment_diameter"] = fit_dia
    section.metadata["designation"] = designation.strip()
    return section


def designate(section: RCSection) -> str:
    """Serialise an :class:`RCSection` back to a designation string.

    The inverse of :func:`parse`. Where the section came from :func:`parse`, the
    cover and fitment diameter are read from its metadata; otherwise they are
    inferred from the bar depths, which is exact for the single-layer
    arrangement the grammar covers.

    Raises
    ------
    DesignationError
        If the section cannot be expressed in the grammar -- more than one
        layer per face, or a shape that is neither rectangular nor a tee.
    """
    geom = section.geometry
    bands = geom.bands

    if len(bands) == 1:
        width, is_tee = geom.b_top, False
    elif len(bands) == 2 and bands[0].width > bands[1].width:
        width, is_tee = bands[1].width, True
    else:
        raise DesignationError(
            f"Section shape with {len(bands)} bands cannot be expressed in the "
            "designation grammar, which covers rectangles and top-flanged tees."
        )

    fit = section.fitment
    fit_dia = section.metadata.get(
        "fitment_diameter", fit.diameter if fit and fit.diameter else DEFAULT_FITMENT_DIAMETER
    )

    # Split layers by face. The grammar supports one layer each.
    mid = geom.D / 2.0
    bottom = [layer for layer in section.layers if layer.depth > mid]
    top = [layer for layer in section.layers if layer.depth <= mid]
    for face, layers in (("bottom", bottom), ("top", top)):
        if len(layers) > 1:
            raise DesignationError(
                f"Section has {len(layers)} {face} reinforcement layers. The "
                "designation grammar supports one layer per face; record "
                "multi-layer arrangements in a note."
            )

    cover = section.metadata.get("cover")
    if cover is None and bottom and bottom[0].diameter:
        cover = geom.D - bottom[0].depth - fit_dia - bottom[0].diameter / 2.0
    if cover is None:
        cover = DEFAULT_COVER

    parts = [f"{width:g} x {geom.D:g}", f"C{section.concrete.fc:g}"]
    if is_tee:
        parts.append(f"T {bands[0].width:g}/{bands[0].y_bot:g}")
    parts.append(f"COV {cover:g}")

    for face, layers in (("BOT", bottom), ("TOP", top)):
        if not layers:
            continue
        layer = layers[0]
        if not (layer.n_bars and layer.diameter):
            raise DesignationError(
                f"{face} layer is specified by area ({layer.area:.0f} mm^2) "
                "rather than by bars, so it cannot be written as a designation. "
                "Detail it with RebarLayer.from_bars() first."
            )
        parts.append(f"{face} {layer.n_bars}-N{layer.diameter:g}")

    if fit:
        legs = fit.n_legs or 2
        parts.append(f"LIG N{fit_dia:g}-{legs}L@{fit.spacing:g}")

    return " | ".join(parts)


def validate(designation: str) -> tuple[bool, str]:
    """Check a designation parses, without raising.

    For bulk-checking a schedule, where one bad cell should be reported rather
    than stopping the run.

    Returns
    -------
    (ok, message)
        ``message`` is empty when ``ok`` is True.
    """
    try:
        parse(designation)
    except (DesignationError, Exception) as exc:  # noqa: BLE001 -- report anything
        return False, str(exc)
    return True, ""
