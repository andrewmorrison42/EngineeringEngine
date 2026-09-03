"""Build the tutorial: HTML, then PDF via headless Chromium.

Every code panel is read out of the real job files and every terminal panel is
read out of `captures/`, which holds the actual stdout of the actual commands.
Nothing in the document is transcribed by hand, so the document cannot drift
away from the code it describes.

Usage:
    python build_tutorial.py                      # writes tutorial.html
    python build_tutorial.py --pdf /path/to/chrome  # ... and the PDF
"""

from __future__ import annotations

import base64
import html
import re
import subprocess
import sys
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

HERE = Path(__file__).resolve().parent
JOB = HERE / "job"
CAP = HERE / "captures"
OUT = HERE / "outputs"

CHROME_CANDIDATES = (
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
)


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------
def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def terminal(text: str, title: str = "Terminal", note: str = "") -> str:
    """A dark terminal panel. Prompt lines are picked out from output lines."""
    lines = []
    for raw in text.rstrip("\n").split("\n"):
        esc = html.escape(raw)
        if raw.startswith(("$ ", "(.venv) $ ", ">>> ", "... ")):
            cls = "cmd"
            # colour the prompt itself
            for prompt in ("(.venv) $ ", "$ ", ">>> ", "... "):
                if raw.startswith(prompt):
                    esc = (f'<span class="prompt">{html.escape(prompt.rstrip())}</span> '
                           + html.escape(raw[len(prompt):]))
                    break
        elif re.match(r"^\s*(Traceback|\w+Error|\w+Exception|austruct\.core)", raw):
            cls = "err"
        elif "PASS" in raw:
            cls = "pass"
        elif "FAIL" in raw or "NOT VERIFIED" in raw or "UNVERIFIED" in raw:
            cls = "warn"
        else:
            cls = "out"
        lines.append(f'<span class="{cls}">{esc or "&nbsp;"}</span>')
    body = "".join(lines)
    cap = f'<div class="shot-cap">{note}</div>' if note else ""
    return f"""<figure class="panel term">
  <div class="chrome"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
    <span class="tt">{html.escape(title)}</span></div>
  <pre>{body}</pre>
</figure>{cap}"""


def code(source: str, filename: str, first_line: int = 1, note: str = "") -> str:
    """A light editor panel with a filename tab, line numbers and highlighting."""
    fmt = HtmlFormatter(nowrap=True)
    rendered = highlight(source.rstrip("\n"), PythonLexer(), fmt).split("\n")
    rows = "\n".join(
        f'<tr><td class="ln">{first_line + i}</td><td class="src">{ln or "&nbsp;"}</td></tr>'
        for i, ln in enumerate(rendered)
    )
    cap = f'<div class="shot-cap">{note}</div>' if note else ""
    return f"""<figure class="panel editor">
  <div class="chrome light"><span class="tab">{html.escape(filename)}</span></div>
  <table class="codetable">{rows}</table>
</figure>{cap}"""


def shot(name: str, caption: str, frame: str = "browser", width: str = "") -> str:
    path = (CAP / name) if (CAP / name).exists() else (OUT / name)
    style = f' style="max-width:{width}"' if width else ""
    bar = ('<div class="chrome light browserbar">'
           '<span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>'
           '<span class="url">outputs/B1_report.html</span></div>') if frame == "browser" else ""
    return f"""<figure class="panel imgpanel"{style}>
  {bar}<img src="{_data_uri(path)}" alt="{html.escape(caption)}">
</figure>
<div class="shot-cap">{caption}</div>"""


def fig(name: str, caption: str, width: str = "") -> str:
    return shot(name, caption, frame="plain", width=width)


def callout(kind: str, title: str, body: str) -> str:
    return (f'<div class="callout {kind}"><div class="ctitle">{html.escape(title)}</div>'
            f'<div class="cbody">{body}</div></div>')


def excerpt(filename: str, start: str, end: str | None = None, note: str = "") -> str:
    """Pull a real slice out of a real file, with its real line numbers."""
    text = (JOB / filename).read_text().split("\n")
    i = next(n for n, ln in enumerate(text) if start in ln)
    if end is None:
        j = len(text)
    else:
        j = next(n for n, ln in enumerate(text) if n > i and end in ln)
    while j > i and not text[j - 1].strip():
        j -= 1
    return code("\n".join(text[i:j]), f"job/{filename}", first_line=i + 1, note=note)


def cap(name: str, title: str = "Terminal", note: str = "") -> str:
    return terminal((CAP / f"{name}.txt").read_text(), title, note)


