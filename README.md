# austruct — structural engineering toolkit

Python framework for structural design to **AS 3600:2018**, **AS 5100.5:2017**
and (later) **AS 5100.2:2017**.

Version 0.1.0. Materials, beam analysis, and flexural and shear design of
reinforced concrete sections.

---

## ⚠ Read this before using any number this produces

**No module in this package has been verified.** Every value transcribed from a
printed standard — capacity reduction factors, stress block coefficients, shear
constants — is tagged `[VECTOR]` in the source and is **UNVERIFIED**. Several
are further tagged **UNCONFIRMED**, meaning the author is not confident of the
value at all, not merely that nobody has checked it.

The mechanics are tested and correct. The *constants* need a person with the
standards open beside them.

To make that fail loudly rather than quietly:

```bash
AUSTRUCT_STRICT=1 python your_calc.py     # unverified modules raise instead of returning
```

Everything you need to check lives in exactly two files:

| File | What to check |
|---|---|
| `src/austruct/design/as3600/constants.py` | Every AS 3600:2018 value |
| `src/austruct/design/as5100_5/constants.py` | Every AS 5100.5:2017 value |

Plus `src/austruct/materials/concrete.py` for Table 3.1.2. Nothing else in the
package hard-codes a code value — that centralisation is deliberate, so
verification is one sitting rather than an archaeology exercise.

Current status:

```
9 module(s), 9 not cleared for issue.
```

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest                     # 132 tests
```

Only runtime dependency is `numpy`. Plotting and reporting extras are optional
so the core installs cleanly into a wheelhouse and freezes into a `.exe`.

---

## Layer architecture

Modules may import from layers **above** them in this list, never below. That
one rule is what keeps the toolkit composable.

```
L0  core        contract, basis, envelope, provenance, units, registry
L1  materials   concrete, reinforcement, bar catalogue
L2  sections    geometry primitives, RC sections, section properties
L3  analysis    beam models, stiffness solver, closed-form benchmarks
L3b loads       load combinations, AS 5100.2 traffic loads      [not built]
L4  design      rc_common/ + as3600/ + as5100_5/
L5  report      the audit artifact
```

```
src/austruct/
├── core/                    L0 — imports nothing else
│   ├── contract.py            CalcResult: inputs/basis/envelope/outputs/provenance
│   ├── basis.py               ClauseRef → resolves into the TS Reference Library
│   ├── envelope.py            validity limits, explicit in/out flag, fail-closed
│   ├── provenance.py          version, author, checker, golden-vector status
│   ├── units.py               the N/mm/MPa convention
│   └── registry.py            module register for the quarterly review
├── materials/               L1 — the reference-data layer
├── sections/                L2 — banded geometry, RC sections, cracked properties
├── analysis/                L3 — loads, beam model, stiffness solver, closed forms
├── design/                  L4
│   ├── rc_common/             shared mechanics — NO clause numbers, NO phi
│   ├── as3600/                AS 3600:2018
│   └── as5100_5/              AS 5100.5:2017
└── report/                  L5 — fixed layout, interchangeable renderers
```

### The two decisions worth knowing about

**1. `rc_common` holds the mechanics; the code packages hold only what differs.**

Both standards use the same rectangular stress block and the same
plane-sections assumption, so both call one strain-compatibility solver. What
differs is φ, the ductility limit, and the clause references.

The payoff is visible in `examples/03_as3600_vs_as5100.py`: the same section
returns an *identical* nominal `M_uo` under both standards, and differs only in
φ. Duplicating the solver into both packages would guarantee they drift.

**But shear is genuinely two different models, and they share nothing.**
AS 3600:2018 uses a modified-compression-field-theory formulation (`k_v`, `d_v`,
`θ_v`). AS 5100.5:2017 predates it and uses the AS 3600:2009 family
(`β₁β₂β₃`, `f_cv`, `d_o`, θ_v interpolated on web demand). Treating AS 5100.5 as
"AS 3600 with different numbers" is the most likely way to get a bridge wrong
with this toolkit, so the packages are kept apart.

**2. Analysis is a general stiffness solver; closed-form solutions are its verification.**

`analysis/solver.py` is a direct-stiffness Euler-Bernoulli solver: any number of
spans, any support arrangement, any load type. `analysis/closed_form.py` holds
the textbook formulae as an *independent implementation* sharing no code, used
as the benchmark.

Within the solver there's a further split. Reactions and deflections come from
the finite element solve; **shear and moment diagrams are then built by
statics** from those reactions. Statics gives exact values at any position for
any load type with no dependence on mesh density, and it is checkable by hand —
which matters when the numbers go on a drawing.

---

## The module contract

Every public calculation returns a `CalcResult`, never a bare float. A float has
no units, no clause reference and no envelope, and every one of those is needed
by someone downstream.

```python
result.inputs         # echoed verbatim, units declared
result.basis          # ClauseRefs in application order
result.envelope       # validity limits + explicit in/out flag
result.outputs        # results with units
result.checks         # pass/fail against criteria
result.provenance     # version, author, checker, vector status, timestamp
result.intermediates  # the working a reviewer follows
```

```python
result.passed         # every check AND the envelope
result.utilisation    # governing utilisation
result.to_dict()      # plain data — consumable without importing austruct
```

### Envelope vs Check — the distinction that matters

An **envelope limit** bounds the range of application of the calculation. Breach
one and the answer is not conservative or unconservative, it is *unknown* — so
the module raises `OutsideEnvelope` and refuses to produce a number.

A **check** is pass/fail against a code criterion. Breach one and you have a
legitimate result that reads FAIL.

A beam that is overstressed is a valid calculation with a failing result. A beam
of 150 MPa concrete is not a calculation this toolkit can do at all.

---

## Units

**N, mm, MPa.** Plain floats, no units library.

| Quantity | Unit | | Quantity | Unit |
|---|---|---|---|---|
| Length | mm | | Moment | N·mm |
| Force | N | | Distributed load | N/mm |
| Stress / modulus | MPa | | Angle | radian |

`1 kN/m = 1 N/mm` exactly, so a 25 kN/m UDL is the float `25.0`.

Density is the one deliberate exception — it stays in kg/m³ because that is what
AS 3600 Cl 3.1.2 uses, and it is confined to `materials/concrete.py`.

The mitigation for having no runtime dimensional analysis is not "be careful":
every reported quantity is wrapped in a `Value` that declares its unit, every
function carries a `[UNITS]` callout, and the golden vectors would fail loudly
on a factor-of-1000 error.

---

## Sign convention

Stated once, applied everywhere:

| | |
|---|---|
| Downward load | **positive** |
| Downward deflection | **positive** |
| Sagging bending moment | **positive** (tension in the bottom fibre) |
| Shear force | positive where the resultant to the **left** acts upward |
| Applied concentrated moment | positive where it **increases** the sagging moment to its right |
| Support reaction | reported positive **upward** |

The solver works internally in an upward-positive frame and converts **once**,
in `solver.py`. There is no second conversion anywhere.

For hogging bending, **invert the section** (`inverted_tee`) rather than
negating anything — the design modules assume compression at the top throughout.

---

## Callout convention

A fixed vocabulary, used consistently across every module. Nothing else.

| Tag | Meaning |
|---|---|
| `[BASIS]` | The clause this line implements |
| `[VECTOR]` | A value transcribed from a standard — needs verification |
| `[ENVELOPE]` | A validity limit being enforced |
| `[ASSUMPTION]` | A modelling choice the reader must know about |
| `[UNITS]` | Unit convention at this point |
| `[CHECK]` | A pass/fail criterion or a guard |
| `[TODO]` | Known incomplete |

Every function that touches a standard carries `Basis` and `Envelope` docstring
sections:

```python
def moment_capacity(section):
    """Ultimate flexural capacity of a reinforced concrete section.

    Basis
    -----
    AS 3600:2018 Cl 8.1.2, Cl 8.1.3, Cl 8.1.5, Table 2.2.2

    Envelope
    --------
    20 MPa <= f'c <= 100 MPa. Non-prestressed. Pure bending.
    """
    # [BASIS]     AS 3600:2018 Cl 8.1.3 — rectangular stress block
    # [UNITS]     N, mm, MPa throughout
    # [ASSUMPTION] plane sections remain plane
    # [CHECK]     k_uo <= 0.36 for ductility
```

---

## Quick start

```python
from austruct.analysis import UDL, PointLoad, simply_supported
from austruct.core.units import kN, kNm, kN_per_m, m
from austruct.design import as3600
from austruct.materials import concrete
from austruct.sections import rc_beam

section = rc_beam(350, 650, concrete(40), cover=40,
                  n_bars=4, diameter=28, fitment_spacing=200)

beam = simply_supported(
    8 * m,
    loads=(UDL(magnitude=46.5 * kN_per_m), PointLoad(position=4 * m, magnitude=90 * kN)),
    section=section,
)
results = beam.solve()

flexure = as3600.check_flexure(section, results.max_moment)
shear = as3600.check_shear(section, V_star=max(results.shear_at_d_from_support(section.d)))

print(f"M* = {results.max_moment / kNm:.1f} kN.m,  "
      f"phi.Muo = {flexure.get('phiMuo') / kNm:.1f} kN.m,  "
      f"utilisation {flexure.utilisation:.3f}")
