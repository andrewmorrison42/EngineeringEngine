"""``minimize_scheme`` -- an optional ``scipy.optimize`` search over the
CONTINUOUS variables of a design problem.

``scipy`` is not a core dependency of this package (see the note at the top
of ``pyproject.toml``) -- install it with ``pip install -e ".[optimise]"``.
Importing this module without it does not fail; calling
:func:`minimize_scheme` does, with that install instruction in the message.

What this is for, and what it is not
-------------------------------------
This drives a continuous search (thicknesses, lengths, cover) over the
SAME ``build``/``check``/``cost`` shape :func:`~.sweep.run_sweep` uses, so a
scenario written for one works for the other. It does NOT know about
DISCRETE choices -- catalogue bar diameters, standard UB/UC sections, block
thickness series. Keep those on the existing catalogue-search pattern
(``options_for_area``, ``bar_catalogue``, ``steel_catalogue``) and use this
only for the genuinely continuous dimensions; round a discrete choice to a
practical value AFTER the continuous optimum is found, then re-verify.

``scipy.optimize`` only ever sees the objective and constraint functions
handed to it -- it has no idea what an ``Envelope`` or a ductility limit is.
So the proposed optimum is ALWAYS re-run through the real ``check`` function
before being returned: :attr:`OptimiseResult.result` is a genuine
``check(build(**x))`` at the optimiser's final ``x``, not a number `scipy`
computed and this module trusted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .sweep import Checkable

try:
    import numpy as _np
    from scipy.optimize import NonlinearConstraint as _NonlinearConstraint
    from scipy.optimize import minimize as _minimize
except ImportError as exc:  # pragma: no cover -- exercised only without scipy installed
    _IMPORT_ERROR: ImportError | None = exc
else:
    _IMPORT_ERROR = None

SCIPY_AVAILABLE = _IMPORT_ERROR is None


def _require_scipy() -> None:
    if _IMPORT_ERROR is not None:
        raise ImportError(
            "minimize_scheme() needs scipy, which is not installed in this "
            "environment. Install it with:\n\n"
            '    pip install -e ".[optimise]"\n'
        ) from _IMPORT_ERROR


@dataclass(frozen=True)
class OptimiseResult:
    """The optimiser's proposed optimum, ALREADY re-verified against the
    real check -- see the module docstring for why that matters."""

    x: dict[str, float]
    subject: Any
    result: Checkable
    success: bool
    message: str
    raw: Any
    """The underlying ``scipy.optimize.OptimizeResult``, for anyone who
    wants the iteration count, the Jacobian, or anything else `scipy`
    tracked and this module does not re-expose."""

    def describe(self) -> str:
        status = "converged" if self.success else "DID NOT CONVERGE"
        x_str = ", ".join(f"{k}={v:.3g}" for k, v in self.x.items())
        return (
            f"{status} ({self.message}): {x_str}  ->  "
            f"util {self.result.utilisation:.3f}  "
            f"{'PASS' if self.result.passed else 'FAIL'}"
        )


def minimize_scheme(
    variables: Mapping[str, tuple[float, float]],
    build: Callable[..., Any],
    check: Callable[[Any], Checkable],
    cost: Callable[[Any], float],
    base: Mapping[str, Any] | None = None,
    x0: Mapping[str, float] | None = None,
    method: str = "SLSQP",
) -> OptimiseResult:
    """Minimise ``cost(build(**x))`` over continuous ``variables``, subject
    to ``check(build(**x)).utilisation <= 1``.

    Parameters
    ----------
    variables:
        ``{name: (lower, upper)}`` bounds for each continuous variable
        being searched. Every other keyword ``build`` needs comes from
        ``base``.
    build, check:
        Same shape as :func:`~.sweep.run_sweep` -- ``build(**kwargs)``
        constructs the subject, ``check(subject)`` returns something with
        ``.utilisation``/``.passed``.
    cost:
        Objective to minimise, over the built subject.
    base:
        Keyword arguments held fixed across the search.
    x0:
        Starting point per variable; defaults to the midpoint of each
        variable's bounds.
    method:
        Passed to ``scipy.optimize.minimize``. ``"SLSQP"`` (the default)
        handles bounds and nonlinear constraints together; switch to
        differential evolution yourself (via ``scipy.optimize`` directly)
        if the objective is non-smooth -- see the roadmap note on when
        gradient-based search is the wrong tool.

    Returns
    -------
    OptimiseResult

    Raises
    ------
    ImportError
        If ``scipy`` is not installed.
    """
    _require_scipy()
    base = dict(base or {})
    names = list(variables.keys())
    bounds = [variables[n] for n in names]

    if x0 is None:
        x0_vec = [(lo + hi) / 2.0 for lo, hi in bounds]
    else:
        x0_vec = [x0[n] for n in names]

    def kwargs_for(x) -> dict[str, Any]:
        merged = dict(base)
        merged.update(zip(names, x))
        return merged

    def objective(x) -> float:
        return cost(build(**kwargs_for(x)))

    def constraint(x) -> float:
        # >= 0 means the check passes -- scipy's NonlinearConstraint wants
        # this sign, not a raw utilisation.
        return 1.0 - check(build(**kwargs_for(x))).utilisation

    raw = _minimize(
        objective,
        x0_vec,
        method=method,
        bounds=bounds,
        constraints=[_NonlinearConstraint(constraint, 0.0, _np.inf)],
    )

    x_dict = dict(zip(names, raw.x))
    subject = build(**kwargs_for(raw.x))
    result = check(subject)  # re-verify the REAL check at the final candidate

    return OptimiseResult(
        x=x_dict,
        subject=subject,
        result=result,
        success=bool(raw.success),
        message=str(raw.message),
        raw=raw,
    )
