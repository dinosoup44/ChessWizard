"""Compatibility entry for the explicit-root servicing validation harness."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.validate_upgrade import main

if __name__ == "__main__":
    raise SystemExit(main())
