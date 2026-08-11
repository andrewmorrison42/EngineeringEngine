"""AS 5100.2:2017 road traffic load models.

=============================================================================
READ THE DATA FILE HEADER BEFORE USING THIS MODULE.
=============================================================================

Every other module in this package marks individual coefficients as needing
verification. Here the unverified content is *the geometry and magnitude of an
entire load model*. An axle spacing transcribed wrongly produces a bridge
design that is wrong in a way no downstream check will catch.

So this module fails closed harder than anything else in the toolkit: while
``data/traffic_models.json`` declares itself UNVERIFIED, every constructor
raises unless it is passed ``allow_unverified=True``. That flag exists so the
machinery can be developed and tested; it is not a way to get a bridge design.

What is here
------------
:func:`w80`, :func:`a160`
    Local wheel and axle loads, as positionable :class:`LoadTrain` objects.
:func:`m1600`, :func:`s1600`
    Global traffic models, with their UDL and axle groups.
:func:`with_dla`
    Applies the dynamic load allowance.
:func:`lane_factor`
    Accompanying lane factors for multi-lane loading.

Each returns a :class:`~austruct.analysis.moving.LoadTrain`, which is then
swept along the member by
:func:`~austruct.analysis.moving.moving_load_envelope` -- because a traffic
load model is a pattern with a free position, not a load at a known place.

Per-lane, per-metre, or total?
------------------------------
Every model here returns loads for **one lane**, as total force. The UDL
component is returned as a line load along the member (kN/m), NOT as a pressure
-- the standard specifies it per lane over a stated loaded width, and this
module keeps the per-lane form. Distributing it onto a particular girder or
strip is a load-distribution decision the caller must make explicitly; see
:mod:`austruct.loads.dispersal` for the buried-structure case.

[UNITS] Positions mm, forces N, distributed loads N/mm, as everywhere.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from ...analysis.loading import LoadTrain
from ...core.exceptions import AustructError
from ...core.provenance import ASETComponent, ModuleType, Provenance
from ...core.registry import REGISTRY
from ...core.units import kN, kN_per_m

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.A_TABULATED,
        component=ASETComponent.PROJECT_DATA,
    ),
    description="AS 5100.2:2017 road traffic load models as positionable load trains",
    envelope_summary="W80, A160, M1600, S1600. HLP not implemented. UNVERIFIED geometry.",
)

DATA_PACKAGE = "austruct.loads.as5100_2.data"
DATA_FILE = "traffic_models.json"


class UnverifiedLoadModel(AustructError):
    """A traffic load model was requested while its geometry is unverified.

    Distinct from :class:`~austruct.core.exceptions.UnverifiedConstant`, which
    is about a coefficient. This is about an entire load model, and it is
    refused by default rather than only in strict mode.
    """


@cache
def load_data() -> dict[str, Any]:
    """The traffic model data file."""
    text = resources.files(DATA_PACKAGE).joinpath(DATA_FILE).read_text(encoding="utf-8")
    return json.loads(text)


def verification_status() -> tuple[str, str | None, str | None]:
    """``(status, checked_by, checked_on)`` for the traffic model data."""
    data = load_data()
    return data.get("status", "UNKNOWN"), data.get("checked_by"), data.get("checked_on")


def is_verified() -> bool:
    """Whether the traffic geometry has been checked against the standard."""
    return verification_status()[0] == "VERIFIED"


def _guard(model: str, allow_unverified: bool) -> None:
    """Refuse to build an unverified load model unless explicitly overridden.

    [CHECK] This is the hardest fail-closed gate in the package, and
            deliberately so. See the module docstring.
    """
    if is_verified() or allow_unverified:
        return
    raise UnverifiedLoadModel(
        f"The {model} load model geometry in {DATA_FILE} is UNVERIFIED -- it has "
        "not been transcribed from AS 5100.2:2017, only recalled. Axle spacings "
        "and axle loads must be confirmed against the printed standard, and the "
        "file's status set to VERIFIED with a named checker, before this model "
        "is used for design.\n\n"
        "Pass allow_unverified=True to build it anyway for development or "
        "testing. Do not use the result for a bridge."
    )


# ---------------------------------------------------------------------------
# Local models -- individual wheel and axle
# ---------------------------------------------------------------------------


def w80(allow_unverified: bool = False) -> LoadTrain:
    """W80 -- individual heavy wheel load.

    Basis
    -----
    AS 5100.2:2017 Section 6. [VECTOR] UNVERIFIED.

    Governs local effects: deck slab bending, and the top slab of a buried
    structure under shallow fill.

    Returns
    -------
    LoadTrain
        A single concentrated load. For a buried structure the wheel should be
        dispersed through the fill first -- see
        :func:`austruct.loads.dispersal.disperse_wheel`.
    """
    _guard("W80", allow_unverified)
    data = load_data()["W80"]
    return LoadTrain(
        name="W80",
        axles=((0.0, data["wheel_load"] * kN),),
        length=0.0,
    )


def a160(allow_unverified: bool = False) -> LoadTrain:
    """A160 -- single axle load.

    Basis
    -----
    AS 5100.2:2017 Section 6. [VECTOR] UNVERIFIED.

    [ASSUMPTION] Returned as a single concentrated load equal to the whole axle.
                 The two wheels are 2.0 m apart TRANSVERSELY, which does not
                 affect a longitudinal beam analysis; it matters for transverse
                 distribution and for dispersal through fill, where the wheels
                 must be treated separately.
    """
    _guard("A160", allow_unverified)
    data = load_data()["A160"]
    return LoadTrain(
        name="A160",
        axles=((0.0, data["axle_load"] * kN),),
        length=0.0,
    )


def a160_wheels(allow_unverified: bool = False) -> tuple[float, float, float, float]:
    """A160 as ``(wheel_load, transverse_spacing, contact_length, contact_width)``.

    The form the dispersal module needs, where the two wheels must be
    dispersed separately and their patches may overlap.

    [UNITS] N and mm.
    """
    _guard("A160", allow_unverified)
    data = load_data()["A160"]
    return (
        data["axle_load"] * kN / 2.0,
        data["wheel_spacing"],
        data["contact_length"],
        data["contact_width"],
    )


def w80_wheel(allow_unverified: bool = False) -> tuple[float, float, float]:
    """W80 as ``(wheel_load, contact_length, contact_width)``.

    [UNITS] N and mm.
    """
    _guard("W80", allow_unverified)
    data = load_data()["W80"]
    return (
        data["wheel_load"] * kN,
        data["contact_length"],
        data["contact_width"],
    )


# ---------------------------------------------------------------------------
# Global models -- M1600 and S1600
# ---------------------------------------------------------------------------


def _build_grouped_train(
    name: str,
    spec: dict[str, Any],
    n_groups: int | None,
    group_gap: float | None,
    include_udl: bool,
) -> LoadTrain:
    """Assemble a train of axle groups plus its UDL.

    The axle groups are laid out front to back: within a group, ``n_axles``
    axles at ``axle_spacing``; between groups, ``group_gap``.
    """
    group = spec["axle_group"]
    n_axles = int(group["n_axles"])
    axle_spacing = float(group["axle_spacing"])
    axle_load = float(group["axle_load"]) * kN

    groups = int(n_groups if n_groups is not None else spec["n_groups"])
    gap = float(group_gap if group_gap is not None else spec["group_gap_min"])

    if gap < spec["group_gap_min"]:
        raise ValueError(
            f"{name} group gap {gap:.0f} mm is below the minimum "
            f"{spec['group_gap_min']:.0f} mm"
        )

    group_length = (n_axles - 1) * axle_spacing

    axles: list[tuple[float, float]] = []
    offset = 0.0
    for _ in range(groups):
        for a in range(n_axles):
            axles.append((offset + a * axle_spacing, axle_load))
        offset += group_length + gap

    # Overall length is front axle to rear axle -- the trailing gap after the
    # last group is not part of the vehicle.
    total_length = (groups - 1) * (group_length + gap) + group_length if groups else 0.0

    udl = spec["udl"] * kN_per_m if include_udl else 0.0

    return LoadTrain(
        name=name,
        axles=tuple(axles),
        length=total_length,
        # [ASSUMPTION] The UDL is applied over the loaded length behind the
        #              vehicle, via the trailing-UDL mechanism. On a single
        #              span that is the part of the span the vehicle has
        #              reached; for the worst effect the sweep finds the
        #              position that maximises it.
        trailing_udl=udl,
    )


def m1600(
    n_groups: int | None = None,
    group_gap: float | None = None,
    include_udl: bool = True,
    allow_unverified: bool = False,
) -> LoadTrain:
    """M1600 -- moving traffic load, one lane.

    Basis
    -----
    AS 5100.2:2017 Section 6. [VECTOR] UNVERIFIED -- axle geometry and loads.

    Parameters
    ----------
    n_groups:
        Number of axle groups. Defaults to the data file's value.
        [TODO] The standard varies the number of groups to suit the span;
        this implementation uses a fixed count. Sweep ``n_groups`` yourself,
        or confirm the intended rule, before relying on it.
    group_gap:
        Spacing between axle groups (mm). Variable in the standard, with a
        minimum; defaults to the minimum, which is not always the worst case
        on a continuous member.
    include_udl:
        Whether to include the 6 kN/m lane UDL.

    Returns
    -------
    LoadTrain
        Per lane, unfactored, WITHOUT dynamic load allowance -- apply it with
        :func:`with_dla`.

    Examples
    --------
    >>> train = with_dla(m1600(allow_unverified=True), "M1600")
    >>> result = moving_load_envelope(beam, train, step=250.0)
    """
    _guard("M1600", allow_unverified)
    return _build_grouped_train(
        "M1600", load_data()["M1600"], n_groups, group_gap, include_udl
    )


def s1600(
    n_groups: int | None = None,
    group_gap: float | None = None,
    include_udl: bool = True,
    allow_unverified: bool = False,
) -> LoadTrain:
    """S1600 -- stationary traffic load, one lane.

    Basis
    -----
    AS 5100.2:2017 Section 6. [VECTOR] UNVERIFIED.

    Heavier UDL and lighter axles than M1600, and no dynamic load allowance --
    stationary traffic does not bounce. Governs where queuing is expected and
    on longer loaded lengths where the UDL dominates.
    """
    _guard("S1600", allow_unverified)
    return _build_grouped_train(
        "S1600", load_data()["S1600"], n_groups, group_gap, include_udl
    )


# ---------------------------------------------------------------------------
# Dynamic load allowance and lane factors
# ---------------------------------------------------------------------------


def dla(model: str) -> float:
    """Dynamic load allowance for a load model.

    Basis
    -----
    AS 5100.2:2017. [VECTOR] UNVERIFIED.

    Returns the ALLOWANCE (e.g. 0.35), not the multiplier. The design action
    is ``(1 + alpha)`` times the static action.

    S1600 returns 0.0 -- stationary traffic attracts no dynamic allowance.
    """
    key = model.upper()
    data = load_data()
    if key not in data or "dla" not in data.get(key, {}):
        raise KeyError(
            f"No dynamic load allowance recorded for {model!r}. "
            f"Known models: {[k for k in data if isinstance(data[k], dict) and 'dla' in data[k]]}"
        )
    return float(data[key]["dla"])


def with_dla(train: LoadTrain, model: str | None = None) -> LoadTrain:
    """Apply the dynamic load allowance to a train.

    Parameters
    ----------
    train:
        The static load train.
    model:
        Which model's allowance to use. Defaults to the train's own name, so
        ``with_dla(m1600())`` does the right thing.

    Returns
    -------
    LoadTrain
        Scaled by ``(1 + alpha)`` and renamed so the factor is visible in the
        governing-position label rather than being invisibly baked in.
    """
    alpha = dla(model or train.name)
    if alpha == 0.0:
        return train
    scaled = train.scaled(1.0 + alpha)
    return LoadTrain(
        name=f"{train.name}(1+{alpha:g})",
        axles=scaled.axles,
        udl_segments=scaled.udl_segments,
        length=scaled.length,
        trailing_udl=scaled.trailing_udl,
    )


def lane_factor(n_lanes: int, lane: int = 1) -> float:
    """Accompanying lane factor for the ``lane``-th most heavily loaded lane.

    Basis
    -----
    AS 5100.2:2017. [VECTOR] UNVERIFIED.

    Parameters
    ----------
    n_lanes:
        Number of loaded lanes.
    lane:
        Which lane, 1-based, ordered by severity. Lane 1 is unreduced.
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
    """Sum of the accompanying lane factors -- the effective number of lanes.

    Multiply a single-lane effect by this to get the effect of ``n_lanes``
    loaded lanes on a member that carries all of them.
    """
    factors = load_data()["lane_factors"][str(int(n_lanes))]
    return float(sum(factors))


