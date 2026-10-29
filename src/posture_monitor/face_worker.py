"""Worker nhận diện khuôn mặt chạy nền (spec V3 §5.13, §5.16).

:mod:`posture_monitor.faces` lo phần OpenCV (YuNet + SFace) nhưng **cố ý**
không tự chạy theo nhịp và không đụng vào vòng lặp giám sát. Module này là
lớp nối: một luồng riêng nhận khung từ vòng lặp chính, thưa ra theo
``face.interval_s``, và để lại **một** kết quả danh tính mới nhất.

Vì sao phải có luồng riêng: đường ống đo trên Pi 4 tốn **86,1 ms/lượt**
(§4.2), trong khi ngân sách của vòng lặp chính là 200 ms/khung (§4.3) và khung
đó còn phải chạy YOLO pose. Chạy nhận diện ngay trong vòng lặp sẽ ăn gần nửa
ngân sách cho một tín hiệu chỉ cần cập nhật mỗi vài giây. Vì vậy
:meth:`FaceWorker.submit` **trả về ngay**, không bao giờ chờ nhận diện xong.

Bốn quyết định đáng ghi lại:

- **Nhịp do ``submit`` quyết định, không do luồng ngủ.** Vòng lặp chính vốn
  đã có đồng hồ của nó; ``submit`` so ``now`` với lần nhận gần nhất rồi mới
  hẹn một lượt. Nhờ vậy ``interval_s`` kiểm chứng được bằng đồng hồ giả mà
  không phải chờ thời gian thật.
- **Khung không có khuôn mặt / kho rỗng → ``UNKNOWN``, không bao giờ
  ``MISMATCH``.** Che mặt, quay đi, ngược sáng đều dẫn tới ``UNKNOWN``; chỉ
  khi *tìm thấy* khuôn mặt và so với một gallery **không rỗng** mà mọi điểm
  đều dưới ngưỡng thì mới là ``MISMATCH`` (§5.13, bảng "Ba kết quả danh
  tính"). Suy "không nhận ra ⇒ người lạ" là điều spec cấm.
- **Tuổi tín hiệu là một phần của kết quả.** :meth:`latest` trả ``fresh =
  False`` và **xoá tên** khi kết quả cũ hơn ``interval_s * 3``; UI nhờ đó nói
  "chưa có dữ liệu mới" thay vì trình bày kết luận cũ như mới (§5.16).
- **Tắt thì tắt hẳn, có lý do.** ``match_threshold`` là ``null`` (chưa đo)
  hay thiếu mô hình thì worker không chạy và :meth:`latest` trả ``UNKNOWN``
  kèm thông điệp tiếng Việt nêu cách sửa. Không chạy với ngưỡng bịa.

**Không ghi ảnh.** Khung chỉ sống trong RAM: ``submit`` giữ **một** khung mới
nhất, luồng xử lý xong thì bỏ tham chiếu. Không có lời gọi ghi tệp nào trong
module này (§5.13.1).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, replace
from typing import Any, Callable

import numpy as np

from .config import FaceConfig
from .faces import (
    DetectedFace,
    FaceModelError,
    FaceStore,
    best_match,
    validate_threshold,
)
from .logging_setup import get_logger

logger = get_logger(__name__)

#: Kết quả danh tính, đúng ba giá trị của spec §5.13.
MATCH = "MATCH"
MISMATCH = "MISMATCH"
UNKNOWN = "UNKNOWN"
OUTCOMES = (MATCH, MISMATCH, UNKNOWN)

#: Số lần ``interval_s`` mà một kết quả còn được coi là "mới".
#:
#: Yêu cầu chống hiểu nhầm của spec §5.16: tín hiệu cũ hơn ngưỡng này thì UI
#: phải nói "chưa có dữ liệu mới", **không** được trình bày kết luận cũ như
#: vừa đo. Ba nhịp (mặc định 6 s với ``interval_s: 2.0``) đủ rộng cho một lần
#: nhận diện chậm bất thường mà vẫn không giữ một danh tính sai quá lâu.
STALE_INTERVAL_FACTOR = 3.0

#: Thông điệp khi chưa có kết quả nào.
NO_DATA_MESSAGE = "Chưa có dữ liệu nhận diện khuôn mặt."


@dataclass(frozen=True)
class IdentityReading:
    """Một kết quả danh tính kèm tuổi của tín hiệu.

    Attributes:
        outcome: ``MATCH`` / ``MISMATCH`` / ``UNKNOWN``.
        name: Tên người khớp; ``None`` trừ khi ``outcome == MATCH``.
        score: Điểm cosine cao nhất (``0.0`` khi không so được).
        age_s: Tuổi tín hiệu (giây) tại thời điểm :meth:`FaceWorker.latest`
            trả về. ``math.inf`` khi chưa từng có kết quả.
        fresh: ``True`` nếu kết quả còn trong hạn ``interval_s * 3``. Khi
            ``False``, ``name`` bị xoá và ``outcome`` là ``UNKNOWN`` — nơi
            hiển thị **không được** dùng lại kết luận cũ.
        message: Ghi chú tiếng Việt cho UI (lý do chưa có dữ liệu, ...).
        box: Hộp khuôn mặt **trong hệ pixel của khung gốc** (``x, y, w, h``),
            hoặc ``None``. Đây là điều khoản hợp đồng dữ liệu của §5.13(2).
        ts: Mốc thời gian của lần đo (giây, theo đồng hồ được tiêm).
    """

    outcome: str = UNKNOWN
    name: str | None = None
    score: float = 0.0
    age_s: float = math.inf
    fresh: bool = False
    message: str = NO_DATA_MESSAGE
    box: tuple[float, float, float, float] | None = None
    ts: float = 0.0


def _default_prepare(frame: Any, detect_width: int, clahe_enabled: bool) -> Any:
    """Thu nhỏ khung về ``detect_width`` rồi (tuỳ chọn) cân bằng sáng CLAHE.

    Bắt buộc theo §5.13(1): YuNet ở 704x576 tốn 99,9 ms, ở 320x262 chỉ
    19,3 ms. Không phóng to: khung đã hẹp hơn ``detect_width`` thì giữ
    nguyên — phóng lên chỉ tốn thời gian mà không thêm chi tiết.

    CLAHE chạy trong không gian LAB với ``clipLimit=2.0`` và lưới 8x8, đúng
    như mục (3) của spec; nó là biện pháp phòng ngừa ngược sáng, không phải
    điều kiện để hệ thống chạy.
    """
    try:
        import cv2  # noqa: PLC0415 - cố ý nạp lười
    except ImportError as exc:
        raise FaceModelError(
            "Không nhận diện khuôn mặt được vì thiếu gói OpenCV "
            "(opencv-python). Hãy cài đặt theo requirements.txt."
        ) from exc
    height, width = int(frame.shape[0]), int(frame.shape[1])
    if height <= 0 or width <= 0:
        raise ValueError("Khung hình rỗng, không thu nhỏ được.")
    scale = min(1.0, float(detect_width) / float(width))
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    if clahe_enabled:
        lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
        lightness, a_chan, b_chan = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        lightness = clahe.apply(lightness)
        small = cv2.cvtColor(
            cv2.merge((lightness, a_chan, b_chan)), cv2.COLOR_LAB2BGR
        )
    return small


def map_box_to_frame(
    box: DetectedFace, scale_x: float, scale_y: float,
    frame_width: float, frame_height: float,
) -> tuple[float, float, float, float]:
    """Ánh xạ hộp từ hệ ``detect_width`` về hệ pixel của **khung gốc**.

    Đây là §5.13(2): trả nguyên toạ độ hệ 320 lên tầng trên làm mọi overlay và
    phép tính khoảng cách lệch theo tỉ lệ ``frame_w / 320``. Hàm nhận tỉ lệ
    thật (đo từ kích thước ảnh đã thu nhỏ) chứ không giả định chia hết cho 320,
    nên khung 1000x750 cũng đúng.

    Toạ độ được kẹp trong khung gốc: sai số làm tròn khi ``resize`` có thể đẩy
    mép hộp ra ngoài một pixel, và một hộp âm sẽ làm hỏng overlay.
    """
    x0 = max(0.0, min(float(box.x) * scale_x, frame_width))
    y0 = max(0.0, min(float(box.y) * scale_y, frame_height))
    width = max(0.0, min(float(box.width) * scale_x, frame_width - x0))
    height = max(0.0, min(float(box.height) * scale_y, frame_height - y0))
    return (x0, y0, width, height)


class FaceWorker:
    """Nhận diện khuôn mặt trong luồng nền, trả kết quả mới nhất.

    Args:
        config: mục ``face`` của cấu hình.
        store: kho người đã đăng ký (:class:`~posture_monitor.faces.FaceStore`).
            ``None`` thì dựng từ ``config.store_path`` (thư mục của tệp).
        recognizer: đối tượng có ``detect(image)`` và
            ``embedding(image, face)`` như :class:`FaceRecognizer`. ``None``
            thì dựng :class:`FaceRecognizer` từ ``config.detector``/``recognizer``.
        clock: hàm trả mốc thời gian (giây); test truyền đồng hồ giả.
        prepare: hàm ``(frame, detect_width, clahe_enabled) -> ảnh đã thu nhỏ``.
            Test truyền hàm giả để không cần OpenCV.

    Worker **không** bao giờ chặn luồng gọi và không ghi ảnh ra đĩa.
    """

    def __init__(
        self,
        config: FaceConfig,
        *,
        store: FaceStore | None = None,
        recognizer: Any = None,
        clock: Callable[[], float] | None = None,
        prepare: Callable[[Any, int, bool], Any] | None = None,
    ) -> None:
        self.config = config
        self._clock = clock or _monotonic
        self._prepare = prepare or _default_prepare
        self._interval_s = float(config.interval_s)
        self._stale_after_s = self._interval_s * STALE_INTERVAL_FACTOR

        #: Lý do worker không chạy; ``None`` nghĩa là chạy được.
        self._disabled_reason: str | None = None
        self._threshold: float | None = None
        if config.match_threshold is None:
            self._disabled_reason = (
                "Nhận diện khuôn mặt đang tắt: chưa đặt 'face.match_threshold' "
                "(ngưỡng phải được đo trên dữ liệu thật — spec V3 §5.13)."
            )
        else:
            try:
                self._threshold = validate_threshold(config.match_threshold)
            except ValueError as exc:
                self._disabled_reason = f"Nhận diện khuôn mặt đang tắt: {exc}"
        if config.enabled is False and self._disabled_reason is None:
            self._disabled_reason = (
                "Nhận diện khuôn mặt đang tắt theo cấu hình "
                "('face.enabled: false')."
            )

        self._store = store if store is not None else _store_from_config(config)
        self._recognizer = recognizer
        self._model_failed: str | None = None

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._closing = False
        self._pending: tuple[Any, float] | None = None
        self._accepted_at = -math.inf
        self._result: IdentityReading | None = None

    # ------------------------------------------------------------------
    # Truy vấn trạng thái
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """Worker có thật sự chạy nhận diện hay không.

        Gồm **cả** lỗi mô hình phát sinh lúc chạy: ``yunet.onnx``/``sface.onnx``
        thiếu thì worker tắt hẳn thay vì thử lại (và ghi log) mỗi nhịp.
        """
        return self.disabled_reason is None

    @property
    def disabled_reason(self) -> str | None:
        """Lý do worker tắt (đã bao gồm lỗi mô hình nếu có), hoặc ``None``."""
        return self._disabled_reason or self._model_failed

    @property
    def stale_after_s(self) -> float:
        """Ngưỡng tuổi tín hiệu (giây) mà quá đó kết quả bị coi là cũ."""
        return self._stale_after_s

    # ------------------------------------------------------------------
    # Giao diện với vòng lặp chính
    # ------------------------------------------------------------------
    def submit(self, frame: Any, now: float | None = None) -> bool:
        """Dâng một khung cho worker; **trả về ngay**, không chờ nhận diện.

        Vòng lặp chính gọi hàm này mỗi khung. Nếu chưa tới nhịp ``interval_s``
        thì khung bị bỏ (hoặc thay khung đang chờ, để không nhận diện ảnh cũ);
        tới nhịp thì một lượt được hẹn và luồng nền xử lý.

        Args:
            frame: khung BGR (chỉ sống trong bộ nhớ).
            now: mốc thời gian của khung; ``None`` thì đọc ``clock``.

        Returns:
            ``True`` nếu lượt nhận diện mới được hẹn, ``False`` nếu khung bị
            bỏ (chưa tới nhịp, worker tắt, hoặc đang dừng).
        """
        if self.disabled_reason is not None:
            return False
        if frame is None or not hasattr(frame, "shape"):
            return False
        moment = float(self._clock() if now is None else now)
        if not math.isfinite(moment):
            return False
        with self._lock:
            if self._closing:
                return False
            if moment - self._accepted_at < self._interval_s:
                if self._pending is not None:
                    # Chưa xử lý xong nhưng đã có khung mới hơn: nhận diện
                    # khung mới nhất thay vì ảnh cũ. Không hẹn thêm lượt.
                    self._pending = (frame, moment)
                return False
            self._pending = (frame, moment)
            self._accepted_at = moment
            self._ensure_thread_locked()
        self._wake.set()
        return True

    def latest(self) -> IdentityReading:
        """Kết quả mới nhất kèm tuổi tín hiệu; **không** trả kết luận cũ.

        Khi chưa có kết quả, worker tắt, hoặc kết quả cũ hơn
        ``interval_s * 3``, trả ``IdentityReading`` với ``outcome=UNKNOWN``,
        ``name=None`` và ``fresh=False`` — nơi hiển thị phải nói "chưa có dữ
        liệu mới" (§5.16), không được dùng lại tên cũ.
        """
        now = float(self._clock())
        with self._lock:
            reading = self._result
        reason = self.disabled_reason
        if reason is not None:
            return IdentityReading(
                outcome=UNKNOWN,
                age_s=math.inf,
                fresh=False,
                message=reason,
                ts=0.0,
            )
        if reading is None:
            return IdentityReading(
                outcome=UNKNOWN, age_s=math.inf, fresh=False
            )
        age = now - reading.ts
        if not math.isfinite(age) or age < 0:
            age = math.inf
        if age > self._stale_after_s:
            return IdentityReading(
                outcome=UNKNOWN,
                name=None,
                score=0.0,
                age_s=age,
                fresh=False,
                message=(
                    "Chưa có dữ liệu nhận diện mới: kết quả gần nhất đã cũ "
                    f"({age:.1f} s > {self._stale_after_s:.1f} s) nên không "
                    "dùng để kết luận."
                ),
                box=None,
                ts=reading.ts,
            )
        return replace(reading, age_s=age, fresh=True)

    def stop(self, timeout: float = 5.0) -> bool:
        """Dừng luồng nền và bỏ khung đang chờ; ``True`` nếu luồng đã dừng.

        Không treo tiến trình: luồng là daemon, ``join`` có ``timeout``. Nếu
        một lần nhận diện đang chạy thì nó tự xong (không có cơ chế huỷ giữa
        chừng của OpenCV) và kết quả bị bỏ — sau khi ``stop`` gọi ``latest``
        vẫn an toàn.
        """
        with self._lock:
            self._closing = True
            self._pending = None
            thread = self._thread
        self._wake.set()
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    def _ensure_thread_locked(self) -> None:
        """Dựng luồng nền ở lượt hẹn đầu tiên (gọi khi đã giữ ``_lock``)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="face-worker", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            while True:
                with self._lock:
                    if self._closing:
                        return
                    item = self._pending
                    self._pending = None
                if item is None:
                    break
                frame, moment = item
                reading = self._measure(frame, moment)
                del frame
                with self._lock:
                    if self._closing:
                        return
                    self._result = reading

    def _measure(self, frame: Any, moment: float) -> IdentityReading:
        """Chạy một lượt phát hiện + nhận diện trên ``frame``.

        Không raise: lỗi thường gặp (không có mặt, kho rỗng, ảnh hỏng) thành
        ``UNKNOWN`` có lý do; thiếu mô hình thì tắt worker một lần và ghi log
        thay vì thử lại mỗi nhịp.
        """
        try:
            prepared = self._prepare(
                frame, int(self.config.detect_width), bool(self.config.clahe_enabled)
            )
        except FaceModelError as exc:
            self._fail_model(exc)
            return self._unknown(str(exc), moment)
        except (ValueError, TypeError) as exc:
            return self._unknown(f"Khung hình không dùng được: {exc}", moment)

        frame_h = float(frame.shape[0])
        frame_w = float(frame.shape[1])
        prep_h = float(prepared.shape[0])
        prep_w = float(prepared.shape[1])
        if prep_w <= 0 or prep_h <= 0:
            return self._unknown("Khung hình rỗng, không nhận diện được.", moment)
        scale_x = frame_w / prep_w
        scale_y = frame_h / prep_h

        recognizer = self._recognizer
        if recognizer is None:
            recognizer = self._build_recognizer()
            if recognizer is None:
                reason = self._model_failed or "Chưa nạp được mô hình khuôn mặt."
                return self._unknown(reason, moment)

        try:
            faces = recognizer.detect(prepared)
        except FaceModelError as exc:
            self._fail_model(exc)
            return self._unknown(str(exc), moment)
        except (ValueError, TypeError) as exc:
            return self._unknown(f"Không phát hiện được khuôn mặt: {exc}", moment)

        if not faces:
            return self._unknown("Không thấy khuôn mặt nào trong khung.", moment)

        largest = max(faces, key=lambda face: face.area)
        box = map_box_to_frame(
            largest, scale_x, scale_y, frame_w, frame_h
        )

        entries = self._store.pairs()
        if not entries:
            # Gallery rỗng: KHÔNG có ai để so, nên không thể là MISMATCH.
            return IdentityReading(
                outcome=UNKNOWN,
                score=0.0,
                fresh=False,
                message="Chưa có ai được đăng ký trên thiết bị này.",
                box=box,
                ts=moment,
            )

        try:
            vector = recognizer.embedding(prepared, largest)
        except (ValueError, TypeError) as exc:
            return self._unknown(
                f"Không trích được đặc trưng khuôn mặt: {exc}", moment, box
            )

        threshold = self._threshold
        if threshold is None:
            # Không xảy ra khi đã qua ``enabled``, nhưng giữ đường phòng thủ:
            # tuyệt đối không gọi ``best_match`` với ngưỡng bịa.
            return self._unknown(
                "Chưa có ngưỡng nhận diện; không kết luận danh tính.", moment, box
            )

        result = best_match(vector, entries, threshold=threshold)
        if result.name is not None:
            return IdentityReading(
                outcome=MATCH,
                name=result.name,
                score=float(result.score),
                box=box,
                ts=moment,
            )
        return IdentityReading(
            outcome=MISMATCH,
            score=float(result.score),
            fresh=False,
            message=result.message or "Không nhận ra khuôn mặt.",
            box=box,
            ts=moment,
        )

    def _build_recognizer(self) -> Any:
        """Dựng :class:`FaceRecognizer` lần đầu; ``None`` nếu thiếu mô hình."""
        if self._model_failed is not None:
            return None
        try:
            from .faces import FaceRecognizer  # noqa: PLC0415

            self._recognizer = FaceRecognizer(
                self.config.detector, self.config.recognizer
            )
        except FaceModelError as exc:
            self._fail_model(exc)
            return None
        return self._recognizer

    def _fail_model(self, exc: Exception) -> None:
        """Ghi nhận lỗi mô hình **một lần** và tắt worker."""
        if self._model_failed is not None:
            return
        self._model_failed = f"Nhận diện khuôn mặt đang tắt: {exc}"
        logger.error("%s", self._model_failed)

    def _unknown(
        self, message: str, moment: float,
        box: tuple[float, float, float, float] | None = None,
    ) -> IdentityReading:
        """Kết quả ``UNKNOWN`` đã đo tại ``moment`` (tín hiệu tươi)."""
        return IdentityReading(
            outcome=UNKNOWN,
            score=0.0,
            fresh=False,
            message=message,
            box=box,
            ts=moment,
        )


def _store_from_config(config: FaceConfig) -> FaceStore:
    """Dựng :class:`FaceStore` từ ``face.store_path`` (chỉ dùng thư mục)."""
    from pathlib import Path  # noqa: PLC0415

    path = Path(config.store_path)
    return FaceStore(path.parent if str(path.parent) else Path("."))


def _monotonic() -> float:
    """Đồng hồ mặc định: đơn điệu, không nhảy khi đổi giờ hệ thống.

    Tuổi tín hiệu là một **hiệu** thời gian, nên dùng ``monotonic`` tránh
    việc chỉnh đồng hồ làm một kết quả đang tươi bỗng thành "cũ" (hoặc ngược
    lại). ``FaceStore`` vẫn dùng thời gian thực cho ``enrolled_at``.
    """
    import time  # noqa: PLC0415

    return time.monotonic()


__all__ = [
    "MATCH",
    "MISMATCH",
    "UNKNOWN",
    "OUTCOMES",
    "STALE_INTERVAL_FACTOR",
    "FaceWorker",
    "IdentityReading",
    "map_box_to_frame",
]
