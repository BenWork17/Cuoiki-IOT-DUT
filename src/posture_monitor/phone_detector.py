"""Model dò điện thoại COCO và bộ lọc thời gian nối vào vòng lặp.

Vì sao cần model thứ hai
------------------------
``yolo11n-pose`` chỉ có lớp ``person``, nên nó không bao giờ trả hộp
``cell phone``. :mod:`posture_monitor.phone` đã có phép đo hình học
(khoảng cách cổ tay ↔ hộp) nhưng cố ý **không** tự chạy model, không tự giữ
trạng thái. Module này là hai mảnh còn thiếu:

- :class:`PhoneDetector` — nạp model detect COCO thứ hai và trả hộp lớp
  ``cell phone`` (index 67, :data:`posture_monitor.phone.PHONE_CLASS_ID`)
  **trong hệ pixel của khung đưa vào**. Ultralytics tự co hộp từ ``imgsz``
  về kích thước ảnh gốc; module không tự nhân/chia tỉ lệ, và cũng không nhận
  hộp trong hệ 320 vì ``phone.hand_phone_contact`` cần cùng hệ với keypoint.
- :class:`PhoneSignal` — chạy detect mỗi ``detect_every_n_frames`` khung,
  giữ hộp gần nhất tối đa ``box_ttl_s``, rồi gọi ``hand_phone_contact`` ở
  **mọi** khung để có trạng thái chạm liên tục theo thời gian.

Vì sao nhịp detect phải cấu hình được
-------------------------------------
Số liệu duy nhất đã đo cho model detect là ``yolo11n`` ncnn @320 =
**98,6 ms cho một lần suy luận**, đo trên khung **tổng hợp** 640x480
(``np.zeros`` + ``cv2.rectangle``), 20 vòng, trên Pi 4 ngày 2026-10-29.
Phép đo đó **chỉ có inference**: không capture và không phải khung camera
thật, nên nó không phải thời gian xử lý một khung của pipeline. Cùng lần
chạy đó, bật pose và detect ở **mọi** khung đo được **4,90 FPS**.

Chi phí của detect **trong pipeline thật thì chưa được đo**. Phép đo
pipeline thật duy nhất của dự án là pose-only trên camera thật 704x576:
199,39 ms/khung → 5,01 FPS. Ghép detect cách khung vào đúng phép đo đó
(199,39 + 49,35 ms) ra ≈ 4,02 FPS, **không đạt** mục tiêu ≥ 5 FPS — nên
chưa có cơ sở nào để nói cấu hình detect cách khung đạt mục tiêu. Vì vậy
``phone.detect_every_n_frames`` vẫn là khóa cấu hình, mặc định ``2``, nhưng
đó là **giá trị mặc định chưa có ngân sách đo**: phải chứng minh lại bằng
``benchmark --profile pose_phone`` thật trên Pi khi camera trở lại. Test
đếm đúng số lần gọi ``detect``.

Nạp model lười, cùng quy ước với ``pose.PoseEstimator``
-------------------------------------------------------
Tạo đối tượng **không** được ném lỗi chỉ vì thiếu trọng số: máy chưa có
``yolo11n.pt`` vẫn phải chạy được các chức năng khác. Lần gọi
:meth:`PhoneDetector.detect` đầu tiên mới nạp, theo thứ tự backend của
``config.model.format``: ``ncnn`` (thư mục ``<stem>_ncnn_model``, export nếu
chưa có) → ``onnx`` → ``pt``. Không nạp được backend nào thì ném
:class:`PhoneDetectorError` với đường dẫn tuyệt đối; nơi gọi bắt lỗi đó và
tắt tính năng điện thoại — cả chương trình không chết.

Đồng hồ
-------
:class:`PhoneSignal` **không** đọc ``time.monotonic()``: thời điểm ``now``
do nơi gọi truyền vào (cùng quy ước ``presence.PresenceTracker`` nhận
``clock``), nhờ vậy test tất định và không cần ``sleep``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .logging_setup import get_logger
from .phone import PHONE_CLASS_ID, HandPhoneResult, hand_phone_contact

logger = get_logger(__name__)

#: Ngưỡng tin cậy mặc định khi gọi model detect (khớp ``phone.conf_threshold``).
DEFAULT_CONF_THRESHOLD = 0.25

#: ``imgsz`` mặc định (khớp ``phone.imgsz``).
DEFAULT_IMGSZ = 320

#: Các backend được chấp nhận, giống ``config.MODEL_FORMATS``.
_MODEL_FORMATS = ("ncnn", "onnx", "pt")


class PhoneDetectorError(RuntimeError):
    """Không nạp hoặc không chạy được model dò điện thoại.

    Nơi gọi (ví dụ :class:`PhoneSignal`) bắt lỗi này, ghi cảnh báo và tắt
    tính năng điện thoại; lỗi ở đây **không** được làm chết chương trình.
    """


def _to_numpy(value: Any) -> np.ndarray:
    """Chuyển tensor ``torch`` / ndarray / list về ``numpy`` (thuần đọc)."""
    current = value
    cpu = getattr(current, "cpu", None)
    if callable(cpu):
        current = cpu()
    to_numpy = getattr(current, "numpy", None)
    if callable(to_numpy):
        current = to_numpy()
    return np.asarray(current, dtype=float)


class PhoneDetector:
    """Nạp model COCO thứ hai và trả hộp lớp ``cell phone``.

    Args:
        weights: đường dẫn trọng số model detect (``.pt``). Truyền từ cấu
            hình, **không** hardcode. Thư mục/thư viện NCNN và ONNX suy ra từ
            tên file theo đúng quy ước ``pose.PoseEstimator``.
        conf_threshold: ngưỡng tin cậy khi gọi model, trong ``[0, 1]``.
        imgsz: kích thước ảnh đưa vào model; hộp trả ra vẫn ở hệ pixel khung.
        model_format: ``ncnn`` / ``onnx`` / ``pt`` — thứ tự backend ưu tiên,
            lấy từ ``config.model.format`` để hai model dùng cùng backend.

    Raises:
        ValueError: tham số sai (ngưỡng ngoài ``[0, 1]``, ``imgsz`` không
            dương, ``model_format`` lạ). Đây là lỗi lập trình, khác với lỗi
            thiếu trọng số — lỗi đó chỉ hiện ở :meth:`detect`.
    """

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
                f"model_format phải là một trong {_MODEL_FORMATS}, "
                f"nhận được {model_format!r}"
            )

        self._weights = Path(weights)
        self._conf_threshold = float(conf_threshold)
        self._imgsz = int(imgsz)
        self._format = model_format

        #: Model đã nạp; ``None`` cho tới lần :meth:`detect` đầu tiên.
        self._model: Any | None = None
        self._backend = "chưa nạp"
        #: Lỗi nạp đã gặp, giữ lại để mọi lần gọi sau báo cùng một lỗi.
        self._load_error: str | None = None

    @property
    def backend(self) -> str:
        """Backend đang dùng: ``ncnn``, ``onnx``, ``pt`` hoặc ``chưa nạp``."""
        return self._backend

    @property
    def weights(self) -> Path:
        return self._weights

    # -- nạp model (lười) -----------------------------------------------

    def _yolo(self):
        from ultralytics import YOLO  # noqa: PLC0415 - import nặng, cố ý muộn

        return YOLO

    def _ncnn_dir(self) -> Path:
        """Thư mục NCNN theo quy ước ultralytics: ``<stem>_ncnn_model``."""
        return self._weights.with_name(f"{self._weights.stem}_ncnn_model")

    def _onnx_path(self) -> Path:
        return self._weights.with_suffix(".onnx")

    def _ensure(self) -> None:
        """Nạp model lần đầu; ném :class:`PhoneDetectorError` nếu không được.

        Không cache lỗi thành ``None`` model im lặng: mỗi lần gọi lại đều
        báo lỗi có đường dẫn để người dùng biết sửa gì.
        """
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
        """Thử lần lượt backend theo thứ tự của ``config.model.format``."""
        if self._format == "ncnn":
            if self._load_ncnn():
                return True
            logger.warning(
                "Backend NCNN của model dò điện thoại không dùng được; "
                "rơi về ONNX rồi PyTorch."
            )
        if self._format in ("ncnn", "onnx"):
            if self._load_onnx():
                return True
            logger.warning(
                "Backend ONNX của model dò điện thoại không dùng được; "
                "rơi về PyTorch (.pt)."
            )
        return self._load_pt()

    def _load_ncnn(self) -> bool:
        directory = self._ncnn_dir()
        if not directory.is_dir():
            logger.info(
                "Chưa có thư mục NCNN '%s'; export một lần với imgsz=%d.",
                directory,
                self._imgsz,
            )
            if not self._export("ncnn", directory):
                return False
        try:
            self._model = self._yolo()(str(directory))
            self._backend = "ncnn"
            logger.info("Đã nạp model dò điện thoại NCNN từ '%s'.", directory)
            return True
        except Exception as exc:  # noqa: BLE001 - backend lỗi không được crash
            logger.warning("Nạp model dò điện thoại NCNN thất bại: %s", exc)
            return False

    def _load_onnx(self) -> bool:
        path = self._onnx_path()
        if not path.is_file():
            logger.info(
                "Chưa có file ONNX '%s'; export một lần với imgsz=%d.",
                path,
                self._imgsz,
            )
            if not self._export("onnx", path):
                return False
        try:
            self._model = self._yolo()(str(path))
            self._backend = "onnx"
            logger.info("Đã nạp model dò điện thoại ONNX từ '%s'.", path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Nạp model dò điện thoại ONNX thất bại: %s", exc)
            return False

    def _load_pt(self) -> bool:
        try:
            self._model = self._yolo()(str(self._weights))
            self._backend = "pt"
            logger.info(
                "Đã nạp model dò điện thoại PyTorch từ '%s'.", self._weights
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Nạp model dò điện thoại PyTorch thất bại: %s", exc)
            return False

    def _export(self, fmt: str, target: Path) -> bool:
        """Export từ ``.pt`` sang ``fmt``; không ném, trả ``True`` nếu có file."""
        if not self._weights.is_file():
            logger.warning(
                "Không export được %s: thiếu trọng số nguồn '%s'.",
                fmt,
                self._weights,
            )
            return False
        try:
            produced = self._yolo()(str(self._weights)).export(
                format=fmt, imgsz=self._imgsz
            )
            produced_path = Path(str(produced))
            if produced_path.exists():
                logger.info("Export %s xong: '%s'.", fmt, produced_path)
                return True
            logger.warning(
                "Export %s báo xong nhưng không thấy '%s'.", fmt, produced_path
            )
        except Exception as exc:  # noqa: BLE001 - export lỗi phải rơi tiếp
            logger.warning("Export %s lỗi: %s", fmt, exc)
        return target.exists()

    # -- suy luận -------------------------------------------------------

    def detect(self, frame: np.ndarray) -> list[tuple[float, float, float, float]]:
        """Trả hộp ``cell phone`` trong **hệ pixel của ``frame``**.

        Args:
            frame: ảnh BGR ``uint8`` đúng như ``FrameSource.read`` trả.

        Returns:
            Danh sách ``(x1, y1, x2, y2)`` pixel trên khung gốc, đã lọc đúng
            lớp :data:`~posture_monitor.phone.PHONE_CLASS_ID`. Hộp có toạ độ
            không hữu hạn, âm cạnh, hoặc bị đảo cạnh đều bị bỏ. Danh sách
            rỗng là kết quả hợp lệ ("không thấy điện thoại").

        Raises:
            PhoneDetectorError: không nạp được model (thiếu trọng số, thiếu
                thư viện) hoặc model lỗi lúc suy luận. Nơi gọi bắt lỗi này
                và tắt tính năng.
        """
        self._ensure()
        try:
            results = self._model.predict(
                frame,
                imgsz=self._imgsz,
                conf=self._conf_threshold,
                verbose=False,
            )
        except Exception as exc:  # noqa: BLE001 - lỗi backend phải thành lỗi riêng
            raise PhoneDetectorError(
                "Model dò điện thoại lỗi khi suy luận trên khung hình: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        boxes = _phone_boxes_from_results(results)
        return boxes


def _phone_boxes_from_results(results: Any) -> list[tuple[float, float, float, float]]:
    """Lọc hộp lớp 67 trong output ultralytics, giữ nguyên hệ pixel khung.

    Tách thành hàm thuần để test gọi trực tiếp bằng đối tượng giả, không cần
    model. Không nhân/chia ``imgsz`` ở đây: ultralytics **đã** trả hộp trong
    hệ ảnh gốc, và ``phone.hand_phone_contact`` so khoảng cách với keypoint
    pose cùng hệ đó.
    """
    if not results:
        return []
    result = results[0]

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []

    classes = getattr(boxes, "cls", None)
    if classes is None:
        # Không có nhãn lớp thì không thể khẳng định đây là điện thoại:
        # không đoán (spec v2 §11.4).
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
        # Hộp đảo cạnh hoặc âm cạnh là hộp hỏng của bộ dò, không phải điện
        # thoại nằm ngược chiều.
        if x2 <= x1 or y2 <= y1:
            continue
        found.append((x1, y1, x2, y2))
    return found


class PhoneSignal:
    """Nối model dò điện thoại vào vòng lặp, có lọc thời gian.

    Mỗi khung gọi :meth:`observe`:

    - Nếu tắt (``config.enabled`` sai) hoặc khung không có keypoint dùng được
      (không đọc được hình dạng, hoặc cả hai cổ tay dưới ``min_kp_conf``) thì
      **không** chạy detect và trả ``None``.
    - Cứ ``detect_every_n_frames`` khung dùng được thì chạy detect một lần,
      ghi lại hộp cùng thời điểm.
    - Hộp cũ hơn ``box_ttl_s`` bị bỏ; sau đó không có hộp nào để xét.
    - Có hộp còn hạn thì gọi ``hand_phone_contact`` với keypoint của **khung
      hiện tại** và hộp đã lưu, trả :class:`HandPhoneResult`.

    Thời gian chạm liên tục nằm ở :attr:`held_s`; :attr:`in_use` thành
    ``True`` khi ``held_s >= config.hold_s``.

    Args:
        config: :class:`~posture_monitor.config.Config` đầy đủ; đọc
            ``config.phone``, ``config.model.format`` và
            ``config.model.kp_conf_min``.
        detector: :class:`PhoneDetector` (hoặc đối tượng cùng giao diện).
            ``None`` thì tự dựng từ ``config.phone`` — an toàn vì model nạp
            lười, thiếu trọng số chỉ lỗi ở lần detect đầu.
        min_kp_conf: ngưỡng tin cậy cổ tay; mặc định lấy
            ``config.model.kp_conf_min``.

    Raises:
        ValueError: khi một ngưỡng trong ``config.phone`` vô lý (âm/không hữu
            hạn). Cấu hình đã kiểm tra lúc nạp, đây chỉ là chốt phòng vệ.
    """

    def __init__(
        self,
        config,
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
        self._proximity_px = _finite_non_negative(
            self._cfg.touching_slack_px, "touching_slack_px"
        )
        self._min_kp_conf = (
            float(config.model.kp_conf_min)
            if min_kp_conf is None
            else float(min_kp_conf)
        )

        if detector is not None:
            self._detector = detector
        else:
            weights = self._cfg.detect_weights.strip() or (
                f"{self._cfg.detect_model}.pt"
            )
            self._detector = PhoneDetector(
                weights,
                conf_threshold=self._cfg.conf_threshold,
                imgsz=self._cfg.imgsz,
                model_format=config.model.format,
            )

        #: Số khung có keypoint dùng được kể từ lúc tạo.
        self._frames_seen = 0
        #: Hộp của lần detect gần nhất và thời điểm detect.
        self._boxes: list[tuple[float, float, float, float]] = []
        self._boxes_ts: float | None = None
        #: Mốc bắt đầu chuỗi chạm liên tục; ``None`` khi không chạm.
        self._contact_since: float | None = None
        #: Bật ``False`` khi detect lỗi: tắt tính năng cho phần đời còn lại.
        self._failed = False
        #: Số giây chạm liên tục tới lần :meth:`observe` gần nhất.
        self._held_s = 0.0

    @property
    def enabled(self) -> bool:
        """Tính năng còn chạy hay không (cấu hình bật **và** chưa gặp lỗi)."""
        return self._enabled and not self._failed

    @property
    def held_s(self) -> float:
        """Số giây chạm liên tục tới lần :meth:`observe` gần nhất."""
        return self._held_s

    @property
    def in_use(self) -> bool:
        """``True`` khi đã chạm liên tục đủ ``config.phone.hold_s``."""
        return self._held_s >= self._hold_s

    def observe(
        self, frame: np.ndarray, keypoints: object, now: float
    ) -> HandPhoneResult | None:
        """Xét một khung và cập nhật trạng thái chạm.

        Args:
            frame: ảnh BGR của khung; chỉ dùng khi tới nhịp detect.
            keypoints: mảng ``(17, 3)`` ``[x, y, conf]`` pixel cùng hệ với
                hộp, ví dụ ``PoseResult`` ghép ``xy``/``conf``.
            now: thời điểm hiện tại (giây, đơn điệu) do nơi gọi cung cấp.

        Returns:
            :class:`~posture_monitor.phone.HandPhoneResult` khi có hộp còn
            hạn để xét, ``None`` khi không xét được (tắt, thiếu keypoint,
            chưa detect lần nào, hoặc hộp đã hết hạn).
        """
        if not self.enabled:
            return None

        now = float(now)
        if not math.isfinite(now):
            return None

        keypoints_array = _usable_keypoints(keypoints, self._min_kp_conf)
        if keypoints_array is None:
            return None

        self._frames_seen += 1
        if (self._frames_seen - 1) % self._detect_every == 0:
            if not self._run_detect(frame, now):
                return None

        if self._boxes_expired(now):
            self._boxes = []
            self._boxes_ts = None
        if not self._boxes:
            self._reset_contact()
            return None

        result = hand_phone_contact(
            keypoints_array,
            self._boxes,
            proximity_px=self._proximity_px,
            min_kp_conf=self._min_kp_conf,
        )
        self._update_contact(result.co_cham, now)
        return result

    # -- nội bộ ---------------------------------------------------------

    def _run_detect(self, frame: np.ndarray, now: float) -> bool:
        """Chạy detect, cập nhật hộp. Trả ``False`` nếu tính năng vừa tắt."""
        try:
            boxes = self._detector.detect(frame)
        except PhoneDetectorError as exc:
            # Thiếu trọng số/thiếu backend: tắt tính năng điện thoại và để
            # luồng chính chạy tiếp (spec v2 §11.4).
            logger.warning(
                "Tắt tính năng phát hiện điện thoại: %s", exc
            )
            self._failed = True
            self._boxes = []
            self._boxes_ts = None
            self._reset_contact()
            return False
        self._boxes = list(boxes)
        self._boxes_ts = now
        return True

    def _boxes_expired(self, now: float) -> bool:
        if self._boxes_ts is None:
            return True
        return (now - self._boxes_ts) > self._box_ttl_s

    def _update_contact(self, touching: bool, now: float) -> None:
        if not touching:
            self._reset_contact()
            return
        if self._contact_since is None:
            self._contact_since = now
        self._held_s = max(0.0, now - self._contact_since)

    def _reset_contact(self) -> None:
        self._contact_since = None
        self._held_s = 0.0


def _usable_keypoints(keypoints: object, min_kp_conf: float) -> np.ndarray | None:
    """Keypoint nếu đọc được hình dạng và có ít nhất một cổ tay đủ tin cậy.

    Không có cổ tay đủ tin cậy thì ``hand_phone_contact`` chắc chắn trả
    "không chạm"; bỏ qua luôn để khỏi chạy model detect vô ích.
    """
    try:
        array = np.asarray(keypoints, dtype=float)
    except (TypeError, ValueError):
        return None
    if array.ndim != 2 or array.shape[1] < 3:
        return None
    if array.shape[0] <= 10:
        return None
    for index in (9, 10):
        confidence = float(array[index, 2])
        if math.isfinite(confidence) and confidence >= min_kp_conf:
            return array
    return None


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
        raise ValueError(
            f"{name} phải là số hữu hạn không âm, nhận được {value!r}"
        )
    return number
