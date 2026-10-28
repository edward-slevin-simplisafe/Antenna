"""Matplotlib plotting. Functions draw on a caller-supplied Axes so they can be reused
from scripts now and from a GUI canvas later; the make_* helpers build whole figures."""

import math

import matplotlib.pyplot as plt
import numpy as np

from antenna import analysis
from antenna.models import (DEFAULT_POLS, GAIN_LIMIT_DB, POL_COLORS, POL_LABELS, Pattern,
                            S11Data, plane_name)


# ---- S11 -------------------------------------------------------------------

def plot_s11(ax, series: list[S11Data], threshold_db: float | None = -10.0,
             mark_mhz: list[float] | None = None, shade_bands: bool = True):
    """Overlay |S11| (dB) vs frequency (MHz) for one or more measurements."""
    for k, data in enumerate(series):
        f_mhz = data.freq_hz / 1e6
        y = analysis.s11_db(data.s11)
        (line,) = ax.plot(f_mhz, y, label=data.name or f"S11 {k + 1}")
        if threshold_db is not None and shade_bands:
            for lo, hi in analysis.bands_below(f_mhz, y, threshold_db):
                ax.axvspan(lo, hi, color=line.get_color(), alpha=0.08)
        marks = sorted(mark_mhz or [])
        for i, fm in enumerate(marks):
            val = float(np.interp(fm, f_mhz, y))
            ax.plot([fm], [val], "o", color=line.get_color())
            # Stagger labels so neighbouring markers don't overlap: first up-left, last to the
            # right, any in between below-left.
            if i == len(marks) - 1 and i > 0:
                offset, ha = (10, -4), "left"
            elif i == 0:
                offset, ha = (-10, 8), "right"
            else:
                offset, ha = (-10, -16), "right"
            ax.annotate(f"{fm:g} MHz\n{val:.1f} dB", (fm, val), textcoords="offset points",
                        xytext=offset, ha=ha, fontsize=8)
    for fm in mark_mhz or []:
        ax.axvline(fm, color="gray", ls=":", lw=0.8)
    if threshold_db is not None:
        ax.axhline(threshold_db, color="gray", ls="--", lw=0.8)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("S11 (dB)")
    ax.grid(True, alpha=0.3)
    ax.legend()


def make_s11_figure(series: list[S11Data], **kwargs):
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    plot_s11(ax, series, **kwargs)
    ax.set_title("Return loss")
    return fig


def plot_s11_smith(ax, series: list[S11Data], threshold_db: float | None = -10.0,
                   mark_mhz: list[float] | None = None):
    """Overlay S11 traces on a Smith chart, with optional frequency markers.

    The dashed circle is the |S11| = threshold_db contour: points inside it are
    better matched than the threshold.
    """
    import skrf  # lazy: slow to import, and not needed for the other plots

    for k, data in enumerate(series):
        label = data.name or f"S11 {k + 1}"
        ntwk = skrf.Network(
            frequency=skrf.Frequency.from_f(data.freq_hz, unit="hz"),
            s=data.s11.reshape(-1, 1, 1),
            z0=data.z0,
        )
        ntwk.plot_s_smith(m=0, n=0, ax=ax, show_legend=False, label=label,
                          color=f"C{k % 10}")
        for fm in mark_mhz or []:
            g = analysis.s11_at(data, fm * 1e6)
            ax.plot([g.real], [g.imag], "o", color=f"C{k % 10}")
            ax.annotate(f"{fm:g} MHz", (g.real, g.imag), textcoords="offset points",
                        xytext=(6, 6), fontsize=8)
    if threshold_db is not None:
        r = 10 ** (threshold_db / 20)
        ax.add_patch(plt.Circle((0, 0), r, fill=False, ls="--", lw=0.8, color="gray"))
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 1.08))


def make_smith_figure(series: list[S11Data], **kwargs):
    fig, ax = plt.subplots(figsize=(7, 7), constrained_layout=True)
    plot_s11_smith(ax, series, **kwargs)
    ax.set_title("S11 Smith chart")
    return fig


# ---- Radiation patterns ----------------------------------------------------

TRACE_LINEWIDTH = 2.5  # pattern traces (matplotlib's default is 1.5)


def _limits(gains: dict[str, np.ndarray], dynamic_range_db: float,
            rmin: float | None = None, rmax: float | None = None):
    """Gain-axis (bottom, top) in dB.

    Explicit rmin/rmax win. By default the top is the highest gain rounded up to a multiple of
    5 dB. A lone rmax puts the bottom dynamic_range_db below it; a lone rmin keeps the top automatic.
    """
    if rmax is None:
        peak = max(float(np.nanmax(g)) for g in gains.values())
        top = 5 * math.ceil(peak / 5) if peak > 0 else 5 * math.ceil((peak + 0.001) / 5)
    else:
        top = rmax
    bottom = rmin if rmin is not None else top - dynamic_range_db
    if bottom >= top:
        raise ValueError(f"rmin ({bottom:g} dB) must be below rmax ({top:g} dB)")
    return bottom, top


