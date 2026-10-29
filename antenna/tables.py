"""Tabulate pattern gains: one row per frequency. No plotting."""

import csv
import math
from pathlib import Path

from antenna import analysis
from antenna.models import DIRECTIONS, OPPOSITE_SIDES, ORIENTATION, Pattern

TOTAL = "T"  # the H+V total gain table
GAIN_DECIMALS = 2


def _axis_text(axis: str) -> str:
    """'Y-' -> '-Y' (the usual way to write an axis direction)."""
    return f"{axis[1]}{axis[0]}"


# Side name -> CSV column, e.g. "Front" -> "Front(-Y)_gain_dBi". Dict order follows ORIENTATION.
DIRECTION_COLUMNS = {
    label: f"{label}({_axis_text(axis)})_gain_dBi" for label, axis in ORIENTATION.items()
}

# Side name -> CSV column for the average gain over the half of the sphere facing that side.
HALF_COLUMNS = {
    label: f"{label}({_axis_text(axis)})_half_avg_dBi" for label, axis in ORIENTATION.items()
}

# (first side, second side) -> CSV column holding half-sphere average of first minus second, in dB.
DIFF_COLUMNS = {pair: f"{pair[0]}_minus_{pair[1]}_dB" for pair in OPPOSITE_SIDES}

# Average of the measured gain over the whole sphere, as a percentage. This is the antenna's
# efficiency when the gain is absolute (see analysis.mean_gain_linear); the name says how it is
# derived because it can differ from an efficiency a vendor reports.
EFFICIENCY_COLUMN = "efficiency_from_gain_pct"

# Optional comparison with numbers from a vendor's test report (see read_vendor_report).
# "Diff" columns are ours minus the vendor's; for efficiency that is the ratio, in dB.
VENDOR_PEAK_COLUMN = "vendor_peak_gain_dBi"
VENDOR_EFFICIENCY_COLUMN = "vendor_efficiency_pct"
PEAK_DIFF_COLUMN = "peak_gain_vs_vendor_dB"
EFFICIENCY_DIFF_COLUMN = "efficiency_vs_vendor_dB"
VENDOR_COLUMNS = [VENDOR_PEAK_COLUMN, PEAK_DIFF_COLUMN, VENDOR_EFFICIENCY_COLUMN,
                  EFFICIENCY_DIFF_COLUMN]
VENDOR_MATCH_MHZ = 0.5  # a vendor row matches a pattern file if the frequencies are this close

COLUMNS = (
    ["freq_MHz", "peak_gain_dBi", "peak_theta_deg", "peak_phi_deg", "peak_direction"]
    + list(DIRECTION_COLUMNS.values())
    + list(HALF_COLUMNS.values())
    + list(DIFF_COLUMNS.values())
    + [EFFICIENCY_COLUMN]
)

# Columns written with GAIN_DECIMALS decimals (frequency and angles are written as plain numbers).
_GAIN_SUFFIXES = ("_gain_dBi", "_half_avg_dBi", "_dB", "_pct")

# Sides that lie on a pole of the measurement sphere (Top and Bottom), where phi has no meaning.
POLE_LABELS = [label for label, axis in ORIENTATION.items() if DIRECTIONS[axis][1] is None]


def summary_row(pattern: Pattern, pol: str = TOTAL) -> dict:
    """Peak gain with its angles and direction, and the gain toward each side of the device.

    The peak is the highest measured grid point; if it falls at a pole, phi is the first grid
    value. "peak_direction" names it by the device's sides (analysis.direction_label), for
    example "Bottom-Front-Left". The side gains follow ORIENTATION: Front, Rear, Right and Left
    lie on the measurement grid and are measured values. Top and Bottom are the power average over
    phi, because the measured gain at a pole varies with phi; that variation is kept in the row as
    "<side>_phi_spread_dB" (not a CSV column). The "..._half_avg_dBi" values are the average gain
    over the half of the sphere facing each side (analysis.hemisphere_gain), and each
    "<a>_minus_<b>_dB" is the half-sphere average of side a minus that of its opposite side b, so
    a positive number means a is the stronger side. The efficiency is 100 times the average of the
    linear gain over the whole sphere (analysis.mean_gain_linear).
    """
    if pol not in pattern.gain_db:
        raise ValueError(f"{pattern.name}: no Gain{pol} table (have {pattern.pols})")
    peak, theta, phi = analysis.peak_gain(pattern, pol)
    row = {
        "freq_MHz": pattern.freq_hz / 1e6,
        "peak_gain_dBi": peak,
        "peak_theta_deg": theta,
        "peak_phi_deg": phi,
        "peak_direction": analysis.direction_label(theta, phi),
    }
    for label, axis in ORIENTATION.items():
        th, ph = DIRECTIONS[axis]
        row[DIRECTION_COLUMNS[label]] = analysis.gain_at(pattern, pol, th, ph)
        if ph is None:
            row[f"{label}_phi_spread_dB"] = analysis.phi_spread_db(pattern, pol, th)
        row[HALF_COLUMNS[label]] = analysis.hemisphere_gain(pattern, pol, axis)
    for (first, second), column in DIFF_COLUMNS.items():
        row[column] = row[HALF_COLUMNS[first]] - row[HALF_COLUMNS[second]]
    row[EFFICIENCY_COLUMN] = 100 * analysis.mean_gain_linear(pattern, pol)
    return row


