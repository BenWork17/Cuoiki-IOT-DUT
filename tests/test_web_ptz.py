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
# Ghép route với PtzController thật (phiên giả): chặn duration nằm ở đâu?
# ---------------------------------------------------------------------------


class FakePtzSession:
    """Phiên tối thiểu để kiểm route + controller thật cùng lúc."""

    def __init__(self) -> None:
        self.pan_tilt: list[tuple[float, float]] = []
        self.stopped = 0

    def continuous_move(self, *, pan_tilt, timeout_ms):
        self.pan_tilt.append(pan_tilt)

    def stop(self, *, pan_tilt=True, zoom=True):
        self.stopped += 1

    def close(self):
        pass


def test_route_voi_controller_that_thi_duration_bi_ep():
    """Route không tự cắt ``duration``; ``PtzController`` mới cắt.

    Ghép hai nửa lại để chốt rằng client gửi 999 giây vẫn chỉ xoay 3 giây —
    đây là chỗ chặn giữ khoá và giữ camera xoay quá lâu.
    """
    from posture_monitor.camera_control import PtzController

    session = FakePtzSession()
    controller = PtzController(
        "192.0.2.10", password=FAKE_PASSWORD, opener=lambda: session,
        sleeper=lambda seconds: None,
    )
    client = make_client(
        config=make_config(onvif_enabled=True, host="192.0.2.10"), ptz=controller
    )

    payload = client.post(
        "/api/ptz", json={"direction": "left", "duration": 999}
    ).get_json()

    assert payload["duration"] == pytest.approx(3.0)
    assert session.pan_tilt == [(-1.0, 0.0)], "chỉ đúng một lệnh xoay"
    assert session.stopped == 1


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


# ---------------------------------------------------------------------------
# Giao diện: dashboard phải thật sự CÓ nút và thật sự gọi route
# ---------------------------------------------------------------------------
#
# Backend có route mà giao diện không có nút thì người dùng bấm không ra gì —
# đúng lỗi được báo. Test dưới đây đọc thẳng template và app.js (không chạy
# JS), nên chúng khẳng định *dây nối tồn tại* chứ không khẳng định hành vi
# trình duyệt. Phần hành vi (bấm giữ, khoá nút) được kiểm bằng mắt trên trình
# duyệt thật, ghi rõ trong báo cáo.

from posture_monitor.camera_control import DIRECTION_VECTORS  # noqa: E402

_TEMPLATE = (
    _REPO_ROOT / "src" / "posture_monitor" / "web" / "templates" / "index.html"
)
_APP_JS = _REPO_ROOT / "src" / "posture_monitor" / "web" / "static" / "app.js"


def _html() -> str:
    app = create_app(make_config(), state=DashboardState())
    app.config.update(TESTING=True)
    return app.test_client().get("/").get_data(as_text=True)


def test_trang_chu_co_du_bon_nut_ptz_theo_dung_huong():
    """Bốn ``data-ptz-direction`` khớp đúng tập hướng backend nhận.

    So với ``DIRECTION_VECTORS`` chứ không đếm chuỗi: thêm một hướng ở backend
    mà quên nút, hoặc đổi tên hướng, đều làm test đỏ.
    """
    import re

    html = _html()
    found = set(re.findall(r'data-ptz-direction="([^"]+)"', html))

    assert found == set(DIRECTION_VECTORS), (
        f"nút PTZ lệch so với backend: thiếu {set(DIRECTION_VECTORS) - found}, "
        f"thừa {found - set(DIRECTION_VECTORS)}"
    )


def test_moi_nut_ptz_co_id_va_nhan_tieng_viet():
    html = _html()
    for direction in DIRECTION_VECTORS:
        assert f'id="ptz-{direction}"' in html, direction
    for label in (
        'aria-label="Xoay camera lên"',
        'aria-label="Xoay camera xuống"',
        'aria-label="Xoay camera sang trái"',
        'aria-label="Xoay camera sang phải"',
    ):
        assert label in html, label


