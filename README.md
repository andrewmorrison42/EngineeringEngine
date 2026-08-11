# austruct — structural engineering toolkit

Python framework for structural design to **AS 3600:2018**, **AS 5100.5:2017**
and (later) **AS 5100.2:2017**, structured around the six components of the
**Automated Structural Engineering Toolkit** framework.

Version 0.1.0.

---

## ⚠ Read this before using any number this produces

**No module in this package has been verified.** Every value transcribed from a
printed standard — capacity reduction factors, stress block coefficients, shear
constants, load combinations, ψ factors — is tagged `[VECTOR]` and is
**UNVERIFIED**. Several are further tagged **UNCONFIRMED**, meaning the author
is not confident of the value at all, not merely that nobody has checked it.

The mechanics are tested and correct. The *constants* need a person with the
standards open beside them.

```bash
AUSTRUCT_STRICT=1 python your_calc.py     # unverified modules raise instead of returning
```

### The traffic models fail closed harder than anything else

Everywhere else an unverified value is a single coefficient. In
`loads/as5100_2/` the unverified content is *the geometry and magnitude of an
entire load model* — an axle spacing transcribed wrongly produces a bridge
design that is wrong in a way no downstream check will catch. So the catalogue
**refuses to hand out a model by default**:

```python
>>> traffic.get("M1600")
UnverifiedLoadModel: The M1600 load model geometry in traffic_models.json is
UNVERIFIED -- it has not been transcribed from AS 5100.2:2017, only recalled...

>>> traffic.allow_unverified(True)      # once per session, development only
>>> with traffic.unverified_ok(): ...   # or scoped, which cannot leak
```

Listing the catalogue needs no permission — `traffic.names()` and
`traffic.catalogue()` always work, because seeing what exists is not using it.


Everything needing verification is in a handful of places, deliberately:

| File | What to check |
|---|---|
| `src/austruct/design/as3600/constants.py` | Every AS 3600:2018 value |
| `src/austruct/design/as5100_5/constants.py` | Every AS 5100.5:2017 value |
| `src/austruct/loads/combinations.py` | AS/NZS 1170.0 combinations |
| `src/austruct/project/project.py` | ψ combination factors by occupancy |
| `src/austruct/materials/data/*.json` | Table 3.1.2, bar sizes, steel grades |
| `src/austruct/loads/as5100_2/data/traffic_models.json` | **M1600/S1600/A160/W80 axle geometry — the highest-risk file in the package** |
| `src/austruct/loads/dispersal.py` | Fill dispersal slope |

Those JSON data files carry their own `status` / `checked_by` / `checked_on`
fields, so the tables can be checked and signed off by the engineer who owns the
standard — without reading any Python.

```python
>>> from austruct.core.registry import REGISTRY
>>> print(REGISTRY.summary())      # 16 module(s), 16 not cleared for issue.
>>> from austruct.materials import _data
>>> print(_data.data_verification_report())   # 3 data file(s), 3 not verified.
```

---

## The ASET framework

Built to Connor Ferster's *Anatomy of Your Automated Structural Engineering
Toolkit* (2025). Every module declares which of the six components it belongs
to, so the register can report what is actually built:

```python
>>> print(REGISTRY.coverage())
```

| # | ASET component | Package | What it does here |
|---|---|---|---|
| 1 | **Reference data** | `materials/` | Concrete grades, steel grades, bar catalogue. Held as JSON, queried in one call. |
| 2 | **Project data** | `project/`, `loads/` | Job record → ψ factors → jurisdiction-specific combinations; AS 5100.2 traffic models; fill dispersal. |
| 3 | **Fast demand calculation** | `analysis/` | Stiffness solver, moving-load sweeps, influence lines, then enveloping with the governing case recorded. |
| 4 | **Design documentation** | `design_documentation/` | Plain-text designation grammar + CSV member schedules, round-tripping to sections. |
| 5 | **Design verification** | `design/`, `sections/` | AS 3600 and AS 5100.5 flexure and shear. |
| 6 | **Reporting** | `report/` | Fixed audit layout, interchangeable renderers. |
| — | Infrastructure | `core/` | The contract that lets 1–6 exchange data. |

That last row is not one of the six, but component 5 asks for exactly it: *"an
over-arching structure to coordinate the retrieval of information from the
multiple domains"*.

