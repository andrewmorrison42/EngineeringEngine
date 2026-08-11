"""Closed-form solutions for standard beam cases.

Purpose
-------
These are NOT the product. They are the **verification** of the product.

The stiffness solver in ``solver.py`` is the general engine; these formulae are
the independent source the golden vectors compare it against. Keeping them in
the package rather than only in the tests means they are also available for a
quick sanity check at a console, and it means the comparison is between two
implementations that share no code beyond arithmetic.

Every formula here is standard textbook beam theory, so ``basis`` is
FIRST_PRINCIPLES rather than a code clause. They still need checking -- a
transcription error in a benchmark is worse than no benchmark, because it makes
a wrong solver look verified.

[VECTOR] UNVERIFIED. Each formula needs checking against a published table
         (Warner, Roark, or the AS 3600 commentary) and the check recording a
         named engineer and date.

Sign convention as elsewhere: downward loads and deflections positive, sagging
moments positive, reactions positive upward.

[UNITS] w in N/mm, P in N, L in mm, EI in N.mm^2. Moments N.mm, deflections mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ClosedFormResult:
    """Key results for a standard case.

    Attributes
    ----------
    R_left, R_right:
        Reactions (N, positive upward).
    M_left, M_right:
        Restraint moments at the ends (N.mm), in the sagging-positive
        convention -- a hogging restraint moment is negative.
    M_max:
        Maximum sagging moment (N.mm).
    M_max_position:
        Where it occurs (mm from the left end).
    deflection_max:
        Maximum deflection (mm, downward positive).
    deflection_max_position:
        Where it occurs (mm from the left end).
    """

    R_left: float = 0.0
    R_right: float = 0.0
    M_left: float = 0.0
    M_right: float = 0.0
    M_max: float = 0.0
    M_max_position: float = 0.0
    deflection_max: float = 0.0
    deflection_max_position: float = 0.0
    case: str = ""


# ---------------------------------------------------------------------------
# Simply supported
# ---------------------------------------------------------------------------


def ss_udl(w: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Simply supported span under a full uniformly distributed load.

    R = wL/2,  M_max = wL^2/8 at midspan,  delta = 5wL^4/(384EI).
    """
    return ClosedFormResult(
        R_left=w * L / 2.0,
        R_right=w * L / 2.0,
        M_max=w * L**2 / 8.0,
        M_max_position=L / 2.0,
        deflection_max=5.0 * w * L**4 / (384.0 * EI),
        deflection_max_position=L / 2.0,
        case="Simply supported, full UDL",
    )


