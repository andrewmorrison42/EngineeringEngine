"""Concrete material properties to AS 3600 and AS 5100.5.

This is the "reference data" layer in the ASET sense: values that are looked up
rather than derived, held in a form that is immediately queryable and ready to
be consumed by the next step. The user asks for a grade and gets an object that
answers every question the design layer will put to it.

    >>> c = concrete(40)
    >>> c.Ec, c.fctf, c.alpha2, c.gamma
    (32800.0, 3.79..., 0.79, 0.87 -> clipped 0.85)

[UNITS] N, mm, MPa throughout, except `density` which stays kg/m^3 because
        that is the unit AS 3600 Cl 3.1.2 uses. See core/units.py.

[VECTOR] EVERY numeric value in this module is transcribed from a printed
         standard and is UNVERIFIED. Check each against the standard before
         issuing any calculation that depends on it. The tabulated values in
         _TABLE_3_1_2 and the coefficients in the property expressions are the
         highest-consequence numbers in the package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.basis import AS3600_2018, AS5100_5_2017, ClauseRef, Standard
from ..core.envelope import Envelope
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from ..core.units import U_DENSITY, U_STRESS
from . import _data

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.A_TABULATED,
        component=ASETComponent.REFERENCE_DATA,
    ),
    description="Concrete grade properties to AS 3600 Table 3.1.2 and Section 3.1",
    envelope_summary="20 <= f'c <= 100 MPa (AS 3600); 25 <= f'c <= 100 MPa (AS 5100.5)",
)


# ---------------------------------------------------------------------------
# [BASIS]  AS 3600:2018 Table 3.1.2 -- properties of standard concrete grades.
#
# The table itself lives in materials/data/concrete_grades.json, not here.
# ASET component 1 calls for reference data in a text format that can be
# loaded and queried in one or two calls -- and, more importantly, it puts the
# numbers somewhere an engineer can check and sign off without reading Python.
# See materials/_data.py.
#
# [VECTOR] UNVERIFIED. Check every row in the data file against the standard.
#
# Columns:  f'c   -- characteristic compressive strength at 28 days (MPa)
#           fcmi  -- mean in-situ compressive strength at 28 days (MPa)
#           fcm   -- mean compressive (cylinder) strength at 28 days (MPa)
#           Ec    -- mean modulus of elasticity at 28 days (MPa)
#
# Ec here is the TABULATED value, which assumes density 2400 kg/m^3. For any
# other density use the Cl 3.1.2 expression -- see `elastic_modulus`.
# ---------------------------------------------------------------------------
_TABLE_3_1_2: dict[int, tuple[float, float, float]] = {
    int(row["fc"]): (float(row["fcmi"]), float(row["fcm"]), float(row["Ec"]))
    for row in _data.load("concrete_grades.json")["grades"]
}

STANDARD_GRADES: tuple[int, ...] = tuple(sorted(_TABLE_3_1_2))

# [BASIS]  AS 3600:2018 Cl 1.1.2 -- range of application of the standard.
# [VECTOR] UNVERIFIED.
FC_MIN_AS3600 = 20.0
FC_MAX_AS3600 = 100.0

# [BASIS]  AS 5100.5:2017 -- range of application.
# [VECTOR] UNVERIFIED and specifically UNCONFIRMED. AS 5100.5 sets a higher
#          minimum grade than AS 3600 for bridgeworks; confirm the actual lower
#          bound and any exposure-dependent minimum before relying on this.
FC_MIN_AS5100 = 25.0
FC_MAX_AS5100 = 100.0

# [BASIS]  AS 3600:2018 Cl 3.1.4 -- ultimate compressive strain of concrete.
# [VECTOR] UNVERIFIED.
EPSILON_CU = 0.003

# [BASIS]  Normal-weight concrete density. AS 3600 Cl 3.1.3 permits 2400 kg/m^3
#          for normal-weight concrete in the absence of test data.
# [VECTOR] UNVERIFIED.
DENSITY_NORMAL = 2400.0


@dataclass(frozen=True)
class Concrete:
    """Concrete of a given characteristic strength, with derived properties.

    Construct via :func:`concrete` rather than directly -- the factory applies
    the envelope check and resolves tabulated versus computed properties.

    [UNITS] All stresses MPa, density kg/m^3, strains dimensionless.
    """

    fc: float
    """f'c -- characteristic compressive cylinder strength at 28 days (MPa)."""

    density: float = DENSITY_NORMAL
    """rho -- density (kg/m^3). Affects Ec only."""

    standard: Standard = AS3600_2018
    """Which standard's range of application was applied."""

    fcmi: float = 0.0
    """Mean in-situ compressive strength at 28 days (MPa)."""

    fcm: float = 0.0
    """Mean compressive cylinder strength at 28 days (MPa)."""

    Ec: float = 0.0
    """Mean modulus of elasticity at 28 days (MPa)."""

    ec_source: str = "table"
    """Where Ec came from: ``"table"`` (Table 3.1.2) or ``"formula"`` (Cl 3.1.2)."""

    envelope: Envelope = field(default_factory=Envelope, repr=False)

    # -- tensile strength ----------------------------------------------------

    @property
    def fct(self) -> float:
        """f'ct -- characteristic uniaxial (direct) tensile strength (MPa).

        [BASIS]  AS 3600:2018 Cl 3.1.1.3
        [VECTOR] UNVERIFIED -- coefficient 0.36.
        """
        return 0.36 * math.sqrt(self.fc)

    @property
    def fctf(self) -> float:
        """f'ct.f -- characteristic flexural tensile strength (MPa).

        Governs cracking moment, and through it the Cl 8.1.6.1 minimum
        reinforcement requirement.

        [BASIS]  AS 3600:2018 Cl 3.1.1.3
        [VECTOR] UNVERIFIED -- coefficient 0.6.
        """
        return 0.6 * math.sqrt(self.fc)

    # -- stress block parameters ---------------------------------------------
    #
    # These live on the material rather than in the design layer because they
    # are functions of f'c alone, and because AS 3600:2018 and AS 5100.5:2017
    # use the same expressions -- putting them here stops the two design
    # packages each carrying their own copy and drifting apart.

    @property
    def alpha2(self) -> float:
        """alpha_2 -- ratio of the uniform stress block intensity to f'c.

        [BASIS]  AS 3600:2018 Cl 8.1.3: alpha_2 = 0.85 - 0.0015.f'c >= 0.67.
        """
        return _clip(0.85 - 0.0015 * self.fc, 0.67, 1.0)

    @property
    def gamma(self) -> float:
        """gamma -- ratio of the stress block depth to the neutral axis depth.

        [BASIS]  AS 3600:2018 Cl 8.1.3: gamma = 0.97 - 0.0025.f'c,
                 bounded 0.67 <= gamma <= 0.85.
        """
        return _clip(0.97 - 0.0025 * self.fc, 0.67, 0.85)

    @property
    def epsilon_cu(self) -> float:
        """Ultimate compressive strain at the extreme compression fibre."""
        return EPSILON_CU

    @property
    def sqrt_fc(self) -> float:
        """sqrt(f'c), the form that appears throughout the shear provisions."""
        return math.sqrt(self.fc)

    def describe(self) -> list[str]:
        """Report-ready property lines."""
        return [
            f"f'c        = {self.fc:.0f} MPa",
            f"density    = {self.density:.0f} kg/m^3",
            f"Ec         = {self.Ec:.0f} MPa  (source: {self.ec_source})",
            f"f'ct       = {self.fct:.2f} MPa",
            f"f'ct.f     = {self.fctf:.2f} MPa",
            f"alpha_2    = {self.alpha2:.3f}",
            f"gamma      = {self.gamma:.3f}",
            f"epsilon_cu = {self.epsilon_cu:.4f}",
        ]


