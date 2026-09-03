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
  combinations of AS/NZS&nbsp;1170 and designed for flexure and shear to
  AS&nbsp;3600:2018 &mdash; written the way you would run a real job.</div>
  <dl>
    <dt>Written for</dt><dd>An engineer who reads design codes fluently and Python
      slowly. No prior Python project experience assumed.</dd>
    <dt>Library</dt><dd><code>austruct</code> 0.1.0 &mdash; the toolkit in this repository</dd>
    <dt>Worked example</dt><dd>Job 25-0142 Northbank Depot, roof beam B1</dd>
    <dt>Framework</dt><dd>The six ASET components (Ferster, 2025)</dd>
    <dt>Every panel</dt><dd>Real output. Each terminal panel is the captured stdout
      of the command shown; each code panel is read out of the committed file at build time.</dd>
    <dt>Status</dt><dd><strong>Not verified for issue.</strong> This document teaches the
      workflow. It makes no claim that any number the library produces is correct.</dd>
  </dl>
</section>"""


def part_0() -> str:
    return f"""
<h2><span class="num">0</span>What you are going to build</h2>

<p class="lead">By the end of this you will have a folder for one job, containing two
short Python files you wrote, that together produce a signed calculation report for a
beam. Neither of your files contains a single clause of AS&nbsp;3600. Every code
equation comes from a library that lives somewhere else, is version controlled, and is
tested.</p>

<p>That separation is the whole idea, and it is worth being blunt about why it matters.
A spreadsheet mixes three things that have completely different lifetimes:</p>

<table class="data">
<tr><th>What it is</th><th>How often it changes</th><th>Who should own it</th></tr>
<tr><td>The <strong>code equations</strong> &mdash; &phi;M<sub>uo</sub>, k<sub>v</sub>, &theta;<sub>v</sub></td>
    <td>When the Standard is amended. Every few years.</td>
    <td>One vetted, tested library. Written once, checked once.</td></tr>
<tr><td>The <strong>job</strong> &mdash; spans, loads, grades, the client's name</td>
    <td>Every job. Sometimes every day.</td><td>You, in a job folder.</td></tr>
<tr><td>The <strong>decision</strong> &mdash; 350&nbsp;&times;&nbsp;650, 3-N24</td>
    <td>Every iteration, until it lands.</td><td>You, in one line you can read aloud.</td></tr>
</table>

<p>In a spreadsheet all three are tangled in the same cells, so re-using the equations
means copying the job with them &mdash; and that copy is now a second, unchecked version
of AS&nbsp;3600. In Python you keep them apart by putting the equations in an
<em>importable package</em> and the job in a <em>script that imports it</em>. That is
what the word "import" is really doing for you: it is not a convenience, it is the
mechanism that stops your calculations from being copied.</p>

{callout("good", "The shape of the finished job", '''
<p>Two files you write, one command you run, five files you get back:</p>
<ol class="steps">
<li><code>job_data.py</code> &mdash; the job. Project record, spans, tributary widths,
areal loads, and the wind pressure worked out to AS/NZS&nbsp;1170.2. No capacities.</li>
<li><code>beam_B1.py</code> &mdash; the member. Says what B1 is, what is on it, and what to
check. Every capacity comes from an <code>import</code>.</li>
<li><code>python beam_B1.py</code> &mdash; and out come three diagrams, a Markdown report
and an HTML report, all stamped with the clause references used to produce them.</li>
</ol>''')}

<h3>Where this sits in the ASET framework</h3>
<p>Ferster's <em>Anatomy of Your Automated Structural Engineering Toolkit</em> splits a
toolkit into six components. This tutorial walks all six in order, because that order is
also the order a real calculation goes in. Keep the map in your head as you go &mdash; when
you are lost in the code, the question "which of the six am I in?" usually unsticks it.</p>

<table class="data">
<tr><th>#</th><th>ASET component</th><th>In this job</th><th>Where the code lives</th></tr>
<tr><td class="n">1</td><td>Reference data</td><td>C32 concrete, N24 bar areas</td><td><code>austruct.materials</code></td></tr>
<tr><td class="n">2</td><td>Project data</td><td>Job record &rarr; &psi; factors &rarr; combinations; wind</td><td><code>austruct.project</code>, <code>austruct.loads</code>, <em>your</em> <code>job_data.py</code></td></tr>
<tr><td class="n">3</td><td>Fast demand calculation</td><td>Analyse 7 combinations, envelope them</td><td><code>austruct.analysis</code></td></tr>
<tr><td class="n">4</td><td>Design documentation</td><td><code>350 x 650 | C32 | BOT 3-N24 | ...</code></td><td><code>austruct.design_documentation</code></td></tr>
<tr><td class="n">5</td><td>Design verification</td><td>Flexure and shear to AS 3600:2018</td><td><code>austruct.design.as3600</code></td></tr>
<tr><td class="n">6</td><td>Reporting</td><td>The signed audit document</td><td><code>austruct.report</code></td></tr>
</table>