def plot_cut_polar(ax, angle_deg: np.ndarray, gains: dict[str, np.ndarray],
                   dynamic_range_db: float = 40.0, colors: dict[str, str] | None = None,
                   top_down: bool = False, rmin: float | None = None, rmax: float | None = None):
    """Polar overlay. `ax` needs projection='polar'.

    Default: 0 deg at the top, increasing clockwise (theta sweeps of the XZ/YZ cuts).
    top_down=True: 0 deg at the right, increasing counterclockwise, i.e. the view from +Z
    for an azimuth (phi) sweep, so +X is right and +Y is up.
    """
    rmin, rmax = _limits(gains, dynamic_range_db, rmin, rmax)
    for label, g in gains.items():
        ax.plot(np.deg2rad(angle_deg), np.maximum(g, rmin), label=label,
                color=(colors or {}).get(label), lw=TRACE_LINEWIDTH)
    if top_down:
        ax.set_theta_zero_location("E")
        ax.set_theta_direction(1)
    else:
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
    ax.set_rlim(rmin, rmax)
    ax.set_rlabel_position(22.5)
    ax.grid(True, alpha=0.4)


def plot_cut_rect(ax, angle_deg: np.ndarray, gains: dict[str, np.ndarray], xlabel: str,
                  dynamic_range_db: float = 40.0, colors: dict[str, str] | None = None,
                  limit_db: float | None = None, rmin: float | None = None,
                  rmax: float | None = None):
    """Rectangular overlay; limit_db draws a dashed requirement line (e.g. max gain)."""
    auto_top = rmax is None
    rmin, rmax = _limits(gains, dynamic_range_db, rmin, rmax)
    for label, g in gains.items():
        ax.plot(angle_deg, g, label=label, color=(colors or {}).get(label), lw=TRACE_LINEWIDTH)
    if limit_db is not None:
        ax.axhline(limit_db, color="black", ls="--", lw=1.6, label=f"{limit_db:g} dB limit")
        if auto_top:  # keep the limit line inside the plot unless the top was set explicitly
            rmax = max(rmax, limit_db + 1)
    ax.set_xlim(angle_deg.min(), angle_deg.max())
    ax.set_ylim(rmin, rmax)
    ax.set_xticks(np.arange(math.ceil(angle_deg.min() / 30) * 30, angle_deg.max() + 1, 30))
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Gain (dB)")
    ax.grid(True, alpha=0.3)


def make_cut_figure(pattern: Pattern, cut: str, value_deg: float, kind: str = "polar",
                    pols: list[str] | None = None, dynamic_range_db: float = 40.0,
                    smooth_deg: float = 0.0, gain_limit_db: float | None = GAIN_LIMIT_DB,
                    rmin: float | None = None, rmax: float | None = None):
    """One figure for one frequency and one cut, polarizations overlaid.

    cut='phi'  : fixed phi = value_deg, sweep theta (angle -180..180)
    cut='theta': fixed theta = value_deg, sweep phi (0..360); polar plots are drawn top-down
                 (0 deg at +X, counterclockwise) to match the XY view in the test report
    kind: 'polar' or 'rect'
    smooth_deg: sliding-window width in degrees; 0 turns smoothing off
    gain_limit_db: dashed requirement line on rectangular plots; None to omit
    rmin, rmax: gain-axis limits in dB (polar radius / rectangular y axis). Default: the top is
                the highest gain rounded up to a multiple of 5, the bottom dynamic_range_db below.
    Traces use the report's colors (POL_COLORS); principal planes are named in the title.
    """
    pols = pols or [k for k in DEFAULT_POLS if k in pattern.gain_db]
    gains, colors, angle = {}, {}, None
    for key in pols:
        if key not in pattern.gain_db:
            raise KeyError(f"{pattern.name}: no Gain{key} table (have {pattern.pols})")
        if cut == "phi":
            angle, g = analysis.cut_phi(pattern, key, value_deg)
        elif cut == "theta":
            angle, g = analysis.cut_theta(pattern, key, value_deg)
        else:
            raise ValueError("cut must be 'phi' or 'theta'")
        step = float(np.median(np.diff(angle)))
        g = analysis.smooth_circular(g, step, smooth_deg)
        label = POL_LABELS.get(key, key)
        gains[label] = g
        if key in POL_COLORS:
            colors[label] = POL_COLORS[key]
    applied_deg = analysis.effective_window_deg(step, smooth_deg)

    if kind == "polar":
        fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(7, 6.5),
                               constrained_layout=True)
        plot_cut_polar(ax, angle, gains, dynamic_range_db, colors, top_down=(cut == "theta"),
                       rmin=rmin, rmax=rmax)
        ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
    elif kind == "rect":
        fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
        plot_cut_rect(ax, angle, gains, "Theta (deg)" if cut == "phi" else "Phi (deg)",
                      dynamic_range_db, colors, gain_limit_db, rmin, rmax)
        ax.legend()
    else:
        raise ValueError("kind must be 'polar' or 'rect'")

    sym, fixed = ("φ", value_deg) if cut == "phi" else ("θ", value_deg)
    smooth_note = f"   ({applied_deg:g}° smoothing window)" if applied_deg else ""
    plane = plane_name(cut, value_deg)
    what = f"{plane} plane ({sym} = {fixed:g}°)" if plane else f"{sym} = {fixed:g}° cut"
    ax.set_title(f"{pattern.freq_hz / 1e6:g} MHz   {what}{smooth_note}")
    return fig
