# austruct — structural engineering toolkit

Python framework for structural design to **AS 3600:2018**, **AS 5100.5:2017**
and (later) **AS 5100.2:2017**, structured around the six components of the
**Automated Structural Engineering Toolkit** framework.

Version 0.1.0.

**Looking for a list of every calculation this package can run?**
[`CATALOGUE.md`](CATALOGUE.md) is generated directly from every module's
`Provenance` registration (`core/registry.py`) — it cannot drift from the
code the way a hand-written list can, and it's what to check before asking
"does this do X yet?". This README covers HOW to use each domain; the
catalogue covers WHAT exists.

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
| 3 | **Fast demand calculation** | `analysis/`, `structures/` | Beam and plane-frame stiffness solvers, moving-load sweeps, influence lines, pattern loading and redistribution, then enveloping with the governing case recorded. |
| 4 | **Design documentation** | `design_documentation/` | Plain-text designation grammar + CSV member schedules, round-tripping to sections. |
| 5 | **Design verification** | `design/`, `sections/` | AS 3600 and AS 5100.5 flexure, shear, serviceability, detailing and fatigue. AS 4100 steel: classification, section and member capacity, compression, combined actions. |
| 6 | **Reporting** | `report/` | Fixed audit layout, interchangeable renderers, engineer narrative in place. |
| — | Infrastructure | `core/` | The contract that lets 1–6 exchange data. |

That last row is not one of the six, but component 5 asks for exactly it: *"an
over-arching structure to coordinate the retrieval of information from the
multiple domains"*.

---

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                     # 802 tests
pip install -e ".[optimise]"  # + scipy, for austruct.study.optimise (see below)
pip install -e ".[tools]"  # + pydantic/pyyaml, for austruct.tools (see below)
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
L1   materials             concrete, reinforcement, bar catalogue,       [ASET 1]
                           steel grades banded by plate thickness
L1b  project               job record, occupancy, exposure, ψ factors    [ASET 2]
L2   sections              geometry primitives, RC sections, properties,
                           steel plate assemblies, section catalogue
L2b  design_documentation  designation grammar, member schedules         [ASET 4]
L3   analysis              loads, beam model, solver, moving loads,      [ASET 3]
                           influence lines, envelopes
L3b  loads                 combinations, AS 5100.2 traffic, dispersal,
                           pattern loading                              [ASET 2]
L3c  structures            box culvert, crown (arch) culvert,           [ASET 3]
                           perimeter profiles, directed node layout
L4   design                rc_common/ + as3600/ + as5100_5/ + as4100/    [ASET 5]
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
python examples/06_box_culvert_frame.py    # closed frame, directed nodes, HTML report
python examples/07_crown_culvert.py        # arch action, thrust, unbalanced fill
python examples/08_steel_beam.py           # AS 4100, buckling, restraint spacing
python examples/09_section_cost_optimisation.py   # cheapest RC section for a given M*
python examples/10_cantilever_wall.py      # AS 4678 wall, tools/ contracts, save/load
python examples/11_masonry_wall.py         # AS 3700 flexure and shear, one-way strip
python examples/12_optioneering.py         # sweep schemes across two design domains
python examples/13_gravity_wall.py         # modular gravity block wall, NCMA-style ASD
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

## Serviceability, detailing and fatigue

Strength design says a section works. Serviceability says the member is usable,
and detailing says it can be built. A beam that passes flexure and shear alone
has not been designed.

```python
state = as3600.effective_stiffness(section, M_s_max=180*kNm)   # I_ef, Branson
as3600.check_deflection(section, span, delta_sustained, delta_transient, M_s_max)
as3600.check_crack_control(section, M_s, cover=40, fitment_diameter=12)
as5100_5.check_steel_stress(section, M_s, exposure="B2")       # bridges
```

Three distinctions the API refuses to collapse, because the code is built
around them:

- **The peak service moment is a separate argument from the sustained one.**
  Cracking is irreversible, so the stiffness the sustained load acts on is the
  one the *peak* left behind. Passing the sustained moment overestimates
  stiffness and underestimates long-term deflection.
- **Creep multiplies only the sustained part**, never the transient part.
- **Steel stress past the end of a deemed-to-comply table is a failure, not an
  extrapolation.** The route simply does not extend there.

### Detailing — the check a capacity calculation cannot make

```python
as3600.development_length(20, fc=32, fsy=500, cover_to_bar=52, clear_spacing=40)
as3600.lap_length(20, 32, 500, staggered=True, generous_steel=True)
as3600.check_bar_fit(section, cover=40, aggregate_size=20)
as3600.check_detailing(section, cover=40, available_anchorage=1200)
```

`M_uo` is perfectly happy with twelve N32 bars in a 300 mm web that could never
be built. `check_bar_fit` is the only thing that isn't.

`check_detailing` **reports** development lengths but **refuses to check** them
unless you supply `available_anchorage`. The package sees a cross-section, not a
member, so it cannot know how much bar runs past the point of maximum stress.

### Fatigue

Fatigue responds to the stress *range*, not the peak — so it is the one check
that cannot come from a single static analysis, and it is the natural consumer
of the moving-load sweep:

```python
env = moving_load_envelope(beam, model.train_with_dla(), step=250.0,
                           static_loads=(UDL(magnitude=30*kN_per_m),))
as5100_5.fatigue_from_envelope(section, env, detail="welded")
as5100_5.worst_fatigue_position(section, env)
```

A consequence worth stating because it is counter-intuitive: **more dead load
does not worsen fatigue.** It raises the stress but not the range, and the tests
assert exactly that. The *detail* governs too, not the bar — a weld more than
halves the permitted range.

---

## Continuous members: pattern loading and redistribution

Loading every span of a continuous beam maximises nothing. On three equal spans,
patterning finds 12% more sagging and 8% more hogging than the fully loaded
case:

```python
env = analyse_patterns(beam, cases, as1170_uls())
env.moment.max_combo[env.moment.peak_max_index]    # 'ULS2 [alternate odd]'
```

The governing label names both the combination and the arrangement, because
patterns go through the same envelope core as the combinations and the moving
load sweep.

**Permanent actions are never patterned.** Self weight is present on every span
whatever the imposed load is doing; patterning it would model a beam with
sections of itself missing.

```python
r = redistribute(env, beam.support_positions, percentage=30.0)
r.sagging_increase                 # what it cost
as3600.redistribution_limit(kuo)   # what the code allows: 30% at kuo<=0.2, 0 at >=0.4
```

