"""Unit tests for the project record (ASET component 2) and the reference-data
files (ASET component 1).

The reference-data tests are deliberately about the FILES, not the values.
Whether f'c = 40 gives Ec = 32800 is a question for an engineer with the
standard open; whether the loader reads the file, caches it, and reports its
verification status is a question for a test.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from austruct.loads import ActionType
from austruct.materials import _data, concrete, reinforcement
from austruct.materials.bar_catalogue import DEFORMED_DIAMETERS
from austruct.project import (
    ExposureClassification,
    Occupancy,
    Project,
    StructureType,
)

# ---------------------------------------------------------------------------
# Reference data files
# ---------------------------------------------------------------------------


def test_every_data_file_loads_and_declares_its_source():
    for filename in _data.all_data_files():
        data = _data.load(filename)
        assert data.get("source"), f"{filename} has no source"
        assert data.get("status"), f"{filename} has no status"
        assert "units" in data, f"{filename} does not declare its units"


def test_data_files_are_cached():
    _data.reload()
    first = _data.load("concrete_grades.json")
    second = _data.load("concrete_grades.json")
    assert first is second, "static tables should be read once"


def test_reload_drops_the_cache():
    first = _data.load("bar_sizes.json")
    _data.reload()
    assert _data.load("bar_sizes.json") is not first


def test_missing_data_file_raises_a_useful_error():
    with pytest.raises(FileNotFoundError, match="package-data"):
        _data.load("not_a_real_file.json")


def test_data_verification_report_names_every_file():
    report = _data.data_verification_report()
    for filename in _data.all_data_files():
        assert filename in report
    assert "not verified" in report


def test_data_files_currently_declare_themselves_unverified():
    """If this fails somebody has marked a table VERIFIED. Check that the rows
    were actually confirmed against the standard and that a checker is named."""
    for filename in _data.all_data_files():
        status, checker, checked_on = _data.verification_status(filename)
        if status == "VERIFIED":
            assert checker, f"{filename} claims VERIFIED with no checked_by"
            assert checked_on, f"{filename} claims VERIFIED with no checked_on"


def test_data_drives_the_python_api():
    """The tables come from the files, not from literals in the modules."""
    grades = _data.load("concrete_grades.json")["grades"]
    row = next(g for g in grades if g["fc"] == 40)
    assert concrete(40).Ec == pytest.approx(row["Ec"])
    assert concrete(40).fcmi == pytest.approx(row["fcmi"])

    sizes = _data.load("bar_sizes.json")["deformed_diameters"]
    assert DEFORMED_DIAMETERS == tuple(sizes)

    steel = _data.load("reinforcement_grades.json")["grades"]
    d500n = next(g for g in steel if g["name"] == "D500N")
    assert reinforcement("D500N").fsy == pytest.approx(d500n["fsy"])


def test_data_files_carry_an_explanatory_comment_block():
    """The _comment block is what makes the file reviewable by a non-programmer,
    so it is part of the contract, not decoration."""
    for filename in _data.all_data_files():
        raw = _data.load(filename)
        assert "_comment" in raw, f"{filename} has no explanatory comment block"
        assert json.dumps(raw)  # serialisable


# ---------------------------------------------------------------------------
# Project record
# ---------------------------------------------------------------------------


@pytest.fixture
def project():
    return Project(
        job_number="24-1234",
        job_name="Riverside Apartments",
        client="Acme Developments",
        site_address="12 River Rd",
        jurisdiction="NSW",
        structure_type=StructureType.BUILDING,
        occupancy=Occupancy.RESIDENTIAL,
        exposure=ExposureClassification.B1,
        design_life_years=50,
        importance_level=2,
        engineer="A. Morrison",
        started_on=date(2026, 1, 15),
    )


def test_occupancy_converts_to_combination_factors(project):
    psi_c, psi_s, psi_l = project.combination_factors()
    assert 0.0 <= psi_c <= 1.0
    assert 0.0 <= psi_s <= 1.0
    assert 0.0 <= psi_l <= 1.0


def test_different_occupancies_give_different_factors():
    storage = Project(occupancy=Occupancy.STORAGE).combination_factors()
    residential = Project(occupancy=Occupancy.RESIDENTIAL).combination_factors()
    assert storage != residential
    assert storage[2] > residential[2], "storage has a higher long-term factor"


def test_explicit_psi_overrides_the_occupancy_lookup():
    p = Project(occupancy=Occupancy.RESIDENTIAL, psi_c=0.9)
    assert p.combination_factors()[0] == pytest.approx(0.9)


def test_project_derives_its_combination_set(project):
    combos = project.load_combinations()
    names = {c.name for c in combos}
    assert "ULS2" in names and "SLS2" in names

    uls_only = project.load_combinations(sls=False)
    assert all(c.name.startswith("ULS") for c in uls_only)


def test_psi_factors_actually_reach_the_combinations():
    storage = Project(occupancy=Occupancy.STORAGE)
    residential = Project(occupancy=Occupancy.RESIDENTIAL)
    s_uls3 = next(c for c in storage.load_combinations(sls=False) if c.name == "ULS3")
    r_uls3 = next(c for c in residential.load_combinations(sls=False) if c.name == "ULS3")
    assert s_uls3.factor_for(ActionType.Q) > r_uls3.factor_for(ActionType.Q)


def test_bridge_project_fails_closed():
    """A bridge silently getting building combinations is exactly the error the
    project record exists to prevent."""
    bridge = Project(job_number="B-1", structure_type=StructureType.BRIDGE)
    with pytest.raises(NotImplementedError, match="AS 5100.2"):
        bridge.load_combinations()


def test_json_round_trip(tmp_path, project):
    path = tmp_path / "project.json"
    project.save(path)
    back = Project.load(path)
    assert back.to_dict() == project.to_dict()
    assert back.occupancy is Occupancy.RESIDENTIAL
    assert back.exposure is ExposureClassification.B1
    assert back.started_on == date(2026, 1, 15)


def test_saved_record_shows_the_derived_values(tmp_path, project):
    """A reader must be able to see which psi factors a job was designed to
    without rerunning the code."""
    path = tmp_path / "project.json"
    project.save(path)
    data = json.loads(path.read_text())
    assert "_derived" in data
    assert data["_derived"]["psi_source"].startswith("occupancy:")


def test_unknown_fields_survive_a_read_modify_write(tmp_path, project):
    path = tmp_path / "project.json"
    project.save(path)
    data = json.loads(path.read_text())
    data["future_field"] = "keep me"
    path.write_text(json.dumps(data))

    back = Project.load(path)
    assert back.metadata["future_field"] == "keep me"


def test_unstated_values_are_none_not_defaults():
    """A report should be able to say 'not stated' rather than print a number
    nobody chose."""
    p = Project()
    assert p.design_life_years is None
    assert p.importance_level is None
    assert p.exposure is None
    assert "not stated" in "\n".join(p.describe())


def test_signature_block_comes_from_the_project(project):
    block = project.signature_block(element="Beam B1", revision="A")
    assert block.job_number == "24-1234"
    assert block.job_name == "Riverside Apartments"
    assert block.element == "Beam B1"
    assert block.designed_by == "A. Morrison"


def test_describe_flags_an_unchecked_project(project):
    assert "NOT CHECKED" in "\n".join(project.describe())
    project.checker = "B. Engineer"
    assert "NOT CHECKED" not in "\n".join(project.describe())


# ---------------------------------------------------------------------------
# ASET component coverage -- the register reports on the framework itself
# ---------------------------------------------------------------------------


def test_every_aset_component_has_at_least_one_module():
    """The whole point of tagging modules with their component: the register
    can say which parts of the framework are actually built."""
    import austruct  # noqa: F401 -- import registers the modules
    from austruct.core.provenance import ASETComponent
    from austruct.core.registry import REGISTRY

    for component in ASETComponent:
        assert REGISTRY.by_component(component), (
            f"ASET component {component.value} "
            f"({component.name}) has no module registered against it"
        )


def test_coverage_report_lists_all_six_components():
    import austruct  # noqa: F401
    from austruct.core.registry import REGISTRY

    report = REGISTRY.coverage()
    for name in (
        "Reference data",
        "Project data",
        "Fast demand calculation",
        "Design documentation",
        "Design verification",
        "Reporting and documentation",
    ):
        assert name in report
