"""Checks against the stability ledger. Each returns a
:class:`~austruct.core.contract.CalcResult`, and ranks by ``utilisation``
rather than a bare pass/fail.

Built: sliding, eccentricity, bearing. NOT yet built: stem/heel/toe flexure
and shear (AS 3600:2018), and the global-stability geometry screen -- see
the package README for what remains.
"""

from __future__ import annotations

from .bearing import check_bearing
from .eccentricity import check_eccentricity
from .sliding import check_sliding

__all__ = ["check_sliding", "check_eccentricity", "check_bearing"]