---

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                     # 275 tests
```

Only runtime dependency is `numpy`. Plotting and reporting are extras:

```bash
pip install -e ".[dev,plots]"
```

### Using it from Jupyter

Install the package **into the environment your kernel runs in** — that is the
one thing that catches people out:

```bash
pip install -e "/path/to/engineeringengine[plots]"   # from your notebook env
python -m ipykernel install --user --name austruct   # optional: a named kernel
```

Then `import austruct` works from any directory. Start with
[`notebooks/quickstart.ipynb`](notebooks/quickstart.ipynb), which walks a beam
from project record to signed report.

The headline objects render properly in a notebook rather than dumping their
dataclass repr — evaluating a `CalcResult` shows the calculation, and a `Report`
shows the document:

```python
section                       # section properties, materials, reinforcement
as3600.check_flexure(...)     # inputs, basis, envelope, working, checks
env                           # governing actions and which case caused each
report                        # the whole audit document
```

Diagrams convert straight to a DataFrame, without the package depending on
pandas:

```python
import pandas as pd
pd.DataFrame(results.to_table())        # x_m, shear_kN, moment_kNm, deflection_mm
pd.DataFrame(env.moment.to_table())     # plus the governing case at every position
```

And plots, with matplotlib as an optional extra:

```python
from austruct.report import plots
plots.plot_diagrams(results)      # shear, moment, deflection — sagging drawn down
plots.plot_envelope(env, show_cases=True)
plots.plot_influence_line(il)
plots.plot_section(section)       # outline with the bars to scale
```

`austruct.report` imports without matplotlib; only reaching `plots` pulls it in,
and its absence gives an install instruction rather than a traceback.

---

## Layer architecture

Modules import from layers **above** them in this list, never below. That one
rule is what keeps the toolkit composable.

```
L0   core                  contract, basis, envelope, provenance, units, registry
L1   materials             concrete, reinforcement, bar catalogue        [ASET 1]
L1b  project               job record, occupancy, exposure, ψ factors    [ASET 2]
L2   sections              geometry primitives, RC sections, properties
L2b  design_documentation  designation grammar, member schedules         [ASET 4]
L3   analysis              loads, beam model, solver, moving loads,      [ASET 3]
                           influence lines, envelopes
