# austruct capability catalogue

GENERATED FILE -- do not hand-edit. Every row below is read directly out of `austruct.core.registry.REGISTRY` at the point every module in the package has been imported once, so this list is exactly what is actually built, not what someone remembered to write down. Regenerate with:

```bash
python scripts/generate_catalogue.py
```

For HOW to use a domain (worked examples, code samples, the reasoning behind a design choice), see the matching README section -- this file answers "what exists", the README answers "how do I use it".

**Status** is a verification claim, not a completeness one: `UNVERIFIED` means written but not checked against an external source, and its output is not for issue -- see the README's "What is verified, and what is not" section before trusting a number from any row below.

Not every importable module is a row here -- only ones that produce their own `CalcResult` register with `REGISTRY`. An orchestration layer that calls other registered modules rather than doing its own standard-referenced arithmetic (e.g. `tools.cantilever_wall.member_design`, which builds a section and calls the already-listed `design.as3600.flexure`/`shear`; or `austruct.study`, the domain-agnostic sweep engine, which never touches a standard at all) is deliberately absent -- look for what it CALLS in the table below instead.

**56 modules registered, 56 not yet cleared for issue.**

## Contents

- [analysis.envelope](#analysisenvelope) (1)
- [analysis.frame](#analysisframe) (1)
- [analysis.moving](#analysismoving) (1)
- [analysis.redistribution](#analysisredistribution) (1)
- [analysis.results](#analysisresults) (1)
- [design.as3600](#designas3600) (4)
- [design.as3700](#designas3700) (2)
- [design.as4100](#designas4100) (7)
- [design.as5100_5](#designas5100_5) (4)
- [design.rc_common](#designrc_common) (1)
- [design_documentation.designation](#design_documentationdesignation) (1)
- [design_documentation.schedule](#design_documentationschedule) (1)
- [loads.as5100_2](#loadsas5100_2) (1)
- [loads.combinations](#loadscombinations) (1)
- [loads.dispersal](#loadsdispersal) (1)
- [loads.patterns](#loadspatterns) (1)
- [materials.bar_catalogue](#materialsbar_catalogue) (1)
- [materials.concrete](#materialsconcrete) (1)
- [materials.masonry](#materialsmasonry) (1)
- [materials.reinforcement](#materialsreinforcement) (1)
- [materials.steel](#materialssteel) (1)
- [project.project](#projectproject) (1)
- [report.plots](#reportplots) (1)
- [report.template](#reporttemplate) (1)
- [sections.bar_layout](#sectionsbar_layout) (1)
- [sections.properties](#sectionsproperties) (1)
- [sections.steel_catalogue](#sectionssteel_catalogue) (1)
- [sections.steel_profile](#sectionssteel_profile) (1)
- [structures.box_culvert](#structuresbox_culvert) (1)
- [structures.crown_culvert](#structurescrown_culvert) (1)
- [structures.perimeter](#structuresperimeter) (1)
- [structures.profile](#structuresprofile) (1)
- [tools.cantilever_wall](#toolscantilever_wall) (5)
- [tools.gravity_wall](#toolsgravity_wall) (5)
- [Framework infrastructure](#framework-infrastructure) (1)

---

## analysis.envelope

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `analysis.envelope` | Enveloping of beam analysis results across load combinations | UNVERIFIED | 0 | Linear elastic superposition; one member at a time |

## analysis.frame

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `analysis.frame` | Plane frame direct stiffness solver, 3 DOF per node | UNVERIFIED | 0 | Linear elastic, small displacement, prismatic members; no P-Delta, no shear deformation, rigid joints |

## analysis.moving

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `analysis.moving` | Moving load trains, position sweeps and influence lines | UNVERIFIED | 0 | Linear elastic; load pattern rigid; position swept at a finite step |

## analysis.redistribution

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `analysis.redistribution` | Moment redistribution on continuous members, preserving equilibrium | UNVERIFIED | 0 | Ductile sections capable of forming plastic hinges; linear correction within each span; percentage supplied by the caller |

## analysis.results

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `analysis.results` | Beam analysis result container and diagram interrogation | UNVERIFIED | 0 | Linear elastic, small deflection, Euler-Bernoulli |

## design.as3600

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `design.as3600.detailing` | Development length, laps, curtailment and bar fit to AS 3600:2018 Section 13 | UNVERIFIED | 0 | Deformed bars, straight anchorage, no hooks or cogs; one row of bars per layer; normal-weight concrete |
| `design.as3600.flexure` | Ultimate flexural capacity of RC sections to AS 3600:2018 Section 8.1 | UNVERIFIED | 0 | 20 <= f'c <= 100 MPa; non-prestressed; pure bending, no axial force; compression at the top of the section as supplied |
| `design.as3600.serviceability` | Deflection and crack control of RC members to AS 3600:2018 Sections 8.5, 8.6 | UNVERIFIED | 0 | Non-prestressed; prismatic member; one I_ef for the span; deemed-to-comply crack control by bar diameter and spacing |
| `design.as3600.shear` | Shear capacity of RC beams to AS 3600:2018 Section 8.2 | UNVERIFIED | 0 | 20 <= f'c <= 100 MPa; non-prestressed; vertical fitments only; no axial force; no torsion |

## design.as3700

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `design.as3700.flexure` | Flexural capacity of masonry walls to AS 3700:2018, one-way strip only | UNVERIFIED | 0 | One-way spanning strip -- not the two-way panel/yield-line method |
| `design.as3700.shear` | Out-of-plane one-way shear capacity of masonry walls, AS 3700:2018 | UNVERIFIED | 0 | Bed-joint friction/bond shear, masonry contribution only -- see module docstring |

## design.as4100

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `design.as4100.classification` | Section slenderness and effective section modulus to AS 4100 Section 5.2 | UNVERIFIED | 0 | I-sections, channels and plates; uniform compression assumed in each element |
| `design.as4100.combined` | Combined bending and axial force to AS 4100 Section 8 | UNVERIFIED | 0 | Uniaxial bending with axial compression; doubly symmetric sections; no biaxial bending, no tension |
| `design.as4100.compression` | Compression member capacity to AS 4100 Section 6 | UNVERIFIED | 0 | Concentrically loaded prismatic members; flexural buckling only; no torsional or flexural-torsional buckling |
| `design.as4100.flexure` | Section moment capacity of steel members to AS 4100 Section 5.2 | UNVERIFIED | 0 | Section capacity only -- lateral-torsional buckling is NOT included. Valid for a fully restrained segment; see lateral_torsional.py otherwise |
| `design.as4100.lateral_torsional` | Lateral-torsional buckling and member moment capacity to AS 4100 Section 5.6 | UNVERIFIED | 0 | Doubly symmetric I-sections bent about the major axis; elastic buckling; no axial force; thin-walled J understates torsional stiffness |
| `design.as4100.restraints` | Restraint classification and effective length to AS 4100 Cl 5.6.3 | UNVERIFIED | 0 | k_t supplied by the caller except for fully restrained segments |
| `design.as4100.shear` | Shear capacity and shear-moment interaction to AS 4100 Sections 5.11, 5.12 | UNVERIFIED | 0 | Unstiffened webs; shear carried by the web alone; no transverse or longitudinal stiffeners |

## design.as5100_5

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `design.as5100_5.fatigue` | Fatigue of reinforcement and concrete to AS 5100.5:2017 Section 12 | UNVERIFIED | 0 | Non-prestressed; constant-amplitude stress range; cracked section throughout the cycle; no cumulative damage summation |
| `design.as5100_5.flexure` | Ultimate flexural capacity of RC sections to AS 5100.5:2017 | UNVERIFIED | 0 | 25 <= f'c <= 100 MPa; non-prestressed; pure bending; compression at the top of the section as supplied |
| `design.as5100_5.serviceability` | Serviceability of bridge RC members to AS 5100.5:2017 Sections 8.5, 8.6 | UNVERIFIED | 0 | Non-prestressed; prismatic; crack control by steel stress limit, not by calculated crack width |
| `design.as5100_5.shear` | Shear capacity of RC beams to AS 5100.5:2017 (AS 3600:2009 family) | UNVERIFIED | 0 | 25 <= f'c <= 100 MPa; non-prestressed; vertical fitments only; no axial force; no torsion |

## design.rc_common

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `design.rc_common.serviceability` | Cracked-section serviceability mechanics shared by both standards | UNVERIFIED | 0 | Linear elastic materials, plane sections, no tension stiffening in I_cr |

## design_documentation.designation

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `design_documentation.designation` | Plain-text design designation grammar for RC beams, with round-trip parsing | UNVERIFIED | 0 | Rectangular and tee RC beams; one top and one bottom bar layer |

## design_documentation.schedule

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `design_documentation.schedule` | CSV member schedules in long and matrix form, round-tripping to RCSections | UNVERIFIED | 0 | Members expressible in the designation grammar |

## loads.as5100_2

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `loads.as5100_2.traffic` | AS 5100.2:2017 road and rail traffic load models, as a named catalogue | UNVERIFIED | 0 | W80, A160, M1600, S1600, HLP320, HLP400, 300LA. UNVERIFIED geometry; HLP entries are placeholders. |

## loads.combinations

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `loads.combinations` | Load cases and jurisdiction-specific load combinations | UNVERIFIED | 0 | AS/NZS 1170.0 basic combinations; AS 5100.2 skeleton only |

## loads.dispersal

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `loads.dispersal` | Dispersal of wheel loads and earth pressure through fill onto a buried structure | UNVERIFIED | 0 | Single-layer fill; linear dispersal at a stated slope; no soil-structure interaction; no arching |

## loads.patterns

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `loads.patterns` | Pattern loading arrangements for continuous members | UNVERIFIED | 0 | Imposed actions patterned span by span; permanent actions never patterned |

## materials.bar_catalogue

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `materials.bar_catalogue` | Standard reinforcing bar sizes, areas and arrangement queries | UNVERIFIED | 0 | Standard AS/NZS 4671 bar diameters only |

## materials.concrete

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `materials.concrete` | Concrete grade properties to AS 3600 Table 3.1.2 and Section 3.1 | UNVERIFIED | 0 | 20 <= f'c <= 100 MPa (AS 3600); 25 <= f'c <= 100 MPa (AS 5100.5) |

## materials.masonry

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `materials.masonry` | Masonry unit sizes and derived masonry strengths to AS 3700:2018 Section 3 | UNVERIFIED | 0 | Simplified derivation, not the full Table 3.1 -- see module docstring |

## materials.reinforcement

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `materials.reinforcement` | Reinforcing steel grades and ductility classes to AS/NZS 4671 | UNVERIFIED | 0 | Grades R250N, D500N, D500L as tabulated |

## materials.steel

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `materials.steel` | Structural steel grades with thickness-banded yield strength | UNVERIFIED | 0 | Hot-rolled sections and plate to AS/NZS 3679.1 and AS/NZS 3678 |

## project.project

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `project.project` | Project record: job data, site, occupancy, exposure, derived design parameters | UNVERIFIED | 0 | Australian jurisdictions; buildings to AS/NZS 1170, bridges to AS 5100 |

## report.plots

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `report.plots` | Diagram, envelope, influence line and section plots | UNVERIFIED | 0 | Presentation only -- produces no numbers |

## report.template

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `report.template` | The fixed calculation report layout, independent of any renderer | UNVERIFIED | 0 | Any CalcResult-producing module |

## sections.bar_layout

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `sections.bar_layout` | Bar spacing and fit geometry within a section width | UNVERIFIED | 0 | Bars in one horizontal row, equally spaced, symmetric about the centreline |

## sections.properties

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `sections.properties` | Transformed and cracked section properties for RC sections | UNVERIFIED | 0 | Linear elastic materials; concrete tension ignored when cracked |

## sections.steel_catalogue

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `sections.steel_catalogue` | Australian hot-rolled steel section catalogue with a self-verifying cross-check | UNVERIFIED | 0 | UB, UC and PFC; dimensions recalled, properties cross-checked against them |

## sections.steel_profile

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `sections.steel_profile` | Steel section geometry as an assembly of rectangular plates | UNVERIFIED | 0 | Rectangular plates only; thin-walled J ignoring fillets; I_w computed per shape type |

## structures.box_culvert

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `structures.box_culvert` | Box culvert analysed as a closed plane frame on soil springs | UNVERIFIED | 0 | Single-cell rectangular box; prismatic members; no haunches; linear elastic soil springs under the base slab only |

## structures.crown_culvert

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `structures.crown_culvert` | Crown (arch) culvert as a plane frame, with tapered legs and a haunched crown | UNVERIFIED | 0 | Single-cell arch on two legs; circular crown; linear elastic; free-field soil stresses with no arching; no soil-structure interaction |

## structures.perimeter

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `structures.perimeter` | Directed node placement around a closed structural perimeter | UNVERIFIED | 0 | Four-sided closed perimeter; nodes placed by fraction along each side |

## structures.profile

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `structures.profile` | Straight and circular perimeter paths with variable member thickness | UNVERIFIED | 0 | Plane geometry; circular arcs only; thickness varies along the path |

## tools.cantilever_wall

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `tools.cantilever_wall.checks.bearing` | Bearing pressure: Meyerhof effective width, Terzaghi/Meyerhof capacity | UNVERIFIED | 0 | e/B < 0.5 required -- B' must stay positive |
| `tools.cantilever_wall.checks.eccentricity` | Eccentricity of the base resultant, AS 4678:2002 | UNVERIFIED | 0 | V* > 0 required -- a net uplift makes eccentricity undefined |
| `tools.cantilever_wall.checks.sliding` | Sliding resistance: friction, adhesion, passive -- AS 4678:2002 | UNVERIFIED | 0 | Homogeneous soil, Rankine passive (no wall friction credit) |
| `tools.cantilever_wall.pressure.culmann` | Culmann trial wedge search -- Method B | UNVERIFIED | 0 | Frictionless virtual plane, no cohesion credit, drained only |
| `tools.cantilever_wall.pressure.rankine` | Rankine active earth pressure on a virtual plane through the heel | UNVERIFIED | 0 | Homogeneous soil, vertical virtual plane, backslope <= phi |

## tools.gravity_wall

| Module | Description | Status | Vectors | Scope / envelope |
|---|---|---|---|---|
| `tools.gravity_wall.checks.bearing` | Bearing pressure, FS-based -- NCMA-style allowable stress design | UNVERIFIED | 0 | e/B < 0.5 required -- B' must stay positive |
| `tools.gravity_wall.checks.interface_shear` | Course-to-course interface shear, FS-based -- internal stability | UNVERIFIED | 0 | Linear Mohr-Coulomb interface law -- see the module note |
| `tools.gravity_wall.checks.overturning` | Overturning about the toe, FS-based -- NCMA-style allowable stress design | UNVERIFIED | 0 | M_overturning > 0 required |
| `tools.gravity_wall.checks.sliding` | Sliding resistance, FS-based -- NCMA-style allowable stress design | UNVERIFIED | 0 | No passive resistance credited |
| `tools.gravity_wall.pressure` | Coulomb active earth pressure, general wall batter and wall friction | UNVERIFIED | 0 | Homogeneous, cohesionless soil, backslope <= phi |

---

## Framework infrastructure

Not a calculation domain -- the cross-cutting contract (the module contract, provenance/registry itself) that lets components 1-6 exchange data. Listed separately so the table above stays "things you can calculate", not "things that exist in the repo".

| Module | Description |
|---|---|
| `core.contract` | The calculation contract every module emits |
