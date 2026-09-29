"""Root pytest conftest: keep the project root on sys.path so tests/ can import core and server."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