L3b  loads                 combinations, AS 5100.2 traffic, dispersal    [ASET 2]
L4   design                rc_common/ + as3600/ + as5100_5/              [ASET 5]
L5   report                the audit artifact                            [ASET 6]
```

Note `LoadTrain` lives in `analysis/loading.py`, not in `analysis/moving.py`.
A load pattern is a load, and putting it with the driver would make `loads`
depend on `analysis.envelope`, which already depends on `loads.combinations` —
a genuine import cycle rather than a stylistic one.

### The decisions worth knowing about

**1. `rc_common` holds the mechanics; the code packages hold only what differs.**
The same section returns an *identical* nominal `M_uo` under both standards and
differs only in φ — see `examples/03_as3600_vs_as5100.py`. **But shear is two
genuinely different models**: AS 3600:2018 uses modified compression field
theory (`k_v`, `d_v`, `θ_v`); AS 5100.5:2017 predates it and uses the
AS 3600:2009 family (`β₁β₂β₃`, `f_cv`, `d_o`). They share no code. Treating
AS 5100.5 as "AS 3600 with different numbers" is the most likely way to get a
bridge wrong with this toolkit.

**2. Analysis is a general stiffness solver; closed-form solutions verify it.**
Within the solver, reactions and deflections come from the finite element solve,
but **shear and moment diagrams are built by statics** from those reactions —
exact at any position, no mesh dependence, checkable by hand.

**3. All load combinations share one exact sampling grid.** Meshed
independently, each combination would land on a different `x` array and could
only be enveloped by interpolating — which smears the shear discontinuities an
envelope exists to capture. `Beam.extra_mesh_points` gives every combination the
union of all mesh points, so the envelope is element-wise and exact.

---

## The module contract

Every public calculation returns a `CalcResult`, never a bare float.

```python
result.inputs         # echoed verbatim, units declared
result.basis          # ClauseRefs in application order
result.envelope       # validity limits + explicit in/out flag
result.outputs        # results with units
result.checks         # pass/fail against criteria
result.provenance     # version, author, checker, vector status, ASET component
result.to_dict()      # plain data — consumable without importing austruct
```

### Envelope vs Check

An **envelope limit** bounds the range of application: breach one and the answer
is *unknown*, so the module raises `OutsideEnvelope` and refuses to produce a
number. A **check** is pass/fail against a code criterion: breach one and you
have a legitimate result that reads FAIL.

A beam that is overstressed is a valid calculation with a failing result. A beam
of 150 MPa concrete is not a calculation this toolkit can do at all.

---

## Units and sign convention

**N, mm, MPa.** Plain floats, no units library. `1 kN/m = 1 N/mm` exactly, so a
25 kN/m UDL is the float `25.0`. Density is the one exception (kg/m³, because
AS 3600 Cl 3.1.2 uses it), confined to `materials/concrete.py`.

| | |
|---|---|
| Downward load, downward deflection | **positive** |
| Sagging bending moment | **positive** |
| Shear force | positive where the resultant to the **left** acts upward |
| Applied concentrated moment | positive where it **increases** sagging to its right |
| Support reaction | reported positive **upward** |

The solver works internally upward-positive and converts **once**, in
`solver.py`. For hogging bending, **invert the section** rather than negating
anything.

---

## Callout convention

Fixed vocabulary, used consistently. Nothing else.

| Tag | Meaning |
|---|---|
| `[BASIS]` | The clause this line implements |
| `[VECTOR]` | A value transcribed from a standard — needs verification |
| `[ENVELOPE]` | A validity limit being enforced |
| `[ASSUMPTION]` | A modelling choice the reader must know about |
| `[UNITS]` | Unit convention at this point |
| `[CHECK]` | A pass/fail criterion or a guard |
| `[TODO]` | Known incomplete |

Every function touching a standard carries `Basis` and `Envelope` docstring
sections.

---

## Quick start

```python
from austruct.analysis import UDL, PointLoad, analyse_combinations, simply_supported
from austruct.core.units import kN, kNm, kN_per_m, m
from austruct.design import as3600
from austruct.design_documentation import parse
from austruct.loads import ActionType, LoadCase
from austruct.project import Occupancy, Project

# 2. Project data -> combinations
project = Project(job_number="24-1234", occupancy=Occupancy.RESIDENTIAL,
                  engineer="A. Morrison")

# 4. The design, as plain text
section = parse("350 x 650 | C40 | COV 40 | BOT 4-N28 | LIG N12-2L@200", name="B1")

# 3. Analyse over every combination and envelope
cases = (
    LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),)),
    LoadCase("Q", ActionType.Q, (UDL(magnitude=15 * kN_per_m),
                                 PointLoad(position=4 * m, magnitude=60 * kN))),
)
beam = simply_supported(8 * m, section=section, name="B1")
env = analyse_combinations(beam, cases, project.load_combinations(sls=False))

# 5. Verify
flexure = as3600.check_flexure(section, env.M_star)
print(f"M* = {env.M_star / kNm:.1f} kN.m [{env.moment.governing_combo}]  "
      f"util {flexure.utilisation:.3f}  {'PASS' if flexure.passed else 'FAIL'}")