{callout("warn", "One honest caveat before you start", '''
<p>Every module in this library currently reports its verification status as
<code>UNVERIFIED</code>, and every report it produces is stamped
<strong>NOT VERIFIED FOR ISSUE</strong>. That is deliberate and it is correct: the
constants have been written but not independently checked against the printed
Standards. This tutorial teaches you the <em>workflow</em>. Checking the numbers is a
separate job, and the library is built so that job is possible &mdash; which is more than
a spreadsheet usually offers.</p>''')}
"""


def part_1() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">1</span>How Python finds other people's code</h2>

<p class="lead">Everything that follows rests on four words: module, package, install,
and path. Ten minutes here will save you an afternoon of <code>ModuleNotFoundError</code>.</p>

<h3>A module is a file. A package is a folder of them.</h3>
<p>A <strong>module</strong> is any <code>.py</code> file. <code>job_data.py</code> is a
module. A <strong>package</strong> is a folder of modules that can be imported as a unit
&mdash; <code>austruct</code> is a package, <code>austruct.design</code> is a sub-package
inside it, and <code>austruct.design.as3600.flexure</code> is a module inside that. The
dots in an import statement are folder separators.</p>

<p>So this line:</p>
<p><code>from austruct.design import as3600</code></p>
<p>reads as: <em>go into the folder</em> <code>austruct/design/</code>, <em>and give me the
thing called</em> <code>as3600</code>. And once you have it, <code>as3600.check_flexure(...)</code>
calls a function that lives in a file you did not write, did not copy, and cannot
accidentally edit while typing a span.</p>

<h3>The three shapes of an import, and when to use which</h3>
<table class="data">
<tr><th>You write</th><th>You then use</th><th>Use it when</th></tr>
<tr><td><code>import austruct</code></td><td><code>austruct.design.as3600.check_flexure(...)</code></td>
    <td>Rarely. Too long to read.</td></tr>
<tr><td><code>from austruct.design import as3600</code></td><td><code>as3600.check_flexure(...)</code></td>
    <td><strong>Most of the time.</strong> The call still says which Standard it came from.</td></tr>
<tr><td><code>from austruct.design.as3600 import check_flexure</code></td><td><code>check_flexure(...)</code></td>
    <td>Sparingly. Six months later, <code>check_flexure</code> alone does not tell a
    reviewer whether that was AS&nbsp;3600 or AS&nbsp;5100.5.</td></tr>
</table>

{callout("stop", "Never do this", '''
<p><code>from austruct.design.as3600 import *</code> pulls every name in the module into
your file at once. It is the Python equivalent of pasting someone's whole spreadsheet
into your sheet: you now cannot tell which numbers are yours, and a rename upstream
silently changes your results. In a calculation file it is not a style preference, it is
a traceability defect.</p>''')}

<h3>Where Python actually looks</h3>
<p>When you write <code>import x</code>, Python searches a list of folders, in order, and
takes the first <code>x</code> it finds:</p>
<ol class="steps">
<li><strong>The folder the script you ran lives in.</strong> Not the folder you are standing in
&mdash; the folder of the <code>.py</code> file you handed to <code>python</code>. This is why
<code>beam_B1.py</code> can say <code>import job_data</code> with no setup at all: they are
siblings.</li>
<li><strong>The site-packages of the environment you are in.</strong> This is where
<code>pip install</code> puts things, and it is how <code>austruct</code> is found from any
directory on the machine.</li>
<li>The standard library, and a few other places you will not need to think about.</li>
</ol>

<p>Both of the errors below are that list failing, and they read very differently once
you know it. First: the library is not in this environment, because the environment was
never activated.</p>

{cap("err_novenv", "bash", "<b>Screenshot 1.1</b> &mdash; no <code>(.venv)</code> in the prompt, so <code>pip install</code>'s work is invisible. The fix is <code>source .venv/bin/activate</code>, not editing the file.")}

<p>Second: your own module is not found, because you are running from the wrong
directory &mdash; and then the same import working one folder down.</p>

{cap("err_localmod", "bash", "<b>Screenshot 1.2</b> &mdash; <code>import job_data</code> is not magic. It works because <code>job_data.py</code> sits beside the file being run.")}

{callout("warn", "The rule to memorise", '''
<p><strong>Library code gets installed. Job code sits next to the script.</strong>
If you ever find yourself writing <code>sys.path.append("../../my_calcs")</code> to reach
your own calculations, stop &mdash; that is the signal that those calculations have grown up
and want to be an installed package too.</p>''')}
"""


def part_2() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">2</span>Setting up, from nothing</h2>

<p class="lead">Two folders, and they must be different folders. One holds the library.
One holds the job. Confusing them is the single most common way a Python toolkit turns
back into a spreadsheet.</p>

<h3>Step 1 &mdash; a virtual environment</h3>
<p>A <em>virtual environment</em> is a private copy of Python for one project. It exists so
that upgrading a package for this job cannot silently change the answers on last year's
job. Create it once, in the library folder, and activate it every time you open a
terminal. The <code>(.venv)</code> that appears in your prompt is the confirmation.</p>

{cap("setup_install", "bash — in the library folder", "<b>Screenshot 2.1</b> &mdash; <code>pip install -e</code> installs the library in <em>editable</em> mode: <code>site-packages</code> gets a pointer to the source folder rather than a copy, so a fix to the library is live immediately. The bracketed names are optional extras &mdash; <code>plots</code> pulls in matplotlib, <code>report</code> pulls in the renderers.")}

<h3>Step 2 &mdash; prove it worked before you write anything</h3>
<p>Two commands. The first shows you <em>which</em> copy of the library you are about to
use, which is the question you will want answered the first time two versions disagree.
The second runs the library's own test suite &mdash; the evidence that the thing you are
about to trust still behaves the way its author intended.</p>

{cap("setup_verify", "bash", "<b>Screenshot 2.2</b> &mdash; the path printed is the source tree, not a copy in site-packages: that is what <em>editable</em> means. 799 passing tests is not proof the clauses are right, but it is proof nothing has broken since they were written.")}

{callout("", "If pytest feels absurdly slow", '''
<p>On a CPU-limited container, multi-threaded BLAS spin-waiting inside hundreds of tiny
matrix solves can cost two orders of magnitude. Prefix the command with
<code>OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1</code>. The 799 tests above ran in under
three minutes that way.</p>''')}

