"""L3 -- analysis. Code-agnostic structural analysis.

Imports from: core, materials, sections. Knows nothing about design standards.
"""

from .beam import (
    Beam,
    Support,
    SupportType,
    cantilever,
    continuous,
    fixed_fixed,
    propped_cantilever,
    simply_supported,
)
from .closed_form import (
    ClosedFormResult,
    cantilever_tip_point,
    cantilever_udl,
    fixed_central_point,
    fixed_udl,
    propped_central_point,
    propped_udl,
    ss_central_point,
    ss_offset_point,
    ss_udl,
)
from .envelope import (
    ActionEnvelope,
    BeamEnvelope,
    ReactionEnvelope,
    analyse_combinations,
    envelope_by_limit_state,
    envelope_from_results,
)
from .loading import (
    UDL,
    AppliedMoment,
    Load,
    LoadTrain,
    PartialUDL,
    PointLoad,
    SelfWeight,
    VaryingUDL,
)
from .moving import (
    InfluenceLine,
    MovingLoadResult,
    influence_line,
    moving_load_envelope,
    sweep_positions,
)
from .results import BeamResults, Reaction
from .solver import solve

__all__ = [
    # model
    "Beam",
    "Support",
    "SupportType",
    "simply_supported",
    "cantilever",
    "propped_cantilever",
    "fixed_fixed",
    "continuous",
    # loads
    "Load",
    "PointLoad",
    "UDL",
    "PartialUDL",
    "VaryingUDL",
    "AppliedMoment",
    "SelfWeight",
    # solving
    "solve",
    "BeamResults",
    "Reaction",
    # envelopes across load combinations
    "analyse_combinations",
    "envelope_by_limit_state",
    "BeamEnvelope",
    "ActionEnvelope",
    "ReactionEnvelope",
    "envelope_from_results",
    # moving loads
    "LoadTrain",
    "MovingLoadResult",
    "moving_load_envelope",
    "sweep_positions",
    "InfluenceLine",
    "influence_line",
    # closed form benchmarks
    "ClosedFormResult",
    "ss_udl",
    "ss_central_point",
    "ss_offset_point",
    "cantilever_udl",
    "cantilever_tip_point",
    "propped_udl",
    "propped_central_point",
    "fixed_udl",
    "fixed_central_point",
]
