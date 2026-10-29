"""Luồng worker nhận diện khuôn mặt **không được chết im lặng**.

Ba lỗi thật đã đo trên ``main`` (``55e0b0e``), cả ba cùng dẫn tới một hệ quả:
nhận diện khuôn mặt tắt hẳn tới khi restart tiến trình, trong khi dashboard
vẫn trả 200 và trình bày dữ liệu cũ như còn mới.

1. ``_worker_loop`` gọi ``process_frame`` **không** có ``try/except``. Một lỗi
   ở tầng áp dụng kết quả (ngoài phần ``processor`` đã được bọc) thoát khỏi
   vòng lặp → thread chết; ``threading.excepthook`` in traceback ra stderr còn
   logger của dự án **không có dòng nào**.
2. ``_ensure_worker`` chỉ tạo thread khi ``self._worker is None``; không chỗ
   nào gán lại ``None``, nên sau khi thread chết mọi ``observe()`` thấy
   ``_worker != None`` và không bao giờ hồi sinh.
3. ``_coerce_embedding`` bắt ``(TypeError, ValueError)`` nhưng
   ``np.asarray([10**400]*8, dtype=np.float32)`` ném ``OverflowError`` — một
   ``ArithmeticError``, **không** phải ``ValueError`` — nên embedding hỏng
   giết cả luồng thay vì chỉ là "không dùng được".

Test trong tệp này khoá cả ba. Chạy trên PC, không cần camera/mô hình: kho
khuôn mặt là bản thật trong ``tmp_path`` (hoặc bản bọc tiêm lỗi), processor
là hàm thường, đồng hồ tiêm.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.faces import FaceStore  # noqa: E402
from posture_monitor.people_service import (  # noqa: E402
    IDENTITY_MATCH,
    PeopleService,
    _coerce_embedding,
)

#: Embedding đơn vị 8 chiều; đủ nhỏ để test nhanh, đủ lớn để chuẩn hoá có nghĩa.
VECTOR = np.ones(8, dtype=np.float32) / np.sqrt(8.0)

#: Embedding "không dùng được" đúng như đã đo: chuyển sang ``float32`` ném
#: ``OverflowError``. ``10**400`` không biểu diễn được bằng ``float``.
OVERFLOW_VECTOR = [10 ** 400] * 8

class FakeClock:
    """Đồng hồ tiêm: thời gian chỉ chạy khi test tự đẩy."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)

class RecordingLogger:
    """Đếm bản ghi theo mức; ``info`` im lặng để không nhiễu đếm cảnh báo."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, fmt: object, *args: object) -> None:
        self.warnings.append(fmt % args if args else str(fmt))

    def info(self, *_a: object, **_k: object) -> None:
        pass

    def error(self, *_a: object, **_k: object) -> None:
        pass

    def debug(self, *_a: object, **_k: object) -> None:
        pass

    def exception(self, *_a: object, **_k: object) -> None:
        pass

class BrokenStore:
    """Kho bọc quanh :class:`FaceStore`; ``pairs()`` ném lỗi tầng dữ liệu.

    ``error_message`` đổi được giữa test để kiểm tra chống ngập log: lỗi
    *cùng* thông điệp lặp 30 khung chỉ được một cảnh báo.
    """

    def __init__(self, inner: FaceStore, error_message: str = "kho hỏng") -> None:
        self._inner = inner
        self.data_dir = inner.data_dir
        self.error_message = error_message
        self.pairs_calls = 0

    def pairs(self):
        self.pairs_calls += 1
        raise RuntimeError(self.error_message)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

class ScriptedProcessor:
    """Processor theo kịch bản: khung ``"bad"`` trả embedding tràn, còn lại tốt."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, frame: object) -> object:
        self.calls += 1
        if frame == "bad":
            return OVERFLOW_VECTOR
        return np.array(VECTOR)

