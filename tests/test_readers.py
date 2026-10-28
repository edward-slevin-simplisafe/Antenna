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