```

### The designation grammar

Pipe-separated, first field is the dimensions, the rest keyword-led and
order-independent:

```
350 x 650 | C40 | COV 40 | BOT 4-N28 | TOP 2-N16 | LIG N12-2L@200
```

It round-trips (`parse(designate(s))` reproduces the section), it is
case-insensitive, and it **fails loudly** — an unrecognised field raises rather
than being dropped, because silently ignoring `TOP 2-N16` would give a singly
reinforced capacity for a doubly reinforced beam.

Schedules are plain CSV in either long form (one row per member) or matrix form
(rows are levels, columns are member types — the shape in the ASET material's
coupling-beam example). Both open in a spreadsheet and diff in git.

### Examples

```bash
python examples/01_beam_analysis.py        # support arrangements and load types
python examples/02_beam_design_report.py   # end-to-end design + audit report
python examples/03_as3600_vs_as5100.py     # the two standards side by side
python examples/04_full_aset_workflow.py   # all six ASET components in one run
python examples/05_buried_structure_and_moving_load.py   # moving loads + fill dispersal
```

> **If a moving-load sweep feels far too slow**, it is almost certainly BLAS
> thread oversubscription, not this package. A sweep is hundreds of *small*
> dense solves, and multithreaded BLAS spin-waiting inside a CPU-limited
> container (CI, Docker with `--cpus`, some notebook hosts) can cost two orders
> of magnitude. Measured on a 4-vCPU container, a 202×202 `np.linalg.solve`
> took 410 ms; pinning to one thread took 0.5 ms. Matrices this small never
> benefit from threading:
>
> ```bash
> OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python examples/05_...py
> ```
>
> The package does not set these itself — a library has no business
> reconfiguring your BLAS for the rest of your notebook.

---

## Moving loads

A traffic load model is not a load, it is a pattern with a *free position*.
M1600 does not act at midspan; it acts wherever it produces the worst effect,
and that position differs for moment at midspan, shear at a support, and the
reaction at a pier. So the analysis has to search.

```python
from austruct.analysis import LoadTrain, moving_load_envelope, influence_line

train = LoadTrain("2-axle", axles=((0.0, 100*kN), (4*m, 100*kN)), length=4*m)
result = moving_load_envelope(beam, train, step=50.0)

result.M_star                          # 810.0 kN.m
result.critical_position("moment")     # where the leading axle was
```

The sweep runs the train **on and off both ends**, because the worst shear at a
support usually occurs with the vehicle partly off the member, and adds
positions that place an axle exactly on each support — a uniform sweep only ever
gets within half a step of one.

Each train position becomes a case in the same envelope machinery the load
combinations use, so the "governing combination" label simply becomes the
governing position. One implementation answers both questions.

### Nominating a standard load model by name

You should never have to restate an axle spacing. Name the model and it carries
its own geometry — axles, wheels, contact patch, lane UDL, dynamic allowance:

```python
from austruct.loads import as5100_2 as traffic

traffic.names("road")        # ('A160', 'HLP320', 'HLP400', 'M1600', 'S1600', 'W80')
print(traffic.catalogue())   # the whole table, with a confidence column

m1600 = traffic.get("M1600")          # or traffic.m1600()
m1600.axle_load                       # 360 kN
m1600.wheel_load                      # 180 kN -- derived, not restated
m1600.wheel.spacing                   # 2000 mm
moving_load_envelope(beam, m1600.train_with_dla(), step=250.0)
```

`W80`, `A160`, `M1600`, `S1600`, `HLP320`, `HLP400` and `300LA` are catalogued,
with `traffic.hlp(400)` and `traffic.la(250)` as shorthands — `250LA` is
generated by scaling `300LA`, since the *n*LA family shares one geometry.

Two deliberate refusals sit in here:

- **`300LA` has no constant dynamic load allowance.** AS 5100.2 Section 9 makes
  it a function of loaded length, so `dla` is `null` in the data file and
  `train_with_dla()` **raises** rather than quietly applying a road number.
- **`HLP320` / `HLP400` are flagged `is_placeholder`.** Their axle count and
  arrangement are not trusted at all; they exist so the catalogue has the slot
  and the schema is visible.

Adding a loading — an ARTC rail load, a state authority vehicle, a
project-specific crane — is an edit to `traffic_models.json`, not a code change.
Every model follows one schema; copy the nearest entry.

**Influence lines** answer the complementary question — where should the load go
to maximise a given response — and their area is the standard hand check:

```python
il = influence_line(beam, "moment", location=L/2)
il.peak                    # L/4
w * il.area                # == w.L²/8, the UDL effect
il = influence_line(beam, "shear", location=L/4, side="right")
```

That `side` argument is not decoration: the shear influence line **steps by 1.0
across the section it is measured at**, so "the shear at L/4" is two different
numbers depending on which face you stand on, and asking without saying returns
the average of the two — a value that answers neither question.

---

## Load through fill onto a buried structure

A culvert does not see a wheel. It sees what the wheel became after spreading
through the fill.

```python
from austruct.loads import FillDispersal, buried_structure_loads

fill = FillDispersal(depth=600, density=2000, slope=2.0, effective_width=1000)
loads = buried_structure_loads(fill, span, wheel, contact_len, contact_wid,
                               wheel_positions=(span/2,))
