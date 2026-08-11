"""AS 5100.2:2017 traffic load models -- a catalogue you nominate by name.

The point of this module
------------------------
You should be able to say "M1600" and get the vehicle -- axle spacings, axle
loads, lane UDL, wheel contact patch and dynamic load allowance, all of it --
without writing any of those numbers down. Writing them down at each call site
is how a wheel spacing ends up differing between two calculations on the same
job.

    >>> allow_unverified(True)              # once, see the guard below
    >>> m1600 = get("M1600")
    >>> m1600.train_with_dla()              # ready to sweep
    >>> m1600.wheel.contact_length          # dispersal reads this itself

Everything is data-driven from ``data/traffic_models.json``, so adding a
loading -- an ARTC rail vehicle, a state authority permit vehicle, a project
crane -- is an edit to that file, not a change here.

=============================================================================
THE GUARD -- READ THIS
=============================================================================
Everywhere else in austruct an unverified value is a single coefficient. Here
it is *the geometry and magnitude of an entire load model*, and an axle spacing
transcribed wrongly produces a bridge design that is wrong in a way no
downstream check will catch.

So the catalogue refuses to hand out a model until somebody says, once, that
they know the geometry is unverified::

    from austruct.loads.as5100_2 import allow_unverified, unverified_ok

    allow_unverified(True)          # for a notebook or a script
    with unverified_ok():           # or scoped, for a test
        ...

That is one line per session rather than an argument on every call, which was
the friction that made people want to remove the guard altogether. Set
``AUSTRUCT_ALLOW_UNVERIFIED_LOADS=1`` to do it from the environment.

Once the data file's status is VERIFIED with a named checker, the guard stops
applying and none of this is needed.

[UNITS] Positions mm, forces N, distributed loads N/mm, as everywhere. The
        DATA FILE is in kN and kN/m because that is how the standard prints
        them; conversion happens on load.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from functools import cache
from importlib import resources
from typing import Any

from ...analysis.loading import LoadTrain
from ...core.basis import AS5100_2_2017, ClauseRef
from ...core.exceptions import AustructError
from ...core.provenance import ASETComponent, ModuleType, Provenance
from ...core.registry import REGISTRY
from ...core.units import kN, kN_per_m

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.2.0",
        author="A. Morrison",
        module_type=ModuleType.A_TABULATED,
        component=ASETComponent.PROJECT_DATA,
    ),
    description="AS 5100.2:2017 road and rail traffic load models, as a named catalogue",
    envelope_summary=(
        "W80, A160, M1600, S1600, HLP320, HLP400, 300LA. "
        "UNVERIFIED geometry; HLP entries are placeholders."
    ),
)

DATA_PACKAGE = "austruct.loads.as5100_2.data"
DATA_FILE = "traffic_models.json"


class UnverifiedLoadModel(AustructError):
    """A traffic load model was requested while its geometry is unverified.

    Distinct from :class:`~austruct.core.exceptions.UnverifiedConstant`, which
    is about a coefficient. This is about an entire load model, and it is
    refused by default rather than only in strict mode.
    """


class TrafficKind(str, Enum):
    """Road or rail.

    They differ in more than magnitude: the rail dynamic load allowance is
    span-dependent, and rail loads run on a track rather than in a lane, so the
    accompanying lane factors do not apply to them.
    """

    ROAD = "road"
    RAIL = "rail"


# ---------------------------------------------------------------------------
# The session guard
# ---------------------------------------------------------------------------

_ALLOW_UNVERIFIED = os.environ.get(
    "AUSTRUCT_ALLOW_UNVERIFIED_LOADS", ""
).lower() in {"1", "true", "yes"}


def allow_unverified(enabled: bool | None = None) -> bool:
    """Get or set the session-wide permission to build unverified models.

    Call once at the top of a notebook or script::

        from austruct.loads.as5100_2 import allow_unverified
        allow_unverified(True)

    Deliberately session-wide rather than per-call: an argument repeated on
    every line stops being read after the third time, whereas one statement at
    the top of a file is a decision somebody made.
    """
    global _ALLOW_UNVERIFIED
    if enabled is not None:
        _ALLOW_UNVERIFIED = bool(enabled)
    return _ALLOW_UNVERIFIED


@contextmanager
def unverified_ok() -> Iterator[None]:
    """Scoped permission to build unverified models.

    For tests, and for a single calculation inside an otherwise strict script::

        with unverified_ok():
            train = get("M1600").train_with_dla()

    Restores the previous setting on exit, including on exception.
    """
    previous = allow_unverified()
    allow_unverified(True)
    try:
        yield
    finally:
        allow_unverified(previous)


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------


@cache
def load_data() -> dict[str, Any]:
    """The traffic model data file."""
    text = resources.files(DATA_PACKAGE).joinpath(DATA_FILE).read_text(encoding="utf-8")
    return json.loads(text)


def reload() -> None:
    """Drop the caches so an edited data file is picked up without a restart."""
    load_data.cache_clear()
    _build_model.cache_clear()


def verification_status() -> tuple[str, str | None, str | None]:
    """``(status, checked_by, checked_on)`` for the traffic model data."""
    data = load_data()
    return data.get("status", "UNKNOWN"), data.get("checked_by"), data.get("checked_on")


def is_verified() -> bool:
    """Whether the traffic geometry has been checked against the standard."""
    return verification_status()[0] == "VERIFIED"


def _guard(name: str) -> None:
    """Refuse an unverified model unless permission has been given.

    [CHECK] The hardest fail-closed gate in the package. See the module
            docstring for why this one is stricter than everything else.
    """
    if is_verified() or _ALLOW_UNVERIFIED:
        return
    raise UnverifiedLoadModel(
        f"The {name} load model geometry in {DATA_FILE} is UNVERIFIED -- it has "
        "not been transcribed from AS 5100.2:2017, only recalled. Axle spacings "
        "and axle loads must be confirmed against the printed standard, and the "
        "file's status set to VERIFIED with a named checker, before this model "
        "is used for design.\n\n"
        "To proceed anyway for development or testing, say so once:\n\n"
        "    from austruct.loads.as5100_2 import allow_unverified\n"
        "    allow_unverified(True)\n\n"
        "or scope it with `with unverified_ok():`. Do not use the result for a "
        "bridge."
    )


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WheelGeometry:
    """Contact geometry of the wheels on one axle.

    Carried BY the load model, so dispersal through fill, bearing checks and
    local slab analysis all read the same numbers rather than each being handed
    them separately at the call site.

    Parameters
    ----------
    n_per_axle:
        Wheels on one axle.
    spacing:
        Transverse centre-to-centre spacing between adjacent wheels (mm).
    contact_length:
        Contact patch dimension ALONG the direction of travel (mm).
    contact_width:
        Contact patch dimension ACROSS the direction of travel (mm).
    """

    n_per_axle: int
    spacing: float
    contact_length: float
    contact_width: float

    def transverse_positions(self) -> tuple[float, ...]:
        """Wheel centres across the vehicle, from its centreline (mm).

        A two-wheel axle at 2.0 m spacing gives ``(-1000, +1000)``. Symmetric
        about zero, so the vehicle centreline is the datum that the
        ``transverse_offset`` used in dispersal is measured against.
        """
        n = self.n_per_axle
        if n <= 1:
            return (0.0,)
        span = (n - 1) * self.spacing
        return tuple(-span / 2.0 + i * self.spacing for i in range(n))

    def wheel_load(self, axle_load: float) -> float:
        """Load on one wheel, given the total on the axle (N)."""
        return axle_load / max(self.n_per_axle, 1)

    def __str__(self) -> str:
        return (
            f"{self.n_per_axle} wheel(s) @ {self.spacing:.0f} mm, contact "
            f"{self.contact_length:.0f} x {self.contact_width:.0f} mm"
        )


@dataclass(frozen=True)
class LoadModel:
    """A named traffic load model, complete with everything it needs.

    Nominate it by name from the catalogue; do not build one by hand unless you
    are adding a loading the data file does not carry.

    Attributes
    ----------
    name:
        Designation, e.g. ``"M1600"``.
    kind:
        Road or rail.
    train:
        The load pattern, WITHOUT any dynamic load allowance.
    wheel:
        Contact geometry per axle.
    dla:
        Dynamic load allowance as a fraction, or ``None`` where it is not a
        constant -- rail, where it depends on the loaded length.
    """

    name: str
    kind: TrafficKind
    train: LoadTrain
    wheel: WheelGeometry
    dla: float | None
    description: str = ""
    clause: str = ""
    confidence: str = ""
    axle_load: float = 0.0
    """Total load on one axle (N). Zero for a model with no regular axle."""

    loaded_width: float = 3200.0
    """Transverse width the UDL is spread over (mm) -- the lane or track width.

    Needed to work out how much of a lane UDL lands on a strip narrower than
    the lane. Only meaningful where the model HAS a UDL.
    """

    @property
    def basis(self) -> ClauseRef:
        return ClauseRef(AS5100_2_2017, self.clause, note=self.description)

    @property
    def total_axle_load(self) -> float:
        """Sum of all axle loads (N)."""
        return self.train.total_axle_load

    @property
    def udl(self) -> float:
        """Lane or track distributed load (N/mm)."""
        return self.train.trailing_udl

    @property
    def wheel_load(self) -> float:
        """Load on one wheel of a typical axle (N)."""
        return self.wheel.wheel_load(self.axle_load)

    @property
    def is_placeholder(self) -> bool:
        """Whether the data file flags this entry as untrusted even by the
        standards of a file that is unverified throughout."""
        return "PLACEHOLDER" in self.confidence.upper()

    def train_with_dla(self) -> LoadTrain:
        """The load pattern with the dynamic load allowance applied.

        Raises
        ------
        NotImplementedError
            For a rail model, whose allowance depends on the loaded length and
            is not implemented. Refusing beats applying a wrong constant.
        """
        if self.dla is None:
            raise NotImplementedError(
                f"{self.name} has no constant dynamic load allowance -- for rail "
                "traffic AS 5100.2 Section 9 makes it a function of the loaded "
                "length, which is not implemented. Compute it yourself and "
                "apply it with train.scaled(1 + alpha)."
            )
        if self.dla == 0.0:
            return self.train
        scaled = self.train.scaled(1.0 + self.dla)
        return LoadTrain(
            name=f"{self.name}(1+{self.dla:g})",
            axles=scaled.axles,
            udl_segments=scaled.udl_segments,
            length=scaled.length,
            trailing_udl=scaled.trailing_udl,
        )

    def scaled(self, factor: float, name: str | None = None) -> LoadModel:
        """A copy with every load multiplied -- for a lane factor, or for an
        ``nLA`` rail variant. Geometry is untouched."""
        return LoadModel(
            name=name or f"{self.name}x{factor:g}",
            kind=self.kind,
            train=self.train.scaled(factor),
            wheel=self.wheel,
            dla=self.dla,
            loaded_width=self.loaded_width,
            description=self.description,
            clause=self.clause,
            confidence=self.confidence,
            axle_load=self.axle_load * factor,
        )

    def describe(self) -> list[str]:
        lines = [
            f"{self.name}  ({self.kind.value})",
            f"  {self.description}",
            f"  Basis        AS 5100.2:2017 Cl {self.clause}",
            f"  Axles        {len(self.train.axles)}, total "
            f"{self.total_axle_load / kN:.0f} kN over {self.train.length / 1000:.2f} m",
        ]
        if self.axle_load:
            lines.append(
                f"  Per axle     {self.axle_load / kN:.0f} kN "
                f"({self.wheel_load / kN:.0f} kN per wheel)"
            )
        if self.udl:
            lines.append(
                f"  UDL          {self.udl / kN_per_m:.1f} kN/m over "
                f"{self.loaded_width / 1000:.1f} m width"
            )
        lines.append(f"  Wheels       {self.wheel}")
        lines.append(
            f"  DLA          {self.dla:.2f}"
            if self.dla is not None
            else "  DLA          span-dependent, not implemented"
        )
        if self.confidence:
            lines.append(f"  Confidence   {self.confidence}")
        return lines

    def __str__(self) -> str:
        return f"<LoadModel {self.name} {self.total_axle_load / kN:.0f} kN>"

    def _repr_markdown_(self) -> str:
        """Rich display in a Jupyter notebook."""
        body = "\n".join(self.describe())
        warning = (
            "\n\n> **Placeholder geometry — not trusted even as a recollection.**"
            if self.is_placeholder
            else ""
        )
        return f"```\n{body}\n```{warning}"


# ---------------------------------------------------------------------------
# Building models from the data file
# ---------------------------------------------------------------------------


def _axles_from_geometry(
    geom: dict[str, Any],
) -> tuple[tuple[tuple[float, float], ...], float]:
    """``(axles, overall_length)`` from a geometry block.

    Handles both schema forms: an explicit ``axles`` list, and repeated
    ``groups`` at a variable gap.
    """
    kind = geom.get("type", "axles")

    if kind == "axles":
        axles = tuple((float(o), float(load) * kN) for o, load in geom["axles"])
        length = max((o for o, _ in axles), default=0.0)
        return axles, length

    if kind != "groups":
        raise ValueError(f"Unknown geometry type {kind!r} in the traffic data file")

    n_axles = int(geom["n_axles"])
    spacing = float(geom["axle_spacing"])
    load = float(geom["axle_load"]) * kN
    n_groups = int(geom["n_groups"])
    gap = float(geom["group_gap"])

    group_length = (n_axles - 1) * spacing
    out: list[tuple[float, float]] = []
    offset = 0.0
    for _ in range(n_groups):
        for a in range(n_axles):
            out.append((offset + a * spacing, load))
        offset += group_length + gap

    # Front axle to rear axle -- the trailing gap is not part of the vehicle.
    length = (n_groups - 1) * (group_length + gap) + group_length if n_groups else 0.0
    return tuple(out), length


def _resolve_name(name: str) -> str:
    """Match a designation case- and whitespace-insensitively.

    Raises a KeyError that LISTS what is available: the usual mistake is a
    near-miss designation, and a bare KeyError does not help with that.
    """
    models = load_data()["models"]
    wanted = name.strip().upper()
    for key in models:
        if key.upper() == wanted:
            return key
    raise KeyError(
        f"No traffic load model named {name!r}. Available: "
        f"{', '.join(sorted(models))}. Add a new one by editing "
        f"{DATA_FILE} -- the schema is documented in its header."
    )


@cache
def _build_model(key: str) -> LoadModel:
    """Construct one model from the data file. Cached -- models are immutable."""
    spec = load_data()["models"][key]

    geom = spec["geometry"]
    axles, length = _axles_from_geometry(geom)
    wheel_spec = spec["wheel"]

    axle_load = (
        float(geom["axle_load"]) * kN
        if geom.get("type") == "groups"
        else (axles[0][1] if axles else 0.0)
    )

    return LoadModel(
        name=key,
        kind=TrafficKind(spec["kind"]),
        train=LoadTrain(
            name=key,
            axles=axles,
            length=length,
            trailing_udl=float(spec.get("udl", 0.0)) * kN_per_m,
        ),
        wheel=WheelGeometry(
            n_per_axle=int(wheel_spec["n_per_axle"]),
            spacing=float(wheel_spec["spacing"]),
            contact_length=float(wheel_spec["contact_length"]),
            contact_width=float(wheel_spec["contact_width"]),
        ),
        dla=None if spec.get("dla") is None else float(spec["dla"]),
        loaded_width=float(spec.get("loaded_width", 3.2)) * 1000.0,
        description=spec.get("description", ""),
        clause=spec.get("clause", ""),
        confidence=spec.get("confidence", ""),
        axle_load=axle_load,
    )


def get(name: str) -> LoadModel:
    """Nominate a load model by name.

    Parameters
    ----------
    name:
        Designation -- ``"M1600"``, ``"S1600"``, ``"A160"``, ``"W80"``,
        ``"HLP320"``, ``"HLP400"``, ``"300LA"``. Case-insensitive.

    Returns
    -------
    LoadModel
        Carrying the axle pattern, the wheel contact geometry and the dynamic
        load allowance, so no call site has to state any of them.

    Raises
    ------
    UnverifiedLoadModel
        Unless permission has been given for the session -- see the module
        docstring.
    KeyError
        If the designation is not in the catalogue. The message lists what is.

    Examples
    --------
    >>> allow_unverified(True)
    >>> m1600 = get("M1600")
    >>> m1600.wheel.contact_length
    250.0
    """
    key = _resolve_name(name)
    _guard(key)
    return _build_model(key)


def names(kind: TrafficKind | str | None = None) -> tuple[str, ...]:
    """Designations in the catalogue, optionally filtered to road or rail.

    Needs no permission -- listing what exists is not using it.
    """
    models = load_data()["models"]
    if kind is None:
        return tuple(sorted(models))
    wanted = TrafficKind(kind).value
    return tuple(sorted(k for k, v in models.items() if v["kind"] == wanted))


def catalogue(kind: TrafficKind | str | None = None) -> str:
    """The catalogue as a table, with verification status and confidence.

    Needs no permission, so it can be printed to decide what to nominate.
    """
    data = load_data()
    status, checker, checked_on = verification_status()

    lines = [
        f"AS 5100.2 traffic load models -- {data['source']}",
        f"Status: {status}   checked by: {checker or '-'}   on: {checked_on or '-'}",
        "",
    ]
    if status != "VERIFIED":
        lines += [
            "  *** GEOMETRY NOT TRANSCRIBED FROM THE STANDARD. NOT FOR DESIGN. ***",
            f"  *** Permission {'GIVEN' if _ALLOW_UNVERIFIED else 'NOT GIVEN'} "
            "for this session (allow_unverified). ***",
            "",
        ]

    header = (
        f"  {'Model':<8}{'Kind':<7}{'Axles':>6}{'Total kN':>10}"
        f"{'UDL kN/m':>10}  Confidence"
    )
    lines += [header, "  " + "-" * (len(header) - 2)]

    for key in names(kind):
        spec = data["models"][key]
        axles, _ = _axles_from_geometry(spec["geometry"])
        total = sum(load for _, load in axles) / kN
        lines.append(
            f"  {key:<8}{spec['kind']:<7}{len(axles):>6}{total:>10.0f}"
            f"{spec.get('udl', 0.0):>10.1f}  {spec.get('confidence', '')}"
        )

    lines += ["", "  Add a loading by editing the data file -- see its header."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience for the models people reach for most
# ---------------------------------------------------------------------------


def w80() -> LoadModel:
    """W80 -- individual heavy wheel load."""
    return get("W80")


def a160() -> LoadModel:
    """A160 -- single axle load."""
    return get("A160")


def m1600() -> LoadModel:
    """M1600 -- moving traffic load."""
    return get("M1600")


def s1600() -> LoadModel:
    """S1600 -- stationary traffic load."""
    return get("S1600")


def hlp(tonnes: int = 320) -> LoadModel:
    """HLP -- heavy load platform.

    [VECTOR] The HLP entries are PLACEHOLDERS. The author is not confident of
             the axle count, the axle load or the group arrangement, and says
             so on the model itself via ``is_placeholder``.
    """
    return get(f"HLP{tonnes}")


def la(axle_kn: int = 300) -> LoadModel:
    """Rail traffic load of the ``nLA`` family.

    ``la(300)`` is 300LA as tabulated. Any other value scales the tabulated
    300LA configuration by ``axle_kn/300`` -- which is what the nLA designation
    means, the geometry being common to the family.

    [VECTOR] UNVERIFIED. Confirm both the 300LA configuration and that the
             family really does scale linearly before relying on a variant.
    """
    base = get("300LA")
    if axle_kn == 300:
        return base
    return base.scaled(axle_kn / 300.0, name=f"{axle_kn}LA")


# ---------------------------------------------------------------------------
# Dynamic load allowance and lane factors
# ---------------------------------------------------------------------------


def dla(name: str) -> float:
    """Dynamic load allowance for a named model, as a FRACTION.

    The design action is ``(1 + alpha)`` times the static action.

    Raises
    ------
    NotImplementedError
        For a rail model, whose allowance is span-dependent.
    """
    model = get(name)
    if model.dla is None:
        raise NotImplementedError(
            f"{model.name} has a span-dependent dynamic load allowance. See rail_dla()."
        )
    return model.dla


def rail_dla(loaded_length: float) -> float:
    """Dynamic load allowance for rail traffic. NOT IMPLEMENTED.

    AS 5100.2 Section 9 makes the rail allowance a function of the loaded
    length rather than a constant. Raising is deliberate: a plausible constant
    here would be applied silently to every rail calculation ever run.
    """
    raise NotImplementedError(
        "The rail dynamic load allowance is span-dependent and is not "
        "implemented. AS 5100.2 Section 9 gives it as a function of the loaded "
        f"length (here {loaded_length / 1000:.1f} m). Compute it from the "
        "standard and apply it with train.scaled(1 + alpha)."
    )


def lane_factor(n_lanes: int, lane: int = 1) -> float:
    """Accompanying lane factor for the ``lane``-th most heavily loaded lane.

    [VECTOR] UNVERIFIED. Road traffic only -- rail loads run on a track, not a
             lane, so these do not apply to an LA loading.
    """
    factors = load_data()["lane_factors"]
    key = str(int(n_lanes))
    if key not in factors:
        raise KeyError(
            f"No lane factors recorded for {n_lanes} lanes. "
            f"Known: {sorted(k for k in factors if not k.startswith('_'))}"
        )
    row = factors[key]
    if not 1 <= lane <= len(row):
        raise ValueError(f"lane must be between 1 and {len(row)}, got {lane}")
    return float(row[lane - 1])


def total_lane_factor(n_lanes: int) -> float:
    """Sum of the accompanying lane factors -- the effective number of lanes."""
    return float(sum(load_data()["lane_factors"][str(int(n_lanes))]))
