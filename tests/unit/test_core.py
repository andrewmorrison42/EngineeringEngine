"""Unit tests for the L0 contract layer.

These are the tests that protect the contract itself. If the contract changes,
these break first -- which is the intent, because every downstream module
depends on its shape.
"""

from __future__ import annotations

from datetime import date

import pytest

from austruct.core import (
    AS3600_2018,
    REGISTRY,
    CalcResult,
    Check,
    ClauseRef,
    Envelope,
    GoldenVector,
    ModuleType,
    OutsideEnvelope,
    Provenance,
    UnverifiedConstant,
    Value,
    VerificationStatus,
    strict_mode,
)
from austruct.core.units import U_MOMENT, U_STRESS, kN, kN_per_m, kNm, m

# ---------------------------------------------------------------------------
# Units convention
# ---------------------------------------------------------------------------


def test_kn_per_m_equals_n_per_mm():
    """The convenience noted in units.py: 1 kN/m == 1 N/mm exactly."""
    assert kN_per_m == 1.0
    assert 25.0 * kN_per_m == 25.0


def test_unit_conversions():
    assert 8.0 * m == 8000.0
    assert 100.0 * kN == 100_000.0
    assert 200.0 * kNm == 200e6


# ---------------------------------------------------------------------------
# ClauseRef and Basis
# ---------------------------------------------------------------------------


def test_clause_ref_formats_and_resolves():
    ref = ClauseRef(AS3600_2018, "8.1.3", note="Rectangular stress block")
    assert "AS 3600:2018" in str(ref)
    assert "Cl 8.1.3" in str(ref)
    assert ref.citation == "AS 3600:2018 Cl 8.1.3"
    assert ref.library_key == "as3600-2018/cl/8.1.3"


def test_clause_ref_for_a_table():
    ref = ClauseRef(AS3600_2018, table="3.1.2", note="Concrete properties")
    assert "Table 3.1.2" in str(ref)
    assert ref.library_key == "as3600-2018/table/3.1.2"


# ---------------------------------------------------------------------------
# Envelope -- fail closed
# ---------------------------------------------------------------------------


def test_envelope_within_and_breaches():
    env = Envelope("test")
    env.add("f'c", 32.0, lower=20.0, upper=100.0, unit=U_STRESS)
    assert env.within
    assert not env.breaches

    env.add("f'c high", 150.0, lower=20.0, upper=100.0, unit=U_STRESS)
    assert not env.within
    assert len(env.breaches) == 1


def test_envelope_require_raises_with_detail():
    env = Envelope("test")
    env.add("f'c", 150.0, lower=20.0, upper=100.0, unit=U_STRESS)
    with pytest.raises(OutsideEnvelope) as exc:
        env.require()
    assert "f'c" in str(exc.value)
    assert exc.value.envelope is env


def test_nan_is_treated_as_outside():
    env = Envelope("test")
    env.add("x", float("nan"), lower=0.0, upper=1.0)
    assert not env.within


def test_envelope_extend_carries_restrictions_upward():
    inner = Envelope("inner")
    inner.add("y", 5.0, upper=1.0)
    inner.note("inner restriction")

    outer = Envelope("outer")
    outer.add("x", 0.5, upper=1.0)
    assert outer.within

    outer.extend(inner)
    assert not outer.within, "a caller must inherit the callee's restrictions"
    assert "inner restriction" in outer.notes


# ---------------------------------------------------------------------------
# Check -- utilisation orientation
# ---------------------------------------------------------------------------


def test_capacity_check_utilisation():
    c = Check(label="M* <= phiMuo", actual=80.0, limit=100.0, operator="<=")
    assert c.passed
    assert c.utilisation == pytest.approx(0.8)


def test_minimum_check_utilisation_is_inverted():
    """A '>=' check must still read utilisation > 1.0 when it FAILS."""
    passing = Check(label="Ast >= Ast_min", actual=1000.0, limit=800.0, operator=">=")
    assert passing.passed
    assert passing.utilisation == pytest.approx(0.8)

    failing = Check(label="Ast >= Ast_min", actual=600.0, limit=800.0, operator=">=")
    assert not failing.passed
    assert failing.utilisation > 1.0


def test_invalid_operator_raises():
    with pytest.raises(ValueError):
        Check(label="bad", actual=1.0, limit=1.0, operator="<")


# ---------------------------------------------------------------------------
# Value display units
# ---------------------------------------------------------------------------


def test_value_display_converts_without_changing_storage():
    v = Value(200e6, U_MOMENT, "M*", "Design moment", "kN.m", kNm)
    magnitude, unit = v.display
    assert magnitude == pytest.approx(200.0)
    assert unit == "kN.m"
    assert v.value == 200e6, "storage must stay in base units"
    assert float(v) == 200e6


