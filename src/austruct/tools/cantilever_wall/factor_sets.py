"""``FactorSet`` -- factors are data, not code.

Every verification framework this tool supports is one YAML file in
``factors/``, validated into a :class:`FactorSet`. Adding a framework a
client specifies is editing a config file, not touching the checks or the
pressure methods -- :func:`~austruct.tools.cantilever_wall.checks` and
:mod:`~austruct.tools.cantilever_wall.pressure` take a resolved
``FactorSet`` and never know or care which framework it came from.

[VECTOR] The FILES in ``factors/`` are the numbers to check against the
printed standard -- this module only loads and validates their shape.
"""

from __future__ import annotations

from ..contracts.base import ToolkitModel
from . import _data

KNOWN_FRAMEWORKS: tuple[str, ...] = ("as4678_class_b",)
"""Every framework with a YAML file in ``factors/``. Extend this tuple and
add the file -- nothing else needs to change to add a framework."""


class MaterialFactors(ToolkitModel):
    phi_ug_factor: float
    """Applied to tan(phi): tan(phi_design) = phi_ug_factor * tan(phi_char)."""
    cohesion_factor: float
    """Applied directly to cohesion: c_design = cohesion_factor * c_char."""


class ActionFactors(ToolkitModel):
    destabilising: float
    stabilising: float


class SlidingFactors(ToolkitModel):
    friction_reduction: float
    """Additional geotechnical reduction on friction resistance, compounding
    with ``MaterialFactors.phi_ug_factor``."""


class BearingFactors(ToolkitModel):
    geotechnical_reduction: float
    """phi_g on the ultimate bearing capacity."""


class EccentricityFactors(ToolkitModel):
    max_e_over_b: float


class FactorSet(ToolkitModel):
    """One verification framework's factors, loaded from a YAML file."""

    name: str
    standard: str
    status: str = "UNVERIFIED"
    checked_by: str | None = None
    checked_on: str | None = None
    material: MaterialFactors
    actions: ActionFactors
    sliding: SlidingFactors
    bearing: BearingFactors
    eccentricity: EccentricityFactors


def load_factor_set(framework: str) -> FactorSet:
    """Load and validate a factor set by name, e.g. ``"as4678_class_b"``.

    Parameters
    ----------
    framework:
        One of :data:`KNOWN_FRAMEWORKS`. This is the ``framework`` argument
        threaded through from :func:`~austruct.tools.cantilever_wall.api.analyse`.

    Raises
    ------
    ValueError
        If ``framework`` is not a known name.
    """
    if framework not in KNOWN_FRAMEWORKS:
        raise ValueError(
            f"Unknown framework {framework!r}. Known: {', '.join(KNOWN_FRAMEWORKS)}"
        )
    raw = _data.load_yaml(f"{framework}.yaml")
    return FactorSet.model_validate(raw)
