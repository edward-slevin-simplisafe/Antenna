"""Tests for the half-plane shading: where the sides fall along a cut, which split is chosen, and how
it shows up in the single-dataset and comparison figures and in the scripts."""

import os
import subprocess
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402

from antenna import analysis  # noqa: E402
from antenna.models import (AUTO_SHADE_AXIS, SHADE_ALPHA, SHADE_SPLITS, SIDE_COLORS,  # noqa: E402
                            Pattern)
from antenna.plotting import make_compare_figure, make_cut_figure, resolve_shade  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

PATTERN_CSV = """GainT,,Gain:,3.0,,
Theta-Phi,0,90,180,270,360
0,1,1,1,1,1
90,2,3,4,5,2
180,0,0,0,0,0
GainH,,Gain:,-1.0,,
Theta-Phi,0,90,180,270,360
0,-1,-1,-1,-1,-1
90,-2,-3,-4,-5,-2
180,-9,-9,-9,-9,-9
"""


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def pattern(offset_db=0.0):
    """T/H/V tables on a coarse full-sphere grid, peak 0 dB + offset."""
    th = np.array([0.0, 90, 180])
    ph = np.array([0.0, 90, 180, 270, 360])
    base = np.add.outer(np.linspace(0, -6, 3), np.linspace(0, -3, 5))
    gains = {"T": base + offset_db, "H": base - 3 + offset_db, "V": base - 6 + offset_db}
    return Pattern(freq_hz=2.45e9, theta_deg=th, phi_deg=ph, gain_db=gains, name="p")


def rounded(spans):
    return [(round(a, 3), round(b, 3), s) for a, b, s in spans]


# ---- where the sides fall along a cut ---------------------------------------------------------

@pytest.mark.parametrize("cut, value, axis, expected", [
    ("theta", 90, "Y", [(0, 180, 1), (180, 360, -1)]),  # XY plane: rear (+Y) then front (-Y)
    ("theta", 90, "X", [(0, 90, 1), (90, 270, -1), (270, 360, 1)]),
    ("phi", 0, "Z", [(-180, -90, -1), (-90, 90, 1), (90, 180, -1)]),  # XZ plane: top in the middle
    ("phi", 0, "X", [(-180, 0, -1), (0, 180, 1)]),
    ("phi", 90, "Y", [(-180, 0, -1), (0, 180, 1)]),  # YZ plane: front (-Y) then rear (+Y)
    ("phi", 90, "Z", [(-180, -90, -1), (-90, 90, 1), (90, 180, -1)]),
])
def test_shade_spans_principal_planes(cut, value, axis, expected):
    assert rounded(analysis.shade_spans(cut, value, axis)) == expected


@pytest.mark.parametrize("cut, value, axis", [("theta", 90, "Z"), ("phi", 0, "Y"), ("phi", 90, "X")])
def test_shade_spans_axis_not_in_the_plane(cut, value, axis):
    assert analysis.shade_spans(cut, value, axis) is None


@pytest.mark.parametrize("cut, value, axis", [
    ("phi", 45, "Y"), ("phi", 30, "X"), ("phi", 120, "Z"), ("theta", 60, "Z"), ("theta", 45, "X")])
def test_shade_spans_tile_the_whole_range_for_any_cut(cut, value, axis):
    spans = analysis.shade_spans(cut, value, axis)
    lo, hi = (-180, 180) if cut == "phi" else (0, 360)
    assert spans[0][0] == lo and spans[-1][1] == hi
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))  # no gaps or overlaps
    assert all(s in (1, -1) for _, _, s in spans)
    assert all(a[2] == -b[2] for a, b in zip(spans, spans[1:]))  # neighbours are on opposite sides
    assert rounded(analysis.shade_spans("theta", 45, "Z")) == [(0, 360, 1)]  # never crosses: one side


def test_shade_spans_input_errors():
    with pytest.raises(ValueError, match="cut must be"):
        analysis.shade_spans("diagonal", 0, "X")
    with pytest.raises(ValueError, match="axis must be"):
        analysis.shade_spans("phi", 0, "W")


# ---- choosing the split -----------------------------------------------------------------------

