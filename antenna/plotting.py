"""Matplotlib plotting. Functions draw on a caller-supplied Axes so they can be reused
from scripts now and from a GUI canvas later; the make_* helpers build whole figures."""

import math

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

from antenna import analysis
from antenna.models import (AUTO_SHADE_AXIS, DEFAULT_POLS, DIFF_RANGE_DB, GAIN_LIMIT_DB, ORIENTATION,
                            POL_COLORS, POL_LABELS, SHADE_ALPHA, SHADE_SPLITS, SIDE_COLORS, Pattern,
                            S11Data, WIFI_24_BAND_LABEL, WIFI_24_BAND_MHZ, axis_text, plane_name)


# ---- S11 -------------------------------------------------------------------

def plot_s11(ax, series: list[S11Data], threshold_db: float | None = -10.0,
             mark_mhz: list[float] | None = None,
             band_mhz: tuple[float, float] | None = WIFI_24_BAND_MHZ,
             ymin: float | None = None, ymax: float | None = None):
    """Overlay |S11| (dB) vs frequency (MHz) for one or more measurements.

    band_mhz: (low, high) frequency range to shade, default the 2.4 GHz Wi-Fi band (CH 1-13);
              None for no shading.
    ymin, ymax: dB axis limits; either one may be omitted to keep the automatic limit.
    """
    if band_mhz is not None:
        lo, hi = band_mhz
        is_wifi = (float(lo), float(hi)) == WIFI_24_BAND_MHZ
        ax.axvspan(lo, hi, color="0.5", alpha=0.15, lw=0,
                   label=WIFI_24_BAND_LABEL if is_wifi else f"{lo:g}-{hi:g} MHz band")
    for k, data in enumerate(series):
        f_mhz = data.freq_hz / 1e6
        y = analysis.s11_db(data.s11)
        (line,) = ax.plot(f_mhz, y, label=data.name or f"S11 {k + 1}")
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
    if ymin is not None or ymax is not None:
        ax.set_ylim(bottom=ymin, top=ymax)
        bottom, top = ax.get_ylim()
        if bottom >= top:
            raise ValueError(f"ymin ({bottom:g} dB) must be below ymax ({top:g} dB)")
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

# Text sizes in points for the pattern plots (matplotlib's default is 10).
TICK_FONTSIZE = 13
LABEL_FONTSIZE = 14
LEGEND_FONTSIZE = 14
TITLE_FONTSIZE = 16

