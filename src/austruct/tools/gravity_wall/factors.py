"""Minimum factors of safety -- NCMA-style allowable stress design.

Unlike ``cantilever_wall.factor_sets`` (several AS 4678 verification
classes, each a YAML file, because that framework genuinely varies by
consequence class), this tool supports exactly one methodology, and its
minimums are a matter of published record rather than an office judgement
call -- so they live here as plain constants, not a swappable file. Sliding
and overturning minimums are stated directly on p.95 of the Redi-Rock
Design Resource Manual V20 (source PDF for this tool's development); the
same 1.5/1.5/2.0/1.3 figures are the long-standing NCMA convention and
recur across other manufacturers' manuals -- treat them as representative
industry practice, not a transcription unique to one manufacturer.

[VECTOR] FS_INTERFACE_SHEAR specifically is NOT stated in the source PDF
         (which never reaches internal/interface stability at all -- see
         the package README) -- it is set equal to the sliding/overturning
         minimum as a reasonable default, UNVERIFIED against an office
         standard or a specific manufacturer's design manual.
"""

from __future__ import annotations

FS_SLIDING = 1.5
FS_OVERTURNING = 1.5
FS_BEARING = 2.0
FS_INTERFACE_SHEAR = 1.5
"""[VECTOR] UNVERIFIED -- see the module docstring."""

FS_GLOBAL_STABILITY = 1.3
"""Not computed by this tool -- no geometry screen exists for it, the same
way ``cantilever_wall`` flags rather than computes global stability. Kept
here so the number appears in one place, referenced in
:mod:`.api`'s ``notes`` output rather than hardcoded into a string there."""
