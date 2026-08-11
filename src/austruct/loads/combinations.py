"""Load cases and load combinations.

ASET component 2 -- project data
--------------------------------
Ferster places load combinations under *Project data*: "information generated
from client-supplied information, such as climatic data, environmental loads,
dead loads, load combinations (jurisdiction specific)". They are jurisdiction
specific and derived from what the client tells you, not from the member.

The split from analysis is deliberate. A :class:`LoadCase` says *what the loads
are and which action they represent*; a :class:`LoadCombination` says *how the
jurisdiction requires them to be added up*. Neither knows anything about a beam.
:mod:`austruct.analysis.envelope` then applies them to a member.

[UNITS] Loads in N and N/mm as elsewhere. Factors dimensionless.

[VECTOR] Every combination and every psi factor here is UNVERIFIED. Load
         combinations are jurisdiction-specific and change between editions;
         check every one against the printed standard before use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..analysis.loading import Load
from ..core.basis import AS1170_0_2002, AS5100_2_2017, ClauseRef
from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.A_TABULATED,
        component=ASETComponent.PROJECT_DATA,
    ),
    description="Load cases and jurisdiction-specific load combinations",
    envelope_summary="AS/NZS 1170.0 basic combinations; AS 5100.2 skeleton only",
)


class ActionType(str, Enum):
    """The kind of action a load case represents.

    A load combination is a set of factors keyed on these, so the action type
    is what connects "this 25 kN/m is floor live load" to "the code wants it
    multiplied by 1.5 in this combination".
    """

    G = "G"
    """Permanent action -- self weight, superimposed dead."""

    Q = "Q"
    """Imposed action -- occupancy live load."""

    Wu = "Wu"
    """Wind action, ultimate."""

    Ws = "Ws"
    """Wind action, serviceability."""

    Su = "Su"
    """Snow action, ultimate."""

    Eu = "Eu"
    """Earthquake action, ultimate."""

    Fl = "Fl"
    """Liquid pressure."""

    Traffic = "Traffic"
    """Road traffic actions to AS 5100.2 -- M1600, S1600, A160, W80, HLP.

    [TODO] The AS 5100.2 traffic load models are not built. This action type
           exists so a bridge combination can be written now and the loads
           dropped in later without the combination changing.
    """

    Braking = "Braking"
    """Longitudinal braking and traction forces to AS 5100.2. [TODO] Not built."""

    Thermal = "Thermal"
    """Temperature effects."""

    Shrinkage = "Shrinkage"
    """Shrinkage and creep effects."""


PERMANENT_ACTIONS: frozenset[ActionType] = frozenset(
    {ActionType.G, ActionType.Shrinkage}
)
"""Actions that are always present on a member if they are present at all.

