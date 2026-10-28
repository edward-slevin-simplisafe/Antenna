"""Plot S11 from one or more .s1p files: a dB-vs-frequency plot and a Smith chart.

    python scripts/plot_s11.py data/01.S1P
    python scripts/plot_s11.py data/a.s1p data/b.s1p --mark 2400 2450 2480
    python scripts/plot_s11.py data/01.S1P --plots smith --save-dir output

By default the plots are marked at the 2.4 GHz Wi-Fi band edges and center
(2400, 2442 and 2483 MHz). Use --mark to choose other frequencies (MHz), or
--no-marks to turn the markers off.
"""

import argparse
import sys
import time
from pathlib import Path

from antenna.feedback import elapsed, say, tip_if_slow
from antenna.models import WIFI_24_MARKS_MHZ
from antenna.readers import check_s1p_path


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

    for path in args.files:  # fail fast on a typo, before the slow library load
        try:
            check_s1p_path(path)
        except (FileNotFoundError, ValueError) as err:
            sys.exit(f"error: {err}")

    say("Loading libraries (numpy, scipy, matplotlib, scikit-rf)...")
    t0 = time.perf_counter()
    import matplotlib.pyplot as plt

    from antenna.plotting import make_s11_figure, make_smith_figure
    from antenna.readers import read_s1p

    import skrf  # noqa: F401  (imported here so its load time is reported with the rest)

    load_s = time.perf_counter() - t0
    say(f"Libraries loaded in {load_s:.1f} s")
    tip_if_slow(load_s)

    series = []
    for k, path in enumerate(args.files, 1):
        say(f"Reading {path} ({k}/{len(args.files)})...")
        try:
            data = read_s1p(path)
        except (FileNotFoundError, ValueError) as err:
            sys.exit(f"error: {err}")
        series.append(data)
        say(f"  {len(data.freq_hz)} points, "
            f"{data.freq_hz[0] / 1e6:g} to {data.freq_hz[-1] / 1e6:g} MHz")
    stem = series[0].name if len(series) == 1 else "s11"

    if marks:
        say("Marking " + ", ".join(f"{m:g}" for m in sorted(marks)) + " MHz")
    figures = {}
    if "db" in args.plots:
        say("Building dB plot...")
        figures["db"] = make_s11_figure(series, threshold_db=args.threshold, mark_mhz=marks)
    if "smith" in args.plots:
        say("Building Smith chart...")
        figures["smith"] = make_smith_figure(series, threshold_db=args.threshold,
                                             mark_mhz=marks)

    if args.save_dir:
        args.save_dir.mkdir(parents=True, exist_ok=True)
        for kind, fig in figures.items():
            out = args.save_dir / f"{stem}_{kind}.png"
            say(f"Saving {out}...")
            fig.savefig(out, dpi=150)
        say(f"Done: {len(figures)} file(s) saved to {args.save_dir} in {elapsed():.1f} s")
    else:
        say(f"Showing {len(figures)} figure window(s) - close them to exit.")
        plt.show()
        say("Done")


if __name__ == "__main__":
    main()
