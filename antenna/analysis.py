"""Pure numeric helpers: no file I/O, no plotting."""

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from antenna.models import Pattern, S11Data


# ---- S11 -------------------------------------------------------------------

def s11_db(s11: np.ndarray) -> np.ndarray:
    """|S11| in dB (negative; return loss is the same number with the sign flipped)."""
    return 20 * np.log10(np.maximum(np.abs(s11), 1e-12))


def vswr(s11: np.ndarray) -> np.ndarray:
    gamma = np.minimum(np.abs(s11), 1 - 1e-12)
    return (1 + gamma) / (1 - gamma)


def bands_below(freq_hz: np.ndarray, y_db: np.ndarray, threshold_db: float = -10.0):
    """Contiguous (f_lo, f_hi) ranges where y_db <= threshold, edges linearly interpolated.

    A band that touches the first/last sample is cut at that sample.
    """
    below = y_db <= threshold_db
    bands = []
    start = None
    for k in range(len(freq_hz)):
        if below[k] and start is None:
            start = freq_hz[k] if k == 0 else _crossing(freq_hz, y_db, k - 1, k, threshold_db)
        elif not below[k] and start is not None:
            bands.append((start, _crossing(freq_hz, y_db, k - 1, k, threshold_db)))
            start = None
    if start is not None:
        bands.append((start, freq_hz[-1]))
    return bands


def s11_at(data: S11Data, freq_hz: float) -> complex:
    """Complex S11 at freq_hz, linearly interpolated (real and imaginary parts separately)."""
    return complex(
        np.interp(freq_hz, data.freq_hz, data.s11.real),
        np.interp(freq_hz, data.freq_hz, data.s11.imag),
    )


def _crossing(x, y, k0, k1, level):
    return x[k0] + (level - y[k0]) * (x[k1] - x[k0]) / (y[k1] - y[k0])


# ---- Radiation patterns ----------------------------------------------------

def _interpolator(pattern: Pattern, pol: str) -> RegularGridInterpolator:
    return RegularGridInterpolator(
        (pattern.theta_deg, pattern.phi_deg), pattern.gain_db[pol], method="linear"
    )


def _wrap_phi(pattern: Pattern, phi_deg):
    """Map phi into the grid's own 360-degree window (e.g. 0..360)."""
    lo = pattern.phi_deg[0]
    return lo + (np.asarray(phi_deg, dtype=float) - lo) % 360.0


def cut_phi(pattern: Pattern, pol: str, phi_deg: float):
    """Great-circle cut at fixed phi, sweeping theta.

    Returns (angle_deg, gain_db) with angle running -180..180: positive angles are
    theta on the phi side, negative angles are theta on the phi+180 side.
    """
    interp = _interpolator(pattern, pol)
    theta = pattern.theta_deg
    g_pos = interp(np.column_stack([theta, np.full_like(theta, _wrap_phi(pattern, phi_deg))]))
    g_neg = interp(
        np.column_stack([theta, np.full_like(theta, _wrap_phi(pattern, phi_deg + 180.0))])
    )
    angle = np.concatenate([-theta[::-1], theta])
    gain = np.concatenate([g_neg[::-1], g_pos])
    if theta[0] == 0:  # theta=0 appears on both sides; keep one copy
        keep = np.ones(len(angle), bool)
        keep[len(theta) - 1] = False
        angle, gain = angle[keep], gain[keep]
    return angle, gain


def cut_theta(pattern: Pattern, pol: str, theta_deg: float):
    """Conical cut at fixed theta, sweeping phi. Returns (phi_deg, gain_db)."""
    interp = _interpolator(pattern, pol)
    phi = pattern.phi_deg
    gain = interp(np.column_stack([np.full_like(phi, theta_deg), phi]))
    return phi, gain


def _window_samples(step_deg: float, window_deg: float) -> int:
    n = int(round(window_deg / step_deg))
    return n + (n % 2 == 0)  # odd, so the window stays centered on a sample


def effective_window_deg(step_deg: float, window_deg: float) -> float:
    """Width actually averaged by smooth_circular (0 if it would do nothing)."""
    n = _window_samples(step_deg, window_deg)
    return n * step_deg if window_deg > 0 and n > 1 else 0.0


def smooth_circular(gain_db: np.ndarray, step_deg: float, window_deg: float) -> np.ndarray:
    """Sliding-window average of a closed angular cut (first sample == last sample).

    The average is taken in linear power, not dB, and wraps around the seam. The window is
    rounded to an odd number of samples so it stays centered; window_deg <= 0, or a window
    narrower than two samples, returns the input unchanged. Smoothing lowers peaks and fills nulls.
    """
    n = _window_samples(step_deg, window_deg)
    loop = gain_db[:-1]
    n = min(n, len(loop) - (len(loop) % 2 == 0))
    if window_deg <= 0 or n <= 1:
        return gain_db
    pad = n // 2
    power = 10 ** (loop / 10)
    ext = np.concatenate([power[-pad:], power, power[:pad]])
    smooth = np.convolve(ext, np.ones(n) / n, mode="valid")
    out = 10 * np.log10(smooth)
    return np.append(out, out[0])


def peak_gain(pattern: Pattern, pol: str):
    """(gain_db, theta_deg, phi_deg) of the maximum grid point."""
    g = pattern.gain_db[pol]
    it, ip = np.unravel_index(np.argmax(g), g.shape)
    return float(g[it, ip]), float(pattern.theta_deg[it]), float(pattern.phi_deg[ip])
