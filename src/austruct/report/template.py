"""The audit artifact -- a fixed report layout, independent of any renderer.

Roadmap Phase 2 is explicit: *"the durable standard is the report template, not
the package"*. So the layout is fixed here as an ordered list of sections, and
renderers are interchangeable implementations of that layout::

    Inputs echoed
      -> basis and envelope statement
      -> step-by-step working with units
      -> pass/fail against criteria
      -> embedded plots and geometry
      -> signature block

Any module that produces this document is compliant, whether it got there via
handcalcs, Jinja, or a Word merge. Adding a renderer means implementing
:class:`Renderer`; it does not mean touching this file.

Deliberately NOT using handcalcs here
-------------------------------------
handcalcs renders the *arithmetic*, which is one of six sections. Making it the
report engine would make the layout hostage to its rendering choices and would
leave Type A (tabulated) and Type C (geometry) modules with no compliant
artifact at all. It slots in as a renderer for the working section instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from ..core.contract import CalcResult


@dataclass
class SignatureBlock:
    """Who did the work, who checked it, and against what.

    Empty fields render as blank ruled lines -- a report with an unsigned block
    is a valid draft, and printing it that way is more useful than refusing to
    render one.
    """

    job_number: str = ""
    job_name: str = ""
    element: str = ""
    designed_by: str = ""
    designed_on: date | None = None
    checked_by: str = ""
    checked_on: date | None = None
    revision: str = ""
    notes: str = ""


@dataclass
class Report:
    """A calculation report: a title, a signature block, and one or more results.

    Multiple results in one report is the normal case -- a beam design is an
    analysis, a flexure check and a shear check, and they belong in one
    document with one signature block.
    """

    title: str
    results: list[CalcResult] = field(default_factory=list)
    signature: SignatureBlock = field(default_factory=SignatureBlock)
    preamble: str = ""
    figures: list[tuple[str, str]] = field(default_factory=list)
    """``[(caption, path_or_data_uri), ...]`` for embedded plots and geometry."""

    def add(self, result: CalcResult) -> CalcResult:
        self.results.append(result)
        return result

    def add_figure(self, caption: str, path: str) -> None:
        self.figures.append((caption, path))

    @property
    def passed(self) -> bool:
        """True only if every result passes -- including its envelope."""
        return all(r.passed for r in self.results)

    @property
    def issuable(self) -> bool:
        """Whether every module used is verified for issue.

        A report can pass every design check and still not be issuable, because
        the modules that produced it have not been verified. Keeping the two
        separate is the point of the Phase 3 spine.
        """
        return all(r.provenance.issuable for r in self.results)

    def render(self, renderer: Renderer) -> str:
        return renderer.render(self)


class Renderer(ABC):
    """Base class for report renderers.

    A renderer walks the fixed section order and emits its own markup. It must
    not reorder, omit or add sections -- that ordering IS the standard.
    """

    @abstractmethod
    def render(self, report: Report) -> str:
        """Render a complete report to a string."""

    # -- the fixed section order ---------------------------------------------
    # Subclasses implement each hook. `render` in a subclass should call these
    # in exactly this order.

    @abstractmethod
    def header(self, report: Report) -> str: ...

    @abstractmethod
    def inputs(self, result: CalcResult) -> str: ...

    @abstractmethod
    def basis_and_envelope(self, result: CalcResult) -> str: ...

    @abstractmethod
    def working(self, result: CalcResult) -> str: ...

    @abstractmethod
    def checks(self, result: CalcResult) -> str: ...

    @abstractmethod
    def figures(self, report: Report) -> str: ...

    @abstractmethod
    def signature(self, report: Report) -> str: ...

    def result_sections(self, result: CalcResult) -> list[str]:
        """The four per-result sections, in the fixed order."""
        return [
            self.inputs(result),
            self.basis_and_envelope(result),
            self.working(result),
            self.checks(result),
        ]
