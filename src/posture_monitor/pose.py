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
bám theo một track id. Track id còn trong khung thì bám đúng nó, nên người thứ
hai đi ngang qua không làm nhảy người đang theo dõi.

Track id **mất khỏi khung** là ca khác: bộ theo dõi (BotSORT) đổi id khi người
cúi xuống, rời nửa khung hoặc ánh sáng đổi, trong khi người vẫn ngồi đó. Bám
mãi id cũ trong trường hợp này làm :meth:`PoseEstimator.detect` trả ``None``
suốt ``timing.absent_reset_s`` (mặc định 120 s): mất skeleton trên khung hình
và ``presence`` báo "quay lại bàn học" oan. Vì vậy khi id cũ mất mà khung **còn
người**, module bám lại ngay vào người có khung bao lớn nhất và cập nhật
``_locked_id``; chỉ hộp quá nhỏ so với khung (rác của bộ dò) mới bị từ chối,
xem :data:`REACQUIRE_MIN_FRAME_RATIO`. Khung không còn ai mới là vắng thật:
trả ``None`` và để đồng hồ chạy tới khi hết ``absent_reset_s`` mới nhả khoá.

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

#: Tỉ lệ cạnh dài khung bao tối thiểu so với cạnh dài khung hình để một phát
#: hiện được phép **bám lại** khi track id đang khoá biến mất.
#:
#: Vì sao cần: khi bám lại, module lấy khung bao lớn nhất của khung hiện tại.
#: Bộ dò vẫn thường trả những hộp rác rất nhỏ (mép bàn, ghế, bóng đổ) trùng
#: đúng lúc BotSORT đổi id; bám vào một hộp như vậy sẽ vẽ skeleton sai chỗ và
#: vẫn làm ``presence`` đếm 0 keypoint thân trên — tức là đổi lỗi "mất
#: skeleton" thành lỗi "skeleton nhảy sang góc bàn".
#:
#: **Đây là ngưỡng mặc định CHƯA đo trên dữ liệu thật.** Không có phép đo nào
#: trong repo xác nhận 0,05: nó được chọn để một người ngồi bàn (thường chiếm
#: phần lớn chiều cao khung) luôn vượt, còn hộp rác vài chục pixel thì không.
#: Phải đo lại trên camera thật trước khi coi là con số đã hiệu chuẩn.
REACQUIRE_MIN_FRAME_RATIO = 0.05

#: Tỉ lệ khung (``width / height``) tối đa được phép khi bám lại. Hộp người
#: ngồi không bao giờ dẹt như mép bàn hay bóng đổ, nên một hộp rộng gấp nhiều
#: lần chiều cao là bằng chứng đủ mạnh rằng đó không phải người. Đặt 4,0 theo
#: cả hai chiều (dùng nghịch đảo cho hộp đứng) để không phụ thuộc hộp nghiêng
#: về bên nào.
#:
#: **CHƯA đo trên dữ liệu thật** — cùng mức tín nhiệm với
#: :data:`REACQUIRE_MIN_FRAME_RATIO`.
REACQUIRE_MAX_ASPECT_RATIO = 4.0

#: Độ dịch tâm tối đa (tính theo **cạnh dài của hộp trước**) khi bám lại, so
#: với hộp của người đang được theo dõi ở khung trước.
#:
#: Vì sao cần cổng này — đây là lỗi nghiêm trọng nhất của bản bám lại đầu tiên:
#: nếu chỉ đòi "hộp lớn nhất đủ to", thì khi người học **rời bàn** mà trong
#: khung còn **một người khác**, ``_locked_id`` nhảy sang người kia và
#: ``presence`` **không bao giờ** báo vắng — đúng tính năng mà bản sửa định
#: cứu bị phá từ chiều ngược lại. Người đi lại trong phòng cũng dịch chuyển,
#: nhưng không nhảy sang góc khác trong một khung ở 5 FPS, nên một cổng liên
#: tục không gian là đủ và không cần mô hình chuyển động.
#:
#: 0,5 nghĩa là hộp mới không được lệch tâm quá nửa cạnh dài hộp cũ. Với người
#: ngồi bàn (hộp cao ~360 px), mức chịu được là ~180 px — rộng hơn nhịp thở,
#: cúi xuống hay xê dịch ghế rất nhiều, nhưng chặn được việc nhảy sang người
#: đứng ở góc kia khung.
#:
#: **CHƯA đo trên dữ liệu thật.**
REACQUIRE_MAX_CENTER_SHIFT_RATIO = 0.5

