"""The verification spine -- one runner over every golden vector file.

Roadmap Phase 3:

    No module enters the catalog without golden vectors and a named checker.

    - Every module ships with benchmark cases checked against the legacy
      spreadsheet, a published worked example, or a hand calc.
    - Each case names the engineer who verified it and the date.
    - Vectors run on every change. A failed vector pulls the module from the
      catalog automatically.

This file implements the first three. The fourth -- automatic removal from the
catalog -- is a CI concern: wire this test suite into the pipeline and make a
failure block the merge.

Adding a vector means adding a case to a YAML file in ``vectors/``. It does not
mean writing a test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from austruct.analysis import (
    UDL,
    AppliedMoment,
    PartialUDL,
    PointLoad,
    VaryingUDL,
    cantilever,
    continuous,
    fixed_fixed,
    propped_cantilever,
    simply_supported,
)
from austruct.core.units import kN, kN_per_m, kNm, m

VECTOR_DIR = Path(__file__).parent / "vectors"

PLACEHOLDER_CHECKER = "PENDING"


def _load_all_cases() -> list[tuple[str, str, dict]]:
    """Every case in every vector file, as ``(file, case_id, case)``."""
    out = []
    for path in sorted(VECTOR_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        for case in data.get("cases", []):
            out.append((path.name, case["id"], case))
    return out


ALL_CASES = _load_all_cases()


def _build_loads(specs: list[dict]) -> tuple:
    """Turn the YAML load specifications into load objects."""
    loads = []
    for spec in specs:
        kind = spec["type"]
        if kind == "UDL":
            loads.append(UDL(magnitude=spec["magnitude_kN_per_m"] * kN_per_m))
        elif kind == "PointLoad":
            loads.append(
                PointLoad(
                    position=spec["position_m"] * m,
                    magnitude=spec["magnitude_kN"] * kN,
                )
            )
        elif kind == "PartialUDL":
            loads.append(
                PartialUDL(
                    start=spec["start_m"] * m,
                    end=spec["end_m"] * m,
                    magnitude=spec["magnitude_kN_per_m"] * kN_per_m,
                )
            )
        elif kind == "VaryingUDL":
            loads.append(
                VaryingUDL(
                    start=spec["start_m"] * m,
                    end=spec["end_m"] * m,
                    w_start=spec["w_start_kN_per_m"] * kN_per_m,
                    w_end=spec["w_end_kN_per_m"] * kN_per_m,
                )
            )
        elif kind == "AppliedMoment":
            loads.append(
                AppliedMoment(
                    position=spec["position_m"] * m,
                    magnitude=spec["magnitude_kNm"] * kNm,
                )
            )
        else:  # pragma: no cover -- guards against a typo in a vector file
            raise ValueError(f"Unknown load type in vector: {kind!r}")
    return tuple(loads)


def _build_beam(model: dict, loads: tuple):
    """Turn the YAML model specification into a Beam."""
    kind = model["type"]
    EI = float(model["EI"])

    if kind == "continuous":
        return continuous([s * m for s in model["spans_m"]], loads=loads, EI=EI)

    length = model["length_m"] * m
    builders = {
        "simply_supported": simply_supported,
        "cantilever": cantilever,
        "propped_cantilever": propped_cantilever,
        "fixed_fixed": fixed_fixed,
    }
    if kind not in builders:  # pragma: no cover
        raise ValueError(f"Unknown model type in vector: {kind!r}")
    return builders[kind](length, loads=loads, EI=EI)


def _actual_value(results, key: str) -> float:
    """Map a vector's expectation key onto a result quantity, in report units."""
    reactions = sorted(results.reactions, key=lambda r: r.position)
    mapping = {
        "R_left_kN": lambda: reactions[0].force / kN,
        "R_right_kN": lambda: reactions[-1].force / kN,
        "R_centre_kN": lambda: reactions[len(reactions) // 2].force / kN,
        "M_max_kNm": lambda: results.max_moment / kNm,
        "M_min_kNm": lambda: results.min_moment / kNm,
        "V_max_kN": lambda: results.max_shear / kN,
        "deflection_max_mm": lambda: results.max_deflection,
    }
    if key not in mapping:  # pragma: no cover
        raise ValueError(f"Unknown expectation key in vector: {key!r}")
    return mapping[key]()


@pytest.mark.golden
@pytest.mark.parametrize(
    "filename,case_id,case",
    ALL_CASES,
    ids=[f"{f}::{cid}" for f, cid, _ in ALL_CASES],
)
def test_golden_vector(filename: str, case_id: str, case: dict) -> None:
    """Run one benchmark case and compare against its recorded expectation."""
    loads = _build_loads(case["loads"])
    beam = _build_beam(case["model"], loads)
    results = beam.solve()

    tol = float(case.get("tolerance", 1e-6))

    for key, expected in case["expect"].items():
        actual = _actual_value(results, key)
        if abs(expected) < 1e-12:
            assert abs(actual) < 1e-6, f"{case_id}: {key} expected ~0, got {actual}"
        else:
            rel = abs(actual - expected) / abs(expected)
            assert rel <= tol, (
                f"{case_id}: {key} = {actual!r}, expected {expected!r} "
                f"(relative error {rel:.3e} > tolerance {tol:.3e})\n"
                f"Source: {case['source']}"
            )


def test_every_vector_names_a_checker_and_date() -> None:
    """Structural requirement on the vectors themselves.

    A vector without a named checker is not a verification, it is an
    assertion. This test does not fail on the PENDING placeholder -- that
    would block all development -- but it does fail on a MISSING field, so a
    vector cannot be added without at least acknowledging the requirement.
    """
    for filename, case_id, case in ALL_CASES:
        assert case.get("source"), f"{filename}::{case_id} has no source"
        assert case.get("checked_by"), f"{filename}::{case_id} has no checked_by"
        assert case.get("checked_on"), f"{filename}::{case_id} has no checked_on"


def test_report_unverified_vectors() -> None:
    """Report which vectors are still unverified. Never fails.

    Prints the outstanding verification work so it appears in every test run
    rather than only when somebody goes looking for it.
    """
    pending = [
        f"{filename}::{case_id}"
        for filename, case_id, case in ALL_CASES
        if case.get("checked_by") == PLACEHOLDER_CHECKER
    ]
    if pending:
        print(
            f"\n{len(pending)} of {len(ALL_CASES)} golden vectors are UNVERIFIED "
            f"(checked_by = {PLACEHOLDER_CHECKER}):"
        )
        for name in pending:
            print(f"  - {name}")
        print(
            "\nThese modules are NOT cleared for issue. Verify each expectation "
            "against its cited source and record the engineer's name and date."
        )
