"""L5 -- the audit artifact.

The durable standard is the report LAYOUT (``template.py``), not any particular
rendering library. See the roadmap, Phase 2.
"""

from .renderers import MarkdownRenderer
from .template import Renderer, Report, SignatureBlock

__all__ = ["Report", "SignatureBlock", "Renderer", "MarkdownRenderer"]
