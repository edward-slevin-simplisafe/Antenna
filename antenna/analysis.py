"""Pure numeric helpers: no file I/O, no plotting."""

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from antenna.models import DIRECTION_TOLERANCE_DEG, ORIENTATION, Pattern, S11Data


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


def _phi_samples(pattern: Pattern, pol: str, theta_deg: float) -> np.ndarray:
    """Gain (dB) around the full phi circle at fixed theta, without the repeated closing sample."""
    phi, gain = cut_theta(pattern, pol, theta_deg)
    return gain[:-1] if phi[-1] - phi[0] >= 360.0 - 1e-9 else gain


def gain_at(pattern: Pattern, pol: str, theta_deg: float, phi_deg: float | None) -> float:
    """Gain (dB) in one direction: exactly the measured value at a grid point, linearly
    interpolated between grid points. phi_deg=None gives the power average over all phi
    (for the poles, where phi has no meaning)."""
    lo, hi = pattern.theta_deg[0], pattern.theta_deg[-1]
    if not lo <= theta_deg <= hi:
        raise ValueError(f"{pattern.name}: theta={theta_deg:g} is outside the measured "
                         f"range {lo:g} to {hi:g}")
    if phi_deg is None:
        return float(10 * np.log10(np.mean(10 ** (_phi_samples(pattern, pol, theta_deg) / 10))))
    point = [[theta_deg, float(_wrap_phi(pattern, phi_deg))]]
    return float(_interpolator(pattern, pol)(point)[0])


def phi_spread_db(pattern: Pattern, pol: str, theta_deg: float) -> float:
    """Max minus min gain (dB) around the phi circle at fixed theta; 0 for an ideal pole."""
    samples = _phi_samples(pattern, pol, theta_deg)
    return float(samples.max() - samples.min())


def _trapezoid_weights(x: np.ndarray) -> np.ndarray:
    """Trapezoid-rule weights for samples at ascending positions x."""
    w = np.zeros(len(x))
    half_gaps = np.diff(x) / 2
    w[:-1] += half_gaps
    w[1:] += half_gaps
    return w


def hemisphere_gain(pattern: Pattern, pol: str, axis: str) -> float:
    """Average gain (dB) over the half of the sphere facing an axis direction such as 'Y-'.

    Every measured point is weighted by the solid angle it stands for (sin(theta) times the grid
    spacing), because points near the poles cover much less area than points near the equator.
    The average is taken in linear power and converted back to dB, so deep nulls do not drag it
    down the way an average of dB values would. Points exactly on the dividing circle count half
    in each hemisphere, which is exact when the grid spacing divides 90 degrees (a 5 degree grid
    does). Needs a full-sphere measurement (theta 0 to 180, phi spanning 360 degrees).
    """
    if len(axis) != 2 or axis[0] not in "XYZ" or axis[1] not in "+-":
        raise ValueError(f"axis must look like 'X+' or 'Y-', not {axis!r}")
    theta, phi, area = _sphere_grid(pattern, "a half-sphere average")
    component = {"X": np.sin(theta) * np.cos(phi), "Y": np.sin(theta) * np.sin(phi),
                 "Z": np.cos(theta) * np.ones_like(phi)}[axis[0]]
    facing = component if axis[1] == "+" else -component
    membership = np.where(facing > 1e-9, 1.0, np.where(facing >= -1e-9, 0.5, 0.0))
    weight = area * membership
    power = 10 ** (pattern.gain_db[pol] / 10)
    return float(10 * np.log10((power * weight).sum() / weight.sum()))


def mean_gain_linear(pattern: Pattern, pol: str) -> float:
    """Average of the linear gain over the whole sphere (area-weighted), as a plain ratio.

    For absolute gain, meaning gain referenced to the power fed to the antenna, this equals the
    fraction of that power that is radiated, i.e. the antenna efficiency. For a gain pattern that
    is only normalized (for example to its peak) it means nothing of the sort.
    """
    _, _, area = _sphere_grid(pattern, "a whole-sphere average")
    power = 10 ** (pattern.gain_db[pol] / 10)
    return float((power * area).sum() / area.sum())