def test_split_names_and_auto_choices():
    assert list(SHADE_SPLITS) == ["front-rear", "right-left", "top-bottom"]
    assert AUTO_SHADE_AXIS == {"XY": "Y", "XZ": "X", "YZ": "Z"}
    assert resolve_shade("theta", 90) == ("front-rear", None)  # XY
    assert resolve_shade("phi", 0) == ("right-left", None)  # XZ
    assert resolve_shade("phi", 90) == ("top-bottom", None)  # YZ
    assert resolve_shade("phi", 45, "auto") == ("front-rear", None)  # not a principal plane
    assert resolve_shade("theta", 0) == (None, None)  # a cut around the pole has nothing to split


def test_resolve_shade_off_explicit_and_fallback():
    assert resolve_shade("theta", 90, None) == (None, None)
    assert resolve_shade("theta", 90, "none") == (None, None)
    assert resolve_shade("theta", 90, "right-left") == ("right-left", None)

    split, note = resolve_shade("phi", 0, "front-rear")  # the XZ plane has no Y axis
    assert split == "right-left"
    assert "front-rear shading needs the Y axis" in note and "XZ plane" in note
    assert "using right-left" in note
    split, note = resolve_shade("theta", 90, "top-bottom")  # the XY plane has no Z axis
    assert split == "front-rear" and "top-bottom shading needs the Z axis" in note
    split, note = resolve_shade("phi", 90, "right-left")  # the YZ plane has no X axis
    assert split == "top-bottom" and "right-left shading needs the X axis" in note
    assert "YZ plane" in note and "using top-bottom" in note

    with pytest.raises(ValueError, match="shade must be"):
        resolve_shade("theta", 90, "bogus")


# ---- the single-dataset figures ---------------------------------------------------------------

def test_rect_shading_spans_colors_legend_and_layering():
    fig = make_cut_figure(pattern(), "theta", 90, "rect")  # shading is on by default
    ax = fig.axes[0]
    assert [(round(p.get_x()), round(p.get_x() + p.get_width())) for p in ax.patches] == \
        [(0, 180), (180, 360)]
    assert to_rgb(ax.patches[0].get_facecolor()) == pytest.approx(to_rgb(SIDE_COLORS["Rear"]))
    assert to_rgb(ax.patches[1].get_facecolor()) == pytest.approx(to_rgb(SIDE_COLORS["Front"]))
    assert ax.patches[0].get_alpha() == SHADE_ALPHA
    assert [t.get_text() for t in ax.get_legend().get_texts()][-2:] == ["Front (-Y)", "Rear (+Y)"]
    assert all(p.get_zorder() < ln.get_zorder() for p in ax.patches for ln in ax.get_lines())


def test_rect_shading_off_and_explicit_choices():
    for off in (None, "none"):
        ax = make_cut_figure(pattern(), "theta", 90, "rect", shade=off).axes[0]
        assert len(ax.patches) == 0
        assert not {"Front (-Y)", "Rear (+Y)"} & {t.get_text() for t in ax.get_legend().get_texts()}
    assert len(make_cut_figure(pattern(), "theta", 90, "rect", shade="right-left").axes[0].patches) == 3
    xz = make_cut_figure(pattern(), "phi", 0, "rect").axes[0]  # left on the negative angles
    assert [(round(p.get_x()), round(p.get_x() + p.get_width())) for p in xz.patches] == \
        [(-180, 0), (0, 180)]
    assert to_rgb(xz.patches[0].get_facecolor()) == pytest.approx(to_rgb(SIDE_COLORS["Left"]))
    assert to_rgb(xz.patches[1].get_facecolor()) == pytest.approx(to_rgb(SIDE_COLORS["Right"]))
    assert [t.get_text() for t in xz.get_legend().get_texts()][-2:] == ["Right (+X)", "Left (-X)"]
    yz = make_cut_figure(pattern(), "phi", 90, "rect").axes[0]  # top in the middle, bottom either side
    assert len(yz.patches) == 3
    assert [t.get_text() for t in yz.get_legend().get_texts()][-2:] == ["Top (+Z)", "Bottom (-Z)"]
    fallback = make_cut_figure(pattern(), "phi", 0, "rect", shade="front-rear").axes[0]
    assert len(fallback.patches) == 2  # front-rear has no meaning in XZ, so right-left is used