```

Two things arrive: the fill's own weight as a UDL, and each wheel spread over a
patch that grows with depth. Overlapping patches add by superposition, which
needs no special case.

The intensity applied is `pressure × min(dispersed_width, effective_width)`.
That `min` matters — under shallow fill the patch is narrower than the strip and
multiplying by the full strip width would invent load, turning an 80 kN wheel
into 200 kN on a 1 m strip.

**Both extremes of the fill range must be checked.** The two components pull in
opposite directions — the wheel effect falls with depth as the patch spreads,
the earth pressure rises — so the depth that governs the total is not the depth
that governs the wheel:

```
  fill    earth    patch  pressure   M_earth   M_wheel   M_total
    mm      kPa       mm       kPa      kN.m      kN.m      kN.m
   300     5.89      550     207.8     26.49    114.50    140.99
  1200    23.54     1450      34.5    105.95     65.94    171.89
  3000    58.86     3250       7.2    264.87     25.74    290.61
```

Here the total is worst at 3000 mm, but the wheel — what the local punching and
top-steel checks see — is worst at 300 mm. Sweep the whole cover range.

### Dispersing a named model

Pass the model itself and no geometry is restated anywhere; the dispersal reads
the contact patch, the wheel spacing and the lane UDL off it:

```python
loads     = fill.disperse_model(traffic.get("A160"), datum=span/2, member_length=span)
dispersed = fill.dispersed_model_train(traffic.get("A160"))   # still positionable
moving_load_envelope(slab, dispersed, step=100.0,
                     static_loads=(fill.earth_pressure_udl(),))
```

Multi-wheel axles need transverse bookkeeping, and the obvious default is the
wrong one. A 1 m strip **on the vehicle centreline** of a 2 m axle under shallow
fill carries *nothing* — both patches sit either side of it. So `strip_offset`
defaults to `"worst"`, which searches for the governing strip:

```
depth  300 mm:  centreline   0.0 kN | worst at -1148 mm ->  80.0 kN
depth 3000 mm:  centreline  47.1 kN | worst at  -135 mm ->  47.1 kN
```

Shallow, the wheel lines govern; deep, the patches merge and the centre governs.
Summed over adjacent strips the total returns the axle load exactly, which is
the conservation check the tests assert.

---

## Enveloped demands

Results carry the **governing combination** alongside every value — the part
usually lost. Knowing `M* = 552 kN·m` is half an answer; knowing it came from
ULS2 is what lets a reviewer reproduce it.

```python
env.M_star, env.moment.governing_combo     # (5.52e8, 'ULS2')
env.shear_at_d_from_support(section.d)     # governing shear for the shear check
env.to_dict()                              # the ASET factored_forces.json shape
```

```json
{"B1": {"moment": {"Mz": {
   "fact_max": 552.0, "fact_max_combo": "ULS2",
   "fact_min": 0.0,   "fact_min_combo": "ULS2",
   "fact_max_position": 4000.0, "unit": "kN.m"}}}}