def _sphere_grid(pattern: Pattern, what: str):
    """(theta, phi, area) for a full-sphere pattern: theta as a column and phi as a row of angles
    in radians, and the solid-angle weight of each grid point (sin(theta) times the spacing)."""
    theta_deg, phi_deg = pattern.theta_deg, pattern.phi_deg
    if theta_deg[0] > 1e-9 or theta_deg[-1] < 180 - 1e-9 or phi_deg[-1] - phi_deg[0] < 360 - 1e-9:
        raise ValueError(f"{pattern.name}: {what} needs a full-sphere measurement "
                         "(theta 0 to 180 and phi spanning 360 degrees)")
    theta = np.deg2rad(theta_deg)[:, None]
    phi = np.deg2rad(phi_deg)[None, :]
    area = (np.sin(theta[:, 0]) * _trapezoid_weights(theta[:, 0]))[:, None] \
        * _trapezoid_weights(phi[0])[None, :]
    return theta, phi, area


def peak_gain(pattern: Pattern, pol: str):
    """(gain_db, theta_deg, phi_deg) of the maximum grid point."""
    g = pattern.gain_db[pol]
    it, ip = np.unravel_index(np.argmax(g), g.shape)
    return float(g[it, ip]), float(pattern.theta_deg[it]), float(pattern.phi_deg[ip])