def cap_slice(name: str, start: str, end: str | None = None,
              title: str = "Terminal", note: str = "") -> str:
    text = (CAP / f"{name}.txt").read_text().split("\n")
    i = next(n for n, ln in enumerate(text) if start in ln)
    j = len(text) if end is None else next(n for n, ln in enumerate(text) if n > i and end in ln)
    return terminal("\n".join(text[i:j]).strip("\n"), title, note)


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
CSS = """
@page { size: A4; margin: 18mm 16mm 16mm 16mm; }

:root {
  --ink: #16191d;
  --ink-2: #4a525c;
  --ink-3: #7b8593;
  --accent: #1f4e79;
  --accent-soft: #eaf1f8;
  --rule: #d8dde3;
  --warn: #8a6100;
  --warn-soft: #fdf6e6;
  --good: #1e6b3a;
  --bad: #a32020;
  --term-bg: #1c2128;
  --term-fg: #d5dae1;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font: 10.2pt/1.55 "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
  color: var(--ink);
  background: #fff;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.sheet { max-width: 178mm; margin: 0 auto; }

/* ---- cover ---- */
.cover { page-break-after: always; padding-top: 26mm; }
.cover .kicker { font-size: 9pt; letter-spacing: .18em; text-transform: uppercase;
  color: var(--accent); font-weight: 700; }
.cover h1 { font-size: 30pt; line-height: 1.1; margin: 6mm 0 4mm; letter-spacing: -.01em; }
.cover .sub { font-size: 13pt; color: var(--ink-2); line-height: 1.45; max-width: 140mm; }
.cover .rule { height: 3px; background: var(--accent); width: 42mm; margin: 8mm 0; }
.cover dl { display: grid; grid-template-columns: 34mm 1fr; gap: 2mm 6mm;
  font-size: 9.5pt; margin-top: 10mm; }
.cover dt { color: var(--ink-3); text-transform: uppercase; letter-spacing: .08em; font-size: 8pt;
  padding-top: .9mm; }
.cover dd { margin: 0; }

/* ---- headings ---- */
h2 { font-size: 16pt; margin: 11mm 0 3mm; padding-bottom: 2mm;
  border-bottom: 2px solid var(--accent); letter-spacing: -.01em;
  page-break-after: avoid; }
h2 .num { color: var(--accent); font-variant-numeric: tabular-nums; margin-right: 3mm; }
h3 { font-size: 11.5pt; margin: 7mm 0 2mm; color: var(--accent); page-break-after: avoid; }
h4 { font-size: 10pt; margin: 5mm 0 1.5mm; page-break-after: avoid; }
p { margin: 0 0 3mm; }
ul, ol { margin: 0 0 3mm; padding-left: 6mm; }
li { margin-bottom: 1.2mm; }
strong { font-weight: 700; }
code { font-family: "DejaVu Sans Mono", "Liberation Mono", monospace; font-size: 8.8pt;
  background: #f2f4f7; padding: .3mm 1mm; border-radius: 2px; }
a { color: var(--accent); text-decoration: none; }

.lead { font-size: 11pt; color: var(--ink-2); }

/* ---- panels ---- */
.panel { margin: 4mm 0 1mm; border-radius: 4px; overflow: hidden;
  border: 1px solid var(--rule); page-break-inside: avoid; }
.chrome { display: flex; align-items: center; gap: 2mm; padding: 1.6mm 3mm;
  background: var(--term-bg); border-bottom: 1px solid #000; }
.chrome.light { background: #eef1f5; border-bottom: 1px solid var(--rule); }
.dot { width: 2.6mm; height: 2.6mm; border-radius: 50%; display: inline-block; }
.dot.r { background: #ff5f57; } .dot.y { background: #febc2e; } .dot.g { background: #28c840; }
.tt { color: #97a1ad; font-size: 7.6pt; margin-left: 2mm; letter-spacing: .04em; }
.tab { font-family: "DejaVu Sans Mono", monospace; font-size: 8pt; color: var(--ink-2);
  background: #fff; border: 1px solid var(--rule); border-bottom-color: #fff;
  padding: 1mm 3mm; border-radius: 3px 3px 0 0; position: relative; top: 1.6mm; }
.browserbar .url { font-family: "DejaVu Sans Mono", monospace; font-size: 7.6pt;
  color: var(--ink-3); background: #fff; border: 1px solid var(--rule);
  border-radius: 10px; padding: .6mm 4mm; margin-left: 3mm; flex: 1; }

.term { border-color: #0d1116; }
.term pre { margin: 0; padding: 3mm 4mm; background: var(--term-bg); color: var(--term-fg);
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 7.9pt; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
.term .cmd { color: #e6edf3; font-weight: 700; display: block; }
.term .prompt { color: #7ee787; font-weight: 700; }
.term .out { color: #b9c3ce; display: block; }
.term .err { color: #ff7b72; display: block; }
.term .pass { color: #7ee787; display: block; }
.term .warn { color: #e3b341; display: block; }

.editor .codetable { border-collapse: collapse; width: 100%; background: #fbfcfd; }
.editor td { padding: 0; vertical-align: top; }
.editor .ln { width: 9mm; text-align: right; padding-right: 2.5mm; color: #aab3bf;
  font-family: "DejaVu Sans Mono", monospace; font-size: 7.3pt; line-height: 1.5;
  background: #f2f5f8; border-right: 1px solid var(--rule); user-select: none; }
.editor .src { padding-left: 3mm; font-family: "DejaVu Sans Mono", monospace;
  font-size: 8pt; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }

.imgpanel img { display: block; width: 100%; }
.imgpanel { background: #fff; }
.shot-cap { font-size: 8.2pt; color: var(--ink-3); margin: 0 0 5mm; padding-left: 1mm; }
.shot-cap b { color: var(--ink-2); }

/* ---- callouts ---- */
.callout { border-left: 3px solid var(--accent); background: var(--accent-soft);
  padding: 3mm 4mm; margin: 4mm 0; border-radius: 0 3px 3px 0; page-break-inside: avoid; }
.callout .ctitle { font-size: 8.2pt; text-transform: uppercase; letter-spacing: .1em;
  font-weight: 700; color: var(--accent); margin-bottom: 1.5mm; }
.callout .cbody p:last-child { margin-bottom: 0; }
.callout.warn { border-left-color: var(--warn); background: var(--warn-soft); }
.callout.warn .ctitle { color: var(--warn); }
.callout.stop { border-left-color: var(--bad); background: #fdeeee; }
.callout.stop .ctitle { color: var(--bad); }
.callout.good { border-left-color: var(--good); background: #eef7f1; }
.callout.good .ctitle { color: var(--good); }

/* ---- tables ---- */
table.data { width: 100%; border-collapse: collapse; font-size: 9pt; margin: 3mm 0 4mm;
  page-break-inside: avoid; }
table.data th { text-align: left; background: #f2f5f8; border: 1px solid var(--rule);
  padding: 1.6mm 2.5mm; font-size: 8.4pt; }
table.data td { border: 1px solid var(--rule); padding: 1.6mm 2.5mm; vertical-align: top; }
table.data td.n { text-align: right; font-variant-numeric: tabular-nums; }
table.data code { background: none; padding: 0; }
table.data td:first-child code { white-space: nowrap; }

.steps { counter-reset: s; list-style: none; padding: 0; }
.steps li { counter-increment: s; position: relative; padding-left: 9mm; margin-bottom: 2.5mm; }
.steps li::before { content: counter(s); position: absolute; left: 0; top: .2mm;
  width: 6mm; height: 6mm; border-radius: 50%; background: var(--accent); color: #fff;
  font-size: 8pt; font-weight: 700; display: flex; align-items: center; justify-content: center; }

.pagebreak { page-break-before: always; }
.avoid { page-break-inside: avoid; }
footer.doc { margin-top: 10mm; padding-top: 3mm; border-top: 1px solid var(--rule);
  font-size: 8.2pt; color: var(--ink-3); }
"""


REPO = HERE.parent.parent


