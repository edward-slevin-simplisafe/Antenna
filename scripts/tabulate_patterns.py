"""Tabulate radiation-pattern gains into a CSV file (no plots), one row per frequency.

For each pattern file it records the peak total (H+V) gain with the theta and phi where it
occurs and which side of the device that is, and the total gain toward each side of the device.

    python scripts/tabulate_patterns.py data/v1p9/v1p9-A_pattern
    python scripts/tabulate_patterns.py data/v1p9/v1p9-A_pattern --output output/v1p9-A.csv
    python scripts/tabulate_patterns.py "data/v1p9/v1p9-A_pattern/v1p9_A-24[45]*.csv"
    python scripts/tabulate_patterns.py data/v1p9/v1p9-A_pattern --vendor data/v1p9/vendor_report_v1.9.csv

Sides of the device (set in ORIENTATION in antenna/models.py; Right and Left are as seen from
the front):
    Front = -Y   Rear = +Y   Right = +X   Left = -X   Top = +Z   Bottom = -Z
Theta is measured from +Z and phi from +X toward +Y, so for example Right is (theta 90, phi 0)
and Front is (theta 90, phi 270).

The peak direction is named from theta (Top above the horizon, Bottom below) and the quadrant
of phi, for example "Bottom-Front-Left". A peak within 22.5 degrees of an axis is named by that
side alone ("Front", "Top"), and near the horizon no Top/Bottom word is used.

Gains are in dBi. The on-axis columns (Front(-Y)_gain_dBi, ...) are the gain measured exactly
toward each side: Front, Rear, Right and Left are measured grid points. At the poles (Top,
Bottom) the measured gain varies with phi, so those two are the power average over all phi; the
terminal output says how large that variation is. The peak is the highest measured grid point;
if it falls at a pole, phi is reported as the first grid value.

The half-sphere columns (Front(-Y)_half_avg_dBi, ...) are the average gain over the half of the
sphere facing each side, to show which side radiates more overall, not just along one line. The
average is taken in linear power, with each measured point weighted by the area it covers on
the sphere (sin theta); points on the dividing circle count half in each half.

Summary numbers: Front_minus_Rear_dB, Right_minus_Left_dB and Top_minus_Bottom_dB are the
half-sphere average of the first side minus that of the second, so a positive value means the
first side is stronger. efficiency_from_gain_pct is 100 times the average of the linear gain over
the whole sphere. That equals the antenna efficiency (radiated power / input power) when the gain
is absolute, meaning referenced to the power fed to the antenna, as chamber gain normally is. It
can differ from an efficiency a vendor reports, depending on how that is defined and measured.

Vendor comparison (optional): --vendor FILE reads the numbers from a vendor's test report and
shows them beside ours: peak gain and efficiency, and the difference (ours minus the vendor's;
for efficiency, our value over theirs in dB). FILE is a CSV with the columns freq_MHz,
peak_gain_dBi and efficiency_pct, one row per frequency. Lines starting with # are comments and
a blank cell means the vendor gave no number. The columns are added to the output CSV as well.

Files may be given as paths, directories (all *.csv directly inside) or glob patterns. The
frequency is read from the filename (e.g. v1p9_A-2400.000000MHz.csv).
"""

import argparse
import sys
import time
from pathlib import Path

from antenna.feedback import elapsed, say, tip_if_slow
from antenna.readers.pattern import find_pattern_files, freq_from_filename, load_patterns


def default_output(inputs) -> Path:
    """output/<folder>_summary.csv when given a folder, else output/pattern_summary.csv."""
    first = Path(inputs[0])
    stem = first.name if first.is_dir() else "pattern"
    return Path("output") / f"{stem}_summary.csv"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="pattern CSV files, directories or globs")
    ap.add_argument("-o", "--output", type=Path,
                    help="CSV file to write (default: output/<folder name>_summary.csv)")
    ap.add_argument("--vendor", type=Path, metavar="FILE",
                    help="CSV of the vendor report's peak gain and efficiency "
                         "(freq_MHz, peak_gain_dBi, efficiency_pct) to compare with")
    args = ap.parse_args()
    if args.vendor and not args.vendor.is_file():  # fail fast, before the library load
        sys.exit(f"error: {args.vendor}: vendor report file not found")

    try:  # fail fast on a typo, before the library load
        files = find_pattern_files(args.inputs)
    except FileNotFoundError as err:
        sys.exit(f"error: {err}")
    say(f"Found {len(files)} pattern file(s)")

    say("Loading libraries (numpy, scipy)...")
    t0 = time.perf_counter()
    from antenna import tables

    load_s = time.perf_counter() - t0
    say(f"Libraries loaded in {load_s:.1f} s")
    tip_if_slow(load_s)

    def reading(i, total, path):
        freq = freq_from_filename(path)
        say(f"Reading {path.name} ({i}/{total})" + (f" - {freq / 1e6:g} MHz" if freq else ""))

    try:
        patterns = load_patterns(files, on_file=reading)
        say("Computing peak gain and the gain in each major direction...")
        rows = tables.summary_rows(patterns)
        if args.vendor:
            say(f"Reading vendor report numbers from {args.vendor}")
            rows = tables.add_vendor_columns(rows, tables.read_vendor_report(args.vendor))
    except (FileNotFoundError, ValueError, KeyError) as err:
        sys.exit(f"error: {err}")

    print("\nTotal (H+V) gain in dBi; Theta and Phi (of the peak) in degrees")
    print(tables.orientation_note())
    print("\nPeak gain, and the gain measured exactly toward each side (on-axis):\n")
    print(tables.format_table(rows))
    print("\nHalf-sphere average gain (dBi): the power-averaged gain over the half of the sphere "
          "facing each side:\n")
    print(tables.format_half_table(rows))
    print("\nSummary: how much stronger one side is than its opposite (half-sphere averages), and "
          "the efficiency:\n")
    print(tables.format_summary_table(rows))
    print("\n" + tables.summary_note(rows))
    if args.vendor:
        print("\nComparison with the vendor report (our peak gain and efficiency vs. theirs):\n")
        print(tables.format_vendor_table(rows))
        print("\n" + tables.vendor_note(rows))
    note = tables.pole_note(rows)
    print(f"\n{note}\n" if note else "")

    out = args.output or default_output(args.inputs)
    tables.write_csv(rows, out)
    say(f"Done: {len(rows)} row(s) written to {out} in {elapsed():.1f} s")


if __name__ == "__main__":
    main()