Redistribution rests on one fact: **adding a function that is linear within each
span leaves equilibrium unchanged**, because a linear moment diagram carries no
load. The correction is pinned to the chosen change at each support and
interpolated across the spans, with the end supports pinned at zero so the
reactions cannot move. Equilibrium holds by construction — `verify_equilibrium`
demonstrates it rather than enforcing it.

---

## Box culverts: a closed frame, with the nodes where you want them

A culvert top slab modelled as simply supported gets midspan roughly right and
everything else wrong. The real structure is a closed box, so the walls restrain
the slab and the corners carry hogging the simple model reports as **zero** —
which is top steel it never asks for.

```python
culvert = BoxCulvert(
    geometry=CulvertGeometry(clear_span=3000, clear_height=2400,
                             top_thickness=300, base_thickness=350,
                             wall_thickness=300),
    loading=CulvertLoading(fill_depth=1000, k0=0.5),
)
results = culvert.solve()
results.peak_moment(Wall.TOP)        # (fraction, moment)
results.bearing_pressure()           # from the soil springs
```

The base slab sits on a bed of **springs**, not pins: a pinned base attracts
corner moments no real soil could deliver, and the answer depends on exactly
where the pins were put.

Moments are reported with **tension on the inside face positive** for all four
sides. The frame works in each member's local axes, and the two walls disagree
about which way is "out" — so identical physical bending would otherwise read
`+23.8` on one and `−23.8` on the other. The test that the convention is right
is symmetry.

### Directing the nodes

A frame reports actions at nodes, so a peak *between* two nodes is never
reported. Three ways to put one where you need it:

```python
layout = PerimeterLayout(default_divisions=8)          # 1. uniform baseline
culvert.with_node_at_distance(Wall.TOP, 750, "construction joint")   # 2. by hand
culvert.with_node_at(Wall.LEFT, 0.5, "mid-height check")
refined = culvert.refined()                            # 3. onto the peaks
```

`refined()` solves, finds the zero-shear point **inside** every member by
statics — exact, not sampled — and pins a node there:

```
mesh                    nodes   reported sagging    error
3 divisions                12           13.09 kN.m   25.74%
3 divisions, refined       16           17.25 kN.m    2.17%
8 divisions                32           17.56 kN.m    0.40%
200 divisions             800           17.63 kN.m    0.00%
```

Four extra nodes take the error from 26% to 2%. Every pinned node records *why*
it is there, so a reviewer can see the mesh was directed rather than arbitrary.

`peak_moment()` adds the interior extrema itself, so it is right whether or not
the mesh has been refined — refinement matters when you want the *nodal* output,
a plot, or a schedule to land on the peak.


---

## Crown (arch) culverts

A crown unit is not a box with a curved lid. A box carries load in **bending**;
an arch carries it in **thrust**, and what is left over after the thrust has
done its work is a much smaller moment. Same span, same cover, same 250 mm
thickness:

```
box top slab peak M    =  17.81 kN.m
arch crown  peak M     =   5.81 kN.m
arch crown  max thrust =   60.3 kN
```

That is the reason for the shape — and the reason the footing has to be able to
hold the thrust.

```python
culvert = CrownCulvert(
    geometry=CrownGeometry(
        span=4000, rise=1200, leg_height=1500,
        crown_thickness=200, haunch_thickness=350, haunch_extent=0.18,
        leg_thickness_base=300, leg_thickness_top=225,   # tapered legs
    ),
    loading=CrownLoading(fill_depth=600, k0=0.5),
)
r = culvert.solve()
r.segment_thrust(Part.CROWN)     # compression positive
r.springing_thrust()             # (horizontal, vertical) at the foot
r.arch_efficiency                # M/(N.t) at the apex
```

**Tapered legs and haunches** are first-class: `profile.py` supplies `Line` and
`Arc` paths and `Constant` / `Tapered` / `Haunched` thickness profiles, and each
element takes the thickness at its own midpoint. A haunched crown really is
stiffer at the springing in the model, not just in the drawing.

**The fill depth varies across the crown** — deepest at the springings,
shallowest at the apex — and the soil stress is resolved onto each element's own
orientation, giving both a normal and a tangential traction. On a flat slab the
tangential part vanishes; on an arch it feeds straight into the thrust.

### Two things worth knowing before you design one

**The springing thrust can point the wrong way.** An arch pushes its supports
apart; backfill pushes the legs together. Which wins depends on the leg height
and the earth pressure:

```
    k0    H at left foot   direction
  0.001         12.0 kN     OUTWARD
  0.200          0.4 kN     OUTWARD
  0.500        -17.1 kN      inward
  0.800        -34.6 kN      inward
```

With 1.5 m legs under 1.8 m of cover this unit's feet are pushed **inward**. A
footing designed for outward thrust alone would be resisting the wrong
direction.

**The unbalanced case governs.** Symmetric lateral pressure largely cancels;
asymmetric pressure does not, and an arch is far more sensitive to it than a box:

```
case                          left leg M   right leg M
balanced                        -5.15         -5.15
20 kPa surcharge one side       12.35        -24.36
40 kPa surcharge one side       21.01        -43.57
```

A one-sided surcharge multiplies the leg moment eightfold. Backfilling one side
ahead of the other is the same case, applied to a unit with no fill on top to
hold it down — so construction sequence is a design condition, not a site
matter. Use `surcharge_left` / `surcharge_right`.

### Divisions matter more than node placement on a curve

On a box the geometry is exact and only the sampling is coarse, so `refined()`
fixes the answer outright. On a crown the geometry is a **chain of chords**, so
the error is geometric and refinement converges rather than snapping to the
peak. The crown's division count is therefore chosen from the **subtended
angle**, not from a round number:

```python
geometry.recommended_crown_divisions()   # 25 for a 124-degree arc, ~5 deg/chord
```

This is applied by default, and it matters: eight divisions on this arc looks
generous and is 12% wrong. Pass `divisions={Part.CROWN.value: n}` to override.

Node directing works exactly as it does on a box, except distances along the
crown are measured **along the arc** — which is what the unit is made to:

```python
culvert.with_node_at_distance(Part.CROWN, 1000, "lifting point")
culvert.with_node_at(Part.CROWN, 0.5, "apex")
```

### What is not modelled

- **Soil-structure interaction.** Free-field stresses only: no arching, no
  relative-stiffness redistribution, no Marston or Spangler factor. A rigid
  culvert under fill attracts *more* than the free field, so this is
  **unconservative** unless you supply `vertical_arching_factor`.
- **Combined bending and axial force.** The thrust is reported but
  `check_flexure` takes no account of it. For a section below the balance point
  the compression would increase the moment capacity, so ignoring it is
  conservative for flexure — but the section has **not** been checked for
  combined actions, which needs the N–M interaction this package does not have.
