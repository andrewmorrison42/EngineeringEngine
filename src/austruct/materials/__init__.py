"""L1 -- materials. The reference-data layer.

Imports from: core only.
"""

from .bar_catalogue import (
    DEFORMED_DIAMETERS,
    FITMENT_DIAMETERS,
    PLAIN_DIAMETERS,
    BarArrangement,
    bar_area,
    bars_for_area,
    describe_options,
    layer_area,
    options_for_area,
    spacing_for_area,
)
from .concrete import (
    C25,
    C32,
    C40,
    C50,
    EPSILON_CU,
    STANDARD_GRADES,
    Concrete,
    concrete,
    elastic_modulus,
)
from .reinforcement import (
    D500L,
    D500N,
    R250N,
    Ductility,
    Reinforcement,
    reinforcement,
)
from .steel import SteelGrade, describe_grades, grade_names, steel

__all__ = [
    "steel",
    "SteelGrade",
    "grade_names",
    "describe_grades",
    # concrete
    "Concrete",
    "concrete",
    "elastic_modulus",
    "STANDARD_GRADES",
    "EPSILON_CU",
    "C25",
    "C32",
    "C40",
    "C50",
    # reinforcement
    "Reinforcement",
    "reinforcement",
    "Ductility",
    "D500N",
    "D500L",
    "R250N",
    # bar catalogue
    "bar_area",
    "layer_area",
    "bars_for_area",
    "spacing_for_area",
    "options_for_area",
    "describe_options",
    "BarArrangement",
    "DEFORMED_DIAMETERS",
    "PLAIN_DIAMETERS",
    "FITMENT_DIAMETERS",
]
