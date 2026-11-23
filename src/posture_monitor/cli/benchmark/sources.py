"""Các nguồn khung chuyên dụng cho benchmark (ảnh tĩnh lặp lại, danh sách khung tổng hợp)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from ...camera.capture import CameraError, FrameSource
from ...core.config import Config, ConfigError, parse_camera_source, redact_camera_source
from ...core.logging_setup import get_logger
from .telemetry import BenchmarkError

logger = get_logger("posture_monitor.cli.benchmark.sources")

IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
)

SOURCE_KINDS = {
    "camera": "camera trực tiếp (USB hoặc Pi Camera)",
    "video": "video ghi sẵn, phát lặp lại",
    "image": "ảnh tĩnh lặp lại — KHÔNG phải FPS camera thật",
    "synthetic": "khung tổng hợp dùng cho kiểm thử — không phải camera",
}


class StaticImageSource(FrameSource):
    """Ảnh tĩnh lặp lại vô hạn (dùng khi máy đích chưa gắn camera)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._frame = cv2.imread(str(self._path))
        if self._frame is None:
            raise CameraError(
                f"Không đọc được ảnh tĩnh '{self._path}'. Kiểm tra đường dẫn "
                "và định dạng file."
            )
        logger.info(
            "Đã mở ảnh tĩnh '%s' (%dx%d); dùng lặp lại cho bài đo.",
            self._path,
            self._frame.shape[1],
            self._frame.shape[0],
        )

    def read(self) -> np.ndarray | None:
        return self._frame

    def close(self) -> None:
        self._frame = None  # type: ignore[assignment]

    @property
    def backend(self) -> str:
        return "image"

    def __repr__(self) -> str:  # pragma: no cover
        return f"StaticImageSource({str(self._path)!r})"


class FrameListSource(FrameSource):
    """Lặp vô hạn một danh sách khung ``numpy`` dùng cho kiểm thử trên PC."""

    def __init__(self, frames: Sequence[np.ndarray]) -> None:
        if not frames:
            raise CameraError("Danh sách khung tổng hợp rỗng.")
        for index, frame in enumerate(frames):
            if not isinstance(frame, np.ndarray) or frame.size == 0:
                raise CameraError(
                    f"Khung tổng hợp thứ {index} không phải ảnh numpy hợp lệ."
                )
        self._frames = list(frames)
        self._index = 0

    def read(self) -> np.ndarray | None:
        if not self._frames:
            return None
        frame = self._frames[self._index % len(self._frames)]
        self._index += 1
        return frame

    def close(self) -> None:
        self._frames = []
        self._index = 0

    @property
    def backend(self) -> str:
        return "synthetic"


def _safe_backend(source: FrameSource) -> str:
    try:
        return str(source.backend)
    except Exception:  # noqa: BLE001
        return "không rõ"


def _source_meta(kind: str, source: FrameSource, detail: str) -> dict[str, Any]:
    return {
        "spec": redact_camera_source(detail),
        "kind": kind,
        "backend": _safe_backend(source),
        "is_static": kind == "image",
        "note": SOURCE_KINDS.get(kind, kind),
    }


def resolve_source(
    config: Config,
    source_override: Any,
    *,
    capture_factory: Callable[[Any], FrameSource | None],
) -> tuple[FrameSource, dict[str, Any], bool]:
    """Mở nguồn ảnh và trả ``(nguồn, mô_tả, có_phải_tự_đóng)``."""
    if isinstance(source_override, np.ndarray):
        source: FrameSource = FrameListSource([source_override])
        return source, _source_meta("synthetic", source, "một khung tổng hợp lặp lại"), True
    if isinstance(source_override, (list, tuple)):
        try:
            source = FrameListSource(source_override)
        except CameraError as exc:
            raise BenchmarkError(str(exc)) from exc
        return (
            source,
            _source_meta("synthetic", source, f"{len(source_override)} khung tổng hợp lặp lại"),
            True,
        )

    if isinstance(source_override, FrameSource):
        return (
            source_override,
            _source_meta("camera", source_override, "nguồn do bên gọi truyền vào"),
            False,
        )

    spec = config.camera.source if source_override is None else source_override
    if not isinstance(spec, str) or not spec.strip():
        raise BenchmarkError(
            f"Nguồn ảnh không hợp lệ: {redact_camera_source(repr(spec))}. "
            "Dùng 'usb:N', 'picamera' hoặc 'file:duong_dan'."
        )
    spec = spec.strip()
    safe_spec = redact_camera_source(spec)

    try:
        kind, value = parse_camera_source(spec)
    except ConfigError as exc:
        raise BenchmarkError(str(exc)) from exc

    if kind == "file":
        path = Path(str(value))
        if not path.is_file():
            raise BenchmarkError(
                f"Nguồn ảnh '{safe_spec}' không tồn tại: {path.resolve()}. "
                "Trên Pi chưa có camera, hãy trỏ tới ảnh tĩnh hoặc video có "
                "sẵn, ví dụ --source file:anh_mau.jpg."
            )
        if path.suffix.lower() in IMAGE_SUFFIXES:
            from . import StaticImageSource as static_cls  # noqa: PLC0415

            try:
                source = static_cls(path)
            except CameraError as exc:
                raise BenchmarkError(str(exc)) from exc
            return (
                source,
                _source_meta("image", source, f"ảnh tĩnh '{path.name}' lặp lại"),
                True,
            )

    patched = replace(config, camera=replace(config.camera, source=spec))
    try:
        opened = capture_factory(patched)
    except CameraError as exc:  # pragma: no cover
        raise BenchmarkError(f"Không mở được nguồn '{safe_spec}': {exc}") from exc
    if opened is None:
        raise BenchmarkError(
            f"Không mở được nguồn ảnh '{safe_spec}'. Xem log phía trên để biết "
            "lý do (thiếu thiết bị, sai đường dẫn, driver lỗi). Chạy "
            "'python scripts/camera_probe.py' để kiểm tra phần cứng."
        )
    report_kind = "video" if kind == "file" else "camera"
    return opened, _source_meta(report_kind, opened, spec), True