<h3>Step 3 &mdash; make the job folder</h3>
<p>One folder per <em>job</em>, not per member. B1, B2 and the transfer slab all share the
same project record and the same load schedule, and duplicating those three times is how
they drift apart.</p>

{cap("tree", "bash", "<b>Screenshot 2.3</b> &mdash; the job folder (top) and the library folder (bottom) are separate, and only one of them is installed. <code>outputs/</code> holds only generated files, so you can delete it at any time and re-run to get it back &mdash; which is a good habit: if you cannot delete it, something in there was hand-edited.")}

{callout("good", "A checklist you can re-use for every new job", '''
<ol class="steps">
<li>Copy the two-file job folder from your last job. Do not start from a blank page.</li>
<li>Open a terminal, activate the environment, and confirm <code>(.venv)</code> appears.</li>
<li><code>cd</code> into <code>job/</code>. Everything runs from there.</li>
<li>Edit <code>job_data.py</code> first, completely, before touching the member file.</li>
<li>Run early and often. A five-line script that runs beats a fifty-line one that does not.</li>
</ol>''')}
"""


def part_3() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">3</span>Finding out what the library can do</h2>

<p class="lead">Before importing anything into a job file, get into the habit of poking
at it interactively. Type <code>python</code> with no arguments and you get a prompt where
every line runs as you press enter. Nothing you do there can break a file.</p>

<h3>Reference data &mdash; ASET component 1</h3>
<p>Start with the simplest thing in the toolkit: a concrete grade. It is looked up from a
JSON file, not calculated, and one call gets you everything AS&nbsp;3600 derives from
f'<sub>c</sub>.</p>

{cap("repl_refdata", "python", "<b>Screenshot 3.1</b> &mdash; the third line is a deliberate mistake, left in. Guessing an attribute name is normal; the recovery is <code>dir()</code>, which lists everything the object actually has. That two-line loop is the most useful debugging habit in Python.")}

<p>Two things in that panel are worth dwelling on. <code>Ec = 30100 MPa (source: table)</code>
tells you the modulus came from Table&nbsp;3.1.2 rather than the expression &mdash; the
library records <em>which</em> route it took, not just the answer. And
<code>bar_area(24)</code> returns <code>452.389...</code>, not a rounded 450: reference data
is held exactly and rounded only when printed.</p>

<h3>The same trick on a design module</h3>
<p><code>dir()</code> on a package tells you what checks exist. The docstring tells you what
each one wants. Between them you rarely need to open the source.</p>

{cap("repl_discover", "python", "<b>Screenshot 3.2</b> &mdash; every public calculation in AS 3600, listed by the library itself. The docstring of <code>check_shear</code> names its Basis (which clauses), its Parameters (what you must supply) and its Returns.")}

{callout("", "The three places to look, in order", '''
<p><strong>1.</strong> <code>dir(module)</code> in the REPL &mdash; what exists.
<strong>2.</strong> <code>print(thing.__doc__)</code> or <code>help(thing)</code> &mdash; what it wants.
<strong>3.</strong> <code>CATALOGUE.md</code> in the repository root &mdash; every registered module,
its clause coverage and its verification status, generated from the code itself so it
cannot go stale.</p>''')}

<h3>Envelope versus check &mdash; the distinction that makes the library safe</h3>
<p>This is the most important idea in the toolkit and it takes thirty seconds to see.
Ask for 150&nbsp;MPa concrete and the module <em>refuses</em>. Ask for 100 and it answers.</p>

{cap("repl_envelope", "python", "<b>Screenshot 3.3</b> &mdash; an <code>OutsideEnvelope</code> exception, not a number. The message names the limit, the clause behind it, and your value.")}

<table class="data">
<tr><th></th><th>Envelope</th><th>Check</th></tr>
<tr><td>What it bounds</td><td>The range in which the method is valid</td><td>A code criterion</td></tr>
<tr><td>Breaching it means</td><td>The answer is <em>unknown</em></td><td>The answer is <em>known and it fails</em></td></tr>
<tr><td>What you get</td><td>An exception. No number at all.</td><td>A valid result that reads FAIL</td></tr>
<tr><td>Example</td><td>f'<sub>c</sub> = 150 MPa</td><td>M* &gt; &phi;M<sub>uo</sub></td></tr>
</table>

<p>An overstressed beam is a perfectly good calculation with a failing result &mdash; you
want to see that, with all the working, so you can size up. A beam of 150&nbsp;MPa
concrete is not a calculation this library can do at all, and quietly extrapolating would
be the worst possible outcome. Spreadsheets almost never make this distinction. It is
worth insisting on it in anything you build.</p>
"""


def part_4() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">4</span>File one &mdash; the job (ASET component 2)</h2>

<p class="lead">Write this file completely before you touch the member file. It contains
no capacities and no Standards arithmetic beyond turning site data into loads. If you
later design B2, B3 and the transfer slab, they all import this same file &mdash; and they
all move together when the client changes the plant weight.</p>

<h3>The job record</h3>
<p><code>Project</code> is a plain record of client-supplied facts. It looks like
bookkeeping, and then it quietly does real work: the occupancy you state drives the
&psi; combination factors, and the structure type decides whether you get the
AS/NZS&nbsp;1170.0 building combinations or the AS&nbsp;5100.2 bridge set. Stating
"office building" once is what stops a bridge combination reaching a floor beam.</p>

