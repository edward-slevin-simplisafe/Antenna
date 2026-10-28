"""One-port Touchstone (.s1p) reader, built on scikit-rf."""

from pathlib import Path

from antenna.models import S11Data


def check_s1p_path(path) -> Path:
    """Raise a clear error unless `path` is an existing .s1p file. Cheap: imports nothing heavy."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path}: file not found")
    if path.suffix.lower() != ".s1p":
        raise ValueError(f"{path.name}: expected a .s1p file, got '{path.suffix}'")
    return path


def read_s1p(path) -> S11Data:
    # lazy imports: slow to load, and callers that only validate paths don't need them
    import numpy as np
    import skrf

    path = check_s1p_path(path)
    ntwk = skrf.Network(str(path))
    if ntwk.nports != 1:
        raise ValueError(f"{path.name}: expected a one-port network, found {ntwk.nports} ports")

    return S11Data(
        freq_hz=np.asarray(ntwk.f, dtype=float),
        s11=ntwk.s[:, 0, 0],
        z0=float(np.real(ntwk.z0[0, 0])),
        name=path.stem,
    )
