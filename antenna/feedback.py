"""Progress messages for the command-line scripts (the library code itself stays silent)."""

import time

_START = time.perf_counter()

# Library loading slower than this suggests the environment is on a synced or network drive.
SLOW_LOAD_SECONDS = 8.0


def elapsed() -> float:
    """Seconds since this module was first imported (i.e. since the script started)."""
    return time.perf_counter() - _START


def say(message: str) -> None:
    print(f"[{elapsed():5.1f}s] {message}", flush=True)


def tip_if_slow(load_seconds: float) -> None:
    if load_seconds > SLOW_LOAD_SECONDS:
        say(f"Tip: loading libraries took {load_seconds:.0f} s. If the virtual environment is on "
            "Google Drive or another synced/network folder, recreating it in a local folder "
            "(for example C:\\venvs\\antenna) usually makes this much faster.")
