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
