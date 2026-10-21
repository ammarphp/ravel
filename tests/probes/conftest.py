"""Import the existing inert fixture libraries for bounded user-facing probes."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
for relative in ("tests/unit", "tests/unit/controller", "tests/integration/canaries"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.append(path)