def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.005) -> bool:
    """Chờ có điều kiện; trả ``False`` khi hết hạn (test tự khẳng định)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()

def _service(
    tmp_path: Path,
    *,
    store: object | None = None,
    logger: object | None = None,
    clock: FakeClock | None = None,
) -> tuple[PeopleService, FakeClock, RecordingLogger]:
    fake_clock = clock or FakeClock()
    real_store = FaceStore(tmp_path, clock=fake_clock)
    real_store.add("An", VECTOR, enrolled_at=1.0)
    service = PeopleService(
        store if store is not None else real_store,
        None,
        clock=fake_clock,
        threshold=0.5,
        logger=logger,
    )
    return service, fake_clock, logger

# ---------------------------------------------------------------------------
# T1 — khung làm processor trả embedding tràn KHÔNG giết worker
# ---------------------------------------------------------------------------
def test_worker_con_song_va_khung_tot_ke_tiep_van_duoc_xu_ly(
    tmp_path: Path,
) -> None:
    """Embedding tràn chỉ là "không dùng được", không phải lỗi giết luồng.

    Đây là đường đã đo: ``_coerce_embedding`` trả ``None`` thay vì để
    ``OverflowError`` thoát ra, nên ``_worker_loop`` không thấy gì bất thường
    và vẫn xử lý khung kế tiếp.
    """
    logger = RecordingLogger()
    service, clock, _ = _service(tmp_path, logger=logger)
    processor = ScriptedProcessor()
    service.set_processor(processor)
    try:
        service.observe("bad", now=clock())
        assert _wait_until(lambda: processor.calls == 1)

        service.observe("good", now=clock())
        assert _wait_until(lambda: processor.calls == 2)
        assert _wait_until(
            lambda: service.signals()["identity"]["state"] == IDENTITY_MATCH
        )

        # Luồng vẫn sống sau khi đã xử lý khung tràn.
        assert service._worker is not None
        assert service._worker.is_alive() is True
        # Khung tốt THẬT SỰ được xử lý (đổi tín hiệu), không chỉ "không ném".
        assert service.signals()["identity"]["state"] == IDENTITY_MATCH
        assert service.signals()["identity"]["name"] == "An"
    finally:
        service.close()

# ---------------------------------------------------------------------------
# T2 — thread chết vì lý do không bắt được thì ``observe`` phải hồi sinh
# ---------------------------------------------------------------------------
def test_ensure_worker_hoi_sinh_khi_thread_cu_da_chet(tmp_path: Path) -> None:
    """``self._worker`` trỏ tới một ``Thread`` đã kết thúc, không phải ``None``.

    Trước khi sửa, ``_ensure_worker`` thấy ``self._worker is not None`` nên
    trả về ngay: không bao giờ có luồng mới. Test dựng đúng tình trạng đó rồi
    đòi luồng mới còn sống, và một khung mới thật sự được xử lý.
    """
    logger = RecordingLogger()
    service, clock, _ = _service(tmp_path, logger=logger)
    processor = ScriptedProcessor()
    service.set_processor(processor)
    try:
        dead = threading.Thread(target=lambda: None, name="dead-worker")
        dead.start()
        dead.join(timeout=2.0)
        assert dead.is_alive() is False
        service._worker = dead

        service.observe("good", now=clock())

        assert _wait_until(
            lambda: service._worker is not None and service._worker is not dead
        ), "Không có luồng mới sau khi luồng cũ đã chết."
        assert service._worker.is_alive() is True
        assert _wait_until(lambda: processor.calls == 1)
        # Hồi sinh đúng một lần cảnh báo, đúng như yêu cầu vận hành.
        assert len(logger.warnings) == 1
        assert "khởi động lại luồng mới" in logger.warnings[0]
    finally:
        service.close()

# ---------------------------------------------------------------------------
# T3 — lỗi tầng áp dụng lặp lại không làm ngập log
# ---------------------------------------------------------------------------
def test_loi_lap_lai_chi_ghi_mot_canh_bao_va_loi_doi_thi_them_mot(
    tmp_path: Path,
) -> None:
    """30 khung cùng một lỗi kho → **đúng 1** WARNING; đổi thông điệp → thêm 1.

    Không có chống ngập thì lỗi kho hỏng ghi 30 dòng cho 30 khung (trên Pi là
    hàng nghìn dòng mỗi giờ, xem bài học cooldown).
    """
    logger = RecordingLogger()
    real_store = FaceStore(tmp_path, clock=FakeClock())
    real_store.add("An", VECTOR, enrolled_at=1.0)
    store = BrokenStore(real_store, error_message="kho hỏng A")
    clock = FakeClock()
    service, _, _ = _service(tmp_path, store=store, logger=logger, clock=clock)
    processor = ScriptedProcessor()
    service.set_processor(processor)
    try:
        for index in range(30):
            service.observe("good", now=clock())
            # Chờ tới khi lỗi của khung này thật sự được ném (``pairs()``
            # được gọi) để không khung nào bị khung sau ghi đè.
            assert _wait_until(lambda i=index: store.pairs_calls >= i + 1)

        assert _wait_until(lambda: len(logger.warnings) >= 1)
        time.sleep(0.05)  # chỗ trống cho log trùng lặp nếu có
        assert service._worker is not None and service._worker.is_alive()
        assert len(logger.warnings) == 1, logger.warnings

        store.error_message = "kho hỏng B"
        with_error = store.pairs_calls
        service.observe("good", now=clock())
        assert _wait_until(lambda: store.pairs_calls > with_error)
        assert _wait_until(lambda: len(logger.warnings) >= 2)
        time.sleep(0.05)
        assert len(logger.warnings) == 2, logger.warnings
    finally:
        service.close()

# ---------------------------------------------------------------------------
# T4 — lỗi tầng áp dụng phải tới logger của service, không im lặng
# ---------------------------------------------------------------------------
def test_loi_tang_ap_dung_den_logger_va_worker_van_song(
    tmp_path: Path,
) -> None:
    """Lỗi kho không được im lặng (chỉ ``threading.excepthook``) và không giết luồng.

    Trước khi sửa: ``_worker_loop`` không bọc ``process_frame``, nên
    ``RuntimeError`` của ``store.pairs()`` thoát ra, thread chết, và
    ``logger.warnings`` rỗng — đúng "chết im lặng". Test khẳng định **có**
    bản ghi, không chỉ "không ném".
    """
    logger = RecordingLogger()
    real_store = FaceStore(tmp_path, clock=FakeClock())
    real_store.add("An", VECTOR, enrolled_at=1.0)
    store = BrokenStore(real_store, error_message="kho hỏng")
    clock = FakeClock()
    service, _, _ = _service(tmp_path, store=store, logger=logger, clock=clock)
    processor = ScriptedProcessor()
    service.set_processor(processor)
    try:
        service.observe("good", now=clock())

        assert _wait_until(lambda: len(logger.warnings) > 0), (
            "Lỗi tầng áp dụng không tới logger của service: worker chết im lặng."
        )
        assert any("Không áp dụng được" in line for line in logger.warnings)
        # Luồng vẫn sống: lỗi một khung không được tắt nhận diện.
        assert service._worker is not None
        assert service._worker.is_alive() is True

        # Và khung kế tiếp vẫn được xử lý (không phải chỉ sống mà không làm gì).
        before = processor.calls
        service.observe("good", now=clock())
        assert _wait_until(lambda: processor.calls > before)
        assert service._worker.is_alive() is True
    finally:
        service.close()

# ---------------------------------------------------------------------------
# T5 — ``_coerce_embedding`` coi embedding tràn là ``None``
# ---------------------------------------------------------------------------
def test_coerce_embedding_tra_none_cho_so_nguyen_tra_tran() -> None:
    """``OverflowError`` là ``ArithmeticError``, không phải ``ValueError``.

    Không bắt riêng lớp này thì ``_coerce_embedding`` ném, ``_apply_observation``
    ném, và toàn bộ ``_worker_loop`` chết.
    """
    assert _coerce_embedding(OVERFLOW_VECTOR) is None
    # Đối chứng: embedding hợp lệ vẫn được chuẩn hoá bình thường.
    valid = _coerce_embedding(VECTOR)
    assert valid is not None
    assert pytest.approx(1.0, abs=1e-6) == float(np.linalg.norm(valid))
