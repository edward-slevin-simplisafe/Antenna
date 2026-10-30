"""Tests for comparing datasets: frequency matching, the comparison figures and compare_patterns.py."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from antenna import analysis  # noqa: E402
from antenna.models import Pattern  # noqa: E402
from antenna.plotting import DATASET_COLORS, make_compare_figure  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_patterns.py"

# A tiny full-sphere pattern file with T, H and L tables (no V).
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
GainL,,,,,
Theta-Phi,0,90,180,270,360
0,0,0,0,0,0
90,0,0,0,0,0
180,0,0,0,0,0
"""


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


def three_pol_pattern(freq_mhz, offset_db=0.0, theta=(0, 90, 180)):
    """T/H/V tables on a coarse full-sphere grid with a smooth, varied shape (peak 0 dB + offset)."""
    th = np.array(theta, dtype=float)
    ph = np.array([0.0, 90, 180, 270, 360])
    base = np.add.outer(np.linspace(0, -6, len(th)), np.linspace(0, -3, len(ph)))
    gains = {"T": base + offset_db, "H": base - 3 + offset_db, "V": base - 6 + offset_db}
    return Pattern(freq_hz=freq_mhz * 1e6, theta_deg=th, phi_deg=ph, gain_db=gains,
                   name=f"p{freq_mhz:g}")


def flat_pattern(freq_mhz, gain_db, theta):
    th = np.array(theta, dtype=float)
    ph = np.array([0.0, 90, 180, 270, 360])
    gains = {k: np.full((len(th), len(ph)), float(gain_db)) for k in "THV"}
    return Pattern(freq_hz=freq_mhz * 1e6, theta_deg=th, phi_deg=ph, gain_db=gains, name="flat")


def compare(kind="rect", labels=("A", "B"), offsets=(0.0, 2.0), **kwargs):
    kwargs.setdefault("shade", None)  # shading has its own tests (test_shading.py)
    patterns = [three_pol_pattern(2450, o) for o in offsets]
    return make_compare_figure(patterns, list(labels), "phi", 0, kind, **kwargs)


# ---- frequency matching ---------------------------------------------------------------------

def test_match_by_frequency_pairs_within_tolerance_and_reports_skipped():
    a = [three_pol_pattern(f) for f in (2400, 2410, 2420)]
    b = [three_pol_pattern(f) for f in (2410.3, 2420, 2430)]
    groups, skipped = analysis.match_by_frequency([a, b], ["A", "B"])
    assert [g[0] for g in groups] == [2410.0, 2420.0]
    assert groups[0][1][0] is a[1] and groups[0][1][1] is b[0]  # 2410.3 counts as 2410
    assert skipped == {"A": [2400.0], "B": [2430.0]}


def test_match_by_frequency_three_sets_none_in_common_and_duplicates():
    a = [three_pol_pattern(f) for f in (2400, 2410)]
    b = [three_pol_pattern(f) for f in (2410, 2420)]
    c = [three_pol_pattern(2410)]
    groups, skipped = analysis.match_by_frequency([a, b, c], ["A", "B", "C"])
    assert [g[0] for g in groups] == [2410.0] and len(groups[0][1]) == 3
    assert skipped == {"A": [2400.0], "B": [2420.0], "C": []}

    groups, skipped = analysis.match_by_frequency(
        [[three_pol_pattern(2400)], [three_pol_pattern(2500)]], ["A", "B"])
    assert groups == [] and skipped == {"A": [2400.0], "B": [2500.0]}

    twins = [three_pol_pattern(2450), three_pol_pattern(2450.2)]
    with pytest.raises(ValueError, match="A: two files at 2450 and 2450.2 MHz"):
        analysis.match_by_frequency([twins, b], ["A", "B"])
    with pytest.raises(ValueError, match="one label per dataset"):
        analysis.match_by_frequency([a, b], ["A"])


# ---- the comparison figures -----------------------------------------------------------------

