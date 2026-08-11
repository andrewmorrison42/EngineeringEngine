"""Self-contained HTML renderer, for a report that leaves the office.

Why HTML and not just Markdown
------------------------------
Markdown is right for version control and for reading in a terminal. It is the
wrong thing to email to a road authority, because how it looks depends entirely
on what opens it, and a calculation whose table alignment collapses reads as
carelessness whatever the numbers say.

This renderer emits ONE file with the styling inline. It opens identically
anywhere, prints to PDF from any browser, and needs no network access -- which
matters because the recipient is often behind a corporate firewall that strips
external stylesheets.

Design decisions worth stating
------------------------------
- **Print stylesheet included.** A reviewer prints it. Page breaks are set to
  avoid splitting a check table across pages, because a half-table is worse
  than a page break.
- **Status is visible without reading.** Pass, fail and not-issuable each get a
  banner. An unverified report is marked on every page of the printed output,
  not just the first, so a page photocopied out of context still carries it.
- **No JavaScript.** Nothing to be blocked, nothing to break, nothing that
  makes the document behave differently for different readers.
- **Engineer narrative is visually distinct** from generated content, so a
  reviewer can tell a statement by the engineer from an output of the package.
  That distinction matters for where responsibility sits.
"""

from __future__ import annotations

import html as _html

from ...core.contract import CalcResult, Value
from ..template import Figure, Narrative, NarrativeKind, Renderer, Report

_CSS = """
:root {
  --ink: #1a1a1a; --muted: #5b6470; --rule: #d6dae0; --bg: #ffffff;
  --pass: #1a7f4b; --fail: #b3261e; --warn: #8a6100; --warn-bg: #fdf6e3;
  --narrative-bg: #f4f7fb; --narrative-edge: #3b6ea5;
}
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 32px 28px 64px; max-width: 900px;
  font: 15px/1.55 "Segoe UI", -apple-system, Roboto, Helvetica, Arial, sans-serif;
  color: var(--ink); background: var(--bg);
}
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.2rem; margin: 34px 0 10px; padding-bottom: 5px;
     border-bottom: 2px solid var(--rule); }
h3 { font-size: 1.02rem; margin: 22px 0 6px; }
h4 { font-size: 0.92rem; margin: 16px 0 5px; color: var(--muted);
     text-transform: uppercase; letter-spacing: 0.06em; }
p { margin: 8px 0; }
code { font-family: "SF Mono", Consolas, monospace; font-size: 0.92em; }

.meta { color: var(--muted); font-size: 0.9rem; margin-bottom: 14px; }
.meta span { margin-right: 16px; white-space: nowrap; }

.banner { padding: 9px 14px; border-radius: 5px; font-weight: 600;
          margin: 12px 0; }
.banner.pass { background: #eaf6ef; color: var(--pass);
               border-left: 5px solid var(--pass); }
.banner.fail { background: #fdeceb; color: var(--fail);
               border-left: 5px solid var(--fail); }
.banner.warn { background: var(--warn-bg); color: var(--warn);
               border-left: 5px solid var(--warn); }

table { border-collapse: collapse; width: 100%; margin: 10px 0 16px;
        font-size: 0.9rem; }
th, td { border: 1px solid var(--rule); padding: 5px 9px; text-align: left; }
th { background: #f2f4f7; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.failed td { background: #fdeceb; }

.narrative { background: var(--narrative-bg);
             border-left: 4px solid var(--narrative-edge);
             padding: 10px 16px; margin: 16px 0; }
.narrative .tag { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
                  text-transform: uppercase; color: var(--narrative-edge); }
.narrative.commentary { background: transparent; border-left-color: var(--rule); }

.note { color: var(--muted); font-size: 0.88rem; margin: 4px 0 4px 14px; }
.prov { color: var(--muted); font-size: 0.82rem; margin-top: 8px; }
figure { margin: 16px 0; }
figure img { max-width: 100%; border: 1px solid var(--rule); }
figcaption { color: var(--muted); font-size: 0.86rem; margin-top: 5px; }
.sig td { height: 46px; vertical-align: bottom; }

@media print {
  body { max-width: none; padding: 0; font-size: 11pt; }
  h2 { break-after: avoid; }
  table, figure, .narrative { break-inside: avoid; }
  .banner { break-inside: avoid; }
  /* Repeat the unverified warning on every printed page: a page
     photocopied out of context must still carry it. */
  .running-warning { position: fixed; bottom: 0; left: 0; right: 0;
                     font-size: 8pt; color: var(--fail); text-align: center;
                     padding: 3px 0; border-top: 1px solid var(--fail); }
}
.running-warning { display: none; }
@media print { .running-warning { display: block; } }
"""


