"""Flexural design of reinforced concrete sections to AS 3600:2018 Section 8.1.

Public entry points
-------------------
:func:`moment_capacity`
    Nominal and design flexural capacity of a section, with the ductility and
    minimum-strength checks.
:func:`check_flexure`
    The same, plus the capacity check against a design moment ``M*``.
:func:`required_steel_area`
    Inverse problem -- the tensile steel area needed for a given ``M*``.

All return a :class:`~austruct.core.contract.CalcResult`, never a bare float.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] This module is UNVERIFIED. Every code constant it uses is centralised
         in ``constants.py`` and must be checked against the printed standard.
"""

from __future__ import annotations

from ...core.basis import Basis, ClauseRef
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import (
    U_AREA,
    U_LENGTH,
    U_MOMENT,
    U_NONE,
    U_STRESS,
    kNm,
)
from ...materials.reinforcement import Ductility
from ...sections.properties import cracking_moment
from ...sections.rc_section import RCSection, RebarLayer
from ..rc_common.strain_compat import FlexuralState, solve_flexural_state
from . import constants as C

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Ultimate flexural capacity of RC sections to AS 3600:2018 Section 8.1",
    envelope_summary=(
        "20 <= f'c <= 100 MPa; non-prestressed; pure bending, no axial force; "
        "compression at the top of the section as supplied"
    ),
)


def _build_envelope(section: RCSection) -> Envelope:
    """Validity envelope common to every entry point in this module."""
    env = Envelope(name="AS 3600 flexure")

    env.add(
        "f'c",
        section.concrete.fc,
        lower=20.0,
        upper=100.0,
        unit=U_STRESS,
        basis=ClauseRef(C.STANDARD, "1.1.2", note="Range of application"),
    )
    env.note("Non-prestressed reinforced concrete only. No axial force.")
    env.note(
        "Sagging bending with the compression face at the top of the section "
        "as supplied. Model hogging by inverting the section."
    )
    env.note(
        "Torsion, lateral instability of slender beams and the effects of "
        "sustained load are not considered."
    )
    return env


def _ductility_class(section: RCSection, state: FlexuralState) -> Ductility:
    """Governing ductility class of the TENSILE reinforcement.

    Where layers of different class are mixed, the lower class governs -- the
    capacity reduction factor cannot be better than the worst reinforcement
    relied on.
    """
    tensile = [lf.layer.material.ductility for lf in state.layer_forces if lf.strain > 0]
    return Ductility.L if Ductility.L in tensile else Ductility.N


def minimum_steel_area(section: RCSection, d: float) -> float:
    """(A_st)min for a RECTANGULAR section.

    Basis
    -----
    AS 3600:2018 Cl 8.1.6.1::

        (A_st / b.d)_min = 0.20 . (D/d)^2 . f'ct.f / f_sy

    [VECTOR] UNVERIFIED -- coefficient and form.
    [ENVELOPE] Rectangular sections only. For a tee or any other shape the
               clause gives a different expression, so this function refuses
               rather than returning a number that looks plausible. Use the
               ``M_uo >= 1.2 M_cr`` check instead, which is general.

    Parameters
    ----------
    section:
        The RC section.
    d:
        Effective depth (mm).

    Returns
    -------
    float
        Minimum tensile steel area (mm^2).
    """
    if len(section.geometry.bands) != 1:
        raise ValueError(
            "minimum_steel_area() implements the rectangular-section form of "
            "AS 3600 Cl 8.1.6.1 only. For a non-rectangular section use the "
            "M_uo >= 1.2 M_cr check, which check_flexure() applies generally."
        )

    b = section.geometry.b_top
    D = section.geometry.D
    fsy = section.layers[0].material.fsy if section.layers else 500.0
    return (
        C.MIN_STEEL_COEFFICIENT
        * (D / d) ** 2
        * (section.concrete.fctf / fsy)
        * b
        * d
    )