Used by :meth:`LoadCombination.involves` to decide whether a combination has
anything meaningful to act on. Everything not in this set is a variable action
whose absence makes the combinations built around it irrelevant.
"""


class LimitState(str, Enum):
    """Which limit state a combination belongs to."""

    ULS = "ULS"
    SLS = "SLS"


@dataclass(frozen=True)
class LoadCase:
    """A named group of loads representing one action.

    Parameters
    ----------
    name:
        Identifier, e.g. ``"G_dead"``. Appears in the envelope output as part
        of the governing-combination record, so make it readable.
    action:
        Which action this case represents. Drives which combination factor applies.
    loads:
        The loads themselves, unfactored.

    Examples
    --------
    >>> LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),))
    """

    name: str
    action: ActionType
    loads: tuple[Load, ...] = ()

    def scaled(self, factor: float) -> tuple[Load, ...]:
        """Every load in this case multiplied by ``factor``.

        A factor of zero returns an empty tuple rather than a tuple of zero
        loads -- there is no point meshing around a load that does nothing.
        """
        if factor == 0.0:
            return ()
        return tuple(load.scale(factor) for load in self.loads)

    @property
    def total(self) -> float:
        """Total unfactored downward force in this case (N)."""
        return sum(load.total() for load in self.loads)


@dataclass(frozen=True)
class LoadCombination:
    """A jurisdiction's rule for adding factored actions together.

    Parameters
    ----------
    name:
        Short identifier, e.g. ``"ULS2"``. This is what gets recorded as the
        governing combination in an envelope, so keep it short and stable.
    factors:
        Factor per action type. An action not present is not included.
    limit_state:
        ULS or SLS. Envelopes are normally taken separately for each.
    basis:
        The clause the combination comes from.
    description:
        Human-readable form, e.g. ``"1.2G + 1.5Q"``.
    """

    name: str
    factors: dict[ActionType, float] = field(default_factory=dict)
    limit_state: LimitState = LimitState.ULS
    basis: ClauseRef | None = None
    description: str = ""

    def factor_for(self, action: ActionType) -> float:
        """Factor applied to ``action`` in this combination. Zero if absent."""
        return self.factors.get(action, 0.0)

    def apply(self, cases: tuple[LoadCase, ...]) -> tuple[Load, ...]:
        """Factored loads for this combination, across every supplied case.

        Cases whose action does not appear in the combination contribute
        nothing. Several cases may share an action type -- two separate
        permanent cases, say -- and all of them are factored identically.
        """
        out: list[Load] = []
        for case in cases:
            factor = self.factor_for(case.action)
            out.extend(case.scaled(factor))
        return tuple(out)

    def involves(self, cases: tuple[LoadCase, ...]) -> bool:
        """Whether this combination has anything meaningful to act on.

        The rule, and why it is not simply "any action present":

        A combination is relevant if it factors no VARIABLE action at all
        (``1.35G`` always applies), or if at least one of the variable actions
        it factors is present among the cases.

        Testing only for "any action present" would keep ``0.9G + Wu`` on a
        member with no wind case, because it factors G. That combination exists
        solely to find load reversal under wind; with no wind it degenerates to
        ``0.9G``, which can never govern against ``1.35G``, and it would put an
        irrelevant name into the governing-combination record.

        Some noise remains by design: ``1.2G + Wu + psi_c.Q`` on a member with
        only G and Q degenerates to ``1.2G + psi_c.Q``, a strict subset of
        ``1.2G + 1.5Q``. It is kept because dropping every combination whose
        actions are not ALL present would discard ``1.2G + Wu`` on a member
        that has wind but no imposed load -- a combination that certainly does
        govern. Combinations that survive but cannot govern cost one solve and
        change no answer.

        Both conditions below must hold. A combination factoring only permanent
        actions is still irrelevant if none of those actions is present -- it
        would apply no load at all and analyse an unloaded beam.
        """
        present = {case.action for case in cases}
        factored = {action for action, factor in self.factors.items() if factor != 0.0}

        # Something to act on at all.
        if not (factored & present):
            return False

        # And, where the combination is built around variable actions, at least
        # one of those must be present.
        variable = factored - PERMANENT_ACTIONS
        if not variable:
            return True
        return bool(variable & present)

    def __str__(self) -> str:
        if self.description:
            return f"{self.name}: {self.description}"
        parts = [f"{f:g}{a.value}" for a, f in self.factors.items()]
        return f"{self.name}: {' + '.join(parts)}"


# ---------------------------------------------------------------------------
# AS/NZS 1170.0:2002 -- combinations of actions
#
# [VECTOR] EVERY combination below is UNVERIFIED. Check each against Section 4
#          of the printed standard, including which combinations apply to which
#          action types and the psi factors from Table 4.1.
# ---------------------------------------------------------------------------

CLAUSE_ULS = ClauseRef(AS1170_0_2002, "4.2.2", note="Combinations for ultimate limit states")
CLAUSE_SLS = ClauseRef(AS1170_0_2002, "4.3", note="Combinations for serviceability limit states")
CLAUSE_PSI = ClauseRef(AS1170_0_2002, table="4.1", note="Combination factors psi")

# [BASIS]  AS/NZS 1170.0 Table 4.1 -- combination factors.
# [VECTOR] UNVERIFIED. These vary with occupancy; the values below are the
#          commonly quoted ones for floors in general office/residential use
#          and MUST be replaced with the values for the actual occupancy.
PSI_C_DEFAULT = 0.4
"""psi_c -- combination factor for imposed action acting with wind/earthquake."""

PSI_S_DEFAULT = 0.7
"""psi_s -- short-term factor, serviceability."""

PSI_L_DEFAULT = 0.4
"""psi_l -- long-term factor, serviceability and long-term ULS."""


def as1170_uls(
    psi_c: float = PSI_C_DEFAULT,
    psi_l: float = PSI_L_DEFAULT,
) -> tuple[LoadCombination, ...]:
    """Ultimate limit state combinations to AS/NZS 1170.0 Cl 4.2.2.

    [VECTOR] UNVERIFIED. Check every combination and factor.
    [ASSUMPTION] Liquid pressure, thermal and shrinkage actions are not
                 included in these combinations. Add them explicitly where the
                 member is subject to them.

    Parameters
    ----------
    psi_c:
        Combination factor for imposed action acting with wind or earthquake.
    psi_l:
        Long-term factor for imposed action.

    Returns
    -------
    tuple[LoadCombination, ...]
    """
    return (
        LoadCombination(
            "ULS1", {ActionType.G: 1.35}, LimitState.ULS, CLAUSE_ULS, "1.35G"
        ),
        LoadCombination(
            "ULS2",
            {ActionType.G: 1.2, ActionType.Q: 1.5},
            LimitState.ULS,
            CLAUSE_ULS,
            "1.2G + 1.5Q",
        ),
        LoadCombination(
            "ULS3",
            {ActionType.G: 1.2, ActionType.Q: 1.5 * psi_l},
            LimitState.ULS,
            CLAUSE_ULS,
            f"1.2G + {1.5 * psi_l:g}Q (long term)",
        ),
        LoadCombination(
            "ULS4",
            {ActionType.G: 1.2, ActionType.Wu: 1.0, ActionType.Q: psi_c},
            LimitState.ULS,
            CLAUSE_ULS,
            f"1.2G + Wu + {psi_c:g}Q",
        ),
        LoadCombination(
            "ULS5",
            {ActionType.G: 0.9, ActionType.Wu: 1.0},
            LimitState.ULS,
            CLAUSE_ULS,
            "0.9G + Wu  (uplift/reversal)",
        ),
        LoadCombination(
            "ULS6",
            {ActionType.G: 1.0, ActionType.Eu: 1.0, ActionType.Q: psi_c},
            LimitState.ULS,
            CLAUSE_ULS,
            f"G + Eu + {psi_c:g}Q",
        ),
        LoadCombination(
            "ULS7",
            {ActionType.G: 1.2, ActionType.Su: 1.0, ActionType.Q: psi_c},
            LimitState.ULS,
            CLAUSE_ULS,
            f"1.2G + Su + {psi_c:g}Q",
        ),
    )


def as1170_sls(
    psi_s: float = PSI_S_DEFAULT,
    psi_l: float = PSI_L_DEFAULT,
) -> tuple[LoadCombination, ...]:
    """Serviceability limit state combinations to AS/NZS 1170.0 Cl 4.3.

    [VECTOR] UNVERIFIED.
    [ASSUMPTION] Short-term and long-term cases are given separately, since
                 deflection limits usually differ between them.
    """
    return (
        LoadCombination(
            "SLS1", {ActionType.G: 1.0}, LimitState.SLS, CLAUSE_SLS, "G"
        ),
        LoadCombination(
            "SLS2",
            {ActionType.G: 1.0, ActionType.Q: psi_s},
            LimitState.SLS,
            CLAUSE_SLS,
            f"G + {psi_s:g}Q (short term)",
        ),
        LoadCombination(
            "SLS3",
            {ActionType.G: 1.0, ActionType.Q: psi_l},
            LimitState.SLS,
            CLAUSE_SLS,
            f"G + {psi_l:g}Q (long term)",
        ),
        LoadCombination(
            "SLS4",
            {ActionType.G: 1.0, ActionType.Ws: 1.0, ActionType.Q: psi_l},
            LimitState.SLS,
            CLAUSE_SLS,
            f"G + Ws + {psi_l:g}Q",
        ),
    )


# ---------------------------------------------------------------------------
# AS 5100.2:2017 -- bridge design loads
#
# [TODO]   SKELETON ONLY. The AS 5100.2 traffic load models (M1600, S1600,
#          A160, W80, HLP) are NOT implemented, so the Traffic action type has
#          no loads to carry yet. These combinations are provided so that the
#          structure is in place, and so the gap is explicit rather than
#          silently absent.
# [VECTOR] UNVERIFIED and UNCONFIRMED. Do not use for bridge design until the
#          combinations have been checked against AS 5100.2 Section 22 and the
#          traffic load models are built.
# ---------------------------------------------------------------------------

CLAUSE_BRIDGE_ULS = ClauseRef(
    AS5100_2_2017, "22", note="Combinations of actions -- ultimate limit states"
)
CLAUSE_BRIDGE_SLS = ClauseRef(
    AS5100_2_2017, "22", note="Combinations of actions -- serviceability limit states"
)

# [VECTOR] UNVERIFIED and UNCONFIRMED. The factors below are the author's best
#          recollection and have NOT been transcribed from AS 5100.2 Section
#          22. They must be checked before any bridge calculation is issued.
#          The traffic load model geometry they act on carries the same
#          warning -- see austruct/loads/as5100_2/data/traffic_models.json.
GAMMA_G_CONCRETE_MAX = 1.2
GAMMA_G_CONCRETE_MIN = 0.85
"""Permanent effects, cast-in-place concrete. Two values because a permanent
action that RELIEVES an effect must be factored down, not up -- the minimum
governs uplift, overturning and load reversal."""

GAMMA_G_SUPERIMPOSED_MAX = 2.0
GAMMA_G_SUPERIMPOSED_MIN = 0.7
"""Superimposed dead load. A wider spread than structural dead because a
wearing surface can be resurfaced several times over a bridge's life."""

