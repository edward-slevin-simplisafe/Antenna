import numpy as np
import pytest

from antenna import analysis
from antenna.readers import read_pattern, read_s1p
from antenna.readers.pattern import freq_from_filename

S1P_RI = """!Agilent Technologies,E5071C
!Freq\tS11
# Hz S RI R 50
2000000000\t0.5\t-0.5
2100000000\t0.0\t0.1
"""

S1P_DB_GHZ = """# GHZ S DB R 75
2.4 -10 90
"""


def test_s1p_ri(tmp_path):
    f = tmp_path / "a.s1p"
    f.write_text(S1P_RI)
    d = read_s1p(f)
    np.testing.assert_allclose(d.freq_hz, [2.0e9, 2.1e9])
    np.testing.assert_allclose(d.s11, [0.5 - 0.5j, 0.1j])
    assert d.z0 == 50


def test_s1p_db_ghz(tmp_path):
    f = tmp_path / "a.s1p"
    f.write_text(S1P_DB_GHZ)
    d = read_s1p(f)
    assert d.freq_hz[0] == pytest.approx(2.4e9)
    assert d.z0 == 75
    assert abs(d.s11[0]) == pytest.approx(10 ** (-10 / 20))
    assert analysis.s11_db(d.s11)[0] == pytest.approx(-10)


