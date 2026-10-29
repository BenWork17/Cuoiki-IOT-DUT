"""Unit test cho ``face_worker.py`` (nhận diện khuôn mặt chạy nền).

Chạy trên PC, **không cần** ``yunet.onnx``/``sface.onnx``, không cần camera:
bộ nhận diện là fake, hàm thu nhỏ khung là thuần ``numpy``.

Các test dưới đây khoá đúng bốn quyết định của spec V3 mà một bản cài đặt
"sạch sẽ" rất dễ làm sai:

1. Nhận diện **không chặn** vòng lặp chính (fake recognizer ngủ 0,3 s mà
   ``submit`` vẫn trả về trong vài chục ms).
2. Nhịp ``interval_s`` giữ cho nhận diện **không chạy mỗi khung**.
3. Tín hiệu cũ hơn ``interval_s * 3`` **không** được trả như kết luận mới —
   đây là yêu cầu chống hiểu nhầm của §5.16.
4. Hộp khuôn mặt trả về nằm trong **hệ pixel của khung gốc**, không phải hệ
   ``detect_width`` (§5.13(2)).

Cộng thêm hai ràng buộc nghiệp vụ: gallery rỗng **không bao giờ** thành
``MISMATCH``, và ``match_threshold: null`` thì tính năng **không chạy** chứ
không chạy với ngưỡng bịa (§5.13).
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

from posture_monitor.config import FaceConfig  # noqa: E402
from posture_monitor.face_worker import (  # noqa: E402
    MATCH,
    MISMATCH,
    UNKNOWN,
    FaceWorker,
    map_box_to_frame,
)
from posture_monitor.faces import DetectedFace, FaceStore  # noqa: E402


# ---------------------------------------------------------------------------
# Tiện ích giả lập
# ---------------------------------------------------------------------------
class FakeClock:
    """Đồng hồ điều khiển được, để test nhịp và tuổi tín hiệu không chờ thật."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


def _fake_prepare(frame, detect_width: int, clahe_enabled: bool):
    """Thu nhỏ khung như ``cv2.resize`` (nearest-neighbour, đủ cho test).

    Giữ đúng hợp đồng: chiều rộng kết quả ≤ ``detect_width``, tỉ lệ giữ
    nguyên. Không phóng to khung đã nhỏ hơn ngưỡng.
    """
    height, width = int(frame.shape[0]), int(frame.shape[1])
    scale = min(1.0, float(detect_width) / float(width))
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    ys = (np.arange(new_h) * (height / new_h)).astype(int).clip(0, height - 1)
    xs = (np.arange(new_w) * (width / new_w)).astype(int).clip(0, width - 1)
    return frame[ys][:, xs]


def _box(x: float, y: float, w: float, h: float) -> DetectedFace:
    """Khuôn mặt giả với hộp trong hệ của ảnh đã thu nhỏ."""
    return DetectedFace(
        x=x,
        y=y,
        width=w,
        height=h,
        score=0.95,
        box=np.array([x, y, w, h, 0, 0, 0, 0], dtype=np.float32),
    )


class FakeRecognizer:
    """Bộ nhận diện giả: đếm lượt, trả hộp/vector cố định, có thể ngủ."""

    def __init__(
        self,
        faces: list[DetectedFace] | None = None,
        vector: np.ndarray | None = None,
        delay_s: float = 0.0,
        detect_error: Exception | None = None,
    ) -> None:
        self.faces = faces
        self.vector = (
            vector
            if vector is not None
            else np.ones(8, dtype=np.float32) / np.sqrt(8.0)
        )
        self.delay_s = float(delay_s)
        self.detect_error = detect_error
        self.detect_calls = 0
        self.embedding_calls = 0
        self.shapes: list[tuple[int, int]] = []
        self._lock = threading.Lock()

    def detect(self, image):
        with self._lock:
            self.detect_calls += 1
        self.shapes.append((int(image.shape[0]), int(image.shape[1])))
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.detect_error is not None:
            raise self.detect_error
        # ``None`` = "không thấy mặt nào"; danh sách giả lập nhiều mặt.
        return list(self.faces or [])

    def embedding(self, image, face):
        with self._lock:
            self.embedding_calls += 1
        return np.asarray(self.vector, dtype=np.float32)


