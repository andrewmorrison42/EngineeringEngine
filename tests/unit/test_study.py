"""Unit tests for ``austruct.study`` -- the sweep/optioneering layer.

The point of this package is that it is domain-agnostic, so these tests
deliberately exercise it against TWO different design domains (RC flexure,
masonry flexure) with the same engine, never importing a domain module from
inside ``study`` itself -- only from the tests, exactly as a real caller
would.
"""

from __future__ import annotations

import pytest

from austruct.core.units import kNm
from austruct.design.as3600 import check_flexure as check_rc_flexure
from austruct.design.as3700 import check_flexure as check_masonry_flexure
from austruct.materials import concrete
from austruct.materials.masonry import MortarClass, masonry_properties
from austruct.sections import rc_beam
from austruct.sections.masonry_section import masonry_wall
from austruct.study import optimise as optimise_module
from austruct.study.optimise import SCIPY_AVAILABLE, minimize_scheme
from austruct.study.scheme import Scheme, load_schemes_csv, save_schemes_csv
from austruct.study.sweep import run_sweep

# ---------------------------------------------------------------------------
# Scheme / CSV round trip
# ---------------------------------------------------------------------------


def test_csv_round_trip_preserves_overrides_and_notes(tmp_path):
    schemes = [
        Scheme("A", {"D": 600, "diameter": 24}),
        Scheme("B", {"D": 700}, notes="deeper and leaner"),
    ]
    path = tmp_path / "schemes.csv"
    save_schemes_csv(schemes, path)
    reloaded = load_schemes_csv(path)

    assert [s.name for s in reloaded] == ["A", "B"]
    assert reloaded[0].overrides == {"D": 600, "diameter": 24}
    assert reloaded[1].overrides == {"D": 700}  # B never had 'diameter'
    assert reloaded[1].notes == "deeper and leaner"


def test_a_blank_cell_means_no_override_not_empty_string(tmp_path):
    path = tmp_path / "schemes.csv"
    path.write_text("scheme,b,D,notes\nA,300,,\n")
    schemes = load_schemes_csv(path)
    assert "D" not in schemes[0].overrides
    assert schemes[0].overrides == {"b": 300}


def test_cell_values_are_coerced_int_float_bool():
    import tempfile
    from pathlib import Path

    text = "scheme,n,area,grouted\nA,4,201.06,true\n"
    p = Path(tempfile.mktemp(suffix=".csv"))
    p.write_text(text)
    schemes = load_schemes_csv(p)
    p.unlink()
    overrides = schemes[0].overrides
    assert overrides["n"] == 4 and isinstance(overrides["n"], int)
    assert overrides["area"] == pytest.approx(201.06) and isinstance(overrides["area"], float)
    assert overrides["grouted"] is True


def test_missing_scheme_column_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("name,D\nA,600\n")
    with pytest.raises(ValueError, match="scheme"):
        load_schemes_csv(path)


def test_duplicate_scheme_names_are_rejected(tmp_path):
    path = tmp_path / "dupe.csv"
    path.write_text("scheme,D\nA,600\nA,700\n")
    with pytest.raises(ValueError, match="more than once"):
        load_schemes_csv(path)


def test_merged_applies_overrides_on_top_of_base():
    scheme = Scheme("A", {"D": 600})
    assert scheme.merged({"b": 300, "D": 400}) == {"b": 300, "D": 600}


# ---------------------------------------------------------------------------
# run_sweep -- RC flexure
# ---------------------------------------------------------------------------


def _rc_build(b, D, diameter=24):
    return rc_beam(b, D, concrete(32), cover=40, n_bars=4, diameter=diameter, fitment_spacing=200)


def _rc_check(section):
    return check_rc_flexure(section, 300 * kNm)


def _rc_cost(section):
    return section.geometry.area * 1e-6 * 180.0


def test_sweep_ranks_passing_schemes_cheapest_first():
    schemes = [
        Scheme("A", {"D": 600}),
        Scheme("B", {"D": 700}),
        Scheme("C", {"D": 300}),  # too shallow -- fails
    ]
    result = run_sweep(schemes, _rc_build, _rc_check, base={"b": 300}, cost=_rc_cost)

    assert len(result.passing) == 2
    assert len(result.failing) == 1
    assert result.governing is not None
    assert result.governing.scheme.name == "A"  # shallower -> cheaper, both pass
    assert [o.scheme.name for o in result.ranked[:2]] == ["A", "B"]


def test_sweep_without_a_cost_function_ranks_by_utilisation():
    schemes = [Scheme("A", {"D": 600}), Scheme("B", {"D": 900})]
    result = run_sweep(schemes, _rc_build, _rc_check, base={"b": 300})
    # No cost given -- deeper section has more spare capacity, lower utilisation.
    assert result.governing.scheme.name == "B"


