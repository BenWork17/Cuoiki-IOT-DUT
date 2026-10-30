"""Unit test cho phiên học bật/tắt bằng tay (``study_session``).

Module thuần, có **đồng hồ tiêm từ ngoài**, nên toàn bộ test ở đây điều khiển
được thời gian mà không cần ``sleep``. Không có camera, không có Flask, không
có model — đúng lý do module được tách ra.

Ba nhóm hành vi được kiểm chặt vì chúng là nguồn lỗi thật của tính năng:

1. **Hết giờ là tự dừng** — ``RUNNING`` → ``FINISHED``, không phải "vẫn chạy
   nhưng báo hết".
2. **Câu thông báo ra đúng một lần** — ``tick`` lặp lại không được nói lại;
   ``snapshot`` không bao giờ được nói.
3. **``FINISHED`` khác ``IDLE``** — giữ số phút đã đặt để dashboard hiện tổng
   kết thay vì nhảy về "Chưa bắt đầu".
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.study_session import (  # noqa: E402
    DEFAULT_MINUTES,
    FINISHED_MESSAGE,
    MAX_MINUTES,
    MIN_MINUTES,
    STATE_FINISHED,
    STATE_IDLE,
    STATE_RUNNING,
    StudySession,
    StudySessionError,
    normalise_minutes,
    payload,
)


class FakeClock:
    """Đồng hồ đơn điệu giả: mọi test tự nhích thời gian."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


def make_session(minutes: int = 60, *, clock: FakeClock | None = None) -> StudySession:
    return StudySession(minutes, clock=clock or FakeClock())


# ---------------------------------------------------------------------------
# normalise_minutes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [MIN_MINUTES, 1, 60, MAX_MINUTES, 60.0])
def test_chap_nhan_so_phut_hop_le(value):
    assert normalise_minutes(value) == int(value)


@pytest.mark.parametrize("value", [0, -1, MAX_MINUTES + 1, 10_000])
def test_tu_choi_so_phut_ngoai_khoang(value):
    with pytest.raises(StudySessionError) as excinfo:
        normalise_minutes(value)
    assert f"{MIN_MINUTES}–{MAX_MINUTES}" in str(excinfo.value)


@pytest.mark.parametrize("value", [True, False, None, "60", [60], {"m": 60}])
def test_tu_choi_kieu_khong_phai_so(value):
    with pytest.raises(StudySessionError):
        normalise_minutes(value)


@pytest.mark.parametrize("value", [60.5, 0.4, 1.0001])
def test_tu_choi_so_le(value):
    with pytest.raises(StudySessionError) as excinfo:
        normalise_minutes(value)
    assert "nguyên" in str(excinfo.value).lower()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_tu_choi_so_khong_huu_han(value):
    with pytest.raises(StudySessionError) as excinfo:
        normalise_minutes(value)
    assert "hữu hạn" in str(excinfo.value)


def test_bool_khong_duoc_coi_la_mot_phut():
    """``True == 1`` trong Python; người dùng gõ ``true`` không có nghĩa là
    "một phút" nên phải bị từ chối thay vì lặng lẽ thành phiên 1 phút."""
    with pytest.raises(StudySessionError):
        normalise_minutes(True)


# ---------------------------------------------------------------------------
# Trạng thái và vòng đời
# ---------------------------------------------------------------------------


def test_mac_dinh_la_idle():
    session = make_session()
    assert session.state == STATE_IDLE
    assert session.is_running is False
    assert session.default_minutes == 60

    snapshot = session.snapshot()
    assert snapshot.state == STATE_IDLE
    assert snapshot.minutes == 0
    assert snapshot.remaining_s == 0.0
    assert snapshot.elapsed_s == 0.0
    assert snapshot.ends_in_text is None
    assert snapshot.finished_message is None


def test_start_dung_thoi_luong_mac_dinh():
    session = make_session(60)
    snapshot = session.start()
    assert snapshot.state == STATE_RUNNING
    assert snapshot.minutes == 60
    assert snapshot.remaining_s == pytest.approx(3600.0)
    assert snapshot.ends_in_text == "60:00"
    assert session.is_running is True


def test_start_voi_thoi_luong_rieng():
    session = make_session(60)
    snapshot = session.start(25)
    assert snapshot.minutes == 25
    assert snapshot.remaining_s == pytest.approx(1500.0)


def test_start_lai_ghi_de_phien_cu():
    clock = FakeClock()
    session = make_session(60, clock=clock)
    session.start(60)
    clock.advance(600)

    snapshot = session.start(10)
    assert snapshot.minutes == 10
    assert snapshot.remaining_s == pytest.approx(600.0)
    assert snapshot.elapsed_s == pytest.approx(0.0)


def test_start_thoi_luong_sai_khong_doi_trang_thai():
    clock = FakeClock()
    session = make_session(30, clock=clock)
    session.start(30)

    with pytest.raises(StudySessionError):
        session.start(0)

    assert session.is_running is True, "lần start hỏng không được dừng phiên đang chạy"
    assert session.snapshot().minutes == 30


def test_stop_ve_idle_va_xoa_so_lieu():
    clock = FakeClock()
    session = make_session(60, clock=clock)
    session.start()
    clock.advance(120)

    snapshot = session.stop()
    assert snapshot.state == STATE_IDLE
    assert snapshot.minutes == 0
    assert snapshot.elapsed_s == 0.0
    assert session.is_running is False


def test_stop_khi_dang_idle_khong_loi():
    session = make_session()
    first = session.stop()
    second = session.stop()
    assert first.state == STATE_IDLE
    assert second.state == STATE_IDLE


