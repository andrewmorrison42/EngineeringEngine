"""AS 3600:2018 design provisions.

All code constants live in :mod:`.constants` -- that is the module to check
against the printed standard. The mechanics are shared with AS 5100.5 via
:mod:`austruct.design.rc_common`.
"""

from . import constants
from .detailing import (
    DevelopmentLength,
    cd_dimension,
    check_bar_fit,
    check_detailing,
    compression_development_length,
    curtailment_extension,
    development_length,
    lap_length,
    minimum_clear_spacing,
)
from .flexure import (
    check_flexure,
    minimum_steel_area,
    moment_capacity,
    required_steel_area,
)
from .optimise import (
    CostRates,
    OptimisationResult,
    SearchBounds,
    SectionCost,
    SizeRange,
    minimum_cost_section,
)
from .serviceability import (
    check_crack_control,
    check_deflection,
    check_span_to_depth,
    effective_stiffness,
    ief_max,
    redistribution_limit,
)
from .shear import (
    check_shear,
    effective_shear_depth,
    minimum_shear_reinforcement,
    required_shear_reinforcement,
    shear_capacity,
)

__all__ = [
    "constants",
    # flexure
    "moment_capacity",
    "check_flexure",
    "required_steel_area",
    "minimum_steel_area",
    # cost optimisation
    "minimum_cost_section",
    "SearchBounds",
    "SizeRange",
    "CostRates",
    "SectionCost",
    "OptimisationResult",
    # shear
    "shear_capacity",
    "check_shear",
    "required_shear_reinforcement",
    "effective_shear_depth",
    "minimum_shear_reinforcement",
    # serviceability
    "effective_stiffness",
    "ief_max",
    "check_deflection",
    "check_crack_control",
    "check_span_to_depth",
    "redistribution_limit",
    # detailing and anchorage
    "DevelopmentLength",
    "development_length",
    "compression_development_length",
    "lap_length",
    "curtailment_extension",
    "minimum_clear_spacing",
    "cd_dimension",
    "check_bar_fit",
    "check_detailing",
]
