"""Model dò điện thoại COCO thứ hai và bộ lọc thời gian nối vào vòng lặp.

Số liệu duy nhất đã đo cho model detect là ``yolo11n`` ncnn @320 = 98,6 ms cho
một lần suy luận trên khung tổng hợp 640x480 (chỉ inference, không capture);
cùng lần chạy đó pose + detect ở mọi khung đạt 4,90 FPS. Chi phí detect trong
pipeline thật chưa được đo (pose-only đạt 199,25 ms/khung -> 5,02 FPS, ghép
detect cách khung ra ~4,02 FPS, chưa đạt >= 5 FPS), nên ``detect_every_n_frames``
mặc định là ``2`` và cần đo bằng ``benchmark --profile pose_phone``.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..core.credentials import resolve_model_path
from ..core.logging_setup import get_logger
from .phone import (
    PHONE_CLASS_ID,
    HandPhoneResult,
    hand_phone_contact,
    is_head_like_box,
    is_plausible_phone_box,
    shoulder_width_px,
    usable_wrist_keypoints,
)
from .yolo_loader import YoloModelMixin

logger = get_logger("posture_monitor.vision.phone_detector")

DEFAULT_CONF_THRESHOLD = 0.06
DEFAULT_IMGSZ = 320
_MODEL_FORMATS = ("ncnn", "onnx", "pt")


class PhoneDetectorError(RuntimeError):
    """Không nạp hoặc không chạy được model dò điện thoại."""


def _to_numpy(value: Any) -> np.ndarray:
    current = value
    cpu = getattr(current, "cpu", None)
    if callable(cpu):
        current = cpu()
    to_numpy = getattr(current, "numpy", None)
    if callable(to_numpy):
        current = to_numpy()
    return np.asarray(current, dtype=float)


class PhoneDetector(YoloModelMixin):
    """Nạp model COCO thứ hai (lười ở lần detect đầu) và trả hộp lớp ``cell phone``."""

    _model_label = "model dò điện thoại"

    def __init__(
        self,
        weights: str | Path,
        *,
        conf_threshold: float = DEFAULT_CONF_THRESHOLD,
        imgsz: int = DEFAULT_IMGSZ,
        model_format: str = "ncnn",
    ) -> None:
        if not math.isfinite(conf_threshold) or not 0.0 <= conf_threshold <= 1.0:
            raise ValueError("conf_threshold phải nằm trong [0, 1]")
        if int(imgsz) <= 0:
            raise ValueError("imgsz phải là số dương")
        if model_format not in _MODEL_FORMATS:
            raise ValueError(
                f"model_format phải là một trong {_MODEL_FORMATS}, nhận được {model_format!r}"
            )

        self._weights = Path(weights)
        self._conf_threshold = float(conf_threshold)
        self._imgsz = int(imgsz)
        self._format = model_format
        self._model: Any | None = None
        self._backend = "chưa nạp"
        self._load_error: str | None = None

    @property
    def weights(self) -> Path:
        return self._weights

    def _export_imgsz(self) -> int:
        return self._imgsz

    def _logger(self) -> logging.Logger:
        return logger

    def _ensure(self) -> None:
        if self._model is not None:
            return
        if self._load_error is not None:
            raise PhoneDetectorError(self._load_error)
        if self._load():
            return
        self._load_error = (
            "Không nạp được model dò điện thoại "
            f"'{self._weights.name}'. Đã thử NCNN, ONNX và PyTorch. Kiểm tra "
            f"trọng số '{self._weights.resolve()}' có tồn tại, và đã cài "
            "ultralytics + torch chưa (xem requirements.txt)."
        )
        raise PhoneDetectorError(self._load_error)

    def _load(self) -> bool:
        return self._load_with_fallback(self._format)

    def detect(self, frame: np.ndarray) -> list[tuple[float, float, float, float]]:
        """Trả hộp ``cell phone`` trong hệ pixel của ``frame``."""
        self._ensure()
        try:
            results = self._model.predict(
                frame,
                imgsz=self._imgsz,
                conf=self._conf_threshold,
                verbose=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise PhoneDetectorError(
                "Model dò điện thoại lỗi khi suy luận trên khung hình: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        return _phone_boxes_from_results(results)


def _phone_boxes_from_results(results: Any) -> list[tuple[float, float, float, float]]:
    if not results:
        return []
    result = results[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    classes = getattr(boxes, "cls", None)
    if classes is None:
        return []
    try:
        xyxy = _to_numpy(boxes.xyxy).reshape(-1, 4)
        class_ids = _to_numpy(classes).reshape(-1)
    except (TypeError, ValueError):
        return []
    if class_ids.size != xyxy.shape[0]:
        return []

    found: list[tuple[float, float, float, float]] = []
    for box, class_id in zip(xyxy, class_ids):
        if not math.isfinite(float(class_id)):
            continue
        if int(round(float(class_id))) != PHONE_CLASS_ID:
            continue
        x1, y1, x2, y2 = (float(value) for value in box)
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        found.append((x1, y1, x2, y2))
    return found


class PhoneSignal:
    """Nối model dò điện thoại vào vòng lặp, có lọc thời gian và bộ đệm hộp."""

    def __init__(
        self,
        config: Any,
        *,
        detector: Any | None = None,
        min_kp_conf: float | None = None,
    ) -> None:
        self._cfg = config.phone
        self._enabled = bool(self._cfg.enabled)
        self._detect_every = _positive_int(
            self._cfg.detect_every_n_frames, "detect_every_n_frames"
        )
        self._box_ttl_s = _finite_non_negative(self._cfg.box_ttl_s, "box_ttl_s")
        self._hold_s = _finite_non_negative(self._cfg.hold_s, "hold_s")
        self._slack_px = _finite_non_negative(
            self._cfg.touching_slack_px, "touching_slack_px"
        )
        self._shoulder_ratio = _finite_non_negative(
            self._cfg.shoulder_ratio, "shoulder_ratio"
        )
        self._head_filter = bool(self._cfg.head_filter)
        self._phone_like_filter = bool(getattr(self._cfg, "phone_like_filter", True))
        self._min_size_ratio = _finite_non_negative(
            getattr(self._cfg, "min_size_ratio", 0.45), "min_size_ratio"
        )
        self._max_above_shoulder_px = _finite_non_negative(
            getattr(self._cfg, "max_above_shoulder_px", 10.0), "max_above_shoulder_px"
        )
        self._oversize_ratio = _finite_non_negative(
            getattr(self._cfg, "oversize_ratio", 1.2), "oversize_ratio"
        )
        self._miss_tolerance = _non_negative_int(
            self._cfg.miss_tolerance_frames, "miss_tolerance_frames"
        )
        self._min_kp_conf = (
            float(self._cfg.wrist_conf_min)
            if min_kp_conf is None
            else float(min_kp_conf)
        )

        if detector is not None:
            self._detector = detector
        else:
            raw_weights = self._cfg.detect_weights.strip()
            weights = (
                Path(raw_weights)
                if raw_weights
                else resolve_model_path(self._cfg.detect_model, default_suffix=".pt")
            )
            self._detector = PhoneDetector(
                weights,
                conf_threshold=self._cfg.conf_threshold,
                imgsz=self._cfg.imgsz,
                model_format=config.model.format,
            )

        self._frames_seen = 0
        self._boxes: list[tuple[float, float, float, float]] = []
        self._boxes_ts: float | None = None
        self._contact_since: float | None = None
        self._failed = False
        self._held_s = 0.0
        self._miss_streak = 0

    @property
    def enabled(self) -> bool:
        return self._enabled and not self._failed

    @property
    def held_s(self) -> float:
        return self._held_s

    @property
    def in_use(self) -> bool:
        return self._held_s >= self._hold_s

    def boxes(self, now: float) -> tuple[tuple[float, float, float, float], ...]:
        try:
            moment = float(now)
        except (TypeError, ValueError):
            return ()
        if not math.isfinite(moment) or not self.enabled or self._boxes_expired(moment):
            return ()
        return tuple(self._boxes)

    def observe(
        self, frame: np.ndarray, keypoints: object, now: float
    ) -> HandPhoneResult | None:
        if not self.enabled:
            return None
        now = float(now)
        if not math.isfinite(now):
            return None

        keypoints_array = usable_wrist_keypoints(keypoints, self._min_kp_conf)
        if keypoints_array is None:
            return None

        self._frames_seen += 1
        if (self._frames_seen - 1) % self._detect_every == 0:
            if not self._run_detect(frame, now, keypoints_array):
                return None

        if self._boxes_expired(now):
            self._boxes = []
            self._boxes_ts = None
        if not self._boxes:
            self._register_miss(now)
            return None

        result = hand_phone_contact(
            keypoints_array,
            self._boxes,
            proximity_px=self._proximity(keypoints_array),
            min_kp_conf=self._min_kp_conf,
        )
        self._update_contact(result.co_cham, now)
        return result

    def _proximity(self, keypoints_array: np.ndarray) -> float:
        if self._shoulder_ratio <= 0.0:
            return self._slack_px
        width = shoulder_width_px(keypoints_array, min_kp_conf=self._min_kp_conf)
        if width is None:
            return self._slack_px
        return self._slack_px + self._shoulder_ratio * width

    def _run_detect(
        self, frame: np.ndarray, now: float, keypoints_array: np.ndarray
    ) -> bool:
        try:
            boxes = self._detector.detect(frame)
        except PhoneDetectorError as exc:
            logger.warning("Tắt tính năng phát hiện điện thoại: %s", exc)
            self._failed = True
            self._boxes = []
            self._boxes_ts = None
            self._reset_contact()
            return False
        if self._head_filter:
            boxes = [
                box
                for box in boxes
                if not is_head_like_box(
                    box,
                    keypoints_array,
                    min_kp_conf=self._min_kp_conf,
                    oversize_ratio=self._oversize_ratio,
                )
            ]
        if self._phone_like_filter:
            boxes = [
                box
                for box in boxes
                if is_plausible_phone_box(
                    box,
                    keypoints_array,
                    min_kp_conf=self._min_kp_conf,
                    min_size_ratio=self._min_size_ratio,
                    max_above_shoulder_px=self._max_above_shoulder_px,
                    oversize_ratio=self._oversize_ratio,
                )
            ]
        self._boxes = list(boxes)
        self._boxes_ts = now
        return True

    def _boxes_expired(self, now: float) -> bool:
        if self._boxes_ts is None:
            return True
        return (now - self._boxes_ts) > self._box_ttl_s

    def reset(self) -> None:
        self._boxes = []
        self._boxes_ts = None
        self._frames_seen = 0
        self._reset_contact()

    def _update_contact(self, touching: bool, now: float) -> None:
        if touching:
            self._miss_streak = 0
            if self._contact_since is None:
                self._contact_since = now
            self._held_s = max(0.0, now - self._contact_since)
            return
        self._register_miss(now)

    def _register_miss(self, now: float) -> None:
        self._miss_streak += 1
        if self._miss_streak > self._miss_tolerance:
            self._reset_contact()
            return
        if self._contact_since is not None:
            self._held_s = max(0.0, now - self._contact_since)

    def _reset_contact(self) -> None:
        self._contact_since = None
        self._held_s = 0.0
        self._miss_streak = 0


def _positive_int(value: object, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} phải là số nguyên dương") from exc
    if number < 1:
        raise ValueError(f"{name} phải >= 1, nhận được {value!r}")
    return number


def _finite_non_negative(value: object, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} phải là số hữu hạn không âm, nhận được {value!r}")
    return number


def _non_negative_int(value: object, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} phải là số nguyên không âm") from exc
    if number < 0:
        raise ValueError(f"{name} phải >= 0, nhận được {value!r}")
    return number
