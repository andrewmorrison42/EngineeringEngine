"""Tests for engineer narrative in reports, and the HTML renderer.

The point of these features is a document a road authority or an independent
reviewer can read. So the tests check the two things that decide whether it is
readable: that the engineer's prose appears WHERE IT WAS WRITTEN rather than
being swept to the end, and that a reader can tell the engineer's statements
apart from the package's output.
"""

from __future__ import annotations

import re

import pytest

from austruct.core.units import kNm
from austruct.design import as3600
from austruct.materials import concrete
from austruct.report import (
    HtmlRenderer,
    MarkdownRenderer,
    NarrativeKind,
    Report,
    SignatureBlock,
)
from austruct.sections import rc_beam


@pytest.fixture
def section():
    return rc_beam(
        b=300, D=600, concrete=concrete(32), cover=40,
        n_bars=4, diameter=24, fitment_diameter=12, fitment_spacing=200,
        name="B1",
    )


@pytest.fixture
def report(section):
    r = Report(
        title="Beam B1",
        signature=SignatureBlock(job_number="24-001", element="B1", designed_by="AM"),
    )
    r.add_scope("Covers flexure at midspan only.")
    r.add(as3600.check_flexure(section, 200 * kNm))
    r.add_narrative("The corner moment governs because the walls restrain the slab.")
    r.add(as3600.check_shear(section, 150e3, 200 * kNm))
    r.add_conclusion("The section is adequate.")
    return r


# ---------------------------------------------------------------------------
# The ordered body
# ---------------------------------------------------------------------------


def test_narrative_and_results_share_one_ordered_body(report):
    kinds = [type(item).__name__ for item in report.items]
    assert kinds == [
        "Narrative", "CalcResult", "Narrative", "CalcResult", "Narrative"
    ]


def test_results_and_figures_remain_available_as_views(report):
    assert len(report.results) == 2
    assert report.figures == []
    assert len(report.narratives) == 3


def test_figures_land_where_they_are_added(report):
    report.add_figure("Bending moment diagram", "bmd.png")
    assert type(report.items[-1]).__name__ == "Figure"
    assert report.figures == [("Bending moment diagram", "bmd.png")]


def test_a_report_can_be_asked_whether_it_states_its_assumptions(report):
    """So it can be checked before issue rather than after."""
    assert report.has_narrative(NarrativeKind.SCOPE)
    assert report.has_narrative(NarrativeKind.CONCLUSION)
    assert not report.has_narrative(NarrativeKind.LIMITATION)


def test_the_legacy_results_argument_still_populates_the_body(section):
    result = as3600.check_flexure(section, 100 * kNm)
    r = Report(title="T", results_in=[result])
    assert r.results == [result]


def test_pass_and_issuable_still_read_off_the_results(report):
    assert report.passed == all(r.passed for r in report.results)
    assert not report.issuable, "unverified modules"


# ---------------------------------------------------------------------------
# Markdown: prose in place
# ---------------------------------------------------------------------------


def test_markdown_puts_narrative_between_the_calculations(report):
    text = report.render(MarkdownRenderer())
    scope = text.index("Covers flexure at midspan only")
    flexure = text.index("1. ")
    commentary = text.index("The corner moment governs")
    shear = text.index("2. ")
    conclusion = text.index("The section is adequate")

    assert scope < flexure < commentary < shear < conclusion


def test_markdown_sets_a_scope_apart_but_leaves_commentary_as_prose(report):
    text = report.render(MarkdownRenderer())
    assert "> **SCOPE**" in text
    assert "The corner moment governs because the walls restrain the slab." in text
    assert "> The corner moment governs" not in text


def test_calculations_are_still_numbered_in_order(report):
    text = report.render(MarkdownRenderer())
    numbers = re.findall(r"^## (\d+)\. ", text, flags=re.MULTILINE)
    assert numbers == ["1", "2"], "narrative must not consume a number"


# ---------------------------------------------------------------------------
# HTML: the document that leaves the office
# ---------------------------------------------------------------------------


def test_html_is_one_self_contained_document(report):
    out = report.render(HtmlRenderer())
    assert out.startswith("<!DOCTYPE html>")
    assert "<style>" in out, "styling must be inline, not linked"
    assert "<script" not in out, "no JavaScript to be blocked or to break"
    assert "http://" not in out and "https://" not in out, "no external requests"


def test_html_marks_an_unverified_report_prominently(report):
    out = report.render(HtmlRenderer())
    assert "NOT VERIFIED FOR ISSUE" in out
    assert "running-warning" in out, "and on every printed page"


def test_html_carries_a_print_stylesheet(report):
    out = report.render(HtmlRenderer())
    assert "@media print" in out
    assert "break-inside: avoid" in out


def test_html_distinguishes_engineer_prose_from_generated_content(report):
    """A reviewer must be able to see which statements are the engineer's."""
    out = report.render(HtmlRenderer())
    assert 'class="narrative scope"' in out
    assert 'class="narrative commentary"' in out


def test_html_preserves_body_order(report):
    out = report.render(HtmlRenderer())
    assert out.index("Covers flexure at midspan") < out.index(
        "The corner moment governs"
    ) < out.index("The section is adequate")


def test_html_escapes_user_text():
    """A job name with an ampersand must not corrupt the document."""
    r = Report(title="Smith & Jones <Bridge>")
    r.add_narrative("Load < capacity & that is fine")
    out = r.render(HtmlRenderer())
    assert "Smith &amp; Jones &lt;Bridge&gt;" in out
    assert "Load &lt; capacity &amp; that is fine" in out


def test_html_shows_a_failing_check_distinctly(section):
    r = Report(title="Overloaded")
    r.add(as3600.check_flexure(section, 900 * kNm))
    out = r.render(HtmlRenderer())
    assert 'class="failed"' in out
    assert "banner fail" in out


def test_html_renders_the_signature_block(report):
    out = report.render(HtmlRenderer())
    assert "Signatures" in out
    assert "AM" in out
    assert "24-001" in out


def test_both_renderers_accept_the_same_report(report):
    """The layout is the standard; renderers are interchangeable."""
    md = report.render(MarkdownRenderer())
    html = report.render(HtmlRenderer())
    for renderer_output in (md, html):
        assert "Beam B1" in renderer_output
        assert "The section is adequate" in renderer_output


def test_an_empty_report_still_renders(report):
    empty = Report(title="Nothing yet")
    assert empty.render(HtmlRenderer()).startswith("<!DOCTYPE html>")
    assert "Nothing yet" in empty.render(MarkdownRenderer())


def test_multi_paragraph_narrative_becomes_multiple_paragraphs():
    r = Report(title="T")
    r.add_narrative("First para.\n\nSecond para.")
    out = r.render(HtmlRenderer())
    assert out.count("<p>First para.</p>") == 1
    assert out.count("<p>Second para.</p>") == 1
