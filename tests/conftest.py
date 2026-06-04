from __future__ import annotations

import sys
from pathlib import Path

from app.core.runtime import configure_asyncio_runtime


configure_asyncio_runtime()

ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent

for candidate in (str(ROOT), str(TESTS_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