def test_compare_rect_layout_colors_and_difference():
    fig = compare("rect")
    assert len(fig.axes) == 6  # three overlay panels and three difference panels
    top, diff = fig.axes[:3], fig.axes[3:]
    assert [ax.get_title() for ax in top] == ["H+V", "H", "V"]

    lines = {ln.get_label(): ln for ln in top[0].get_lines()}
    assert lines["A"].get_color().lower() == DATASET_COLORS[0].lower()
    assert lines["B"].get_color().lower() == DATASET_COLORS[1].lower()

    (b_minus_a,) = [ln for ln in diff[0].get_lines() if ln.get_label() == "B − A"]
    assert list(b_minus_a.get_ydata()) == pytest.approx([2.0] * len(b_minus_a.get_ydata()))
    assert any(list(ln.get_ydata()) == [0, 0] for ln in diff[0].get_lines())  # the zero line

    assert "4 dB limit" in [ln.get_label() for ln in top[0].get_lines()]
    assert "4 dB limit" not in [ln.get_label() for ln in diff[0].get_lines()]
    assert [t.get_text() for t in fig.legends[0].get_texts()] == ["A", "B", "4 dB limit"]
    assert fig.get_suptitle() == "2450 MHz   XZ plane (φ = 0°)"


def test_compare_shares_the_gain_axis_across_panels_and_honors_limits():
    fig = compare("rect")
    assert {ax.get_ylim() for ax in fig.axes[:3]} == {(-35.0, 5.0)}  # one scale for H+V, H, V
    assert {ax.get_ylim() for ax in fig.axes[3:]} == {(-10.0, 10.0)}

    explicit = compare("rect", rmin=-30, rmax=3, diff_range_db=4)
    assert {ax.get_ylim() for ax in explicit.axes[:3]} == {(-30.0, 3.0)}
    assert {ax.get_ylim() for ax in explicit.axes[3:]} == {(-4.0, 4.0)}

    no_limit = compare("rect", gain_limit_db=None)
    assert "4 dB limit" not in [t.get_text() for t in no_limit.legends[0].get_texts()]


def test_compare_polar_panels_and_three_datasets():
    fig = compare("polar")
    assert len(fig.axes) == 3 and all(ax.name == "polar" for ax in fig.axes)
    assert [t.get_text() for t in fig.legends[0].get_texts()] == ["A", "B"]

    three = compare("rect", labels=("A", "B", "C"), offsets=(0.0, 1.0, -1.0))
    diff_labels = [ln.get_label() for ln in three.axes[3].get_lines() if ln.get_label()[0] != "_"]
    assert diff_labels == ["B − A", "C − A"]  # every later set against the first
    assert [t.get_text() for t in three.legends[0].get_texts()] == ["A", "B", "C", "4 dB limit"]


def test_compare_counts_differences_beyond_the_range():
    fig = compare("rect", offsets=(0.0, 20.0))
    assert [t.get_text() for t in fig.axes[3].texts] == ["5 points beyond ±10 dB"]
    assert len(compare("rect", offsets=(0.0, 20.0), diff_range_db=30).axes[3].texts) == 0

    # exactly one point differs (theta = 0 appears once along a phi cut), and only in T: singular
    a, b = three_pol_pattern(2450), three_pol_pattern(2450)
    b.gain_db["T"][0, 0] += 20
    fig = make_compare_figure([a, b], ["A", "B"], "phi", 0, "rect")
    assert [t.get_text() for t in fig.axes[3].texts] == ["1 point beyond ±10 dB"]
    assert len(fig.axes[4].texts) == 0  # the H panel is unchanged


def test_compare_resamples_a_different_angle_grid_and_notes_smoothing():
    coarse = flat_pattern(2450, 3.0, (0, 90, 180))
    fine = flat_pattern(2450, 5.0, (0, 45, 90, 135, 180))
    fig = make_compare_figure([coarse, fine], ["coarse", "fine"], "phi", 0, "rect")
    (diff,) = [ln for ln in fig.axes[3].get_lines() if ln.get_label() == "fine − coarse"]
    assert list(diff.get_ydata()) == pytest.approx([2.0] * len(diff.get_ydata()))

    theta, phi = np.arange(0.0, 181, 5), np.arange(0.0, 361, 5)
    grid = np.add.outer(-theta / 30, -phi / 90)
    fine5 = [Pattern(freq_hz=2.45e9, theta_deg=theta, phi_deg=phi,
                     gain_db={k: grid - i for k in "THV"}, name="p") for i in range(2)]
    smoothed = make_compare_figure(fine5, ["A", "B"], "phi", 0, "polar", smooth_deg=20)
    assert "(25° smoothing window)" in smoothed.get_suptitle()


