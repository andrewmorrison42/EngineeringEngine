"""Bolt-on tools built on top of ``austruct``'s core layers.

A tool in this package is composed differently from the L0-L5 layers below
it: it takes a validated Pydantic model as input and returns one as output
(:mod:`austruct.tools.contracts`), and internally it *calls into* the core
layers -- ``materials``, ``sections``, ``design.as3600`` -- for the mechanics
those layers already own, in their existing mm/N/MPa float convention.

Pydantic's job here is narrow and deliberate: guardrails on values that are an
ENGINEERING JUDGEMENT CALL (a backslope, a water table depth, how much cover
to neglect for services trenching), validated at construction time, before any
calculation runs. It is not a replacement for :class:`austruct.core.envelope.Envelope`
-- a code clause's validity range is the standard's limit, not a judgement
call, and stays expressed as an ``Envelope`` inside the engine, checked at
calculation time as everywhere else in this package.

This is why ``pydantic`` is an optional extra (``pip install -e ".[tools]"``)
rather than a core dependency: the core package's dependency-minimal,
no-units-library convention (see ``core/units.py``) is about the wheelhouse/
``.exe`` distribution path for the L0-L5 layers, and stays intact. Only an
installation actually using ``tools/`` pulls Pydantic in.
"""

from __future__ import annotations
