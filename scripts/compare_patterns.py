"""Overlay radiation patterns from two or more datasets, one panel per polarization.

Each input is one dataset: a folder of pattern CSVs, a single file, or a glob. Files are paired by
frequency, and each frequency, plane and plot type gives one figure with a panel for H+V, H and V
sharing one gain axis. Rectangular figures also get a row of difference panels: the gain of every
later dataset minus the first one (the reference), in dB. Datasets are colored, and the
polarization is named on each panel.

    # two hardware versions, all three principal planes, at three frequencies
    python scripts/compare_patterns.py data/v1p9/v1p9-A_pattern data/v2p1/v2p1_Pattern --plane XY XZ YZ --freqs 2400 2450 2500 --save-dir output

    # three samples of one version plus the new version, 2450 MHz, polar only
    python scripts/compare_patterns.py data/v1p9/v1p9-A_pattern data/v1p9/v1p9-B_pattern data/v1p9/v1p9-C_pattern data/v2p1/v2p1_Pattern --plane XY --freqs 2450 --kind polar

    # two single files, with your own legend names
    python scripts/compare_patterns.py "data/v1p9/v1p9-A_pattern/*2450*.csv" "data/v2p1/v2p1_Pattern/*2450*.csv" --plane XZ --labels "v1.9 A" "v2.1"

Datasets are drawn in the order given. The legend names default to the folder names (without a
trailing "_pattern"); --labels sets them. Only frequencies present in every dataset are compared
(within 0.5 MHz), and the others are listed and skipped. Theta is measured from +Z and phi from +X
toward +Y, as in plot_patterns.py, and the datasets are assumed to share one coordinate frame.
Smoothing, axis limits, the gain limit line and the half-plane shading (--shade) work as in
plot_patterns.py and apply to every dataset and panel. Up to six datasets can be compared at once.
"""

import argparse
import re
import sys
import time
from pathlib import Path

from antenna.feedback import elapsed, say, tip_if_slow
from antenna.models import (DEFAULT_POLS, DIFF_RANGE_DB, GAIN_LIMIT_DB, PLANES, SHADE_SPLITS,
                            plane_name)
from antenna.readers.pattern import find_pattern_files

MANY_WINDOWS = 12  # warn before opening more interactive windows than this
MAX_DATASETS = 6  # one color each; see antenna.plotting.DATASET_COLORS
FREQ_TOL_MHZ = 0.5  # files this close in frequency are the same frequency