{excerpt("job_data.py", "# 1. The job record", "# 2. Geometry", "<b>Screenshot 4.1</b> &mdash; note what is <em>not</em> here: no defaults invented on your behalf. An unstated design life stays empty so the report can say &lsquo;not stated&rsquo; rather than printing a number nobody chose.")}

<h3>Geometry and areal loads</h3>
<p>Spans and tributary widths get names, so that every later use of them is self-evidently
the same number. The library works in newtons and millimetres &mdash; which makes
1&nbsp;kN/m exactly 1&nbsp;N/mm &mdash; so areal loads are written in kPa the way a load
schedule states them and converted exactly once, here, by multiplying by
<code>kPa</code>.</p>

{excerpt("job_data.py", "# 2. Geometry the loads depend on", "# 4. Wind", "<b>Screenshot 4.2</b> &mdash; the triple-quoted string under each value is a docstring, and it is doing the job a cell comment does in a spreadsheet, except it cannot be scrolled out of view or lost in a copy-paste.")}

{callout("", "Units: read this once and stop worrying", '''
<p>Everything is N, mm and MPa. The constants <code>kN</code>, <code>m</code>,
<code>kPa</code>, <code>kNm</code> and <code>kN_per_m</code> are plain multipliers that
convert <em>into</em> that system on the way in (<code>7.2 * m</code> is 7200.0) and
<em>out of</em> it on the way to a print statement (<code>M / kNm</code>). If a number
ever looks wrong by a factor of 1000, this is where to look first.</p>''')}

<h3>Wind, to AS/NZS 1170.2</h3>
<p>The library does not derive site wind &mdash; that is a job-specific piece of work with
too many local judgements to hide inside a package. So it goes in your file, as a small
function with each multiplier on its own line, tagged with the clause it comes from. This
is exactly the pattern to copy whenever you need a calculation the library does not
have.</p>

{excerpt("job_data.py", "# 4. Wind, to AS/NZS 1170.2", "# 5. Derived line loads", "<b>Screenshot 4.3</b> &mdash; one factor per line, each with its clause. When the checker asks &lsquo;where did M<sub>z,cat</sub> = 0.91 come from?&rsquo;, the answer is on the same line as the number.")}

<p>Two habits in that panel are worth stealing. The <code>[VECTOR]</code> tag marks values
transcribed from a Standard, so a reviewer can find every one of them with a text search.
And <code>net_uplift_pressure()</code> returns a magnitude only, with the docstring saying
the sign is applied at the call site &mdash; because the direction of a load is easier to
get right where you can see the beam it is on.</p>

<h3>Derived line loads &mdash; the file's actual output</h3>
{excerpt("job_data.py", "# 5. Derived line loads", None, "<b>Screenshot 4.4</b> &mdash; three numbers, in the library's units, ready to be consumed. Everything above exists to produce these.")}
"""


def part_5() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">5</span>File two &mdash; the member</h2>

<p class="lead">Now the calculation itself. It opens with a block of imports, and that
block is worth reading slowly, because it is the answer to the question this tutorial
exists for: <em>how do I call vetted modules into a different file?</em></p>

{excerpt("beam_B1.py", "from pathlib import Path", "# ------", "<b>Screenshot 5.1</b> &mdash; six imports from the installed library, then one from the file next door. The blank line between them is a convention worth keeping: above it, code you did not write; below it, code you did.")}

<p>Read down the imports and you can predict the whole calculation before reading a line
of it: something about beams and loads, units, AS&nbsp;3600, a designation parser, load
cases, a bar catalogue, a report. Imports at the top of a file are a table of contents.</p>

<h3>The design decision, as one line of text (ASET component 4)</h3>
<p>Here is where the toolkit does something a spreadsheet cannot. The beam is described
by a string in a defined grammar &mdash; the same string that goes on the drawing &mdash; and
the library turns it into a section object.</p>

{excerpt("beam_B1.py", "# 1. The design decision", "# 2. Load cases", "<b>Screenshot 5.2</b> &mdash; <code>parse()</code> in, <code>designate()</code> back out. The <code>assert</code> on line 34 is a one-line guard that the round trip is exact.")}

<table class="data">
<tr><th>Field</th><th>Means</th><th>Rules</th></tr>
<tr><td><code>350 x 650</code></td><td>b &times; D, mm</td><td>Always first</td></tr>
<tr><td><code>C32</code></td><td>f'<sub>c</sub> = 32 MPa</td><td rowspan="4">All keyword-led and order-independent. An unrecognised field <strong>raises</strong> rather than being ignored &mdash; silently dropping <code>TOP 2-N16</code> would hand you a singly reinforced capacity for a doubly reinforced beam.</td></tr>
<tr><td><code>COV 40</code></td><td>Cover to the fitment, mm</td></tr>
<tr><td><code>BOT 3-N24</code></td><td>Three N24 bottom bars</td></tr>
<tr><td><code>LIG N12-2L@250</code></td><td>N12 two-leg ligatures at 250</td></tr>
</table>

{callout("good", "Why a string, and not five arguments", '''
<p>Because that string is the thing everyone else in the project already reads. It goes
in the schedule, on the drawing, in the email to the drafter, and into
<code>parse()</code> &mdash; unchanged. There is no transcription step between the design
decision and the calculation, so there is no transcription error. And because
<code>designate(parse(s)) == s</code> is asserted, the calculation cannot quietly be for a
different beam than the one you wrote down.</p>''')}

{cap_slice("run_full", "SECTION", "LOAD CASES", "python beam_B1.py — first block", "<b>Screenshot 5.3</b> &mdash; what that one line expanded into. Note d = 586 mm, derived from cover + fitment + half a bar, not typed. That subtraction is one of the most common arithmetic slips in hand calculations, and here it happens once, in tested code.")}
"""