POLAR_TICK_STEP_DEG = 10  # angle grid lines and labels on polar plots
POLAR_TICK_FONTSIZE = 12  # a little smaller than TICK_FONTSIZE so 36 angle labels don't collide
POLAR_FIGSIZE = (9, 8)  # inches; larger so the 10 degree labels have room


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
    ax.set_thetagrids(np.arange(0, 360, POLAR_TICK_STEP_DEG))
    ax.tick_params(labelsize=POLAR_TICK_FONTSIZE)
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
    ax.set_xlabel(xlabel, fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("Gain (dB)", fontsize=LABEL_FONTSIZE)
    ax.tick_params(labelsize=TICK_FONTSIZE)
    ax.grid(True, alpha=0.3)


def _cut_trace(pattern: Pattern, key: str, cut: str, value_deg: float, smooth_deg: float):
    """(angle_deg, gain_db, grid_step_deg) of one table along a cut, smoothed if requested."""
    if key not in pattern.gain_db:
        raise KeyError(f"{pattern.name}: no Gain{key} table (have {pattern.pols})")
    if cut == "phi":
        angle, g = analysis.cut_phi(pattern, key, value_deg)
    elif cut == "theta":
        angle, g = analysis.cut_theta(pattern, key, value_deg)
    else:
        raise ValueError("cut must be 'phi' or 'theta'")
    step = float(np.median(np.diff(angle)))
    return angle, analysis.smooth_circular(g, step, smooth_deg), step


def _cut_title(freq_hz: float, cut: str, value_deg: float, applied_smooth_deg: float) -> str:
    """'2450 MHz   XY plane (θ = 90°)', plus the smoothing window if one was applied."""
    sym = "φ" if cut == "phi" else "θ"
    smooth_note = f"   ({applied_smooth_deg:g}° smoothing window)" if applied_smooth_deg else ""
    plane = plane_name(cut, value_deg)
    what = f"{plane} plane ({sym} = {value_deg:g}°)" if plane else f"{sym} = {value_deg:g}° cut"
    return f"{freq_hz / 1e6:g} MHz   {what}{smooth_note}"


def _axis_of_split(split: str) -> str:
    """The axis letter ('X', 'Y' or 'Z') a split such as 'front-rear' is across."""
    return ORIENTATION[SHADE_SPLITS[split][0]][0]


def _split_for_axis(axis: str) -> str:
    return next(name for name in SHADE_SPLITS if _axis_of_split(name) == axis)


def resolve_shade(cut: str, value_deg: float, shade: str | None = "auto"):
    """Pick the half-plane split to shade along a cut: (split name or None, note or None).

    shade is None or 'none' (no shading), 'auto', or a split name such as 'front-rear' (see
    SHADE_SPLITS). 'auto' splits on the axis AUTO_SHADE_AXIS gives for a principal plane, and for
    other cuts on the first of Y, X, Z that the cut crosses. A named split whose axis is not in the
    cut's plane (front-rear in the XZ plane, say) falls back to 'auto', and the note says so.
    """
    if shade is None or shade == "none":
        return None, None
    if shade not in ("auto", *SHADE_SPLITS):
        raise ValueError(f"shade must be 'auto', 'none' or one of {', '.join(SHADE_SPLITS)}")
    note = None
    if shade != "auto":
        spans = analysis.shade_spans(cut, value_deg, _axis_of_split(shade))
        if spans is not None:
            return shade, None
        where = plane_name(cut, value_deg) or f"{cut} = {value_deg:g}"
        note = (f"{shade} shading needs the {_axis_of_split(shade)} axis, which is not in the "
                f"{where} plane")
    plane = plane_name(cut, value_deg)
    axes = [AUTO_SHADE_AXIS[plane]] if plane else ["Y", "X", "Z"]
    for axis in axes:
        spans = analysis.shade_spans(cut, value_deg, axis)
        if spans is not None and len({sign for _, _, sign in spans}) == 2:
            return _split_for_axis(axis), (f"{note}; using {_split_for_axis(axis)}" if note else None)
    return None, (f"{note}; not shading it" if note else None)


def _draw_shading(axes, kind: str, cut: str, value_deg: float, split: str | None):
    """Shade the half-planes of a cut behind the traces on every axes in `axes`.

    kind is 'rect' or 'polar' (polar axes must already have their radial limits set). Returns the
    legend patches naming each side, empty if split is None.
    """
    if split is None:
        return []
    sides = SHADE_SPLITS[split]
    side_of_sign = {(1 if ORIENTATION[s][1] == "+" else -1): s for s in sides}
    spans = analysis.shade_spans(cut, value_deg, _axis_of_split(split))
    if spans is None:
        raise ValueError(f"{split} shading needs the {_axis_of_split(split)} axis, which this cut "
                         "never leaves the plane of")
    for ax in axes:
        for start, end, sign in spans:
            color = SIDE_COLORS[side_of_sign[sign]]
            if kind == "rect":
                ax.axvspan(start, end, facecolor=color, alpha=SHADE_ALPHA, lw=0, zorder=0)
            else:
                arc = np.deg2rad(np.linspace(start, end, max(2, int(round(end - start)) + 1)))
                ax.fill_between(arc, ax.get_rmin(), ax.get_rmax(), facecolor=color,
                                alpha=SHADE_ALPHA, lw=0, zorder=0)
    return [Patch(facecolor=SIDE_COLORS[s], alpha=min(1.0, SHADE_ALPHA * 2.5),
                  label=f"{s} ({axis_text(ORIENTATION[s])})") for s in sides]


def make_cut_figure(pattern: Pattern, cut: str, value_deg: float, kind: str = "polar",
                    pols: list[str] | None = None, dynamic_range_db: float = 40.0,
                    smooth_deg: float = 0.0, gain_limit_db: float | None = GAIN_LIMIT_DB,
                    rmin: float | None = None, rmax: float | None = None,
                    shade: str | None = "auto"):
    """One figure for one frequency and one cut, polarizations overlaid.

    cut='phi'  : fixed phi = value_deg, sweep theta (angle -180..180)
    cut='theta': fixed theta = value_deg, sweep phi (0..360); polar plots are drawn top-down
                 (0 deg at +X, counterclockwise) to match the XY view in the test report
    kind: 'polar' or 'rect'
    smooth_deg: sliding-window width in degrees; 0 turns smoothing off
    gain_limit_db: dashed requirement line on rectangular plots; None to omit
    rmin, rmax: gain-axis limits in dB (polar radius / rectangular y axis). Default: the top is
                the highest gain rounded up to a multiple of 5, the bottom dynamic_range_db below.
    shade: tint the two half-planes of the cut, such as front and rear, so the angles read as
           directions; see resolve_shade. None or 'none' turns it off.
    Traces use the report's colors (POL_COLORS); principal planes are named in the title.
    """
    split, _ = resolve_shade(cut, value_deg, shade)
    pols = pols or [k for k in DEFAULT_POLS if k in pattern.gain_db]
    gains, colors, angle = {}, {}, None
    for key in pols:
        angle, g, step = _cut_trace(pattern, key, cut, value_deg, smooth_deg)
        label = POL_LABELS.get(key, key)
        gains[label] = g
        if key in POL_COLORS:
            colors[label] = POL_COLORS[key]
    applied_deg = analysis.effective_window_deg(step, smooth_deg)

    if kind == "polar":
        fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=POLAR_FIGSIZE,
                               constrained_layout=True)
        plot_cut_polar(ax, angle, gains, dynamic_range_db, colors, top_down=(cut == "theta"),
                       rmin=rmin, rmax=rmax)
        patches = _draw_shading([ax], "polar", cut, value_deg, split)
        handles, names = ax.get_legend_handles_labels()
        fig.legend(handles + patches, names + [p.get_label() for p in patches],
                   loc="outside upper right", fontsize=LEGEND_FONTSIZE)
    elif kind == "rect":
        fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
        plot_cut_rect(ax, angle, gains, "Theta (deg)" if cut == "phi" else "Phi (deg)",
                      dynamic_range_db, colors, gain_limit_db, rmin, rmax)
        patches = _draw_shading([ax], "rect", cut, value_deg, split)
        handles, names = ax.get_legend_handles_labels()
        ax.legend(handles + patches, names + [p.get_label() for p in patches],
                  fontsize=LEGEND_FONTSIZE)
    else:
        raise ValueError("kind must be 'polar' or 'rect'")

    ax.set_title(_cut_title(pattern.freq_hz, cut, value_deg, applied_deg),
                 fontsize=TITLE_FONTSIZE, pad=18 if kind == "polar" else 6)
    return fig