GAMMA_TRAFFIC_ULS = 1.8
"""Road traffic actions at ULS. [VECTOR] UNCONFIRMED."""

GAMMA_TRAFFIC_SLS = 1.0
GAMMA_BRAKING_ULS = 1.8


def as5100_uls(
    include_braking: bool = True,
) -> tuple[LoadCombination, ...]:
    """Ultimate limit state combinations to AS 5100.2:2017.

    Basis
    -----
    AS 5100.2:2017 Section 22.

    [VECTOR] UNVERIFIED and UNCONFIRMED -- every factor. These have not been
             transcribed from the printed standard.

    [ENVELOPE] Road traffic and permanent effects only. Does NOT include:
               wind, thermal, differential settlement, shrinkage and creep,
               earthquake, collision, construction or flood actions, nor the
               heavy load platform (HLP) cases. A bridge design needs those;
               this returns the gravity-and-traffic subset.

    Parameters
    ----------
    include_braking:
        Whether to include the braking/traction combination.

    Returns
    -------
    tuple[LoadCombination, ...]

    Notes
    -----
    The minimum permanent factors exist to catch reversal: a deck cantilever
    or an integral abutment can be governed by the case where the dead load is
    LOW and the traffic is high, which the maximum factors would never find.
    """
    combos = [
        LoadCombination(
            "B-ULS1",
            {ActionType.G: GAMMA_G_CONCRETE_MAX},
            LimitState.ULS,
            CLAUSE_BRIDGE_ULS,
            f"{GAMMA_G_CONCRETE_MAX:g}G  (permanent only)",
        ),
        LoadCombination(
            "B-ULS2",
            {
                ActionType.G: GAMMA_G_CONCRETE_MAX,
                ActionType.Traffic: GAMMA_TRAFFIC_ULS,
            },
            LimitState.ULS,
            CLAUSE_BRIDGE_ULS,
            f"{GAMMA_G_CONCRETE_MAX:g}G + {GAMMA_TRAFFIC_ULS:g}Traffic",
        ),
        LoadCombination(
            "B-ULS3",
            {
                ActionType.G: GAMMA_G_CONCRETE_MIN,
                ActionType.Traffic: GAMMA_TRAFFIC_ULS,
            },
            LimitState.ULS,
            CLAUSE_BRIDGE_ULS,
            f"{GAMMA_G_CONCRETE_MIN:g}G + {GAMMA_TRAFFIC_ULS:g}Traffic  (reversal)",
        ),
    ]
    if include_braking:
        combos.append(
            LoadCombination(
                "B-ULS4",
                {
                    ActionType.G: GAMMA_G_CONCRETE_MAX,
                    ActionType.Traffic: GAMMA_TRAFFIC_ULS,
                    ActionType.Braking: GAMMA_BRAKING_ULS,
                },
                LimitState.ULS,
                CLAUSE_BRIDGE_ULS,
                f"{GAMMA_G_CONCRETE_MAX:g}G + {GAMMA_TRAFFIC_ULS:g}Traffic "
                f"+ {GAMMA_BRAKING_ULS:g}Braking",
            )
        )
    return tuple(combos)


