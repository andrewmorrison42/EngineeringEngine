"""Plots -- diagrams, envelopes, influence lines and section geometry.

ASET component 6 covers "embedded plots and geometry", which is section 5 of
the report template. This module fills it, and doubles as the thing that makes
the package pleasant in a Jupyter notebook.

matplotlib is an OPTIONAL dependency
------------------------------------
The core package installs with numpy alone, because the distribution path is a
wheelhouse on a shared drive and a compiled ``.exe`` for factory users, and
every dependency is one more thing to vendor. So matplotlib is imported lazily,
here, and its absence produces a clear instruction rather than an ImportError
traceback from somewhere unexpected::

    pip install austruct[plots]

Conventions
-----------
Every plot puts the x axis in METRES and the vertical axis in kN or kN.m,
because that is what an engineer reads. Bending moment is plotted with the
SAGGING side DOWN, which is the drawing convention -- the diagram then hangs
below the beam the way the beam deflects.

[UNITS] Inputs are base units (mm, N, N.mm) as everywhere; the conversion to
        display units happens in this module only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..core.provenance import ASETComponent, ModuleType, Provenance
from ..core.registry import REGISTRY
from ..core.units import kN, kNm

if TYPE_CHECKING:  # pragma: no cover
    from ..analysis.envelope import BeamEnvelope
    from ..analysis.moving import InfluenceLine
    from ..analysis.results import BeamResults
    from ..sections.rc_section import RCSection

PROVENANCE = REGISTRY.register(
    Provenance(
        module=__name__,
        version="0.1.0",
        author="A. Morrison",
        module_type=ModuleType.C_GEOMETRY,
        component=ASETComponent.REPORTING,
    ),
    description="Diagram, envelope, influence line and section plots",
    envelope_summary="Presentation only -- produces no numbers",
)


def _plt() -> Any:
    """matplotlib.pyplot, or a clear instruction if it is not installed."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover -- depends on the environment
        raise ImportError(
            "Plotting needs matplotlib, which is an optional dependency of "
            "austruct. Install it with:\n\n"
            "    pip install 'austruct[plots]'\n\n"
            "The core package deliberately depends on numpy alone so it can be "
            "vendored into a wheelhouse and frozen into a .exe."
        ) from exc
    return plt


def _style_axis(ax: Any, ylabel: str, title: str = "", xlabel: bool = True) -> None:
    """House style: zero line, light grid, labelled axes.

    ``xlabel`` is False for all but the bottom axis of a stacked figure --
    matplotlib's ``sharex`` shares the SCALE, not the label, so without this
    every subplot repeats "Distance along member (m)".
    """
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.grid(True, alpha=0.3, linewidth=0.5)
    if xlabel:
        ax.set_xlabel("Distance along member (m)")
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title, fontsize=10)


def plot_diagrams(
    results: BeamResults,
    figsize: tuple[float, float] = (9.0, 7.0),
    title: str = "",
) -> Any:
    """Shear, bending moment and deflection, stacked on a shared x axis.

    Parameters
    ----------
    results:
        From :meth:`austruct.analysis.beam.Beam.solve`.
    figsize:
        Figure size in inches.
    title:
        Overall title. Defaults to the member name.

    Returns
    -------
    matplotlib.figure.Figure

    Examples
    --------
    >>> fig = plot_diagrams(beam.solve())
    """
    plt = _plt()
    fig, (ax_v, ax_m, ax_d) = plt.subplots(3, 1, figsize=figsize, sharex=True)

    x = results.x / 1000.0

    ax_v.plot(x, results.shear / kN, color="tab:blue", linewidth=1.2)
    ax_v.fill_between(x, results.shear / kN, 0, alpha=0.15, color="tab:blue")
    _style_axis(ax_v, "Shear (kN)", xlabel=False)

    ax_m.plot(x, results.moment / kNm, color="tab:red", linewidth=1.2)
    ax_m.fill_between(x, results.moment / kNm, 0, alpha=0.15, color="tab:red")
    _style_axis(ax_m, "Moment (kN.m)", xlabel=False)
    # [ASSUMPTION] Sagging plotted DOWNWARD, the drawing convention -- the
    #              diagram then hangs below the beam the way it deflects.
    ax_m.invert_yaxis()

    ax_d.plot(x, results.deflection, color="tab:green", linewidth=1.2)
    _style_axis(ax_d, "Deflection (mm)")
    ax_d.invert_yaxis()  # downward deflection plotted downward

    _annotate_peak(ax_v, x, results.shear / kN, "V")
    _annotate_peak(ax_m, x, results.moment / kNm, "M", inverted=True)

    fig.suptitle(title or results.beam_name or "Beam diagrams", fontsize=11)
    fig.tight_layout()
    return fig


def _annotate_peak(ax: Any, x, values, symbol: str, inverted: bool = False) -> None:
    """Mark the largest magnitude on a diagram.

    Worth doing automatically: the peak and its position are the two numbers
    anybody reads off a diagram, and hunting for them defeats the plot.
    """
    import numpy as np

    idx = int(np.argmax(np.abs(values)))
    peak, at = float(values[idx]), float(x[idx])
    ax.plot([at], [peak], "o", color="black", markersize=4)
    # On an inverted axis the peak sits at the BOTTOM of the plot, so the
    # label must go up the screen to stay clear of the axis edge.
    ax.annotate(
        f"{symbol} = {peak:.1f} at {at:.2f} m",
        xy=(at, peak),
        xytext=(6, 8),
        textcoords="offset points",
        fontsize=8,
        va="bottom",
    )