# ---- Comparing datasets ----------------------------------------------------

# Colors for comparison plots, from the Okabe-Ito colorblind-safe palette. Here the datasets get
# the colors (not the polarizations, as in the single-dataset plots); each panel names its
# polarization instead.
DATASET_COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
COMPARE_POLAR_PANEL = (7.4, 8.4)  # inches per polarization panel: width, figure height
COMPARE_RECT_PANEL = (6.6, 9.0)


def make_compare_figure(patterns: list[Pattern], labels: list[str], cut: str, value_deg: float,
                        kind: str = "polar", pols: list[str] | None = None,
                        dynamic_range_db: float = 40.0, smooth_deg: float = 0.0,
                        gain_limit_db: float | None = GAIN_LIMIT_DB, rmin: float | None = None,
                        rmax: float | None = None, diff_range_db: float = DIFF_RANGE_DB,
                        shade: str | None = "auto"):
    """Overlay the same cut of several datasets at one frequency, one panel per polarization.

    patterns holds one Pattern per dataset (all at the same frequency) and labels names them; the
    datasets are drawn in DATASET_COLORS order. All panels share one gain axis so the polarizations
    can be compared directly. Rectangular figures get a second row with the difference in dB between
    each later dataset and the first one (the reference), after any smoothing. Differences beyond
    +/- diff_range_db run off the edge of the panel, and the panel says how many points do.
    Datasets on a different angle grid are resampled onto the first dataset's grid.

    cut, value_deg, kind, pols, smooth_deg, gain_limit_db, rmin, rmax and shade work as in
    make_cut_figure (the shading is drawn on every panel, the difference panels included); pols
    defaults to H+V, H and V.
    """
    n = len(patterns)
    if n < 2:
        raise ValueError("need at least two datasets to compare")
    if n > len(DATASET_COLORS):
        raise ValueError(f"at most {len(DATASET_COLORS)} datasets can be compared at once")
    if len(labels) != n:
        raise ValueError(f"{n} datasets but {len(labels)} labels")
    if len(set(labels)) != n:
        raise ValueError("labels must all be different")
    if kind not in ("polar", "rect"):
        raise ValueError("kind must be 'polar' or 'rect'")
    pols = list(pols or DEFAULT_POLS)
    colors = dict(zip(labels, DATASET_COLORS))
    split, _ = resolve_shade(cut, value_deg, shade)

    traces = {key: {} for key in pols}  # polarization key -> {dataset label: gain in dB}
    angle, applied_deg = None, 0.0
    for pattern, label in zip(patterns, labels):
        for key in pols:
            a, g, step = _cut_trace(pattern, key, cut, value_deg, smooth_deg)
            if angle is None:
                angle, applied_deg = a, analysis.effective_window_deg(step, smooth_deg)
            elif a.shape != angle.shape or not np.allclose(a, angle):
                g = np.interp(angle, a, g)
            traces[key][label] = g

    everything = {f"{key}/{label}": g for key in pols for label, g in traces[key].items()}
    bottom, top = _limits(everything, dynamic_range_db, rmin, rmax)
    if kind == "rect" and gain_limit_db is not None and rmax is None:
        top = max(top, gain_limit_db + 1)  # keep the limit line inside the plots
    k, reference = len(pols), labels[0]

    if kind == "polar":
        fig, axes = plt.subplots(
            1, k, subplot_kw={"projection": "polar"}, squeeze=False, constrained_layout=True,
            figsize=(COMPARE_POLAR_PANEL[0] * k, COMPARE_POLAR_PANEL[1]))
        for ax, key in zip(axes[0], pols):
            plot_cut_polar(ax, angle, traces[key], dynamic_range_db, colors,
                           top_down=(cut == "theta"), rmin=bottom, rmax=top)
            ax.set_title(POL_LABELS.get(key, key), fontsize=TITLE_FONTSIZE, pad=18)
        patches = _draw_shading(list(axes[0]), "polar", cut, value_deg, split)
        handles, names = axes[0, 0].get_legend_handles_labels()
    else:
        fig, axes = plt.subplots(
            2, k, sharex="col", sharey="row", squeeze=False, constrained_layout=True,
            figsize=(COMPARE_RECT_PANEL[0] * k, COMPARE_RECT_PANEL[1]),
            gridspec_kw={"height_ratios": [3, 1.5]})
        xlabel = "Theta (deg)" if cut == "phi" else "Phi (deg)"
        for j, key in enumerate(pols):
            ax, diff_ax = axes[0, j], axes[1, j]
            plot_cut_rect(ax, angle, traces[key], "", dynamic_range_db, colors, gain_limit_db,
                          bottom, top)
            ax.set_title(POL_LABELS.get(key, key), fontsize=TITLE_FONTSIZE)
            clipped = 0
            for label in labels[1:]:
                diff = traces[key][label] - traces[key][reference]
                clipped += int((np.abs(diff) > diff_range_db).sum())
                diff_ax.plot(angle, diff, color=colors[label], lw=TRACE_LINEWIDTH,
                             label=f"{label} − {reference}")
            diff_ax.axhline(0, color="black", lw=1.2)
            diff_ax.set_ylim(-diff_range_db, diff_range_db)
            diff_ax.set_xlim(angle.min(), angle.max())
            # 60 degree ticks (the single-dataset plots use 30): three panels side by side are
            # narrower, and the labels at the shared panel edges would run together
            diff_ax.set_xticks(np.arange(math.ceil(angle.min() / 60) * 60, angle.max() + 1, 60))
            diff_ax.set_xlabel(xlabel, fontsize=LABEL_FONTSIZE)
            diff_ax.tick_params(labelsize=TICK_FONTSIZE)
            diff_ax.grid(True, alpha=0.3)
            if j == 0:
                diff_ax.set_ylabel(f"Difference (dB)\nvs {reference}", fontsize=LABEL_FONTSIZE)
            else:
                ax.set_ylabel("")
            if clipped:
                noun = "point" if clipped == 1 else "points"
                diff_ax.text(0.99, 0.04, f"{clipped} {noun} beyond ±{diff_range_db:g} dB",
                             transform=diff_ax.transAxes, ha="right", va="bottom",
                             fontsize=TICK_FONTSIZE - 1, color="dimgray")
        patches = _draw_shading(list(axes.ravel()), "rect", cut, value_deg, split)
        handles, names = axes[0, 0].get_legend_handles_labels()

    names = names + [p.get_label() for p in patches]
    fig.legend(handles + patches, names, loc="outside lower center", ncol=min(len(names), 6),
               fontsize=LEGEND_FONTSIZE)
    fig.suptitle(_cut_title(patterns[0].freq_hz, cut, value_deg, applied_deg),
                 fontsize=TITLE_FONTSIZE + 2)
    return fig
