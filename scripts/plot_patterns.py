"""Plot radiation-pattern cuts, one figure per frequency, polarizations overlaid.

    # polar + rectangular phi=0 and phi=90 cuts for every CSV in data/
    python scripts/plot_patterns.py data --cut phi --angles 0 90

    # conical cut at theta=90 (azimuth sweep), a single file, saved to disk
    python scripts/plot_patterns.py "data/01-2400*.csv" --cut theta --angles 90 --save-dir output

Files may be given as paths, directories (all *.csv) or glob patterns. The frequency is
read from the filename (e.g. 01-2400.000000MHz.csv).
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from antenna.plotting import make_cut_figure
from antenna.readers import load_patterns


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="pattern CSV files, directories or globs")
    ap.add_argument("--cut", choices=["phi", "theta"], required=True,
                    help="phi: fixed phi, sweep theta.  theta: fixed theta, sweep phi")
    ap.add_argument("--angles", type=float, nargs="+", required=True,
                    help="fixed angle(s) in degrees, one set of figures per value")
    ap.add_argument("--kind", nargs="+", choices=["polar", "rect"], default=["polar", "rect"])
    ap.add_argument("--pols", nargs="+", help="table keys to overlay (default: T H V)")
    ap.add_argument("--smooth", type=float, nargs="?", const=10.0, default=0.0, metavar="DEG",
                    help="sliding-window smoothing across angle: omit = off, bare --smooth = 10 deg,\n"
                         "--smooth 20 = 20 deg window. Averaged in linear power, wraps at the seam; the\n"
                         "window is rounded to an odd number of samples (5 deg grid: 20 -> 25 deg),\n"
                         "and the plot title shows the width actually used")
    ap.add_argument("--range", type=float, default=40.0, dest="dyn_range",
                    help="plot dynamic range in dB below the top (default 40)")
    ap.add_argument("--save-dir", type=Path, help="save PNGs here instead of showing")
    args = ap.parse_args()

    patterns = load_patterns(args.inputs)
    print(f"loaded {len(patterns)} pattern file(s): "
          + ", ".join(f"{p.freq_hz / 1e6:g} MHz" for p in patterns))

    for pattern in patterns:
        for angle in args.angles:
            for kind in args.kind:
                fig = make_cut_figure(pattern, args.cut, angle, kind, args.pols, args.dyn_range,
                                      args.smooth)
                if args.save_dir:
                    args.save_dir.mkdir(parents=True, exist_ok=True)
                    tag = f"_smooth{args.smooth:g}" if args.smooth > 0 else ""
                    name = f"{pattern.freq_hz / 1e6:g}MHz_{args.cut}{angle:g}_{kind}{tag}.png"
                    fig.savefig(args.save_dir / name, dpi=150)
                    plt.close(fig)
                    print(f"saved {args.save_dir / name}")

    if not args.save_dir:
        plt.show()


if __name__ == "__main__":
    main()
