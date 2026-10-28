"""Test route ``POST /api/ptz`` (spec v2 §5.10).

Camera thật **không** được gọi: route nhận controller tiêm từ ngoài, nên test
dùng một đối tượng giả ghi lại lời gọi. Nhờ vậy khẳng định được cả hợp đồng
giữa route và :class:`posture_monitor.camera_control.PtzController` (tên hướng,
``duration`` sau khi ép) mà không cần mạng.

Mọi lỗi phải trả **JSON** (không HTML) và thông điệp tiếng Việt; mật khẩu giả
dùng trong test không được xuất hiện trong body.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.camera_control import PtzError  # noqa: E402
from posture_monitor.config import (  # noqa: E402
    CameraConfig,
    Config,
    OnvifConfig,
    WebConfig,
)
from posture_monitor.web import DashboardState, create_app  # noqa: E402

FAKE_PASSWORD = "matkhau-gia"


class FakePtz:
    """Controller giả: ghi lại ``(direction, duration)`` đã nhận."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, float | None]] = []
        self._error = error

    def move_direction(self, direction, duration_s=None):
        self.calls.append((direction, duration_s))
        if self._error is not None:
            raise self._error
        return duration_s


class ExplodingPtz:
    """Controller ném lỗi lạ (không phải ``PtzError``) — route phải bọc lại."""

    def move_direction(self, direction, duration_s=None):
        raise ZeroDivisionError("lỗi lập trình")


def make_config(*, onvif_enabled: bool = False, host: str = "") -> Config:
    config = Config()
    config.web = WebConfig(host="127.0.0.1", port=8000, stream_enabled=False)
    config.camera = CameraConfig(
        onvif=OnvifConfig(enabled=onvif_enabled, host=host)
    )
    return config


def make_client(*, config=None, ptz=None):
    app = create_app(
        config if config is not None else make_config(),
        state=DashboardState(),
        ptz=ptz,
    )
    app.config.update(TESTING=True)
    return app.test_client()


def assert_json_error(response, status: int):
    assert response.status_code == status
    assert response.mimetype == "application/json", "lỗi phải là JSON, không HTML"
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["message"], str) and payload["message"]
    assert FAKE_PASSWORD not in payload["message"]
    assert FAKE_PASSWORD not in response.get_data(as_text=True)
    return payload


# ---------------------------------------------------------------------------
# Hợp đồng cơ bản
# ---------------------------------------------------------------------------


def test_ptz_xoay_dung_huong_va_tra_json():
    ptz = FakePtz()
    client = make_client(ptz=ptz)

    response = client.post("/api/ptz", json={"direction": "left", "duration": 0.2})

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["direction"] == "left"
    assert payload["duration"] == pytest.approx(0.2)
    assert "trái" in payload["message"]
    assert ptz.calls == [("left", pytest.approx(0.2))]


@pytest.mark.parametrize("direction", ["left", "right", "up", "down"])
def test_ptz_chap_nhan_du_bon_huong(direction):
    ptz = FakePtz()
    client = make_client(ptz=ptz)
    response = client.post("/api/ptz", json={"direction": direction})
    assert response.status_code == 200
    assert ptz.calls == [(direction, pytest.approx(0.5))]


def test_ptz_duration_mac_dinh_khi_khong_gui():
    ptz = FakePtz()
    client = make_client(ptz=ptz)
    client.post("/api/ptz", json={"direction": "up"})
    assert ptz.calls == [("up", pytest.approx(0.5))]


def test_ptz_khong_tao_route_khac():
    """Chỉ thêm đúng một route; không lén mở API phụ."""
    app = create_app(make_config(), state=DashboardState())
    ptz_rules = [rule.rule for rule in app.url_map.iter_rules()
                 if "ptz" in rule.rule]
    assert ptz_rules == ["/api/ptz"]


# ---------------------------------------------------------------------------
# Lỗi đầu vào → 400, không chạm camera
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"direction": "xiên"},
        {"direction": None},
        {"direction": 1},
        {"direction": "left", "duration": "lâu"},
        {"direction": "left", "duration": True},
        {"direction": "left", "duration": -1},
    ],
)
def test_ptz_dau_vao_sai_tra_400_va_khong_goi_camera(body):
    ptz = FakePtz()
    client = make_client(ptz=ptz)
    response = client.post("/api/ptz", json=body)
    assert_json_error(response, 400)
    assert ptz.calls == []


def test_ptz_than_khong_phai_json_tra_400():
    ptz = FakePtz()
    client = make_client(ptz=ptz)
    response = client.post("/api/ptz", data="khong-phai-json",
                           content_type="text/plain")
    assert_json_error(response, 400)
    assert ptz.calls == []


def test_ptz_than_la_mang_tra_400():
    client = make_client(ptz=FakePtz())
    assert_json_error(client.post("/api/ptz", json=[1, 2, 3]), 400)


