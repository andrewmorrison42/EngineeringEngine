"""Strain-compatibility solution for the ultimate flexural capacity of an RC
section.

This is the shared mechanical core. It contains NO clause numbers and NO
capacity reduction factors -- only equilibrium, compatibility and the
constitutive idealisations that AS 3600 and AS 5100.5 share. The two design
packages wrap it with their own ``phi``, their own ductility limits and their
own minimum-strength rules.

Method
------
Solve for the neutral axis depth ``dn`` such that the section carries no net
axial force::

    C_concrete(dn)  -  sum( A_si . sigma_si(dn) )  =  0

by bisection on ``dn`` in ``(0, D]``. Bisection rather than Newton because the
residual is piecewise-smooth -- both the steel constitutive law and the banded
geometry introduce kinks -- and a bracketed method cannot run away from them.
The residual is monotonic increasing in ``dn``, so the bracket is guaranteed.

Then take moments about the concrete compressive resultant, where the concrete
force contributes nothing::

    M_uo = sum( T_i . (y_i - y_c) )

which is valid precisely because the net axial force is zero.

[UNITS] mm, N, MPa, N.mm.

Sign convention: depths measured down from the extreme compression fibre,
tension positive in steel, sagging moments positive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.exceptions import ConvergenceError, ModelError
from ...sections.rc_section import RCSection, RebarLayer
from .stress_block import ConcreteBlock, concrete_block, steel_strain


@dataclass(frozen=True)
class LayerForce:
    """The force in one reinforcement layer at the ultimate limit state."""

    layer: RebarLayer
    strain: float
    """Tension positive."""

    stress: float
    """Tension positive (MPa), after the yield cap and any displaced-concrete
    correction."""

    force: float
    """Tension positive (N)."""

    yielded: bool

    @property
    def depth(self) -> float:
        return self.layer.depth


@dataclass
class FlexuralState:
    """The converged ultimate flexural state of a section.

    Attributes
    ----------
    dn:
        Neutral axis depth (mm).
    block:
        Concrete compressive resultant.
    layer_forces:
        Force in each reinforcement layer.
    Muo:
        Ultimate moment capacity without any capacity reduction factor (N.mm).
    d:
        Effective depth to the centroid of the TENSILE reinforcement, computed
        from the converged neutral axis rather than assumed (mm).
    d_o:
        Depth to the centroid of the outermost tensile layer (mm).
    ku:
        ``dn / d``.
    kuo:
        ``dn / d_o`` -- the ratio the ductility limit is written against.
    lever_arm:
        Distance from the concrete resultant to the tensile force resultant (mm).
    iterations:
        Bisection iterations used, for diagnostics.
    """

    dn: float
    block: ConcreteBlock
    layer_forces: list[LayerForce]
    Muo: float
    d: float
    d_o: float
    ku: float
    kuo: float
    lever_arm: float
    iterations: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def tensile_force(self) -> float:
        """Resultant tensile force in the reinforcement (N)."""
        return sum(lf.force for lf in self.layer_forces if lf.force > 0)

    @property
    def compressive_steel_force(self) -> float:
        """Resultant compressive force in the reinforcement (N, positive)."""
        return -sum(lf.force for lf in self.layer_forces if lf.force < 0)

    @property
    def all_tensile_steel_yielded(self) -> bool:
        """Whether every tensile layer has reached yield.

        A section where the tensile steel has not yielded at ultimate is
        over-reinforced and will fail without warning. Both standards address
        this through the ``k_uo`` limit rather than by checking yield directly,
        but the flag is useful diagnostically.
        """
        tensile = [lf for lf in self.layer_forces if lf.force > 0]
        return bool(tensile) and all(lf.yielded for lf in tensile)

    @property
    def Ast(self) -> float:  # noqa: N802
        """Total area of reinforcement in tension at ultimate (mm^2)."""
        return sum(lf.layer.area for lf in self.layer_forces if lf.strain > 0)

    @property
    def Asc(self) -> float:  # noqa: N802
        """Total area of reinforcement in compression at ultimate (mm^2)."""
        return sum(lf.layer.area for lf in self.layer_forces if lf.strain <= 0)


def _layer_forces(
    section: RCSection,
    dn: float,
    deduct_displaced_concrete: bool,
) -> list[LayerForce]:
    """Force in every reinforcement layer for a trial neutral axis depth."""
    concrete = section.concrete
    out: list[LayerForce] = []

    for layer in section.layers:
        strain = steel_strain(layer.depth, dn, concrete.epsilon_cu)
        stress = layer.material.stress(strain)
        yielded = abs(strain) >= layer.material.epsilon_sy

        # [ASSUMPTION] Reinforcement inside the concrete stress block displaces
        #              concrete that the block has already counted as carrying
        #              alpha_2.f'c. Deducting it avoids double-counting that
        #              area. Common Australian practice; switch off via the
        #              flag if the office convention is to ignore it.
        if deduct_displaced_concrete and stress < 0:
            block_depth = min(concrete.gamma * dn, section.geometry.D)
            if layer.depth <= block_depth:
                stress += concrete.alpha2 * concrete.fc
                stress = min(stress, 0.0)

        out.append(
            LayerForce(
                layer=layer,
                strain=strain,
                stress=stress,
                force=layer.area * stress,
                yielded=yielded,
            )
        )
    return out


def _axial_residual(
    section: RCSection, dn: float, deduct_displaced_concrete: bool
) -> float:
    """Net axial force for a trial neutral axis depth (N).

    Positive means too much compression -- the neutral axis is too deep.
    Monotonic increasing in ``dn``, which is what guarantees the bracket.

    [ASSUMPTION] The concrete force is COMPRESSION positive and the steel
                 forces are TENSION positive, so the two are subtracted. Adding
                 them would be dimensionally fine and physically meaningless --
                 the resulting solver finds no root for any ordinary beam.
    """
    block = concrete_block(section.geometry, section.concrete, dn)
    steel = _layer_forces(section, dn, deduct_displaced_concrete)
    return block.force - sum(lf.force for lf in steel)


def solve_flexural_state(
    section: RCSection,
    deduct_displaced_concrete: bool = True,
    tol: float = 1e-9,
    max_iter: int = 200,
) -> FlexuralState:
    """Solve the ultimate flexural state of a reinforced concrete section.

    Basis
    -----
    Equilibrium and strain compatibility, with the rectangular stress block and
    elastic-plastic steel idealisations common to AS 3600 Cl 8.1 and the
    equivalent AS 5100.5 provisions. No capacity reduction factor is applied --
    the returned ``Muo`` is the nominal capacity.

    Envelope
    --------
    Sagging bending with compression at the top of the section as supplied.
    Pure bending -- no axial force. Non-prestressed sections only.

    Parameters
    ----------
    section:
        The RC section. Must carry at least one reinforcement layer, and at
        least one of those layers must end up in tension.
    deduct_displaced_concrete:
        Whether to deduct ``alpha_2 . f'c`` from the stress in compression
        reinforcement lying inside the stress block. See the assumption note
        in :func:`_layer_forces`.
    tol:
        Convergence tolerance on the neutral axis depth, as a fraction of D.
    max_iter:
        Iteration budget.

    Returns
    -------
    FlexuralState

    Raises
    ------
    ModelError
        If the section has no reinforcement, or no reinforcement in tension.
    ConvergenceError
        If the bisection fails to converge or the root cannot be bracketed.

    Examples
    --------
    >>> section = rc_beam(300, 600, concrete(32), n_bars=4, diameter=24,
    ...                   fitment_spacing=200)
    >>> state = solve_flexural_state(section)
    >>> state.Muo / 1e6      # kN.m
    """
    if not section.layers:
        raise ModelError(
            "Section has no reinforcement. Plain concrete flexural capacity is "
            "outside the scope of this module."
        )

    D = section.geometry.D

    # [CHECK] Bracket the root. The residual is negative for a vanishing
    #         neutral axis (all steel in tension, no concrete force) and
    #         positive for a full-depth one (large concrete force). If that is
    #         not so, the section is not a normal flexural member.
    lo, hi = 1e-6 * D, D
    f_lo = _axial_residual(section, lo, deduct_displaced_concrete)
    f_hi = _axial_residual(section, hi, deduct_displaced_concrete)

    if f_lo > 0:
        raise ModelError(
            "Net compression at a vanishing neutral axis depth -- the section "
            "has no reinforcement in tension. Check that the section is "
            "oriented with the compression face at the top."
        )
    if f_hi < 0:
        raise ConvergenceError(
            "Cannot bracket the neutral axis: the section cannot develop "
            "equilibrium even with the whole depth in compression. This "
            "usually means an implausibly large reinforcement area.",
            last_value=hi,
        )

    # Counted explicitly rather than taken from the loop variable, because the
    # count is reported on the FlexuralState for diagnostics -- a solve that
    # needs an unusual number of iterations is worth noticing.
    iterations = 0
    converged = False
    while iterations < max_iter:
        iterations += 1
        mid = 0.5 * (lo + hi)
        f_mid = _axial_residual(section, mid, deduct_displaced_concrete)
        if f_mid > 0:
            hi = mid
        else:
            lo = mid
        if (hi - lo) < tol * D:
            converged = True
            break

    if not converged:
        raise ConvergenceError(
            f"Neutral axis did not converge in {max_iter} iterations",
            last_value=0.5 * (lo + hi),
            iterations=max_iter,
        )

    dn = 0.5 * (lo + hi)
    block = concrete_block(section.geometry, section.concrete, dn)
    forces = _layer_forces(section, dn, deduct_displaced_concrete)

    tensile = [lf for lf in forces if lf.strain > 0]
    if not tensile:
        raise ModelError(
            "No reinforcement in tension at the converged neutral axis; the "
            "section cannot develop a flexural capacity in this direction."
        )

    # -- moment about the concrete resultant ---------------------------------
    # Valid because the net axial force is zero, so the moment is independent
    # of the reference point; taking it here removes the concrete term.
    Muo = sum(lf.force * (lf.depth - block.centroid) for lf in forces)

    # -- effective depths, from the CONVERGED neutral axis --------------------
    ast_total = sum(lf.layer.area for lf in tensile)
    d = sum(lf.layer.area * lf.depth for lf in tensile) / ast_total
    d_o = max(lf.depth for lf in tensile)

    tension_resultant = sum(lf.force for lf in tensile)
    if tension_resultant > 0:
        y_t = sum(lf.force * lf.depth for lf in tensile) / tension_resultant
        lever_arm = y_t - block.centroid
    else:  # pragma: no cover -- guarded by the check above
        lever_arm = 0.0

    state = FlexuralState(
        dn=dn,
        block=block,
        layer_forces=forces,
        Muo=Muo,
        d=d,
        d_o=d_o,
        ku=dn / d if d > 0 else 0.0,
        kuo=dn / d_o if d_o > 0 else 0.0,
        lever_arm=lever_arm,
        iterations=iterations,
    )

    if block.block_depth >= section.geometry.D - 1e-9:
        state.notes.append(
            "The stress block extends to the full section depth. The section is "
            "grossly over-reinforced and the result should not be relied on."
        )
    if not state.all_tensile_steel_yielded:
        state.notes.append(
            "Not all tensile reinforcement has yielded at ultimate -- the "
            "section is over-reinforced and will fail without warning. Check "
            "the ductility limit."
        )

    return state