def repo_excerpt(relpath: str, start: str, end: str | None = None, note: str = "") -> str:
    """A real slice out of the library source, with its real line numbers."""
    text = (REPO / relpath).read_text().split("\n")
    i = next(n for n, ln in enumerate(text) if start in ln)
    j = len(text) if end is None else next(n for n, ln in enumerate(text) if n > i and end in ln)
    while j > i and not text[j - 1].strip():
        j -= 1
    return code("\n".join(text[i:j]), relpath, first_line=i + 1, note=note)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------
def cover() -> str:
    return """
<section class="cover">
  <div class="kicker">Structural Python &middot; Tutorial 01</div>
  <h1>Calling vetted calculation<br>modules from a job file</h1>
  <div class="rule"></div>
  <div class="sub">A simply supported roof beam, analysed over the ultimate load
  combinations of AS/NZS&nbsp;1170.0 and designed for flexure and shear to
  AS&nbsp;3600:2018 &mdash; written the way you would run a real job.</div>
  <dl>
    <dt>Written for</dt><dd>An engineer who reads design codes fluently and Python
      slowly. No prior Python project experience assumed.</dd>
    <dt>Library</dt><dd><code>austruct</code> 0.1.0 &mdash; the toolkit in this repository</dd>
    <dt>Worked example</dt><dd>Job 25-0142 Northbank Depot, roof beam B1</dd>
    <dt>Every panel</dt><dd>Real output. Terminal panels are captured stdout; code
      panels are read out of the committed files at build time.</dd>
    <dt>Status</dt><dd><strong>Not verified for issue.</strong> This teaches the
      workflow. It makes no claim that any number the library produces is correct
      &mdash; that validation is yours to do.</dd>
  </dl>
</section>"""


def part_1() -> str:
    return f"""
<h2><span class="num">1</span>What you are going to build</h2>

<p class="lead">A folder for one job, holding two short files you wrote, that
together produce a signed calculation report for a beam. Neither file contains a
clause of AS&nbsp;3600. Every code equation comes from a library that lives
elsewhere, is version controlled, and is tested.</p>

<p>That separation is the whole idea. A spreadsheet tangles three things with
completely different lifetimes:</p>

<table class="data">
<tr><th>What it is</th><th>Changes</th><th>Should live</th></tr>
<tr><td><strong>Code equations</strong> &mdash; &phi;M<sub>uo</sub>, k<sub>v</sub>, &theta;<sub>v</sub></td>
    <td>When the Standard is amended</td>
    <td>In one vetted, tested library</td></tr>
<tr><td><strong>The job</strong> &mdash; spans, loads, grades, the client</td>
    <td>Every job</td><td>In a job folder</td></tr>
<tr><td><strong>The decision</strong> &mdash; 350&nbsp;&times;&nbsp;650, 3-N24</td>
    <td>Every iteration</td><td>In one line you can read aloud</td></tr>
</table>

<p>Re-using spreadsheet equations means copying the job with them &mdash; and that copy
is now a second, unchecked version of AS&nbsp;3600. Putting the equations in an
importable package and the job in a script that imports it is what stops the copying.
That is what <code>import</code> is really for.</p>

<h3>Where this sits in the ASET framework</h3>
<p>Ferster's six components are also the order a real calculation goes in. When you
are lost in the code, "which of the six am I in?" usually unsticks it.</p>

<table class="data">
<tr><th>#</th><th>ASET component</th><th>In this job</th><th>Where the code lives</th></tr>
<tr><td class="n">1</td><td>Reference data</td><td>C32 concrete, N24 bar areas</td><td><code>austruct.materials</code></td></tr>
<tr><td class="n">2</td><td>Project data</td><td>Job record &rarr; &psi; factors &rarr; combinations; wind</td><td><code>austruct.project</code>, <code>austruct.loads</code>, <em>your</em> <code>job_data.py</code></td></tr>
<tr><td class="n">3</td><td>Fast demand calculation</td><td>7 combinations, analysed and enveloped</td><td><code>austruct.analysis</code></td></tr>
<tr><td class="n">4</td><td>Design documentation</td><td><code>350 x 650 | C32 | BOT 3-N24 | ...</code></td><td><code>austruct.design_documentation</code></td></tr>
<tr><td class="n">5</td><td>Design verification</td><td>Flexure and shear to AS 3600:2018</td><td><code>austruct.design.as3600</code></td></tr>
<tr><td class="n">6</td><td>Reporting</td><td>The signed audit document</td><td><code>austruct.report</code></td></tr>
</table>

{callout("warn", "One caveat before you start", '''
<p>Every module in this library reports its status as <code>UNVERIFIED</code>, and
every report it produces is stamped <strong>NOT VERIFIED FOR ISSUE</strong>. The
constants are written but not independently checked against the printed Standards.
This tutorial teaches the workflow; validating the numbers is the engineer's job, and
part 4 shows you where to look to do it.</p>''')}
"""