def _esc(text: str) -> str:
    return _html.escape(str(text), quote=False)


class HtmlRenderer(Renderer):
    """Render a report as one self-contained HTML document.

    Parameters
    ----------
    show_intermediates:
        Include the working values. Reviewers generally want them; a covering
        summary generally does not.
    float_format:
        Format string for magnitudes.
    """

    def __init__(
        self, show_intermediates: bool = True, float_format: str = "{:.4g}"
    ) -> None:
        self.show_intermediates = show_intermediates
        self.float_format = float_format

    # -- helpers --------------------------------------------------------------

    def _value_rows(self, values: dict[str, Value]) -> str:
        rows = []
        for value in values.values():
            magnitude, unit = value.display
            rows.append(
                "<tr>"
                f"<td><code>{_esc(value.symbol)}</code></td>"
                f"<td>{_esc(value.description)}</td>"
                f'<td class="num">{self.float_format.format(magnitude)}</td>'
                f"<td>{_esc(unit)}</td>"
                "</tr>"
            )
        return "".join(rows)

    def _value_table(self, values: dict[str, Value], caption: str) -> str:
        if not values:
            return ""
        return (
            f"<h4>{_esc(caption)}</h4><table>"
            "<thead><tr><th>Symbol</th><th>Description</th>"
            "<th>Value</th><th>Unit</th></tr></thead>"
            f"<tbody>{self._value_rows(values)}</tbody></table>"
        )

    # -- fixed sections -------------------------------------------------------

    def header(self, report: Report) -> str:
        sig = report.signature
        meta = []
        for label, value in (
            ("Job", sig.job_number),
            ("Project", sig.job_name),
            ("Element", sig.element),
            ("Revision", sig.revision),
        ):
            if value:
                meta.append(f"<span><strong>{label}:</strong> {_esc(value)}</span>")

        parts = [f"<h1>{_esc(report.title)}</h1>"]
        if meta:
            parts.append(f'<div class="meta">{"".join(meta)}</div>')

        if report.results:
            state = "pass" if report.passed else "fail"
            word = "PASS" if report.passed else "FAIL"
            parts.append(f'<div class="banner {state}">Result: {word}</div>')

        if not report.issuable:
            parts.append(
                '<div class="banner warn">NOT VERIFIED FOR ISSUE &mdash; one or '
                "more modules used in this report have not been checked against "
                "the printed standard. Development use only.</div>"
            )
        return "".join(parts)

    def inputs(self, result: CalcResult) -> str:
        return self._value_table(result.inputs, "Inputs")

    def basis_and_envelope(self, result: CalcResult) -> str:
        parts = []
        if result.basis:
            items = "".join(
                f"<li>{_esc(ref.citation)}"
                + (f" &mdash; {_esc(ref.note)}" if ref.note else "")
                + "</li>"
                for ref in result.basis
            )
            parts.append(f"<h4>Basis</h4><ul>{items}</ul>")

        env = result.envelope
        if env.limits or env.notes:
            rows = "".join(
                "<tr>"
                f"<td>{_esc(lim.name)}</td>"
                f'<td class="num">{lim.value:.4g}</td>'
                f"<td>{'' if lim.lower is None else f'{lim.lower:.4g}'}</td>"
                f"<td>{'' if lim.upper is None else f'{lim.upper:.4g}'}</td>"
                f"<td>{'yes' if lim.within else '<strong>NO</strong>'}</td>"
                "</tr>"
                for lim in env.limits
            )
            parts.append("<h4>Validity envelope</h4>")
            if rows:
                parts.append(
                    "<table><thead><tr><th>Quantity</th><th>Value</th>"
                    "<th>Lower</th><th>Upper</th><th>Within</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table>"
                )
            for note in env.notes:
                parts.append(f'<div class="note">{_esc(note)}</div>')
        return "".join(parts)

    def working(self, result: CalcResult) -> str:
        if not self.show_intermediates:
            return ""
        return self._value_table(result.intermediates, "Working")

    def checks(self, result: CalcResult) -> str:
        parts = [self._value_table(result.outputs, "Results")]
        if result.checks:
            rows = []
            for check in result.checks:
                cls = "" if check.passed else ' class="failed"'
                factor = check.display_factor
                unit = check.display_unit or check.unit
                rows.append(
                    f"<tr{cls}>"
                    f"<td>{_esc(check.label)}</td>"
                    f'<td class="num">{check.actual / factor:.4g}</td>'
                    f"<td>{_esc(check.operator)}</td>"
                    f'<td class="num">{check.limit / factor:.4g}</td>'
                    f"<td>{_esc(unit)}</td>"
                    f'<td class="num">{check.utilisation:.3f}</td>'
                    f"<td>{'PASS' if check.passed else '<strong>FAIL</strong>'}</td>"
                    "</tr>"
                )
            parts.append(
                "<h4>Checks</h4><table><thead><tr><th>Criterion</th><th>Actual</th>"
                "<th></th><th>Limit</th><th>Unit</th><th>Utilisation</th>"
                "<th>Status</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table>"
            )
        for message in result.messages:
            parts.append(f'<div class="note">{_esc(message)}</div>')
        return "".join(parts)

    def provenance(self, result: CalcResult) -> str:
        p = result.provenance
        checked = (
            f"checked by {_esc(p.checker)} on {p.checked_on.isoformat()}"
            if p.checker and p.checked_on
            else "not checked"
        )
        return (
            f'<div class="prov">{_esc(p.module)} v{_esc(p.version)} &middot; '
            f"{_esc(p.status.value)} &middot; {checked} &middot; "
            f"run {p.run_at.isoformat(timespec='seconds')}</div>"
        )

    def narrative(self, block: Narrative) -> str:
        parts = []
        if block.heading:
            parts.append(f"<h3>{_esc(block.heading)}</h3>")
        tag = (
            ""
            if block.kind is NarrativeKind.COMMENTARY
            else f'<div class="tag">{_esc(block.kind.value)}</div>'
        )
        paragraphs = "".join(
            f"<p>{_esc(para.strip())}</p>"
            for para in block.text.split("\n\n")
            if para.strip()
        )
        parts.append(
            f'<div class="narrative {block.kind.value}">{tag}{paragraphs}</div>'
        )
        return "".join(parts)

    def figures(self, report: Report) -> str:
        """Kept for the Renderer interface. Figures are emitted in body order
        by :meth:`render`, so this is only used by a caller that wants them
        collected together."""
        if not report.figures:
            return ""
        return "".join(self._figure(Figure(c, p)) for c, p in report.figures)

    def _figure(self, figure: Figure) -> str:
        return (
            f'<figure><img src="{_html.escape(figure.path)}" '
            f'alt="{_html.escape(figure.caption)}">'
            f"<figcaption>{_esc(figure.caption)}</figcaption></figure>"
        )

    def signature(self, report: Report) -> str:
        sig = report.signature
        designed_on = sig.designed_on.isoformat() if sig.designed_on else ""
        checked_on = sig.checked_on.isoformat() if sig.checked_on else ""
        parts = [
            "<h2>Signatures</h2>",
            '<table class="sig"><thead><tr><th></th><th>Name</th>'
            "<th>Signature</th><th>Date</th></tr></thead><tbody>",
            f"<tr><td>Designed</td><td>{_esc(sig.designed_by)}</td><td></td>"
            f"<td>{_esc(designed_on)}</td></tr>",
            f"<tr><td>Checked</td><td>{_esc(sig.checked_by)}</td><td></td>"
            f"<td>{_esc(checked_on)}</td></tr>",
            "</tbody></table>",
        ]
        if sig.notes:
            parts.append(f"<p>{_esc(sig.notes)}</p>")
        return "".join(parts)

    # -- driver ---------------------------------------------------------------

    def render(self, report: Report) -> str:
        """Emit the whole document, body items in the order they were added."""
        body = [self.header(report)]
        if report.preamble:
            body.append(f"<p>{_esc(report.preamble)}</p>")

        number = 0
        for item in report.items:
            if isinstance(item, Narrative):
                body.append(self.narrative(item))
            elif isinstance(item, Figure):
                body.append(self._figure(item))
            else:
                number += 1
                body.append(f"<h2>{number}. {_esc(item.name)}</h2>")
                body.extend(p for p in self.result_sections(item) if p)
                body.append(self.provenance(item))

        body.append(self.signature(report))

        if not report.issuable:
            body.append(
                '<div class="running-warning">NOT VERIFIED FOR ISSUE '
                "&mdash; development use only</div>"
            )

        return (
            "<!DOCTYPE html>\n<html lang=\"en\"><head>"
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_esc(report.title)}</title>"
            f"<style>{_CSS}</style></head><body>"
            + "".join(body)
            + "</body></html>\n"
        )