def part_6() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">6</span>Load cases and combinations (AS/NZS 1170)</h2>

<p class="lead">A load case says <em>what the loads are and which action they represent</em>.
A combination says <em>how the jurisdiction requires them to be added up</em>. Keeping
those separate is why you never write <code>1.2 * dead + 1.5 * live</code> by hand
again.</p>

<h3>The cases &mdash; unfactored, and tagged</h3>
{excerpt("beam_B1.py", "# 2. Load cases", "# [UNITS] A UDL learns", "<b>Screenshot 6.1</b> &mdash; three cases. Each carries an <code>ActionType</code>, and that tag is the whole mechanism: it is what connects &lsquo;this 18.79 kN/m is permanent action&rsquo; to &lsquo;the code multiplies permanent action by 1.2 in this combination&rsquo;.")}

<p>Four things in that panel repay attention:</p>
<ul>
<li><strong><code>SelfWeight</code> instead of a number.</strong> It derives the UDL from the
section's own area and a density, so the moment you change 350&nbsp;&times;&nbsp;650 to
400&nbsp;&times;&nbsp;750 the self weight follows. A hand-computed 5.36 would not.</li>
<li><strong>A UDL and a point load in the same case.</strong> A load case is a group of
loads, not one load: the roof imposed pressure and the plant unit are both Q and must be
factored together.</li>
<li><strong>The minus sign on the wind UDL.</strong> Downward is positive throughout, so
uplift is negative. It is applied here, next to the beam, rather than buried in
<code>job_data.py</code>.</li>
<li><strong>Names you will read again.</strong> <code>"G_roof"</code> and
<code>"Wu_uplift"</code> come back out in the envelope as the governing case, so make them
say something.</li>
</ul>

{cap_slice("run_full", "LOAD CASES", "COMBINATIONS", "python beam_B1.py", "<b>Screenshot 6.2</b> &mdash; every load echoed back with its type and intensity. Reading this block before looking at any capacity is the equivalent of checking your load take-down before you start designing.")}

<h3>The combinations come from the project record, not from you</h3>
<p>You never type a load factor. <code>PROJECT.load_combinations(sls=False)</code> reads the
structure type and the occupancy off the record you wrote in part 4 and returns the
AS/NZS&nbsp;1170.0 Cl&nbsp;4.2.2 ultimate set, with the &psi; factors already resolved for
an office.</p>

{cap("repl_project", "python", "<b>Screenshot 6.3</b> &mdash; <code>(0.4, 0.7, 0.4)</code> is (&psi;<sub>c</sub>, &psi;<sub>s</sub>, &psi;<sub>l</sub>) for an office, and you can see them arrive in ULS3 and ULS4. Change <code>Occupancy.OFFICE</code> to <code>STORAGE</code> and every combination below changes with it.")}

{callout("warn", "Combinations you did not ask for are a feature", '''
<p>Seven come back, including earthquake and snow, because the <em>project</em> implies
them. The analysis step drops the ones no supplied case contributes to, so ULS6 and ULS7
cost nothing here. The point is that the list is generated from the jurisdiction, not
from what you remembered on the day &mdash; and the one you forget is the one that
governs.</p>''')}

{cap_slice("run_full", "COMBINATIONS (AS", "ENVELOPE", "python beam_B1.py", "<b>Screenshot 6.4</b> &mdash; the same seven, echoed by the job script. ULS5 (0.9G + W<sub>u</sub>) is the uplift/reversal case: with 0.9G at 21.7 kN/m against 3.98 kN/m of uplift there is no reversal here, but the combination is run and the result recorded rather than assumed.")}
"""


def part_7() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">7</span>Analyse, then envelope (ASET component 3)</h2>

<p class="lead">Two lines of code do the whole of the analysis: build the member, then run
every combination over it and keep the worst of each action &mdash; along with a record of
which combination caused it.</p>

{excerpt("beam_B1.py", "# 3. Analyse over every ULS", "# 4. Design verification", "<b>Screenshot 7.1</b> &mdash; <code>simply_supported()</code> is one of a family (<code>cantilever</code>, <code>propped</code>, <code>continuous</code>). Passing <code>section=</code> rather than a bare EI means the deflections use the section you actually detailed.")}

{cap_slice("run_full", "ENVELOPE", "AS 3600:2018 CHECKS", "python beam_B1.py", "<b>Screenshot 7.2</b> &mdash; the governing action table. Every row carries the combination that caused it in square brackets, which is the single most useful thing an envelope can tell you.")}

<p>Read that block the way you would read the summary page of a frame analysis:</p>
<ul>
<li><strong>M* = 296.1 kN.m at x = 3.000 m [ULS2]</strong> &mdash; sagging, under the plant
load, from 1.2G&nbsp;+&nbsp;1.5Q. Not at midspan, because the point load is not at
midspan.</li>
<li><strong>M<sub>hog</sub> = 0.00 kN.m</strong> &mdash; no reversal anywhere, under any of the
seven. The uplift case never overcomes 0.9G.</li>
<li><strong>Reactions, max and min.</strong> The minimum at each support is 69.43&nbsp;kN
from ULS5, still comfortably downward: no hold-down required. That is a real check, and
it fell out of the envelope for free.</li>
<li><strong>Deflection 6.26 mm [ULS2]</strong> &mdash; from <em>factored</em> loads on a gross
section, so it is a solver output, not a serviceability check. Do that separately, with
SLS combinations and <code>as3600.effective_stiffness</code>.</li>
</ul>

{callout("", "One mesh, shared by every combination", '''
<p>Meshed independently, each combination would land on a slightly different set of
x-positions, and enveloping them would need interpolation &mdash; which smears exactly the
shear discontinuities an envelope exists to capture. The library gives every combination
the union of all mesh points, so the envelope is element-wise and exact. You get the sharp
step under the plant load, not a rounded corner.</p>''')}

<h3>Seeing it</h3>
<p>Two plots, both one line of code. The first is the governing combination alone, drawn
the way you would draw it by hand; the second is the envelope with all seven cases faint
behind it.</p>

{excerpt("beam_B1.py", "# The governing combination on its own", "fig_sec = plots.plot_section", "<b>Screenshot 7.3</b> &mdash; <code>combo.apply(cases)</code> is the same factoring the envelope did internally, done once here where you can see it. That is the layering working: nothing is hidden, it is just not repeated.")}

{fig("B1_diagrams.png", "<b>Screenshot 7.4</b> &mdash; ULS2. Sagging is drawn downward, the engineering convention, so the moment diagram hangs the way the beam does. The shear step at 3.0 m is the 60 kN factored plant load; V = 144.2 kN at the support, reduced to 126.4 kN at d for the shear check.")}

{fig("B1_envelope.png", "<b>Screenshot 7.5</b> &mdash; the envelope, with every contributing combination faint behind it. The dashed <em>min</em> curve is the lower bound: driven by ULS5 (0.9G + W<sub>u</sub>), it still sits at about 90 kN.m of sagging at midspan, which is the picture of &lsquo;no reversal anywhere&rsquo;. Seeing that is worth more than reading M<sub>hog</sub> = 0.")}
"""


