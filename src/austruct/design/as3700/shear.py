"""Shear design of masonry walls to AS 3700:2018 -- out-of-plane, one-way.

Scope: which shear check this is
----------------------------------
AS 3700 has two materially different shear mechanisms. This module
implements the one that pairs with :mod:`.flexure`'s one-way bending strip:
shear at the SUPPORT of a wall spanning as a one-way strip under
out-of-plane load, resisted by bed-joint friction/bond -- the same
mechanics AS 3700 Cl 7.5.4 uses for sliding shear, applied here across the
full strip thickness rather than along the wall's in-plane length.

It is **NOT** AS 3700's in-plane shear-wall (racking) provision -- the check
that resists lateral load applied IN the plane of the wall (wind or seismic
racking of a shear wall), which acts over the wall's LENGTH rather than its
thickness and, for reinforced masonry, is usually resisted by horizontal
bond-beam steel rather than the vertical bars this package's
:class:`~austruct.sections.masonry_section.MasonryWallSection` models. That
check is materially different and is NOT implemented here -- see the README
for what a future in-plane module would need.

Reinforcement is not credited
-------------------------------
:func:`check_shear` returns the same capacity whether or not the section has
vertical reinforcement. Those bars resist FLEXURE (see ``flexure.py``); they
do not cross a horizontal shear-sliding plane the way transverse
reinforcement does in a reinforced concrete beam, so crediting them here
would overstate the capacity. If the applied shear exceeds the unreinforced
capacity, horizontal bond-beam reinforcement is the usual remedy -- verify
it by hand, or extend this module, rather than reading a false PASS from a
steel contribution this function does not compute.

[UNITS] mm, N, MPa, N.mm.

[VECTOR] UNVERIFIED, and more heavily simplified than ``as3600``/``as4100``
-- see ``constants.py``.
"""

from __future__ import annotations

from ...core.basis import Basis
from ...core.contract import CalcResult, Check, Value
from ...core.envelope import Envelope
from ...core.provenance import ASETComponent, ModuleType, Provenance, VerificationStatus
from ...core.registry import REGISTRY
from ...core.units import U_FORCE, U_LENGTH, U_NONE, U_STRESS, kN
from ...sections.masonry_section import MasonryWallSection
from . import constants as C

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.B_PER_JOB,
        component=ASETComponent.VERIFICATION,
        status=VerificationStatus.UNVERIFIED,
    ),
    description="Out-of-plane one-way shear capacity of masonry walls, AS 3700:2018",
    envelope_summary="Bed-joint friction/bond shear, masonry contribution only -- see module docstring",
)


def shear_capacity(section: MasonryWallSection, fd: float = 0.0) -> CalcResult:
    """Out-of-plane shear capacity, masonry (bed-joint friction/bond) only.

    Basis
    -----
    AS 3700:2018 Cl 7.5.4, applied across the strip: ``v = f'ms + kv.fd``,
    capped at :data:`~.constants.SHEAR_STRESS_CAP`; ``Vo = v . A``, with
    ``A = design_width . thickness``.

    Parameters
    ----------
    section:
        Reinforced or unreinforced -- reinforcement does not change this
        result. See the module docstring for why.
    fd:
        Design compressive stress on the section (MPa), e.g. self-weight
        above. Increases sliding-friction shear resistance.
    """
    env = Envelope(name="Out-of-plane shear")
    env.add("fd", fd, lower=0.0, unit="MPa", basis=C.CLAUSE_SHEAR)
    env.note("Bed-joint friction/bond mechanism -- not the in-plane shear-wall check.")
    env.require()

    basis = Basis()
    basis.add(C.CLAUSE_SHEAR)

    f_ms = section.masonry.f_ms
    v_raw = f_ms + C.KV_FRICTION * fd
    v = min(v_raw, C.SHEAR_STRESS_CAP)
    A = section.area
    # [ASSUMPTION] phi is selected by whether the SECTION is reinforced, even
    # though the shear MECHANISM computed here is masonry-only either way --
    # AS 3700 Table 4.4 ties phi to category of construction, which typically
    # differs between reinforced and unreinforced work. Reinforcement does
    # not change v or Vo above; it only changes which phi row applies.
    phi = C.PHI_REINFORCED_SHEAR if section.reinforced else C.PHI_UNREINFORCED_SHEAR
    Vo = v * A

    result = CalcResult(
        name="Out-of-plane shear capacity -- AS 3700:2018 Cl 7.5.4",
        provenance=PROVENANCE, basis=basis, envelope=env,
    )
    result.add_input("t", Value(section.thickness, U_LENGTH, "t", "Wall thickness"))
    result.add_input("f_ms", Value(f_ms, U_STRESS, "f'ms", "Characteristic shear bond strength"))
    result.add_input("fd", Value(fd, U_STRESS, "fd", "Design compressive stress"))
    result.add_intermediate("v_raw", Value(v_raw, U_STRESS, "v", "f'ms + kv.fd, uncapped"))
    result.add_intermediate("A", Value(A, "mm^2", "A", "Strip cross-sectional area"))
    result.add_output("phi", Value(phi, U_NONE, "phi", "Capacity reduction factor"))
    result.add_output("Vo", Value(Vo, U_FORCE, "V_o", "Nominal shear capacity", "kN/m", kN))
    result.add_output(
        "phiVo", Value(phi * Vo, U_FORCE, "phi.V_o", "Design shear capacity", "kN/m", kN)
    )
    if v_raw > C.SHEAR_STRESS_CAP:
        result.note(
            f"Shear stress capped at {C.SHEAR_STRESS_CAP:g} MPa "
            f"(uncapped value was {v_raw:.2f} MPa)."
        )
    if section.reinforced:
        result.note(
            "Section has vertical reinforcement, but it is NOT credited here "
            "-- see the module docstring on why this capacity is the "
            "masonry-only (bed-joint friction/bond) mechanism."
        )
    return result


def check_shear(
    section: MasonryWallSection,
    V_star: float,  # noqa: N803
    fd: float = 0.0,
) -> CalcResult:
    """Check a wall's out-of-plane shear capacity against a design shear.

    Parameters
    ----------
    V_star:
        Design shear force per metre of wall length (N/m), magnitude.
    fd:
        Design compressive stress (MPa).
    """
    V_star = abs(V_star)
    result = shear_capacity(section, fd)
    result.name = "Shear strength check -- AS 3700:2018 Cl 7.5.4"
    result.add_input("Vstar", Value(V_star, U_FORCE, "V*", "Design shear force", "kN/m", kN))
    result.add_check(
        Check(
            label="Shear strength, V* <= phi.V_o",
            actual=V_star, limit=result.get("phiVo"), operator="<=", unit=U_FORCE,
            basis=C.CLAUSE_SHEAR, display_factor=kN, display_unit="kN/m",
        )
    )
    return result