def _clip(value: float, lower: float, upper: float) -> float:
    """Clamp to an inclusive range. Named rather than inlined so the clause
    callouts above read as one idea per line."""
    return max(lower, min(upper, value))


def elastic_modulus(fcmi: float, density: float = DENSITY_NORMAL) -> float:
    """Mean elastic modulus from the Cl 3.1.2 expression.

    Basis
    -----
    AS 3600:2018 Cl 3.1.2::

        Ec = rho^1.5 * (0.043 * sqrt(fcmi))            for fcmi <= 40 MPa
        Ec = rho^1.5 * (0.024 * sqrt(fcmi) + 0.12)     for fcmi >  40 MPa

    The standard notes these are subject to a tolerance of roughly +/-20%,
    which is worth remembering before treating a deflection result as precise.

    [UNITS]  fcmi in MPa, density in kg/m^3, returns MPa.
    [VECTOR] UNVERIFIED -- both coefficients and the 40 MPa switch point.

    Parameters
    ----------
    fcmi:
        Mean in-situ compressive strength at 28 days (MPa).
    density:
        Concrete density (kg/m^3).

    Returns
    -------
    float
        Mean modulus of elasticity (MPa).
    """
    rho_term = density**1.5
    if fcmi <= 40.0:
        return rho_term * 0.043 * math.sqrt(fcmi)
    return rho_term * (0.024 * math.sqrt(fcmi) + 0.12)


def mean_in_situ_strength(fc: float) -> float:
    """fcmi from f'c, interpolating between the Table 3.1.2 rows.

    Non-standard grades are not tabulated. Linear interpolation between the
    bracketing standard grades is a defensible reading, but it is an
    interpretation rather than a code provision -- hence the explicit note.

    [BASIS]  AS 3600:2018 Table 3.1.2 (interpolated)
    [ASSUMPTION] Linear interpolation between tabulated grades. The standard
                 does not sanction this; prefer a standard grade.
    """
    if fc in _TABLE_3_1_2:
        return _TABLE_3_1_2[fc][0]

    grades = STANDARD_GRADES
    if fc < grades[0] or fc > grades[-1]:
        # Outside the table: fall back on the mean-strength margin implied by
        # the lowest/highest rows rather than extrapolating a fitted curve.
        nearest = grades[0] if fc < grades[0] else grades[-1]
        margin = _TABLE_3_1_2[nearest][0] - nearest
        return fc + margin

    lo = max(g for g in grades if g < fc)
    hi = min(g for g in grades if g > fc)
    f = (fc - lo) / (hi - lo)
    return _TABLE_3_1_2[lo][0] + f * (_TABLE_3_1_2[hi][0] - _TABLE_3_1_2[lo][0])


