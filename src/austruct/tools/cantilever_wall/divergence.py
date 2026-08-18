"""Comparing Method A and Method B, per the brief's original spec.

``divergence = |P_A - P_B| / max(P_A, P_B)``, banded:

- under 5% -- informational, the methods agree
- 5-15% -- warn, and NAME the likely cause rather than leaving the reader
  to guess
- over 15% -- flag for engineer adjudication; this module never averages
  the two or silently prefers one

Scope note: this compares the two earth-pressure THRUSTS directly (the
quantity both :mod:`.pressure.rankine` and :mod:`.pressure.culmann`
produce), not a re-run of sliding/eccentricity/bearing under Method B's
ledger. Extending the stability checks to accept either method's thrust is
a natural next step -- noted in the README -- but doubles the size of
``checks/`` to do properly, and the thrust-level comparison already
surfaces the real divergence sources this tool's two methods have (see
``pressure/culmann.py``'s docstring): backslope, and cohesion credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

INFORMATIONAL_LIMIT = 0.05
WARN_LIMIT = 0.15
"""[VECTOR] Bands from the original brief, not a transcribed code clause --
these are a documented judgement call on what counts as "the methods
agree", not an AS 4678/AS 5100.3 value."""

Band = Literal["informational", "warn", "flag"]


@dataclass(frozen=True)
class Divergence:
    """One quantity, compared between the two methods."""

    quantity: str
    value_a: float
    value_b: float
    divergence: float
    band: Band
    cause: str

    def describe(self) -> str:
        return (
            f"{self.quantity}: A = {self.value_a:.2f}, B = {self.value_b:.2f}  "
            f"({self.divergence:.1%} divergence, {self.band}) -- {self.cause}"
        )


def _band(divergence: float) -> Band:
    if divergence < INFORMATIONAL_LIMIT:
        return "informational"
    if divergence < WARN_LIMIT:
        return "warn"
    return "flag"


def _compare(quantity: str, value_a: float, value_b: float, cause_if_diverging: str) -> Divergence:
    denom = max(abs(value_a), abs(value_b))
    divergence = 0.0 if denom == 0 else abs(value_a - value_b) / denom
    band = _band(divergence)
    cause = "the methods agree" if band == "informational" else cause_if_diverging
    return Divergence(quantity, value_a, value_b, divergence, band, cause)


def compare_thrust(
    thrust_a_horizontal: float,
    thrust_b_horizontal: float,
    backslope_deg: float,
    cohesion: float,
) -> Divergence:
    """Compare the two methods' horizontal earth-pressure thrust.

    ``backslope_deg`` and ``cohesion`` are used only to NAME the likely
    cause when the two diverge -- see ``pressure/culmann.py``'s docstring
    for why these are this tool's two known, real divergence sources.
    """
    causes = []
    if backslope_deg > 0:
        causes.append(
            f"backslope ({backslope_deg:.1f} deg) -- Rankine and Coulomb(delta=0) "
            "are not expected to agree once the ground behind the wall slopes; "
            "see pressure/culmann.py"
        )
    if cohesion > 0:
        causes.append(
            f"cohesion (c' = {cohesion:.1f} kPa) -- Method A credits cohesion "
            "relief, Method B does not"
        )
    cause = "; and ".join(causes) if causes else "no known cause identified -- investigate"
    return _compare("Horizontal thrust P_h", thrust_a_horizontal, thrust_b_horizontal, cause)
