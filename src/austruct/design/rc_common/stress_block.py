"""Rectangular stress block mechanics, shared by AS 3600 and AS 5100.5.

Both standards idealise the concrete compressive stress distribution the same
way: a uniform stress ``alpha_2 . f'c`` acting over a depth ``gamma . k_u . d``
from the extreme compression fibre. The parameters ``alpha_2`` and ``gamma``
live on the :class:`~austruct.materials.concrete.Concrete` object because they
are functions of f'c alone.

Because the section geometry is banded (see ``sections/primitives.py``), the
concrete force and its line of action come out of the same two integrals for a
rectangle, a tee, or any stepped shape. That is what stops "support tee beams"
from meaning "rewrite the flexure module".

[UNITS] mm, N, MPa.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...materials.concrete import Concrete
from ...sections.primitives import SectionGeometry


@dataclass(frozen=True)
class ConcreteBlock:
    """The concrete compressive resultant for a given neutral axis depth.

    Attributes
    ----------
    dn:
        Neutral axis depth from the extreme compression fibre (mm).
    block_depth:
        Depth of the equivalent uniform stress block, ``gamma . dn`` (mm).
    area:
        Concrete area within the block (mm^2).
    force:
        Compressive resultant (N, positive in compression).
    centroid:
        Depth to the line of action of ``force`` (mm).
    """

    dn: float
    block_depth: float
    area: float
    force: float
    centroid: float


def concrete_block(
    geometry: SectionGeometry, concrete: Concrete, dn: float
) -> ConcreteBlock:
    """Concrete compressive resultant for a trial neutral axis depth.

    Basis
    -----
    AS 3600:2018 Cl 8.1.3 (and the equivalent provision in AS 5100.5):
    uniform stress ``alpha_2 . f'c`` over a depth ``gamma . k_u . d``, with
    ``alpha_2`` and ``gamma`` from the concrete grade.

    [UNITS]  dn in mm, returns force in N.
    [ASSUMPTION] The stress block is truncated at the section soffit when
                 ``gamma . dn`` exceeds the overall depth. That situation means
                 the section is far into over-reinforced territory; the flexure
                 solver flags it separately rather than relying on this clamp.

    Parameters
    ----------
    geometry:
        Section outline.
    concrete:
        Concrete material, supplying ``alpha_2``, ``gamma`` and ``f'c``.
    dn:
        Trial neutral axis depth (mm).

    Returns
    -------
    ConcreteBlock
    """
    block_depth = min(concrete.gamma * dn, geometry.D)
    area = geometry.area_above(block_depth)
    force = concrete.alpha2 * concrete.fc * area
    centroid = geometry.centroid_above(block_depth)
    return ConcreteBlock(
        dn=dn,
        block_depth=block_depth,
        area=area,
        force=force,
        centroid=centroid,
    )


def steel_strain(depth: float, dn: float, epsilon_cu: float) -> float:
    """Strain in reinforcement at ``depth``, for a neutral axis at ``dn``.

    Basis
    -----
    AS 3600:2018 Cl 8.1.2 -- plane sections remain plane, with the extreme
    compression fibre at the ultimate concrete strain.

    [UNITS] mm in, dimensionless out.

    Returns
    -------
    float
        Strain, TENSION POSITIVE. Reinforcement above the neutral axis returns
        a negative (compressive) strain.
    """
    if dn <= 0:
        # Degenerate trial: the whole section is in tension. Return a large
        # tensile strain so the equilibrium residual points the solver the
        # right way rather than dividing by zero.
        return epsilon_cu * 1e6
    return epsilon_cu * (depth - dn) / dn