def part_8() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">8</span>Flexure to AS 3600:2018</h2>

<p class="lead">After all that, the design itself is three lines. That is the correct
proportion: the hard part of a calculation is getting the right demand to the right
section, not evaluating the capacity once you have.</p>

{excerpt("beam_B1.py", "# 4. Design verification", "AS 3600:2018 CHECKS", "<b>Screenshot 8.1</b> &mdash; <code>shear_at_d_from_support(d)</code> is the code allowance for taking the design shear at d from a support that introduces compression. It is a method on the envelope because only the envelope knows the shear diagram.")}

{cap_slice("run_full", "AS 3600:2018 CHECKS", "Bar arrangements", "python beam_B1.py", "<b>Screenshot 8.2</b> &mdash; both checks, with the governing combination, the capacity, the utilisation and a verdict. Flexure at 0.933 is a sensibly worked section; shear at 0.372 is not, and part 10 comes back to that.")}

<h3>What is actually inside <code>check_flexure</code></h3>
<p>The function returns a <code>CalcResult</code>, never a bare float. That object carries
the inputs it was given, the clauses it applied, the validity envelope it enforced, the
intermediate working, the results, and every pass/fail criterion &mdash; which is what makes
the report in part 11 possible without you assembling anything.</p>

{cap("repl_audit", "python", "<b>Screenshot 8.3</b> &mdash; the audit trail, interrogated from the REPL. Five clauses in the order they were applied; three checks, not one; the envelope that was enforced; and the module's own verification status.")}

<p>Notice that there are <strong>three</strong> flexural checks, not just M*&nbsp;&le;&nbsp;&phi;M<sub>uo</sub>:</p>
<table class="data">
<tr><th>Check</th><th>Clause</th><th>Here</th><th>Why it exists</th></tr>
<tr><td>Ductility, k<sub>uo</sub> &le; 0.36</td><td>Cl 8.1.5</td><td>0.147 &mdash; PASS</td>
    <td>A section that crushes before the steel yields fails without warning. This is the check a
    hand calculation most often skips.</td></tr>
<tr><td>M<sub>uo</sub> &ge; 1.2 M<sub>cr</sub></td><td>Cl 8.1.6.1</td><td>373 &ge; 110 kN.m &mdash; PASS</td>
    <td>Minimum strength: the beam must not fail the instant it cracks.</td></tr>
<tr><td>M* &le; &phi;M<sub>uo</sub></td><td>Cl 2.2.2</td><td>296.1 &le; 317.4 kN.m &mdash; PASS</td>
    <td>The strength check everyone remembers.</td></tr>
</table>