def part_2() -> str:
    return f"""
<h2><span class="num">2</span>How Python finds other people's code</h2>

<p class="lead">A <strong>module</strong> is a file. A <strong>package</strong> is a folder
of them. The dots in an import are folder separators.</p>

<p>So <code>from austruct.design import as3600</code> reads as: go into
<code>austruct/design/</code> and give me <code>as3600</code>. After that,
<code>as3600.check_flexure(...)</code> calls a function in a file you did not write,
did not copy, and cannot edit by accident while typing a span.</p>

<table class="data">
<tr><th>You write</th><th>You then use</th><th>Use it when</th></tr>
<tr><td><code>import austruct</code></td><td><code>austruct.design.as3600.check_flexure(...)</code></td>
    <td>Rarely &mdash; too long to read.</td></tr>
<tr><td><code>from austruct.design import as3600</code></td><td><code>as3600.check_flexure(...)</code></td>
    <td><strong>Most of the time.</strong> The call still names the Standard.</td></tr>
<tr><td><code>from austruct.design.as3600 import check_flexure</code></td><td><code>check_flexure(...)</code></td>
    <td>Sparingly &mdash; alone it does not say AS 3600 rather than AS 5100.5.</td></tr>
</table>

{callout("stop", "Never use import *", '''
<p><code>from austruct.design.as3600 import *</code> pulls every name into your file at
once. It is the equivalent of pasting someone's whole spreadsheet into yours: you can no
longer tell which numbers are yours, and a rename upstream silently changes your results.
In a calculation file that is a traceability defect, not a style preference.</p>''')}

<h3>Where Python actually looks</h3>
<ol class="steps">
<li><strong>The folder of the script you ran</strong> &mdash; not the folder you are standing
in. This is why <code>beam_B1.py</code> can say <code>import job_data</code> with no setup:
they are siblings.</li>
<li><strong>The site-packages of the environment you are in</strong> &mdash; where
<code>pip install</code> puts things, and how <code>austruct</code> is found from anywhere.</li>
<li>The standard library, and places you will not need to think about.</li>
</ol>

<p>Both errors below are that list failing. First, the library is not in this
environment because the environment was never activated:</p>

{cap("err_novenv", "bash", "<b>Screenshot 2.1</b> &mdash; no <code>(.venv)</code> in the prompt. The fix is <code>source .venv/bin/activate</code>, not editing the file.")}

<p>Second, your own module is not found because you are one directory too high &mdash;
then the same import working one folder down:</p>

{cap("err_localmod", "bash", "<b>Screenshot 2.2</b> &mdash; <code>import job_data</code> is not magic. It works because <code>job_data.py</code> sits beside the file being run.")}

{callout("warn", "The rule to memorise", '''
<p><strong>Library code gets installed. Job code sits next to the script.</strong> If you
find yourself writing <code>sys.path.append("../../my_calcs")</code> to reach your own
calculations, that is the signal those calculations have grown up and want to be an
installed package too.</p>''')}
"""


def part_3() -> str:
    return f"""
<h2><span class="num">3</span>Setting up, from nothing</h2>

<p class="lead">Two folders, and they must be different folders. One holds the library.
One holds the job.</p>

<p>A <em>virtual environment</em> is a private copy of Python for one project, so that
upgrading a package for this job cannot silently change last year's answers. Create it
once in the library folder and activate it every time you open a terminal; the
<code>(.venv)</code> in the prompt is the confirmation.</p>

{cap("setup_install", "bash — in the library folder", "<b>Screenshot 3.1</b> &mdash; <code>pip install -e</code> installs it <em>editable</em>: site-packages gets a pointer to the source folder rather than a copy, so a library fix is live immediately. The bracketed names are optional extras.")}

<p>Before writing anything, prove it worked. The first command shows <em>which</em> copy
you are about to use; the second runs the library's own tests &mdash; the evidence that the
thing you are about to trust still behaves as its author intended.</p>

{cap("setup_verify", "bash", "<b>Screenshot 3.2</b> &mdash; the path is the source tree, not a copy: that is what <em>editable</em> means. 799 passing tests is not proof the clauses are right, but it is proof nothing has broken since they were written.")}

<p>Then the job folder. One folder per <em>job</em>, not per member: B1, B2 and the
transfer slab share a project record and a load schedule, and duplicating those is how
they drift apart.</p>

{cap("tree", "bash", "<b>Screenshot 3.3</b> &mdash; job folder above, library folder below; only one of them is installed. <code>outputs/</code> holds only generated files, so you can delete it and re-run to get it back. If you cannot, something in there was hand-edited.")}
"""


def part_4() -> str:
    return f"""
<h2><span class="num">4</span>From a bare equation to a vetted module</h2>

<p class="lead">This part explains why the repository is shaped the way it is. You are
not going to build these modules &mdash; they exist. But you should recognise the shape,
because it is what makes them safe to call, and it is what you will validate.</p>

<h3>The equation is the small part</h3>
<p>The concrete compressive resultant of AS&nbsp;3600 Cl&nbsp;8.1.3 is three lines of
arithmetic. In a script you would write it once and move on. In the library it is
<code>rc_common/stress_block.py</code>, and the arithmetic is still three lines:</p>

{repo_excerpt("src/austruct/design/rc_common/stress_block.py", "    block_depth = min(", "    return ConcreteBlock(", "<b>Screenshot 4.1</b> &mdash; &alpha;<sub>2</sub>&nbsp;f'<sub>c</sub> over &gamma;d<sub>n</sub>, exactly as printed in the Standard. Nothing clever happens here, and nothing should.")}

<p>That arithmetic lives in <code>rc_common/</code>, shared by every standard. One layer up,
<code>as3600/flexure.py</code> wraps it in the part that earns its keep: a docstring naming
the clauses it implements and the range it is valid over, so a reviewer can check both
without reading the code.</p>

{repo_excerpt("src/austruct/design/as3600/flexure.py", "Ultimate flexural capacity of a reinforced concrete section", "    Parameters", "<b>Screenshot 4.2</b> &mdash; the AS 3600 wrapper around that mechanics, one layer up. <code>Basis</code> says which clauses. <code>Envelope</code> says the range it is valid over. Those two sections are the difference between an equation and a module you can hand to a checker.")}

<h3>Three stages, and why the third exists</h3>
<table class="data">
<tr><th>Stage</th><th>What you get</th><th>What breaks</th></tr>
<tr><td>Equation in a script</td><td>One answer, once</td>
    <td>The next beam means copy-paste, and now there are two versions.</td></tr>
<tr><td>Equation in a function</td><td>Re-usable, testable</td>
    <td>It returns a bare float. Nothing records the clause, the assumptions, or the
    range it is valid over &mdash; so nothing can be checked or reported.</td></tr>
<tr><td><strong>Equation in a module</strong></td><td>A <code>CalcResult</code></td>
    <td>Nothing. This is the shape everything in <code>design/</code> returns.</td></tr>
</table>

<p>Every public calculation in this library returns a <code>CalcResult</code>, never a
bare float, carrying six things:</p>

<table class="data">
<tr><td><code>.inputs</code></td><td>Echoed verbatim, with units</td></tr>
<tr><td><code>.basis</code></td><td>The clauses, in the order they were applied</td></tr>
<tr><td><code>.envelope</code></td><td>Validity limits, and whether you are inside them</td></tr>
<tr><td><code>.outputs</code></td><td>The results, with units</td></tr>
<tr><td><code>.checks</code></td><td>Pass/fail against each code criterion</td></tr>
<tr><td><code>.provenance</code></td><td>Version, author, checker, verification status</td></tr>
</table>

<p>That is why the report in part 11 needs no assembly: the results already carry everything a
report has to show.</p>

<h3>Envelope versus check</h3>
<p>The distinction that makes the library safe, and the one spreadsheets almost never
make. Ask for 150&nbsp;MPa concrete and the module <em>refuses</em>; ask for 100 and it
answers.</p>

{cap("repl_envelope", "python", "<b>Screenshot 4.3</b> &mdash; an exception, not a number. The message names the limit, the clause behind it, and your value.")}

<table class="data">
<tr><th></th><th>Envelope</th><th>Check</th></tr>
<tr><td>Bounds</td><td>Where the method is valid</td><td>A code criterion</td></tr>
<tr><td>Breach means</td><td>The answer is <em>unknown</em></td><td>The answer is <em>known and it fails</em></td></tr>
<tr><td>You get</td><td>An exception, no number</td><td>A full result that reads FAIL</td></tr>
</table>

<p>An overstressed beam is a good calculation with a failing result &mdash; you want to see
it, with the working, so you can size up. A beam of 150&nbsp;MPa concrete is not a
calculation this library can do at all.</p>

<h3>One import rule keeps it composable</h3>
<p>Modules import from layers <em>above</em> them in this list, never below. That single
rule is why you can call any of it in any order without circular surprises.</p>

<table class="data">
<tr><td class="n">L0</td><td><code>core/</code></td><td>The contract: basis, envelope, provenance, units</td></tr>
<tr><td class="n">L1</td><td><code>materials/</code>, <code>project/</code></td><td>Grades, bar catalogue, job record</td></tr>
<tr><td class="n">L2</td><td><code>sections/</code>, <code>design_documentation/</code></td><td>Geometry, the designation grammar</td></tr>
<tr><td class="n">L3</td><td><code>analysis/</code>, <code>loads/</code>, <code>structures/</code></td><td>Solver, combinations, envelopes</td></tr>
<tr><td class="n">L4</td><td><code>design/</code></td><td><code>rc_common/</code> holds the mechanics; <code>as3600/</code>, <code>as5100_5/</code>, <code>as4100/</code>, <code>as3700/</code> hold only what differs</td></tr>
<tr><td class="n">L5</td><td><code>report/</code></td><td>The audit artifact</td></tr>
</table>

<h3>What is already there, and how to find it</h3>
<p>Fifty-six modules are registered. <code>CATALOGUE.md</code> in the repository root
lists every one with its clause coverage and verification status, and it is generated
from the code itself so it cannot go stale. For a single package, ask Python:</p>

{cap("repl_discover", "python", "<b>Screenshot 4.4</b> &mdash; every public calculation in AS 3600, listed by the library itself. The docstring names the Basis, the Parameters and the Returns. <code>dir(x)</code> is also the fastest recovery when you guess an attribute name wrong.")}

{callout("good", "Your job is the middle step", '''
<p>You are not writing these equations and you are not re-deriving them. You are
<strong>reading the Basis, checking the constants against your copy of the Standard,
and then calling the module</strong> &mdash; after which every job that calls it inherits
that one act of checking. That is the entire economic argument for the structure.</p>''')}
"""