- **Any manufacturer's product.** This is a parametric model of a crown unit,
  not a model of a Humes unit. Span, rise, thicknesses and haunch dimensions
  come from the catalogue and must be entered.


---

## Steel to AS 4100

### The catalogue checks itself

Every other reference file here can only be confirmed against the printed
source. The steel catalogue is different: it holds the **dimensions** and the
**published properties**, and the second follows from the first. So they can be
compared.

```python
from austruct.sections import steel_catalogue as cat
print(cat.verify_catalogue().report())
```

```
prop       mean     tol   expected cause
A        -0.76%      5%   fillet material at the web
Ix       -1.16%      5%   as A, close to the neutral axis
Iy        1.36%      3%   fillets barely affect the minor axis
J       -11.68%     40%   acutely sensitive to the junction
```

Computed low on the major axis, barely moved on the minor, badly low in torsion
— that is the signature of the unmodelled root radii, not of a mistake. The
*direction and size* of the error are what distinguish the two, which is why the
tolerances differ per property rather than being one number.

**It found things.** Every UB and UC is internally consistent. Three channels
are not: their dimensions disagree with their own tabulated area by 5–20%, in
the wrong direction for fillets. A third independent source settles it — mass
per metre divided by density:

```
section       from dims  published  from mass   verdict
100PFC             1265       1060       1061   DIMENSIONS disagree with the table
```

Two sources against one, so the dimensions are wrong. They are left as recorded
and flagged `INCONSISTENT`, because tuning them until the check goes green would
produce a file that is self-consistent and wrong.

The check does **not** prove the catalogue is right — a section family
misremembered consistently would pass. What it buys is the elimination of the
single most likely error, a typo, from a file with three hundred numbers in it.
Its sensitivity floor is documented and tested too: a flange 10% too thick hides
inside the fillet band, a flange *width* error does not.

### f_y depends on thickness, not just grade

A Grade 300 UB has a different yield stress in its flange than its web, because
they are different thicknesses. AS 4100 uses the flange value for flexure and
the web value for shear. So there is deliberately **no** `grade.fy` — every
lookup takes a thickness.

```python
section.fy_flange   # 320 MPa -- what flexure uses
section.fy_web      # 320 MPa -- what shear uses; higher on a thicker section
```

### The gate: section capacity is not the answer

For reinforced concrete the section capacity essentially *is* the answer. For
steel it is not — a beam almost always fails by lateral-torsional buckling
first. So `check_flexure` **refuses to run** on an undeclared beam:

```python
>>> as4100.check_flexure(beam, 200*kNm)
ModelError: check_flexure computes the SECTION capacity, which is the member
capacity only for a fully restrained segment...
Either pass fully_restrained=True ... or use as4100.check_member_flexure()
```

How much it matters, for a 360UB50.7:

```
restraint   M_b/M_s
      1 m       99%
      4 m       53%
      9 m       24%
     12 m       18%
```

A design that stopped at `M_s` would be wrong by a factor of five.

### α_m comes off the real moment diagram

The moment modification factor needs the moments at the quarter, mid and
three-quarter points — which the solver already produces. So the real diagram is
used, not the nearest textbook case:

```python
env = analyse_combinations(member, cases, as1170_uls())
alpha_m = as4100.alpha_m_from_diagram(env.moment.x, env.moment.max_values, 0, span)
# 1.166 for a parabolic diagram, against 0.981 for uniform moment
```

### Restraint spacing is a design variable

For M* = 188 kN·m over 9 m, the section that works depends almost entirely on
how often you brace it:

```
restraint spacing   section       mass kg/m
          9.0 m     530UB92.4          92.4
          4.5 m     460UB74.6          74.6
          3.0 m     360UB50.7          50.7
          1.5 m     360UB44.7          44.7
```

Halving the restraint spacing is worth more than two section sizes. On a steel
beam the bracing is a design decision, not a detail.

### What the package will not guess

`k_t`, the twist restraint factor, is **required** for anything but a fully
restrained segment. AS 4100 gives it as an expression in the section geometry
and segment length, not a table of constants, so defaulting it to 1.0 would
treat partial restraint as full:

```python
as4100.segment(6000, "FF")                 # k_t = 1.0, stated by the standard
as4100.segment(6000, "FP", kt=1.08)        # read off Table 5.6.3(1)
as4100.segment(6000, "FP")                 # raises
```

Load height is the factor people forget — a gravity load on the **top flange**
is destabilising and costs about 32% of the capacity:

```python
as4100.segment(6000, "FF", load_height="top flange")   # l_e = 8400, not 6000
```

### Compression and combined actions

```python
as4100.check_compression(column, N_star, le=4000, axis="y", alpha_b=0.5)
as4100.check_combined_member(column, N_star, M_star, seg, le_compression=4000)
```

The bending and compression effective lengths are **separate arguments**,
because the bracing that restrains a beam against lateral-torsional buckling is
often not the bracing that holds a column.

And the reason combined actions exist at all: a member at 70% in compression and
70% in bending is not at 70% — the interaction is 1.40 and it has failed.

### Not implemented

Connections, web stiffeners and bearing, fatigue, torsional and
flexural-torsional buckling, biaxial bending, tension members, and composite
construction (a different standard). The torsion constant `J` is thin-walled and
runs 10–30% low for a rolled section, which makes `M_o` and therefore `M_b`
conservative.

---

## Masonry to AS 3700

Flexure and shear only, by design — this package does not attempt compression/
buckling, in-plane shear walls, or two-way panel bending. Every wall is
designed as a **one-way strip**, exactly like a one-way slab: the same
simplification as the rest of this section's numbers, stated up front rather
than discovered by reading the source.

```python
from austruct.design import as3700
from austruct.materials.masonry import get_unit, masonry_properties, MortarClass
from austruct.sections.masonry_section import masonry_wall

unit = get_unit("block_190")
grade = masonry_properties(unit.f_uc, MortarClass.M3, grouted=True)
wall = masonry_wall(unit.thickness, grade)

as3700.check_flexure(wall, 2.0 * kNm, direction="vertical", fd=0.15)
as3700.check_flexure(wall, 2.0 * kNm, direction="horizontal")
as3700.check_shear(wall, 20 * kN, fd=0.15)
```

### Three flexural mechanisms, not one

`check_flexure` dispatches on the SECTION, not a flag the caller has to get
right: a wall with vertical reinforcement in grouted cores always uses the
reinforced stress-block formula (`direction` is ignored — there is only one
reinforced mechanism in this scope); an unreinforced wall uses `direction` to
choose vertical bending (tension perpendicular to the bed joints, the weak
axis) or horizontal bending (tension parallel, using a `kp` enhancement on
`f'mt`).

