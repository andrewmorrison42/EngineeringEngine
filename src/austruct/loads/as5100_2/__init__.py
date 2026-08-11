"""AS 5100.2:2017 road traffic actions.

Read ``data/traffic_models.json`` before using anything here: the axle
geometry has NOT been transcribed from the printed standard, and every
constructor refuses to build a model until it has been.
"""

from .traffic import (
    UnverifiedLoadModel,
    a160,
    a160_wheels,
    describe_models,
    dla,
    is_verified,
    lane_factor,
    load_data,
    m1600,
    s1600,
    total_lane_factor,
    verification_status,
    w80,
    w80_wheel,
    with_dla,
)

__all__ = [
    "w80",
    "w80_wheel",
    "a160",
    "a160_wheels",
    "m1600",
    "s1600",
    "dla",
    "with_dla",
    "lane_factor",
    "total_lane_factor",
    "describe_models",
    "is_verified",
    "verification_status",
    "load_data",
    "UnverifiedLoadModel",
]