```

### Examples

```bash
python examples/01_beam_analysis.py        # support arrangements and load types
python examples/02_beam_design_report.py   # end-to-end design + audit report
python examples/03_as3600_vs_as5100.py     # the two standards side by side
```

---

## The report artifact

The durable standard is the **layout**, not the rendering library. Fixed order:

> inputs echoed → basis & envelope statement → step-by-step working with units →
> pass/fail against criteria → embedded plots/geometry → signature block

Any module producing that document is compliant, whether via handcalcs, Jinja or
a Word merge. Adding a renderer means implementing `Renderer`; it does not mean
touching the layout.

`handcalcs` is deliberately **not** the report engine — it renders the
arithmetic, which is one of six sections. Making it the engine would make the
layout hostage to its rendering choices and leave tabulated and geometry modules
with no compliant artifact at all. It slots in as a renderer for the working
section instead.

A report tracks two things independently:

```python
report.passed      # every design check passed
report.issuable    # every module used is verified for issue
```

A calculation can pass every check and still not be issuable.

---

## The verification spine

> **No module enters the catalog without golden vectors and a named checker.**

- `tests/golden/vectors/*.yaml` — benchmark cases, each naming its source,
  its checker and the date
- `tests/golden/test_vectors.py` — one runner over all of them

Adding a vector means adding a case to a YAML file. It does not mean writing a
test.

```yaml
- id: PROP-UDL-01
  description: Propped cantilever, full UDL. Singly indeterminate.
  source: "Standard closed-form: R_fixed=5wL/8, M_fixed=-wL^2/8"
  checked_by: PENDING          # ← replace with a real name
  checked_on: 2026-01-01
  tolerance: 1.0e-6
```

Every vector currently reads `checked_by: PENDING`, and the test suite prints
the outstanding list on every run.

`Provenance` enforces the rule in code: claiming `VERIFIED` without a named
checker raises.

---

## What is verified, and what is not

**Verified by test (132 passing):**

- Stiffness solver against closed-form solutions for simply supported,
  cantilever, propped cantilever, encastre and continuous beams — reactions,
  moments and deflections agreeing to ~1e-9 relative
- Sign conventions, including applied moments and hogging at cantilever roots
- Superposition, equilibrium, and that a point load on a mesh node is not
  double-counted
- Flexural strain-compatibility solve against a hand calculation (exact)
- Cracked section neutral axis and `I_cr` against hand calculation (exact)
- Tee sections reducing to the equivalent rectangle when the NA is in the flange
- Contract compliance across every public entry point
- Fail-closed behaviour: unstable beams, out-of-envelope inputs, bad models

**Not verified — needs a person with the standards:**

- Every numeric constant in both `constants.py` files
- AS 3600 Table 3.1.2 values
- Whether AS 3600 Cl 8.2.4.2's `k_v` expression uses `d_o` or `d_v`
  (see `KV_NO_STEEL_DEPTH_IS_DO`)
- AS 5100.5's φ for flexure, and its `k_uo` limit (0.36 or 0.40)
- Amendment states — every `Standard.amendments` tuple is empty

---

## Not built yet

| | Why it matters |
|---|---|
| **AS 5100.2 traffic loads** | M1600, S1600, A160, W80, HLP, DLA. Scaffolded at `loads/as5100_2/`. |
| **Load combinations** | AS/NZS 1170.0 and AS 5100.2 ULS/SLS. Currently applied by hand in the examples. |
| **Serviceability** | Deflection, crack control. `cracked_properties` and `cracking_moment` are in place as the foundation. |
| **Durability** | Cover and exposure classification. |
| **Prestress** | Stubbed in `materials/prestress.py`. |
| **Torsion, columns, footings** | Out of scope for v0.1. |
| **Plots** | BMD/SFD/deflection. The report template has a figures section waiting. |

---

## Extending it

**A new section shape** — build it from bands (`from_bands`) or add a
constructor to `primitives.py`. Every integral in the flexure solver works on
any banded shape, so nothing in the design layer changes.

**A new design check to an existing standard** — add a module under
`design/as3600/`, put any new constants in `constants.py`, return a
`CalcResult`, register `Provenance` at import.

**A new standard** — add a `Standard` to `core/basis.py`, create
`design/<standard>/` with its own `constants.py`. Reuse `rc_common` for
mechanics; if you find yourself copying from another code package, the shared
part belongs in `rc_common` instead.

**A new renderer** — implement `Renderer` in `report/renderers/`. Do not reorder
the sections.

---

## Governance

Per the roadmap's governance minimums:

- **Naming and versioning** — each module carries its own semantic version in
  its `Provenance`, independent of the package version. Bump the minor when
  behaviour changes in a way that could change an issued number.
- **Module register** — `austruct.core.registry.REGISTRY.summary()` generates
  the register from the modules themselves, so it cannot drift from reality.
  Records type (A/B/C/D), owner, checker, envelope and vector count.
- **Deprecation** — `VerificationStatus.SUPERSEDED` marks a module retained only
  to reproduce previously issued outputs.
- **Quarterly review** — `REGISTRY.summary()` is the input.

Roadmap Phase 0 classification is recorded per module as `ModuleType`:
A tabulated / B per-job / C geometry / D extraction.
