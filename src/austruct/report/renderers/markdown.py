"""Markdown renderer for the standard report layout.

Markdown is the default because it is readable as plain text, diffs cleanly in
git (so a change to an issued calculation is visible in review), and converts
to PDF or Word without this package taking a dependency on either.

[UNITS] Values are rendered in their declared display units -- moments in kN.m,
        forces in kN -- while storage stays in base units. See
        :class:`austruct.core.contract.Value`.
"""

from __future__ import annotations

from ...core.contract import CalcResult, Value
from ..template import Figure, Narrative, NarrativeKind, Renderer, Report


class MarkdownRenderer(Renderer):
    """Render a :class:`~austruct.report.template.Report` as Markdown."""

    def __init__(self, show_intermediates: bool = True, float_format: str = "{:.4g}") -> None:
        self.show_intermediates = show_intermediates
        self.float_format = float_format

    # -- helpers --------------------------------------------------------------

    def _fmt(self, value: Value) -> tuple[str, str]:
        magnitude, unit = value.display
        return self.float_format.format(magnitude), unit

    def _value_table(self, values: dict[str, Value], caption: str) -> str:
        if not values:
            return ""
        rows = [f"**{caption}**", "", "| Symbol | Description | Value | Unit |", "|---|---|---:|---|"]
        for value in values.values():
            magnitude, unit = self._fmt(value)
            symbol = f"`{value.symbol}`" if value.symbol else ""
            rows.append(f"| {symbol} | {value.description} | {magnitude} | {unit} |")
        rows.append("")
        return "\n".join(rows)

    # -- fixed sections -------------------------------------------------------

    def header(self, report: Report) -> str:
        lines = [f"# {report.title}", ""]
        sig = report.signature
        meta = []
        if sig.job_number:
            meta.append(f"**Job:** {sig.job_number}")
        if sig.job_name:
            meta.append(f"**Project:** {sig.job_name}")
        if sig.element:
            meta.append(f"**Element:** {sig.element}")
        if sig.revision:
            meta.append(f"**Revision:** {sig.revision}")
        if meta:
            lines.extend([" &nbsp;|&nbsp; ".join(meta), ""])

        status = "PASS" if report.passed else "**FAIL**"
        lines.append(f"**Result: {status}**")
        if not report.issuable:
            lines.extend(
                [
                    "",
                    "> **NOT FOR ISSUE.** One or more modules used in this "
                    "calculation have not been verified against the printed "
                    "standard by a named checker. See the provenance block at "
                    "the end of each section.",
                ]
            )
        lines.append("")
        if report.preamble:
            lines.extend([report.preamble, ""])
        return "\n".join(lines)

    def inputs(self, result: CalcResult) -> str:
        """Section 1 -- inputs echoed verbatim, units declared."""
        return self._value_table(result.inputs, "Inputs")

    def basis_and_envelope(self, result: CalcResult) -> str:
        """Section 2 -- basis and envelope statement."""
        lines = ["**Basis**", ""]
        if len(result.basis):
            for ref in result.basis:
                lines.append(f"- {ref}")
        else:
            lines.append("- _No basis recorded._")
        lines.append("")

        lines.append("**Validity envelope**")
        lines.append("")
        flag = "WITHIN" if result.envelope.within else "**OUTSIDE**"
        lines.append(f"Status: {flag}")
        lines.append("")
        for line in result.envelope.describe():
            lines.append(f"- {line}")
        lines.append("")
        return "\n".join(lines)

    def working(self, result: CalcResult) -> str:
        """Section 3 -- step-by-step working with units."""
        out = []
        if self.show_intermediates and result.intermediates:
            out.append(self._value_table(result.intermediates, "Working"))
        out.append(self._value_table(result.outputs, "Results"))
        if result.messages:
            out.append("**Notes**\n")
            out.extend(f"- {m}" for m in result.messages)
            out.append("")
        return "\n".join(p for p in out if p)

    def checks(self, result: CalcResult) -> str:
        """Section 4 -- pass/fail against criteria."""
        if not result.checks:
            return ""
        lines = [
            "**Checks**",
            "",
            "| Criterion | Actual | Limit | Utilisation | Result | Basis |",
            "|---|---:|---:|---:|:---:|---|",
        ]
        for check in result.checks:
            f = check.display_factor
            unit = check.display_unit or check.unit
            status = "PASS" if check.passed else "**FAIL**"
            basis = check.basis.citation if check.basis else ""
            lines.append(
                f"| {check.label} "
                f"| {check.actual / f:.4g} {unit} "
                f"| {check.operator} {check.limit / f:.4g} {unit} "
                f"| {check.utilisation:.3f} "
                f"| {status} "
                f"| {basis} |"
            )
        lines.append("")
        return "\n".join(lines)

    def provenance(self, result: CalcResult) -> str:
        """Provenance block. Not one of the six template sections, but required
        by the module contract, so it is rendered after the checks."""
        lines = ["<details><summary>Provenance</summary>", "", "```"]
        lines.extend(result.provenance.describe())
        lines.extend(["```", "", "</details>", ""])
        return "\n".join(lines)

    def narrative(self, block: Narrative) -> str:
        """Engineer-written prose, set apart from the generated content.

        Scope, assumptions and limitations are blockquoted so a reviewer can
        see at a glance which parts of the document are a statement by the
        engineer and which are output from the package. Commentary is left as
        plain prose because it is meant to read continuously with what
        surrounds it.
        """
        lines: list[str] = []
        if block.heading:
            lines.extend([f"### {block.heading}", ""])
        if block.kind is NarrativeKind.COMMENTARY:
            lines.extend([block.text, ""])
        else:
            label = block.kind.value.upper()
            lines.append(f"> **{label}**")
            lines.append(">")
            lines.extend(f"> {line}" for line in block.text.splitlines())
            lines.append("")
        return "\n".join(lines)

    def figures(self, report: Report) -> str:
        """Section 5 -- embedded plots and geometry."""
        if not report.figures:
            return ""
        lines = ["## Figures", ""]
        for caption, path in report.figures:
            lines.extend([f"![{caption}]({path})", "", f"*{caption}*", ""])
        return "\n".join(lines)

    def signature(self, report: Report) -> str:
        """Section 6 -- signature block."""
        sig = report.signature
        designed_on = sig.designed_on.isoformat() if sig.designed_on else ""
        checked_on = sig.checked_on.isoformat() if sig.checked_on else ""
        lines = [
            "## Signatures",
            "",
            "| | Name | Date |",
            "|---|---|---|",
            f"| Designed | {sig.designed_by or '&nbsp;'} | {designed_on or '&nbsp;'} |",
            f"| Checked | {sig.checked_by or '&nbsp;'} | {checked_on or '&nbsp;'} |",
            "",
        ]
        if sig.notes:
            lines.extend([sig.notes, ""])
        return "\n".join(lines)

    # -- driver ---------------------------------------------------------------

    def render(self, report: Report) -> str:
        """Walk the report body in order and emit the document.

        The body order is the ENGINEER'S order, not a fixed calculations-then-
        prose split: narrative sits where it was written, between the
        calculations it explains. Within each calculation the fixed section
        order still applies, which is what keeps the artifact compliant.
        """
        parts = [self.header(report)]
        if report.preamble:
            parts.extend([report.preamble, ""])

        number = 0
        for item in report.items:
            if isinstance(item, Narrative):
                parts.append(self.narrative(item))
            elif isinstance(item, Figure):
                parts.extend([f"![{item.caption}]({item.path})", "", f"*{item.caption}*", ""])
            else:
                number += 1
                parts.append(f"## {number}. {item.name}")
                parts.append("")
                parts.extend(p for p in self.result_sections(item) if p)
                parts.append(self.provenance(item))

        parts.append(self.signature(report))

        return "\n".join(p for p in parts if p is not None).rstrip() + "\n"
