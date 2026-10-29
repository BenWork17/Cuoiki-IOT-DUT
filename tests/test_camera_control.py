"""Unit test cho điều khiển PTZ (spec v2 §5.10).

Toàn bộ test chạy **không cần camera, không cần mạng, không cần cài**
``rtsp-backchannel``: ``PtzController`` chỉ làm việc với một giao diện nhỏ
(``continuous_move``/``stop``/``close``), nên ở đây tiêm một phiên giả và một
hàm ngủ giả. Nhờ vậy test chạy tức thì thay vì chờ đủ ``duration`` thật.

Điểm được kiểm kỹ vì dễ hỏng lặng lẽ:

- Camera phải **dừng** sau mỗi lần xoay, kể cả khi hàm ngủ ném lỗi.
- ``duration`` do client gửi lên phải bị ép vào chặn trên/dưới; nếu không một
  request có thể giữ khoá và giữ camera xoay rất lâu.
- Phiên ONVIF được **cache**, không mở lại mỗi request; phiên hỏng thì bị bỏ
  và mở lại ở lần sau, chứ không dùng mãi một phiên chết.
- Thiếu thư viện thì báo tiếng Việt, không traceback.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import camera_control  # noqa: E402
from posture_monitor.camera_control import (  # noqa: E402
    DEFAULT_MOVE_DURATION_S,
    MAX_MOVE_DURATION_S,
    MIN_MOVE_DURATION_S,
    MISSING_LIBRARY_MESSAGE,
    PtzController,
    PtzError,
    from_config,
)
from posture_monitor.config import CameraConfig, Config, OnvifConfig  # noqa: E402

#: Mật khẩu giả — KHÔNG dùng mật khẩu thật trong bất kỳ test nào.
FAKE_PASSWORD = "matkhau-gia"


class FakeSession:
    """Phiên ONVIF giả, ghi lại đúng thứ tự lệnh đã nhận."""

    def __init__(self, *, move_error: Exception | None = None,
                 stop_error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.closed = 0
        self._move_error = move_error
        self._stop_error = stop_error

    def continuous_move(self, *, pan_tilt, timeout_ms):
        self.calls.append(("continuous_move", pan_tilt, timeout_ms))
        if self._move_error is not None:
            raise self._move_error

    def stop(self, *, pan_tilt=True, zoom=True):
        self.calls.append(("stop", pan_tilt, zoom))
        if self._stop_error is not None:
            raise self._stop_error

    def close(self):
        self.closed += 1
        self.calls.append(("close",))

    @property
    def moves(self):
        return [c for c in self.calls if c[0] == "continuous_move"]

    @property
    def stops(self):
        return [c for c in self.calls if c[0] == "stop"]


class FakeSleeper:
    def __init__(self, error: Exception | None = None) -> None:
        self.slept: list[float] = []
        self._error = error

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)
        if self._error is not None:
            raise self._error


def make_controller(session, *, sleeper=None, password=FAKE_PASSWORD, **kwargs):
    """Controller nối với phiên giả; bộ mở phiên đếm số lần được gọi."""
    opened: list[FakeSession] = []

    def opener():
        opened.append(session)
        return session

    controller = PtzController(
        "192.0.2.10",  # TEST-NET-1: không bao giờ là camera thật
        password=password,
        opener=opener,
        sleeper=sleeper or FakeSleeper(),
        **kwargs,
    )
    return controller, opened


# ---------------------------------------------------------------------------
# move: vector, thứ tự lệnh, stop
# ---------------------------------------------------------------------------


def test_move_gui_dung_vector_roi_dung_camera():
    session = FakeSession()
    controller, _ = make_controller(session)

    controller.move(-1.0, 0.0, 0.2)

    assert len(session.moves) == 1
    _, pan_tilt, timeout_ms = session.moves[0]
    assert pan_tilt == (-1.0, 0.0), "trái là x âm, không phải y"
    assert timeout_ms == pytest.approx(1200.0), "timeout camera = (0.2 + 1) s"
    assert len(session.stops) == 1
    # stop phải nằm SAU continuous_move, nếu không camera xoay mãi.
    names = [c[0] for c in session.calls]
    assert names.index("continuous_move") < names.index("stop")


def test_move_direction_doi_ten_huong_thanh_vector():
    cases = {
        "left": (-1.0, 0.0),
        "right": (1.0, 0.0),
        "up": (0.0, 1.0),
        "down": (0.0, -1.0),
    }
    for direction, expected in cases.items():
        session = FakeSession()
        controller, _ = make_controller(session)
        controller.move_direction(direction, 0.1)
        assert session.moves[0][1] == expected, direction


def test_move_direction_hoa_thuong_va_bo_khoang_trang():
    session = FakeSession()
    controller, _ = make_controller(session)
    controller.move_direction("  RIGHT ", 0.1)
    assert session.moves[0][1] == (1.0, 0.0)


def test_move_direction_sai_huong_tra_loi_tieng_viet():
    session = FakeSession()
    controller, _ = make_controller(session)
    with pytest.raises(PtzError) as excinfo:
        controller.move_direction("xiên", 0.1)
    assert excinfo.value.status == 400
    assert "Hướng xoay" in str(excinfo.value)
    assert session.calls == [], "không được chạm camera khi hướng sai"


def test_move_vector_ngoai_khoang_bi_tu_choi():
    session = FakeSession()
    controller, _ = make_controller(session)
    for dx, dy in ((2.0, 0.0), (0.0, -1.5)):
        with pytest.raises(PtzError) as excinfo:
            controller.move(dx, dy)
        assert excinfo.value.status == 400
    assert session.calls == []


def test_move_vector_bang_khong_bi_tu_choi():
    session = FakeSession()
    controller, _ = make_controller(session)
    with pytest.raises(PtzError) as excinfo:
        controller.move(0.0, 0.0)
    assert excinfo.value.status == 400
    assert session.calls == []


def test_move_vector_khong_phai_so_bi_tu_choi():
    session = FakeSession()
    controller, _ = make_controller(session)
    with pytest.raises(PtzError):
        controller.move(True, False)  # bool là int trong Python — phải chặn
    assert session.calls == []


def test_stop_van_chay_khi_ham_ngu_nem_loi():
    """Nếu ngủ lỗi mà không stop, camera sẽ xoay mãi cho tới timeout."""
    session = FakeSession()
    controller, _ = make_controller(session, sleeper=FakeSleeper(RuntimeError("bùm")))

    with pytest.raises(RuntimeError):
        controller.move(1.0, 0.0, 0.1)

    assert len(session.stops) == 1


def test_stop_loi_khong_lam_hong_ket_qua_xoay():
    """``stop`` là best-effort: lỗi dừng không được biến cú xoay thành 5xx."""
    session = FakeSession(stop_error=RuntimeError("SOAP stop hỏng"))
    controller, _ = make_controller(session)
    assert controller.move(1.0, 0.0, 0.1) == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# duration: ép chặn trên / chặn dưới
# ---------------------------------------------------------------------------


def test_duration_bi_ep_xuong_chan_tren():
    session = FakeSession()
    sleeper = FakeSleeper()
    controller, _ = make_controller(session, sleeper=sleeper)

    moved = controller.move(1.0, 0.0, 999.0)

    assert moved == pytest.approx(MAX_MOVE_DURATION_S)
    assert sleeper.slept == [pytest.approx(MAX_MOVE_DURATION_S)]
    timeout_ms = session.moves[0][2]
    assert timeout_ms == pytest.approx((MAX_MOVE_DURATION_S + 1.0) * 1000.0)
    assert 1.0 <= timeout_ms <= 60_000.0, "phải nằm trong cửa sổ của thư viện"


def test_duration_bi_ep_len_chan_duoi():
    session = FakeSession()
    sleeper = FakeSleeper()
    controller, _ = make_controller(session, sleeper=sleeper)
    assert controller.move(1.0, 0.0, 0.0) == pytest.approx(MIN_MOVE_DURATION_S)
    assert sleeper.slept == [pytest.approx(MIN_MOVE_DURATION_S)]


def test_duration_mac_dinh_khi_khong_truyen():
    session = FakeSession()
    controller, _ = make_controller(session)
    assert controller.move(0.0, 1.0) == pytest.approx(DEFAULT_MOVE_DURATION_S)


@pytest.mark.parametrize("bad", [float("nan"), "abc", object()])
def test_duration_khong_hop_le_ve_mac_dinh(bad):
    session = FakeSession()
    controller, _ = make_controller(session)
    assert controller.move(1.0, 0.0, bad) == pytest.approx(DEFAULT_MOVE_DURATION_S)


def test_duration_vo_cuc_bi_ep_ve_chan_tren():
    session = FakeSession()
    controller, _ = make_controller(session)
    assert controller.move(1.0, 0.0, float("inf")) == pytest.approx(
        MAX_MOVE_DURATION_S
    )


# ---------------------------------------------------------------------------
# Phiên: lười, cache, khoá, đóng
# ---------------------------------------------------------------------------


def test_init_khong_mo_phien():
    session = FakeSession()
    controller, opened = make_controller(session)
    assert opened == [], "PtzController không được nối mạng trong __init__"
    assert controller._session is None


def test_phien_duoc_cache_giua_cac_lan_move():
    session = FakeSession()
    controller, opened = make_controller(session)
    controller.move(1.0, 0.0, 0.1)
    controller.move(-1.0, 0.0, 0.1)
    assert len(opened) == 1, "mỗi request mở phiên mới là sai thiết kế"
    assert len(session.moves) == 2


def test_phien_hong_bi_bo_va_lan_sau_mo_lai():
    broken = FakeSession(move_error=RuntimeError("mất mạng"))
    healthy = FakeSession()
    opened: list[FakeSession] = []

    def opener():
        target = broken if not opened else healthy
        opened.append(target)
        return target

    controller = PtzController(
        "192.0.2.10", password=FAKE_PASSWORD, opener=opener, sleeper=FakeSleeper()
    )

    with pytest.raises(PtzError) as excinfo:
        controller.move(1.0, 0.0, 0.1)
    assert excinfo.value.status == 502
    assert broken.closed == 1, "phiên hỏng phải được đóng"

    assert controller.move(1.0, 0.0, 0.1) == pytest.approx(0.1)
    assert len(opened) == 2
    assert len(healthy.moves) == 1


def test_camera_khong_ho_tro_continuous_tra_501():
    session = FakeSession(
        move_error=RuntimeError("PTZ continuous pan/tilt is not supported")
    )
    controller, _ = make_controller(session)
    with pytest.raises(PtzError) as excinfo:
        controller.move(1.0, 0.0, 0.1)
    assert excinfo.value.status == 501
    assert "liên tục" in str(excinfo.value)


def test_close_hai_lan_khong_loi():
    session = FakeSession()
    controller, _ = make_controller(session)
    controller.move(1.0, 0.0, 0.1)

    controller.close()
    controller.close()

    assert session.closed == 1, "close() idempotent, không đóng hai lần"


def test_move_sau_close_bao_loi_ro_rang():
    session = FakeSession()
    controller, _ = make_controller(session)
    controller.close()
    with pytest.raises(PtzError) as excinfo:
        controller.move(1.0, 0.0, 0.1)
    assert "đóng" in str(excinfo.value)


def test_lock_khong_cho_hai_lenh_chong_len_nhau():
    """Flask chạy đa luồng: hai cú bấm không được chồng lên cùng một phiên.

    Bộ đếm phải mở ở ``continuous_move`` và chỉ đóng ở ``stop`` — tức là span
    bao trọn cả quãng ngủ giữa hai lệnh, nơi camera đang thật sự xoay. Bản cũ
    tăng/giảm ngay trong một lời gọi ``continuous_move`` (vài micro-giây), nên
    nó chỉ đo độ chồng lấn bên trong lời gọi đồng bộ và **luôn** thấy
    ``max_active == 1``, kể cả khi bỏ khoá: một test xanh giả.
    """

    class DoSession(FakeSession):
        """Mở span khi bắt đầu xoay, đóng span khi camera đã dừng."""

        def __init__(self):
            super().__init__()
            self.active = 0
            self.max_active = 0
            self._guard = threading.Lock()

        def continuous_move(self, *, pan_tilt, timeout_ms):
            with self._guard:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            super().continuous_move(pan_tilt=pan_tilt, timeout_ms=timeout_ms)

        def stop(self, *, pan_tilt=True, zoom=True):
            try:
                super().stop(pan_tilt=pan_tilt, zoom=zoom)
            finally:
                with self._guard:
                    self.active -= 1

    # Đủ dài để 4 luồng thật sự có cơ hội chồng nhau nếu thiếu khoá, đủ ngắn
    # để cả test dưới 1 giây khi khoá hoạt động (4 luồng nối tiếp nhau).
    duration = 0.1
    session = DoSession()
    controller, _ = make_controller(session, sleeper=time.sleep)

    # Cổng xuất phát: cả 4 luồng cùng vào ``move`` một lúc, không dựa vào việc
    # lịch trình luồng tình cờ trùng nhau.
    start_gate = threading.Event()

    def worker():
        start_gate.wait()
        controller.move(1.0, 0.0, duration)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    start_gate.set()
    for thread in threads:
        thread.join(timeout=10.0)

    assert not any(t.is_alive() for t in threads), "còn luồng treo sau move"
    # Khoá đang giữ thì không bao giờ quá 1 — assert này không thể đỏ vì máy
    # chậm. Bỏ khoá thì 4 luồng cùng ngủ, bộ đếm thấy 2..4.
    assert session.max_active == 1, f"{session.max_active} lệnh chồng lên nhau"
    assert len(session.moves) == 4
    assert len(session.stops) == 4


# ---------------------------------------------------------------------------
# Bảo mật: mật khẩu không rò
# ---------------------------------------------------------------------------


def test_repr_khong_lo_mat_khau_va_che_userinfo():
    """Lỗi hay gặp: dán cả URL RTSP (có mật khẩu) vào ``camera.onvif.host``.

    Host trần thì không phải bí mật, nhưng userinfo trong URL thì có — nên
    ``repr`` đi qua :func:`redact_camera_source` như mọi thông điệp khác.
    """
    controller = PtzController(
        "rtsp://admin:matkhau-gia@192.0.2.10:554/1/2", password=FAKE_PASSWORD
    )
    text = repr(controller)
    assert FAKE_PASSWORD not in text
    assert "admin" not in text
    assert "***:***@" in text, "host phải đi qua redact_camera_source"


def test_thong_diep_loi_chua_url_co_mat_khau_bi_che():
    """Lỗi mạng có thể kèm URL đầy đủ; thông điệp ra ngoài phải đã che."""

    def opener():
        raise RuntimeError("không tới được rtsp://admin:matkhau-gia@192.0.2.10:554/")

    controller = PtzController(
        "192.0.2.10", password=FAKE_PASSWORD, opener=opener, sleeper=FakeSleeper()
    )
    with pytest.raises(PtzError) as excinfo:
        controller.move(1.0, 0.0, 0.1)
    assert FAKE_PASSWORD not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Thư viện tuỳ chọn
# ---------------------------------------------------------------------------


def test_thieu_thu_vien_bao_loi_tieng_viet(monkeypatch):
    # ``None`` trong sys.modules làm ``import`` ném ImportError ngay cả khi
    # wheel có mặt, nên test này không phụ thuộc môi trường.
    monkeypatch.setitem(sys.modules, "rtsp_backchannel", None)
    with pytest.raises(PtzError) as excinfo:
        camera_control._load_library()
    assert str(excinfo.value) == MISSING_LIBRARY_MESSAGE
    assert "Chưa cài thư viện" in str(excinfo.value)
    assert excinfo.value.status == 503


def test_move_khi_thieu_thu_vien_khong_traceback_ra_ngoai(monkeypatch):
    """Đường thật (không tiêm phiên giả) khi thiếu thư viện."""
    monkeypatch.setitem(sys.modules, "rtsp_backchannel", None)
    controller = PtzController("192.0.2.10", password=FAKE_PASSWORD,
                               sleeper=FakeSleeper())

    with pytest.raises(PtzError) as excinfo:
        controller.move(1.0, 0.0, 0.1)

    message = str(excinfo.value)
    assert message == MISSING_LIBRARY_MESSAGE
    assert "Traceback" not in message
    assert FAKE_PASSWORD not in message


def test_module_import_duoc_khong_can_thu_vien():
    """Module phải import được ngay cả khi chưa cài ``rtsp-backchannel``."""
    assert camera_control.PtzController is PtzController


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


def test_from_config_khi_tat_onvif():
    with pytest.raises(PtzError) as excinfo:
        from_config(Config())
    assert "camera.onvif.enabled" in str(excinfo.value)


def test_from_config_thieu_host():
    config = Config()
    config.camera = CameraConfig(onvif=OnvifConfig(enabled=True, host=""))
    with pytest.raises(PtzError) as excinfo:
        from_config(config)
    assert "host" in str(excinfo.value)


def test_from_config_thieu_mat_khau(monkeypatch):
    monkeypatch.delenv(camera_control.ONVIF_PASSWORD_ENV, raising=False)
    config = Config()
    config.camera = CameraConfig(
        onvif=OnvifConfig(enabled=True, host="192.0.2.10")
    )
    with pytest.raises(PtzError) as excinfo:
        from_config(config)
    assert camera_control.ONVIF_PASSWORD_ENV in str(excinfo.value)


def test_from_config_du_thi_tao_controller(monkeypatch):
    monkeypatch.setenv(camera_control.ONVIF_PASSWORD_ENV, FAKE_PASSWORD)
    config = Config()
    config.camera = CameraConfig(
        onvif=OnvifConfig(enabled=True, host="192.0.2.10", port=8080, user="admin")
    )
    controller = from_config(config)
    assert controller.port == 8080
    assert controller.user == "admin"
    assert controller._session is None, "from_config cũng phải lười"
    assert FAKE_PASSWORD not in repr(controller)


# ---------------------------------------------------------------------------
# Đường mở phiên thật: chỉ kiểm phần dựng tham số
# ---------------------------------------------------------------------------


def test_duong_mo_phien_that_dung_dung_api_thu_vien(monkeypatch):
    """Kiểm tra lớp mỏng ``_LibrarySession`` khớp chữ ký thật của thư viện."""
    recorded: dict[str, object] = {}

    class FakeVector:
        def __init__(self, x, y):
            self.x, self.y = x, y

    class FakeRealSession:
        def continuous_move(self, *, pan_tilt, timeout_ms):
            recorded["pan_tilt"] = (pan_tilt.x, pan_tilt.y)
            recorded["timeout_ms"] = timeout_ms

        def stop(self, *, pan_tilt=True, zoom=True):
            recorded["stop"] = (pan_tilt, zoom)

        def close(self):
            recorded["closed"] = True

    library = SimpleNamespace(
        PtzVector=FakeVector,
        PtzSessionOptions=lambda **kwargs: recorded.setdefault("options", kwargs),
        open_ptz_session=lambda options: FakeRealSession(),
    )
    monkeypatch.setitem(sys.modules, "rtsp_backchannel", library)

    controller = PtzController(
        "192.0.2.10", port=8080, user="admin", password=FAKE_PASSWORD,
        sleeper=FakeSleeper(),
    )
    controller.move(0.0, -1.0, 0.25)

    options = recorded["options"]
    assert options["host"] == "192.0.2.10"
    assert options["password"] == FAKE_PASSWORD
    assert options["device_urls"] == ["http://192.0.2.10:8080/onvif/device_service"]
    assert recorded["pan_tilt"] == (0.0, -1.0)
    assert recorded["stop"] == (True, True)


# ---------------------------------------------------------------------------
# from_config: tài khoản lấy từ tài khoản nhúng trong camera.source
# ---------------------------------------------------------------------------

SOURCE_USER = "camera-user"
SOURCE_URL = f"rtsp://{SOURCE_USER}:{FAKE_PASSWORD}@192.0.2.77:554/1/2"


def _config_with_source(source: str, **onvif_kwargs) -> Config:
    config = Config()
    config.camera = CameraConfig(
        source=source,
        onvif=OnvifConfig(**onvif_kwargs),
    )
    return config


def test_from_config_dung_tai_khoan_nhung_trong_camera_source(monkeypatch):
    """Không có ``POSTURE_ONVIF_PASSWORD``: lấy tài khoản trong URL nguồn.

    Người dùng đặt camera IP bằng một biến môi trường duy nhất
    (``POSTURE_CAMERA_SOURCE``); cùng một camera thì cùng một tài khoản, nên
    không phải nhập mật khẩu lần thứ hai.
    """
    monkeypatch.delenv(camera_control.ONVIF_PASSWORD_ENV, raising=False)
    config = _config_with_source(f"rtsp:{SOURCE_URL}", enabled=True, host="192.0.2.77")

    controller = from_config(config)

    assert controller.user == SOURCE_USER
    assert controller._password == FAKE_PASSWORD
    assert controller._session is None
    assert FAKE_PASSWORD not in repr(controller)
    assert FAKE_PASSWORD not in repr(config), "repr(config) cũng phải che"


def test_from_config_bien_moi_truong_thang_tai_khoan_trong_source(monkeypatch):
    """Có ``POSTURE_ONVIF_PASSWORD`` thì nó thắng tài khoản trong URL nguồn."""
    monkeypatch.setenv(camera_control.ONVIF_PASSWORD_ENV, "mat-khau-khac")
    config = _config_with_source(
        f"rtsp:{SOURCE_URL}", enabled=True, host="192.0.2.77", user="admin"
    )

    controller = from_config(config)

    assert controller.user == "admin"
    assert controller._password == "mat-khau-khac"


def test_from_config_khi_that_bai_chi_ro_ca_hai_duong_sua(monkeypatch):
    """Thiếu mật khẩu ở mọi nơi → thông điệp nêu cả hai biến môi trường."""
    monkeypatch.delenv(camera_control.ONVIF_PASSWORD_ENV, raising=False)
    config = _config_with_source(
        "rtsp:rtsp://192.0.2.77:554/1/2", enabled=True, host="192.0.2.77"
    )

    with pytest.raises(PtzError) as excinfo:
        from_config(config)

    message = str(excinfo.value)
    assert camera_control.ONVIF_PASSWORD_ENV in message
    assert camera_control.CAMERA_SOURCE_ENV in message
    assert FAKE_PASSWORD not in message
    assert excinfo.value.status == 503


def test_from_config_tat_thi_thong_diep_chi_cach_bat(monkeypatch):
    """PTZ tắt → lỗi nêu đường bật mới (biến môi trường) lẫn đường cũ."""
    monkeypatch.delenv(camera_control.ONVIF_PASSWORD_ENV, raising=False)
    config = _config_with_source("usb:0", enabled=False)

    with pytest.raises(PtzError) as excinfo:
        from_config(config)

    message = str(excinfo.value)
    assert camera_control.CAMERA_SOURCE_ENV in message
    assert "camera.onvif.enabled" in message
