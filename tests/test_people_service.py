"""Unit test cho ``people_service.py``.

Chạy trên PC, **không cần camera, không cần mô hình thật**:

- :class:`~posture_monitor.faces.FaceStore` là bản thật (chỉ ghi JSON, rất
  nhẹ) trong ``tmp_path``; ``recognizer`` là bản giả tiêm được nên không có
  OpenCV, không có ``yunet.onnx``/``sface.onnx``.
- Đồng hồ là đồng hồ giả: không test nào ``sleep`` thật, trừ test đo
  ``observe()`` không chặn và ở đó chỉ ``sleep`` bên trong ``processor`` giả
  để mô phỏng 86,1 ms/lượt của đường ống thật.

Các nhóm test tương ứng bảng tiêu chí của đề bài: danh sách người, vòng đời
đăng ký, chọn/xoá người, ba kết quả danh tính, tuổi tín hiệu và quyền riêng
tư (không có tệp ảnh nào được ghi).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.faces import STORE_FILENAME, FaceStore  # noqa: E402
from posture_monitor.people_service import (  # noqa: E402
    DEFAULT_STEPS,
    IDENTITY_MATCH,
    IDENTITY_MISMATCH,
    IDENTITY_UNKNOWN,
    PHONE_AGE_LIMIT_S,
    PHONE_STATE_NONE,
    PHONE_STATE_USE,
    STATE_CANCELLED,
    STATE_DONE,
    STATE_FAILED,
    STATE_NO_DATA,
    STATE_RUNNING,
    PeopleService,
    PeopleServiceError,
)

#: Vector đơn vị 128 chiều dùng làm embedding; cố định để kết quả tất định.
BASE_VECTOR = np.ones(128, dtype=np.float32) / np.sqrt(128.0)


class FakeClock:
    """Đồng hồ tiêm được: thời gian chỉ chạy khi test tự đẩy."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeRecognizer:
    """Bản giả tối thiểu: mỗi khung trả một embedding cố định hoặc ``None``."""

    def __init__(self, vector: np.ndarray | None = BASE_VECTOR) -> None:
        self.vector = vector
        self.calls = 0

    def embed_largest(self, _frame: object) -> np.ndarray | None:
        self.calls += 1
        return None if self.vector is None else np.array(self.vector)


def _service(
    tmp_path: Path,
    *,
    recognizer: object | None = None,
    clock: FakeClock | None = None,
    **kwargs: object,
) -> tuple[PeopleService, FaceStore, FakeClock]:
    """Dựng service với kho thật trong ``tmp_path`` và đồng hồ giả."""
    fake_clock = clock or FakeClock()
    store = FaceStore(tmp_path, clock=fake_clock)
    service = PeopleService(
        store,
        recognizer if recognizer is not None else FakeRecognizer(),
        clock=fake_clock,
        **kwargs,
    )
    return service, store, fake_clock


# ---------------------------------------------------------------------------
# 1. list_people
# ---------------------------------------------------------------------------
def test_list_people_tra_dung_ba_truong_va_khong_co_embedding(
    tmp_path: Path,
) -> None:
    service, store, _ = _service(tmp_path)
    store.add("An", BASE_VECTOR, enrolled_at=1234.5)

    people = service.list_people()

    assert people == [{"id": "An", "name": "An", "created_ts": 1234.5}]
    assert set(people[0]) == {"id", "name", "created_ts"}
    # Khoá cấm: vector sinh trắc học không được rời khỏi tầng lưu trữ.
    assert "embedding" not in people[0]
    assert "vector" not in people[0]


def test_list_people_id_chinh_la_ten(tmp_path: Path) -> None:
    """Kho ``faces.py`` khoá theo tên, nên ``id`` phải là tên để khớp."""
    service, store, _ = _service(tmp_path)
    store.add("Bình", BASE_VECTOR, enrolled_at=10.0)

    assert service.list_people()[0]["id"] == "Bình"
    assert service.delete_person("Bình") is True
    assert service.list_people() == []


