"""Suy luận pose bằng YOLO11n-pose kèm cơ chế bám người & bám lại theo không gian."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

from ..core.credentials import resolve_model_path
from ..core.logging_setup import get_logger
from .yolo_loader import YoloModelMixin

logger = get_logger("posture_monitor.vision.pose")

NUM_KEYPOINTS = 17
DEFAULT_CONF = 0.25

REACQUIRE_MIN_FRAME_RATIO = 0.05
REACQUIRE_MAX_ASPECT_RATIO = 4.0
REACQUIRE_MAX_CENTER_SHIFT_RATIO = 0.5
REACQUIRE_MIN_IOU = 0.1


class PoseError(RuntimeError):
    """Không nạp được backend model nào (thiếu trọng số, thiếu thư viện)."""


class PoseResult(NamedTuple):
    """Kết quả pose của một người, toạ độ pixel trên khung gốc."""

    xy: np.ndarray
    conf: np.ndarray
    bbox: np.ndarray


def pose_to_keypoints_array(pose_result: PoseResult | Any | None) -> np.ndarray | None:
    """Ghép ``(17, 3)`` ``[x, y, conf]`` từ ``PoseResult`` (dùng chung cho CLI & benchmark)."""
    if pose_result is None:
        return None
    try:
        return np.concatenate(
            (
                np.asarray(pose_result.xy, dtype=float),
                np.asarray(pose_result.conf, dtype=float).reshape(-1, 1),
            ),
            axis=1,
        )
    except (AttributeError, TypeError, ValueError):
        return None


def _as_pose_result(keypoints: Any, box: Any) -> PoseResult:
    xy = np.asarray(keypoints.xy[0], dtype=np.float32).reshape(NUM_KEYPOINTS, 2)
    conf = np.asarray(keypoints.conf[0], dtype=np.float32)
    if conf.size == 0:  # pragma: no cover
        conf = np.zeros(NUM_KEYPOINTS, dtype=np.float32)
    conf = conf.reshape(NUM_KEYPOINTS)
    bbox = np.asarray(box, dtype=np.float32).reshape(4)
    return PoseResult(xy=xy, conf=conf, bbox=bbox)


def _box_area(box: np.ndarray) -> float:
    width = max(0.0, float(box[2] - box[0]))
    height = max(0.0, float(box[3] - box[1]))
    return width * height


def _safe_len(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(len(value))
    except TypeError:  # pragma: no cover
        return 0


def _box_is_big_enough(box: np.ndarray, frame_shape: Any) -> bool:
    """Khung bao có chiếm đủ khung hình để được phép bám lại khi track id mất không."""
    width = max(0.0, float(box[2] - box[0]))
    height = max(0.0, float(box[3] - box[1]))
    if frame_shape is None:
        return width > 0.0 or height > 0.0
    try:
        frame_h = float(frame_shape[0])
        frame_w = float(frame_shape[1])
    except (TypeError, IndexError, ValueError):  # pragma: no cover
        return width > 0.0 or height > 0.0
    if frame_h <= 0.0 or frame_w <= 0.0:  # pragma: no cover
        return width > 0.0 or height > 0.0
    if width <= 0.0 or height <= 0.0:
        return False
    aspect = width / height
    if aspect > REACQUIRE_MAX_ASPECT_RATIO or (1.0 / aspect) > REACQUIRE_MAX_ASPECT_RATIO:
        return False
    return bool(
        (width / frame_w >= REACQUIRE_MIN_FRAME_RATIO)
        and (height / frame_h >= REACQUIRE_MIN_FRAME_RATIO)
    )


def _box_iou(a: np.ndarray, b: np.ndarray) -> float:
    """Giao trên hợp (IoU) của hai khung bao pixel; ``0.0`` khi không giao."""
    ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
    bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def _box_center_shift_ratio(box: np.ndarray, previous: np.ndarray) -> float:
    """Độ dịch tâm giữa ``box`` và ``previous``, chia cho cạnh dài ``previous``."""
    px1, py1, px2, py2 = (float(v) for v in previous[:4])
    bx1, by1, bx2, by2 = (float(v) for v in box[:4])
    longest = max(px2 - px1, py2 - py1)
    if longest <= 0.0:
        return float("inf")
    pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
    bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
    return float(np.hypot(bcx - pcx, bcy - pcy)) / longest


def _box_is_continuous(box: np.ndarray, previous: np.ndarray | None) -> bool:
    """Hộp mới có còn liên tục không gian với hộp của người đang theo dõi không."""
    if previous is None:
        return True
    if _box_iou(box, previous) >= REACQUIRE_MIN_IOU:
        return True
    return _box_center_shift_ratio(box, previous) <= REACQUIRE_MAX_CENTER_SHIFT_RATIO


class PoseEstimator(YoloModelMixin):
    """Nạp model pose và trả kết quả của người đang được theo dõi."""

    _model_label = "model"

    def __init__(self, config: Any, weights: str | Path | None = None) -> None:
        self._model_cfg = config.model
        self._tracking = config.tracking
        self._absent_reset_s = float(config.timing.absent_reset_s)

        self._weights = (
            Path(weights)
            if weights is not None
            else resolve_model_path(self._model_cfg.name, default_suffix=".pt")
        )
        self._model = None
        self._backend = "chưa nạp"
        self._tracking_on = bool(self._tracking.enabled)

        self._locked_id: int | None = None
        self._last_seen_ts: float = 0.0
        self._last_box: np.ndarray | None = None
        self.last_person_count: int = 0

        self._load()

    def _export_imgsz(self) -> int:
        return int(self._model_cfg.imgsz)

    def _logger(self) -> logging.Logger:
        return logger

    def _load(self) -> None:
        if self._load_with_fallback(self._model_cfg.format):
            return
        raise PoseError(
            f"Không nạp được model pose '{self._model_cfg.name}'. Đã thử NCNN, "
            "ONNX và PyTorch. Kiểm tra trọng số "
            f"'{self._weights.resolve()}' có tồn tại, và đã cài "
            "ultralytics + torch chưa (xem requirements.txt)."
        )

    def detect(self, frame: np.ndarray) -> PoseResult | None:
        """Phát hiện pose của người đang được theo dõi trong ``frame``."""
        if self._model is None:  # pragma: no cover
            return None

        results = self._infer(frame)
        if not results:
            self.last_person_count = 0
            return None

        result = results[0]
        boxes = getattr(result, "boxes", None)
        keypoints = getattr(result, "keypoints", None)
        count = _safe_len(boxes)
        if boxes is not None and (keypoints is None or count == 0):
            self.last_person_count = count
            self._mark_absent()
            return None
        if boxes is None or keypoints is None or count == 0:
            self.last_person_count = 0
            self._mark_absent()
            return None

        self.last_person_count = count
        xyxy = np.asarray(boxes.xyxy.cpu().numpy(), dtype=np.float32)

        ids = None
        if getattr(boxes, "id", None) is not None:
            ids = [int(value) for value in boxes.id.cpu().numpy().tolist()]

        index = self._select(xyxy, ids, frame_shape=getattr(frame, "shape", None))
        if index is None:
            return None

        box = xyxy[index]
        self._last_box = np.array(box, dtype=np.float32, copy=True)
        return _as_pose_result(keypoints[index], box)

    def _infer(self, frame: np.ndarray):
        kwargs: dict[str, Any] = {
            "imgsz": self._model_cfg.imgsz,
            "conf": DEFAULT_CONF,
            "verbose": False,
        }
        if self._tracking_on:
            try:
                return self._model.track(
                    frame,
                    persist=True,
                    tracker=self._tracking.tracker,
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Tracking lỗi (%s); chuyển sang predict không theo track.",
                    exc,
                )
                self._tracking_on = False
        return self._model.predict(frame, **kwargs)

    def _select(
        self,
        xyxy: np.ndarray,
        ids: list[int] | None,
        frame_shape: Any = None,
    ) -> int | None:
        now = time.monotonic()
        if not xyxy.size:
            return None

        if self._locked_id is not None and ids is not None:
            matches = [i for i, tid in enumerate(ids) if tid == self._locked_id]
            if matches:
                self._last_seen_ts = now
                return matches[0]

            index = int(np.argmax([_box_area(box) for box in xyxy]))
            candidate = xyxy[index]
            if _box_is_big_enough(candidate, frame_shape) and _box_is_continuous(
                candidate, self._last_box
            ):
                logger.info(
                    "Track id %d mất khỏi khung nhưng còn người: bám lại track "
                    "id %d (khung bao lớn nhất, còn liên tục vị trí).",
                    self._locked_id,
                    ids[index],
                )
                self._locked_id = ids[index]
                self._last_seen_ts = now
                return index

            if now - self._last_seen_ts < self._absent_reset_s:
                return None
            logger.info(
                "Track id %d vắng quá %.0f giây; nhả khoá để chọn người khác.",
                self._locked_id,
                self._absent_reset_s,
            )
            self._locked_id = None
        elif self._locked_id is not None and ids is None:
            self._locked_id = None

        index = int(np.argmax([_box_area(box) for box in xyxy]))
        if ids is not None:
            self._locked_id = ids[index]
        self._last_seen_ts = now
        return index

    def _mark_absent(self) -> None:
        if self._locked_id is None:
            self._last_seen_ts = time.monotonic()
