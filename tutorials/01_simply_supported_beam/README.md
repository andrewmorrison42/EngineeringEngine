# Tutorial 01 — Calling vetted calculation modules from a job file

A 24-page tutorial for an engineer who reads design codes fluently and Python
slowly. It walks one real job — a simply supported roof beam, analysed over the
AS/NZS 1170.0 ultimate combinations and designed for flexure and shear to
AS 3600:2018 — and uses it to teach the thing the toolkit exists for: keeping
the code equations in an installed, tested library and the job in a script that
imports it.

**Read:** [`Tutorial_01_Beam_B1.pdf`](Tutorial_01_Beam_B1.pdf)

## What is in here

| Path | What it is |
|---|---|
| `Tutorial_01_Beam_B1.pdf` | The tutorial. 24 pages, ~30 screenshots. |
| `tutorial.html` | The same document before printing. Build artefact, not committed. |
| `job/job_data.py` | The job: project record, geometry, areal loads, site wind to AS/NZS 1170.2. |
| `job/beam_B1.py` | The member: section, load cases, analysis, AS 3600 checks, figures, report. |
| `outputs/` | Everything the run produces. Delete it and re-run to get it back. |
| `captures/` | Captured stdout of every command shown in the tutorial, plus report screenshots. |
| `build_tutorial.py` | Builds the HTML and the PDF. |

## Running the worked example

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "../..[dev,plots,report]"     # the library, editable
cd job && python beam_B1.py
```

## Rebuilding the tutorial

Every code panel in the PDF is read out of `job/` at build time and every
terminal panel is read out of `captures/`, so the document cannot drift away
from the code it describes. Needs `pygments` and a Chromium binary.

```bash
python build_tutorial.py --pdf
```

To refresh the captures after changing the job files, re-run `beam_B1.py`,
capture its stdout to `captures/run_full.txt`, and re-screenshot
`outputs/B1_report.html`.

## Status

Every module used here reports `UNVERIFIED` and every report it produces is
stamped **NOT VERIFIED FOR ISSUE**. The tutorial teaches the workflow and makes
no claim that any number the library produces is correct.
