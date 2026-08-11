"""Exception hierarchy.

Design rule: modules **fail closed**. A calculation that cannot demonstrate it
is inside its validity envelope raises rather than returning a number with a
warning attached, because warnings do not survive being copied into a drawing.
"""

from __future__ import annotations


class AustructError(Exception):
    """Base class for every error raised by this toolkit."""


class OutsideEnvelope(AustructError):
    """Inputs fall outside the module's declared validity envelope.

    Raised by :meth:`austruct.core.envelope.Envelope.require`. Carries the
    envelope so a caller that wants to report rather than crash -- a batch
    parametric run, say -- can inspect exactly which limit was breached.
    """

    def __init__(self, message: str, envelope=None):
        super().__init__(message)
        self.envelope = envelope


class ConvergenceError(AustructError):
    """An iterative solve failed to converge within its iteration budget.

    Used by the strain-compatibility neutral-axis solve. Carries the last
    iterate so the failure can be diagnosed rather than merely reported.
    """

    def __init__(self, message: str, last_value: float | None = None, iterations: int = 0):
        super().__init__(message)
        self.last_value = last_value
        self.iterations = iterations


class ModelError(AustructError):
    """The structural model itself is invalid or inconsistent.

    Examples: a beam with insufficient supports to be stable, a load applied
    beyond the end of the member, a section with no reinforcement in tension.
    Distinct from OutsideEnvelope -- this is a model that cannot be analysed at
    all, not one that is outside a code's range of application.
    """


class UnverifiedConstant(AustructError):
    """A code constant flagged as unverified was used in strict mode.

    See :mod:`austruct.core.provenance`. Every numeric value taken from a
    printed standard starts life UNVERIFIED. Enabling strict mode turns any use
    of an unverified value into a hard error, which is what a production
    configuration should do.
    """
