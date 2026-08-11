"""L2 -- sections. Geometry and section properties.

Imports from: core, materials.
"""

from .bar_layout import BarLayout, layer_layout, max_bars_in_width
from .primitives import (
    Band,
    SectionGeometry,
    from_bands,
    inverted_tee,
    rectangle,
    tee,
)
from .properties import (
    TransformedProperties,
    cracked_properties,
    cracking_moment,
    modular_ratio,
    uncracked_properties,
)
from .rc_section import Fitment, RCSection, RebarLayer, rc_beam, rc_tee

__all__ = [
    # primitives
    "Band",
    "SectionGeometry",
    "rectangle",
    "tee",
    "inverted_tee",
    "from_bands",
    # rc sections
    "RCSection",
    "RebarLayer",
    "Fitment",
    "rc_beam",
    "rc_tee",
    # properties
    "TransformedProperties",
    "modular_ratio",
    "uncracked_properties",
    "cracked_properties",
    "cracking_moment",
    # bar layout
    "BarLayout",
    "layer_layout",
    "max_bars_in_width",
]