def test_polar_shading_follows_the_radial_limits():
    fig = make_cut_figure(pattern(), "phi", 90, "polar")  # YZ: top in the middle, bottom either side
    ax = fig.axes[0]
    assert len(ax.collections) == 3
    radii = np.unique(np.round(ax.collections[0].get_paths()[0].vertices[:, 1], 6))
    assert radii.tolist() == [ax.get_rmin(), ax.get_rmax()]  # fills the whole radius
    assert [t.get_text() for t in fig.legends[0].get_texts()][-2:] == ["Top (+Z)", "Bottom (-Z)"]
    xz = make_cut_figure(pattern(), "phi", 0, "polar")
    assert len(xz.axes[0].collections) == 2
    assert [t.get_text() for t in xz.legends[0].get_texts()][-2:] == ["Right (+X)", "Left (-X)"]
    assert len(make_cut_figure(pattern(), "theta", 90, "polar").axes[0].collections) == 2
    assert len(make_cut_figure(pattern(), "theta", 90, "polar", shade=None).axes[0].collections) == 0


# ---- the comparison figures -------------------------------------------------------------------

def test_compare_shades_every_panel_including_the_difference_row():
    pair = [pattern(), pattern(2.0)]
    rect = make_compare_figure(pair, ["A", "B"], "theta", 90, "rect")
    assert len(rect.axes) == 6 and all(len(ax.patches) == 2 for ax in rect.axes)
    assert [t.get_text() for t in rect.legends[0].get_texts()] == [
        "A", "B", "4 dB limit", "Front (-Y)", "Rear (+Y)"]
    polar = make_compare_figure(pair, ["A", "B"], "theta", 90, "polar")
    assert len(polar.axes) == 3 and all(len(ax.collections) == 2 for ax in polar.axes)
    assert [t.get_text() for t in polar.legends[0].get_texts()] == [
        "A", "B", "Front (-Y)", "Rear (+Y)"]
    off = make_compare_figure(pair, ["A", "B"], "theta", 90, "rect", shade="none")
    assert all(len(ax.patches) == 0 for ax in off.axes)
    xz = make_compare_figure(pair, ["A", "B"], "phi", 0, "rect", shade="front-rear")
    assert all(len(ax.patches) == 2 for ax in xz.axes)  # falls back to right-left in the XZ plane


# ---- the scripts --------------------------------------------------------------------------------

def run_script(name, cwd, *args):
    env = dict(os.environ, MPLBACKEND="Agg")
    return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)], cwd=cwd, env=env,
                          capture_output=True, text=True)


def test_plot_patterns_script_shade_option(tmp_path):
    (tmp_path / "x-2450.000000MHz.csv").write_text(PATTERN_CSV)
    run = run_script("plot_patterns.py", tmp_path, "x-2450.000000MHz.csv", "--plane", "XY", "XZ",
                     "--pols", "T", "H", "--kind", "rect", "--shade", "front-rear", "--save-dir", "out")
    assert run.returncode == 0, run.stderr
    assert "Note: front-rear shading needs the Y axis, which is not in the XZ plane; using right-left" \
        in run.stdout
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "2450MHz_XY_rect.png", "2450MHz_XZ_rect.png"]
    quiet = run_script("plot_patterns.py", tmp_path, "x-2450.000000MHz.csv", "--plane", "XY", "--pols",
                       "T", "H", "--kind", "rect", "--shade", "none", "--save-dir", "out2")
    assert quiet.returncode == 0 and "shading" not in quiet.stdout
    bad = run_script("plot_patterns.py", tmp_path, "x-2450.000000MHz.csv", "--plane", "XY",
                     "--shade", "bogus")
    assert bad.returncode == 2 and "invalid choice" in bad.stderr


def test_compare_patterns_script_shade_option(tmp_path):
    for folder in ("a_pattern", "b_pattern"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "x-2450.000000MHz.csv").write_text(PATTERN_CSV)
    common = ("a_pattern", "b_pattern", "--pols", "T", "H", "--kind", "rect", "--save-dir", "out")
    run = run_script("compare_patterns.py", tmp_path, *common, "--plane", "XZ", "--shade", "front-rear")
    assert run.returncode == 0, run.stderr
    assert "Note: front-rear shading needs the Y axis, which is not in the XZ plane" in run.stdout
    quiet = run_script("compare_patterns.py", tmp_path, *common, "--plane", "XY", "--shade", "none")
    assert quiet.returncode == 0 and "shading" not in quiet.stdout
    bad = run_script("compare_patterns.py", tmp_path, *common, "--plane", "XY", "--shade", "bogus")
    assert bad.returncode == 2 and "invalid choice" in bad.stderr
