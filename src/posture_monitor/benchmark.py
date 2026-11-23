"""Điểm vào tương thích cho ``python -m posture_monitor.benchmark``."""

from __future__ import annotations

import sys

from .cli import benchmark as _benchmark

if __name__ == "__main__":
    raise SystemExit(_benchmark.main())

sys.modules[__name__] = _benchmark
