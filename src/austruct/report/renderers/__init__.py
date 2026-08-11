"""Report renderers. Each implements the fixed layout in ``template.py``.

Adding a renderer (handcalcs, Jinja/HTML, Word merge) means implementing
``Renderer``; it does not mean changing the layout.
"""

from .markdown import MarkdownRenderer

__all__ = ["MarkdownRenderer"]
