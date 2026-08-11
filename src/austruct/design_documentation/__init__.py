"""L2b -- design documentation. ASET component 4.

Plain-text formats describing design DECISIONS -- both human- and
machine-readable, so a schedule can be reviewed by an engineer, drafted from by
a technician, and consumed by a program, without the design being written down
more than once.

Imports from: core, materials, sections.
"""

from .designation import (
    DesignationError,
    ParsedDesignation,
    designate,
    parse,
    parse_fields,
    validate,
)
from .schedule import (
    ScheduleEntry,
    read_matrix_schedule,
    read_schedule,
    schedule_report,
    to_sections,
    validate_schedule,
    write_matrix_schedule,
    write_schedule,
)

__all__ = [
    # designation grammar
    "parse",
    "designate",
    "parse_fields",
    "validate",
    "ParsedDesignation",
    "DesignationError",
    # schedules
    "ScheduleEntry",
    "read_schedule",
    "write_schedule",
    "read_matrix_schedule",
    "write_matrix_schedule",
    "to_sections",
    "validate_schedule",
    "schedule_report",
]
