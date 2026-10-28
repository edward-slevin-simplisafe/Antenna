"""Plot radiation-pattern cuts, one figure per frequency, polarizations overlaid.

Theta is measured from +Z and phi from +X toward +Y, so the principal planes are
    XY = theta 90 cut,   XZ = phi 0 cut,   YZ = phi 90 cut.

    # the three principal planes, polar + rectangular, for every CSV in data/
    python scripts/plot_patterns.py data --plane XY XZ YZ

    # one plane, one frequency, polar only, saved to disk
    python scripts/plot_patterns.py "data/01-2450*.csv" --plane XY --kind polar --save-dir output

    # arbitrary cuts: phi = 45 and phi = 135 (sweeping theta)
    python scripts/plot_patterns.py data --cut phi --angles 45 135

Files may be given as paths, directories (all *.csv) or glob patterns. The frequency is
read from the filename (e.g. 01-2400.000000MHz.csv). --plane and --cut/--angles can be combined.
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from antenna.models import GAIN_LIMIT_DB, PLANES, plane_name
from antenna.plotting import make_cut_figure
from antenna.readers import load_patterns


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
                    help="plot dynamic range in dB below the top (default 40)")
    ap.add_argument("--gain-limit", type=float, default=GAIN_LIMIT_DB, metavar="DB",
                    help=f"dashed max-gain requirement line on rectangular plots (default {GAIN_LIMIT_DB:g})")
    ap.add_argument("--no-gain-limit", action="store_true", help="omit the gain limit line")
    ap.add_argument("--save-dir", type=Path, help="save PNGs here instead of showing")
    args = ap.parse_args()
    gain_limit = None if args.no_gain_limit else args.gain_limit

    if bool(args.cut) != bool(args.angles):
        ap.error("--cut and --angles must be given together")
    cuts = [PLANES[p] for p in args.plane or []]
    cuts += [(args.cut, a) for a in args.angles or []]
    if not cuts:
        ap.error("choose what to plot: --plane XY XZ YZ and/or --cut with --angles")
    cuts = list(dict.fromkeys(cuts))  # e.g. --plane XZ plus --cut phi --angles 0 is one plot

    patterns = load_patterns(args.inputs)
    print(f"loaded {len(patterns)} pattern file(s): "
          + ", ".join(f"{p.freq_hz / 1e6:g} MHz" for p in patterns))

    for pattern in patterns:
        for cut, angle in cuts:
            for kind in args.kind:
                fig = make_cut_figure(pattern, cut, angle, kind, args.pols, args.dyn_range,
                                      args.smooth, gain_limit)
                if args.save_dir:
                    args.save_dir.mkdir(parents=True, exist_ok=True)
                    where = plane_name(cut, angle) or f"{cut}{angle:g}"
                    tag = f"_smooth{args.smooth:g}" if args.smooth > 0 else ""
                    name = f"{pattern.freq_hz / 1e6:g}MHz_{where}_{kind}{tag}.png"
                    fig.savefig(args.save_dir / name, dpi=150)
                    plt.close(fig)
                    print(f"saved {args.save_dir / name}")

    if not args.save_dir:
        plt.show()


if __name__ == "__main__":
    main()