def plot_envelope(
    envelope: BeamEnvelope,
    figsize: tuple[float, float] = (9.0, 5.0),
    show_cases: bool = False,
) -> Any:
    """Moment and shear envelopes, with the individual cases optionally behind.

    Parameters
    ----------
    envelope:
        From :func:`austruct.analysis.envelope.analyse_combinations` or a
        moving-load sweep.
    show_cases:
        Draw every contributing case faintly behind the envelope. Illuminating
        for a handful of combinations; unreadable for a 200-position sweep, so
        it is off by default.

    Returns
    -------
    matplotlib.figure.Figure
    """
    plt = _plt()
    fig, (ax_m, ax_v) = plt.subplots(2, 1, figsize=figsize, sharex=True)

    x = envelope.moment.x / 1000.0

    if show_cases:
        for result in envelope.case_results.values():
            cx = result.x / 1000.0
            ax_m.plot(cx, result.moment / kNm, color="grey", alpha=0.25, linewidth=0.6)
            ax_v.plot(cx, result.shear / kN, color="grey", alpha=0.25, linewidth=0.6)

    for ax, env, unit, colour in (
        (ax_m, envelope.moment, kNm, "tab:red"),
        (ax_v, envelope.shear, kN, "tab:blue"),
    ):
        ax.plot(x, env.max_values / unit, color=colour, linewidth=1.3, label="max")
        ax.plot(
            x, env.min_values / unit, color=colour, linewidth=1.3,
            linestyle="--", label="min",
        )
        ax.fill_between(
            x, env.max_values / unit, env.min_values / unit,
            alpha=0.12, color=colour,
        )
        ax.legend(fontsize=8, loc="best")

    _style_axis(ax_m, "Moment (kN.m)", xlabel=False)
    ax_m.invert_yaxis()
    _style_axis(ax_v, "Shear (kN)")

    fig.suptitle(
        f"{envelope.member} -- {envelope.limit_state.value} envelope "
        f"({len(envelope.case_results)} cases)",
        fontsize=11,
    )
    fig.tight_layout()
    return fig


def plot_influence_line(
    line: InfluenceLine,
    figsize: tuple[float, float] = (9.0, 3.0),
) -> Any:
    """One influence line, with its peak marked.

    Returns
    -------
    matplotlib.figure.Figure
    """
    plt = _plt()
    fig, ax = plt.subplots(figsize=figsize)

    x = line.x / 1000.0
    ax.plot(x, line.values, color="tab:purple", linewidth=1.2)
    ax.fill_between(x, line.values, 0, alpha=0.15, color="tab:purple")
    ax.axvline(line.location / 1000.0, color="black", linestyle=":", linewidth=0.8)

    _style_axis(
        ax,
        "Influence value",
        f"Influence line: {line.response} at x = {line.location / 1000:.3f} m",
    )
    fig.tight_layout()
    return fig


def plot_section(
    section: RCSection,
    figsize: tuple[float, float] = (4.0, 5.0),
) -> Any:
    """Cross-section outline with the reinforcement drawn to scale.

    Bars are drawn at their true diameter where the layer has been detailed,
    and as a marker where it has been specified by area only -- so a section
    that has been sized but not detailed is visibly different from one that has.

    Returns
    -------
    matplotlib.figure.Figure
    """
    plt = _plt()
    from matplotlib.patches import Circle, Rectangle

    fig, ax = plt.subplots(figsize=figsize)

    # Outline, band by band, so tees and stepped sections draw correctly.
    for band in section.geometry.bands:
        ax.add_patch(
            Rectangle(
                (-band.width / 2.0, -band.y_bot),
                band.width,
                band.height,
                facecolor="lightgrey",
                edgecolor="black",
                linewidth=1.0,
            )
        )

    for layer in section.layers:
        y = -layer.depth
        if layer.n_bars and layer.diameter:
            # Spread the bars across the width available at that depth.
            width = section.geometry.width_at(layer.depth)
            cover_ish = 0.12 * width
            usable = width - 2 * cover_ish
            n = layer.n_bars
            xs = (
                [0.0]
                if n == 1
                else [-usable / 2 + usable * i / (n - 1) for i in range(n)]
            )
            for bx in xs:
                ax.add_patch(
                    Circle((bx, y), layer.diameter / 2.0, facecolor="black")
                )
        else:
            ax.plot([0.0], [y], marker="s", color="black", markersize=5)
            ax.annotate(
                f"A_s = {layer.area:.0f} mm²",
                xy=(0.0, y),
                xytext=(6, 0),
                textcoords="offset points",
                fontsize=7,
            )

    ax.set_aspect("equal")
    ax.set_xlabel("mm")
    ax.set_ylabel("mm")
    ax.set_title(section.name or "Section", fontsize=10)
    ax.autoscale_view()
    fig.tight_layout()
    return fig


def save(fig: Any, path: str, dpi: int = 150) -> str:
    """Save a figure and return the path, for embedding in a report.

    Examples
    --------
    >>> report.add_figure("Bending moment diagram",
    ...                   save(plot_diagrams(results), "bmd.png"))
    """
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    return path
