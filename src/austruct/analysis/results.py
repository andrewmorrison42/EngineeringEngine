"""Analysis results -- diagrams, extrema and reactions.

A :class:`BeamResults` is what the design layer consumes. It holds sampled
diagrams plus the machinery to interrogate them, and converts to the standard
:class:`~austruct.core.contract.CalcResult` so an analysis can be reported with
the same template as a design check.

[UNITS] Positions mm, shear N, moment N.mm, deflection mm, rotation radians.

Sign convention as stated in ``loading.py``: downward loads and deflections
positive, sagging moments positive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.basis import FIRST_PRINCIPLES, Basis, ClauseRef
from ..core.contract import CalcResult, Value
from ..core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ..core.registry import REGISTRY
from ..core.units import (
    U_ANGLE,
    U_FORCE,
    U_LENGTH,
    U_MOMENT,
    kN,
    kNm,
)

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.DEMAND,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Beam analysis result container and diagram interrogation",
    envelope_summary="Linear elastic, small deflection, Euler-Bernoulli",
)


@dataclass(frozen=True)
class Reaction:
    """A support reaction.

    Attributes
    ----------
    position:
        Distance from the left end of the member (mm).
    force:
        Vertical reaction (N), POSITIVE UPWARD.
    moment:
        Restraint moment (N.mm). Zero at pinned and roller supports.
    """

    position: float
    force: float
    moment: float = 0.0

    def describe(self) -> str:
        base = f"x = {self.position / 1000:7.3f} m   V = {self.force / kN:10.2f} kN"
        if abs(self.moment) > 1e-6:
            return base + f"   M = {self.moment / kNm:10.2f} kN.m"
        return base


@dataclass
class BeamResults:
    """Sampled diagrams and extrema from a beam analysis.

    Diagrams are sampled at the positions in :attr:`x`. Where a diagram is
    discontinuous -- shear at a point load, moment at an applied moment -- the
    sampling includes a pair of points either side of the discontinuity, so
    ``max``/``min`` capture the true peak rather than a value interpolated
    across the jump.
    """

    x: np.ndarray
    shear: np.ndarray
    moment: np.ndarray
    deflection: np.ndarray
    rotation: np.ndarray
    reactions: list[Reaction] = field(default_factory=list)
    length: float = 0.0
    EI: float = 0.0
    beam_name: str = ""
    messages: list[str] = field(default_factory=list)

    # -- extrema --------------------------------------------------------------

    @property
    def max_moment(self) -> float:
        """Largest sagging moment (N.mm). Zero if the beam is never in sagging."""
        return float(max(self.moment.max(), 0.0))

    @property
    def min_moment(self) -> float:
        """Largest hogging moment, returned NEGATIVE (N.mm)."""
        return float(min(self.moment.min(), 0.0))

    @property
    def max_moment_position(self) -> float:
        return float(self.x[int(np.argmax(self.moment))])

    @property
    def min_moment_position(self) -> float:
        return float(self.x[int(np.argmin(self.moment))])

    @property
    def design_moment(self) -> float:
        """Largest moment magnitude in either direction (N.mm, unsigned).

        The number a flexural capacity is compared against when the section is
        symmetric. For an asymmetric section check sagging and hogging
        separately using :attr:`max_moment` and :attr:`min_moment`.
        """
        return float(max(abs(self.max_moment), abs(self.min_moment)))

    @property
    def max_shear(self) -> float:
        """Largest shear magnitude anywhere on the member (N, unsigned)."""
        return float(np.abs(self.shear).max())

    @property
    def max_shear_position(self) -> float:
        return float(self.x[int(np.argmax(np.abs(self.shear)))])

    @property
    def max_deflection(self) -> float:
        """Largest downward deflection (mm). Negative if the beam only lifts."""
        return float(self.deflection.max())

    @property
    def max_deflection_position(self) -> float:
        return float(self.x[int(np.argmax(self.deflection))])

    @property
    def max_deflection_magnitude(self) -> float:
        """Largest deflection in either direction (mm, unsigned)."""
        return float(np.abs(self.deflection).max())

    @property
    def total_reaction(self) -> float:
        """Sum of vertical reactions (N, upward positive).

        Compare against the total applied load as an equilibrium check --
        :meth:`equilibrium_error` does this for you.
        """
        return sum(r.force for r in self.reactions)

    # -- interrogation --------------------------------------------------------

    def moment_at(self, position: float) -> float:
        """Bending moment at a position (N.mm), linearly interpolated.

        [ASSUMPTION] Interpolation across a discontinuity returns a value
                     between the two sides. Ask for the position of interest
                     directly rather than near a point load.
        """
        return float(np.interp(position, self.x, self.moment))

    def shear_at(self, position: float) -> float:
        """Shear force at a position (N), linearly interpolated."""
        return float(np.interp(position, self.x, self.shear))

    def deflection_at(self, position: float) -> float:
        """Deflection at a position (mm, downward positive)."""
        return float(np.interp(position, self.x, self.deflection))

    def shear_at_d_from_support(self, d: float) -> tuple[float, float]:
        """Shear at ``d`` from each support face, for the shear design check.

        Both AS 3600 and AS 5100.5 permit the design shear to be taken at a
        distance from the support face rather than at the support centreline,
        where the support introduces compression into the member. This returns
        the shear at that offset inboard of the first and last supports.

        [ASSUMPTION] Offset measured from the support CENTRELINE, not the
                     support face -- the beam model has no support width. Where
                     the bearing is wide this is conservative; adjust ``d`` by
                     half the bearing width if you want the face.

        Returns
        -------
        (shear_near_first_support, shear_near_last_support)
            Both unsigned magnitudes (N).
        """
        if not self.reactions:
            raise ValueError("No reactions available")
        first = min(r.position for r in self.reactions)
        last = max(r.position for r in self.reactions)
        left = abs(self.shear_at(min(first + d, self.length)))
        right = abs(self.shear_at(max(last - d, 0.0)))
        return left, right

    def equilibrium_error(self, applied_total: float) -> float:
        """Relative error between total reaction and total applied load.

        A sanity check on the solve, not on the model. Anything above about
        1e-9 means the solver has a problem.
        """
        if abs(applied_total) < 1e-12:
            return abs(self.total_reaction)
        return abs(self.total_reaction - applied_total) / abs(applied_total)

    # -- reporting ------------------------------------------------------------

    def summary(self) -> str:
        """Fixed-width summary of the governing actions."""
        lines = [
            f"Analysis results: {self.beam_name or 'beam'}",
            f"  Length            {self.length / 1000:.3f} m",
            "",
            "Reactions (positive upward):",
        ]
        lines.extend(f"  {r.describe()}" for r in self.reactions)
        lines.extend(
            [
                "",
                "Governing actions:",
                f"  M_max (sagging)   {self.max_moment / kNm:10.2f} kN.m "
                f"at x = {self.max_moment_position / 1000:.3f} m",
                f"  M_min (hogging)   {self.min_moment / kNm:10.2f} kN.m "
                f"at x = {self.min_moment_position / 1000:.3f} m",
                f"  V_max             {self.max_shear / kN:10.2f} kN "
                f"at x = {self.max_shear_position / 1000:.3f} m",
                f"  Deflection max    {self.max_deflection:10.2f} mm "
                f"at x = {self.max_deflection_position / 1000:.3f} m",
            ]
        )
        if self.max_deflection_magnitude > 1e-9 and self.length > 0:
            ratio = self.length / self.max_deflection_magnitude
            lines.append(f"  Span/deflection   L/{ratio:.0f}")
        if self.messages:
            lines.append("")
            lines.extend(f"  NOTE: {m}" for m in self.messages)
        return "\n".join(lines)

    def to_table(self) -> dict[str, list[float]]:
        """Diagrams as plain lists in DISPLAY units, for a DataFrame.

        ``pandas.DataFrame(results.to_table())`` works without this package
        depending on pandas. Display units because a notebook table of moments
        in N.mm is unreadable.

        [UNITS] x in m, shear in kN, moment in kN.m, deflection in mm.
        """
        return {
            "x_m": (self.x / 1000.0).tolist(),
            "shear_kN": (self.shear / kN).tolist(),
            "moment_kNm": (self.moment / kNm).tolist(),
            "deflection_mm": self.deflection.tolist(),
        }

    def _repr_markdown_(self) -> str:
        """Rich display in a Jupyter notebook."""
        return f"```\n{self.summary()}\n```"

    def to_calc_result(self) -> CalcResult:
        """Express the analysis as a standard contract result.

        Lets an analysis be reported through the same template as a design
        check, and serialised for a golden vector, without a special case.
        """
        basis = Basis()
        basis.add(
            ClauseRef(
                FIRST_PRINCIPLES,
                note="Euler-Bernoulli beam theory, linear elastic, direct stiffness method",
            )
        )

        result = CalcResult(
            name=f"Beam analysis -- {self.beam_name or 'beam'}",
            provenance=PROVENANCE,
            basis=basis,
        )
        result.add_input(
            "L", Value(self.length, U_LENGTH, "L", "Member length", "m", 1000.0)
        )
        result.add_input("EI", Value(self.EI, "N.mm^2", "EI", "Flexural rigidity"))

        result.add_output(
            "M_max",
            Value(self.max_moment, U_MOMENT, "M*_sag", "Maximum sagging moment", "kN.m", kNm),
        )
        result.add_output(
            "M_min",
            Value(self.min_moment, U_MOMENT, "M*_hog", "Maximum hogging moment", "kN.m", kNm),
        )
        result.add_output(
            "V_max",
            Value(self.max_shear, U_FORCE, "V*", "Maximum shear force", "kN", kN),
        )
        result.add_output(
            "delta_max",
            Value(self.max_deflection, U_LENGTH, "delta", "Maximum deflection"),
        )
        result.add_intermediate(
            "theta_max",
            Value(float(np.abs(self.rotation).max()), U_ANGLE, "theta", "Maximum rotation"),
        )
        for i, r in enumerate(self.reactions, start=1):
            result.add_output(
                f"R{i}",
                Value(r.force, U_FORCE, f"R_{i}", f"Reaction at x = {r.position:.0f} mm",
                      "kN", kN),
            )
            if abs(r.moment) > 1e-6:
                result.add_output(
                    f"M_R{i}",
                    Value(r.moment, U_MOMENT, f"M_{i}",
                          f"Restraint moment at x = {r.position:.0f} mm", "kN.m", kNm),
                )
        for m in self.messages:
            result.note(m)
        return result