def test_ptz_duration_qua_lon_bi_ep_boi_controller():
    """Route chuyển tiếp nguyên giá trị; ``camera_control`` mới là nơi ép.

    Ở đây controller giả trả lại ``duration_s`` nhận được, nên thấy ngay route
    không tự cắt (cắt hai nơi là hai nguồn sự thật).
    """
    ptz = FakePtz()
    client = make_client(ptz=ptz)
    client.post("/api/ptz", json={"direction": "right", "duration": 999})
    assert ptz.calls == [("right", pytest.approx(999.0))]


# ---------------------------------------------------------------------------
# Thiếu cấu hình → 503 kèm hướng dẫn
# ---------------------------------------------------------------------------


def test_ptz_khi_onvif_tat_tra_503_tieng_viet():
    """Không tiêm controller + cấu hình tắt: route báo đúng khóa cần bật."""
    client = make_client(config=make_config(onvif_enabled=False))

    payload = assert_json_error(
        client.post("/api/ptz", json={"direction": "left"}), 503
    )
    assert "camera.onvif.enabled" in payload["message"]
    assert "host" in payload["message"]


def test_ptz_khong_co_cau_hinh_nao_cung_tra_json_503():
    """``create_app()`` không truyền config: vẫn phải là JSON tiếng Việt."""
    app = create_app(None, state=DashboardState())
    app.config.update(TESTING=True)

    payload = assert_json_error(
        app.test_client().post("/api/ptz", json={"direction": "left"}), 503
    )
    assert "camera.onvif.enabled" in payload["message"]


def test_ptz_onvif_bat_nhung_thieu_host_tra_503(monkeypatch):
    monkeypatch.setenv("POSTURE_ONVIF_PASSWORD", FAKE_PASSWORD)
    client = make_client(config=make_config(onvif_enabled=True, host=""))

    payload = assert_json_error(
        client.post("/api/ptz", json={"direction": "right"}), 503
    )
    assert "camera.onvif.host" in payload["message"]


def test_ptz_onvif_bat_nhung_thieu_mat_khau_tra_503(monkeypatch):
    """Đường thật: bật ONVIF nhưng biến môi trường mật khẩu chưa đặt."""
    monkeypatch.delenv("POSTURE_ONVIF_PASSWORD", raising=False)
    client = make_client(config=make_config(onvif_enabled=True, host="192.0.2.10"))

    payload = assert_json_error(
        client.post("/api/ptz", json={"direction": "left"}), 503
    )
    assert "POSTURE_ONVIF_PASSWORD" in payload["message"]


def test_ptz_onvif_bat_khong_truyen_controller_thi_mo_luoi(monkeypatch):
    """Có cấu hình + mật khẩu: controller được tạo (lười) và dùng thật.

    ``from_config`` chỉ dựng đối tượng, không nối mạng, nên an toàn cho test.
    """
    monkeypatch.setenv("POSTURE_ONVIF_PASSWORD", FAKE_PASSWORD)
    app = create_app(
        make_config(onvif_enabled=True, host="192.0.2.10"), state=DashboardState()
    )
    app.config.update(TESTING=True)
    assert app.config["PTZ_CONTROLLER"] is None

    client = app.test_client()
    # Không bấm nút thì chưa có controller nào (không mở phiên ONVIF sớm).
    assert app.config["PTZ_CONTROLLER"] is None

    from posture_monitor import camera_control

    created = []

    def fake_from_config(config):
        controller = FakePtz()
        created.append(controller)
        return controller

    monkeypatch.setattr(camera_control, "from_config", fake_from_config)
    response = client.post("/api/ptz", json={"direction": "up", "duration": 0.1})

    assert response.status_code == 200
    assert app.config["PTZ_CONTROLLER"] is created[0], "controller phải được cache"
    assert created[0].calls == [("up", pytest.approx(0.1))]


# ---------------------------------------------------------------------------
# Lỗi từ controller → mã HTTP của PtzError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, fragment",
    [
        (501, "liên tục"),
        (502, "không nhận lệnh"),
        (503, "Chưa cài thư viện"),
    ],
)
def test_ptz_loi_tu_controller_giu_ma_http(status, fragment):
    ptz = FakePtz(error=PtzError(f"Lỗi thử: {fragment}", status=status))
    client = make_client(ptz=ptz)

    payload = assert_json_error(
        client.post("/api/ptz", json={"direction": "down"}), status
    )
    assert fragment in payload["message"]


def test_ptz_loi_khong_luong_truoc_tra_500_json():
    client = make_client(ptz=ExplodingPtz())
    payload = assert_json_error(client.post("/api/ptz", json={"direction": "left"}), 500)
    assert "log" in payload["message"].lower()


def test_ptz_khong_lo_thong_tin_mat_khau_tu_controller():
    """Thông điệp controller có URL đầy đủ vẫn không được lộ mật khẩu.

    Route tin tưởng ``PtzError`` đã che sẵn; test này chốt rằng body thật sự
    sạch khi lỗi đến từ phía thư viện.
    """
    from posture_monitor.camera_control import redact_camera_source

    leaky = PtzError(
        redact_camera_source(
            "không tới được rtsp://admin:matkhau-gia@192.0.2.10:554/"
        ),
        status=502,
    )
    client = make_client(ptz=FakePtz(error=leaky))
    assert_json_error(client.post("/api/ptz", json={"direction": "left"}), 502)
