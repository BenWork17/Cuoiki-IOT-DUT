"""Điểm điều phối trung tâm ``main(argv)`` cho CLI."""

from __future__ import annotations

import argparse
import sys
from typing import Callable

_COMMAND_ATTRS: dict[str, str] = {
    "run": "cmd_run",
    "benchmark": "cmd_benchmark",
    "calibrate": "cmd_calibrate",
    "replay": "cmd_replay",
    "speak-test": "cmd_speak_test",
}


def _execute_safely(handler: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> int:
    """Thực thi lệnh con với một lớp bảo vệ ``KeyboardInterrupt`` / ``Exception`` duy nhất."""
    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Lỗi không mong muốn: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    """Hàm chính; trả mã thoát của tiến trình."""
    from .. import cli as _cli  # noqa: PLC0415

    parser = _cli.build_parser()
    args = parser.parse_args(argv)

    attr_name = _COMMAND_ATTRS.get(args.command)
    if attr_name is None:
        print(f"Lệnh không có nhánh xử lý: {args.command}", file=sys.stderr)
        return 2

    handler = getattr(_cli, attr_name)
    return _execute_safely(handler, args)
