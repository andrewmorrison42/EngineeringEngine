"""L0 -- core contract and plumbing.

This layer imports nothing else from austruct. Everything else imports it.
"""

from .basis import (
    AS1170_0_2002,
    AS3600_2018,
    AS4671_2019,
    AS5100_2_2017,
    AS5100_5_2017,
    FIRST_PRINCIPLES,
    Basis,
    ClauseRef,
    Standard,
)
from .contract import CalcResult, Check, Value
from .envelope import Envelope, Limit
from .exceptions import (
    AustructError,
    ConvergenceError,
    ModelError,
    OutsideEnvelope,
    UnverifiedConstant,
)
from .provenance import (
    ASET_COMPONENT_NAMES,
    ASETComponent,
    GoldenVector,
    ModuleType,
    Provenance,
    VerificationStatus,
    strict_mode,
)
from .registry import REGISTRY, ModuleRegistry

__all__ = [
    # basis
    "Standard",
    "ClauseRef",
    "Basis",
    "AS3600_2018",
    "AS5100_5_2017",
    "AS5100_2_2017",
    "AS1170_0_2002",
    "AS4671_2019",
    "FIRST_PRINCIPLES",
    # contract
    "CalcResult",
    "Value",
    "Check",
    # envelope
    "Envelope",
    "Limit",
    # provenance
    "Provenance",
    "VerificationStatus",
    "ModuleType",
    "ASETComponent",
    "ASET_COMPONENT_NAMES",
    "GoldenVector",
    "strict_mode",
    # registry
    "REGISTRY",
    "ModuleRegistry",
    # exceptions
    "AustructError",
    "OutsideEnvelope",
    "ConvergenceError",
    "ModelError",
    "UnverifiedConstant",
]
