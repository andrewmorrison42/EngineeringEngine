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
from dataclasses import InitVar, dataclass, field
from datetime import date
from enum import Enum

from ..core.contract import CalcResult
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.REPORTING,
    ),
    description="The fixed calculation report layout, independent of any renderer",
    envelope_summary="Any CalcResult-producing module",
)


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


class NarrativeKind(str, Enum):
    """What a piece of engineer-written prose is doing in the document.

    Not decoration. A reviewer reads an assumption differently from a
    commentary, and a renderer can set them differently -- but more
    importantly, a report that distinguishes them can be checked for whether
    the assumptions were ever stated at all.
    """

    COMMENTARY = "commentary"
    """Explanation and reasoning. The default."""

    SCOPE = "scope"
    """What this calculation covers, and what it does not."""

    ASSUMPTION = "assumption"
    """Something taken to be true without being calculated here."""

    LIMITATION = "limitation"
    """A known restriction on the validity of the result."""

    CONCLUSION = "conclusion"
    """What the engineer concludes. Usually the last thing a reviewer reads
    and the first thing they look for."""


@dataclass
class Narrative:
    """A block of engineer-written prose in the report.

    Attributes
    ----------
    text:
        Markdown. Written by the engineer, not generated.
    heading:
        Optional heading for the block.
    kind:
        What the prose is doing. See :class:`NarrativeKind`.
    """

    text: str
    heading: str = ""
    kind: NarrativeKind = NarrativeKind.COMMENTARY


@dataclass
class Figure:
    """An embedded plot or geometry image."""

    caption: str
    path: str


ReportItem = CalcResult | Narrative | Figure


@dataclass
class Report:
    """A calculation report: a title, a signature block, and an ordered body.

    Multiple results in one report is the normal case -- a beam design is an
    analysis, a flexure check and a shear check, and they belong in one
    document with one signature block.

    Why the body is ONE ordered list
    --------------------------------
    A report that reaches a road authority or an independent reviewer is read
    by a person, and a person needs the reasoning between the numbers: what was
    assumed, why this load case, what the result means. Keeping calculations in
    one list and prose in another forces the prose to the end, where nobody
    reads it and where it no longer explains anything.

    So results, narrative and figures all go into ``items`` in the order they
    were added, and the renderer walks that order. In a notebook this maps
    directly onto how the work is actually done::

        report.add_narrative("The culvert is founded on ...", kind=SCOPE)
        report.add(flexure_check)
        report.add_narrative("The corner moment governs because ...")
        report.add(shear_check)

    ``results`` and ``figures`` remain available as filtered views, so anything
    that only wants the calculations still works.
    """

    title: str
    results_in: InitVar[list[CalcResult] | None] = None
    signature: SignatureBlock = field(default_factory=SignatureBlock)
    preamble: str = ""
    items: list[ReportItem] = field(default_factory=list)

    def __post_init__(self, results_in: list[CalcResult] | None) -> None:
        if results_in:
            self.items.extend(results_in)

    # -- building the body ----------------------------------------------------

    def add(self, result: CalcResult) -> CalcResult:
        """Append a calculation."""
        self.items.append(result)
        return result

    def add_narrative(
        self,
        text: str,
        heading: str = "",
        kind: NarrativeKind = NarrativeKind.COMMENTARY,
    ) -> Narrative:
        """Append a block of engineer-written prose at this point in the body.

        This is the mechanism by which a report becomes readable by someone who
        did not do the work. The package generates numbers; only the engineer
        can say why they are the right numbers.
        """
        block = Narrative(text=text, heading=heading, kind=kind)
        self.items.append(block)
        return block

    def add_scope(self, text: str, heading: str = "Scope") -> Narrative:
        """Append a scope statement."""
        return self.add_narrative(text, heading, NarrativeKind.SCOPE)

    def add_assumption(self, text: str, heading: str = "Assumptions") -> Narrative:
        """Append an assumptions statement."""
        return self.add_narrative(text, heading, NarrativeKind.ASSUMPTION)

    def add_limitation(self, text: str, heading: str = "Limitations") -> Narrative:
        """Append a limitations statement."""
        return self.add_narrative(text, heading, NarrativeKind.LIMITATION)

    def add_conclusion(self, text: str, heading: str = "Conclusion") -> Narrative:
        """Append a conclusion."""
        return self.add_narrative(text, heading, NarrativeKind.CONCLUSION)

    def add_figure(self, caption: str, path: str) -> Figure:
        """Append a figure at this point in the body."""
        figure = Figure(caption=caption, path=path)
        self.items.append(figure)
        return figure

    # -- filtered views -------------------------------------------------------

    @property
    def results(self) -> list[CalcResult]:
        """Just the calculations, in order."""
        return [i for i in self.items if isinstance(i, CalcResult)]

    @property
    def figures(self) -> list[tuple[str, str]]:
        """``[(caption, path), ...]`` for the figures, in order."""
        return [(i.caption, i.path) for i in self.items if isinstance(i, Figure)]

    @property
    def narratives(self) -> list[Narrative]:
        """Just the prose, in order."""
        return [i for i in self.items if isinstance(i, Narrative)]

    def has_narrative(self, kind: NarrativeKind) -> bool:
        """Whether the report states something of this kind anywhere.

        Lets a reviewer -- or a pre-issue check -- ask whether the assumptions
        and limitations were ever written down, rather than discovering they
        were not after the report has gone out.
        """
        return any(n.kind is kind for n in self.narratives)

    # -- status ---------------------------------------------------------------

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

    def _repr_markdown_(self) -> str:
        """Rich display in a Jupyter notebook -- the whole report, rendered.

        Means a notebook cell containing just the report object shows the
        document, which is the thing the user is building.
        """
        from .renderers.markdown import MarkdownRenderer

        return self.render(MarkdownRenderer())


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
    def narrative(self, block: Narrative) -> str: ...

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