def moment_capacity(
    section: RCSection,
    deduct_displaced_concrete: bool = True,
) -> CalcResult:
    """Ultimate flexural capacity of a reinforced concrete section.

    Basis
    -----
    AS 3600:2018:

    - Cl 8.1.2 -- ultimate strength in bending, plane sections
    - Cl 8.1.3 -- rectangular stress block, ``alpha_2`` and ``gamma``
    - Cl 8.1.5 -- ductility limit ``k_uo <= 0.36``
    - Cl 8.1.6.1 -- minimum strength, ``M_uo >= 1.2 M_cr``
    - Table 2.2.2 -- capacity reduction factor as a function of ``k_uo``

    Envelope
    --------
    20 MPa <= f'c <= 100 MPa. Non-prestressed. Pure bending, no axial force.
    Compression at the top of the section as supplied.

    [UNITS] Returns moments in N.mm; the report displays them in kN.m.

    Parameters
    ----------
    section:
        The RC section to assess.
    deduct_displaced_concrete:
        Passed through to the strain-compatibility solver -- whether to deduct
        the concrete displaced by compression reinforcement.

    Returns
    -------
    CalcResult
        ``outputs["Muo"]``   nominal capacity (N.mm)
        ``outputs["phiMuo"]`` design capacity (N.mm)
        ``outputs["phi"]``    capacity reduction factor
        Checks: ductility ``k_uo <= 0.36``, minimum strength ``M_uo >= 1.2 M_cr``

    Examples
    --------
    >>> section = rc_beam(300, 600, concrete(32), n_bars=4, diameter=24,
    ...                   fitment_spacing=200)
    >>> res = moment_capacity(section)
    >>> res.get("phiMuo") / 1e6      # kN.m
    """
    env = _build_envelope(section)
    env.extend(section.concrete.envelope)
    env.require()

    basis = Basis()
    basis.add(C.CLAUSE_FLEXURE)
    basis.add(C.CLAUSE_STRESS_BLOCK)

    # -- mechanics: shared strain-compatibility solve ------------------------
    state = solve_flexural_state(
        section, deduct_displaced_concrete=deduct_displaced_concrete
    )

    result = CalcResult(
        name="Ultimate moment capacity -- AS 3600:2018 Cl 8.1",
        provenance=PROVENANCE,
        basis=basis,
        envelope=env,
    )

    # -- inputs, echoed verbatim with units ----------------------------------
    result.add_input("fc", Value(section.concrete.fc, U_STRESS, "f'c", "Concrete strength"))
    result.add_input("D", Value(section.geometry.D, U_LENGTH, "D", "Overall depth"))
    result.add_input("b", Value(section.geometry.b_top, U_LENGTH, "b", "Compression face width"))
    for i, layer in enumerate(sorted(section.layers, key=lambda x: x.depth), start=1):
        result.add_input(
            f"layer{i}",
            Value(layer.area, U_AREA, f"A_s{i}", f"{layer.designation} at d = {layer.depth:.0f} mm"),
        )

    # -- intermediates: the working a reviewer follows ------------------------
    result.add_intermediate(
        "alpha2", Value(section.concrete.alpha2, U_NONE, "alpha_2", "Stress block intensity")
    )
    result.add_intermediate(
        "gamma", Value(section.concrete.gamma, U_NONE, "gamma", "Stress block depth ratio")
    )
    result.add_intermediate("dn", Value(state.dn, U_LENGTH, "d_n", "Neutral axis depth"))
    result.add_intermediate(
        "block_depth", Value(state.block.block_depth, U_LENGTH, "gamma.d_n", "Stress block depth")
    )
    result.add_intermediate("d", Value(state.d, U_LENGTH, "d", "Effective depth"))
    result.add_intermediate(
        "do", Value(state.d_o, U_LENGTH, "d_o", "Depth to outermost tensile layer")
    )
    result.add_intermediate("ku", Value(state.ku, U_NONE, "k_u", "d_n / d"))
    result.add_intermediate("kuo", Value(state.kuo, U_NONE, "k_uo", "d_n / d_o"))
    result.add_intermediate("z", Value(state.lever_arm, U_LENGTH, "z", "Lever arm"))
    result.add_intermediate(
        "Cc", Value(state.block.force, "N", "C_c", "Concrete compressive force")
    )
    result.add_intermediate(
        "Ts", Value(state.tensile_force, "N", "T_s", "Tensile force in reinforcement")
    )
    result.add_intermediate("Ast", Value(state.Ast, U_AREA, "A_st", "Tensile steel area"))
    if state.Asc > 0:
        result.add_intermediate(
            "Asc", Value(state.Asc, U_AREA, "A_sc", "Compressive steel area")
        )

    # -- capacity reduction factor -------------------------------------------
    basis.add(C.CLAUSE_PHI)
    ductility = _ductility_class(section, state)
    phi = C.phi_flexure(state.kuo, ductility)
    result.add_output(
        "phi", Value(phi, U_NONE, "phi", f"Capacity reduction factor (Class {ductility.value})")
    )

    # -- capacities -----------------------------------------------------------
    result.add_output(
        "Muo", Value(state.Muo, U_MOMENT, "M_uo", "Nominal moment capacity", "kN.m", kNm)
    )
    result.add_output(
        "phiMuo",
        Value(phi * state.Muo, U_MOMENT, "phi.M_uo", "Design moment capacity", "kN.m", kNm),
    )

    # -- checks ---------------------------------------------------------------
    basis.add(C.CLAUSE_DUCTILITY)
    result.add_check(
        Check(
            label="Ductility, k_uo",
            actual=state.kuo,
            limit=C.KUO_LIMIT,
            operator="<=",
            unit=U_NONE,
            basis=C.CLAUSE_DUCTILITY,
        )
    )

    # [BASIS] Cl 8.1.6.1 -- minimum strength. Applied in the general
    #         M_uo >= 1.2 M_cr form so that it works for any section shape,
    #         not only rectangles.
    basis.add(C.CLAUSE_MIN_STEEL)
    try:
        mcr = cracking_moment(section)
        result.add_intermediate(
            "Mcr", Value(mcr, U_MOMENT, "M_cr", "Cracking moment", "kN.m", kNm)
        )
        result.add_check(
            Check(
                label="Minimum strength, M_uo >= 1.2 M_cr",
                actual=state.Muo,
                limit=C.MIN_STRENGTH_FACTOR * mcr,
                operator=">=",
                unit=U_MOMENT,
                basis=C.CLAUSE_MIN_STEEL,
                display_factor=kNm,
                display_unit="kN.m",
            )
        )
    except Exception as exc:  # pragma: no cover -- defensive
        result.note(
            f"Minimum strength check not performed: {exc}. Apply Cl 8.1.6.1 by hand."
        )

    for note in state.notes:
        result.note(note)
    if not state.all_tensile_steel_yielded:
        result.note(
            "Over-reinforced section: phi has been reduced by the k_uo term, but "
            "the ductility check above is the governing requirement."
        )

    return result