POLE_SPREAD_NOTE_DB = 0.5  # mention the pole variation when it exceeds this


def pole_note(rows: list[dict]) -> str | None:
    """A one-paragraph note when the gain at the poles varies noticeably with phi."""
    spreads = [v for row in rows for k, v in row.items() if k.endswith("_phi_spread_dB")]
    if not spreads or max(spreads) <= POLE_SPREAD_NOTE_DB:
        return None
    sides = " and ".join(POLE_LABELS)
    return (f"Note: the measured gain at the poles varies with phi by up to {max(spreads):.1f} dB, "
            f"so {sides} are the power average over all phi (the other directions are single "
            "measured points).")


def orientation_note() -> str:
    """One line saying which axis each side of the device is, from ORIENTATION."""
    sides = ", ".join(f"{label} = {_axis_text(axis)}" for label, axis in ORIENTATION.items())
    return f"Sides: {sides} (Right and Left as seen from the front)"


def summary_note(rows: list[dict]) -> str:
    """Explains the summary table's numbers, and warns if an efficiency is above 100%."""
    text = ("Each difference is the half-sphere average of the first side minus that of the second "
            "(positive = the first side is stronger). Efficiency is the average of the measured "
            "gain over the whole sphere; it equals the radiated-to-input power ratio when the gain "
            "is absolute (referenced to input power), so it can differ from a figure a vendor "
            "reports, depending on how that is defined and measured.")
    if any(row[EFFICIENCY_COLUMN] > 100.5 for row in rows):
        text += (" WARNING: an efficiency above 100% is not physical, so this gain data may not "
                 "be absolute (for example it may be normalized or a directivity).")
    return "Note: " + text


def _optional_float(cell: str) -> float | None:
    cell = (cell or "").strip()
    return float(cell) if cell else None


