"""Checks against the gravity ledger, each an FS-based
:class:`~austruct.core.contract.CalcResult` -- NCMA-style allowable stress
design. Built: sliding, overturning, bearing, interface shear (internal
stability). NOT built: a global-stability geometry screen -- see the
package README.
"""

from __future__ import annotations

from .bearing import check_bearing
from .interface_shear import check_interface_shear
from .overturning import check_overturning
from .sliding import check_sliding

__all__ = ["check_sliding", "check_overturning", "check_bearing", "check_interface_shear"]