def check_flexure(
    section: RCSection,
    M_star: float,  # noqa: N803
    deduct_displaced_concrete: bool = True,
) -> CalcResult:
    """Check a section's flexural capacity against a design moment.

    Basis
    -----
    As :func:`moment_capacity`, plus the strength requirement
    ``M* <= phi.M_uo`` (AS 3600:2018 Cl 2.2.2).

    Parameters
    ----------
    section:
        The RC section.
    M_star:
        Design bending moment ``M*`` (N.mm), magnitude. Take it from
        :attr:`~austruct.analysis.results.BeamResults.design_moment` or from
        the relevant sagging/hogging extreme.

    Returns
    -------
    CalcResult
        As :func:`moment_capacity`, with the capacity check added and its
        utilisation governing.

    Examples
    --------
    >>> res = check_flexure(section, results.max_moment)
    >>> res.passed, res.utilisation
    """
    result = moment_capacity(section, deduct_displaced_concrete)
    result.name = "Flexural strength check -- AS 3600:2018 Cl 8.1"

    result.add_input(
        "Mstar", Value(abs(M_star), U_MOMENT, "M*", "Design bending moment", "kN.m", kNm)
    )
    result.add_check(
        Check(
            label="Flexural strength, M* <= phi.M_uo",
            actual=abs(M_star),
            limit=result.get("phiMuo"),
            operator="<=",
            unit=U_MOMENT,
            basis=ClauseRef(C.STANDARD, "2.2.2", note="Strength requirement"),
            display_factor=kNm,
            display_unit="kN.m",
        )
    )
    return result