# ---------------------------------------------------------------------------
# 2. start_enroll / enroll_status
# ---------------------------------------------------------------------------
def test_start_enroll_tra_nam_buoc_nguyen_van(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    started = service.start_enroll("An")

    assert started["steps"] == [
        "Nhìn thẳng",
        "Quay sang phải",
        "Quay sang trái",
        "Ngẩng lên",
        "Cúi xuống",
    ]
    assert started["steps"] == list(DEFAULT_STEPS)
    assert started["enroll_id"]

    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_RUNNING
    assert status["step_index"] == 0
    assert status["step_name"] == "Nhìn thẳng"
    assert status["samples"] == 0
    assert status["samples_needed"] == 3
    assert status["error"] is None


def test_start_enroll_ten_rong_bi_tu_choi(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    for bad in ("", "   ", None):
        with pytest.raises(PeopleServiceError):
            service.start_enroll(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. đăng ký thành công
# ---------------------------------------------------------------------------
def test_enroll_du_mau_thi_ghi_va_done(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path)
    started = service.start_enroll("An")

    frames = [object(), object(), object()]
    times = [100.0, 101.5, 103.0]
    for frame, now in zip(frames, times):
        clock.now = now
        service.process_frame(frame, now=now)

    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_DONE
    assert status["samples"] == 3
    assert status["error"] is None
    assert store.names() == ["An"]


def test_enroll_cung_mot_buoc_khong_thu_hai_lan(tmp_path: Path) -> None:
    """Mỗi bước chỉ lấy một mẫu: 3 khung trong cùng bước không đủ 3 mẫu."""
    service, store, clock = _service(tmp_path)
    started = service.start_enroll("An")

    for _ in range(3):
        clock.now = 100.0
        service.process_frame(object(), now=100.0)

    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_RUNNING
    assert status["samples"] == 1
    assert store.names() == []


def test_enroll_lai_ten_da_co_thi_cap_nhat(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path)
    store.add("An", -BASE_VECTOR, enrolled_at=1.0)

    service.start_enroll("An")
    for now in (100.0, 101.5, 103.0):
        clock.now = now
        service.process_frame(object(), now=now)

    people = service.list_people()
    assert len(people) == 1
    assert people[0]["name"] == "An"
    # Embedding đã được cập nhật sang mẫu mới (không tạo bản ghi thứ hai).
    person = store.get("An")
    assert person is not None
    assert float(np.dot(person.embedding, BASE_VECTOR)) > 0.99


# ---------------------------------------------------------------------------
# 4. đăng ký thất bại không ghi gì
# ---------------------------------------------------------------------------
def test_enroll_that_bai_mot_phan_mau_khong_ghi(tmp_path: Path) -> None:
    """Có mẫu nhưng chưa đủ: thất bại và **không** ghi danh tính nửa vời."""
    class FlakyRecognizer:
        """Hai khung đầu có mặt, các khung sau không thấy khuôn mặt."""

        def __init__(self) -> None:
            self.calls = 0

        def embed_largest(self, _frame: object) -> np.ndarray | None:
            self.calls += 1
            return np.array(BASE_VECTOR) if self.calls <= 2 else None

    service, store, clock = _service(tmp_path, recognizer=FlakyRecognizer())
    store.add("Cũ", BASE_VECTOR, enrolled_at=5.0)
    started = service.start_enroll("Mới")

    for now in (100.0, 101.5, 103.0, 104.5, 108.0):
        clock.now = now
        service.process_frame(object(), now=now)

    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_FAILED
    assert status["samples"] == 0
    assert status["error"]
    # Không ghi danh tính nửa vời (spec §3.4): 2/3 mẫu vẫn là không đủ.
    assert store.names() == ["Cũ"]


def test_enroll_thieu_mau_thi_failed_va_khong_ghi(tmp_path: Path) -> None:
    service, store, clock = _service(
        tmp_path, recognizer=FakeRecognizer(None)
    )
    store.add("Cũ", BASE_VECTOR, enrolled_at=5.0)
    started = service.start_enroll("Mới")

    for now in (100.0, 101.5, 103.0, 108.0):
        clock.now = now
        service.process_frame(object(), now=now)

    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_FAILED
    assert status["error"]
    # Không ghi danh tính nửa vời (spec §3.4).
    assert store.names() == ["Cũ"]


def test_enroll_het_gio_thi_failed_va_khong_ghi(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path)
    started = service.start_enroll("An")

    clock.now = 200.0  # quá 5 bước × 1,5 s mà không có khung nào
    service.process_frame(object(), now=200.0)

    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_FAILED
    assert store.names() == []


# ---------------------------------------------------------------------------
# 5. huỷ đăng ký
# ---------------------------------------------------------------------------
def test_cancel_enroll_khong_ghi_gi(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, samples_needed=2)
    started = service.start_enroll("An")
    clock.now = 100.0
    service.process_frame(object(), now=100.0)

    assert service.cancel_enroll(started["enroll_id"]) is True
    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_CANCELLED
    assert store.names() == []
    # Huỷ lần hai không còn gì để huỷ.
    assert service.cancel_enroll(started["enroll_id"]) is False


def test_enroll_status_id_la_bao_loi(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    with pytest.raises(PeopleServiceError):
        service.enroll_status("khong-co-phien-nay")


def test_phien_moi_huy_phien_dang_chay(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    first = service.start_enroll("An")
    second = service.start_enroll("Bình")

    assert service.enroll_status(first["enroll_id"])["state"] == STATE_CANCELLED
    assert service.enroll_status(second["enroll_id"])["state"] == STATE_RUNNING


# ---------------------------------------------------------------------------
# 6. tham số cấu hình
# ---------------------------------------------------------------------------
def test_steps_step_s_samples_needed_doi_duoc(tmp_path: Path) -> None:
    service, store, clock = _service(
        tmp_path,
        steps=["A", "B"],
        step_s=2.0,
        samples_needed=2,
    )
    started = service.start_enroll("An")
    assert started["steps"] == ["A", "B"]

    clock.now = 100.0
    service.process_frame(object(), now=100.0)
    clock.now = 102.0
    service.process_frame(object(), now=102.0)

    status = service.enroll_status(started["enroll_id"])
    assert status["state"] == STATE_DONE
    assert status["samples_needed"] == 2
    assert store.names() == ["An"]


def test_tham_so_cau_hinh_sai_bi_tu_choi(tmp_path: Path) -> None:
    _, store, clock = _service(tmp_path)

    with pytest.raises(ValueError):
        PeopleService(store, FakeRecognizer(), clock=clock, step_s=0)
    with pytest.raises(ValueError):
        PeopleService(store, FakeRecognizer(), clock=clock, samples_needed=0)
    with pytest.raises(ValueError):
        PeopleService(store, FakeRecognizer(), clock=clock, steps=[])


# ---------------------------------------------------------------------------
# 7–8. chọn người
# ---------------------------------------------------------------------------
def test_select_person_none_bo_chon(tmp_path: Path) -> None:
    service, store, _ = _service(tmp_path)
    store.add("An", BASE_VECTOR, enrolled_at=1.0)

    assert service.select_person("An") is True
    assert service.selected_person() == "An"
    assert service.select_person(None) is True
    assert service.selected_person() is None


def test_select_person_khong_ton_tai_tra_false(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    assert service.select_person("khong_co") is False
    assert service.selected_person() is None
    assert service.select_person("") is False


def test_chon_nguoi_khac_khong_xoa_lua_chon_cu(tmp_path: Path) -> None:
    service, store, _ = _service(tmp_path)
    store.add("An", BASE_VECTOR, enrolled_at=1.0)
    store.add("Bình", -BASE_VECTOR, enrolled_at=2.0)

    service.select_person("An")
    service.start_enroll("Bình")
    assert service.selected_person() == "An"


def test_xoa_nguoi_dang_chon_thi_tu_bo_chon(tmp_path: Path) -> None:
    service, store, _ = _service(tmp_path)
    store.add("An", BASE_VECTOR, enrolled_at=1.0)
    service.select_person("An")

    assert service.delete_person("An") is True
    assert service.selected_person() is None
    assert store.names() == []


# ---------------------------------------------------------------------------
# 9. tuổi tín hiệu
# ---------------------------------------------------------------------------
def test_signals_du_lieu_moi_thi_fresh(tmp_path: Path) -> None:
    service, _, clock = _service(tmp_path, threshold=0.5)
    service.update_signals(presence="co_mat", phone="khong_dung", now=clock.now)

    signals = service.signals()

    assert signals["presence"]["state"] == "co_mat"
    assert signals["presence"]["fresh"] is True
    assert signals["presence"]["age_s"] == pytest.approx(0.0)
    assert signals["phone"]["fresh"] is True
    assert signals["presence"]["age_limit_s"] > 0


def test_signals_cu_thi_khong_fresh_va_khong_doi_ket_luan(tmp_path: Path) -> None:
    service, _, clock = _service(tmp_path, threshold=0.5)
    service.update_signals(presence="co_mat", phone="dung", now=clock.now)

    clock.advance(100.0)
    signals = service.signals()

    # Hết dữ liệu, KHÔNG được biến thành "đang có mặt"/"đang dùng điện thoại".
    assert signals["presence"]["fresh"] is False
    assert signals["phone"]["fresh"] is False
    assert signals["presence"]["age_s"] == pytest.approx(100.0)
    assert signals["presence"]["state"] == "co_mat"
    assert signals["phone"]["state"] == "dung"


def test_note_phone_ghi_tin_hieu_dien_thoai_ma_khong_dung_update_signals(
    tmp_path: Path,
) -> None:
    """``note_phone`` phải tới được đúng ô mà ``signals()`` đọc.

    Lỗi gốc: vòng lặp gọi ``update_signals(presence=..., now=...)`` thiếu
    ``phone=``, nên dòng "Điện thoại" trên dashboard đứng ở "chưa có dữ liệu"
    vĩnh viễn trong khi loa vẫn báo dùng điện thoại. Test này khoá phương thức
    thay thế **mà không đổi chữ ký** ``update_signals``.
    """
    service, _, clock = _service(tmp_path, threshold=0.5)

    service.note_phone(PHONE_STATE_USE, now=clock.now)
    signals = service.signals()

    assert signals["phone"]["state"] == PHONE_STATE_USE
    assert signals["phone"]["fresh"] is True
    assert signals["phone"]["age_s"] == pytest.approx(0.0)
    # Presence không được bị đụng tới: đây là tín hiệu riêng.
    assert signals["presence"]["state"] == STATE_NO_DATA
    assert signals["presence"]["age_s"] is None


def test_note_phone_mac_dinh_lay_dong_ho_cua_dich_vu(tmp_path: Path) -> None:
    """Không truyền ``now`` thì tuổi tính theo ``clock`` tiêm vào, không phải
    ``time.monotonic`` thật — trộn hai gốc thời gian làm tuổi sai hàng nghìn
    giây."""
    service, _, clock = _service(tmp_path, threshold=0.5)
    clock.advance(50.0)

    service.note_phone(PHONE_STATE_NONE)

    signals = service.signals()
    assert signals["phone"]["state"] == PHONE_STATE_NONE
    assert signals["phone"]["age_s"] == pytest.approx(0.0)


def test_note_phone_het_han_thi_khong_doi_ket_luan_cu(tmp_path: Path) -> None:
    service, _, clock = _service(tmp_path, threshold=0.5)
    service.note_phone(PHONE_STATE_USE, now=clock.now)

    clock.advance(PHONE_AGE_LIMIT_S + 1.0)
    signals = service.signals()

    assert signals["phone"]["fresh"] is False
    assert signals["phone"]["state"] == PHONE_STATE_USE


def test_signals_chua_co_du_lieu_thi_age_none(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path, threshold=0.5)

    signals = service.signals()

    assert signals["presence"]["age_s"] is None
    assert signals["presence"]["fresh"] is False
    assert signals["identity"]["state"] == IDENTITY_UNKNOWN
    assert signals["identity"]["name"] is None
    assert set(signals) == {"presence", "phone", "identity"}
    for key in ("presence", "phone", "identity"):
        assert "embedding" not in signals[key]
        assert "vector" not in signals[key]


def test_signals_identity_co_tuoi(tmp_path: Path) -> None:
    service, _, clock = _service(tmp_path)
    service.process_frame(object(), now=clock.now)

    fresh = service.signals()["identity"]
    assert fresh["fresh"] is True
    assert fresh["age_s"] == pytest.approx(0.0)

    clock.advance(100.0)
    stale = service.signals()["identity"]
    assert stale["fresh"] is False
    assert stale["state"] == IDENTITY_UNKNOWN


# ---------------------------------------------------------------------------
# 10. ba kết quả danh tính
# ---------------------------------------------------------------------------
def test_threshold_none_thi_unknown(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, recognizer=FakeRecognizer(BASE_VECTOR))
    store.add("An", BASE_VECTOR, enrolled_at=1.0)

    service.process_frame(object(), now=clock.now)

    identity = service.signals()["identity"]
    assert identity["state"] == IDENTITY_UNKNOWN
    assert identity["name"] is None
    assert identity["reason"]


def test_gallery_rong_thi_unknown(tmp_path: Path) -> None:
    service, _, clock = _service(tmp_path, threshold=0.5)

    service.process_frame(object(), now=clock.now)

    identity = service.signals()["identity"]
    assert identity["state"] == IDENTITY_UNKNOWN
    assert identity["name"] is None


def test_khong_thay_khuon_mat_thi_unknown(tmp_path: Path) -> None:
    service, store, clock = _service(
        tmp_path, recognizer=FakeRecognizer(None), threshold=0.5
    )
    store.add("An", BASE_VECTOR, enrolled_at=1.0)

    service.process_frame(object(), now=clock.now)

    assert service.signals()["identity"]["state"] == IDENTITY_UNKNOWN


def test_diem_cao_thi_match_dung_ten(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, threshold=0.5)
    store.add("An", BASE_VECTOR, enrolled_at=1.0)

    service.process_frame(object(), now=clock.now)

    identity = service.signals()["identity"]
    assert identity["state"] == IDENTITY_MATCH
    assert identity["name"] == "An"


def test_diem_thap_thi_mismatch(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, threshold=0.99)
    store.add("An", -BASE_VECTOR, enrolled_at=1.0)

    service.process_frame(object(), now=clock.now)

    identity = service.signals()["identity"]
    assert identity["state"] == IDENTITY_MISMATCH
    assert identity["name"] is None


def test_nguoi_khac_nguoi_dang_chon_thi_mismatch(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, threshold=0.5)
    store.add("An", BASE_VECTOR, enrolled_at=1.0)
    store.add("Bình", -BASE_VECTOR, enrolled_at=2.0)
    service.select_person("Bình")

    service.process_frame(object(), now=clock.now)

    identity = service.signals()["identity"]
    assert identity["state"] == IDENTITY_MISMATCH
    assert identity["name"] is None


def test_dung_nguoi_dang_chon_thi_match(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, threshold=0.5)
    store.add("An", BASE_VECTOR, enrolled_at=1.0)
    store.add("Bình", -BASE_VECTOR, enrolled_at=2.0)
    service.select_person("An")

    service.process_frame(object(), now=clock.now)

    identity = service.signals()["identity"]
    assert identity["state"] == IDENTITY_MATCH
    assert identity["name"] == "An"


def test_processor_loi_khong_lam_sap_service(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, threshold=0.5)
    store.add("An", BASE_VECTOR, enrolled_at=1.0)
    service.set_processor(lambda _frame: 1 / 0)  # noqa: SLF001

    service.process_frame(object(), now=clock.now)

    identity = service.signals()["identity"]
    assert identity["state"] == IDENTITY_UNKNOWN


# ---------------------------------------------------------------------------
# 11. quyền riêng tư: không có tệp ảnh nào
# ---------------------------------------------------------------------------
def test_khong_tao_tep_anh_nao(tmp_path: Path) -> None:
    service, store, clock = _service(tmp_path, threshold=0.5)
    started = service.start_enroll("An")
    for now in (100.0, 101.5, 103.0):
        clock.now = now
        service.process_frame(object(), now=now)
    assert service.enroll_status(started["enroll_id"])["state"] == STATE_DONE
    service.signals()

    created = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert created == {STORE_FILENAME}
    assert not any(
        path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        for path in tmp_path.rglob("*")
    )


# ---------------------------------------------------------------------------
# 12. observe() không chặn
# ---------------------------------------------------------------------------
def test_observe_khong_chan_khi_processor_cham(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path, threshold=0.5)

    def slow_processor(_frame: object) -> np.ndarray:
        time.sleep(0.2)
        return BASE_VECTOR

    service.set_processor(slow_processor)
    try:
        start = time.monotonic()
        for _ in range(5):
            service.observe(object(), now=100.0)
        elapsed = time.monotonic() - start
    finally:
        service.close()

    assert elapsed < 0.05, (
        f"observe() chặn {elapsed * 1000:.1f} ms cho 5 khung; đường ống "
        "khuôn mặt (86,1 ms/lượt) không được chạy trên vòng lặp chính."
    )
