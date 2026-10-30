"""Plain data containers shared by the readers, analysis and plotting code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type hints only; skipping the runtime import keeps script startup fast
    import numpy as np

# Suffix of the "Gain<X>" table name in the pattern CSVs -> legend label.
# "T" is labeled H+V as in the test report (its peaks match the report's peak-gain table).
# TODO: confirm what the L and S tables are (e.g. LHCP/RHCP) and rename here.
POL_LABELS = {
    "T": "H+V",
    "H": "H",
    "V": "V",
    "L": "L",
    "S": "S",
}

# Trace colors copied from the test report so plots can be compared side by side.
# Tables not listed here (L, S) fall back to matplotlib's default color cycle.
POL_COLORS = {
    "T": "#002060",  # dark blue
    "H": "#92D050",  # light green
    "V": "#FF0000",  # red
}

# Requirement: gain must not exceed this (dB); drawn as a dashed line on rectangular plots.
GAIN_LIMIT_DB = 4.0

# The difference panels of dataset comparisons span +/- this many dB.
DIFF_RANGE_DB = 10.0

# 2.4 GHz Wi-Fi markers for S11 plots: lower band edge, band center, upper band edge (MHz),
# rounded to whole MHz. The allocation is 2400-2483.5 MHz (center 2441.75 MHz; channel 7 is 2442).
WIFI_24_MARKS_MHZ = (2400.0, 2442.0, 2483.0)

# Region shaded on the S11 dB plot: the 2.4 GHz Wi-Fi band covering channels 1-13
# (channel 1 is centered at 2412 MHz, channel 13 at 2472 MHz and ends at ~2483 MHz).
WIFI_24_BAND_MHZ = (2400.0, 2483.5)
WIFI_24_BAND_LABEL = "2.4 GHz Wi-Fi band (CH 1-13)"

# Principal planes -> (cut, fixed angle in degrees). Theta is measured from +Z, phi from +X
# toward +Y, so XY is the theta=90 conical cut, XZ is phi=0 and YZ is phi=90.
PLANES = {
    "XY": ("theta", 90.0),
    "XZ": ("phi", 0.0),
    "YZ": ("phi", 90.0),
}


# Major directions -> (theta, phi) in degrees, in the same frame as PLANES. At the poles
# (Z+ and Z-) phi has no geometric meaning, so it is None: the gain there is the power average
# over all phi. (The measured gain at a pole does vary with phi, by up to ~3 dB in the sample
# data, so no single phi column is the "right" one.)
DIRECTIONS = {
    "X+": (90.0, 0.0),
    "X-": (90.0, 180.0),
    "Y+": (90.0, 90.0),
    "Y-": (90.0, 270.0),
    "Z+": (0.0, None),
    "Z-": (180.0, None),
}

# Device orientation: which side of the product faces each axis direction, as label -> a
# DIRECTIONS key. Right and Left are as seen from the front. The order here is the column order
# of the gain table. Edit this if the measurement orientation changes; the table headers and the
# peak-direction wording follow.
ORIENTATION = {
    "Front": "Y-",
    "Rear": "Y+",
    "Right": "X+",
    "Left": "X-",
    "Top": "Z+",
    "Bottom": "Z-",
}

# Pairs of opposite sides compared in the gain table; each difference is (first - second) in dB.
OPPOSITE_SIDES = (("Front", "Rear"), ("Right", "Left"), ("Top", "Bottom"))


def axis_text(axis: str) -> str:
    """'Y-' -> '-Y' (the usual way to write an axis direction)."""
    return f"{axis[1]}{axis[0]}"


# Shading of the half-planes of a cut, so the angle axis can be read as directions. A split is a
# pair of opposite sides, named like "front-rear"; each side keeps one color in every plot.
SHADE_SPLITS = {f"{a}-{b}".lower(): (a, b) for a, b in OPPOSITE_SIDES}
SIDE_COLORS = {
    "Front": "#F2C94C",  # gold
    "Rear": "#8E7CC3",  # violet
    "Right": "#4DB6AC",  # teal
    "Left": "#F08A6C",  # coral
    "Top": "#6BB7E8",  # sky
    "Bottom": "#B58B63",  # tan
}
SHADE_ALPHA = 0.18
# The axis "auto" splits on in each principal plane: front/rear in XY, left/right in XZ and
# top/bottom in YZ.
AUTO_SHADE_AXIS = {"XY": "Y", "XZ": "X", "YZ": "Z"}

# A direction within this many degrees of an axis is named by that axis alone (see
# analysis.direction_label): near a pole just Top/Bottom, near the horizon no Top/Bottom word.
DIRECTION_TOLERANCE_DEG = 22.5


def plane_name(cut: str, value_deg: float) -> str | None:
    """'XY'/'XZ'/'YZ' if (cut, value) is a principal plane, else None."""
    for name, (c, v) in PLANES.items():
        if c == cut and abs(v - value_deg) < 1e-9:
            return name
    return None


# Tables plotted when none are requested; L and S are left out until their meaning is confirmed.
DEFAULT_POLS = ["T", "H", "V"]


@dataclass
class S11Data:
    freq_hz: np.ndarray  # (n,)
    s11: np.ndarray  # (n,) complex reflection coefficient
    z0: float = 50.0
    name: str = ""


@dataclass
class Pattern:
    """Gain (dB) on a theta/phi grid at one frequency, one table per polarization."""

    freq_hz: float
    theta_deg: np.ndarray  # (n_theta,) ascending, e.g. 0..180
    phi_deg: np.ndarray  # (n_phi,) ascending, e.g. 0..360
    gain_db: dict[str, np.ndarray] = field(default_factory=dict)  # key -> (n_theta, n_phi)
    peak_db: dict[str, float] = field(default_factory=dict)  # "Gain:" value from file header
    name: str = ""

    @property
    def pols(self) -> list[str]:
        return list(self.gain_db)