def test_trang_chu_khong_lo_thong_tin_dang_nhap_camera():
    """HTML không được chứa mật khẩu hay host của camera."""
    assert FAKE_PASSWORD not in _html()


def _ptz_request_body_expression(script: str) -> str:
    """Chuỗi đối số của ``JSON.stringify(...)`` trong lời gọi ``/api/ptz``.

    Cắt đúng khối của lời gọi đó (cân bằng ngoặc) chứ không tìm chuỗi rời:
    ``"direction"`` xuất hiện ở nhiều chỗ khác trong file, nên một assert
    ``in script`` vẫn xanh dù thân request đã mất hướng — đúng lỗi mà test
    này phải bắt.
    """
    anchor = script.index('"/api/ptz"')
    start = script.index("JSON.stringify(", anchor) + len("JSON.stringify(")
    depth = 1
    for index in range(start, len(script)):
        char = script[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return script[start:index]
    raise AssertionError("JSON.stringify( không đóng ngoặc trong app.js")


def test_app_js_goi_route_ptz_voi_huong_va_thoi_gian():
    """Thân request ``POST /api/ptz`` phải có cả ``direction`` lẫn ``duration``."""
    script = _APP_JS.read_text(encoding="utf-8")

    assert '"/api/ptz"' in script, "giao diện chưa nối vào route PTZ"
    assert 'method: "POST"' in script

    body = _ptz_request_body_expression(script)
    assert "direction: direction" in body, (
        f"thân request thiếu hướng; thực tế: {body!r}"
    )
    assert "duration: duration" in body, (
        f"thân request thiếu thời gian; thực tế: {body!r}"
    )
    assert "pointerdown" in script, "thiếu bấm-giữ"
    assert "pointerup" in script, "thiếu nhả tay để dừng xoay"


def test_app_js_doc_du_bon_huong_tu_dom_va_khong_hardcode_danh_sach_huong():
    """Chọn nút qua ``[data-ptz-direction]``: thêm nút trong HTML là chạy ngay."""
    script = _APP_JS.read_text(encoding="utf-8")
    assert 'querySelectorAll("[data-ptz-direction]")' in script
    for direction in DIRECTION_VECTORS:
        # Không được tự dựng danh sách hướng trong JS (hai nguồn sự thật).
        assert f'"{direction}"' not in script, (
            f"app.js hardcode hướng {direction!r}; hãy đọc từ data-ptz-direction"
        )


# ---------------------------------------------------------------------------
# Phụ thuộc: người khác cài theo requirements.txt phải có nút xoay chạy được
# ---------------------------------------------------------------------------

_REQUIREMENTS = _REPO_ROOT / "requirements.txt"


def test_requirements_pin_rtsp_backchannel():
    """``requirements.txt`` phải ghim ``rtsp-backchannel`` đúng bản đã kiểm chứng.

    Trên Pi venv trước đây thiếu thư viện này nên nút xoay báo 503 —
    ``camera_control`` vẫn chạy nhờ import muộn, nhưng không ai cài được nó
    từ repo. Test này khoá dòng phụ thuộc đó.
    """
    import re

    text = _REQUIREMENTS.read_text(encoding="utf-8")
    # Bỏ chú thích: dòng bị comment không cài được gì.
    lines = [line.split("#", 1)[0].strip() for line in text.splitlines()]

    assert "rtsp-backchannel==0.5.2" in lines, (
        "requirements.txt phải có dòng 'rtsp-backchannel==0.5.2' (không comment)"
    )
    # Bản đã kiểm chứng thật trên camera của dự án; nới lỏng thành >= là mời
    # một bản chưa ai thử.
    assert not any(
        re.match(r"^rtsp-backchannel\s*(?:>=|>|~=|!=|<=|<)", line)
        for line in lines
    ), "không được nới lỏng phiên bản rtsp-backchannel"