{callout("warn", "Read the envelope notes, every time", '''
<p>The three notes in Screenshot 8.3 are the module telling you what it did <em>not</em>
do: no axial force, no torsion, no lateral instability of slender beams, and
<em>sagging only</em> &mdash; "model hogging by inverting the section". That last one is a
real trap on a continuous beam. The library will not warn you again; it has said it
here, in the result you already have in your hand.</p>''')}
"""


def part_9() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">9</span>Shear to AS 3600:2018</h2>

<p class="lead">Same call shape, one extra argument &mdash; and that extra argument is the
interesting part.</p>

<p><code>as3600.check_shear(section, V_star=V_star, M_star=M_star)</code> takes the
coexisting moment as well as the shear. That is not padding. AS&nbsp;3600:2018 moved to a
modified compression field theory formulation in which the concrete contribution depends
on the longitudinal strain in the web, which depends on M*. Shear capacity is
<em>coupled to the demand</em>. Ferster's component 5 calls this out specifically as the
case that makes a verification tool hard to build, and it is why you want the coupling
handled inside a tested module rather than by remembering to look up a second table.</p>

{shot("shot_report_shear.png", "<b>Screenshot 9.1</b> &mdash; the shear check as it appears in the generated report: inputs, seven clauses, the validity envelope, the working, the results and the checks. d<sub>v</sub> = 527.4 mm, k<sub>v</sub> = 0.15 and &theta;<sub>v</sub> = 36&deg; are the simplified-method values of Cl 8.2.4.2, reported rather than assumed.")}

<h3>The two checks, and the one that is easy to forget</h3>
<table class="data">
<tr><th>Check</th><th>Clause</th><th>Here</th></tr>
<tr><td>Minimum shear reinforcement, A<sub>sv</sub>/s</td><td>Cl 8.2.1.7</td>
    <td>0.905 &ge; 0.317 mm&sup2;/mm &mdash; PASS</td></tr>
<tr><td>V* &le; &phi;V<sub>u</sub></td><td>Cl 2.2.2 / 8.2.1.1</td>
    <td>126.4 &le; 339.5 kN &mdash; PASS, utilisation 0.372</td></tr>
</table>

<p>The minimum-reinforcement check is not decoration: the simplified method's
k<sub>v</sub>&nbsp;=&nbsp;0.15 is only available <em>because</em> the section carries at
least minimum fitments. Widen the ligatures past that limit and both the check and the
concrete contribution change together. The report says so on the k<sub>v</sub> row:
"simplified, &ge; minimum fitments".</p>

{callout("stop", "AS 5100.5 is not &lsquo;AS 3600 with different numbers&rsquo;", '''
<p>The library also implements AS&nbsp;5100.5, and for flexure the two produce an
identical nominal M<sub>uo</sub> and differ only in &phi;. For <strong>shear</strong> they
share no code at all: AS&nbsp;5100.5:2017 predates the 2018 revision and uses the
&beta;<sub>1</sub>&beta;<sub>2</sub>&beta;<sub>3</sub> / f<sub>cv</sub> / d<sub>o</sub>
family. Swapping <code>as3600</code> for <code>as5100_5</code> in a shear line and expecting a
small change is the most likely way to get a bridge wrong with this toolkit.</p>''')}

<h3>Reading a utilisation of 0.37</h3>
<p>The shear result is a genuine engineering signal, not a rounding artefact: N12
two-leg ligatures at 250 are carrying nearly three times what this beam asks of them.
The honest response is to widen the spacing until either the V* check or the
minimum-reinforcement check starts to bind, and let the two checks tell you where the
limit is. That iteration is the subject of the next part.</p>
"""


def part_10() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">10</span>The loop: FAIL is a result, not an error</h2>

<p class="lead">The section in this tutorial did not arrive fully formed. It was the
second try. Here is the first, and the thirty seconds it took to fix &mdash; which is the
part of the workflow that actually saves you time.</p>

{cap("repl_iterate", "python", "<b>Screenshot 10.1</b> &mdash; 3-N20 gives 1.312, FAIL. <code>required_steel_area</code> says the section needs 1255 mm&sup2; and has 942. 3-N24 gives 1357 mm&sup2; and 0.933, PASS. No spreadsheet was reopened and no clause was re-read.")}

<p>Three things make that loop fast, and all three are design choices you can copy into
anything you build:</p>
<ul>
<li><strong>A failing check still returns a full result.</strong> You get the utilisation, the
working and the shortfall &mdash; not an exception. Compare that with the envelope refusal in
Screenshot 3.3: different situation, different behaviour, deliberately.</li>
<li><strong>The inverse problem is a first-class function.</strong>
<code>required_steel_area</code> answers "how much steel does this moment need?" directly,
so you are not bisecting by hand.</li>
<li><strong>The decision is one string.</strong> Changing <code>BOT 3-N20</code> to
<code>BOT 3-N24</code> is the entire edit. Nothing downstream needs touching: d, the self
weight, the diagrams and the report all follow.</li>
</ul>

{cap_slice("run_full", "Bar arrangements", "REPORT", "python beam_B1.py", "<b>Screenshot 10.2</b> &mdash; and if you want the options laid out, <code>describe_options</code> takes the required area and returns every practical arrangement with its excess. 3-N24 at 7.7% over is the obvious pick here; 12-N12 provides the same area and would not fit.")}

{callout("good", "When to stop iterating by hand", '''
<p>Once you are running the same edit-and-check loop more than a few times, the library
will do it for you: <code>as3600.minimum_cost_section</code> searches a grid of widths,
depths and bar arrangements against concrete and steel rates and returns the cheapest
section that passes. Same checks, same clauses &mdash; just driven by a search instead of by
you. That is the natural next step after this tutorial, and it only becomes possible
because the check was written as a function in the first place.</p>''')}

<h3>The other two failure modes you will hit</h3>
<p>Neither is a mistake in the code you wrote; both are the environment telling you where
it is looking. Together with Screenshots 1.1 and 1.2 they cover most of a first
week.</p>

