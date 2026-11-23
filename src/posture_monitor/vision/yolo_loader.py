"""Lớp trộn (mixin) nạp mô hình Ultralytics theo chuỗi dự phòng NCNN -> ONNX -> PyTorch.

Khử trùng lặp ~125 dòng nạp/export mô hình từng bị sao chép giữa ``pose.py`` và
``phone_detector.py``, đồng thời vẫn giữ nguyên các phương thức ``_yolo``,
``_ncnn_dir``, ``_onnx_path``, ``_load_ncnn``, ``_load_onnx``, ``_load_pt``,
``_export`` trên class để mọi phép ``monkeypatch.setattr`` trong unit test hoạt
động tự nhiên qua cơ chế kế thừa (MRO).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


class YoloModelMixin:
    """Cung cấp quy trình nạp/export NCNN -> ONNX -> PT thống nhất cho YOLO."""

    _weights: Path
    _model: Any | None
    _backend: str
    _model_label: str = "model"

    @property
    def backend(self) -> str:
        """Backend đang dùng: ``ncnn``, ``onnx``, ``pt`` hoặc ``chưa nạp``."""
        return self._backend

    def _yolo(self):
        from ultralytics import YOLO  # noqa: PLC0415 - import nặng, cố ý muộn

        return YOLO

    def _ncnn_dir(self) -> Path:
        return self._weights.with_name(f"{self._weights.stem}_ncnn_model")

    def _onnx_path(self) -> Path:
        return self._weights.with_suffix(".onnx")

    def _export_imgsz(self) -> int:
        raise NotImplementedError

    def _logger(self) -> logging.Logger:
        raise NotImplementedError

    def _load_with_fallback(self, fmt: str) -> bool:
        """Thử lần lượt các backend theo thứ tự ưu tiên ``fmt`` (ncnn/onnx/pt)."""
        log = self._logger()
        if fmt == "ncnn":
            if self._load_ncnn():
                return True
            log.warning(
                "Backend NCNN (%s) không dùng được; rơi về ONNX rồi PyTorch.",
                self._model_label,
            )
        if fmt in ("ncnn", "onnx"):
            if self._load_onnx():
                return True
            log.warning(
                "Backend ONNX (%s) không dùng được; rơi về PyTorch (.pt).",
                self._model_label,
            )
        return self._load_pt()

    def _load_ncnn(self) -> bool:
        log = self._logger()
        imgsz = self._export_imgsz()
        directory = self._ncnn_dir()
        if not directory.is_dir():
            log.info(
                "Chưa có thư mục NCNN '%s'; export một lần với imgsz=%d.",
                directory,
                imgsz,
            )
            if not self._export("ncnn", directory):
                return False
        try:
            self._model = self._yolo()(str(directory))
            self._backend = "ncnn"
            log.info("Đã nạp %s NCNN từ '%s'.", self._model_label, directory)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Nạp %s NCNN thất bại: %s", self._model_label, exc)
            return False

    def _load_onnx(self) -> bool:
        log = self._logger()
        imgsz = self._export_imgsz()
        path = self._onnx_path()
        if not path.is_file():
            log.info(
                "Chưa có file ONNX '%s'; export một lần với imgsz=%d.",
                path,
                imgsz,
            )
            if not self._export("onnx", path):
                return False
        try:
            self._model = self._yolo()(str(path))
            self._backend = "onnx"
            log.info("Đã nạp %s ONNX từ '%s'.", self._model_label, path)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Nạp %s ONNX thất bại: %s", self._model_label, exc)
            return False

    def _load_pt(self) -> bool:
        log = self._logger()
        try:
            self._model = self._yolo()(str(self._weights))
            self._backend = "pt"
            log.info("Đã nạp %s PyTorch từ '%s'.", self._model_label, self._weights)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Nạp %s PyTorch thất bại: %s", self._model_label, exc)
            return False

    def _export(self, fmt: str, target: Path) -> bool:
        log = self._logger()
        imgsz = self._export_imgsz()
        if not self._weights.is_file():
            log.warning(
                "Không export được %s: thiếu trọng số nguồn '%s'.",
                fmt,
                self._weights,
            )
            return False
        try:
            log.info(
                "Đang export %s (imgsz=%d) từ '%s'...",
                fmt,
                imgsz,
                self._weights,
            )
            produced = self._yolo()(str(self._weights)).export(
                format=fmt, imgsz=imgsz
            )
            produced_path = Path(str(produced))
            if produced_path.exists():
                log.info("Export %s xong: '%s'.", fmt, produced_path)
                return True
            log.warning(
                "Export %s báo xong nhưng không thấy '%s'.",
                fmt,
                produced_path,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Export %s lỗi: %s", fmt, exc)
        return target.exists()
