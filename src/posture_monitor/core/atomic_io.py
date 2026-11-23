"""Ghi tệp JSON nguyên tử dùng chung cho kho khuôn mặt, ngưỡng và cấu hình giọng.

Quy trình chuẩn chống mất dữ liệu khi cúp điện giữa chừng trên Raspberry Pi:
1. Tạo tệp tạm cùng thư mục đích (cùng filesystem để ``os.replace`` nguyên tử).
2. Ghi JSON UTF-8, ``flush()`` bộ đệm Python và ``fsync()`` xuống đĩa.
3. Thay thế nguyên tử tệp đích bằng ``os.replace``.
4. Trong ``finally``, xoá tệp tạm nếu bước ghi/fsync/replace thất bại.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


def write_json_atomic(
    path: str | Path,
    payload: Any,
    *,
    indent: int = 2,
    fsync_fn: Callable[[int], None] | None = None,
) -> Path:
    """Ghi ``payload`` dạng JSON UTF-8 ra ``path`` một cách nguyên tử.

    Args:
        path: Đường dẫn tệp đích.
        payload: Dữ liệu serialize được sang JSON.
        indent: Số khoảng trắng thụt lề (mặc định 2).
        fsync_fn: Hàm ``fsync`` tuỳ chọn (mặc định :func:`os.fsync`), cho phép
            unit test tiêm lỗi đĩa giả lập mà không phải patch toàn cục.

    Returns:
        Đường dẫn ``Path`` tới tệp đã ghi.
    """
    target = Path(path)
    parent = target.parent if str(target.parent) else Path(".")
    parent.mkdir(parents=True, exist_ok=True)

    sync = os.fsync if fsync_fn is None else fsync_fn
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            json.dump(payload, tmp, ensure_ascii=False, indent=indent)
            tmp.write("\n")
            tmp.flush()
            sync(tmp.fileno())
        os.replace(tmp_name, target)
        tmp_name = None
        return target
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
