"""Presence inspection and an explicit, bounded UCI handshake; never send position/go."""
from pathlib import Path
import subprocess
from engine_cache import STOCKFISH_PATH, ENGINE_VERSION
from admin_models import EngineStatus

ENGINE_TEST_TIMEOUT_SECONDS = 5


def engine_status(root) -> EngineStatus:
    path = Path(root) / STOCKFISH_PATH
    try:
        found = path.is_file()
        return EngineStatus(str(path.absolute()), found, ENGINE_VERSION,
                            path.stat().st_size if found else None)
    except OSError as error:
        return EngineStatus(str(path.absolute()), False, ENGINE_VERSION, error=str(error))


def test_engine(root, *, runner=subprocess.run) -> EngineStatus:
    """Only uci/isready/quit, bounded timeout; subprocess.run kills/waits on timeout."""
    current = engine_status(root)
    if not current.found:
        return EngineStatus(current.path, False, current.configured_version,
                            diagnostic="Missing", error="Configured Stockfish executable was not found.")
    try:
        result = runner([current.path],input="uci\nisready\nquit\n",text=True,
                        encoding="utf-8",errors="replace",capture_output=True,
                        timeout=ENGINE_TEST_TIMEOUT_SECONDS,
                        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        lines = result.stdout.splitlines()
        name = next((line[8:208] for line in lines if line.startswith("id name ")), None)
        ok = result.returncode == 0 and "uciok" in lines and "readyok" in lines
        return EngineStatus(current.path,True,current.configured_version,current.size_bytes,
                            "Passed" if ok else "Failed",name,
                            "" if ok else "UCI handshake did not complete successfully.")
    except (OSError, subprocess.TimeoutExpired) as error:
        return EngineStatus(current.path,True,current.configured_version,current.size_bytes,
                            "Failed",error=type(error).__name__+": engine diagnostic unavailable.")