def as5100_sls() -> tuple[LoadCombination, ...]:
    """Serviceability combinations to AS 5100.2:2017.

    [VECTOR] UNVERIFIED and UNCONFIRMED.
    [ENVELOPE] As :func:`as5100_uls` -- gravity and traffic only.
    """
    return (
        LoadCombination(
            "B-SLS1",
            {ActionType.G: 1.0},
            LimitState.SLS,
            CLAUSE_BRIDGE_SLS,
            "G",
        ),
        LoadCombination(
            "B-SLS2",
            {ActionType.G: 1.0, ActionType.Traffic: GAMMA_TRAFFIC_SLS},
            LimitState.SLS,
            CLAUSE_BRIDGE_SLS,
            f"G + {GAMMA_TRAFFIC_SLS:g}Traffic",
        ),
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def basic_building_combinations(
    psi_c: float = PSI_C_DEFAULT,
    psi_s: float = PSI_S_DEFAULT,
    psi_l: float = PSI_L_DEFAULT,
) -> tuple[LoadCombination, ...]:
    """Every AS/NZS 1170.0 combination, ULS and SLS together.

    Convenient for a first pass; take ULS and SLS separately when you need the
    envelopes kept apart, which is usually.
    """
    return as1170_uls(psi_c, psi_l) + as1170_sls(psi_s, psi_l)


def filter_relevant(
    combinations: tuple[LoadCombination, ...], cases: tuple[LoadCase, ...]
) -> tuple[LoadCombination, ...]:
    """Drop combinations that no supplied load case contributes to.

    A member with only G and Q cases does not need the five wind and earthquake
    combinations analysed; including them puts unloaded-beam results into the
    envelope and makes the governing-combination record misleading.
    """
    return tuple(c for c in combinations if c.involves(cases))