def test_compare_figure_input_errors():
    p = [three_pol_pattern(2450), three_pol_pattern(2450)]
    with pytest.raises(ValueError, match="at least two"):
        make_compare_figure(p[:1], ["A"], "phi", 0)
    with pytest.raises(ValueError, match="2 datasets but 1 labels"):
        make_compare_figure(p, ["A"], "phi", 0)
    with pytest.raises(ValueError, match="labels must all be different"):
        make_compare_figure(p, ["A", "A"], "phi", 0)
    with pytest.raises(ValueError, match="at most 6"):
        make_compare_figure([three_pol_pattern(2450)] * 7, list("ABCDEFG"), "phi", 0)
    with pytest.raises(ValueError, match="kind must be"):
        make_compare_figure(p, ["A", "B"], "phi", 0, kind="3d")
    with pytest.raises(KeyError, match="no GainL"):
        make_compare_figure(p, ["A", "B"], "phi", 0, pols=["L"])
    with pytest.raises(ValueError, match="rmin"):
        make_compare_figure(p, ["A", "B"], "phi", 0, rmin=5, rmax=0)


# ---- the compare_patterns.py script ---------------------------------------------------------

def load_script():
    spec = importlib.util.spec_from_file_location("compare_patterns", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(cwd, *args):
    env = dict(os.environ, MPLBACKEND="Agg")
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=cwd, env=env,
                          capture_output=True, text=True)


def test_default_labels_and_slugs(tmp_path):
    module = load_script()
    for name in ("v1p9-A_pattern", "v2p1_Pattern", "plain"):
        (tmp_path / name).mkdir()
    assert module.default_label(tmp_path / "v1p9-A_pattern") == "v1p9-A"
    assert module.default_label(tmp_path / "v2p1_Pattern") == "v2p1"
    assert module.default_label(tmp_path / "plain") == "plain"
    assert module.default_label(tmp_path / "v1p9-A_pattern" / "x-2450MHz.csv") == "v1p9-A"  # a file
    assert module.slug("v1.9 A / test") == "v1.9-A-test"


def test_script_pairs_frequencies_saves_and_reports(tmp_path):
    for folder, freqs in (("alpha_pattern", (2400, 2410)), ("beta_Pattern", (2410, 2420))):
        (tmp_path / folder).mkdir()
        for f in freqs:
            (tmp_path / folder / f"x-{f}.000000MHz.csv").write_text(PATTERN_CSV)
    run = run_script(tmp_path, "alpha_pattern", "beta_Pattern", "--plane", "XY", "--pols", "T", "H",
                     "--kind", "rect", "polar", "--save-dir", "out")
    assert run.returncode == 0, run.stderr
    assert "Skipping 1 frequency of alpha" in run.stdout and "2400" in run.stdout
    assert "Skipping 1 frequency of beta" in run.stdout and "2420" in run.stdout
    saved = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert saved == ["2410MHz_XY_polar_alpha_vs_beta.png", "2410MHz_XY_rect_alpha_vs_beta.png"]


def test_script_error_messages(tmp_path):
    for folder, freq in (("a_pattern", 2400), ("b_pattern", 2500)):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / f"x-{freq}.000000MHz.csv").write_text(PATTERN_CSV)
    one = run_script(tmp_path, "a_pattern", "--plane", "XY")
    assert one.returncode == 2 and "at least two" in one.stderr
    typo = run_script(tmp_path, "a_pattern", "nope_pattern", "--plane", "XY")
    assert typo.returncode == 1 and "no file or folder matches" in typo.stderr
    none = run_script(tmp_path, "a_pattern", "b_pattern", "--plane", "XY", "--pols", "T")
    assert none.returncode == 1 and "no frequency in common" in none.stderr
    same = run_script(tmp_path, "a_pattern", "a_pattern", "--plane", "XY")
    assert same.returncode == 2 and "different names" in same.stderr
    nothing = run_script(tmp_path, "a_pattern", "b_pattern")
    assert nothing.returncode == 2 and "choose what to plot" in nothing.stderr