Vertical bending gets a credit for design compressive stress `fd` — self-weight
of wall above pre-stresses the section against the tension that would
otherwise crack it first — capped at a documented multiple of `f'mt` so a
large `fd` cannot imply unbounded capacity. Horizontal bending gets no such
credit in this simplified strip model.

### The governing check is not always the one you expect

```python
>>> result = as3700.check_flexure(heavily_reinforced_wall, 6.0 * kNm)
>>> for check in result.checks:
...     print(check.describe())
Ductility, k_u <= limit: 0.4252 <= 0.36  (utilisation 1.181)  FAIL
Flexural strength, M* <= phi.M_uo: 6 <= 9.4 kN.m/m  (utilisation 0.638)  PASS
```

Plenty of steel to develop the moment, comfortable strength margin — and it
still fails, because `ku = a/d` breaches the ductility limit before the
strength check even gets a vote. `result.utilisation` is the governing value
across every check, same convention as `as3600`/`as4100`.

### Shear is the bed-joint mechanism, and reinforcement doesn't help it

`check_shear` implements AS 3700's bed-joint friction/bond shear — the
mechanism that pairs with the one-way bending strip above, resisted across
the wall's THICKNESS at the support of the spanning strip. It is **not** the
in-plane shear-wall (racking) check, which resists lateral load in the
plane of the wall over its LENGTH and is not implemented here.

```python
>>> as3700.shear_capacity(plain_wall, fd=0.15).get("Vo")
56000.0
>>> as3700.shear_capacity(reinforced_wall, fd=0.15).get("Vo")   # same masonry, with bars
56000.0
```

The vertical bars that resist flexure do not cross this shear plane the way
stirrups cross a beam's — crediting them would overstate the capacity, so
`shear_capacity` returns the identical masonry-only term whether or not the
section is reinforced. Only `phi` differs, because AS 3700 ties the capacity
reduction factor to category of construction, not to this particular
mechanism.

### What this package will not guess

