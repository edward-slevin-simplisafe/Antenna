"""Plot radiation-pattern cuts, one figure per frequency, polarizations overlaid.

Theta is measured from +Z and phi from +X toward +Y, so the principal planes are
    XY = theta 90 cut,   XZ = phi 0 cut,   YZ = phi 90 cut.

    # the three principal planes, polar + rectangular, for every CSV in a folder
    python scripts/plot_patterns.py data/01_pattern --plane XY XZ YZ

    # one plane, one frequency, polar only, saved to disk
    python scripts/plot_patterns.py "data/01_pattern/01-2450*.csv" --plane XY --kind polar --save-dir output

    # arbitrary cuts: phi = 45 and phi = 135 (sweeping theta)
    python scripts/plot_patterns.py data/01_pattern --cut phi --angles 45 135

Files may be given as paths, directories (all *.csv directly inside) or glob patterns. The
frequency is read from the filename (e.g. 01-2400.000000MHz.csv). --plane and --cut/--angles
can be combined.
"""

import argparse
import sys
import time
from pathlib import Path

from antenna.feedback import elapsed, say, tip_if_slow
from antenna.models import GAIN_LIMIT_DB, PLANES, plane_name
from antenna.readers.pattern import find_pattern_files, freq_from_filename, load_patterns

MANY_WINDOWS = 12  # warn before opening more interactive windows than this


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="pattern CSV files, directories or globs")
    ap.add_argument("--plane", nargs="+", choices=list(PLANES), type=str.upper,
                    help="principal plane(s) to plot: XY, XZ, YZ")
    ap.add_argument("--cut", choices=["phi", "theta"],
                    help="phi: fixed phi, sweep theta.  theta: fixed theta, sweep phi")
    ap.add_argument("--angles", type=float, nargs="+",
                    help="fixed angle(s) in degrees for --cut, one set of figures per value")
    ap.add_argument("--kind", nargs="+", choices=["polar", "rect"], default=["polar", "rect"])
    ap.add_argument("--pols", nargs="+", help="table keys to overlay (default: T H V)")
    ap.add_argument("--smooth", type=float, nargs="?", const=10.0, default=0.0, metavar="DEG",
                    help="sliding-window smoothing across angle: omit = off, bare --smooth = 10 deg,\n"
                         "--smooth 20 = 20 deg window. Averaged in linear power, wraps at the seam; the\n"
                         "window is rounded to an odd number of samples (5 deg grid: 20 -> 25 deg),\n"
                         "and the plot title shows the width actually used")
    ap.add_argument("--range", type=float, default=40.0, dest="dyn_range",
                    help="plot dynamic range in dB below the top (default 40; unused if --rmin is given)")
    ap.add_argument("--rmax", type=float, metavar="DB",
                    help="top of the gain axis in dB (default: highest gain rounded up to a multiple of 5)")
    ap.add_argument("--rmin", type=float, metavar="DB",
                    help="bottom of the gain axis in dB (default: --range below the top)")
    ap.add_argument("--gain-limit", type=float, default=GAIN_LIMIT_DB, metavar="DB",
                    help=f"dashed max-gain requirement line on rectangular plots (default {GAIN_LIMIT_DB:g})")
    ap.add_argument("--no-gain-limit", action="store_true", help="omit the gain limit line")
    ap.add_argument("--save-dir", type=Path, help="save PNGs here instead of showing")
    args = ap.parse_args()
    gain_limit = None if args.no_gain_limit else args.gain_limit

    if args.rmin is not None and args.rmax is not None and args.rmin >= args.rmax:
        ap.error(f"--rmin ({args.rmin:g}) must be below --rmax ({args.rmax:g})")
    if bool(args.cut) != bool(args.angles):
        ap.error("--cut and --angles must be given together")
    cuts = [PLANES[p] for p in args.plane or []]
    cuts += [(args.cut, a) for a in args.angles or []]
    if not cuts:
        ap.error("choose what to plot: --plane XY XZ YZ and/or --cut with --angles")
    cuts = list(dict.fromkeys(cuts))  # e.g. --plane XZ plus --cut phi --angles 0 is one plot

    try:  # fail fast on a typo, before the slow library load
        files = find_pattern_files(args.inputs)
    except FileNotFoundError as err:
        sys.exit(f"error: {err}")
    say(f"Found {len(files)} pattern file(s)")

    say("Loading libraries (numpy, scipy, matplotlib)...")
    t0 = time.perf_counter()
    import matplotlib.pyplot as plt

    from antenna.plotting import make_cut_figure

    load_s = time.perf_counter() - t0
    say(f"Libraries loaded in {load_s:.1f} s")
    tip_if_slow(load_s)

    def reading(i, total, path):
        freq = freq_from_filename(path)
        say(f"Reading {path.name} ({i}/{total})" + (f" - {freq / 1e6:g} MHz" if freq else ""))

    try:
        patterns = load_patterns(files, on_file=reading)
    except (FileNotFoundError, ValueError, KeyError) as err:
        sys.exit(f"error: {err}")
    say(f"Loaded {len(patterns)} frequency point(s): "
        f"{patterns[0].freq_hz / 1e6:g} to {patterns[-1].freq_hz / 1e6:g} MHz")

    total = len(patterns) * len(cuts) * len(args.kind)
    say(f"Making {total} figure(s)" + (f", saving to {args.save_dir}" if args.save_dir else ""))
    if not args.save_dir and total > MANY_WINDOWS:
        say(f"Note: that opens {total} windows at once; add --save-dir <folder> to save PNGs instead.")

    count = 0
    for pattern in patterns:
        for cut, angle in cuts:
            where = plane_name(cut, angle) or f"{cut}{angle:g}"
            for kind in args.kind:
                count += 1
                say(f"({count}/{total}) {pattern.freq_hz / 1e6:g} MHz {where} {kind}")
                try:
                    fig = make_cut_figure(pattern, cut, angle, kind, args.pols, args.dyn_range,
                                          args.smooth, gain_limit, args.rmin, args.rmax)
                except (KeyError, ValueError) as err:
                    sys.exit(f"error: {err}")
                if args.save_dir:
                    args.save_dir.mkdir(parents=True, exist_ok=True)
                    tag = f"_smooth{args.smooth:g}" if args.smooth > 0 else ""
                    name = f"{pattern.freq_hz / 1e6:g}MHz_{where}_{kind}{tag}.png"
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
