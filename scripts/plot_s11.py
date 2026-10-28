"""Plot S11 from one or more .s1p files: a dB-vs-frequency plot and a Smith chart.

    python scripts/plot_s11.py data/01.S1P
    python scripts/plot_s11.py data/a.s1p data/b.s1p --mark 2400 2450 2480
    python scripts/plot_s11.py data/01.S1P --plots smith --save-dir output

By default the plots are marked at the 2.4 GHz Wi-Fi band edges and center
(2400, 2442 and 2483 MHz). Use --mark to choose other frequencies (MHz), or
--no-marks to turn the markers off.
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

from antenna.models import WIFI_24_MARKS_MHZ
from antenna.plotting import make_s11_figure, make_smith_figure
from antenna.readers import read_s1p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("files", nargs="+", help=".s1p file(s); several files are overlaid")
    ap.add_argument("--plots", nargs="+", choices=["db", "smith"], default=["db", "smith"],
                    help="which plots to make (default: both)")
    ap.add_argument("--threshold", type=float, default=-10.0,
                    help="dB level for the reference line / shaded bands / Smith circle (default -10)")
    ap.add_argument("--mark", type=float, nargs="+", metavar="MHZ",
                    help="frequencies (MHz) to mark on every plot "
                         f"(default: {', '.join(f'{m:g}' for m in WIFI_24_MARKS_MHZ)})")
    ap.add_argument("--no-marks", action="store_true", help="draw no frequency markers")
    ap.add_argument("--save-dir", type=Path, help="save PNGs here instead of showing")
    args = ap.parse_args()

    marks = [] if args.no_marks else (args.mark or list(WIFI_24_MARKS_MHZ))
    series = [read_s1p(f) for f in args.files]
    stem = series[0].name if len(series) == 1 else "s11"

    figures = {}
    if "db" in args.plots:
        figures["db"] = make_s11_figure(series, threshold_db=args.threshold, mark_mhz=marks)
    if "smith" in args.plots:
        figures["smith"] = make_smith_figure(series, threshold_db=args.threshold,
                                             mark_mhz=marks)

    if args.save_dir:
        args.save_dir.mkdir(parents=True, exist_ok=True)
        for kind, fig in figures.items():
            out = args.save_dir / f"{stem}_{kind}.png"
            fig.savefig(out, dpi=150)
            print(f"saved {out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