def required_steel_area(
    section: RCSection,
    M_star: float,  # noqa: N803
    depth: float | None = None,
    tol: float = 1e-4,
    max_iter: int = 100,
) -> CalcResult:
    """Tensile steel area required to develop a design moment.

    Solves the inverse problem by bisection on ``A_st``, re-running the full
    strain-compatibility solve at each trial. Slower than a closed-form
    rearrangement, but it inherits every behaviour of the forward solution --
    tee sections, multiple layers, compression steel, the varying ``phi`` --
    with no separate set of assumptions to keep in step.

    Parameters
    ----------
    section:
        Section whose geometry and materials are fixed. Any EXISTING tensile
        layers are replaced by the single trial layer; compression layers above
        the gross centroid are retained.
    M_star:
        Design bending moment to develop (N.mm).
    depth:
        Depth to the trial reinforcement (mm). Defaults to the deepest existing
        layer, or ``0.9 D`` if the section has none.
    tol:
        Relative convergence tolerance on the steel area.

    Returns
    -------
    CalcResult
        The capacity check for the converged section, with the required area
        as ``outputs["Ast_req"]`` and a bar-arrangement note.

    Raises
    ------
    ValueError
        If the required area exceeds a practical upper bound, which means the
        section is too small for the moment and needs resizing rather than
        more steel.
    """
    M_star = abs(M_star)

    if depth is None:
        depth = (
            max(layer.depth for layer in section.layers)
            if section.layers
            else 0.9 * section.geometry.D
        )

    keep = tuple(
        layer for layer in section.layers if layer.depth < section.geometry.centroid
    )
    material = section.layers[0].material if section.layers else None

    def capacity_for(area: float) -> float:
        trial_layer = RebarLayer(
            area=area,
            depth=depth,
            material=material or RebarLayer(area=1, depth=1).material,
            label="trial",
        )
        trial = section.with_layers(keep + (trial_layer,))
        state = solve_flexural_state(trial)
        phi = C.phi_flexure(state.kuo, _ductility_class(trial, state))
        return phi * state.Muo

    # [ENVELOPE] Upper bound on the search. 4% of the gross area is already
    #            beyond anything buildable; hitting it means the section is
    #            undersized, which is a different decision from "add steel".
    lo = 1.0
    hi = 0.04 * section.geometry.area

    if capacity_for(hi) < M_star:
        raise ValueError(
            f"M* = {M_star / kNm:.1f} kN.m cannot be developed by this section "
            f"even at 4% reinforcement ratio (phi.M_uo = "
            f"{capacity_for(hi) / kNm:.1f} kN.m). Increase the section depth or "
            "the concrete grade."
        )

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if capacity_for(mid) < M_star:
            lo = mid
        else:
            hi = mid
        if (hi - lo) / max(hi, 1.0) < tol:
            break

    area_required = hi

    trial_layer = RebarLayer(
        area=area_required,
        depth=depth,
        material=material or RebarLayer(area=1, depth=1).material,
        label="required",
    )
    designed = section.with_layers(keep + (trial_layer,))

    result = check_flexure(designed, M_star)
    result.name = "Flexural design -- required tensile steel, AS 3600:2018"
    result.add_output(
        "Ast_req",
        Value(area_required, U_AREA, "A_st,req", f"Required tensile steel at d = {depth:.0f} mm"),
    )
    result.note(
        f"Required area solved by bisection on the full section capacity, "
        f"converged to within {tol:.1e} relative."
    )
    return result
