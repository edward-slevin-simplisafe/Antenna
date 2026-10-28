"""Plain data containers shared by the readers, analysis and plotting code."""

from dataclasses import dataclass, field

import numpy as np

# Suffix of the "Gain<X>" table name in the pattern CSVs -> legend label.
# TODO: confirm what the L and S tables are (e.g. LHCP/RHCP) and rename here.
POL_LABELS = {
    "T": "Total",
    "H": "H",
    "V": "V",
    "L": "L",
    "S": "S",
}


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