#: IoU tối thiểu giữa hộp mới và hộp trước để coi là "cùng một người" khi bám
#: lại. Đây là **đường thay thế** cho cổng dịch tâm: hộp có thể lệch tâm xa
#: nhưng vẫn chồng lấn nhiều (người cúi xuống làm hộp co lại một phía), và
#: ngược lại. Chỉ cần **một trong hai** điều kiện đúng.
#:
#: 0,1 rất thấp so với ngưỡng thường dùng cho bài toán "cùng đối tượng" (0,3 –
#: 0,5), vì ở đây mục tiêu không phải nhận dạng chính xác mà là **loại trừ
#: hộp ở chỗ khác hẳn**. Đặt cao hơn sẽ chặn oan đúng ca cần cứu: người cúi
#: xuống làm hộp co mạnh nên IoU với hộp trước tụt nhanh.
#:
#: **CHƯA đo trên dữ liệu thật.**
REACQUIRE_MIN_IOU = 0.1


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


def _safe_len(value) -> int:
    """``len(value)`` nhưng trả ``0`` thay vì ném lỗi với đối tượng lạ.

    ``boxes`` của ultralytics luôn có ``__len__``, nhưng ``detect`` phải sống
    sót với backend khác (spec v2 §11.4: lỗi backend không được crash). Dùng
    cho việc đọc ``len(boxes)`` **trước** khi kiểm tra ``None``, nên không thể
    giả định kiểu.
    """
    if value is None:
        return 0
    try:
        return int(len(value))
    except TypeError:  # pragma: no cover - backend lạ
        return 0


def _box_is_big_enough(box: np.ndarray, frame_shape) -> bool:
    """Khung bao có chiếm đủ khung hình để được phép bám lại không.

    Dùng cho đúng một quyết định: khi track id đang khoá đã mất, có nên lấy
    hộp lớn nhất của khung hiện tại làm người mới hay không. Ngưỡng là
    :data:`REACQUIRE_MIN_FRAME_RATIO` (mặc định **chưa đo trên dữ liệu thật**).

    **Đòi CẢ HAI trục** vượt ngưỡng, không dùng ``max``. Bản đầu tiên dùng
    ``max(width / frame_w, height / frame_h)`` và đo được là hỏng: một mép bàn
    400×4 chỉ cao 4 px (0,8 % chiều cao khung) nhưng rộng 62 % chiều rộng, nên
    ``max`` cho nó qua. Cùng lỗi với bóng đổ 500×6 và thanh ghế 350×10. Đòi cả
    hai trục loại được chúng mà vẫn giữ được người ngồi bị bàn che nửa dưới
    (300×200: rộng 47 %, cao 42 % — vượt cả hai).

    Thêm cổng tỉ lệ khung :data:`REACQUIRE_MAX_ASPECT_RATIO`: hộp người ngồi
    không dẹt, nên ``width / height`` quá lớn (hoặc quá nhỏ) là bằng chứng
    không phải người, kể cả khi cả hai cạnh đều vượt ngưỡng.

    Tỉ lệ tính trên cạnh tương ứng của khung nên không phụ thuộc độ phân giải
    camera.

    Args:
        box: ``x1, y1, x2, y2`` pixel.
        frame_shape: ``(height, width, ...)`` như ``numpy.ndarray.shape`` của
            khung; ``None`` khi không biết hình học khung.

    Returns:
        ``False`` khi biết khung hình mà hộp quá nhỏ hoặc quá dẹt; ``True``
        khi hộp đủ lớn hoặc khi không có thông tin khung để so (không được
        chặn oan).
    """
    width = max(0.0, float(box[2] - box[0]))
    height = max(0.0, float(box[3] - box[1]))
    if frame_shape is None:
        return width > 0.0 or height > 0.0
    try:
        frame_h = float(frame_shape[0])
        frame_w = float(frame_shape[1])
    except (TypeError, IndexError, ValueError):  # pragma: no cover - phòng vệ
        return width > 0.0 or height > 0.0
    if frame_h <= 0.0 or frame_w <= 0.0:  # pragma: no cover - phòng vệ
        return width > 0.0 or height > 0.0
    if width <= 0.0 or height <= 0.0:
        return False
    # Cổng tỉ lệ khung: hộp dẹt là bàn/ghế/bóng, không phải người.
    aspect = width / height
    if aspect > REACQUIRE_MAX_ASPECT_RATIO:
        return False
    if (1.0 / aspect) > REACQUIRE_MAX_ASPECT_RATIO:
        return False
    return bool(
        (width / frame_w >= REACQUIRE_MIN_FRAME_RATIO)
        and (height / frame_h >= REACQUIRE_MIN_FRAME_RATIO)
    )


