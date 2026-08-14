"""AS 4100 design provisions (steel structures).

All code constants live in :mod:`.constants` -- that is the module to check
against the printed standard.

Read this before using the flexure module
-----------------------------------------
For reinforced concrete the section capacity is essentially the answer. For
steel it is not: a beam almost always fails by lateral-torsional buckling
before it reaches ``M_s``. So :func:`check_flexure` refuses to run unless the
segment is declared fully restrained, and :func:`check_member_flexure` is the
one to reach for otherwise.
"""

from . import constants
from .classification import (
    Compactness,
    PlateElement,
    SectionSlenderness,
    check_classification,
    classify,
    effective_modulus,
    plate_elements,
)
from .combined import (
    check_combined_member,
    check_combined_section,
    reduced_section_moment_capacity,
)
from .compression import (
    check_compression,
    compression_factor,
    form_factor,
    member_compression_capacity,
    modified_slenderness,
    section_compression_capacity,
)
from .flexure import (
    check_flexure,
    lightest_section,
    required_section_modulus,
    section_moment_capacity,
)
from .lateral_torsional import (
    BucklingState,
    alpha_m_from_diagram,
    alpha_m_from_moments,
    buckling_state,
    check_member_flexure,
    member_moment_capacity,
    reference_buckling_moment,
    slenderness_reduction,
)
from .restraints import (
    LoadHeight,
    Restraint,
    Segment,
    continuously_restrained,
    effective_length,
    fully_restrained,
    load_height_factor,
    segment,
    twist_factor,
)
from .shear import (
    check_shear,
    check_shear_and_moment,
    shear_capacity,
    web_area,
    web_slenderness,
)

__all__ = [
    "constants",
    # classification
    "Compactness",
    "PlateElement",
    "SectionSlenderness",
    "classify",
    "plate_elements",
    "effective_modulus",
    "check_classification",
    # flexure -- section capacity
    "section_moment_capacity",
    "check_flexure",
    "required_section_modulus",
    "lightest_section",
    # shear
    "shear_capacity",
    "check_shear",
    "check_shear_and_moment",
    "web_area",
    "web_slenderness",
    # restraints and effective length
    "Restraint",
    "LoadHeight",
    "Segment",
    "segment",
    "fully_restrained",
    "continuously_restrained",
    "effective_length",
    "twist_factor",
    "load_height_factor",
    # lateral-torsional buckling
    "BucklingState",
    "reference_buckling_moment",
    "slenderness_reduction",
    "alpha_m_from_moments",
    "alpha_m_from_diagram",
    "member_moment_capacity",
    "check_member_flexure",
    "buckling_state",
    # compression
    "form_factor",
    "modified_slenderness",
    "compression_factor",
    "section_compression_capacity",
    "member_compression_capacity",
    "check_compression",
    # combined actions
    "reduced_section_moment_capacity",
    "check_combined_section",
    "check_combined_member",
]
