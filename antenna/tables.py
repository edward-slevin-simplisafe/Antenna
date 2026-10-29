"""Tabulate pattern gains: one row per frequency. No plotting."""

import csv
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


def summary_rows(patterns: list[Pattern], pol: str = TOTAL) -> list[dict]:
    return [summary_row(p, pol) for p in patterns]


def _text(column: str, value) -> str:
    """Rounded text for a CSV cell or terminal table."""
    if isinstance(value, str):
        return value
    if column.endswith(_GAIN_SUFFIXES):
        return f"{round(value, GAIN_DECIMALS):.{GAIN_DECIMALS}f}"
    return f"{value:g}"  # frequency and angles


def write_csv(rows: list[dict], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow([_text(c, row[c]) for c in COLUMNS])
    return path


def _render(rows: list[dict], columns: list[str], top: list[str], sub: list[str]) -> str:
    """Fixed-width text table: a two-line header, right-aligned cells, and the peak direction
    (text) left-aligned."""
    body = [[_text(c, row[c]) for c in columns] for row in rows]
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


def format_half_table(rows: list[dict]) -> str:
    """Terminal table of the average gain over the half of the sphere facing each side."""
    columns = ["freq_MHz"] + list(HALF_COLUMNS.values())
    return _render(rows, columns, ["MHz"] + list(ORIENTATION), [""] + _axes_line())
