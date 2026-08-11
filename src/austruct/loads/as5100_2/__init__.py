"""AS 5100.2:2017 road and rail traffic actions.

A catalogue you nominate by name -- ``get("M1600")`` returns the vehicle with
its axle spacings, wheel contact patch and dynamic load allowance attached, so
no call site restates them.

Read ``data/traffic_models.json`` before using anything here: the geometry has
NOT been transcribed from the printed standard, and the catalogue refuses to
hand out a model until you say so once with ``allow_unverified(True)``.
"""

from .traffic import (
    DATA_FILE,
    LoadModel,
    TrafficKind,
    UnverifiedLoadModel,
    WheelGeometry,
    a160,
    allow_unverified,
    catalogue,
    dla,
    get,
    hlp,
    is_verified,
    la,
    lane_factor,
    load_data,
    m1600,
    names,
    rail_dla,
    reload,
    s1600,
    total_lane_factor,
    unverified_ok,
    verification_status,
    w80,
)

__all__ = [
    # the catalogue
    "get",
    "names",
    "catalogue",
    "LoadModel",
    "WheelGeometry",
    "TrafficKind",
    # named models
    "w80",
    "a160",
    "m1600",
    "s1600",
    "hlp",
    "la",
    # allowances and factors
    "dla",
    "rail_dla",
    "lane_factor",
    "total_lane_factor",
    # the guard
    "allow_unverified",
    "unverified_ok",
    "UnverifiedLoadModel",
    # data
    "is_verified",
    "verification_status",
    "load_data",
    "reload",
    "DATA_FILE",
]