def concrete(
    fc: float,
    density: float = DENSITY_NORMAL,
    standard: Standard = AS3600_2018,
    ec_method: str = "auto",
) -> Concrete:
    """Build a :class:`Concrete` for a given characteristic strength.

    Basis
    -----
    AS 3600:2018 Table 3.1.2 (tabulated properties), Cl 3.1.2 (elastic modulus),
    Cl 1.1.2 (range of application).

    Envelope
    --------
    20 MPa <= f'c <= 100 MPa for AS 3600:2018.
    25 MPa <= f'c <= 100 MPa for AS 5100.5:2017 (UNCONFIRMED -- see FC_MIN_AS5100).
    1800 kg/m^3 <= density <= 2800 kg/m^3, an implementation restriction:
    outside this the Cl 3.1.2 expression is not calibrated.

    [UNITS] fc in MPa, density in kg/m^3.

    Parameters
    ----------
    fc:
        Characteristic compressive cylinder strength f'c (MPa).
    density:
        Density (kg/m^3). Defaults to 2400 for normal-weight concrete.
    standard:
        AS3600_2018 or AS5100_5_2017. Selects the range-of-application check
        only; the derived properties are identical between the two.
    ec_method:
        ``"table"``  -- use the tabulated Table 3.1.2 value (standard grades only)
        ``"formula"``-- always use the Cl 3.1.2 expression
        ``"auto"``   -- table for standard grades at normal density, else formula

    Returns
    -------
    Concrete

    Raises
    ------
    OutsideEnvelope
        If f'c or density falls outside the validity envelope.
    """
    env = Envelope(name=f"Concrete properties ({standard})")

    # [ENVELOPE] Range of application of the standard. Fail closed -- an
    #            out-of-range f'c makes every downstream property meaningless,
    #            not merely approximate.
    if standard is AS5100_5_2017:
        lo, hi = FC_MIN_AS5100, FC_MAX_AS5100
        ref = ClauseRef(AS5100_5_2017, "1.1", note="Range of application")
    else:
        lo, hi = FC_MIN_AS3600, FC_MAX_AS3600
        ref = ClauseRef(AS3600_2018, "1.1.2", note="Range of application")

    env.add("f'c", fc, lower=lo, upper=hi, unit=U_STRESS, basis=ref)
    env.add(
        "density",
        density,
        lower=1800.0,
        upper=2800.0,
        unit=U_DENSITY,
        reason="Cl 3.1.2 elastic modulus expression is not calibrated outside this range",
    )
    env.require()

    fcmi = mean_in_situ_strength(fc)
    is_standard_grade = int(fc) in _TABLE_3_1_2 and float(fc).is_integer()
    is_normal_density = abs(density - DENSITY_NORMAL) < 1e-9

    # [ASSUMPTION] The tabulated Ec assumes 2400 kg/m^3, so a non-default
    #              density must go through the formula or the result silently
    #              ignores the density the caller asked for.
    if ec_method == "table" or (ec_method == "auto" and is_standard_grade and is_normal_density):
        if not is_standard_grade:
            raise ValueError(
                f"ec_method='table' requires a standard grade "
                f"{STANDARD_GRADES}, got f'c = {fc}"
            )
        fcmi, fcm, Ec = _TABLE_3_1_2[int(fc)]
        source = "table"
    else:
        fcm = fcmi + 6.0  # rough, only used for reporting; see note below
        Ec = elastic_modulus(fcmi, density)
        source = "formula"

    return Concrete(
        fc=float(fc),
        density=float(density),
        standard=standard,
        fcmi=fcmi,
        fcm=fcm,
        Ec=Ec,
        ec_source=source,
        envelope=env,
    )


# Convenience handles for the grades that come up constantly. These are cheap
# to construct, so they are functions rather than module-level singletons --
# a frozen dataclass shared across jobs is an easy way to get a surprise.
def C25() -> Concrete:  # noqa: N802 -- grade names are conventional, not classes
    """Grade 25 normal-weight concrete."""
    return concrete(25)


def C32() -> Concrete:  # noqa: N802
    """Grade 32 normal-weight concrete."""
    return concrete(32)


def C40() -> Concrete:  # noqa: N802
    """Grade 40 normal-weight concrete."""
    return concrete(40)


def C50() -> Concrete:  # noqa: N802
    """Grade 50 normal-weight concrete."""
    return concrete(50)
