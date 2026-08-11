"""Tests for the notebook-facing surface: rich display, table exports, plots.

These guard the ergonomics rather than the engineering. They matter because the
failure mode is silent: a broken ``_repr_markdown_`` does not raise, it just
falls back to the dataclass repr, and the notebook quietly becomes unreadable
again.

The plotting tests are skipped when matplotlib is absent, since it is an
optional dependency and the core package must install and test without it.
"""

from __future__ import annotations

import pytest

from austruct.analysis import (
    UDL,
    LoadTrain,
    PointLoad,
    analyse_combinations,
    influence_line,
    moving_load_envelope,
    simply_supported,
)
from austruct.core.units import kN, kN_per_m, m
from austruct.design import as3600
from austruct.design_documentation import parse
from austruct.loads import ActionType, LoadCase, as1170_uls
from austruct.project import Occupancy, Project
from austruct.report import Report


@pytest.fixture
def section():
    return parse(
        "350 x 650 | C40 | COV 40 | BOT 4-N28 | TOP 2-N16 | LIG N12-2L@200", name="B1"
    )


@pytest.fixture
def beam(section):
    return simply_supported(8 * m, section=section, name="B1")


@pytest.fixture
def results(beam):
    return beam.with_loads(
        (UDL(magnitude=30 * kN_per_m), PointLoad(position=3 * m, magnitude=80 * kN))
    ).solve()


@pytest.fixture
def envelope(beam):
    cases = (
        LoadCase("G", ActionType.G, (UDL(magnitude=20 * kN_per_m),)),
        LoadCase("Q", ActionType.Q, (UDL(magnitude=15 * kN_per_m),)),
    )
    return analyse_combinations(beam, cases, as1170_uls())


# ---------------------------------------------------------------------------
# Rich display
# ---------------------------------------------------------------------------


def test_calc_result_renders_the_calculation_not_the_dataclass(section):
    result = as3600.moment_capacity(section)
    md = result._repr_markdown_()

    assert "Provenance(" not in md, "must not fall back to the dataclass repr"
    assert result.name in md
    assert "Inputs" in md and "Basis" in md and "Checks" in md
    assert "AS 3600:2018" in md
    # Unverified modules must say so wherever they are displayed.
    assert "not verified" in md.lower()


def test_calc_result_display_shows_pass_fail(section):
    passing = as3600.check_flexure(section, 100e6)
    failing = as3600.check_flexure(section, 5000e6)
    assert "PASS" in passing._repr_markdown_()
    assert "FAIL" in failing._repr_markdown_()


def test_report_renders_the_whole_document(section, envelope):
    report = Report(title="B1 design")
    report.add(envelope.to_calc_result())
    report.add(as3600.check_flexure(section, envelope.M_star))
    md = report._repr_markdown_()

    assert md.startswith("# B1 design")
    assert "Signatures" in md
    assert md == report.render(__import__(
        "austruct.report", fromlist=["MarkdownRenderer"]
    ).MarkdownRenderer())


@pytest.mark.parametrize(
    "factory",
    [
        lambda f: f["section"],
        lambda f: f["results"],
        lambda f: f["envelope"],
        lambda f: f["moving"],
        lambda f: f["influence"],
        lambda f: f["train"],
        lambda f: f["project"],
    ],
)
def test_every_headline_object_has_rich_display(factory, section, beam, results, envelope):
    train = LoadTrain("2ax", axles=((0.0, 100 * kN), (4 * m, 100 * kN)), length=4 * m)
    objects = {
        "section": section,
        "results": results,
        "envelope": envelope,
        "moving": moving_load_envelope(beam, train, step=500.0),
        "influence": influence_line(beam, "moment", location=4 * m, n_points=11),
        "train": train,
        "project": Project(job_number="24-1", occupancy=Occupancy.OFFICE),
    }
    obj = factory(objects)
    md = obj._repr_markdown_()
    assert isinstance(md, str) and md.strip()
    assert "object at 0x" not in md


# ---------------------------------------------------------------------------
# Table exports -- DataFrame-ready without pandas being a dependency
# ---------------------------------------------------------------------------


def test_results_table_is_in_display_units(results):
    table = results.to_table()
    assert set(table) == {"x_m", "shear_kN", "moment_kNm", "deflection_mm"}
    assert len(set(len(v) for v in table.values())) == 1, "columns must be equal length"

    assert max(table["x_m"]) == pytest.approx(8.0)
    assert max(table["moment_kNm"]) == pytest.approx(results.max_moment / 1e6)
    assert all(isinstance(v, float) for v in table["x_m"]), "plain floats, not numpy"


def test_envelope_table_carries_the_governing_case_at_every_position(envelope):
    table = envelope.moment.to_table()
    assert set(table) == {"x_m", "max", "max_case", "min", "min_case"}
    assert len(table["max_case"]) == len(table["x_m"])
    assert all(isinstance(c, str) for c in table["max_case"])
    assert max(table["max"]) == pytest.approx(envelope.moment.peak_max / 1e6)


def test_influence_line_table(beam):
    il = influence_line(beam, "moment", location=4 * m, n_points=11)
    table = il.to_table()
    assert set(table) == {"x_m", "value"}
    assert len(table["x_m"]) == len(il.x)


def test_tables_build_a_dataframe_when_pandas_is_present(results):
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(results.to_table())
    assert list(frame.columns) == ["x_m", "shear_kN", "moment_kNm", "deflection_mm"]
    assert len(frame) == len(results.x)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------


def test_plot_functions_return_figures(section, results, envelope, beam, tmp_path):
    plt = pytest.importorskip("matplotlib")
    plt.use("Agg")
    from austruct.report import plots

    il = influence_line(beam, "moment", location=4 * m, n_points=11)

    figures = [
        plots.plot_diagrams(results),
        plots.plot_envelope(envelope),
        plots.plot_envelope(envelope, show_cases=True),
        plots.plot_influence_line(il),
        plots.plot_section(section),
    ]
    for fig in figures:
        assert fig.axes, "figure has no axes"

    path = plots.save(figures[0], str(tmp_path / "d.png"))
    assert (tmp_path / "d.png").stat().st_size > 1000
    assert path.endswith("d.png")


def test_moment_diagram_is_plotted_sagging_downward(results):
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    from austruct.report import plots

    fig = plots.plot_diagrams(results)
    _, ax_m, ax_d = fig.axes
    # Inverted means the top of the axis is the smaller value.
    assert ax_m.get_ylim()[0] > ax_m.get_ylim()[1], "moment axis must be inverted"
    assert ax_d.get_ylim()[0] > ax_d.get_ylim()[1], "deflection axis must be inverted"


def test_only_the_bottom_axis_carries_the_x_label(results):
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    from austruct.report import plots

    fig = plots.plot_diagrams(results)
    labels = [ax.get_xlabel() for ax in fig.axes]
    assert labels[-1], "bottom axis must be labelled"
    assert not any(labels[:-1]), "sharex shares the scale, not the label"


def test_plots_module_is_not_imported_eagerly():
    """Importing austruct.report must not require matplotlib -- the core
    package installs with numpy alone."""
    import sys

    import austruct.report

    assert "plots" in austruct.report.__all__
    # Accessing it is what pulls it in.
    assert austruct.report.plots is sys.modules["austruct.report.plots"]


def test_unknown_report_attribute_still_raises():
    import austruct.report

    missing = "nonexistent"
    with pytest.raises(AttributeError, match="no attribute"):
        getattr(austruct.report, missing)