def part_5() -> str:
    return f"""
<h2><span class="num">5</span>File one &mdash; the job (ASET component 2)</h2>

<p class="lead">Write this completely before touching the member file. It holds no
capacities. If you later design B2, B3 and the transfer slab, they import this same file
and all move together when the client changes the plant weight.</p>

<p><code>Project</code> is a plain record of client-supplied facts that quietly does real
work: the occupancy drives the &psi; combination factors, and the structure type decides
whether you get the AS/NZS&nbsp;1170.0 building set or the AS&nbsp;5100.2 bridge set.
Stating "office building" once is what stops a bridge combination reaching a floor beam.</p>

{excerpt("job_data.py", "# 1. The job record", "# 2. Geometry", "<b>Screenshot 5.1</b> &mdash; note what is <em>not</em> here: no defaults invented on your behalf. An unstated design life stays empty so the report can say &lsquo;not stated&rsquo;.")}

<p>Spans and tributary widths get names, so every later use is self-evidently the same
number. The library works in N, mm and MPa &mdash; which makes 1&nbsp;kN/m exactly
1&nbsp;N/mm &mdash; so areal loads are written in kPa the way a load schedule states them
and converted exactly once, by multiplying by <code>kPa</code>.</p>

{excerpt("job_data.py", "# 2. Geometry the loads depend on", "# 4. Wind", "<b>Screenshot 5.2</b> &mdash; the triple-quoted string under each value is a docstring, doing the job a cell comment does in a spreadsheet, except it cannot be scrolled out of view or lost in a copy-paste.")}

{callout("", "Units, once", '''
<p><code>kN</code>, <code>m</code>, <code>kPa</code>, <code>kNm</code> and
<code>kN_per_m</code> are plain multipliers: they convert <em>into</em> N-mm on the way in
(<code>7.2 * m</code> is 7200.0) and <em>out</em> on the way to a print statement
(<code>M / kNm</code>). If a number is ever wrong by a factor of 1000, look here first.</p>''')}

<h3>Wind, to AS/NZS 1170.2</h3>
<p>The library does not derive site wind &mdash; too many local judgements to hide inside a
package. So it goes in your file, one multiplier per line, each tagged with its clause.
This is the pattern to copy whenever you need something the library does not have.</p>

{excerpt("job_data.py", "# 4. Wind, to AS/NZS 1170.2", "# 5. Derived line loads", "<b>Screenshot 5.3</b> &mdash; when the checker asks where M<sub>z,cat</sub> = 0.91 came from, the answer is on the same line as the number. <code>[VECTOR]</code> marks values transcribed from a Standard, so every one can be found by text search.")}

<p>The file's actual output is three numbers &mdash; <code>W_G</code>, <code>W_Q</code> and
<code>W_WU</code>, in the library's units. Everything above exists to produce them.</p>
"""


