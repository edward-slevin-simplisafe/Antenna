"""Reader for radiation-pattern CSVs: one file per frequency, one table per polarization.

Layout of each file (blank cells omitted):

    GainT,,Gain:,3.07,...        <- table name (Gain<key>), optional peak gain
    Theta-Phi,0,5,10,...,360     <- phi values across
    0,-3.13,-3.10,...            <- theta value, then gain (dB) for each phi
    5,...
    GainH,...                    <- next table
"""

import csv
import glob
import re
from pathlib import Path

from antenna.models import Pattern

_FREQ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GHz|MHz|kHz|Hz)", re.IGNORECASE)
_FREQ_UNITS = {"ghz": 1e9, "mhz": 1e6, "khz": 1e3, "hz": 1.0}
_TABLE_RE = re.compile(r"^Gain(\w+)$", re.IGNORECASE)


def freq_from_filename(path) -> float | None:
    """'01-2400.000000MHz.csv' -> 2.4e9, or None if no frequency is in the name."""
    m = _FREQ_RE.search(Path(path).name)
    if not m:
        return None
    return float(m.group(1)) * _FREQ_UNITS[m.group(2).lower()]


def _floats(cells) -> list[float]:
    return [float(c) for c in cells if c.strip() != ""]


def read_pattern(path, freq_hz: float | None = None) -> Pattern:
    import numpy as np  # lazy so path checks (find_pattern_files) don't wait for numpy to load

    path = Path(path)
    if freq_hz is None:
        freq_hz = freq_from_filename(path)
    if freq_hz is None:
        raise ValueError(f"{path.name}: no frequency in filename; pass freq_hz explicitly")

    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.reader(f))

    gain_db, peak_db = {}, {}
    theta = phi = None
    i = 0
    while i < len(rows):
        cells = rows[i]
        m = _TABLE_RE.match(cells[0].strip()) if cells else None
        nxt = rows[i + 1] if i + 1 < len(rows) else []
        if not (m and nxt and nxt[0].strip().lower().startswith("theta")):
            i += 1
            continue

        key = m.group(1).upper()
        stripped = [c.strip() for c in cells]
        if "Gain:" in stripped:
            j = stripped.index("Gain:") + 1
            if j < len(stripped) and stripped[j] != "":
                peak_db[key] = float(stripped[j])

        tbl_phi = np.array(_floats(nxt[1:]))
        tbl_theta, tbl_rows = [], []
        i += 2
        while i < len(rows) and rows[i] and rows[i][0].strip() != "":
            try:
                tbl_theta.append(float(rows[i][0]))
            except ValueError:
                break  # start of the next table
            vals = _floats(rows[i][1:])
            if len(vals) != len(tbl_phi):
                raise ValueError(
                    f"{path.name}: table Gain{key}, theta={tbl_theta[-1]:g} has "
                    f"{len(vals)} values, expected {len(tbl_phi)}"
                )
            tbl_rows.append(vals)
            i += 1

        tbl_theta = np.array(tbl_theta)
        if theta is None:
            theta, phi = tbl_theta, tbl_phi
        elif not (np.array_equal(theta, tbl_theta) and np.array_equal(phi, tbl_phi)):
            raise ValueError(f"{path.name}: table Gain{key} uses a different theta/phi grid")
        gain_db[key] = np.array(tbl_rows)

    if not gain_db:
        raise ValueError(f"{path.name}: no 'Gain<X>' tables found")

    return Pattern(
        freq_hz=freq_hz,
        theta_deg=theta,
        phi_deg=phi,
        gain_db=gain_db,
        peak_db=peak_db,
        name=path.stem,
    )


def find_pattern_files(inputs) -> list[Path]:
    """Expand files, directories (*.csv) and glob patterns into a de-duplicated path list."""
    found = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            csvs = sorted(p.glob("*.csv"))
            if not csvs:
                subs = sorted(d for d in p.iterdir() if d.is_dir() and any(d.glob("*.csv")))
                hint = (" Subfolders that do contain CSVs: " + ", ".join(str(d) for d in subs)
                        if subs else "")
                raise FileNotFoundError(f"no .csv files directly inside '{p}'.{hint}")
            found += csvs
        elif p.is_file():
            found.append(p)
        else:
            matches = glob.glob(str(item))
            if not matches:
                raise FileNotFoundError(f"no file or folder matches '{item}'")
            found += [Path(m) for m in sorted(matches)]
    return list(dict.fromkeys(found))


def load_patterns(inputs, on_file=None) -> list[Pattern]:
    """Read every pattern file and return them sorted by frequency.

    on_file(index, total, path), if given, is called just before each file is read (1-based),
    so callers can report progress.
    """
    paths = find_pattern_files(inputs)
    patterns = []
    for i, path in enumerate(paths, 1):
        if on_file:
            on_file(i, len(paths), path)
        patterns.append(read_pattern(path))
    return sorted(patterns, key=lambda pat: pat.freq_hz)
