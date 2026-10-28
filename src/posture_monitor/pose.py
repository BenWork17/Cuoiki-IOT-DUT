"""Suy luận pose bằng YOLO11n-pose (spec v2 §5.2).

Module này là **hợp đồng chung với M2**: :meth:`PoseEstimator.detect` trả
:class:`PoseResult` gồm ``xy`` (17x2 pixel), ``conf`` (17) và ``bbox``
``(x1, y1, x2, y2)``, hoặc ``None`` khi không thấy người. Đổi chữ ký này là
phá hợp đồng với ``features.py``/``state.py`` của M2.

Thứ tự nạp model theo ``config.model.format``:

- ``ncnn``: thư mục ``*_ncnn_model`` → nếu chưa có thì export một lần với
  ``imgsz`` đã cấu hình → nếu export lỗi thì rơi về ONNX → rơi về PyTorch.
- ``onnx``: file ``*.onnx`` → export → rơi về PyTorch.
- ``pt``: trọng số PyTorch.

Mỗi lần rơi cấp đều ghi WARNING nêu rõ lý do; không bao giờ crash vì lỗi
backend (spec v2 §11.4). Chỉ khi **không nạp được backend nào** mới ném
:class:`PoseError` để CLI báo lỗi cấu hình bằng thông điệp rõ ràng.

Chọn người (spec v2 §5.6): khi ``tracking.enabled``, dùng ``YOLO.track()`` và
bám theo một track id. Chỉ nhả track khi nó vắng quá ``timing.absent_reset_s``;
nhả xong mới bắt lại người có khung bao lớn nhất. Nhờ vậy người thứ hai đi
ngang qua không làm nhảy người đang theo dõi.

Không in bất kỳ số liệu hiệu năng nào: FPS/độ trễ thuộc ``benchmark`` (spec
§11.6).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

from .logging_setup import get_logger

logger = get_logger(__name__)

#: Số keypoint COCO của model pose.
NUM_KEYPOINTS = 17

#: Ngưỡng tin cậy phát hiện người khi gọi model. Ngưỡng này thuộc về model
#: (không phải ngưỡng phân loại tư thế), nên không nằm trong config.yaml.
DEFAULT_CONF = 0.25


class PoseError(RuntimeError):
    """Không nạp được backend model nào (thiếu trọng số, thiếu thư viện)."""


class PoseResult(NamedTuple):
    """Kết quả pose của **một** người, toạ độ pixel trên khung gốc.

    Attributes:
        xy: ``numpy.ndarray`` shape ``(17, 2)``, ``float32``.
        conf: ``numpy.ndarray`` shape ``(17,)``, ``float32``, trong ``[0, 1]``.
        bbox: ``numpy.ndarray`` shape ``(4,)``: ``x1, y1, x2, y2`` pixel.
    """

    xy: np.ndarray
    conf: np.ndarray
    bbox: np.ndarray


def _as_pose_result(keypoints: Any, box: Any) -> PoseResult:
    """Chuyển output của ultralytics cho một người thành :class:`PoseResult`."""
    xy = np.asarray(keypoints.xy[0], dtype=np.float32).reshape(NUM_KEYPOINTS, 2)
    conf = np.asarray(keypoints.conf[0], dtype=np.float32)
    if conf.size == 0:  # pragma: no cover - backend lạ không trả conf
        conf = np.zeros(NUM_KEYPOINTS, dtype=np.float32)
    conf = conf.reshape(NUM_KEYPOINTS)
    bbox = np.asarray(box, dtype=np.float32).reshape(4)
    return PoseResult(xy=xy, conf=conf, bbox=bbox)


def _box_area(box: np.ndarray) -> float:
    width = max(0.0, float(box[2] - box[0]))
    height = max(0.0, float(box[3] - box[1]))
    return width * height


class PoseEstimator:
    """Nạp model pose và trả kết quả của người đang được theo dõi.

    Args:
        config: :class:`~posture_monitor.config.Config`; dùng
            ``config.model`` và ``config.tracking``, ``config.timing``.
        weights: đường dẫn trọng số ``.pt``. Mặc định ``model.name + ".pt"``
            ở thư mục hiện tại (ultralytics cũng tự tìm ở đó).
    """

    def __init__(self, config, weights: str | Path | None = None) -> None:
        self._model_cfg = config.model
        self._tracking = config.tracking
        self._absent_reset_s = float(config.timing.absent_reset_s)

        self._weights = (
            Path(weights)
            if weights is not None
            else Path(f"{self._model_cfg.name}.pt")
        )
        self._model = None
        self._backend = "chưa nạp"
        #: Cờ tracking nội bộ. Không sửa ``config.tracking.enabled`` vì đối
        #: tượng cấu hình dùng chung với các module khác.
        self._tracking_on = bool(self._tracking.enabled)

        #: Track id đang bám; ``None`` nghĩa là chưa khoá ai.
        self._locked_id: int | None = None
        #: Thời điểm (monotonic) cuối cùng còn thấy track đang bám.
        self._last_seen_ts: float = 0.0

        #: Số người phát hiện được ở lần gọi :meth:`detect` gần nhất.
        self.last_person_count: int = 0

        self._load()

    # -- nạp model ------------------------------------------------------

    @property
    def backend(self) -> str:
        """Backend đang dùng: ``ncnn``, ``onnx`` hoặc ``pt``."""
        return self._backend

    def _yolo(self):
        from ultralytics import YOLO  # noqa: PLC0415 - import nặng, cố ý muộn

        return YOLO

    def _ncnn_dir(self) -> Path:
        return self._weights.with_name(f"{self._weights.stem}_ncnn_model")

    def _onnx_path(self) -> Path:
        return self._weights.with_suffix(".onnx")

    def _load(self) -> None:
        """Thử lần lượt các backend theo thứ tự ưu tiên của cấu hình."""
        fmt = self._model_cfg.format
        if fmt == "ncnn":
            if self._load_ncnn():
                return
            logger.warning(
                "Backend NCNN không dùng được; rơi về ONNX rồi PyTorch "
                "(spec §5.2)."
            )
        if fmt in ("ncnn", "onnx"):
            if self._load_onnx():
                return
            logger.warning(
                "Backend ONNX không dùng được; rơi về PyTorch (.pt)."
            )
        if self._load_pt():
            return
        raise PoseError(
            f"Không nạp được model pose '{self._model_cfg.name}'. Đã thử NCNN, "
            "ONNX và PyTorch. Kiểm tra trọng số "
            f"'{self._weights.resolve()}' có tồn tại, và đã cài "
            "ultralytics + torch chưa (xem requirements.txt)."
        )

    def _load_ncnn(self) -> bool:
        """Nạp thư mục NCNN, export nếu chưa có. Trả ``True`` nếu thành công."""
        directory = self._ncnn_dir()
        if not directory.is_dir():
            logger.info(
                "Chưa có thư mục NCNN '%s'; export một lần với imgsz=%d.",
                directory,
                self._model_cfg.imgsz,
            )
            if not self._export("ncnn", directory):
                return False
        try:
            self._model = self._yolo()(str(directory))
            self._backend = "ncnn"
            logger.info("Đã nạp model NCNN từ '%s'.", directory)
            return True
        except Exception as exc:  # noqa: BLE001 - backend lỗi không được crash
            logger.warning("Nạp model NCNN thất bại: %s", exc)
            return False

    def _load_onnx(self) -> bool:
        """Nạp file ONNX, export nếu chưa có. Trả ``True`` nếu thành công."""
        path = self._onnx_path()
        if not path.is_file():
            logger.info(
                "Chưa có file ONNX '%s'; export một lần với imgsz=%d.",
                path,
                self._model_cfg.imgsz,
            )
            if not self._export("onnx", path):
                return False
        try:
            self._model = self._yolo()(str(path))
            self._backend = "onnx"
            logger.info("Đã nạp model ONNX từ '%s'.", path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Nạp model ONNX thất bại: %s", exc)
            return False

    def _load_pt(self) -> bool:
        """Nạp trọng số PyTorch. Trả ``True`` nếu thành công."""
        try:
            self._model = self._yolo()(str(self._weights))
            self._backend = "pt"
            logger.info("Đã nạp model PyTorch từ '%s'.", self._weights)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Nạp model PyTorch thất bại: %s", exc)
            return False

    def _export(self, fmt: str, target: Path) -> bool:
        """Export từ trọng số ``.pt`` sang ``fmt``; không raise.

        Args:
            fmt: ``ncnn`` hoặc ``onnx``.
            target: đường dẫn/thư mục kỳ vọng sau khi export.

        Returns:
            ``True`` nếu file/thư mục đích tồn tại sau khi export.
        """
        if not self._weights.is_file():
            logger.warning(
                "Không export được %s: thiếu trọng số nguồn '%s'.",
                fmt,
                self._weights,
            )
            return False
        try:
            logger.info(
                "Đang export %s (imgsz=%d) từ '%s'...",
                fmt,
                self._model_cfg.imgsz,
                self._weights,
            )
            produced = self._yolo()(str(self._weights)).export(
                format=fmt, imgsz=self._model_cfg.imgsz
            )
            produced_path = Path(str(produced))
            if produced_path.exists():
                logger.info("Export %s xong: '%s'.", fmt, produced_path)
                return True
            logger.warning(
                "Export %s báo xong nhưng không thấy '%s'.",
                fmt,
                produced_path,
            )
        except Exception as exc:  # noqa: BLE001 - export lỗi phải rơi tiếp
            logger.warning("Export %s lỗi: %s", fmt, exc)
        # Một số bản ultralytics trả đường dẫn khác nơi thực tế ghi file.
        return target.exists()

    # -- suy luận -------------------------------------------------------

    def detect(self, frame: np.ndarray) -> PoseResult | None:
        """Phát hiện pose của người đang được theo dõi trong ``frame``.

        Args:
            frame: ảnh BGR ``uint8`` như :meth:`FrameSource.read` trả.

        Returns:
            :class:`PoseResult` của người đang theo dõi, hoặc ``None`` nếu
            không thấy ai. Số người thật sự thấy trong khung nằm ở
            :attr:`last_person_count` (``0`` khi không thấy ai).
        """
        if self._model is None:  # pragma: no cover - chỉ khi nạp thất bại
            return None

        results = self._infer(frame)
        if not results:
            self.last_person_count = 0
            return None

        result = results[0]
        boxes = getattr(result, "boxes", None)
        keypoints = getattr(result, "keypoints", None)
        if boxes is None or keypoints is None or len(boxes) == 0:
            self.last_person_count = 0
            self._mark_absent()
            return None

        count = len(boxes)
        self.last_person_count = count
        xyxy = np.asarray(boxes.xyxy.cpu().numpy(), dtype=np.float32)

        ids = None
        if getattr(boxes, "id", None) is not None:
            ids = [int(value) for value in boxes.id.cpu().numpy().tolist()]

        index = self._select(xyxy, ids)
        if index is None:  # pragma: no cover - nhánh phòng vệ
            self.last_person_count = 0
            return None

        box = xyxy[index]
        return _as_pose_result(keypoints[index], box)

    def _infer(self, frame: np.ndarray):
        """Gọi ``track`` (nếu bật) hoặc ``predict``; trả list kết quả."""
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
            except Exception as exc:  # noqa: BLE001 - tracker hỏng phải rơi tiếp
                logger.warning(
                    "Tracking lỗi (%s); chuyển sang predict không theo track.",
                    exc,
                )
                self._tracking_on = False
        return self._model.predict(frame, **kwargs)

    # -- chọn người (spec §5.6) -----------------------------------------

    def _select(self, xyxy: np.ndarray, ids: list[int] | None) -> int | None:
        """Chọn index người đang theo dõi trong danh sách phát hiện.

        Quy tắc:

        1. Nếu đang khoá một track id và track đó còn trong khung → chọn nó.
        2. Nếu không còn thấy → giữ khoá tới ``absent_reset_s``; trong khoảng
           đó coi như vắng (``None``) để không nhảy sang người khác.
        3. Quá ``absent_reset_s`` hoặc chưa khoá ai → khoá người có khung bao
           lớn nhất (chỉ lần đầu / sau khi nhả khoá).
        """
        now = time.monotonic()
        if not xyxy.size:
            return None

        if self._locked_id is not None and ids is not None:
            matches = [i for i, tid in enumerate(ids) if tid == self._locked_id]
            if matches:
                self._last_seen_ts = now
                return matches[0]
            if now - self._last_seen_ts < self._absent_reset_s:
                return None
            logger.info(
                "Track id %d vắng quá %.0f giây; nhả khoá để chọn người khác.",
                self._locked_id,
                self._absent_reset_s,
            )
            self._locked_id = None
        elif self._locked_id is not None and ids is None:
            # Không có track id (tracking tắt hoặc backend không trả id):
            # không thể bám id, dùng khung bao lớn nhất.
            self._locked_id = None

        index = int(np.argmax([_box_area(box) for box in xyxy]))
        if ids is not None:
            self._locked_id = ids[index]
        self._last_seen_ts = now
        return index

    def _mark_absent(self) -> None:
        """Ghi nhận khung không có ai (để đồng hồ nhả khoá chạy đúng)."""
        if self._locked_id is None:
            self._last_seen_ts = time.monotonic()