def read_vendor_report(path) -> dict[float, dict]:
    """Read numbers from a vendor's test report: a CSV with the columns freq_MHz, peak_gain_dBi
    and efficiency_pct, one row per frequency. Blank lines and lines starting with '#' are
    ignored, and a blank cell means the vendor gave no number. Returns {freq_MHz: {...}}."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path}: vendor report file not found")
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    missing = {"freq_MHz", "peak_gain_dBi", "efficiency_pct"} - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {', '.join(sorted(missing))} "
                         "(need freq_MHz, peak_gain_dBi, efficiency_pct)")
    vendor = {}
    for row in reader:
        try:
            vendor[float(row["freq_MHz"])] = {
                "peak_gain_dBi": _optional_float(row["peak_gain_dBi"]),
                "efficiency_pct": _optional_float(row["efficiency_pct"]),
            }
        except (TypeError, ValueError):
            raise ValueError(f"{path.name}: not a number in the row for {row['freq_MHz']!r} MHz")
    return vendor


def add_vendor_columns(rows: list[dict], vendor: dict[float, dict]) -> list[dict]:
    """Copies of the rows with the vendor's peak gain and efficiency beside ours, and the
    differences (ours minus the vendor's; for efficiency the ratio in dB). Frequencies the
    vendor did not report get None."""
    out = []
    for row in rows:
        near = [f for f in vendor if abs(f - row["freq_MHz"]) <= VENDOR_MATCH_MHZ]
        ref = vendor[min(near, key=lambda f: abs(f - row["freq_MHz"]))] if near else {}
        peak, eff = ref.get("peak_gain_dBi"), ref.get("efficiency_pct")
        new = dict(row)
        new[VENDOR_PEAK_COLUMN] = peak
        new[PEAK_DIFF_COLUMN] = None if peak is None else row["peak_gain_dBi"] - peak
        new[VENDOR_EFFICIENCY_COLUMN] = eff
        new[EFFICIENCY_DIFF_COLUMN] = (
            None if not eff else 10 * math.log10(row[EFFICIENCY_COLUMN] / eff))
        out.append(new)
    return out


def vendor_note(rows: list[dict]) -> str:
    """Says how many frequencies were compared and how far apart the numbers are."""
    def span(column):
        values = [round(r[column], GAIN_DECIMALS) + 0.0 for r in rows if r.get(column) is not None]
        if not values:
            return None
        lo, hi = min(values), max(values)

        def fmt(v):
            return "0.00" if v == 0 else f"{v:+.2f}"

        return f"{fmt(lo)} dB" if lo == hi else f"{fmt(lo)} to {fmt(hi)} dB"

    compared = sum(r.get(VENDOR_PEAK_COLUMN) is not None or r.get(VENDOR_EFFICIENCY_COLUMN)
                   is not None for r in rows)
    parts = [f"Vendor numbers were found for {compared} of {len(rows)} frequencies. "
             "Diff is ours minus the vendor's (for efficiency, our value over theirs, in dB)."]
    if span(PEAK_DIFF_COLUMN):
        parts.append(f"Peak gain differs by {span(PEAK_DIFF_COLUMN)}.")
    if span(EFFICIENCY_DIFF_COLUMN):
        parts.append(f"Efficiency differs by {span(EFFICIENCY_DIFF_COLUMN)}.")
    return "Note: " + " ".join(parts)


def summary_rows(patterns: list[Pattern], pol: str = TOTAL) -> list[dict]:
    return [summary_row(p, pol) for p in patterns]


def _text(column: str, value, missing: str = "") -> str:
    """Rounded text for a CSV cell or terminal table; `missing` stands in for None."""
    if value is None:
        return missing
    if isinstance(value, str):
        return value
    if column.endswith(_GAIN_SUFFIXES):
        return f"{round(value, GAIN_DECIMALS) + 0.0:.{GAIN_DECIMALS}f}"  # + 0.0: no "-0.00"
    return f"{value:g}"  # frequency and angles


def write_csv(rows: list[dict], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        columns = COLUMNS + (VENDOR_COLUMNS if rows and VENDOR_PEAK_COLUMN in rows[0] else [])
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_text(c, row[c]) for c in columns])
    return path


def _render(rows: list[dict], columns: list[str], top: list[str], sub: list[str]) -> str:
    """Fixed-width text table: a two-line header, right-aligned cells, and the peak direction
    (text) left-aligned."""
    body = [[_text(c, row[c], missing="-") for c in columns] for row in rows]
    widths = [max(len(top[i]), len(sub[i]), *(len(r[i]) for r in body)) for i in range(len(top))]

    def line(cells):
        return "  ".join(
            c.ljust(w) if columns[i] == "peak_direction" else c.rjust(w)
            for i, (c, w) in enumerate(zip(cells, widths))
        ).rstrip()

    return "\n".join([line(top), line(sub)] + [line(r) for r in body])


def _axes_line() -> list[str]:
    return [f"({_axis_text(axis)})" for axis in ORIENTATION.values()]


def format_table(rows: list[dict]) -> str:
    """Terminal table of the peak and the on-axis gain toward each side. Side names sit over
    their axes, and units sit under Peak, Theta and Phi."""
    columns = COLUMNS[:5] + list(DIRECTION_COLUMNS.values())
    top = ["MHz", "Peak", "Theta", "Phi", "Peak direction"] + list(ORIENTATION)
    sub = ["", "dBi", "deg", "deg", ""] + _axes_line()
    return _render(rows, columns, top, sub)


def format_summary_table(rows: list[dict]) -> str:
    """Terminal table of the side-to-side differences (dB) and the efficiency (%)."""
    columns = ["freq_MHz"] + list(DIFF_COLUMNS.values()) + [EFFICIENCY_COLUMN]
    top = ["MHz"] + [f"{a}-{b}" for a, b in DIFF_COLUMNS] + ["Efficiency"]
    sub = [""] + ["dB"] * len(DIFF_COLUMNS) + ["%"]
    return _render(rows, columns, top, sub)


def format_vendor_table(rows: list[dict]) -> str:
    """Terminal table of our peak gain and efficiency beside the vendor report's."""
    columns = ["freq_MHz", "peak_gain_dBi", VENDOR_PEAK_COLUMN, PEAK_DIFF_COLUMN,
               EFFICIENCY_COLUMN, VENDOR_EFFICIENCY_COLUMN, EFFICIENCY_DIFF_COLUMN]
    top = ["MHz", "Peak gain", "Vendor", "Diff", "Efficiency", "Vendor", "Diff"]
    sub = ["", "dBi", "dBi", "dB", "%", "%", "dB"]
    return _render(rows, columns, top, sub)


def format_half_table(rows: list[dict]) -> str:
    """Terminal table of the average gain over the half of the sphere facing each side."""
    columns = ["freq_MHz"] + list(HALF_COLUMNS.values())
    return _render(rows, columns, ["MHz"] + list(ORIENTATION), [""] + _axes_line())