def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.01):
    """Chờ có điều kiện (dùng thời gian thật — luồng nền chạy thật)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(
        f"Không đạt điều kiện trong {timeout} s — worker có thể đang treo."
    )


def _store_with(tmp_path: Path, *, people: bool = True) -> FaceStore:
    """Kho khuôn mặt thật, trong ``tmp_path`` (không đụng dữ liệu ứng dụng)."""
    store = FaceStore(tmp_path)
    if people:
        store.add("An", np.ones(8, dtype=np.float32), enrolled_at=1.0)
    return store


def _config(**overrides) -> FaceConfig:
    """``FaceConfig`` đã có ngưỡng hợp lệ, cho các test không nhắm vào ngưỡng."""
    base = {
        "enabled": True,
        "interval_s": 2.0,
        "match_threshold": 0.5,
        "detect_width": 320,
    }
    base.update(overrides)
    return FaceConfig(**base)


def _frame(width: int = 704, height: int = 576) -> np.ndarray:
    """Khung BGR giả (giá trị không quan trọng — không ai đọc nội dung)."""
    return np.zeros((height, width, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# 1. Nhận diện không chặn vòng lặp chính
# ---------------------------------------------------------------------------
def test_submit_tra_ve_ngay_ca_khi_nhan_dien_dang_chay(tmp_path: Path) -> None:
    """``submit`` không được chờ nhận diện: 86,1 ms/lượt là quá đắt mỗi khung.

    Fake recognizer ngủ 0,3 s; nếu ``submit`` chờ nó thì lời gọi mất ≥ 300 ms
    và test đỏ đúng vì lý do hiệu năng đã nêu trong brief.
    """
    clock = FakeClock()
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)], delay_s=0.3)
    worker = FaceWorker(
        _config(),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        started = time.monotonic()
        accepted = worker.submit(_frame(), now=clock.now)
        elapsed = time.monotonic() - started
        assert accepted is True
        assert elapsed < 0.05, (
            f"submit() mất {elapsed * 1000:.0f} ms — đang chờ nhận diện "
            "(phải trả về ngay, nhận diện chạy ở luồng nền)."
        )
        # Và nhận diện thật sự đã chạy nền (không phải bị bỏ luôn).
        _wait_for(lambda: recognizer.detect_calls == 1)
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# 2. Nhịp interval_s
# ---------------------------------------------------------------------------
def test_interval_s_bo_khung_qua_day(tmp_path: Path) -> None:
    """10 khung trong 0,9 s với ``interval_s: 2.0`` chỉ được nhận 1 lượt.

    Đồng hồ giả nên test không phải chờ 2 giây thật; nếu bỏ kiểm tra nhịp thì
    cả 10 khung được nhận và test đỏ.
    """
    clock = FakeClock()
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)])
    worker = FaceWorker(
        _config(interval_s=2.0),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        accepted = 0
        for _ in range(10):
            if worker.submit(_frame(), now=clock.now):
                accepted += 1
            clock.advance(0.1)
        assert accepted == 1, (
            f"Nhận {accepted} lượt trong 0,9 s với interval_s=2.0; phải chỉ 1 "
            "lượt (không chạy nhận diện mỗi khung)."
        )
        # Qua nhịp thì khung kế tiếp được nhận.
        clock.advance(2.0)
        assert worker.submit(_frame(), now=clock.now) is True
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# 3. Tuổi tín hiệu
# ---------------------------------------------------------------------------
def test_ket_qua_cu_thi_latest_bao_chua_co_du_lieu_moi(
    tmp_path: Path,
) -> None:
    """Quá ``interval_s * 3`` thì ``latest`` **không** được trả tên cũ.

    Đây là yêu cầu chống hiểu nhầm của §5.16: kết luận cũ bị trình bày như
    mới là lỗi UX nguy hiểm (người lạ ngồi vào vẫn thấy tên chính chủ).
    """
    clock = FakeClock(start=100.0)
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)])
    worker = FaceWorker(
        _config(interval_s=2.0, match_threshold=0.1),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        worker.submit(_frame(), now=clock.now)
        first = _wait_for(
            lambda: (lambda r: r if r.ts == 100.0 else None)(worker.latest())
        )
        assert first.outcome == MATCH
        assert first.name == "An"
        assert first.fresh is True

        clock.advance(6.5)  # 6,5 > 2,0 * 3 = 6,0
        stale = worker.latest()
        assert stale.fresh is False, (
            "Kết quả cũ 6,5 s (ngưỡng 6,0 s) vẫn được báo là tươi; UI sẽ "
            "trình bày tên cũ như dữ liệu mới."
        )
        assert stale.outcome == UNKNOWN
        assert stale.name is None, (
            f"Vẫn trả tên cũ {stale.name!r} cho kết quả đã cũ."
        )
        assert "chưa có dữ liệu" in stale.message.lower()
        assert stale.age_s > 6.0
    finally:
        worker.stop()


def test_ket_qua_trong_nguong_van_tuoi(tmp_path: Path) -> None:
    """Trong ``interval_s * 3`` thì kết quả vẫn được dùng (đối chứng)."""
    clock = FakeClock(start=100.0)
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)])
    worker = FaceWorker(
        _config(interval_s=2.0, match_threshold=0.1),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        worker.submit(_frame(), now=clock.now)
        _wait_for(lambda: worker.latest().outcome == MATCH)
        clock.advance(5.9)
        fresh = worker.latest()
        assert fresh.fresh is True
        assert fresh.name == "An"
        assert fresh.age_s == pytest.approx(5.9, abs=0.05)
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# 4. Ánh xạ hộp về hệ khung gốc
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("width", "height"),
    [(704, 576), (1000, 750)],
)
def test_hop_duoc_anh_xa_ve_he_khung_goc(
    tmp_path: Path, width: int, height: int
) -> None:
    """Hộp trả về phải nằm trong khung gốc, không phải hệ ``detect_width``.

    1000x750 cố ý không phải bội số của 320: công thức phải dùng tỉ lệ đo từ
    ảnh đã thu nhỏ, không giả định ``frame_w / detect_width`` chia hết.
    """
    clock = FakeClock()
    frame = _frame(width, height)
    recognizer = FakeRecognizer(faces=[_box(100.0, 50.0, 60.0, 40.0)])
    worker = FaceWorker(
        _config(detect_width=320, match_threshold=0.1),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        worker.submit(frame, now=clock.now)
        reading = _wait_for(
            lambda: (lambda r: r if r.box is not None else None)(worker.latest())
        )
        if width == 704:
            # 704x576 → 320x262: thu nhỏ bằng tỉ lệ, không méo khung.
            assert recognizer.shapes == [(262, 320)], (
                f"Recognizer nhận khung {recognizer.shapes} — phải là khung "
                "đã thu nhỏ về detect_width 320, không phải khung gốc."
            )

        prep_h, prep_w = _fake_prepare(frame, 320, False).shape[:2]
        scale_x = width / prep_w
        scale_y = height / prep_h
        expected = (
            100.0 * scale_x,
            50.0 * scale_y,
            60.0 * scale_x,
            40.0 * scale_y,
        )
        assert reading.box == pytest.approx(expected, rel=1e-6), (
            f"Hộp {reading.box} không phải hộp đã ánh xạ {expected}; nếu "
            "nguyên hệ 320 thì overlay và khoảng cách lệch "
            f"{scale_x:.2f} lần."
        )
        x, y, box_w, box_h = reading.box
        assert 0.0 <= x <= width and 0.0 <= y <= height
        assert 0.0 < box_w <= width and 0.0 < box_h <= height
        assert box_w > 60.0 * 1.5, (
            f"Hộp rộng {box_w:.1f} px trong khung {width} — trông như vẫn ở "
            "hệ 320 (không ánh xạ ngược)."
        )
    finally:
        worker.stop()


def test_map_box_kep_trong_khung() -> None:
    """Ánh xạ không được đẩy hộp ra ngoài khung (sai số làm tròn ``resize``)."""
    box = _box(310.0, 255.0, 30.0, 30.0)
    x, y, w, h = map_box_to_frame(box, 2.2, 2.2, 704.0, 576.0)
    assert x + w <= 704.0 + 1e-6
    assert y + h <= 576.0 + 1e-6
    assert x >= 0.0 and y >= 0.0
    assert w >= 0.0 and h >= 0.0


# ---------------------------------------------------------------------------
# 5. UNKNOWN không bao giờ thành MISMATCH
# ---------------------------------------------------------------------------
def test_gallery_rong_la_unknown_khong_phai_mismatch(tmp_path: Path) -> None:
    """Kho rỗng: không có ai để so, nên kết quả **không** được là MISMATCH.

    MISMATCH nghĩa là "tìm thấy mặt và so với người đã đăng ký đều dưới
    ngưỡng" — đòi hỏi gallery không rỗng. Nhầm chỗ này biến một máy chưa
    đăng ký ai thành máy báo "có người lạ".
    """
    clock = FakeClock()
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)])
    worker = FaceWorker(
        _config(match_threshold=0.1),
        store=_store_with(tmp_path, people=False),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        worker.submit(_frame(), now=clock.now)
        reading = _wait_for(
            lambda: (lambda r: r if r.ts == clock.now else None)(worker.latest())
        )
        assert reading.outcome == UNKNOWN
        assert reading.name is None
        assert "đăng ký" in reading.message.lower()
    finally:
        worker.stop()


def test_khong_thay_mat_la_unknown(tmp_path: Path) -> None:
    """Không phát hiện khuôn mặt → UNKNOWN, không phải MISMATCH."""
    clock = FakeClock()
    recognizer = FakeRecognizer(faces=[])
    worker = FaceWorker(
        _config(),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        worker.submit(_frame(), now=clock.now)
        reading = _wait_for(
            lambda: (lambda r: r if r.ts == clock.now else None)(worker.latest())
        )
        assert reading.outcome == UNKNOWN
        assert reading.name is None
    finally:
        worker.stop()


def test_duoi_nguong_la_mismatch(tmp_path: Path) -> None:
    """Có mặt, gallery không rỗng, mọi điểm dưới ngưỡng → MISMATCH."""
    clock = FakeClock()
    # Vector trực giao với "An" (toàn 1) → cosine 0 < ngưỡng 0.5.
    other = np.zeros(8, dtype=np.float32)
    other[0] = 1.0
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)], vector=other)
    worker = FaceWorker(
        _config(match_threshold=0.5),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        worker.submit(_frame(), now=clock.now)
        reading = _wait_for(
            lambda: (lambda r: r if r.ts == clock.now else None)(worker.latest())
        )
        assert reading.outcome == MISMATCH
        assert reading.name is None
        assert reading.score < 0.5
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# 6. match_threshold: null → không chạy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("enabled", [None, True])
def test_match_threshold_null_thi_tinh_nang_khong_chay(
    tmp_path: Path, enabled: bool | None
) -> None:
    """Chưa đo ngưỡng thì worker **tắt**, báo lý do; không chạy với số bịa.

    ``enabled`` để trống (tự động) hoặc ``True``: trong **cả hai** trường hợp,
    thứ duy nhất có thể chặn là ``match_threshold`` null. Nếu test chỉ dùng
    ``enabled: false`` thì một bản cài đặt chạy với ngưỡng mặc định vẫn "đỏ"
    vì lý do khác — ``detect_calls`` mới là chứng cứ thật.
    """
    clock = FakeClock()
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)])
    worker = FaceWorker(
        FaceConfig(enabled=enabled, match_threshold=None),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        assert worker.enabled is False
        assert worker.submit(_frame(), now=clock.now) is False
        assert recognizer.detect_calls == 0, (
            "Đã chạy nhận diện dù chưa có ngưỡng — spec cấm chạy với ngưỡng bịa."
        )
        reading = worker.latest()
        assert reading.outcome == UNKNOWN
        assert reading.fresh is False
        assert "match_threshold" in worker.disabled_reason
        assert "match_threshold" in reading.message
    finally:
        worker.stop()


def test_config_enabled_true_va_threshold_null_la_hop_le() -> None:
    """Hợp đồng ĐỔI ngày 2026-10-29: ``enabled: true`` + ``match_threshold: null``.

    Trước đây tổ hợp này bị :func:`_parse_face` coi là lỗi cấu hình. Nay nó
    **hợp lệ**: người dùng bật tính năng, còn ngưỡng được **tự suy ra** từ
    chính các mẫu đăng ký (``people_service.derive_threshold``), nên không có
    con số bịa nào được dùng. Trước khi đủ ``enroll_min_samples`` mẫu mọi
    quan sát vẫn là ``UNKNOWN``; :func:`_parse_face` chỉ ghi log một dòng.

    Vì sao đổi: người dùng chốt "tính năng phải chạy được thật" — chặn cứng
    ở config khiến tính năng chưa bao giờ chạy. Không hạ ngưỡng nào: ngưỡng
    vẫn chỉ đến từ dữ liệu đăng ký hoặc từ số người dùng đặt tay.
    """
    from posture_monitor.config import _parse_face

    cfg = _parse_face({"enabled": True, "match_threshold": None})
    assert cfg.enabled is True
    assert cfg.match_threshold is None


def test_cau_hinh_face_mac_dinh_la_tat_va_threshold_null() -> None:
    """Thiếu mục ``face`` → tắt, ngưỡng ``None``, ``store_path`` đúng spec §6."""
    from posture_monitor.config import _parse_face

    cfg = _parse_face(None)
    assert cfg.enabled is False
    assert cfg.match_threshold is None
    assert cfg.interval_s == 2.0
    assert cfg.detect_width == 320
    assert cfg.clahe_enabled is True
    assert cfg.store_path == "data/faces.json"
    assert cfg.enroll_min_samples == 3


def test_cau_hinh_face_khoa_la_sai_kieu_bao_loi() -> None:
    """Chuỗi ở ``match_threshold`` là lỗi cấu hình, không được đổi ngầm."""
    from posture_monitor.config import ConfigError, _parse_face

    with pytest.raises(ConfigError) as excinfo:
        _parse_face({"match_threshold": "0.5"})
    assert "face.match_threshold" in str(excinfo.value)


def test_cau_hinh_face_threshold_ngoai_khoang_bao_loi() -> None:
    """Cosine chỉ nằm trong [-1, 1]; 1,5 là lỗi gõ, không phải ngưỡng."""
    from posture_monitor.config import ConfigError, _parse_face

    with pytest.raises(ConfigError) as excinfo:
        _parse_face({"match_threshold": 1.5})
    assert "face.match_threshold" in str(excinfo.value)


def test_cau_hinh_face_co_threshold_thi_tu_bat() -> None:
    """Đã đo ngưỡng và để ``enabled`` trống → tự bật (như onvif.enabled)."""
    from posture_monitor.config import _parse_face

    cfg = _parse_face({"match_threshold": 0.42})
    assert cfg.enabled is True
    assert cfg.match_threshold == pytest.approx(0.42)


def test_cau_hinh_face_enabled_false_thang_khi_da_co_threshold() -> None:
    """Người dùng chủ động ``false`` thì tôn trọng, dù đã có ngưỡng."""
    from posture_monitor.config import _parse_face

    cfg = _parse_face({"enabled": False, "match_threshold": 0.42})
    assert cfg.enabled is False


def test_repo_config_yaml_co_khoi_face_hop_le() -> None:
    """``config.yaml`` trong repo phải nạp được với khối ``face`` mới."""
    from posture_monitor.config import load_config

    config = load_config(_REPO_ROOT / "config.yaml")
    # Từ 2026-10-29 khối ``face`` bật sẵn với ``match_threshold: null``: ngưỡng
    # được tự suy ra từ dữ liệu đăng ký của người dùng, không có số bịa nào.
    assert config.face.enabled is True
    assert config.face.match_threshold is None
    assert config.face.detect_width == 320


# ---------------------------------------------------------------------------
# 7. stop() không treo
# ---------------------------------------------------------------------------
def test_stop_khong_treo_khi_dang_nhan_dien(tmp_path: Path) -> None:
    """``stop`` có timeout và thật sự dừng; gọi lần hai vẫn an toàn."""
    clock = FakeClock()
    recognizer = FakeRecognizer(faces=[_box(10, 10, 40, 40)], delay_s=0.2)
    worker = FaceWorker(
        _config(),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    worker.submit(_frame(), now=clock.now)
    started = time.monotonic()
    stopped = worker.stop(timeout=5.0)
    elapsed = time.monotonic() - started
    assert stopped is True, "Luồng nền vẫn chạy sau stop()."
    assert elapsed < 5.0
    assert worker.stop(timeout=1.0) is True
    assert worker.submit(_frame(), now=clock.now + 10) is False
    # ``latest`` sau khi dừng vẫn an toàn.
    assert worker.latest().outcome in (UNKNOWN, MATCH, MISMATCH)


# ---------------------------------------------------------------------------
# 8. Không ghi ảnh ra đĩa, không giữ khung
# ---------------------------------------------------------------------------
def test_khong_ghi_anh_ra_dia(tmp_path: Path) -> None:
    """Chạy vài lượt mà thư mục dữ liệu không có tệp ảnh nào (spec §5.13.1)."""
    clock = FakeClock()
    data_dir = tmp_path / "data"
    worker = FaceWorker(
        _config(store_path=str(data_dir / "faces.json")),
        store=_store_with(tmp_path),
        recognizer=FakeRecognizer(faces=[_box(10, 10, 40, 40)]),
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        for _ in range(3):
            worker.submit(_frame(), now=clock.now)
            clock.advance(2.5)
        _wait_for(lambda: worker.latest().outcome == MATCH)
    finally:
        worker.stop()
    leftovers = [
        path
        for path in tmp_path.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".png", ".bmp"}
    ]
    assert leftovers == [], f"Worker ghi ảnh ra đĩa: {leftovers}"
    assert not data_dir.exists() or not any(data_dir.iterdir())


def test_loi_mo_hinh_tat_worker_thay_vi_lap_lai_moi_nhip(
    tmp_path: Path,
) -> None:
    """Thiếu ``yunet.onnx`` → worker tắt, ``latest`` nêu lý do, không crash."""
    from posture_monitor.faces import FaceModelError

    clock = FakeClock()
    recognizer = FakeRecognizer(
        detect_error=FaceModelError("Thiếu tệp mô hình nhận diện khuôn mặt.")
    )
    worker = FaceWorker(
        _config(),
        store=_store_with(tmp_path),
        recognizer=recognizer,
        clock=clock,
        prepare=_fake_prepare,
    )
    try:
        worker.submit(_frame(), now=clock.now)
        # Worker tự tắt khi lỗi mô hình; ``latest`` sau đó trả lý do.
        _wait_for(lambda: worker.enabled is False)
        reading = worker.latest()
        assert reading.outcome == UNKNOWN
        assert "mô hình" in reading.message.lower()
        assert reading.fresh is False
        assert worker.enabled is False
        # Không còn dâng khung mới khi đã hỏng mô hình.
        assert worker.submit(_frame(), now=clock.now + 10) is False
    finally:
        worker.stop()
