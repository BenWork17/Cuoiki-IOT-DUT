"""Tổng hợp giọng đọc dự phòng bằng ``espeak-ng`` và kiểm tra tệp WAV cục bộ.

Tách riêng phần dò nhị phân ``espeak-ng``, chạy subprocess sinh WAV và kiểm tra
header/độ mới của tệp WAV khỏi bộ điều phối cảnh báo trong ``speaker_alert.py``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence

#: Chương trình sinh giọng đọc và mã ngôn ngữ mặc định (spec §5.15).
ESPEAK_BINARY = "espeak-ng"
DEFAULT_LANGUAGE = "vi"

#: Vị trí cài mặc định trên Windows/Linux khi ``espeak-ng`` không nằm trên PATH.
ESPEAK_FALLBACK_PATHS = (
    r"C:\Program Files\eSpeak NG\espeak-ng.exe",
    r"C:\Program Files (x86)\eSpeak NG\espeak-ng.exe",
    "/usr/bin/espeak-ng",
    "/usr/local/bin/espeak-ng",
)

#: Chặn trên thời gian chạy ``espeak-ng`` để không giữ mãi bước khởi động.
ESPEAK_TIMEOUT_S = 30.0


def find_espeak_binary(
    *,
    fallback_paths: Sequence[str] | None = None,
    which_fn: Callable[[str], str | None] | None = None,
) -> str | None:
    """Đường dẫn tới ``espeak-ng`` dùng được, hoặc ``None``."""
    which = shutil.which if which_fn is None else which_fn
    found = which(ESPEAK_BINARY)
    if found:
        return found
    paths = ESPEAK_FALLBACK_PATHS if fallback_paths is None else fallback_paths
    for candidate in paths:
        if Path(candidate).is_file():
            return candidate
    return None


def wav_is_usable(path: Path) -> bool:
    """``True`` khi ``path`` là file WAV RIFF/WAVE đọc được và có dữ liệu tiếng."""
    try:
        if not path.is_file():
            return False
        with path.open("rb") as handle:
            head = handle.read(44)
    except OSError:
        return False
    if len(head) < 44 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return False
    data_size = int.from_bytes(head[40:44], "little")
    return data_size > 0 and path.stat().st_size > 44


def wav_is_current(
    target: Path,
    source: Path,
    *,
    usable_fn: Callable[[Path], bool] | None = None,
) -> bool:
    """Bản WAV ``target`` đã đổi từ ``source`` và còn mới hơn nó chưa."""
    check = wav_is_usable if usable_fn is None else usable_fn
    if not check(target):
        return False
    try:
        return target.stat().st_mtime >= source.stat().st_mtime
    except OSError:
        return False


#: Bí danh nội bộ tương thích ngược.
_wav_is_usable = wav_is_usable
_wav_is_current = wav_is_current


def run_espeak(
    text: str,
    out_path: str,
    *,
    language: str = DEFAULT_LANGUAGE,
    find_binary_fn: Callable[[], str | None] | None = None,
) -> None:
    """Sinh một file WAV từ ``text`` bằng ``espeak-ng`` (đường mặc định).

    Raises:
        RuntimeError: mọi lỗi đều đổi thành tiếng Việt đọc được — thiếu
            ``espeak-ng``, mã trả về khác 0, hoặc chạy quá lâu.
    """
    finder = find_espeak_binary if find_binary_fn is None else find_binary_fn
    try:
        binary = finder()
        if binary is None:
            raise FileNotFoundError(ESPEAK_BINARY)
        subprocess.run(
            [binary, "-v", language, "-w", out_path, text],
            check=True,
            capture_output=True,
            timeout=ESPEAK_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Không tìm thấy '{ESPEAK_BINARY}' trên máy này nên chưa sinh được "
            "file giọng đọc tiếng Việt (Raspberry Pi: sudo apt install -y "
            "espeak-ng)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"'{ESPEAK_BINARY}' trả mã lỗi {exc.returncode} khi sinh giọng "
            f"đọc{' : ' + detail if detail else '.'}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"'{ESPEAK_BINARY}' chạy quá {ESPEAK_TIMEOUT_S:g} giây nên bị dừng."
        ) from exc


__all__ = [
    "DEFAULT_LANGUAGE",
    "ESPEAK_BINARY",
    "ESPEAK_FALLBACK_PATHS",
    "ESPEAK_TIMEOUT_S",
    "_wav_is_current",
    "_wav_is_usable",
    "find_espeak_binary",
    "run_espeak",
    "wav_is_current",
    "wav_is_usable",
]