def direction_label(theta_deg: float, phi_deg: float, orientation: dict[str, str] = ORIENTATION,
                    tol_deg: float = DIRECTION_TOLERANCE_DEG) -> str:
    """Name a (theta, phi) direction by the device's sides, e.g. 'Bottom-Front-Left'.

    Theta picks Top (above the horizon) or Bottom, and phi picks the quadrant of the horizontal
    plane: +X..+Y, +Y..-X, -X..-Y or -Y..+X. A direction within tol_deg of an axis is named by
    that axis alone: near a pole just Top or Bottom, near the horizon no Top/Bottom word, and
    near +/-X or +/-Y a single side. In a two-side name the one on the Y axis comes first.

    orientation maps each side name to an axis direction ('Front' -> 'Y-'), as in
    antenna.models.ORIENTATION. Theta runs from +Z and phi from +X toward +Y.
    """
    if not 0 <= theta_deg <= 180:
        raise ValueError(f"theta={theta_deg:g} is outside 0 to 180")
    side = {axis: name for name, axis in orientation.items()}
    if theta_deg <= tol_deg:
        return side["Z+"]
    if theta_deg >= 180 - tol_deg:
        return side["Z-"]

    parts = []
    if theta_deg < 90 - tol_deg:
        parts.append(side["Z+"])
    elif theta_deg > 90 + tol_deg:
        parts.append(side["Z-"])

    phi = phi_deg % 360
    axes = ["X+", "Y+", "X-", "Y-"]  # at phi = 0, 90, 180, 270
    nearest = round(phi / 90)
    if abs(phi - 90 * nearest) <= tol_deg:
        parts.append(side[axes[nearest % 4]])
    else:
        quadrant = int(phi // 90)
        pair = [axes[quadrant], axes[(quadrant + 1) % 4]]
        parts += [side[ax] for ax in sorted(pair, key=lambda ax: ax[0] != "Y")]
    return "-".join(parts)


def match_by_frequency(pattern_sets: list[list[Pattern]], labels: list[str],
                       tol_mhz: float = 0.5):
    """Group the patterns of several datasets that were measured at the same frequency.

    pattern_sets holds one list of patterns per dataset and labels names each dataset. A pattern
    matches one in another set if their frequencies are within tol_mhz. Returns (groups, skipped):
    groups is a list of (freq_MHz, [one pattern per dataset, in dataset order]) sorted by frequency
    (the frequency of the first dataset's pattern), and skipped maps each label to the frequencies
    (MHz) of its patterns that are not present in every dataset. Raises ValueError if a dataset has
    two patterns within tol_mhz of each other, since they could not be paired reliably.
    """
    if len(pattern_sets) != len(labels):
        raise ValueError("one label per dataset is needed")
    mhz = [[p.freq_hz / 1e6 for p in patterns] for patterns in pattern_sets]
    for label, freqs in zip(labels, mhz):
        ordered = sorted(freqs)
        for a, b in zip(ordered, ordered[1:]):
            if b - a <= tol_mhz:
                raise ValueError(f"{label}: two files at {a:g} and {b:g} MHz cannot be told apart")

    groups, used = [], [set() for _ in pattern_sets]
    for i, ref in enumerate(pattern_sets[0]):
        members, indices = [ref], [i]
        for k in range(1, len(pattern_sets)):
            near = [j for j, f in enumerate(mhz[k]) if abs(f - mhz[0][i]) <= tol_mhz]
            if not near:
                break
            j = min(near, key=lambda j: abs(mhz[k][j] - mhz[0][i]))
            members.append(pattern_sets[k][j])
            indices.append(j)
        else:
            groups.append((mhz[0][i], members))
            for k, j in enumerate(indices):
                used[k].add(j)
    groups.sort(key=lambda g: g[0])
    skipped = {label: sorted(f for j, f in enumerate(freqs) if j not in used[k])
               for k, (label, freqs) in enumerate(zip(labels, mhz))}
    return groups, skipped


def shade_spans(cut: str, value_deg: float, axis: str, step_deg: float = 0.25):
    """Where along a cut the direction lies on the + or - side of an axis ('X', 'Y' or 'Z').

    Returns a list of (start_deg, end_deg, sign) that tiles the cut's angle range (-180 to 180 for
    a phi cut, 0 to 360 for a theta cut), with sign +1 where the direction has a positive component
    along the axis and -1 where it is negative. Boundaries are found on a step_deg grid, so they are
    accurate to about half a step. Returns None if the cut never leaves the plane perpendicular to
    the axis (for example the Y axis for the XZ plane), where there is nothing to split.
    """
    if cut not in ("phi", "theta"):
        raise ValueError("cut must be 'phi' or 'theta'")
    if axis not in ("X", "Y", "Z"):
        raise ValueError(f"axis must be X, Y or Z, not {axis!r}")
    lo, hi = (-180.0, 180.0) if cut == "phi" else (0.0, 360.0)
    psi = np.linspace(lo, hi, int(round((hi - lo) / step_deg)) + 1)
    if cut == "phi":  # theta runs out and back: negative angles are the phi + 180 side
        theta = np.deg2rad(np.abs(psi))
        phi = np.deg2rad(value_deg) + np.where(psi >= 0, 0.0, np.pi)
    else:
        theta = np.full_like(psi, np.deg2rad(value_deg))
        phi = np.deg2rad(psi)
    component = {"X": np.sin(theta) * np.cos(phi), "Y": np.sin(theta) * np.sin(phi),
                 "Z": np.cos(theta)}[axis]
    if np.max(np.abs(component)) < 1e-9:
        return None

    sign = np.where(component > 1e-9, 1, np.where(component < -1e-9, -1, 0))
    known = np.nonzero(sign)[0]  # samples clearly on one side; the rest lie on a boundary
    edges, signs = [lo], [int(sign[known[0]])]
    for i, j in zip(known[:-1], known[1:]):
        if sign[i] != sign[j]:
            edges.append(float((psi[i] + psi[j]) / 2))  # midway across the gap, so on a zero sample
            signs.append(int(sign[j]))
    edges.append(hi)
    return list(zip(edges[:-1], edges[1:], signs))