- **Two-way panel bending** (AS 3700 Cl 7.4.3's yield-line method) — a real
  panel supported on more than two edges is stronger than this one-way strip
  says. Reading a FAIL here is conservative, not proof the panel fails.
- **In-plane shear walls** — lateral racking resistance, typically governed
  by horizontal bond-beam steel this package's `MasonryWallSection` does not
  model (it holds vertical bars only).
- **Compression and slenderness/buckling** — in most masonry wall design this
  is the check that actually governs; it is out of scope here entirely, by
  request, not oversight.
- **Detailing** — minimum reinforcement, bar spacing, lap lengths.
- **The full Table 3.1/3.3 material dependence** — `f'm`, `f'mt` and `f'ms`
  are derived from simplified formulas in `materials/masonry.py`, not the
  full unit-height/category tables. Use a tested value wherever precision
  matters.

[VECTOR] Every constant in `design/as3700/constants.py` and every derivation
in `materials/masonry.py` is UNVERIFIED, and more heavily simplified than
this package's AS 3600/AS 4100 modules — confirm against the printed
standard, or a test report, before issue. `examples/11_masonry_wall.py`
demonstrates the plumbing, not a checked design.

---

## Minimum-cost RC section search

Given a design moment, `as3600.minimum_cost_section` searches a grid of
practical widths and depths and, at each size, asks the bar catalogue for the
cheapest single-layer arrangement that clears `check_flexure` **in full** —
strength, ductility and minimum strength together, not just `M* <= phi.Muo`.

```python
bounds = as3600.SearchBounds(
    width=as3600.SizeRange(250, 500, 50),
    depth=as3600.SizeRange(400, 900, 50),
)
rates = as3600.CostRates(concrete_per_m3=180.0, steel_per_tonne=2200.0)
result = as3600.minimum_cost_section(300 * kNm, concrete(32), bounds, rates)

result.governing.describe()
# '250 x 650  3-N24       util 0.970  cost 52.69 (concrete 29.25 + steel 23.44)'
```

Every `SectionCost` in `result.candidates` carries the actual `check_flexure`
result for that exact section — the same object a hand-picked section would
produce, not a re-derived summary. `result.candidates` is sorted by cost, so
the next-cheapest alternatives are visible alongside the winner rather than
thrown away.

### It is a genuine trade-off, not "add more steel" or "go deeper"

Every candidate pays the same rate per unit mass, so the cheapest bar
arrangement at a given size is also the least-area one — no separate
cost-ranking of arrangements is needed. What is *not* free is the size
itself: run the search at different relative steel prices and the winning
shape changes.

```
   steel $/t       section      bars        cost
        800       250x550     3-N28        36.4
       2200       250x650     3-N24        52.7
       8000       250x900     3-N20        99.7
```

Cheap steel buys a shallow section with more bars; expensive steel buys
depth instead, because lever arm is free and steel mass is not. That is why
the search runs over sizes and bar arrangements together, rather than fixing
a depth and only choosing bars against it.

### What it deliberately does not do

- **No shear reinforcement.** Fitments are sized once a section is chosen —
  run `as3600.check_shear` against the winning candidate.
- **No formwork, wastage or labour cost.** `CostRates.other_cost_rate` is a
  flat per-metre addition the engineer can supply; it does not model any of
  these.
- **No multi-layer or mixed-diameter arrangements.** A section that only
  closes up in two layers will not appear as a candidate — widen the depth
  range rather than expecting the search to find it.
- **No grade search.** Concrete grade is fixed per call. Run the search again
  at a different grade to compare; which grade to use is the engineer's
  decision, not one this function makes on their behalf.
- **An infeasible grid comes back empty, not relaxed.** `result.governing` is
  `None` when no size in the grid can develop `M*` at all, or no catalogue bar
  fits the width — that means widen the bounds, not that the moment cannot be
  carried.

---

## A bolt-on tools layer: cantilever retaining walls (AS 4678 + AS 3600)

Everything above lives in `src/austruct/` — L0 core through L5 report — in
that layer's own convention: plain floats in mm/N/MPa, no runtime units
library, no Pydantic. `src/austruct/tools/` sits *on top of* that, for a
different class of input: an engineering **judgement call** (a backslope, a
water table depth, how much toe cover to write off for services trenching)
rather than a code-mandated range. Those get construction-time validation —
rejected before any calculation runs, not mid-calculation — which is a job
`Envelope` was never meant to do and a Pydantic model does well.

```bash
pip install -e ".[tools]"     # pydantic + pyyaml, on top of the core install
```

`austruct` core stays exactly as dependency-minimal as before — nothing in
`tools/` is imported by anything under `design/`, `analysis/`, `sections/`,
or any other L0–L5 package. The wheelhouse/`.exe` distribution path for the
core layers (see the dependency note at the top of `pyproject.toml`) is
unaffected; only an install that actually uses `tools/` pulls Pydantic in.

### The contracts convention

Every tool's `*Input` and `*Result` inherit from `austruct.tools.contracts.ToolkitModel`:
strict on unexpected fields (`extra="forbid"` — a typo'd or stale field is
rejected loudly, not silently dropped), versioned (`schema_version`), and
round-trips through one save/load pair:

```python
from austruct.tools.contracts import save_result, load_result

save_result(result, "wall_1.json")
reloaded = load_result(WallResult, "wall_1.json")   # RE-validated on the way in
```

That round trip is the actual mechanism for composing tools later — a
smaller tool's `Result` becomes a larger tool's `Input` by serialising once
and re-validating on the way back in, not by trusting an in-memory object to
still mean what it meant when it was built.

### Usable with geometry plus one soil type

```python
from austruct.tools.cantilever_wall import WallGeometry, SoilInput, WallInput, analyse

wall = WallInput(
    geometry=WallGeometry(
        H_retained=4.0, base_length=3.6, base_thickness=0.55,
        toe_length=1.0, stem_thickness_top=0.3, stem_thickness_bottom=0.45,
    ),
    soil=SoilInput(soil_type="clean_sand", surcharge=5.0, water_table=None),
)
result = analyse(wall)
```

Everything else — `gamma`, `cohesion`, `delta`, `backslope`, base friction,
passive-neglect depth — defaults, and **every** default or preset-derived
value is tagged with where it came from, not just quietly substituted:

```python
>>> result.assumptions
["Wall friction delta = 20 (default)", "Backslope = 0 (default)"]
>>> result.resolved_soil.phi
SourcedValue(value=32.0, source='preset')
```

`water_table` is the one field with no silent default at all —
`SoilInput(phi=30.0)` without it raises. A drained design is a decision
(`water_table=None`), not an assumption this tool is willing to make quietly.

### Material factors flow into the pressure calculation, not the answer

AS 4678 factors soil strength — `Φ_uφ` on `tan(φ)`, `Φ_uc` on cohesion —
**before** the earth-pressure calculation, not afterwards:

```python
>>> resolved_soil.phi.value      # characteristic
32.0
>>> design_soil.phi_deg          # what Ka actually used
28.0
```

Every check reads from one `StabilityLedger` built from those design
values — self-weight, the soil-on-heel wedge (surcharge included — see
below), and the earth-pressure thrust, each tagged `stabilising` or
`destabilising` for its AS 4678 action factor *and, independently*, `resists`
or `overturns` for its moment about the toe. Those two classifications can
disagree: a backslope's vertical thrust component is factored as part of the
(destabilising) earth-pressure action, even though the force itself, acting
at the back of the footing, resists overturning — a documented, conservative
simplification, not an oversight.

### Sliding, eccentricity, bearing — ranked, not pass/fail

```python
>>> for name in ("sliding", "eccentricity", "bearing"):
...     check = result.checks[name]
...     print(name, check.utilisation, check.passed)
sliding      0.947  True
eccentricity 0.384  True
bearing      0.270  True
```

Each `CheckSummary.working` is the full `CalcResult.to_dict()` — basis,
intermediates, every message — not just the number. That is what "every
check must emit readable working" means here: reused from the same
`CalcResult` contract the rest of the package uses, rather than a separate
rendering library, and it survives the save/load round trip intact.

### Stem/heel/toe design — and the check that actually governs

`result.checks` also carries `stem_flexure`/`stem_shear`,
`toe_flexure`/`toe_shear` and `heel_flexure`/`heel_shear` — real AS 3600:2018
member design (`design.as3600.flexure`/`shear`, `rc_beam`), driven by the
actual actions this tool's own geometry and pressure methods derive, on a
DIFFERENT factor regime from the stability checks above: AS 1170.0-style
load factors (1.35 permanent, 1.5 variable), not the AS 4678 stabilising/
destabilising pair — see `member_design.py`'s module docstring for why
reusing the stability factors for a local member would be wrong.

```python
>>> result.checks["toe_flexure"].passed
False
```

A footing thick enough for bearing is routinely governed by AS 3600
Cl 8.1.6.1's minimum-strength check (`M_uo >= 1.2 M_cr`) rather than by its
own modest bending — the toe above can pass `M* <= phi.M_uo` at exactly
1.000 utilisation and still fail overall, because `required_steel_area()`
bisects on strength only and does not iterate further for the minimum-
strength check. This is real, common behaviour for a retaining wall
footing, not a bug — `examples/10_cantilever_wall.py` walks through the
exact numbers.

### Method B, and a divergence that is real, not noise

`analyse()` also runs a Culmann trial-wedge search (`pressure/culmann.py`)
and compares it against Method A:

```python
>>> result.method_a.thrust_horizontal, result.method_b.thrust_horizontal
(62.16, 62.16)
>>> result.divergence.describe()
"Horizontal thrust P_h: A = 62.16, B = 62.16  (0.0% divergence, informational) -- the methods agree"
```

At zero backslope the two methods match to floating-point precision — a
genuine cross-check, not a coincidence. With a backslope, they diverge for
real: Rankine's backslope solution assumes the resultant acts parallel to
the sloping ground; the Culmann wedge search at zero wall friction assumes
a horizontal wall reaction. These are two different, both textbook-correct,
boundary conditions that only coincide at zero backslope — confirmed
against Coulomb's own closed-form `Ka(phi, beta, delta=0)` formula, which
the numerical search reproduces exactly. `compare_thrust()` bands the
result (under 5% informational, 5–15% warn and names the cause, over 15%
flag) and **never averages the two or silently prefers one** — a "flag"
divergence fails the wall overall, full stop.

Where `water_table` is set, Method B does not run at all — comparing a
submerged Method A against a dry-unit-weight Method B would be misleading,
not merely approximate, so `method_b`/`divergence` come back `None` and
`notes` says so, rather than either crashing or comparing silently.

This tool's `surcharge` is a single flat, infinite-extent value, with no
set-back distance — the classic "surcharge behind the failure wedge doesn't
load the wall" divergence source needs an input this tool does not yet
have, and worked through algebraically the two methods actually agree
closely on surcharge alone. Backslope, not surcharge, is this tool's real
divergence source today.

### What this pass does not include

- **Compaction-induced pressure**, the global-stability geometry screen, and
  a shear key contribution to sliding.
- **AS 5100.3 and `working_stress.yaml` factor sets** — only
  `as4678_class_b.yaml` exists; adding a framework is a new YAML file plus a
  `FactorSet`, not a code change to any check.
- **Wall friction (delta) in Method B** — the trial wedge search assumes a
  frictionless virtual plane, matching Method A's Rankine assumption, so the
  two remain comparable; crediting wall friction is a real extension.
- **Cohesion in Method B** — the wedge weight is soil and surcharge only.
  Where a cohesive soil is genuinely in use, expect Method A (which credits
  cohesion relief) to read lower than Method B, and the divergence report to
  name cohesion as the likely cause.

[VECTOR] Every AS 4678/AS 1170.0-style factor, the soil preset library, and
the Terzaghi/Meyerhof bearing-capacity formula are UNVERIFIED, as declared
throughout this package. `examples/10_cantilever_wall.py` demonstrates the
plumbing, not a checked design.

---

## Modular gravity block walls (NCMA-style allowable stress design)

`tools/gravity_wall` — a stack of modular blocks (Redi-Rock, Allan Block,
Versa-Lok and similar systems all share this shape) held up by its own
mass alone, no reinforcing steel and no footing. It grew out of a user
request for exactly this wall type; the manufacturer PDF supplied as a
starting point turned out to be pre-computed height tables with no
methodology behind them (confirmed by grepping its extracted text for
"sliding", "overturning", "factor of safety" and finding nothing), so this
tool is built to the established **NCMA-style allowable stress design**
convention instead — the industry-standard approach these systems are
generally checked against — with a **manufacturer-agnostic** block
catalogue rather than one tied to a single product line.

**Deliberately a different design philosophy from `cantilever_wall`, not a
second implementation of the same one.** `cantilever_wall` is AS 4678
limit-state design: a material factor reduces tan(phi) *before* the
pressure calculation, and separate action factors load up the resulting
forces. This tool is allowable stress design: every force uses
**characteristic** (unfactored) soil strength throughout, and a single
factor of safety is checked against the *whole system response* — `FS =
resistance / demand`, e.g. `FS_sliding = R/H >= 1.5`. Reusing
`cantilever_wall`'s AS 4678 machinery here would have been quietly wrong;
what IS reused is `cantilever_wall`'s soil model
(`SoilInput`/`ResolvedSoil`/`resolve_soil`/the preset library) and its
Terzaghi/Meyerhof bearing-capacity factors, because *those* are not
specific to either design philosophy.

```python
from austruct.tools.gravity_wall import (
    GravityWallGeometry, GravityWallInput, SoilInput, analyse, block_series,
)

geometry = GravityWallGeometry(n_courses=8, block=block_series("large_60in"), embedment=0.4)
soil = SoilInput(soil_type="clean_sand", surcharge=5.0, water_table=None)
result = analyse(GravityWallInput(geometry=geometry, soil=soil))

for name, check in result.checks.items():
    print(f"{name:<16} FS-utilisation {check.utilisation:.3f}  {'PASS' if check.passed else 'FAIL'}")
```

### Geometry is a course stack, not a stem/heel/toe

A `BlockSeries` (from the catalogue, or built by hand) carries a course
`width`, `height` and `setback` — most segmental systems achieve their
standard batter by stepping each course back a fixed amount from the one
below (a pin/knob/lip detail), not a sloped block face, so the wall's
batter angle is *derived* from `setback/height`, never a separate input
that could disagree with it. `GravityWallGeometry` is just `n_courses`
plus a `BlockSeries`; there is no separate reinforced-concrete member
design to do, because the blocks themselves are the gravity mass.

### General Coulomb pressure, and a sign convention worth getting right

`cantilever_wall`'s Rankine method has no wall-batter or wall-friction
term — a gravity block wall has no heel to erect a Rankine virtual plane
on, so this tool needs the *general* Coulomb formula instead, with the
wall's own battered back face and an interface friction angle `delta`.
This surfaced a genuine trap while building it: Coulomb's own `omega` sign
convention is **positive when the wall face tilts INTO the backfill**
(which *increases* Ka), the opposite of what "a wall battering away from
the soil reduces pressure" intuition suggests. A block wall's own batter
(always a positive number, `BlockSeries.batter_deg`) is therefore passed
into the pressure calculation **negated** — `omega_deg =
-geometry.batter_deg` in `api.py` — and this is pinned by a regression
test (`test_analyse_negates_batter_deg_for_the_coulomb_sign_convention`)
precisely because the wrong sign would silently *increase* the reported
pressure for every wall this tool analyses, in the conservative direction,
easy to never notice. The degenerate case (`omega = delta = beta = 0`)
still reduces exactly to `cantilever_wall.pressure.rankine.Ka_rankine` —
verified to floating-point precision, the same regression-test pattern
`cantilever_wall`'s own Method A/B cross-check uses.

### Four FS-based checks — three familiar, one new

Sliding, overturning and bearing mirror `cantilever_wall`'s stability
checks in spirit (same underlying mechanics — friction, a toe-moment
balance, Meyerhof effective width — just FS-based instead of
demand/capacity-based, and against characteristic rather than factored
soil). **Interface shear** has no analogue in a monolithic concrete wall
at all: a block wall is a *stack of discrete courses*, and nothing stops
one course sliding on the one below except that interface's own shear
capacity. This tool checks every course boundary and reports the
governing one, modelling the interface as a simple linear Mohr-Coulomb law
(`capacity = c_interface + N.tan(delta_interface)`) — a deliberate
simplification of how these connectors are actually characterised in
practice (ASTM D6916 testing produces a bilinear peak/residual envelope,
not a straight line extending forever); see `checks/interface_shear.py`'s
module note for exactly where that simplification could read
unconservative on a tall wall.

### What this tool does not include

- **No passive resistance in sliding** — a block wall's toe is rarely a
  formed key the way a cantilever footing's is; crediting passive
  resistance from shallow, often-disturbed fill in front of the wall is a
  common source of overconfidence in these systems, so this tool doesn't.
- **No water table.** `GravityWallInput` rejects one outright (raises,
  rather than silently ignoring it) — a submerged block wall needs a
  geotechnical review this tool does not attempt to automate.
- **No cohesion credit in the pressure calculation** — these systems are
  specified with free-draining granular backfill; a cohesive fill behind
  one is itself a design deviation, not something to quietly relieve
  pressure for.
- **No global stability screen** — the same gap `cantilever_wall` has;
  `notes` on every result says so rather than silently omitting it.
- **No geogrid-reinforced segmental walls.** A *gravity* block wall (mass
  alone provides stability) and a *reinforced* segmental retaining wall
  (geogrid layers extending into the backfill, resisting a different
  failure mechanism entirely) are materially different design problems —
  this tool is the former only.

[VECTOR] The block catalogue's course `height` and `unit_weight` are
documented placeholders, not transcribed from any manufacturer data sheet
(the source PDF never states them); the interface friction/cohesion
defaults, and the FS 1.5 interface-shear minimum, are typical values,
UNVERIFIED. See `data/block_catalogue.json`'s `source` field and
`factors.py`'s module docstring for exactly what is and is not backed by
the source document. `examples/13_gravity_wall.py` demonstrates the
plumbing, not a checked design.

---

## Optioneering: running variations on a scheme

Most of a design engineer's time on a job that already has a working answer
goes into RUNNING VARIATIONS on it — a deeper section with less steel, a
different mortar class, three toe widths for the same wall — and comparing
the results. `austruct.study` is that workflow, generalised: it does not
know what a beam or a wall is, only that whatever a check returns has
`.utilisation` and `.passed` — which every `CalcResult` in this package
already provides. One engine sweeps every design domain.

```python
from austruct.study import Scheme, run_sweep

schemes = [
    Scheme("A", {"D": 600, "diameter": 24}),
    Scheme("B", {"D": 700, "diameter": 20}),
]
result = run_sweep(
    schemes,
    build=lambda b, D, diameter: rc_beam(b, D, concrete(32), n_bars=4, diameter=diameter, fitment_spacing=200),
    check=lambda section: as3600.check_flexure(section, M_star),
    base={"b": 300},
    cost=lambda section: section.geometry.area * 1e-6 * 180.0,
)
result.governing.scheme.name   # cheapest PASSING scheme -- or None if nothing passed
```

### The same engine, any design domain

`austruct/study/` imports nothing from `design/`, `sections/` or
`materials/` — `build` and `check` are supplied by the caller, so the exact
same `run_sweep()` call sweeps an RC beam, a masonry wall, or a retaining
wall's stability checks. `examples/12_optioneering.py` runs the identical
engine against RC flexure and masonry flexure back to back.

### A scheme that doesn't build is reported, not thrown

A malformed row (bad geometry, an envelope breach) is caught and recorded
with its error — `SweepResult.errored` — rather than stopping the run.
One bad option in a real six-option list should not hide the other five.

### From a spreadsheet, because that's the shape a brief actually arrives in

```python
from austruct.study import load_schemes_csv, save_schemes_csv
```

```
scheme,D,diameter,notes
A,600,24,
B,700,20,deeper and leaner
C,,,identical to the base scenario
```

A blank cell means "no override for this scheme" — it inherits the sweep's
`base` value — not "override to nothing". Column names are whatever the
caller's `build` function expects; this module has no opinion on what "D"
means.

### Discrete comparison vs continuous search

`run_sweep()` is for a reviewable, NAMED list of options — the six things
someone actually asked about, every one of them visible in the output,
including the ones that fail. For "what is the cheapest section that still
passes" rather than "which of these passes", `austruct.study.minimize_scheme`
drives a continuous `scipy.optimize` search over the same `build`/`check`
shape:

```python
from austruct.study import minimize_scheme   # needs: pip install -e ".[optimise]"

result = minimize_scheme(
    variables={"b": (200.0, 600.0), "D": (400.0, 1000.0)},
    build=build_rc, check=check_rc, cost=cost_rc,
)
result.describe()
# 'converged (...): b=200, D=623  ->  util 1.000  PASS'
```

`scipy` is an optional extra, not a core dependency — importing
`austruct.study.optimise` without it works; calling `minimize_scheme()`
raises with the install instruction. And `scipy.optimize` only ever sees
the objective and constraint functions handed to it — it has no idea what
an `Envelope` or a ductility limit is, so `OptimiseResult.result` is always
a REAL `check(build(**x))` call at the optimiser's final point, re-verified
rather than trusted. It also has no concept of the DISCRETE choices this
toolkit is full of — catalogue bar diameters, standard steel sections,
block-thickness series — those stay on the existing catalogue-search
pattern (`options_for_area`, `bar_catalogue`, `steel_catalogue`); round a
continuous optimum to a practical discrete value and re-verify, the same
"estimate, then verify" pattern `required_steel_area`'s bisection already
uses.

---

## Reports someone else can read

A report that reaches a road authority or an independent reviewer is read by a
**person**, who needs the reasoning between the numbers. So the report body is
one ordered list, and the engineer's prose sits where it was written:

```python
report.add_scope("Covers the top slab in flexure, crack control and deflection.")
report.add_assumption("Founded on granular material, k_s = 30 MPa/m from the geotech report.")
report.add(flexure)
report.add_narrative("The corner hogging governs the top face, which a simply "
                     "supported idealisation reports as zero.")
report.add(crack_control)
report.add_limitation("Every code constant is UNVERIFIED. Not for issue.")
report.add_conclusion("The 300 mm slab with 5-N20 per metre is adequate.")

Path("report.html").write_text(report.render(HtmlRenderer()))
```

This is the notebook workflow: write the calculation in a cell, write what it
means in the next, and the document keeps both in order. Keeping prose in a
separate list forces it to the end, where nobody reads it and where it no longer
explains anything.

The **HTML renderer** emits one self-contained file — inline styling, no
JavaScript, no external requests of any kind, so nothing is stripped by a
corporate firewall and it opens identically anywhere. It carries a print
stylesheet that avoids splitting a check table across pages, and an unverified
report is banded on **every printed page**, so a page photocopied out of context
still carries the warning.

Engineer narrative is styled distinctly from generated content, because a
reviewer needs to tell a statement by the engineer from an output of the
package — that distinction is where responsibility sits.

```python
report.has_narrative(NarrativeKind.ASSUMPTION)   # check before issue, not after
```

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
| **Durability** | Cover and exposure. `Project.exposure` is recorded but not yet acted on. |
| **Prestress** | Stubbed. |
| **RC torsion, columns, footings** | Out of scope for v0.1. |
| **Steel connections** | AS 4100 Section 9 — bolted/welded connection design is not implemented; member design (flexure, shear, compression, combined actions) is. |
| **Masonry: two-way panels, in-plane shear walls, compression** | `design/as3700` covers one-way strip flexure and out-of-plane bed-joint shear only, by design — see its README section for the scope boundary. |
| **Retaining wall: global stability, shear key, compaction pressure** | `tools/cantilever_wall` now covers stability, Method A + Method B with divergence reporting, and stem/heel/toe design; `tools/gravity_wall` now covers a modular block wall's sliding/overturning/bearing/interface shear. Neither has a global-stability geometry screen; `cantilever_wall` alone is missing a shear key contribution to sliding and compaction-induced pressure. |
| **Retaining wall optioneering** | The sweep engine (`austruct.study`) is domain-agnostic and could sweep either wall tool's geometry the same way it sweeps an RC section today; no worked example does yet. |
| **Plots and DXF** | Component 6 also covers drawings. The report template has a figures section waiting. |
| **Multi-layer designations** | The grammar covers one layer per face; more raises rather than silently truncating. |
| **Job intake / scope-of-work tooling** | Considered and deliberately deferred — see the roadmap discussion for why. |

---

## Extending it

**A new section shape** — build it from bands (`from_bands`). Every integral in
the flexure solver works on any banded shape.

**A new design check** — add a module under `design/as3600/`, put constants in
`constants.py`, return a `CalcResult`, register `Provenance` at import with its
`ASETComponent`. Then run `python scripts/generate_catalogue.py` — the new
module's `description`/`envelope_summary` become its `CATALOGUE.md` row for
free; `tests/unit/test_catalogue.py` fails the build if this step is
skipped.

**A new standard** — add a `Standard` to `core/basis.py`, create
`design/<standard>/` with its own `constants.py`. Reuse `rc_common`; if you find
yourself copying from another code package, the shared part belongs in
`rc_common` instead.

**A new renderer** — implement `Renderer` in `report/renderers/`. Do not reorder
the sections.

**New reference data** — add a JSON file under `materials/data/` with `source`,
`status`, `checked_by`, `units` and a `_comment` block, and register it in
`_data.all_data_files()`.

### Likely next directions, and what would help

The patterns above are for extending what's already here. This table is the
other direction — real gaps (mostly already named in "Not built yet" above),
and whether the right move is to hand-roll it in this package's own style or
reach for something that already exists. Cross-checked against
StructuralPython's `pfse_starterkit` — Connor Ferster's own curated
dependency list for a Python structural-engineering practice, the same
Ferster whose ASET framework this package is built around — which is mostly
a confirmation of calls already made here (`scipy` for `austruct.study`,
`handcalcs` as a report-renderer candidate) plus a few gaps it's worth being
explicit about.

Same dependency posture as everywhere else in this README: nothing here
becomes a core dependency (`pyproject.toml`'s own comment explains why —
every one is a wheelhouse/`.exe` vendoring cost). Each row below is either an
optional extra a specific tool opts into, or a standalone cross-check run
outside the package entirely, never something `design/`, `analysis/` or
`sections/` import unconditionally.

| Direction | Where it plugs in | Reach for | Why |
|---|---|---|---|
| **Arbitrary (non-banded) section geometry** | `sections/` currently does rectangular/banded shapes only | [`sectionproperties`](https://sectionproperties.readthedocs.io/) | Mesh-based — handles composite and irregular shapes, and gets warping/torsion constants right for genuinely non-simple cross-sections in a way the band-integral method here doesn't attempt. |
| **RC capacity cross-check, moment-curvature, interaction diagrams** | `design/as3600`, `design/as5100_5` | [`concreteproperties`](https://concreteproperties.readthedocs.io/) (built on `sectionproperties`) | Not a replacement for `design/as3600/flexure.py` — a SECOND, independently-implemented method to run the same section through. Two unrelated implementations agreeing is real evidence; one implementation agreeing with itself is not. |
| **3D frame/truss analysis** | `analysis/frame.py` is 2D (3 DOF/node) only | [`PyNiteFEA`](https://pynite.readthedocs.io/) | Only worth pulling in if a genuine 3D case shows up (a grillage, a tower) — don't reach for it to solve a problem `analysis/frame.py` already covers in-plane. |
| **Steel connections** (AS 4100 Section 9) | `design/as4100/` has member design, not connections | Hand-roll, same as the rest of `design/as4100` | Bolt-group (elastic or ICR method) and weld-group geometry is squarely AS 4100-specific arithmetic — no general-purpose library does an Australian Standard's connection checks for you. |
| **Drawings / DXF output** | Component 6 — `report/` has no drawing output yet | [`ezdxf`](https://ezdxf.readthedocs.io/) | The standard pure-Python DXF read/write library. Slots in as a new `Renderer` alongside the markdown/HTML ones — same `report/renderers/` extension point, not a new subsystem. |
| **Global stability screen** (slip circle) | `tools/cantilever_wall`, `tools/gravity_wall` both flag this as unbuilt | Hand-roll — Bishop's simplified method of slices | A bounded, well-defined geotechnical algorithm, not a generic numerical problem — no obvious off-the-shelf Python library fits it any better than `tools/`'s existing hand-rolled pressure/stability mechanics do. |
| **Retaining wall optioneering example** | `austruct.study` already sweeps any check — no wall example uses it yet | Nothing new — wire it up | `run_sweep`/`minimize_scheme` don't know what a wall is any more than they know what an RC section is; this is a missing example, not a missing capability. |
| **Excel round-trip for schedules** | `design_documentation/schedule.py` is CSV-only, deliberately (git-diffable, opens anywhere — see its README section) | [`openpyxl`](https://openpyxl.readthedocs.io/) as an import/export BRIDGE | CSV should stay canonical; an `openpyxl`-based reader/writer for offices that hand around real `.xlsx` files is additive, not a replacement for the diffable format. |
| **Job intake / scope-of-work tooling** | Considered and explicitly deferred (see "Not built yet") | [`papermodels`](https://github.com/connorferster/papermodels) (Ferster's own PDF-drawing extractor), if this scope ever reopens | Named here for the record, not proposed — the earlier decision not to build this stands. |

`forallpeople` (a units library, also in `pfse_starterkit`) is deliberately
NOT on this list — `core/units.py` already documents why a live unit object
was rejected in favour of a plain string convention; that reasoning doesn't
change just because another curated list includes one.

---

## Governance

- **Versioning** — each module carries its own semantic version in its
  `Provenance`, independent of the package version.
- **Module register** — `REGISTRY.summary()` and `REGISTRY.coverage()` are
  generated from the modules themselves, so they cannot drift from reality.
  `CATALOGUE.md` is the same register, rendered as a browsable per-domain
  reference instead of a quarterly-review printout — see
  `scripts/generate_catalogue.py`.
- **Data register** — `_data.data_verification_report()` does the same for the
  reference tables. A table can be wrong while the code reading it is perfect.
- **Deprecation** — `VerificationStatus.SUPERSEDED` marks a module retained only
  to reproduce previously issued outputs.
- **Quarterly review** — those four reports are the input.