def test_dem_nguoc_giam_theo_dong_ho():
    clock = FakeClock()
    session = make_session(2, clock=clock)
    session.start()

    clock.advance(30)
    snapshot = session.snapshot()
    assert snapshot.remaining_s == pytest.approx(90.0)
    assert snapshot.elapsed_s == pytest.approx(30.0)
    assert snapshot.ends_in_text == "01:30"


def test_dem_nguoc_lam_tron_len():
    """0,4 s còn lại phải hiện ``00:01``, không phải ``00:00``: hiện 0 khi vẫn
    còn thời gian khiến người dùng tưởng đã hết giờ."""
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(59.6)
    assert session.snapshot().ends_in_text == "00:01"


# ---------------------------------------------------------------------------
# Hết giờ
# ---------------------------------------------------------------------------


def test_het_gio_tu_dung():
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()

    clock.advance(60)
    snapshot = session.tick()
    assert snapshot.state == STATE_FINISHED
    assert session.is_running is False, "hết giờ là TỰ DỪNG, không phải vẫn chạy"
    assert snapshot.remaining_s == 0.0
    assert snapshot.ends_in_text is None


def test_tick_truoc_gio_khong_dung():
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(59.9)
    assert session.tick().state == STATE_RUNNING
    assert session.is_running is True


def test_cau_het_gio_chi_tra_mot_lan():
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(60)

    first = session.tick()
    assert first.finished_message == FINISHED_MESSAGE

    for _ in range(5):
        later = session.tick()
        assert later.finished_message is None, "câu 'hết giờ' chỉ được ra một lần"
        assert later.state == STATE_FINISHED


def test_phien_moi_dat_lai_co_hoi_bao_het_gio():
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(60)
    assert session.tick().finished_message == FINISHED_MESSAGE

    session.start(1)
    clock.advance(60)
    assert session.tick().finished_message == FINISHED_MESSAGE


def test_snapshot_khong_bao_gio_phat_cau_het_gio():
    """``GET /api/session`` gọi ``snapshot`` mỗi giây; nó không được làm loa kêu."""
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(200)

    snapshot = session.snapshot()
    assert snapshot.state == STATE_FINISHED
    assert snapshot.finished_message is None

    # Vòng lặp tới sau đó vẫn là nơi duy nhất phát câu.
    assert session.tick().finished_message == FINISHED_MESSAGE


def test_snapshot_tu_ap_het_gio_du_chua_tick():
    """Camera đang chờ khung: dashboard vẫn phải thấy ``finished``, không phải
    "còn 00:00" mãi mãi."""
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(61)

    snapshot = session.snapshot()
    assert snapshot.state == STATE_FINISHED
    assert session.is_running is False


def test_finished_giu_lai_so_phut_da_dat():
    clock = FakeClock()
    session = make_session(45, clock=clock)
    session.start()
    clock.advance(45 * 60)

    snapshot = session.tick()
    assert snapshot.state == STATE_FINISHED
    assert snapshot.minutes == 45
    assert snapshot.elapsed_s == pytest.approx(45 * 60)


def test_stop_sau_khi_het_gio_ve_idle():
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(60)
    session.tick()

    assert session.stop().state == STATE_IDLE
    assert session.snapshot().minutes == 0


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------


def test_payload_json_thuan():
    clock = FakeClock()
    session = make_session(30, clock=clock)
    snapshot = session.start()
    data = payload(snapshot)

    assert data["state"] == STATE_RUNNING
    assert data["minutes"] == 30
    assert data["remaining_s"] == 1800.0
    assert data["ends_in_text"] == "30:00"
    assert data["finish_text"] is None
    assert set(data) == {
        "state",
        "minutes",
        "remaining_s",
        "elapsed_s",
        "ends_in_text",
        "finished_message",
        "finish_text",
    }


def test_payload_khong_co_du_lieu_ca_nhan():
    session = make_session(10)
    data = payload(session.start())
    joined = " ".join(str(value) for value in data.values()).lower()
    for word in ("name", "tên", "embedding", "vector", "face", "khuôn mặt"):
        assert word not in joined


def test_payload_finish_text_ben_vung_khi_finished():
    """``finished_message`` chỉ sống đúng một lần ``tick``; ``finish_text``
    phải còn để web hiện lại câu đó."""
    clock = FakeClock()
    session = make_session(1, clock=clock)
    session.start()
    clock.advance(60)
    session.tick()

    for _ in range(3):
        data = payload(session.snapshot())
        assert data["state"] == STATE_FINISHED
        assert data["finish_text"] == FINISHED_MESSAGE


# ---------------------------------------------------------------------------
# An toàn đa luồng
# ---------------------------------------------------------------------------


def test_doc_ghi_dong_thoi_khong_sinh_trang_thai_vo_ly():
    """Vòng lặp đọc mỗi khung trong khi web bấm nút: không khung nào được thấy
    cặp ``(đang chạy, hết hạn)`` không tồn tại."""
    clock = FakeClock()
    session = StudySession(1, clock=clock)
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                snapshot = session.snapshot()
                if snapshot.state == STATE_RUNNING:
                    assert snapshot.remaining_s >= 0.0
                    assert snapshot.ends_in_text is not None
                else:
                    assert snapshot.remaining_s == 0.0
        except BaseException as exc:  # noqa: BLE001 - gom lại để báo ở luồng chính
            errors.append(exc)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            session.start(1)
            clock.advance(30)
            session.tick()
            session.stop()
    finally:
        stop.set()
        thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert errors == []


def test_default_minutes_trong_khoang_cho_phep():
    assert MIN_MINUTES <= DEFAULT_MINUTES <= MAX_MINUTES