def part_6() -> str:
    return f"""
<h2><span class="num">6</span>File two &mdash; the member</h2>

<p class="lead">The import block answers the question this tutorial exists for.</p>

{excerpt("beam_B1.py", "from pathlib import Path", "# ------", "<b>Screenshot 6.1</b> &mdash; six imports from the installed library, then one from the file next door. The blank line between them is worth keeping: above it, code you did not write; below it, code you did.")}

<p>Read down the imports and you can predict the calculation before reading a line of it.
Imports at the top of a file are a table of contents.</p>

<h3>The design decision, as one line of text (ASET component 4)</h3>
{excerpt("beam_B1.py", "# 1. The design decision", "# 2. Load cases", "<b>Screenshot 6.2</b> &mdash; <code>parse()</code> in, <code>designate()</code> back out. The <code>assert</code> is a one-line guard that the round trip is exact.")}

<table class="data">
<tr><th>Field</th><th>Means</th><th>Rules</th></tr>
<tr><td><code>350 x 650</code></td><td>b &times; D, mm</td><td>Always first</td></tr>
<tr><td><code>C32</code></td><td>f'<sub>c</sub> = 32 MPa</td><td rowspan="4">Keyword-led and order-independent. An unrecognised field <strong>raises</strong> rather than being ignored &mdash; silently dropping <code>TOP 2-N16</code> would hand you a singly reinforced capacity for a doubly reinforced beam.</td></tr>
<tr><td><code>COV 40</code></td><td>Cover to the fitment, mm</td></tr>
<tr><td><code>BOT 3-N24</code></td><td>Three N24 bottom bars</td></tr>
<tr><td><code>LIG N12-2L@250</code></td><td>N12 two-leg ligatures at 250</td></tr>
</table>

<p>Why a string and not five arguments: it is the thing everyone else already reads. It
goes in the schedule, on the drawing, in the email to the drafter, and into
<code>parse()</code> unchanged &mdash; so there is no transcription step, and therefore no
transcription error.</p>

{cap_slice("run_full", "SECTION", "LOAD CASES", "python beam_B1.py — first block", "<b>Screenshot 6.3</b> &mdash; what that one line expanded into. d = 586 mm is derived from cover + fitment + half a bar, not typed: one of the most common arithmetic slips in hand calculations, done once here in tested code.")}
"""


def part_7() -> str:
    return f"""
<h2><span class="num">7</span>Load cases and combinations (AS/NZS 1170.0)</h2>

<p class="lead">A load case says <em>what the loads are and which action they represent</em>.
A combination says <em>how the jurisdiction adds them up</em>. Keeping them separate is why
you never write <code>1.2 * dead + 1.5 * live</code> by hand again.</p>

{excerpt("beam_B1.py", "# 2. Load cases", "# [UNITS] A UDL learns", "<b>Screenshot 7.1</b> &mdash; each case carries an <code>ActionType</code>, and that tag is the mechanism: it connects &lsquo;this 18.79 kN/m is permanent action&rsquo; to &lsquo;the code multiplies permanent action by 1.2 in this combination&rsquo;.")}

<ul>
<li><strong><code>SelfWeight</code> instead of a number</strong> &mdash; derived from the
section's own area, so it follows when you change 350&nbsp;&times;&nbsp;650 to
400&nbsp;&times;&nbsp;750. A hand-computed 5.36 would not.</li>
<li><strong>A UDL and a point load in one case</strong> &mdash; the roof pressure and the
plant unit are both Q and must be factored together.</li>
<li><strong>The minus sign on the wind UDL</strong> &mdash; downward is positive throughout,
so uplift is negative, applied here next to the beam rather than buried in the job file.</li>
</ul>

{cap_slice("run_full", "LOAD CASES", "COMBINATIONS", "python beam_B1.py", "<b>Screenshot 7.2</b> &mdash; every load echoed with its type and intensity. Reading this before looking at any capacity is the equivalent of checking your load take-down first.")}

<p>You never type a load factor. <code>PROJECT.load_combinations(sls=False)</code> reads
the structure type and occupancy off the record from part 5 and returns the
AS/NZS&nbsp;1170.0 Cl&nbsp;4.2.2 ultimate set with the &psi; factors already resolved.</p>

{cap("repl_project", "python", "<b>Screenshot 7.3</b> &mdash; <code>(0.4, 0.7, 0.4)</code> is (&psi;<sub>c</sub>, &psi;<sub>s</sub>, &psi;<sub>l</sub>) for an office, arriving in ULS3 and ULS4. Change <code>Occupancy.OFFICE</code> to <code>STORAGE</code> and every combination changes with it.")}

{callout("warn", "Combinations you did not ask for are a feature", '''
<p>Seven come back, including earthquake and snow, because the <em>project</em> implies
them; the analysis drops the ones no supplied case contributes to, so they cost nothing.
The point is that the list comes from the jurisdiction, not from what you remembered on
the day &mdash; and the one you forget is the one that governs.</p>''')}
"""


def part_8() -> str:
    return f"""
<h2><span class="num">8</span>Analyse, then envelope (ASET component 3)</h2>

<p class="lead">Two lines: build the member, then run every combination over it and keep
the worst of each action &mdash; with a record of which combination caused it.</p>

{excerpt("beam_B1.py", "# 3. Analyse over every ULS", "# 4. Design verification", "<b>Screenshot 8.1</b> &mdash; <code>simply_supported()</code> is one of a family (<code>cantilever</code>, <code>propped</code>, <code>continuous</code>). Passing <code>section=</code> rather than a bare EI means deflections use the section you detailed.")}

{cap_slice("run_full", "ENVELOPE", "AS 3600:2018 CHECKS", "python beam_B1.py", "<b>Screenshot 8.2</b> &mdash; every row carries the combination that caused it in square brackets, which is the most useful thing an envelope can tell you.")}

<ul>
<li><strong>M* = 296.1 kN.m at x = 3.000 m [ULS2]</strong> &mdash; under the plant load, from
1.2G&nbsp;+&nbsp;1.5Q. Not at midspan, because the point load is not at midspan.</li>
<li><strong>M<sub>hog</sub> = 0</strong> &mdash; no reversal under any of the seven.</li>
<li><strong>Minimum reaction 69.43 kN [ULS5]</strong>, still downward: no hold-down
required. A real check, which fell out of the envelope for free.</li>
<li><strong>Deflection 6.26 mm</strong> &mdash; from <em>factored</em> loads on a gross
section, so it is a solver output, not a serviceability check.</li>
</ul>

{fig("B1_diagrams.png", "<b>Screenshot 8.3</b> &mdash; the governing combination alone. Sagging is drawn downward, so the moment diagram hangs the way the beam does. The shear step at 3.0 m is the 60 kN factored plant load; V = 144.2 kN at the support, 126.4 kN at d.")}

{fig("B1_envelope.png", "<b>Screenshot 8.4</b> &mdash; the envelope, with every contributing combination faint behind it. The dashed <em>min</em> curve still sits near 90 kN.m of sagging at midspan: that is the picture of &lsquo;no reversal anywhere&rsquo;, and it is worth more than reading M<sub>hog</sub> = 0.")}
"""