def ss_central_point(P: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Simply supported span under a central point load.

    R = P/2,  M_max = PL/4,  delta = PL^3/(48EI).
    """
    return ClosedFormResult(
        R_left=P / 2.0,
        R_right=P / 2.0,
        M_max=P * L / 4.0,
        M_max_position=L / 2.0,
        deflection_max=P * L**3 / (48.0 * EI),
        deflection_max_position=L / 2.0,
        case="Simply supported, central point load",
    )


def ss_offset_point(P: float, a: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Simply supported span under a point load at ``a`` from the left.

    With ``b = L - a``::

        R_left  = P.b/L
        R_right = P.a/L
        M_max   = P.a.b/L, at the load
        delta_max = P.b.(L^2 - b^2)^1.5 / (9.sqrt(3).L.EI),
                    at x = sqrt((L^2 - b^2)/3), valid for a >= b

    Note the maximum deflection is NOT under the load and NOT at midspan.
    """
    b = L - a
    # The deflection formula assumes the load is in the right half; mirror the
    # problem if it is not, rather than carrying two versions of the formula.
    if a < b:
        a, b = b, a
        mirrored = True
    else:
        mirrored = False

    x_max = math.sqrt((L**2 - b**2) / 3.0)
    delta = P * b * (L**2 - b**2) ** 1.5 / (9.0 * math.sqrt(3.0) * L * EI)

    return ClosedFormResult(
        R_left=P * (L - a) / L if not mirrored else P * a / L,
        R_right=P * a / L if not mirrored else P * (L - a) / L,
        M_max=P * a * b / L,
        M_max_position=(L - a) if mirrored else a,
        deflection_max=delta,
        deflection_max_position=(L - x_max) if mirrored else x_max,
        case="Simply supported, offset point load",
    )


# ---------------------------------------------------------------------------
# Cantilever -- root at the LEFT end, free at the right
# ---------------------------------------------------------------------------


def cantilever_udl(w: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Cantilever under a full UDL.

    R = wL,  M_root = -wL^2/2 (hogging),  delta_tip = wL^4/(8EI).
    """
    return ClosedFormResult(
        R_left=w * L,
        M_left=-w * L**2 / 2.0,
        M_max=0.0,
        M_max_position=L,
        deflection_max=w * L**4 / (8.0 * EI),
        deflection_max_position=L,
        case="Cantilever, full UDL",
    )


def cantilever_tip_point(P: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Cantilever under a point load at the free end.

    R = P,  M_root = -PL,  delta_tip = PL^3/(3EI).
    """
    return ClosedFormResult(
        R_left=P,
        M_left=-P * L,
        M_max=0.0,
        M_max_position=L,
        deflection_max=P * L**3 / (3.0 * EI),
        deflection_max_position=L,
        case="Cantilever, tip point load",
    )


# ---------------------------------------------------------------------------
# Propped cantilever -- fixed LEFT, roller RIGHT. Singly indeterminate.
# ---------------------------------------------------------------------------


def propped_udl(w: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Propped cantilever under a full UDL.

    R_fixed = 5wL/8,  R_prop = 3wL/8,  M_fixed = -wL^2/8,
    M_max(sagging) = 9wL^2/128 at x = 5L/8,
    delta_max = wL^4/(185EI) at x ~= 0.5785L.

    [ASSUMPTION] The 185 denominator is the rounded textbook coefficient; the
                 exact value is 184.6. Deflection from this function is
                 therefore about 0.2% low, which is why the golden vector for
                 this case uses a looser tolerance on deflection than on the
                 reactions and moments. Do not tighten it without replacing
                 the coefficient with the exact form.
    """
    return ClosedFormResult(
        R_left=5.0 * w * L / 8.0,
        R_right=3.0 * w * L / 8.0,
        M_left=-w * L**2 / 8.0,
        M_max=9.0 * w * L**2 / 128.0,
        M_max_position=5.0 * L / 8.0,
        deflection_max=w * L**4 / (185.0 * EI),
        deflection_max_position=0.5785 * L,
        case="Propped cantilever, full UDL",
    )


def propped_central_point(P: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Propped cantilever under a central point load.

    R_fixed = 11P/16,  R_prop = 5P/16,  M_fixed = -3PL/16,
    M_max(sagging) = 5PL/32 at midspan.
    """
    return ClosedFormResult(
        R_left=11.0 * P / 16.0,
        R_right=5.0 * P / 16.0,
        M_left=-3.0 * P * L / 16.0,
        M_max=5.0 * P * L / 32.0,
        M_max_position=L / 2.0,
        deflection_max=7.0 * P * L**3 / (768.0 * EI),
        deflection_max_position=0.4472 * L,
        case="Propped cantilever, central point load",
    )


# ---------------------------------------------------------------------------
# Fixed both ends (encastre). Doubly indeterminate.
# ---------------------------------------------------------------------------


def fixed_udl(w: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Encastre beam under a full UDL.

    R = wL/2 each,  M_ends = -wL^2/12,  M_mid = +wL^2/24,
    delta_mid = wL^4/(384EI).
    """
    return ClosedFormResult(
        R_left=w * L / 2.0,
        R_right=w * L / 2.0,
        M_left=-w * L**2 / 12.0,
        M_right=-w * L**2 / 12.0,
        M_max=w * L**2 / 24.0,
        M_max_position=L / 2.0,
        deflection_max=w * L**4 / (384.0 * EI),
        deflection_max_position=L / 2.0,
        case="Fixed both ends, full UDL",
    )


def fixed_central_point(P: float, L: float, EI: float) -> ClosedFormResult:  # noqa: N803
    """Encastre beam under a central point load.

    R = P/2 each,  M_ends = -PL/8,  M_mid = +PL/8,
    delta_mid = PL^3/(192EI).
    """
    return ClosedFormResult(
        R_left=P / 2.0,
        R_right=P / 2.0,
        M_left=-P * L / 8.0,
        M_right=-P * L / 8.0,
        M_max=P * L / 8.0,
        M_max_position=L / 2.0,
        deflection_max=P * L**3 / (192.0 * EI),
        deflection_max_position=L / 2.0,
        case="Fixed both ends, central point load",
    )
