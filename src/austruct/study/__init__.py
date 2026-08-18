"""``austruct.study`` -- run an existing design check against many variations.

Not a design domain. This package imports nothing from ``design``,
``sections`` or ``materials`` -- it knows only that whatever a check
function returns has ``.utilisation`` and ``.passed``, which every
:class:`~austruct.core.contract.CalcResult` in this toolkit already
provides. That is what lets one engine sweep an RC beam, a masonry wall, or
a retaining wall's stability checks without any design-domain code living
here -- the caller supplies ``build`` and ``check``, this package supplies
the orchestration.

Two ways to run variations:

- :func:`~.sweep.run_sweep` -- a discrete, reviewable list of named
  :class:`~.scheme.Scheme` (by hand, or round-tripped through a CSV via
  :func:`~.scheme.load_schemes_csv`). Every scheme is evaluated and kept,
  including the ones that fail to even build -- this is the tool for
  "here are the six options someone actually asked about."
- :func:`~.optimise.minimize_scheme` -- an optional, `scipy`-backed
  continuous search over a design's continuous variables (thicknesses,
  lengths), for "what is the cheapest section that still passes" rather
  than "which of these six passes". Requires ``pip install -e ".[optimise]"``;
  see the module docstring for the discrete/continuous boundary this does
  NOT cross.
"""

from __future__ import annotations

from .optimise import SCIPY_AVAILABLE, OptimiseResult, minimize_scheme
from .scheme import Scheme, load_schemes_csv, save_schemes_csv
from .sweep import SchemeOutcome, SweepResult, run_sweep

__all__ = [
    "Scheme",
    "load_schemes_csv",
    "save_schemes_csv",
    "run_sweep",
    "SchemeOutcome",
    "SweepResult",
    "minimize_scheme",
    "OptimiseResult",
    "SCIPY_AVAILABLE",
]