def test_sweep_records_a_failing_scheme_without_stopping_the_sweep():
    schemes = [Scheme("tiny", {"D": 250}), Scheme("ok", {"D": 700})]
    result = run_sweep(schemes, _rc_build, _rc_check, base={"b": 300})
    assert result.governing.scheme.name == "ok"
    assert len(result.outcomes) == 2
    failing = result.failing[0]
    assert not failing.passed
    assert failing.error is None


def test_sweep_records_a_build_error_without_crashing():
    def build_that_can_fail(b, D):
        if D <= 0:
            raise ValueError("D must be positive")
        return _rc_build(b, D)

    schemes = [Scheme("bad", {"D": -100}), Scheme("ok", {"D": 700})]
    result = run_sweep(schemes, build_that_can_fail, _rc_check, base={"b": 300})

    assert len(result.errored) == 1
    bad = result.errored[0]
    assert bad.passed is None
    assert bad.utilisation is None
    assert "positive" in bad.error
    assert result.governing.scheme.name == "ok"


def test_governing_is_none_when_nothing_passes():
    schemes = [Scheme("tiny1", {"D": 250}), Scheme("tiny2", {"D": 280})]
    result = run_sweep(schemes, _rc_build, _rc_check, base={"b": 300})
    assert result.governing is None


def test_to_rows_carries_overrides_and_status():
    schemes = [Scheme("A", {"D": 600})]
    result = run_sweep(schemes, _rc_build, _rc_check, base={"b": 300}, cost=_rc_cost)
    rows = result.to_rows()
    assert rows[0]["scheme"] == "A"
    assert rows[0]["D"] == 600
    assert rows[0]["passed"] is True
    assert rows[0]["cost"] is not None


def test_describe_reports_counts_and_the_governing_scheme():
    schemes = [Scheme("A", {"D": 600}), Scheme("B", {"D": 250})]
    result = run_sweep(schemes, _rc_build, _rc_check, base={"b": 300})
    text = "\n".join(result.describe())
    assert "2 scheme(s): 1 passed, 1 failed" in text
    assert "Governing: A" in text


# ---------------------------------------------------------------------------
# run_sweep -- masonry, proving the engine is genuinely domain-agnostic
# ---------------------------------------------------------------------------


def test_sweep_works_identically_against_a_different_design_domain():
    grade = masonry_properties(15.0, MortarClass.M3, grouted=True)

    def build(thickness):
        return masonry_wall(thickness, grade)

    def check(wall):
        return check_masonry_flexure(wall, 1.5 * kNm, direction="vertical", fd=0.1)

    schemes = [Scheme("90", {"thickness": 90}), Scheme("190", {"thickness": 190})]
    result = run_sweep(schemes, build, check)
    assert result.governing.scheme.name == "190"  # only the thicker wall passes
    assert not result.outcomes[0].passed


# ---------------------------------------------------------------------------
# minimize_scheme -- the scipy.optimize integration
# ---------------------------------------------------------------------------


def test_scipy_unavailable_raises_a_clear_import_error(monkeypatch):
    monkeypatch.setattr(optimise_module, "_IMPORT_ERROR", ImportError("simulated"))
    with pytest.raises(ImportError, match="pip install"):
        minimize_scheme({"D": (400.0, 900.0)}, _rc_build, _rc_check, _rc_cost, base={"b": 300})


@pytest.mark.skipif(not SCIPY_AVAILABLE, reason="scipy not installed")
def test_minimize_scheme_converges_to_a_utilisation_bound_optimum():
    result = minimize_scheme(
        variables={"b": (200.0, 600.0), "D": (400.0, 1000.0)},
        build=_rc_build,
        check=_rc_check,
        cost=_rc_cost,
    )
    assert result.success
    # Cheaper to narrow the section than deepen it here, so the optimiser
    # should push width to its lower bound and use depth to just meet M*.
    assert result.x["b"] == pytest.approx(200.0, abs=1.0)
    assert result.result.utilisation <= 1.01  # essentially binding, not slack


@pytest.mark.skipif(not SCIPY_AVAILABLE, reason="scipy not installed")
def test_minimize_scheme_result_is_a_real_reverified_check():
    """The returned .result must come from an ACTUAL check(build(...)) call
    at the final x, not a number scipy computed and this module trusted."""
    result = minimize_scheme(
        variables={"b": (200.0, 600.0), "D": (400.0, 1000.0)},
        build=_rc_build,
        check=_rc_check,
        cost=_rc_cost,
    )
    independent = _rc_check(_rc_build(b=result.x["b"], D=result.x["D"]))
    assert result.result.utilisation == pytest.approx(independent.utilisation)