def _box_iou(a: np.ndarray, b: np.ndarray) -> float:
    """Giao trên hợp (IoU) của hai khung bao pixel; ``0.0`` khi không giao.

    Không ném lỗi với hộp suy biến (rộng hoặc cao bằng 0): trả ``0.0``.
    """
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
    """Độ dịch tâm giữa ``box`` và ``previous``, chia cho cạnh dài ``previous``.

    Mẫu số là **cạnh dài của hộp trước** (không phải hộp mới): hộp mới có thể
    co lại rất nhiều khi người cúi xuống, lấy nó làm mẫu sẽ phóng đại độ dịch
    và chặn oan đúng ca cần cứu.

    Trả ``inf`` khi hộp trước suy biến (không có cạnh dài), để mọi so sánh
    ngưỡng đều thất bại thay vì chia cho 0.
    """
    px1, py1, px2, py2 = (float(v) for v in previous[:4])
    bx1, by1, bx2, by2 = (float(v) for v in box[:4])
    longest = max(px2 - px1, py2 - py1)
    if longest <= 0.0:
        return float("inf")
    pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
    bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
    return float(np.hypot(bcx - pcx, bcy - pcy)) / longest


def _box_is_continuous(box: np.ndarray, previous: np.ndarray | None) -> bool:
    """Hộp mới có còn là **cùng người** với hộp trước không (cổng không gian).

    Đúng khi **một trong hai**: IoU >= :data:`REACQUIRE_MIN_IOU`, hoặc tâm
    dịch không quá :data:`REACQUIRE_MAX_CENTER_SHIFT_RATIO` lần cạnh dài hộp
    trước. Hai điều kiện bù nhau: người cúi xuống làm hộp co mạnh (IoU tụt) mà
    tâm gần như đứng yên; người xê dịch ghế làm tâm lệch nhưng hộp vẫn chồng
    lấn.

    ``previous is None`` (chưa từng có hộp nào) → ``True``: chưa có gì để so,
    chặn ở đây chỉ tạo lỗi giả.

    **Đây là cổng chống "cướp khoá"**: khi người học rời bàn mà còn người khác
    trong khung, hộp người kia ở chỗ khác hẳn nên cả hai điều kiện đều sai,
    ``_locked_id`` giữ nguyên, và ``presence`` báo vắng đúng hạn.
    """
    if previous is None:
        return True
    if _box_iou(box, previous) >= REACQUIRE_MIN_IOU:
        return True
    return (
        _box_center_shift_ratio(box, previous)
        <= REACQUIRE_MAX_CENTER_SHIFT_RATIO
    )


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

        #: Khung bao của người đang theo dõi ở lần trả :class:`PoseResult` gần
        #: nhất. Dùng làm mốc **liên tục không gian** khi track id đổi: hộp
        #: mới phải còn dính tới hộp này (xem :func:`_box_is_continuous`).
        #: Không có nó, người học rời bàn mà còn ai khác trong khung thì khoá
        #: nhảy sang người kia và ``presence`` không bao giờ báo vắng.
        self._last_box: np.ndarray | None = None

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

        ``last_person_count`` **luôn** là ``len(boxes)`` của chính khung này,
        kể cả khi không lấy được keypoint. Trước đây nhánh ``_select`` trả
        ``None`` còn đặt nó về ``0``, gộp "còn người nhưng mất track id" với
        "khung trống" — hai tình huống khác nhau mà tầng trên cần phân biệt
        (``presence`` đếm keypoint, nên nó tự chịu được ``pose=None``; cái sai
        là đầu vào bị nói dối).
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
        count = _safe_len(boxes)
        if boxes is not None and (keypoints is None or count == 0):
            # Có hộp nhưng không đọc được keypoint: vẫn báo đúng **số người đã
            # thấy**, không nói dối là khung trống. ``len(boxes)`` bọc trong
            # ``_safe_len`` vì ``boxes`` có thể là đối tượng lạ không có
            # ``__len__`` dùng được.
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

        index = self._select(
            xyxy, ids, frame_shape=getattr(frame, "shape", None)
        )
        if index is None:
            # Không chọn được ai dù khung có ``count`` người: hoặc mọi hộp đều
            # quá nhỏ/rác, hoặc track cũ mất mà hộp lớn nhất không đủ liên tục
            # không gian (người học đã rời bàn, còn người khác trong khung).
            # Vẫn báo đúng số người đã thấy — ``None`` ở đây là "chưa xác định
            # được người để theo dõi", không phải "khung trống".
            return None

        box = xyxy[index]
        # Ghi mốc không gian **sau mọi lần trả PoseResult**, để khung sau còn
        # cái để so khi BotSORT đổi id.
        self._last_box = np.array(box, dtype=np.float32, copy=True)
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

    def _select(
        self,
        xyxy: np.ndarray,
        ids: list[int] | None,
        frame_shape=None,
    ) -> int | None:
        """Chọn index người đang theo dõi trong danh sách phát hiện.

        Quy tắc:

        1. Đang khoá một track id và track đó **còn** trong khung → chọn nó,
           bất kể ai khác to hơn. Người thứ hai đi ngang qua không cướp được.
        2. Track đang khoá **mất** nhưng khung còn người → bám lại ngay, nhưng
           chỉ khi hộp lớn nhất thoả **cả hai** cổng:
           :func:`_box_is_big_enough` (đủ lớn trên cả hai trục, không quá dẹt)
           **và** :func:`_box_is_continuous` (còn dính tới hộp của khung
           trước). Đây là đường sửa lỗi "vào phiên học thì mất skeleton":
           BotSORT đổi id khi người cúi xuống, nên chờ hết ``absent_reset_s``
           (120 s) mới bám lại nghĩa là bỏ 120 s không vẽ skeleton và báo vắng
           oan.
        3. Track đang khoá mất và hộp lớn nhất **không** qua được hai cổng
           trên → giữ khoá. Chưa hết ``absent_reset_s`` thì trả ``None``; quá
           hạn thì nhả khoá và chọn hộp lớn nhất như cũ (hành vi cũ, giữ
           nguyên). Nhánh này chính là chỗ bảo đảm "người học rời bàn vẫn được
           báo vắng đúng hạn": còn người khác trong khung nhưng ở chỗ khác thì
           khoá **không** nhảy sang.
        4. Khung không có hộp nào → ``None`` (vắng thật; ``detect`` gọi
           :meth:`_mark_absent` để đồng hồ nhả khoá chạy).
        5. ``ids is None`` (tracking tắt hoặc backend không trả id) → không thể
           bám id, dùng hộp lớn nhất như cũ.

        Args:
            xyxy: mảng ``(N, 4)`` khung bao pixel của khung hiện tại.
            ids: track id tương ứng từng hộp, hoặc ``None``.
            frame_shape: ``shape`` của khung (để chuẩn hoá ngưỡng bám lại);
                ``None`` khi không biết.

        Returns:
            Index trong ``xyxy``, hoặc ``None`` khi không xác định được người.
        """
        now = time.monotonic()
        if not xyxy.size:
            return None

        if self._locked_id is not None and ids is not None:
            matches = [i for i, tid in enumerate(ids) if tid == self._locked_id]
            if matches:
                self._last_seen_ts = now
                return matches[0]

            # Id cũ đã mất. Thử bám lại ngay trong khung này thay vì chờ hết
            # ``absent_reset_s``: người vẫn ngồi đó, chỉ nhãn track đổi.
            # NHƯNG phải qua **cả hai** cổng — hộp đủ lớn/không dẹt, và còn
            # liên tục về vị trí so với hộp khung trước. Thiếu cổng thứ hai
            # thì người học rời bàn mà còn ai khác trong khung là khoá nhảy
            # sang người kia, và ``presence`` không bao giờ báo vắng.
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

            # Hộp lớn nhất không dùng được: hoặc là rác (quá nhỏ/quá dẹt),
            # hoặc là người khác ở chỗ khác hẳn. Giữ khoá; chỉ nhả khi đã vắng
            # đủ lâu, đúng như trước đây.
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