def describe_models() -> str:
    """Summary of the traffic models and their verification status."""
    data = load_data()
    status, checker, checked_on = verification_status()
    lines = [
        f"AS 5100.2 traffic load models -- {data['source']}",
        f"Status: {status}   checked by: {checker or '-'}   on: {checked_on or '-'}",
        "",
    ]
    if status != "VERIFIED":
        lines.append("  *** GEOMETRY NOT TRANSCRIBED FROM THE STANDARD. NOT FOR DESIGN. ***")
        lines.append("")

    for key in ("W80", "A160", "M1600", "S1600"):
        spec = data[key]
        lines.append(f"  {key:6s}  {spec['description']}")
        if "axle_group" in spec:
            g = spec["axle_group"]
            lines.append(
                f"          {spec['n_groups']} group(s) of {g['n_axles']} axles "
                f"@ {g['axle_spacing']:.0f} mm, {g['axle_load']:.0f} kN/axle; "
                f"UDL {spec['udl']:.1f} kN/m; DLA {spec['dla']:.2f}"
            )
        elif "wheel_load" in spec:
            lines.append(
                f"          {spec['wheel_load']:.0f} kN wheel, contact "
                f"{spec['contact_length']:.0f} x {spec['contact_width']:.0f} mm; "
                f"DLA {spec['dla']:.2f}"
            )
        else:
            lines.append(
                f"          {spec['axle_load']:.0f} kN axle, wheels @ "
                f"{spec['wheel_spacing']:.0f} mm; DLA {spec['dla']:.2f}"
            )
    lines.append("")
    for key, note in data["not_implemented"].items():
        lines.append(f"  {key:6s}  {note}")
    return "\n".join(lines)