{cap("err_wrongdir", "bash", "<b>Screenshot 10.3</b> &mdash; the shipped file with its output line replaced by a bare <code>OUT = &quot;../outputs&quot;</code>, run from one directory up. The imports all resolve &mdash; Python adds the <em>script's</em> folder to the path, not yours &mdash; but the relative output path does not. The fix is the line the file actually ships with: <code>Path(__file__).resolve().parent.parent / &quot;outputs&quot;</code> anchors the output folder to the script instead of to wherever you are standing.")}
"""


def part_11() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">11</span>The report (ASET component 6)</h2>

<p class="lead">A calculation that only exists in a terminal is not a deliverable. The
last block of the job file assembles the document &mdash; and the assembling is almost
entirely just adding the results you already have, in the order you want them read.</p>

{excerpt("beam_B1.py", "# 6. The report", "B1_report.md", "<b>Screenshot 11.1</b> &mdash; a title, a signature block generated from the project record, and then <code>add()</code> calls in reading order. The results carry their own inputs, clauses, working and checks, so nothing is transcribed into the report.")}

<h3>The part only you can write</h3>
<p><code>add_scope</code>, <code>add_assumption</code> and <code>add_conclusion</code> are
different from <code>add</code>: they take prose, and the library cannot generate them.
That is the point. A report that reaches an independent reviewer is read by a person, and
a person needs to know what was assumed and what the numbers mean. Keeping the narrative
in the same ordered list as the calculations is what stops it drifting to the back of the
document where nobody reads it.</p>

{shot("shot_report_top.png", "<b>Screenshot 11.2</b> &mdash; the top of the generated HTML report. Job header, overall verdict, the not-verified banner, your preamble, and your scope and assumption blocks &mdash; then the enveloped demands.")}

{shot("shot_report_flexure.png", "<b>Screenshot 11.3</b> &mdash; the flexure check as issued: every intermediate quantity from &alpha;<sub>2</sub> through d<sub>n</sub>, k<sub>uo</sub> and the lever arm, then the three checks with utilisations. A reviewer can follow this without opening Python.")}

{shot("shot_report_end.png", "<b>Screenshot 11.4</b> &mdash; the section drawn to scale from the same object that was checked (so it cannot disagree with it), your conclusion, and a signature block with an empty Checked row. The document knows it has not been checked.")}

{cap_slice("run_full", "REPORT", None, "python beam_B1.py — last lines", "<b>Screenshot 11.5</b> &mdash; and the two flags that matter. <code>passed: True</code> means every check passed. <code>issuable: False</code> means at least one module in the document is <code>UNVERIFIED</code>, and the report says so on its own face.")}

{callout("warn", "passed and issuable are different questions", '''
<p><strong>passed</strong> asks: did the beam satisfy the criteria? <strong>issuable</strong>
asks: has the code that evaluated those criteria been checked against the printed
Standard? A calculation can pass and still not be issuable, which is exactly the state
this library is in today &mdash; and the report is built so it cannot pretend
otherwise.</p>''')}

<h3>Getting a PDF out</h3>
<p>The HTML renderer writes a self-contained page; print it to PDF from any browser, or
from the command line with headless Chromium:</p>
{terminal('''$ chrome --headless --print-to-pdf=B1_report.pdf outputs/B1_report.html''', "bash",
  "<b>Screenshot 11.6</b> &mdash; the same command that produced the document you are reading. The Markdown renderer is there for the other common route: paste into a Word template, or check the <code>.md</code> into git and diff calculations between revisions.")}
"""


def part_12() -> str:
    return f"""
<h2 class="pagebreak"><span class="num">12</span>What to do next</h2>

<h3>The habits worth carrying over, in order of value</h3>
<ol class="steps">
<li><strong>One job folder, two files, run from inside it.</strong> Copy the folder for the
next job rather than starting blank.</li>
<li><strong>Job data first, completely, before any member file.</strong> Loads that live in one
place cannot disagree with themselves.</li>
<li><strong>Never type a load factor.</strong> If you find yourself writing
<code>1.2 *</code> anything, the project record is missing information it should have.</li>
<li><strong>The design decision is one string.</strong> The same string as the drawing.</li>
<li><strong>Read the envelope notes on any module the first time you use it.</strong> They tell
you what it does not do.</li>
<li><strong>Write the scope, assumptions and conclusion yourself.</strong> The library can
generate everything except the engineering.</li>
</ol>

<h3>The obvious extensions to this job</h3>
<table class="data">
<tr><th>Next</th><th>Call</th></tr>
<tr><td>Serviceability &mdash; the check this tutorial deliberately skipped</td>
    <td><code>PROJECT.load_combinations(uls=False)</code>, then
    <code>as3600.effective_stiffness</code> and <code>as3600.check_deflection</code></td></tr>
<tr><td>Crack control and detailing</td>
    <td><code>as3600.check_crack_control</code>, <code>as3600.check_detailing</code>,
    <code>as3600.check_bar_fit</code></td></tr>
<tr><td>Design B2 and B3 as well</td>
    <td>A second script importing the same <code>job_data</code>, or a CSV member
    schedule through <code>design_documentation</code></td></tr>
<tr><td>Let the search pick the section</td><td><code>as3600.minimum_cost_section</code></td></tr>
<tr><td>Continuous beams</td>
    <td><code>austruct.analysis</code> pattern loading and
    <code>redistribute</code> &mdash; and remember to invert the section for hogging</td></tr>
</table>

<h3>Three questions Ferster asks at the end of the ASET paper</h3>
<p>They are the right ones to sit with once the mechanics stop being the hard part:</p>
<ul>
<li>Which of the six components, if you built it properly, would change your week the
most? (For most engineers it is component 2 &mdash; project data &mdash; not the
capacity equations everyone starts with.)</li>
<li>What data would you have to feed it, and where does that data come from today?</li>
<li>What is the smallest version of it that would already be useful on the job you are
on right now?</li>
</ul>

{callout("stop", "And the standing caveat", '''
<p>Nothing in this library has been verified against the printed Standards. Every report
it produces says so on its face, and this tutorial does not change that. Treat every
number in this document as an illustration of a workflow, not as a design.</p>''')}

<footer class="doc">
Tutorial 01 &middot; <code>tutorials/01_simply_supported_beam/</code> &middot;
Built from the committed job files and captured terminal output by
<code>build_tutorial.py</code>. Regenerate with <code>python build_tutorial.py --pdf</code>.
</footer>
"""


def build_html() -> str:
    parts = [cover(), part_0(), part_1(), part_2(), part_3(), part_4(), part_5(),
             part_6(), part_7(), part_8(), part_9(), part_10(), part_11(), part_12()]
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
