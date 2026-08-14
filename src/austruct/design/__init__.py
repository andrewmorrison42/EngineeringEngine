"""L4 -- design. Code compliance checks.

Imports from: core, materials, sections, analysis.

Structure
---------
``rc_common``
    The shared mechanics -- stress block, strain compatibility. No clause
    numbers, no capacity reduction factors.
``as3600``
    AS 3600:2018 provisions.
``as4100``
    AS 4100 provisions for structural steel. Note that its flexure module
    REFUSES to return a capacity for an unrestrained segment -- see its
    ``__init__``.
``as5100_5``
    AS 5100.5:2017 provisions. A different shear model from AS 3600:2018, not
    the same model with different constants -- see its ``constants.py``.

Import the code package you are working to, not individual functions, so that
which standard a calculation was performed to is visible at the call site::

    from austruct.design import as3600
    result = as3600.check_flexure(section, M_star)

rather than::

    from austruct.design.as3600.flexure import check_flexure   # ambiguous later
"""

from . import as3600, as4100, as5100_5, rc_common

__all__ = ["rc_common", "as3600", "as4100", "as5100_5"]
