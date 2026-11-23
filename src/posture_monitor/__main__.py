"""Điểm vào dòng lệnh: ``python -m posture_monitor <lệnh>``."""

from __future__ import annotations

import sys

from . import cli as _cli

if __name__ == "__main__":
    raise SystemExit(_cli.main())

sys.modules[__name__] = _cli
