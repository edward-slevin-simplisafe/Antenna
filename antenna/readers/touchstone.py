"""One-port Touchstone (.s1p) reader, built on scikit-rf."""

from pathlib import Path

import numpy as np
import skrf

from antenna.models import S11Data


def read_s1p(path) -> S11Data:
    path = Path(path)
    if path.suffix.lower() != ".s1p":
        raise ValueError(f"{path.name}: expected a .s1p file, got '{path.suffix}'")

    ntwk = skrf.Network(str(path))
    if ntwk.nports != 1:
        raise ValueError(f"{path.name}: expected a one-port network, found {ntwk.nports} ports")

    return S11Data(
        freq_hz=np.asarray(ntwk.f, dtype=float),
        s11=ntwk.s[:, 0, 0],
        z0=float(np.real(ntwk.z0[0, 0])),
        name=path.stem,
    )