# ---------------------------------------------------------------------------
# CalcResult
# ---------------------------------------------------------------------------


@pytest.fixture
def provenance():
    return Provenance(module="austruct.test", version="0.1.0", author="tester")


def test_calc_result_passed_requires_envelope_and_checks(provenance):
    result = CalcResult(name="test", provenance=provenance)
    result.envelope.add("x", 0.5, upper=1.0)
    result.add_check(Check(label="ok", actual=1.0, limit=2.0))
    assert result.passed

    result.add_check(Check(label="bad", actual=3.0, limit=2.0))
    assert not result.passed


def test_out_of_envelope_result_never_reads_as_pass(provenance):
    """A favourable number computed outside the validity range is not a pass."""
    result = CalcResult(name="test", provenance=provenance)
    result.envelope.add("f'c", 150.0, upper=100.0)
    result.add_check(Check(label="ok", actual=1.0, limit=100.0))
    assert not result.passed


def test_critical_check_is_the_highest_utilisation(provenance):
    result = CalcResult(name="test", provenance=provenance)
    result.add_check(Check(label="low", actual=1.0, limit=10.0))
    result.add_check(Check(label="high", actual=9.0, limit=10.0))
    assert result.critical_check.label == "high"
    assert result.utilisation == pytest.approx(0.9)


def test_calc_result_serialises(provenance):
    result = CalcResult(name="test", provenance=provenance)
    result.add_input("b", Value(300.0, "mm", "b", "width"))
    result.add_output("M", Value(200e6, U_MOMENT, "M_uo", "capacity", "kN.m", kNm))
    result.basis.add(ClauseRef(AS3600_2018, "8.1.3"))
    result.envelope.add("f'c", 32.0, lower=20.0, upper=100.0)

    d = result.to_dict()
    assert d["outputs"]["M"]["value"] == 200e6
    assert d["basis"][0]["library_key"] == "as3600-2018/cl/8.1.3"
    assert d["envelope"]["within"] is True
    assert d["provenance"]["issuable"] is False
    assert result.to_json()


def test_get_raises_on_unknown_key(provenance):
    result = CalcResult(name="test", provenance=provenance)
    with pytest.raises(KeyError):
        result.get("nope")


# ---------------------------------------------------------------------------
# Provenance and the verification spine
# ---------------------------------------------------------------------------


def test_unverified_is_the_default():
    p = Provenance(module="m", version="0.1.0", author="a")
    assert p.status is VerificationStatus.UNVERIFIED
    assert not p.issuable


def test_verified_without_a_checker_is_rejected():
    """Phase 3 rule: no catalog entry without a NAMED checker."""
    with pytest.raises(ValueError, match="checker"):
        Provenance(
            module="m",
            version="0.1.0",
            author="a",
            status=VerificationStatus.VERIFIED,
        )


def test_verified_with_a_checker_is_issuable():
    p = Provenance(
        module="m",
        version="0.1.0",
        author="a",
        status=VerificationStatus.VERIFIED,
        checker="B. Engineer",
        checked_on=date(2026, 1, 1),
        vectors=(
            GoldenVector(
                case_id="C1",
                source="Warner Example 3.4",
                checked_by="B. Engineer",
                checked_on=date(2026, 1, 1),
            ),
        ),
    )
    assert p.issuable
    assert "B. Engineer" in "\n".join(p.describe())


def test_strict_mode_blocks_unverified_modules():
    """The deployment posture for issued calculations."""
    strict_mode(True)
    try:
        with pytest.raises(UnverifiedConstant, match="strict mode"):
            Provenance(module="m", version="0.1.0", author="a")
    finally:
        strict_mode(False)

    # Outside strict mode the same construction is allowed.
    assert Provenance(module="m", version="0.1.0", author="a")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_has_recorded_every_imported_module():
    import austruct  # noqa: F401 -- import triggers registration

    assert REGISTRY.entries, "modules must self-register at import"
    assert any("as3600" in key for key in REGISTRY.entries)
    assert any("as5100_5" in key for key in REGISTRY.entries)
    assert REGISTRY.summary()


def test_registry_reports_everything_as_unverified():
    """If this fails, a module claims to be cleared for issue -- check why."""
    import austruct  # noqa: F401

    assert len(REGISTRY.unverified()) == len(REGISTRY.entries)


def test_registry_filters_by_type():
    import austruct  # noqa: F401

    tabulated = REGISTRY.by_type(ModuleType.A_TABULATED)
    per_job = REGISTRY.by_type(ModuleType.B_PER_JOB)
    assert tabulated, "materials modules are Type A"
    assert per_job, "design modules are Type B"
