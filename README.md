# Antenna

Python tools for plotting and analyzing antenna measurements:

- **Return loss / S11** from Touchstone `.s1p` files: dB-vs-frequency plot and Smith chart.
- **Radiation patterns** from per-frequency gain CSVs: polar and rectangular cuts, with the
  polarizations overlaid and an optional smoothing filter.

## Setup

Requires Python 3.10+ (developed on 3.14, Windows).

Create the virtual environment in a **local** folder, outside the repository, then install the
project into it from the repository root (the folder containing `pyproject.toml`):

```powershell
python -m venv C:\venvs\antenna
C:\venvs\antenna\Scripts\Activate.ps1
cd <path to this repository>
pip install -e ".[dev]"
```

Activating the environment (the second line) makes `python` and `pip` in that terminal use it;
the prompt then starts with `(antenna)`. Activate it again in each new terminal, or in VS Code
choose **Python: Select Interpreter** and enter `C:\venvs\antenna\Scripts\python.exe` so new
terminals activate it automatically.

The editable install (`-e`) makes `import antenna` work from anywhere, including the scripts, and
code changes take effect without reinstalling. Dependencies are numpy, scipy, matplotlib and
scikit-rf; `[dev]` adds pytest.

Keep the environment off Google Drive and other synced or network folders: thousands of small
files there make Python start very slowly (see [Performance](#performance)). If you work on another
machine, create a separate environment there; environments are not portable between machines.

## How the code is organized

The code is split into layers so the same functions can serve scripts today and a GUI later.
Nothing below the scripts opens a window or reads the command line.

```
Antenna/
├── antenna/                  # the library
│   ├── models.py             # data containers (S11Data, Pattern) and shared constants
│   ├── readers/
│   │   ├── touchstone.py     # .s1p  -> S11Data        (scikit-rf)
│   │   └── pattern.py        # .csv  -> Pattern        (one file per frequency)
│   ├── analysis.py           # pure numeric functions, no file I/O and no plotting
│   ├── feedback.py           # timestamped progress messages for the scripts
│   ├── tables.py             # per-frequency gain summary table (rows, CSV, terminal text)
│   └── plotting.py           # matplotlib drawing, plus helpers that build whole figures
├── scripts/                  # thin command-line wrappers
│   ├── plot_s11.py
│   ├── plot_patterns.py
│   └── tabulate_patterns.py  # gain summary table, no plots
├── tests/                    # pytest; uses small synthetic files, not your data
├── data/                     # your measurements (not tracked by git)
├── output/                   # saved plots (ignored by git)
└── pyproject.toml
```

| Layer | Responsibility | Notes |
|---|---|---|
| **readers** | Turn files into plain data objects. | No plotting. `read_s1p` accepts only `.s1p` files. Pattern frequency is read from the filename. |
| **models** | `S11Data`, `Pattern`, and constants. | Constants include trace colors and labels, the gain limit, the principal planes, and the Wi-Fi marker frequencies. |
| **analysis** | S11 in dB, VSWR, bandwidth below a threshold, pattern cuts, peak gain, smoothing. | Pure functions of numpy arrays, so they are easy to test and reuse. |
| **plotting** | `plot_*` functions draw on an `Axes` you pass in; `make_*_figure` functions build a complete figure. | Because the plot functions take an `Axes`, they can be embedded in a GUI canvas unchanged. |
| **scripts** | Parse arguments, load, call plotting, save or show, and print progress. | Keep these thin. |

## Data formats

**S11:** a standard Touchstone one-port file (`.s1p`, any frequency unit or RI/MA/DB format).

**Radiation patterns:** one CSV per frequency, with the frequency in the filename
(for example `01-2400.000000MHz.csv`). Each file holds one table per polarization:

```
GainT,,Gain:,3.07,...          <- table name (Gain<key>) and its peak gain
Theta-Phi,0,5,10,...,360       <- phi values across
0,-3.13,-3.10,...              <- theta value, then gain (dB) at each phi
5,...
GainH,...                      <- next table
```

The tables currently in use are `T` (total, labeled **H+V** in plots), `H` and `V`. The `L` and `S`
tables are read but not plotted by default (see Open items).

**Vendor report numbers (optional, for `tabulate_patterns.py --vendor`):** a small CSV you write
from a vendor's test report, one row per frequency. Lines starting with `#` are comments, and a
blank cell means the vendor gave no number for that frequency:

```
# source: vendor test report, "Peak Gain & Efficiency" table
freq_MHz,peak_gain_dBi,efficiency_pct
2400,3.07,57.95
2410,3.11,58.23
```

The sample file `data/vendor_report_v1.9.csv` lives with your other data and is not tracked by git.

## Conventions

- **Angles:** theta is measured from +Z and phi from +X toward +Y.
- **Principal planes:** `XY` is the theta = 90 cut, `XZ` is phi = 0 and `YZ` is phi = 90.
- **Phi cuts** sweep theta over -180 to 180: positive angles are on the phi side of the cut, negative
  angles on the phi+180 side. They are drawn with 0 degrees at the top, increasing clockwise.
- **Theta cuts** (the XY plane) sweep phi and are drawn top-down: 0 degrees at +X, increasing
  counterclockwise, matching the vendor report's XY view.
- **Colors** follow the vendor test report: H light green, V red, H+V dark blue.
- **Gain axis:** by default the top is the highest gain rounded up to a multiple of 5 dB and the
  bottom is `--range` (40 dB) below it. `--rmax` and `--rmin` set the limits explicitly on both
  polar and rectangular plots (for example `--rmax 5 --rmin -45` matches the vendor report). A lone
  `--rmax` puts the bottom `--range` below it; a lone `--rmin` keeps the top automatic.
- **Gain limit:** a dashed 4 dB line is drawn on rectangular plots (`--gain-limit`, `--no-gain-limit`).
- **S11 markers** default to the 2.4 GHz Wi-Fi band edges and center: 2400, 2442 and 2483 MHz.
- **S11 shading:** the dB plot shades the 2.4 GHz Wi-Fi band covering channels 1-13
  (2400-2483.5 MHz) and lists it in the legend; `--band LOW HIGH` or `--no-band` changes it.
  `--ymin` and `--ymax` set the dB axis limits (either may be given alone).
- **Gain table** (`tabulate_patterns.py`): one row per frequency with the peak total (H+V) gain,
  the theta and phi where it occurs, which side of the device that is, and the total gain toward
  each side, written to `output/<folder>_summary.csv` and printed in the terminal.
  - **Device sides:** Front = -Y, Rear = +Y, Right = +X, Left = -X (right and left as seen from
    the front), Top = +Z and Bottom = -Z. They are set in one place, `ORIENTATION` in
    `antenna/models.py`; if the measurement orientation changes, edit that table and the column
    headers and peak-direction wording follow. CSV columns look like `Front(-Y)_gain_dBi`.
  - **Peak direction:** named from theta (Top above the horizon, Bottom below) and the quadrant of
    phi, for example `Bottom-Front-Left` (theta 135, phi 240). A peak within 22.5 degrees of an
    axis is named by that side alone (`Front`, `Top`), and near the horizon there is no
    Top/Bottom word.
  - **Half-sphere averages:** a second set of columns (`Front(-Y)_half_avg_dBi`, ...) gives the
    average gain over the half of the sphere facing each side, to show which side radiates more
    overall. See [Reading the gain table](#reading-the-gain-table).
  - **Summary numbers:** `Front_minus_Rear_dB`, `Right_minus_Left_dB` and `Top_minus_Bottom_dB` are
    the half-sphere average of the first side minus that of the second (positive means the first
    side is stronger), and `efficiency_from_gain_pct` is the average of the linear gain over the
    whole sphere, as a percentage. See the efficiency caveat below and in Open items.
  - **Values:** Front, Rear, Right and Left are measured grid points. The measured gain at the
    poles (Top, Bottom) varies with phi (up to about 3 dB in the sample data), so those two are
    the power average over all phi, and the script prints a note saying how large the variation
    is.
- **Pattern text and ticks:** axis labels, tick labels, legends and titles are larger than the
  matplotlib default, and polar plots have a grid line and label every 10 degrees.
- **Smoothing** (`--smooth`) is a sliding window across angle, averaged in linear power and wrapped
  around the seam. The window is rounded to an odd number of samples, and the plot title shows the
  width actually used. Smoothing lowers peaks, so quote peak gain from the unsmoothed data.

## Reading the gain table

This explains `tabulate_patterns.py` in plain language, for anyone who did not see the raw data.

**What was measured.** The antenna was measured in an anechoic chamber, with one data file per
frequency. The chamber records the gain in dBi on a 5 degree grid covering the whole sphere around
the device: theta is the angle down from the top of the device (0 to 180 degrees) and phi is the
angle around it (0 to 360 degrees). We use the total gain, which is the sum of the horizontally and
vertically polarized power (H+V).

**Sides of the device.** For the doorbell camera: Front = -Y, Rear = +Y, Right = +X and Left = -X
(right and left as seen from the front), Top = +Z and Bottom = -Z.

**Peak gain.** The highest gain on the grid, the theta and phi where it occurs, and a plain
direction. Theta says Top or Bottom (above or below the horizon), and phi says which of the four
horizontal quadrants it is in, for example "Bottom-Front-Left". A peak close to one axis is named by
that side alone, such as "Front".

**Gain toward each side (on-axis).** The gain measured exactly in the direction of each side. Each
is a single direction, so it is sensitive to ripple in the pattern: a narrow dip right on an axis
makes that side look weak even if the side as a whole radiates well. Top and Bottom are the poles,
where the measured gain varies a little with phi, so those two are averaged over phi.

**Half-sphere average gain.** To compare sides more fairly, the sphere is split in half three ways
(front/rear, right/left, top/bottom) and the gain is averaged over each half. Two details keep this
honest. Each measured point is weighted by the area of the sphere it stands for, because near the
poles a grid point covers very little area. And the averaging is done in power, not in dB, because
an average of dB values lets deep nulls dominate. A half-sphere average answers "which side
radiates more overall?". It is a comparison between sides, not an efficiency; for efficiency use the
figure the vendor reports.

**Summary numbers.** Three columns compare opposite sides: Front minus Rear, Right minus Left, and Top
minus Bottom, each the difference between the two half-sphere averages in dB. A positive number
means the first side is stronger and a negative number means the second is. For example, "Front
minus Rear = 3.7 dB" says that on average the front half of the sphere has 3.7 dB more gain than
the rear half. A number near zero means the two sides are about equally strong.

**Efficiency.** Gain in dBi is measured relative to the power fed to the antenna, so averaging the
gain over the whole sphere gives the fraction of that power which is radiated: the antenna
efficiency. This only works because the chamber reports absolute gain, calibrated against a
reference antenna of known gain. Efficiency is computed here from the measured gain and is not
read from any file. It can come out different from an efficiency a vendor reports, depending on how
the vendor defines and measures it, so quote the vendor's figure when you need theirs and treat
this one as a cross-check (see Open items).

**Reading them together.** The peak shows where the strongest lobe is. The on-axis values show what
you get along exactly those lines. The half-sphere averages and the differences show which side is
stronger overall. They can disagree, and that is information about the pattern, not an error. At
2450 MHz the peak (3.41 dBi) is toward Bottom-Front-Left, between the axes. On the axes Top
(-2.19 dBi) is higher than Bottom (-3.66 dBi), but averaged over each half Bottom (-1.99 dBi) is
stronger than Top (-3.74 dBi), which agrees with the peak. Across 2400 to 2500 MHz the front half
averages 4.7 dB above the rear at 2400 MHz, falling to 2.0 dB at 2500 MHz; the bottom half averages
1.4 to 1.75 dB above the top; and Right and Left stay within 0.3 dB of each other, so the larger
on-axis difference between them reflects the shape of the pattern in those two directions, not a
stronger side.

## Usage

Run the scripts from the repository root with the virtual environment active. Without
`--save-dir`, figures open in interactive windows; with it, PNGs are written to that folder
(existing files with the same name are overwritten).

```powershell
# S11: dB plot and Smith chart with the default Wi-Fi markers
python scripts/plot_s11.py data/01.S1P

# Radiation patterns: the three principal planes for every CSV in a sample's folder
python scripts/plot_patterns.py data/01_pattern --plane XY XZ YZ --save-dir output

# Same, smoothed with a 20 degree window
python scripts/plot_patterns.py data/01_pattern --plane XY XZ YZ --smooth 20 --save-dir output

# Gain table (no plots): peak, gain toward and averaged over each side, side-to-side differences, efficiency
python scripts/tabulate_patterns.py data/01_pattern

# Same, with our peak gain and efficiency shown beside the vendor report's
python scripts/tabulate_patterns.py data/01_pattern --vendor data/vendor_report_v1.9.csv
```

Saved filenames look like `01_db.png`, `01_smith.png` and `2450MHz_XY_polar.png`
(`..._smooth<N>` is appended when smoothing is on).

The scripts print timestamped progress (loading libraries, reading each file, building each
figure) and stop with a one-line `error:` message for problems such as a mistyped path or a
folder with no CSVs directly inside it. Pattern folders are not searched recursively: point at the
folder that holds the CSVs, for example `data/01_pattern`.

### `plot_s11.py --help`

```text
usage: plot_s11.py [-h] [--plots {db,smith} [{db,smith} ...]] [--threshold THRESHOLD] [--ymax DB]
                   [--ymin DB] [--band LOW HIGH] [--no-band] [--mark MHZ [MHZ ...]] [--no-marks]
                   [--save-dir SAVE_DIR]
                   files [files ...]

Plot S11 from one or more .s1p files: a dB-vs-frequency plot and a Smith chart.

    python scripts/plot_s11.py data/01.S1P
    python scripts/plot_s11.py data/a.s1p data/b.s1p --mark 2400 2450 2480
    python scripts/plot_s11.py data/01.S1P --plots smith --save-dir output
    python scripts/plot_s11.py data/01.S1P --plots db --ymin -30 --ymax 0

By default the plots are marked at the 2.4 GHz Wi-Fi band edges and center
(2400, 2442 and 2483 MHz). Use --mark to choose other frequencies (MHz), or
--no-marks to turn the markers off. The dB plot shades the 2.4 GHz Wi-Fi band
(CH 1-13, 2400-2483.5 MHz); use --band LOW HIGH to shade another range or
--no-band to turn the shading off.

positional arguments:
  files                 .s1p file(s); several files are overlaid

options:
  -h, --help            show this help message and exit
  --plots {db,smith} [{db,smith} ...]
                        which plots to make (default: both)
  --threshold THRESHOLD
                        dB level for the dashed reference line and the Smith circle (default -10)
  --ymax DB             top of the S11 axis in dB (dB plot only; default: automatic)
  --ymin DB             bottom of the S11 axis in dB (dB plot only; default: automatic)
  --band LOW HIGH       frequency range (MHz) to shade on the dB plot (default: 2400 2483.5, the 2.4 GHz Wi-Fi band, CH 1-13)
  --no-band             shade no frequency band
  --mark MHZ [MHZ ...]  frequencies (MHz) to mark on every plot (default: 2400, 2442, 2483)
  --no-marks            draw no frequency markers
  --save-dir SAVE_DIR   save PNGs here instead of showing
```

### `plot_patterns.py --help`

```text
usage: plot_patterns.py [-h] [--plane {XY,XZ,YZ} [{XY,XZ,YZ} ...]] [--cut {phi,theta}]
                        [--angles ANGLES [ANGLES ...]] [--kind {polar,rect} [{polar,rect} ...]]
                        [--pols POLS [POLS ...]] [--smooth [DEG]] [--range DYN_RANGE] [--rmax DB]
                        [--rmin DB] [--gain-limit DB] [--no-gain-limit] [--save-dir SAVE_DIR]
                        inputs [inputs ...]

Plot radiation-pattern cuts, one figure per frequency, polarizations overlaid.

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

positional arguments:
  inputs                pattern CSV files, directories or globs

options:
  -h, --help            show this help message and exit
  --plane {XY,XZ,YZ} [{XY,XZ,YZ} ...]
                        principal plane(s) to plot: XY, XZ, YZ
  --cut {phi,theta}     phi: fixed phi, sweep theta.  theta: fixed theta, sweep phi
  --angles ANGLES [ANGLES ...]
                        fixed angle(s) in degrees for --cut, one set of figures per value
  --kind {polar,rect} [{polar,rect} ...]
  --pols POLS [POLS ...]
                        table keys to overlay (default: T H V)
  --smooth [DEG]        sliding-window smoothing across angle: omit = off, bare --smooth = 10 deg,
                        --smooth 20 = 20 deg window. Averaged in linear power, wraps at the seam; the
                        window is rounded to an odd number of samples (5 deg grid: 20 -> 25 deg),
                        and the plot title shows the width actually used
  --range DYN_RANGE     plot dynamic range in dB below the top (default 40; unused if --rmin is given)
  --rmax DB             top of the gain axis in dB (default: highest gain rounded up to a multiple of 5)
  --rmin DB             bottom of the gain axis in dB (default: --range below the top)
  --gain-limit DB       dashed max-gain requirement line on rectangular plots (default 4)
  --no-gain-limit       omit the gain limit line
  --save-dir SAVE_DIR   save PNGs here instead of showing
```

### `tabulate_patterns.py --help`

```text
usage: tabulate_patterns.py [-h] [-o OUTPUT] [--vendor FILE] inputs [inputs ...]

Tabulate radiation-pattern gains into a CSV file (no plots), one row per frequency.

For each pattern file it records the peak total (H+V) gain with the theta and phi where it
occurs and which side of the device that is, and the total gain toward each side of the device.

    python scripts/tabulate_patterns.py data/01_pattern
    python scripts/tabulate_patterns.py data/01_pattern --output output/sample1.csv
    python scripts/tabulate_patterns.py "data/01_pattern/01-24[45]*.csv"
    python scripts/tabulate_patterns.py data/01_pattern --vendor data/vendor_report_v1.9.csv

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
frequency is read from the filename (e.g. 01-2400.000000MHz.csv).

positional arguments:
  inputs               pattern CSV files, directories or globs

options:
  -h, --help           show this help message and exit
  -o, --output OUTPUT  CSV file to write (default: output/<folder name>_summary.csv)
  --vendor FILE        CSV of the vendor report's peak gain and efficiency (freq_MHz, peak_gain_dBi, efficiency_pct) to compare with
```

## Performance

Plotting itself takes a second or two per figure; most of the wait is Python loading numpy,
scipy and matplotlib at startup. If the virtual environment lives in a Google Drive (or other
synced or network) folder, those loads can take 30 seconds or more, versus a fraction of a second
from a local disk. The scripts print how long loading took and suggest the fix when it is slow:
recreate the environment in a local folder as described in [Setup](#setup). The project itself can
stay on Drive; only the environment needs to be local.

`--help` and path errors are reported before any heavy library is loaded, so they return immediately.

## Tests

```powershell
python -m pytest tests -q
```

The tests build small synthetic `.s1p` and pattern files, so they do not depend on `data/`.

## Open items

- **Efficiency vs. the vendor report:** `efficiency_from_gain_pct` for the sample data is 47 to 54%
  across 2400-2500 MHz, while the vendor report (Peak Gain & Efficiency table) lists 56 to 64%. The
  ratio is 0.83 to 0.87 at all 11 frequencies, a roughly constant 0.6 to 0.8 dB, and the two follow
  the same shape across the band. Mismatch loss (about 0.04 dB at 2450 MHz and 0.2 dB at 2400 MHz
  from the report's return loss) and the 0.13 dB cable loss are too small to explain it. The cause
  has not been identified; it may be how the vendor defines or measures efficiency, so ask them.
  The peak gain, by contrast, matches the report exactly at every frequency. `--vendor` puts the two
  side by side.
- **Vendor pass/fail criteria:** the report states criteria (peak gain at most 3.5 dBi, efficiency at
  least 55%, return loss below -10 dB over 2400-2500 MHz). They are not applied as pass/fail here.
  Applying the efficiency criterion to `efficiency_from_gain_pct` would mark most of the band as a
  fail where the vendor's own figures pass, until the discrepancy above is understood.
- **`L` and `S` tables:** it is not yet confirmed what these represent (possibly circular
  polarizations), so they are excluded from plots by default. Add them with `--pols T H V L S`.
- **H/V labeling vs. the vendor report:** the `GainH` and `GainV` tables are plotted exactly as
  named in the data files, but the report's H and V curves appear to be the reverse. Whether this is
  a different convention or a labeling issue on the vendor side has not been confirmed.