```

Uplift is detected and attributed: a reaction that goes negative under any
combination raises a note naming the combination and calling for a holding-down
detail.

---

## The report artifact

The durable standard is the **layout**, not the rendering library:

> inputs echoed → basis & envelope statement → step-by-step working with units →
> pass/fail against criteria → embedded plots/geometry → signature block

`handcalcs` is deliberately **not** the report engine — it renders the
arithmetic, one of six sections. It slots in as a renderer instead.

```python
report.passed      # every design check passed
report.issuable    # every module used is verified for issue
```

A calculation can pass every check and still not be issuable.

---

## The verification spine

> **No module enters the catalog without golden vectors and a named checker.**

`tests/golden/vectors/*.yaml` hold benchmark cases, each naming its source,
checker and date; `tests/golden/test_vectors.py` is one runner over all of them.
Adding a vector means adding a YAML case, not writing a test. Every vector
currently reads `checked_by: PENDING`, and the suite prints the outstanding list
on every run. `Provenance` enforces the rule in code: claiming `VERIFIED`
without a named checker raises.

---

## What is verified, and what is not

**Verified by test (275 passing):**

- Stiffness solver against closed-form solutions for simply supported,
  cantilever, propped cantilever, encastre and continuous beams — reactions,
  moments and deflections agreeing to ~1e-9 relative
- Sign conventions, including applied moments and hogging at cantilever roots
- Superposition, equilibrium, no double-counting of a point load on a node
- Flexural strain-compatibility solve against hand calculation (exact)
- Cracked section neutral axis and `I_cr` against hand calculation (exact)
- Load combinations, envelope extraction, governing-combination attribution,
  uplift detection, shared-grid enforcement
- Designation grammar round-trip across rectangular, tee and doubly reinforced
  sections; schedule round-trip in both forms
- Project record round-trip including forward-compatible unknown fields
- Moving-load sweeps against closed-form results: `PL/4` for a single load,
  `P(2L-a)²/8L` for a two-axle train, and a moving UDL longer than the span
  reducing to `wL²/8`
- Influence lines: peak `L/4` and area reproducing `wL²/8` for moment, the
  unit step across a shear section, and `-0.0962L` at the centre support of
  two equal spans
- Fill dispersal conserving load at every depth, and the patch-load moment
  `W(L/4 - a/8)` exactly
- Contract compliance across every public entry point
- Fail-closed behaviour throughout

**Not verified — needs a person with the standards:**

- Every numeric constant in both `constants.py` files
- AS 3600 Table 3.1.2 values, bar sizes, steel grades
- AS/NZS 1170.0 combinations and the ψ factors per occupancy
- Whether AS 3600 Cl 8.2.4.2's `k_v` uses `d_o` or `d_v`
  (see `KV_NO_STEEL_DEPTH_IS_DO`)
- AS 5100.5's φ for flexure, and its `k_uo` limit (0.36 or 0.40)
- **AS 5100.2 traffic geometry** — axle spacings, axle loads, UDL
  intensities, group counts and spacings. Recalled, not transcribed.
- AS 5100.2 load combination factors, and the dispersal slope through fill
- Amendment states — every `Standard.amendments` tuple is empty

---

## Not built yet

| | Why it matters |
|---|---|
| **HLP heavy load platform** | HLP320/HLP400 not implemented; `dla()` raises for them. |
| **Bridge actions beyond gravity + traffic** | The AS 5100.2 combination set covers permanent and road traffic only — no wind, thermal, shrinkage, earthquake, collision, flood or construction actions. |
| **Transverse distribution** | Traffic models are returned per lane; distributing onto a particular girder is left to the caller. |
| **Serviceability checks** | Deflection limits, crack control. `cracked_properties`, `cracking_moment` and the SLS envelopes are the foundation. |
| **Durability** | Cover and exposure. `Project.exposure` is recorded but not yet acted on. |
| **Prestress** | Stubbed. |
| **Torsion, columns, footings** | Out of scope for v0.1. |
| **Plots and DXF** | Component 6 also covers drawings. The report template has a figures section waiting. |
| **Multi-layer designations** | The grammar covers one layer per face; more raises rather than silently truncating. |

---

## Extending it

**A new section shape** — build it from bands (`from_bands`). Every integral in
the flexure solver works on any banded shape.

**A new design check** — add a module under `design/as3600/`, put constants in
`constants.py`, return a `CalcResult`, register `Provenance` at import with its
`ASETComponent`.

**A new standard** — add a `Standard` to `core/basis.py`, create
`design/<standard>/` with its own `constants.py`. Reuse `rc_common`; if you find
yourself copying from another code package, the shared part belongs in
`rc_common` instead.

**A new renderer** — implement `Renderer` in `report/renderers/`. Do not reorder
the sections.

**New reference data** — add a JSON file under `materials/data/` with `source`,
`status`, `checked_by`, `units` and a `_comment` block, and register it in
`_data.all_data_files()`.

---

## Governance

- **Versioning** — each module carries its own semantic version in its
  `Provenance`, independent of the package version.
- **Module register** — `REGISTRY.summary()` and `REGISTRY.coverage()` are
  generated from the modules themselves, so they cannot drift from reality.
- **Data register** — `_data.data_verification_report()` does the same for the
  reference tables. A table can be wrong while the code reading it is perfect.
- **Deprecation** — `VerificationStatus.SUPERSEDED` marks a module retained only
  to reproduce previously issued outputs.
- **Quarterly review** — those three reports are the input.