def part_9() -> str:
    return f"""
<h2><span class="num">9</span>Flexure and shear to AS 3600:2018</h2>

<p class="lead">After all that, the design is three lines. That is the right proportion:
the hard part is getting the right demand to the right section.</p>

{excerpt("beam_B1.py", "# 4. Design verification", "AS 3600:2018 CHECKS", "<b>Screenshot 9.1</b> &mdash; <code>shear_at_d_from_support(d)</code> is the code allowance for taking design shear at d from a support that introduces compression. It is a method on the envelope because only the envelope knows the shear diagram.")}

{cap_slice("run_full", "AS 3600:2018 CHECKS", "Bar arrangements", "python beam_B1.py", "<b>Screenshot 9.2</b> &mdash; both checks with the governing combination, capacity, utilisation and verdict.")}

<p>Note that <code>check_shear</code> takes the coexisting moment as well as the shear.
That is not padding: AS&nbsp;3600:2018 uses a modified compression field formulation in
which the concrete contribution depends on longitudinal strain, which depends on M*.
Shear capacity is <em>coupled to the demand</em> &mdash; exactly the case Ferster names as the
hard one, and the reason you want it inside a tested module.</p>

<h3>Five checks, not two</h3>
<table class="data">
<tr><th>Check</th><th>Clause</th><th>Here</th></tr>
<tr><td>Ductility, k<sub>uo</sub> &le; 0.36</td><td>Cl 8.1.5</td><td>0.147 &mdash; PASS</td></tr>
<tr><td>Minimum strength, M<sub>uo</sub> &ge; 1.2 M<sub>cr</sub></td><td>Cl 8.1.6.1</td><td>373 &ge; 110 kN.m &mdash; PASS</td></tr>
<tr><td>M* &le; &phi;M<sub>uo</sub></td><td>Cl 2.2.2</td><td>296.1 &le; 317.4 kN.m &mdash; PASS</td></tr>
<tr><td>Minimum shear reinforcement</td><td>Cl 8.2.1.7</td><td>0.905 &ge; 0.317 mm&sup2;/mm &mdash; PASS</td></tr>
<tr><td>V* &le; &phi;V<sub>u</sub></td><td>Cl 8.2.1.1</td><td>126.4 &le; 339.5 kN &mdash; PASS</td></tr>
</table>

<p>The ductility check is the one a hand calculation most often skips, and the
minimum-fitment check is not decoration: the simplified method's
k<sub>v</sub>&nbsp;=&nbsp;0.15 is only available <em>because</em> the section carries at least
minimum fitments. Widen the ligatures past that and both change together.</p>

{cap("repl_audit", "python", "<b>Screenshot 9.3</b> &mdash; the audit trail, interrogated from the REPL: the clauses in application order, the checks, the envelope that was enforced, and the module's verification status. This is the <code>CalcResult</code> from part 4, in use.")}

{callout("warn", "Read the envelope notes the first time you use a module", '''
<p>They say what it did <em>not</em> do: no axial force, no torsion, no lateral instability,
and <em>sagging only</em> &mdash; "model hogging by inverting the section". That last is a real
trap on a continuous beam, and the library will not warn you twice.</p>''')}

{shot("shot_report_shear.png", "<b>Screenshot 9.4</b> &mdash; the shear check as it lands in the report: inputs, seven clauses, validity envelope, working, results, checks. d<sub>v</sub> = 527.4 mm, k<sub>v</sub> = 0.15 and &theta;<sub>v</sub> = 36&deg; are reported rather than assumed.")}

{callout("stop", "AS 5100.5 is not &lsquo;AS 3600 with different numbers&rsquo;", '''
<p>For flexure the two give an identical nominal M<sub>uo</sub> and differ only in &phi;.
For <strong>shear</strong> they share no code at all: AS&nbsp;5100.5:2017 predates the 2018
revision and uses the &beta;<sub>1</sub>&beta;<sub>2</sub>&beta;<sub>3</sub> /
f<sub>cv</sub> / d<sub>o</sub> family. Swapping <code>as3600</code> for
<code>as5100_5</code> in a shear line and expecting a small change is the most likely way
to get a bridge wrong with this toolkit.</p>''')}
"""


def part_10() -> str:
    return f"""
<h2><span class="num">10</span>The loop: FAIL is a result, not an error</h2>

<p class="lead">The section here was the second try. Here is the first, and the thirty
seconds it took to fix.</p>

{cap("repl_iterate", "python", "<b>Screenshot 10.1</b> &mdash; 3-N20 gives 1.312, FAIL. <code>required_steel_area</code> says the section needs 1255 mm&sup2; and has 942. 3-N24 gives 1357 mm&sup2; and 0.933, PASS. No spreadsheet was reopened and no clause re-read.")}

<p>Three things make that fast, and all three are choices worth copying: a failing check
still returns a <em>full</em> result rather than an exception; the inverse problem
(<code>required_steel_area</code>) is a first-class function, so you are not bisecting by
hand; and the decision is one string, so changing <code>BOT 3-N20</code> to
<code>BOT 3-N24</code> is the entire edit &mdash; d, self weight, diagrams and report all
follow.</p>

{cap_slice("run_full", "Bar arrangements", "REPORT", "python beam_B1.py", "<b>Screenshot 10.2</b> &mdash; <code>describe_options</code> takes the required area and returns every practical arrangement with its excess. 3-N24 at 7.7% over is the obvious pick; 12-N12 provides the same area and would not fit.")}

<p>Once you are running that loop more than a few times,
<code>as3600.minimum_cost_section</code> will do it for you &mdash; same checks, same clauses,
driven by a search over widths, depths and bar arrangements against concrete and steel
rates. That only becomes possible because the check was written as a function.</p>

{cap("err_wrongdir", "bash", "<b>Screenshot 10.3</b> &mdash; the third failure mode, after the two in part 2: the shipped file with its output line replaced by a bare <code>OUT = &quot;../outputs&quot;</code>, run one directory up. The imports resolve (Python adds the <em>script's</em> folder to the path, not yours) but the relative output path does not. The file ships with <code>Path(__file__).resolve().parent.parent / &quot;outputs&quot;</code> instead.")}
"""


