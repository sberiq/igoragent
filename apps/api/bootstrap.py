from pathlib import Path
import sys

CORE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "core"
sys.path.insert(0, str(CORE_ROOT))