def test_s1p_rejects_other_extensions(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text(S1P_RI)
    with pytest.raises(ValueError, match=r"\.s1p"):
        read_s1p(f)


def test_s1p_uppercase_extension(tmp_path):
    f = tmp_path / "A.S1P"
    f.write_text(S1P_RI)
    assert len(read_s1p(f).freq_hz) == 2


def test_s11_at_interpolates(tmp_path):
    f = tmp_path / "a.s1p"
    f.write_text(S1P_RI)
    d = read_s1p(f)
    assert analysis.s11_at(d, 2.05e9) == pytest.approx(0.25 - 0.2j)


def test_bands_below():
    f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([-5.0, -15.0, -15.0, -5.0, -20.0])
    bands = analysis.bands_below(f, y, -10.0)
    assert bands == [(pytest.approx(1.5), pytest.approx(3.5)), (pytest.approx(4.0 + 5 / 15), 5.0)]


PATTERN = """GainT,,Gain:,3.0,,
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


@pytest.fixture
def pattern(tmp_path):
    f = tmp_path / "01-2400.000000MHz.csv"
    f.write_text(PATTERN)
    return read_pattern(f)


def test_freq_from_filename():
    assert freq_from_filename("01-2400.000000MHz.csv") == pytest.approx(2.4e9)
    assert freq_from_filename("x_2.45GHz.csv") == pytest.approx(2.45e9)
    assert freq_from_filename("nofreq.csv") is None


def test_pattern_parse(pattern):
    assert pattern.freq_hz == pytest.approx(2.4e9)
    assert pattern.pols == ["T", "H", "L"]
    assert pattern.peak_db == {"T": 3.0, "H": -1.0}
    assert pattern.gain_db["T"].shape == (3, 5)
    np.testing.assert_array_equal(pattern.theta_deg, [0, 90, 180])
    np.testing.assert_array_equal(pattern.phi_deg, [0, 90, 180, 270, 360])


def test_cut_phi_signed_angles(pattern):
    angle, g = analysis.cut_phi(pattern, "T", 0)
    np.testing.assert_array_equal(angle, [-180, -90, 0, 90, 180])
    # +angle = theta at phi=0, -angle = theta at phi=180
    np.testing.assert_allclose(g, [0, 4, 1, 2, 0])


def test_cut_phi_interpolates(pattern):
    _, g = analysis.cut_phi(pattern, "T", 45)  # halfway between phi=0 (2) and phi=90 (3) at theta=90
    assert g[3] == pytest.approx(2.5)


def test_cut_theta(pattern):
    phi, g = analysis.cut_theta(pattern, "T", 90)
    np.testing.assert_allclose(g, [2, 3, 4, 5, 2])


def test_peak_gain(pattern):
    assert analysis.peak_gain(pattern, "T") == (5.0, 90.0, 270.0)


def test_missing_frequency_needs_argument(tmp_path):
    f = tmp_path / "nofreq.csv"
    f.write_text(PATTERN)
    with pytest.raises(ValueError, match="frequency"):
        read_pattern(f)
    assert read_pattern(f, freq_hz=2.4e9).freq_hz == 2.4e9


# ---- smoothing --------------------------------------------------------------

def _loop(vals):
    return np.append(vals, vals[0])  # closed cut: last sample repeats the first


def test_smooth_off_returns_input():
    g = _loop(np.array([0.0, -3, -6, -3]))
    assert analysis.smooth_circular(g, 5, 0) is g
    assert analysis.smooth_circular(g, 5, 5) is g  # one-sample window


def test_smooth_constant_unchanged():
    g = _loop(np.full(36, -4.0))
    np.testing.assert_allclose(analysis.smooth_circular(g, 5, 30), g)


def test_smooth_linear_power_average_and_wrap():
    p = np.zeros(36)
    p[0] = 1.0  # one hot sample at the seam
    g = _loop(10 * np.log10(np.maximum(p, 1e-12)))
    out = analysis.smooth_circular(g, 5, 15)  # 3-sample window
    lin = 10 ** (out / 10)
    # the spike spreads to both neighbours, including across the wrap
    assert lin[0] == pytest.approx(1 / 3, rel=1e-6)
    assert lin[1] == pytest.approx(1 / 3, rel=1e-6)
    assert lin[35] == pytest.approx(1 / 3, rel=1e-6)
    assert out[-1] == out[0]  # still a closed loop


def test_smooth_window_larger_than_cut_is_safe():
    g = _loop(np.array([0.0, -3, -6, -3]))
    out = analysis.smooth_circular(g, 5, 720)
    assert out.shape == g.shape


def test_effective_window():
    assert analysis.effective_window_deg(5, 20) == 25  # 4 samples -> next odd, 5
    assert analysis.effective_window_deg(5, 15) == 15
    assert analysis.effective_window_deg(5, 0) == 0
    assert analysis.effective_window_deg(5, 4) == 0  # narrower than 2 samples: no smoothing


# ---- planes / orientation / colors --------------------------------------------

def test_plane_names():
    from antenna.models import PLANES, plane_name
    assert plane_name("theta", 90) == "XY"
    assert plane_name("phi", 0) == "XZ"
    assert plane_name("phi", 90.0) == "YZ"
    assert plane_name("phi", 45) is None
    assert plane_name("theta", 0) is None
    assert set(PLANES) == {"XY", "XZ", "YZ"}


def test_cut_orientation_and_colors(pattern):
    import matplotlib
    matplotlib.use("Agg")
    import numpy as np
    from antenna.plotting import make_cut_figure

    xy = make_cut_figure(pattern, "theta", 90, "polar").axes[0]
    assert xy.get_theta_direction() == 1  # counterclockwise
    assert xy.get_theta_offset() == pytest.approx(0.0)  # 0 deg at +X (right)
    assert "XY plane" in xy.get_title()

    xz = make_cut_figure(pattern, "phi", 0, "polar").axes[0]
    assert xz.get_theta_direction() == -1  # clockwise from the top
    assert xz.get_theta_offset() == pytest.approx(np.pi / 2)
    assert "XZ plane" in xz.get_title()

    colors = {line.get_label(): line.get_color() for line in xz.get_lines() if line.get_label()
              in ("H+V", "H")}
    assert colors == {"H+V": "#002060", "H": "#92D050"}


# ---- gain limit line / S11 markers ---------------------------------------------

def test_gain_limit_line_on_rect_plot(pattern):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.plotting import make_cut_figure

    def limit_lines(fig):
        return [ln for ln in fig.axes[0].get_lines() if ln.get_label() == "4 dB limit"]

    (line,) = limit_lines(make_cut_figure(pattern, "phi", 0, "rect"))  # on by default
    assert list(line.get_ydata()) == [4, 4]
    assert line.get_linestyle() == "--"
    assert not limit_lines(make_cut_figure(pattern, "phi", 0, "rect", gain_limit_db=None))
    assert not limit_lines(make_cut_figure(pattern, "phi", 0, "polar"))  # rect plots only


def test_gain_limit_stays_inside_axes(pattern):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.plotting import make_cut_figure

    ax = make_cut_figure(pattern, "phi", 0, "rect", gain_limit_db=12).axes[0]
    assert ax.get_ylim()[1] >= 12


def test_s11_marker_frequencies_are_labeled(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.models import WIFI_24_MARKS_MHZ
    from antenna.plotting import make_s11_figure

    f = tmp_path / "a.s1p"
    f.write_text("# MHz S RI R 50\n" + "".join(f"{m} {0.1 * (m - 2000) / 1000:g} 0\n"
                                               for m in range(2000, 3001, 50)))
    ax = make_s11_figure([read_s1p(f)], mark_mhz=list(WIFI_24_MARKS_MHZ)).axes[0]
    labels = [t.get_text() for t in ax.texts]
    for freq in ("2400 MHz", "2442 MHz", "2483 MHz"):
        assert any(text.startswith(freq) and text.endswith(" dB") for text in labels)
    assert WIFI_24_MARKS_MHZ == (2400.0, 2442.0, 2483.0)


# ---- user feedback / error messages / startup ------------------------------------

def test_say_format(capsys):
    import re
    from antenna.feedback import say
    say("hello")
    assert re.fullmatch(r"\[\s*\d+\.\ds\] hello\n", capsys.readouterr().out)


def test_slow_load_tip(capsys):
    from antenna.feedback import SLOW_LOAD_SECONDS, tip_if_slow
    tip_if_slow(SLOW_LOAD_SECONDS - 1)
    assert capsys.readouterr().out == ""
    tip_if_slow(SLOW_LOAD_SECONDS + 1)
    assert "Google Drive" in capsys.readouterr().out


def test_folder_without_csvs_points_to_subfolders(tmp_path):
    from antenna.readers.pattern import find_pattern_files
    sub = tmp_path / "01_pattern"
    sub.mkdir()
    (sub / "01-2400.000000MHz.csv").write_text(PATTERN)
    with pytest.raises(FileNotFoundError, match="01_pattern"):
        find_pattern_files([tmp_path])
    assert len(find_pattern_files([sub])) == 1


def test_missing_inputs_raise_clear_errors(tmp_path):
    from antenna.readers.pattern import find_pattern_files
    with pytest.raises(FileNotFoundError, match="no file or folder matches"):
        find_pattern_files([tmp_path / "nope*.csv"])
    with pytest.raises(FileNotFoundError, match="file not found"):
        read_s1p(tmp_path / "missing.s1p")


def test_load_patterns_reports_progress(tmp_path):
    from antenna.readers import load_patterns
    for mhz in (2450, 2400):
        (tmp_path / f"01-{mhz}.000000MHz.csv").write_text(PATTERN)
    calls = []
    patterns = load_patterns([tmp_path], on_file=lambda i, n, p: calls.append((i, n, p.name)))
    assert calls == [(1, 2, "01-2400.000000MHz.csv"), (2, 2, "01-2450.000000MHz.csv")]
    assert [p.freq_hz for p in patterns] == [2.4e9, 2.45e9]  # still sorted by frequency


def test_path_checks_do_not_import_heavy_libraries():
    """Scripts validate paths before the slow library load, so these imports must stay light."""
    import subprocess
    import sys
    code = ("import sys; import antenna.models, antenna.feedback, antenna.readers; "
            "from antenna.readers.pattern import find_pattern_files, freq_from_filename; "
            "print([m for m in ('numpy', 'scipy', 'matplotlib', 'skrf') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "[]", out.stderr or out.stdout


# ---- axis limits / line width ---------------------------------------------------

def test_limits_rules():
    import numpy as np
    from antenna.plotting import _limits
    g = {"a": np.array([-10.0, 2.1])}  # auto top = 5
    assert _limits(g, 40) == (-35, 5)
    assert _limits(g, 40, rmax=0) == (-40, 0)  # lone rmax: floor follows --range
    assert _limits(g, 40, rmin=-30) == (-30, 5)  # lone rmin: top stays automatic
    assert _limits(g, 40, rmin=-45, rmax=5) == (-45, 5)
    with pytest.raises(ValueError, match="below rmax"):
        _limits(g, 40, rmin=6)
    with pytest.raises(ValueError, match="below rmax"):
        _limits(g, 40, rmin=-5, rmax=-5)


def test_explicit_limits_reach_both_plot_types(pattern):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.plotting import make_cut_figure

    rect = make_cut_figure(pattern, "phi", 0, "rect", rmin=-45, rmax=3).axes[0]
    assert rect.get_ylim() == (-45, 3)  # explicit top wins even though the 4 dB line is above it
    polar = make_cut_figure(pattern, "phi", 0, "polar", rmin=-45, rmax=5).axes[0]
    assert (polar.get_rmin(), polar.get_rmax()) == (-45, 5)


def test_traces_are_thick(pattern):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.plotting import TRACE_LINEWIDTH, make_cut_figure

    for kind in ("polar", "rect"):
        ax = make_cut_figure(pattern, "phi", 0, kind).axes[0]
        widths = [ln.get_linewidth() for ln in ax.get_lines() if ln.get_label() in ("H+V", "H")]
        assert widths == [TRACE_LINEWIDTH] * 2
    assert TRACE_LINEWIDTH >= 2.5


# ---- S11 band shading / y limits / pattern text sizes --------------------------------

def _s11_series(tmp_path):
    f = tmp_path / "a.s1p"
    f.write_text("# MHz S RI R 50\n" + "".join(f"{m} {0.05 + 0.1 * abs(m - 2450) / 1000:g} 0\n"
                                               for m in range(2000, 3001, 25)))
    return [read_s1p(f)]


def test_s11_shades_wifi_band_with_legend_entry(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.models import WIFI_24_BAND_LABEL, WIFI_24_BAND_MHZ
    from antenna.plotting import make_s11_figure

    ax = make_s11_figure(_s11_series(tmp_path)).axes[0]
    (span,) = ax.patches  # exactly one shaded region: the Wi-Fi band, not where S11 crosses -10 dB
    assert (span.get_x(), span.get_x() + span.get_width()) == pytest.approx(WIFI_24_BAND_MHZ)
    assert WIFI_24_BAND_LABEL in [t.get_text() for t in ax.get_legend().get_texts()]


def test_s11_custom_and_disabled_band(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.plotting import make_s11_figure

    series = _s11_series(tmp_path)
    ax = make_s11_figure(series, band_mhz=(2412, 2472)).axes[0]
    assert "2412-2472 MHz band" in [t.get_text() for t in ax.get_legend().get_texts()]
    assert len(make_s11_figure(series, band_mhz=None).axes[0].patches) == 0


def test_s11_y_limits(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.plotting import make_s11_figure

    series = _s11_series(tmp_path)
    assert make_s11_figure(series, ymin=-25, ymax=0).axes[0].get_ylim() == (-25, 0)
    assert make_s11_figure(series, ymax=3).axes[0].get_ylim()[1] == 3  # bottom stays automatic
    with pytest.raises(ValueError, match="below ymax"):
        make_s11_figure(series, ymin=50)


def test_polar_ticks_every_10_degrees_and_larger_text(pattern):
    import matplotlib
    matplotlib.use("Agg")
    from antenna.plotting import (LABEL_FONTSIZE, LEGEND_FONTSIZE, POLAR_TICK_FONTSIZE,
                                  TICK_FONTSIZE, TITLE_FONTSIZE, make_cut_figure)

    polar = make_cut_figure(pattern, "phi", 0, "polar")
    ax = polar.axes[0]
    assert len(ax.get_xticks()) == 36  # 0, 10, ..., 350
    assert ax.get_xticklabels()[0].get_fontsize() == POLAR_TICK_FONTSIZE
    assert ax.title.get_fontsize() == TITLE_FONTSIZE
    assert polar.legends[0].get_texts()[0].get_fontsize() == LEGEND_FONTSIZE

    rect = make_cut_figure(pattern, "phi", 0, "rect")
    ax = rect.axes[0]
    assert ax.get_xlabel() and ax.xaxis.label.get_fontsize() == LABEL_FONTSIZE
    assert ax.yaxis.label.get_fontsize() == LABEL_FONTSIZE
    assert ax.get_xticklabels()[0].get_fontsize() == TICK_FONTSIZE
    assert ax.get_legend().get_texts()[0].get_fontsize() == LEGEND_FONTSIZE
    assert min(TICK_FONTSIZE, POLAR_TICK_FONTSIZE, LABEL_FONTSIZE, LEGEND_FONTSIZE) > 10  # was default


# ---- gain tables ------------------------------------------------------------------

def _pole_pattern(pole_row):
    """T table: theta 0 / 90 / 180 rows on a 90-degree phi grid; the +Z pole varies with phi."""
    import numpy as np
    from antenna.models import Pattern
    gain = np.array([pole_row, [2, 3, 4, 5, 2], [0, 0, 0, 0, 0]], dtype=float)
    return Pattern(freq_hz=2.45e9, theta_deg=np.array([0.0, 90, 180]),
                   phi_deg=np.array([0.0, 90, 180, 270, 360]), gain_db={"T": gain}, name="p")


def test_gain_at_grid_points_and_poles(pattern):
    assert analysis.gain_at(pattern, "T", 90, 180) == 4  # a measured grid point
    assert analysis.gain_at(pattern, "T", 90, 45) == pytest.approx(2.5)  # between grid points
    assert analysis.gain_at(pattern, "T", 0, None) == pytest.approx(1.0)  # constant pole row
    with pytest.raises(ValueError, match="outside the measured range"):
        analysis.gain_at(pattern, "T", 200, 0)


def test_pole_gain_is_power_average_over_phi():
    import numpy as np
    p = _pole_pattern([1, 3, 1, 3, 1])  # phi=360 repeats phi=0
    expected = 10 * np.log10(np.mean(10 ** (np.array([1, 3, 1, 3]) / 10)))
    assert analysis.gain_at(p, "T", 0, None) == pytest.approx(expected)
    assert analysis.phi_spread_db(p, "T", 0) == pytest.approx(2.0)
    assert analysis.phi_spread_db(p, "T", 180) == 0


def test_summary_row_values(pattern):
    from antenna.tables import COLUMNS, summary_row
    row = summary_row(pattern)
    assert (row["peak_gain_dBi"], row["peak_theta_deg"], row["peak_phi_deg"]) == (5, 90, 270)
    assert row["peak_direction"] == "Front"  # theta 90, phi 270 is -Y
    assert (row["Right(+X)_gain_dBi"], row["Left(-X)_gain_dBi"]) == (2, 4)  # theta 90, phi 0 / 180
    assert (row["Rear(+Y)_gain_dBi"], row["Front(-Y)_gain_dBi"]) == (3, 5)  # phi 90 / 270
    assert row["Top(+Z)_gain_dBi"] == pytest.approx(1.0)
    assert row["Bottom(-Z)_gain_dBi"] == pytest.approx(0.0)
    assert row["freq_MHz"] == pytest.approx(2400)
    assert all(c in row for c in COLUMNS)


def test_summary_needs_total_table(pattern):
    from antenna.tables import summary_row
    del pattern.gain_db["T"]
    with pytest.raises(ValueError, match="no GainT table"):
        summary_row(pattern)


def test_pole_note_only_when_variation_is_noticeable(pattern):
    from antenna.tables import pole_note, summary_row
    assert pole_note([summary_row(pattern)]) is None  # constant poles: nothing to say
    note = pole_note([summary_row(_pole_pattern([1, 3, 1, 3, 1]))])
    assert "2.0 dB" in note and "power average" in note


def test_csv_and_terminal_table(tmp_path, pattern):
    import csv
    from antenna.tables import COLUMNS, format_table, summary_rows, write_csv
    rows = summary_rows([pattern])
    out = write_csv(rows, tmp_path / "sub" / "summary.csv")  # creates the folder
    lines = list(csv.reader(open(out, newline="")))
    assert lines[0] == COLUMNS
    assert lines[0][0] == "freq_MHz" and not any(c[0] in "+-" for c in lines[0])  # Excel-safe
    assert lines[0][4] == "peak_direction"
    assert lines[0][5:11] == ["Front(-Y)_gain_dBi", "Rear(+Y)_gain_dBi", "Right(+X)_gain_dBi",
                              "Left(-X)_gain_dBi", "Top(+Z)_gain_dBi", "Bottom(-Z)_gain_dBi"]
    # Front, Rear, Right, Left, Top, Bottom
    assert lines[1][:11] == ["2400", "5.00", "90", "270", "Front", "5.00", "3.00", "2.00", "4.00",
                             "1.00", "0.00"]
    assert lines[0][11:17] == ["Front(-Y)_half_avg_dBi", "Rear(+Y)_half_avg_dBi",
                               "Right(+X)_half_avg_dBi", "Left(-X)_half_avg_dBi",
                               "Top(+Z)_half_avg_dBi", "Bottom(-Z)_half_avg_dBi"]
    expected = [f"{analysis.hemisphere_gain(pattern, 'T', axis):.2f}"
                for axis in ("Y-", "Y+", "X+", "X-", "Z+", "Z-")]
    assert lines[1][11:17] == expected and len(lines[1]) == len(COLUMNS)
    assert lines[0][17:] == ["Front_minus_Rear_dB", "Right_minus_Left_dB", "Top_minus_Bottom_dB",
                             "efficiency_from_gain_pct"]
    assert "MHz" in format_table(rows).splitlines()[0]


# ---- device orientation labels -------------------------------------------------------

@pytest.mark.parametrize("theta, phi, expected", [
    (135, 240, "Bottom-Front-Left"),  # the sample data's peak
    (135, 225, "Bottom-Front-Left"),  # exactly between -X and -Y: the quadrant decides
    (45, 45, "Top-Rear-Right"),
    (45, 135, "Top-Rear-Left"),
    (90, 270, "Front"), (90, 90, "Rear"), (90, 0, "Right"), (90, 180, "Left"),
    (90, 360, "Right"),  # phi wraps
    (90, 100, "Rear"),  # within 22.5 deg of +Y, on the horizon: one side, no Top/Bottom word
    (100, 300, "Front-Right"),  # on the horizon but between axes
    (60, 350, "Top-Right"),  # near +X: one horizontal side plus Top
    (0, 123, "Top"), (10, 45, "Top"), (180, 0, "Bottom"), (170, 200, "Bottom"),
    (22.5, 90, "Top"),  # the tolerance is inclusive
])
def test_direction_label(theta, phi, expected):
    assert analysis.direction_label(theta, phi) == expected


def test_direction_label_follows_orientation_and_checks_range():
    turned = {"Front": "X+", "Rear": "X-", "Right": "Y+", "Left": "Y-", "Top": "Z+", "Bottom": "Z-"}
    assert analysis.direction_label(90, 0, turned) == "Front"
    assert analysis.direction_label(135, 45, turned) == "Bottom-Right-Front"  # Y-axis side first
    with pytest.raises(ValueError, match="theta"):
        analysis.direction_label(200, 0)


def test_orientation_is_complete_and_matches_the_requested_sides():
    from antenna.models import DIRECTIONS, ORIENTATION
    assert sorted(ORIENTATION.values()) == sorted(DIRECTIONS)  # each axis direction used once
    assert list(ORIENTATION) == ["Front", "Rear", "Right", "Left", "Top", "Bottom"]
    assert ORIENTATION == {"Front": "Y-", "Rear": "Y+", "Right": "X+", "Left": "X-",
                           "Top": "Z+", "Bottom": "Z-"}


def test_peak_direction_at_a_pole_and_pole_spread_uses_labels():
    from antenna.tables import POLE_LABELS, summary_row
    import numpy as np
    from antenna.models import Pattern
    gain = np.array([[9.0, 9, 9, 9, 9], [2, 3, 4, 5, 2], [0, 0, 0, 0, 0]])
    p = Pattern(freq_hz=2.45e9, theta_deg=np.array([0.0, 90, 180]),
                phi_deg=np.array([0.0, 90, 180, 270, 360]), gain_db={"T": gain}, name="p")
    row = summary_row(p)
    assert row["peak_direction"] == "Top"
    assert POLE_LABELS == ["Top", "Bottom"]
    assert "Top_phi_spread_dB" in row and "Bottom_phi_spread_dB" in row


def test_orientation_note_and_terminal_header():
    from antenna.tables import orientation_note
    assert orientation_note().startswith("Sides: Front = -Y, Rear = +Y, Right = +X, Left = -X")
    assert "Top = +Z, Bottom = -Z" in orientation_note()


def test_terminal_table_has_labels_axes_and_left_aligned_direction(pattern):
    from antenna.tables import format_table, pole_note, summary_rows
    head1, head2, first = format_table(summary_rows([pattern])).splitlines()
    for label in ("Front", "Rear", "Right", "Left", "Top", "Bottom", "Peak direction"):
        assert label in head1
    for axis in ("(-Y)", "(+Y)", "(+X)", "(-X)", "(+Z)", "(-Z)"):
        assert axis in head2
    assert head1.index("Peak direction") == first.index("Front")  # left-aligned under its header
    note = pole_note(summary_rows([_pole_pattern([1, 3, 1, 3, 1])]))
    assert "Top and Bottom" in note and "(+Z" not in note


# ---- half-sphere average gain ---------------------------------------------------------

def _grid_pattern(theta, phi, gain):
    import numpy as np
    from antenna.models import Pattern
    return Pattern(freq_hz=2.45e9, theta_deg=np.array(theta, dtype=float),
                   phi_deg=np.array(phi, dtype=float), gain_db={"T": np.array(gain, dtype=float)},
                   name="p")


def test_hemisphere_gain_of_a_constant_pattern_is_that_constant():
    p = _grid_pattern([0, 45, 90, 135, 180], [0, 90, 180, 270, 360], [[3.0] * 5] * 5)
    for axis in ("X+", "X-", "Y+", "Y-", "Z+", "Z-"):
        assert analysis.hemisphere_gain(p, "T", axis) == pytest.approx(3.0)


def test_hemisphere_gain_top_bottom_uses_sin_weights_power_average_and_half_equator():
    import numpy as np
    # 10 dB on the top rows, 0 dB elsewhere; the equator row (theta 90) is 0 dB, counted half
    # in each hemisphere. Constant in phi, so only the theta weights matter (theta=0 has weight 0).
    rows = [[10.0] * 5, [10.0] * 5, [0.0] * 5, [0.0] * 5, [0.0] * 5]
    p = _grid_pattern([0, 45, 90, 135, 180], [0, 90, 180, 270, 360], rows)
    s45 = np.sin(np.deg2rad(45))
    top = 10 * np.log10((10 * s45 + 1 * 0.5) / (s45 + 0.5))
    assert analysis.hemisphere_gain(p, "T", "Z+") == pytest.approx(top)
    assert analysis.hemisphere_gain(p, "T", "Z-") == pytest.approx(0.0)  # only 0 dB points
    assert top > 10 * s45 / (s45 + 0.5)  # a plain average of the dB values would come out lower


def test_hemisphere_gain_left_right_and_front_rear_boundaries_count_half():
    import numpy as np
    # Gain depends on phi only: 10 dB at phi = 0 and its closing copy 360, else 0 dB.
    row = [10.0, 0, 0, 0, 10.0]
    p = _grid_pattern([0, 45, 90, 135, 180], [0, 90, 180, 270, 360], [row] * 5)
    assert analysis.hemisphere_gain(p, "T", "X+") == pytest.approx(10 * np.log10(5.5))
    assert analysis.hemisphere_gain(p, "T", "X-") == pytest.approx(0.0)
    third = 10 * np.log10(3.25)  # +Y and -Y each contain half of the phi=0/360 and phi=180 columns
    assert analysis.hemisphere_gain(p, "T", "Y+") == pytest.approx(third)
    assert analysis.hemisphere_gain(p, "T", "Y-") == pytest.approx(third)


def test_hemisphere_gain_checks_inputs():
    p = _grid_pattern([0, 90, 180], [0, 90, 180, 270, 360], [[0.0] * 5] * 3)
    with pytest.raises(ValueError, match="axis"):
        analysis.hemisphere_gain(p, "T", "W+")
    with pytest.raises(ValueError, match="axis"):
        analysis.hemisphere_gain(p, "T", "Front")
    partial = _grid_pattern([0, 90], [0, 90, 180, 270, 360], [[0.0] * 5] * 2)
    with pytest.raises(ValueError, match="full-sphere"):
        analysis.hemisphere_gain(partial, "T", "Z+")
    half_turn = _grid_pattern([0, 90, 180], [0, 90, 180], [[0.0] * 3] * 3)
    with pytest.raises(ValueError, match="full-sphere"):
        analysis.hemisphere_gain(half_turn, "T", "Z+")


def test_half_sphere_terminal_table(pattern):
    from antenna.tables import format_half_table, summary_rows
    head1, head2, first = format_half_table(summary_rows([pattern])).splitlines()
    for label in ("MHz", "Front", "Rear", "Right", "Left", "Top", "Bottom"):
        assert label in head1
    for axis in ("(-Y)", "(+Y)", "(+X)", "(-X)", "(+Z)", "(-Z)"):
        assert axis in head2
    assert "Peak" not in head1  # only the half-sphere columns
    assert len(first.split()) == 7  # frequency plus six sides


# ---- summary numbers and efficiency ------------------------------------------------------

def test_mean_gain_linear_constant_and_consistency(pattern):
    import numpy as np
    const = _grid_pattern([0, 45, 90, 135, 180], [0, 90, 180, 270, 360], [[3.0] * 5] * 5)
    assert analysis.mean_gain_linear(const, "T") == pytest.approx(10 ** 0.3)
    # the whole sphere is the two halves of equal solid angle, so its mean is their average
    halves = [10 ** (analysis.hemisphere_gain(pattern, "T", a) / 10) for a in ("Z+", "Z-")]
    assert analysis.mean_gain_linear(pattern, "T") == pytest.approx(np.mean(halves))
    for axis_pair in (("X+", "X-"), ("Y+", "Y-")):
        halves = [10 ** (analysis.hemisphere_gain(pattern, "T", a) / 10) for a in axis_pair]
        assert analysis.mean_gain_linear(pattern, "T") == pytest.approx(np.mean(halves))


def test_mean_gain_needs_a_full_sphere():
    partial = _grid_pattern([0, 90], [0, 90, 180, 270, 360], [[0.0] * 5] * 2)
    with pytest.raises(ValueError, match="whole-sphere average needs a full-sphere"):
        analysis.mean_gain_linear(partial, "T")


def test_summary_row_differences_and_efficiency(pattern):
    from antenna.tables import DIFF_COLUMNS, EFFICIENCY_COLUMN, HALF_COLUMNS, summary_row
    row = summary_row(pattern)
    for (a, b), column in DIFF_COLUMNS.items():
        assert row[column] == pytest.approx(row[HALF_COLUMNS[a]] - row[HALF_COLUMNS[b]])
    assert list(DIFF_COLUMNS.values()) == ["Front_minus_Rear_dB", "Right_minus_Left_dB",
                                           "Top_minus_Bottom_dB"]
    assert row[EFFICIENCY_COLUMN] == pytest.approx(100 * analysis.mean_gain_linear(pattern, "T"))


def test_opposite_sides_really_are_opposite_axes():
    from antenna.models import OPPOSITE_SIDES, ORIENTATION
    used = [side for pair in OPPOSITE_SIDES for side in pair]
    assert sorted(used) == sorted(ORIENTATION)  # every side appears exactly once
    for first, second in OPPOSITE_SIDES:
        a, b = ORIENTATION[first], ORIENTATION[second]
        assert a[0] == b[0] and a[1] != b[1]  # same axis letter, opposite sign


def test_summary_note_warns_about_efficiency_above_100_percent():
    from antenna.tables import summary_note, summary_rows
    grid = ([0, 45, 90, 135, 180], [0, 90, 180, 270, 360])
    high = summary_rows([_grid_pattern(*grid, [[3.0] * 5] * 5)])   # +3 dBi everywhere: 199.5%
    low = summary_rows([_grid_pattern(*grid, [[-3.0] * 5] * 5)])   # -3 dBi everywhere: 50.1%
    assert high[0]["efficiency_from_gain_pct"] == pytest.approx(199.53, abs=0.01)
    assert low[0]["efficiency_from_gain_pct"] == pytest.approx(50.12, abs=0.01)
    assert "WARNING" in summary_note(high) and "not physical" in summary_note(high)
    assert "WARNING" not in summary_note(low)
    assert "positive = the first side is stronger" in summary_note(low)


def test_summary_terminal_table(pattern):
    from antenna.tables import format_summary_table, summary_rows
    head1, head2, first = format_summary_table(summary_rows([pattern])).splitlines()
    for label in ("MHz", "Front-Rear", "Right-Left", "Top-Bottom", "Efficiency"):
        assert label in head1
    assert head2.split() == ["dB", "dB", "dB", "%"]
    assert len(first.split()) == 5  # frequency, three differences, efficiency