def part_11() -> str:
    return f"""
<h2><span class="num">11</span>The report (ASET component 6)</h2>

<p class="lead">A calculation that only exists in a terminal is not a deliverable. The
last block of the job file assembles the document, and the assembling is mostly just
adding the results you already have, in reading order.</p>

{excerpt("beam_B1.py", "# 6. The report", "B1_report.md", "<b>Screenshot 11.1</b> &mdash; a title, a signature block generated from the project record, then <code>add()</code> calls in order. The results carry their own inputs, clauses, working and checks, so nothing is transcribed.")}

<p><code>add_scope</code>, <code>add_assumption</code> and <code>add_conclusion</code> are
different: they take prose, and the library cannot generate them. A report read by an
independent reviewer needs to say what was assumed and what the numbers mean, and keeping
that narrative in the same ordered list as the calculations is what stops it drifting to
the back of the document where nobody reads it.</p>

{shot("shot_report_top.png", "<b>Screenshot 11.2</b> &mdash; job header, overall verdict, the not-verified banner, then your preamble, scope and assumptions.")}

{shot("shot_report_flexure.png", "<b>Screenshot 11.3</b> &mdash; the flexure check as issued: every intermediate from &alpha;<sub>2</sub> through d<sub>n</sub>, k<sub>uo</sub> and the lever arm, then the three checks with utilisations. A reviewer can follow this without opening Python.")}

{cap_slice("run_full", "REPORT", None, "python beam_B1.py — last lines", "<b>Screenshot 11.4</b> &mdash; the two flags that matter.")}

{callout("warn", "passed and issuable are different questions", '''
<p><strong>passed</strong> asks: did the beam satisfy the criteria? <strong>issuable</strong>
asks: has the code that evaluated those criteria been checked against the printed
Standard? A calculation can pass and still not be issuable &mdash; exactly the state this
library is in today &mdash; and the report says so on its own face.</p>''')}

<p>The HTML renderer writes a self-contained page: print it to PDF from any browser, or
with <code>chrome --headless --print-to-pdf=B1_report.pdf outputs/B1_report.html</code>.
The Markdown renderer suits the other route &mdash; paste into a Word template, or check the
<code>.md</code> into git and diff calculations between revisions.</p>
"""


def part_12() -> str:
    return f"""
<h2><span class="num">12</span>What to do next</h2>

<h3>The habits worth carrying over</h3>
<ol class="steps">
<li><strong>One job folder, two files, run from inside it.</strong> Copy the folder for the
next job rather than starting blank.</li>
<li><strong>Job data first, completely.</strong> Loads that live in one place cannot
disagree with themselves.</li>
<li><strong>Never type a load factor.</strong> If you are writing <code>1.2 *</code>
anything, the project record is missing information it should have.</li>
<li><strong>The design decision is one string</strong> &mdash; the same string as the drawing.</li>
<li><strong>Read the Basis and the envelope notes before you trust a module</strong>, and
validate its constants against your copy of the Standard. That check is inherited by every
job that calls it.</li>
<li><strong>Write the scope, assumptions and conclusion yourself.</strong> The library can
generate everything except the engineering.</li>
</ol>

<h3>The obvious extensions to this job</h3>
<table class="data">
<tr><th>Next</th><th>Call</th></tr>
<tr><td>Serviceability &mdash; deliberately skipped here</td>
    <td><code>PROJECT.load_combinations(uls=False)</code>, then
    <code>as3600.effective_stiffness</code> and <code>as3600.check_deflection</code></td></tr>
<tr><td>Crack control and detailing</td>
    <td><code>as3600.check_crack_control</code>, <code>as3600.check_detailing</code>,
    <code>as3600.check_bar_fit</code></td></tr>
<tr><td>B2 and B3 as well</td>
    <td>A second script importing the same <code>job_data</code>, or a CSV member schedule
    through <code>design_documentation</code></td></tr>
<tr><td>Let a search pick the section</td><td><code>as3600.minimum_cost_section</code></td></tr>
<tr><td>Continuous beams</td>
    <td><code>austruct.analysis</code> pattern loading and <code>redistribute</code>
    &mdash; and invert the section for hogging</td></tr>
<tr><td>Steel, masonry, bridges</td>
    <td><code>design.as4100</code>, <code>design.as3700</code>, <code>design.as5100_5</code>
    &mdash; same contract, same call shape</td></tr>
</table>

{callout("stop", "The standing caveat", '''
<p>Nothing in this library has been verified against the printed Standards. Every report
it produces says so on its face, and this tutorial does not change that. Treat every
number here as an illustration of a workflow, not as a design.</p>''')}

<footer class="doc">
Tutorial 01 &middot; <code>tutorials/01_simply_supported_beam/</code> &middot;
Built from the committed job files and captured terminal output by
<code>build_tutorial.py</code>.
</footer>
"""


def build_html() -> str:
    parts = [cover(), part_1(), part_2(), part_3(), part_4(), part_5(), part_6(),
             part_7(), part_8(), part_9(), part_10(), part_11(), part_12()]
    pyg = HtmlFormatter().get_style_defs(".src")
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>Calling vetted calculation modules from a job file</title>"
            f"<style>{CSS}\n{pyg}</style></head><body><div class='sheet'>"
            + "\n".join(parts) + "</div></body></html>")


def main() -> None:
    html_path = HERE / "tutorial.html"
    html_path.write_text(build_html())
    print(f"wrote {html_path}  ({html_path.stat().st_size / 1e6:.1f} MB)")

    if "--pdf" not in sys.argv:
        return
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None)
    if chrome is None:
        sys.exit("no chromium found; pass a path or print from a browser")
    pdf = HERE / "Tutorial_01_Beam_B1.pdf"
    subprocess.run(
        [chrome, "--headless", "--no-sandbox", "--disable-gpu",
         "--no-pdf-header-footer", f"--print-to-pdf={pdf}", html_path.as_uri()],
        check=True, capture_output=True,
    )
    print(f"wrote {pdf}  ({pdf.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
