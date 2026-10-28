# Antenna

Python tools for plotting and analyzing antenna measurements:

- **Return loss / S11** from Touchstone `.s1p` files: dB-vs-frequency plot and Smith chart.
- **Radiation patterns** from per-frequency gain CSVs: polar and rectangular cuts, with the
  polarizations overlaid and an optional smoothing filter.

## Setup

Requires Python 3.10+ (developed on 3.14, Windows).

```powershell
python -m venv antenna.venv
.\antenna.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

The editable install (`-e`) makes `import antenna` work from anywhere, including the scripts.
Dependencies are numpy, scipy, matplotlib and scikit-rf; `[dev]` adds pytest.

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
│   └── plotting.py           # matplotlib drawing, plus helpers that build whole figures
├── scripts/                  # thin command-line wrappers
│   ├── plot_s11.py
│   └── plot_patterns.py
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
- **Smoothing** (`--smooth`) is a sliding window across angle, averaged in linear power and wrapped
  around the seam. The window is rounded to an odd number of samples, and the plot title shows the
  width actually used. Smoothing lowers peaks, so quote peak gain from the unsmoothed data.

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
```

Saved filenames look like `01_db.png`, `01_smith.png` and `2450MHz_XY_polar.png`
(`..._smooth<N>` is appended when smoothing is on).

The scripts print timestamped progress (loading libraries, reading each file, building each
figure) and stop with a one-line `error:` message for problems such as a mistyped path or a
folder with no CSVs directly inside it. Pattern folders are not searched recursively: point at the
folder that holds the CSVs, for example `data/01_pattern`.

### `plot_s11.py --help`

```text
usage: plot_s11.py [-h] [--plots {db,smith} [{db,smith} ...]] [--threshold THRESHOLD]
                   [--mark MHZ [MHZ ...]] [--no-marks] [--save-dir SAVE_DIR]
                   files [files ...]

Plot S11 from one or more .s1p files: a dB-vs-frequency plot and a Smith chart.

    python scripts/plot_s11.py data/01.S1P
    python scripts/plot_s11.py data/a.s1p data/b.s1p --mark 2400 2450 2480
    python scripts/plot_s11.py data/01.S1P --plots smith --save-dir output

By default the plots are marked at the 2.4 GHz Wi-Fi band edges and center
(2400, 2442 and 2483 MHz). Use --mark to choose other frequencies (MHz), or
--no-marks to turn the markers off.

positional arguments:
  files                 .s1p file(s); several files are overlaid

options:
  -h, --help            show this help message and exit
  --plots {db,smith} [{db,smith} ...]
                        which plots to make (default: both)
  --threshold THRESHOLD
                        dB level for the reference line / shaded bands / Smith circle (default -10)
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

## Performance

Plotting itself takes a second or two per figure; most of the wait is Python loading numpy,
scipy and matplotlib at startup. If the virtual environment lives in a Google Drive (or other
synced or network) folder, those loads can take 30 seconds or more, versus a fraction of a second
from a local disk. The scripts print how long loading took and suggest this fix when it is slow:
create the environment in a local folder instead, then install the project into it.

```powershell
python -m venv C:\venvs\antenna
C:\venvs\antenna\Scripts\Activate.ps1
pip install -e ".[dev]"      # run from the repository root
```

`--help` and path errors are reported before any heavy library is loaded, so they return immediately.

## Tests

```powershell
python -m pytest tests -q
```

The tests build small synthetic `.s1p` and pattern files, so they do not depend on `data/`.

## Open items

- **`L` and `S` tables:** it is not yet confirmed what these represent (possibly circular
  polarizations), so they are excluded from plots by default. Add them with `--pols T H V L S`.
- **H/V labeling vs. the vendor report:** the `GainH` and `GainV` tables are plotted exactly as
  named in the data files, but the report's H and V curves appear to be the reverse. Whether this is
  a different convention or a labeling issue on the vendor side has not been confirmed.