def default_label(item) -> str:
    """Folder name without a trailing 'pattern' ('v1p9-A_pattern' -> 'v1p9-A'); for a file or glob,
    the name of the folder it is in."""
    path = Path(item)
    name = path.name if path.is_dir() else path.parent.name
    return re.sub(r"[_\- ]?pattern$", "", name, flags=re.IGNORECASE) or str(item)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.+]+", "-", text).strip("-")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("inputs", nargs="+",
                    help="one dataset per input (folder, file or glob); at least two. The first is "
                         "the reference for the difference panels")
    ap.add_argument("--labels", nargs="+", metavar="NAME",
                    help="legend names, one per dataset (default: the folder names)")
    ap.add_argument("--freqs", type=float, nargs="+", metavar="MHZ",
                    help="compare only these frequencies (default: every frequency in common)")
    ap.add_argument("--plane", nargs="+", choices=list(PLANES), type=str.upper,
                    help="principal plane(s) to plot: XY, XZ, YZ")
    ap.add_argument("--cut", choices=["phi", "theta"],
                    help="phi: fixed phi, sweep theta.  theta: fixed theta, sweep phi")
    ap.add_argument("--angles", type=float, nargs="+",
                    help="fixed angle(s) in degrees for --cut, one set of figures per value")
    ap.add_argument("--kind", nargs="+", choices=["polar", "rect"], default=["polar", "rect"])
    ap.add_argument("--pols", nargs="+", metavar="KEY",
                    help="table keys to show, one panel each (default: "
                         f"{' '.join(DEFAULT_POLS)}, i.e. H+V, H and V)")
    ap.add_argument("--smooth", type=float, nargs="?", const=10.0, default=0.0, metavar="DEG",
                    help="sliding-window smoothing across angle (omit = off, bare --smooth = 10 deg),\n"
                         "applied to every dataset; see plot_patterns.py --help")
    ap.add_argument("--range", type=float, default=40.0, dest="dyn_range",
                    help="gain axis span in dB below the top (default 40)")
    ap.add_argument("--rmax", type=float, metavar="DB",
                    help="top of the gain axis in dB (default: highest gain, rounded up to a multiple of 5)")
    ap.add_argument("--rmin", type=float, metavar="DB",
                    help="bottom of the gain axis in dB (default: --range below the top)")
    ap.add_argument("--gain-limit", type=float, default=GAIN_LIMIT_DB, metavar="DB",
                    help=f"dashed max-gain requirement line on rectangular plots (default {GAIN_LIMIT_DB:g})")
    ap.add_argument("--no-gain-limit", action="store_true", help="omit the gain limit line")
    ap.add_argument("--diff-range", type=float, default=DIFF_RANGE_DB, metavar="DB",
                    help="the difference panels span +/- this many dB (default "
                         f"{DIFF_RANGE_DB:g}); larger differences run off the panel edge and are counted")
    ap.add_argument("--shade", choices=["auto", "none", *SHADE_SPLITS], default="auto",
                    help="tint the two half-planes of each cut on every panel so the angles read as\n"
                         "directions: auto = front/rear in the XY plane, right/left in XZ, top/bottom in YZ;\n"
                         f"or name a split ({', '.join(SHADE_SPLITS)}); or none. A split whose axis is\n"
                         "not in a plane falls back to auto for that plane (default auto)")
    ap.add_argument("--save-dir", type=Path, help="save PNGs here instead of showing")
    args = ap.parse_args()

    if len(args.inputs) < 2:
        ap.error("give at least two datasets to compare")
    if len(args.inputs) > MAX_DATASETS:
        ap.error(f"at most {MAX_DATASETS} datasets can be compared at once")
    if bool(args.cut) != bool(args.angles):
        ap.error("--cut and --angles must be given together")
    if args.rmin is not None and args.rmax is not None and args.rmin >= args.rmax:
        ap.error(f"--rmin ({args.rmin:g}) must be below --rmax ({args.rmax:g})")
    if args.diff_range <= 0:
        ap.error("--diff-range must be positive")
    labels = args.labels or [default_label(item) for item in args.inputs]
    if len(labels) != len(args.inputs):
        ap.error(f"{len(args.inputs)} datasets but {len(labels)} labels")
    if len(set(labels)) != len(labels):
        ap.error("the datasets need different names; give them with --labels "
                 f"(they were called {', '.join(labels)})")
    cuts = [PLANES[p] for p in args.plane or []]
    cuts += [(args.cut, a) for a in args.angles or []]
    if not cuts:
        ap.error("choose what to plot: --plane XY XZ YZ and/or --cut with --angles")
    cuts = list(dict.fromkeys(cuts))
    gain_limit = None if args.no_gain_limit else args.gain_limit

    try:  # fail fast on a typo, before the library load
        file_lists = [find_pattern_files([item]) for item in args.inputs]
    except FileNotFoundError as err:
        sys.exit(f"error: {err}")
    say("Found " + ", ".join(f"{len(files)} file(s) for {label}"
                             for files, label in zip(file_lists, labels)))

    say("Loading libraries (numpy, scipy, matplotlib)...")
    t0 = time.perf_counter()
    import matplotlib.pyplot as plt

    from antenna.analysis import match_by_frequency
    from antenna.plotting import make_compare_figure, resolve_shade
    from antenna.readers import load_patterns

    load_s = time.perf_counter() - t0
    say(f"Libraries loaded in {load_s:.1f} s")
    tip_if_slow(load_s)

    try:
        sets = []
        for files, label in zip(file_lists, labels):
            say(f"Reading {len(files)} file(s) for {label}...")
            sets.append(load_patterns(files))
        groups, skipped = match_by_frequency(sets, labels, FREQ_TOL_MHZ)
    except (FileNotFoundError, ValueError, KeyError) as err:
        sys.exit(f"error: {err}")

    if not groups:
        spans = "; ".join(f"{label}: {p[0].freq_hz / 1e6:g} to {p[-1].freq_hz / 1e6:g} MHz"
                          for p, label in zip(sets, labels))
        sys.exit(f"error: the datasets have no frequency in common ({spans})")
    for label, freqs in skipped.items():
        if freqs:
            say(f"Skipping {len(freqs)} frequenc{'y' if len(freqs) == 1 else 'ies'} of {label} "
                f"that are not in every dataset: {', '.join(f'{f:g}' for f in freqs)} MHz")
    if args.freqs:
        groups = [g for g in groups if any(abs(g[0] - f) <= FREQ_TOL_MHZ for f in args.freqs)]
        if not groups:
            sys.exit("error: none of the requested frequencies are in every dataset")
    say(f"Comparing {len(groups)} frequenc{'y' if len(groups) == 1 else 'ies'}: "
        f"{', '.join(f'{g[0]:g}' for g in groups)} MHz")

    shades = {}  # (cut, angle) -> the half-plane split to shade, or None
    for cut, angle in cuts:
        shades[(cut, angle)], note = resolve_shade(cut, angle, args.shade)
        if note:
            say(f"Note: {note}")

    total = len(groups) * len(cuts) * len(args.kind)
    say(f"Making {total} figure(s)" + (f", saving to {args.save_dir}" if args.save_dir else ""))
    if not args.save_dir and total > MANY_WINDOWS:
        say(f"Note: that opens {total} windows at once; add --save-dir <folder> to save PNGs instead.")

    names = "_vs_".join(slug(label) for label in labels)
    count = 0
    for freq, patterns in groups:
        for cut, angle in cuts:
            where = plane_name(cut, angle) or f"{cut}{angle:g}"
            for kind in args.kind:
                count += 1
                say(f"({count}/{total}) {freq:g} MHz {where} {kind}")
                try:
                    fig = make_compare_figure(patterns, labels, cut, angle, kind, args.pols,
                                              args.dyn_range, args.smooth, gain_limit, args.rmin,
                                              args.rmax, args.diff_range, shades[(cut, angle)])
                except (KeyError, ValueError) as err:
                    sys.exit(f"error: {err}")
                if args.save_dir:
                    args.save_dir.mkdir(parents=True, exist_ok=True)
                    tag = f"_smooth{args.smooth:g}" if args.smooth > 0 else ""
                    name = f"{freq:g}MHz_{where}_{kind}_{names}{tag}.png"
                    fig.savefig(args.save_dir / name, dpi=150)
                    plt.close(fig)

    if args.save_dir:
        say(f"Done: {count} file(s) saved to {args.save_dir} in {elapsed():.1f} s")
    else:
        say(f"Showing {count} figure window(s) - close them to exit.")
        plt.show()
        say("Done")


if __name__ == "__main__":
    main()
