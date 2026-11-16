"""Kiểm thử ``GET /api/frame`` — một khung JPEG rời cho ứng dụng điện thoại.

Vì sao có route này: iOS/React Native **không** render được
``multipart/x-mixed-replace`` trong ``<Image>``, nên ``/stream`` (MJPEG) không
dùng được cho app Expo Go. App gọi ``/api/frame`` theo nhịp của nó và nhận một
ảnh JPEG trọn vẹn mỗi lần.

File này khoá đúng bốn nhánh của hợp đồng:

1. có khung + stream bật → 200, ``image/jpeg``, **đúng byte** đã đặt vào
   ``DashboardState``, kèm ``Cache-Control: no-store``;
2. ``web.stream_enabled: false`` → 403 JSON, câu thông điệp **giống hệt**
   ``/stream`` (một nguồn duy nhất, không có thông điệp thứ hai);
3. chưa có khung nào → 503 JSON tiếng Việt, **không** phải 200 rỗng;
4. route chỉ đọc: không gọi ``cv2.imwrite``, không mở camera.

Không dùng fixture ``tmp_path``: sandbox của máy làm mọi thư mục pytest tạo
bằng ``mkdir(mode=0o700)`` không ``scandir`` được (``PermissionError
[WinError 5]``), nên test này chỉ dùng ``app.test_client()`` và bộ nhớ. Riêng
bài "không ghi đĩa" dùng ``os.scandir`` trên thư mục làm việc hiện tại — thao
tác đọc, không tạo thư mục tạm nào.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.config import Config, WebConfig  # noqa: E402
from posture_monitor.web import DashboardState, create_app  # noqa: E402
from posture_monitor.web import app as web_app_module  # noqa: E402

#: Byte JPEG tổng hợp: khung mở ``FF D8``, dữ liệu phân biệt được, khung đóng
#: ``FF D9``. Không phải ảnh thật — route chỉ chuyển byte, không giải mã, nên
#: ảnh thật không cần và sẽ làm test phụ thuộc thư viện mã hoá.
_FRAME_A = b"\xff\xd8khung-mot-\x00\x01\x02\xff\xd9"
_FRAME_B = b"\xff\xd8khung-hai-\xff\xfe\xfd\xff\xd9"


def _make_client(stream_enabled: bool, state: DashboardState | None = None):
    """Dựng ``test_client`` như ``tests/test_web.py`` (không DB, không I/O)."""
    config = Config()
    config.web = WebConfig(
        host="127.0.0.1", port=8000, stream_enabled=stream_enabled
    )
    app = create_app(config, state=state or DashboardState())
    app.config.update(TESTING=True)
    return app.test_client()


# --------------------------------------------------------------------------
# 1. Có khung + stream bật → 200, image/jpeg, đúng byte, no-store
# --------------------------------------------------------------------------


def test_frame_tra_dung_byte_da_dat_vao_state():
    """Byte trả ra phải **giống hệt** byte đã đặt vào ``DashboardState``.

    Đây là bài quan trọng nhất: một route trả ``200 image/jpeg`` với thân rỗng
    hoặc với ảnh khác vẫn "trông đúng" nếu chỉ so mã trạng thái và content-type.
    """
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(_FRAME_A)

    response = client.get("/api/frame")

    assert response.status_code == 200
    assert response.data == _FRAME_A, "phải trả đúng byte khung đã đặt"


def test_frame_content_type_la_image_jpeg():
    """``Content-Type`` phải là ``image/jpeg`` để ``<Image>`` của RN nhận ra."""
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(_FRAME_A)

    response = client.get("/api/frame")

    assert response.mimetype == "image/jpeg"
    assert response.headers["Content-Type"].startswith("image/jpeg")


def test_frame_co_cache_control_no_store():
    """Ảnh camera là dữ liệu sống: cấm mọi tầng cache giữ lại.

    Thiếu header này, trình duyệt/proxy trả lại khung cũ và người dùng thấy
    hình đứng trong khi số liệu bên cạnh vẫn chạy — lỗi rất khó đoán.
    """
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(_FRAME_A)

    response = client.get("/api/frame")

    assert response.headers.get("Cache-Control") == "no-store"


def test_frame_tra_khung_moi_nhat_sau_khi_thay():
    """Đặt khung mới thì lần gọi sau phải trả khung mới, không phải khung cũ."""
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)

    state.set_frame(_FRAME_A)
    assert client.get("/api/frame").data == _FRAME_A

    state.set_frame(_FRAME_B)
    assert client.get("/api/frame").data == _FRAME_B, "phải là khung mới nhất"


def test_frame_khong_doi_hanh_vi_stream():
    """``/stream`` vẫn trả MJPEG như cũ sau khi thêm ``/api/frame``.

    Thêm route mới không được đổi route cũ — hai route phục vụ hai loại client
    khác nhau và cùng đọc một ``DashboardState``.
    """
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(_FRAME_A)

    response = client.get("/stream", buffered=False)
    try:
        assert response.status_code == 200
        assert response.mimetype == "multipart/x-mixed-replace"
        assert b"khung-mot" in next(iter(response.response))
    finally:
        response.close()


# --------------------------------------------------------------------------
# 2. stream_enabled = False → 403 JSON, cùng câu với /stream
# --------------------------------------------------------------------------


def test_frame_tra_403_khi_stream_tat():
    """Tắt stream thì 403 JSON tiếng Việt, không phải 200 và không phải 500."""
    client = _make_client(stream_enabled=False)

    response = client.get("/api/frame")

    assert response.status_code == 403
    payload = response.get_json()
    assert payload is not None, "phải là JSON, không phải trang HTML lỗi"
    assert payload["ok"] is False
    assert "Tính năng xem trực tiếp đang tắt" in payload["message"]


def test_frame_va_stream_dung_cung_mot_cau_thong_diep():
    """Hai route cùng phục vụ khung hình → phải trả **cùng một câu**.

    Khoá bằng cách so trực tiếp hai message. Nếu ai đó sau này sửa một nhánh mà
    quên nhánh kia, bài này đỏ ngay — thay vì để người dùng đọc hai lời giải
    thích khác nhau cho cùng một cái công tắc.
    """
    client = _make_client(stream_enabled=False)

    frame_msg = client.get("/api/frame").get_json()["message"]
    stream_msg = client.get("/stream").get_json()["message"]

    assert frame_msg == stream_msg
    assert frame_msg == web_app_module.STREAM_DISABLED_MESSAGE


def test_frame_khong_treo_khi_stream_tat():
    """Tắt stream thì phải trả ngay, không chờ hết timeout của ``wait_frame``."""
    import time

    client = _make_client(stream_enabled=False)

    started = time.monotonic()
    client.get("/api/frame")
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, (
        f"không được chờ vô ích khi stream tắt ({elapsed:.2f} s)"
    )


# --------------------------------------------------------------------------
# 3. Chưa có khung → 503 JSON tiếng Việt, không phải 200 rỗng
# --------------------------------------------------------------------------


def test_frame_tra_503_khi_chua_co_khung():
    """Dashboard vừa khởi động, bộ nhớ chưa có khung → 503 JSON, không 200 rỗng.

    Trả 200 với thân rỗng là bẫy tệ nhất cho client: app hiện ô ảnh trắng mà
    không có thông tin gì để phân biệt "chưa có ảnh" với "ảnh hỏng".
    """
    client = _make_client(stream_enabled=True)

    response = client.get("/api/frame")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload is not None, "phải là JSON để app đọc được message"
    assert payload["ok"] is False
    assert "Chưa có khung hình nào" in payload["message"]


def test_frame_503_khong_phai_200_voi_than_rong():
    """Khẳng định trực tiếp điều tệ nhất: không được 200 mà body rỗng."""
    client = _make_client(stream_enabled=True)

    response = client.get("/api/frame")

    assert not (response.status_code == 200 and response.data == b"")


def test_frame_het_thoi_gian_cho_van_tra_503():
    """``wait_frame`` hết hạn mà vẫn không có khung → 503, không treo.

    Gài ``set_frame`` để không bao giờ có khung, rồi đo thời gian: phải xấp xỉ
    ``FRAME_WAIT_S`` (0,5 s) chứ không phải vô hạn. Đây là chốt chống treo
    worker Flask khi app điện thoại gọi lại liên tục.
    """
    import time

    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)

    started = time.monotonic()
    response = client.get("/api/frame")
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert elapsed < web_app_module.FRAME_WAIT_S + 1.5, (
        f"phải bỏ cuộc sau khoảng {web_app_module.FRAME_WAIT_S} s, "
        f"thực tế {elapsed:.2f} s"
    )


def test_hang_so_cho_khung_ngan_hon_stream():
    """``FRAME_WAIT_S`` phải ngắn hơn ``STREAM_WAIT_S``.

    Ảnh rời không cần giữ kết nối lâu như luồng MJPEG. Nếu ai đó nâng
    ``FRAME_WAIT_S`` lên bằng hoặc hơn ``STREAM_WAIT_S``, một request ảnh có
    thể giữ worker Flask tới 2 s — bài này chặn việc đó.
    """
    assert 0.0 < web_app_module.FRAME_WAIT_S < web_app_module.STREAM_WAIT_S


# --------------------------------------------------------------------------
# 4. Route chỉ đọc: không ghi đĩa, không chạm camera
# --------------------------------------------------------------------------


def test_frame_khong_goi_cv2_imwrite(monkeypatch):
    """Gài bẫy ``cv2.imwrite``: gọi ``/api/frame`` không được chạm tới nó.

    spec v2 §11.5: route hiển thị không được lưu ảnh. Gài bẫy thay vì chỉ tin
    vào việc đọc mã — một dòng ``cv2.imwrite`` thêm vào sau này sẽ làm đỏ ngay.
    """
    import cv2

    calls = []
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: calls.append(a))

    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(_FRAME_A)

    assert client.get("/api/frame").status_code == 200
    assert calls == [], "route /api/frame không được gọi cv2.imwrite"


def test_frame_khong_mo_camera(monkeypatch):
    """Route không được dựng ``FrameSource``/mở thiết bị: nó chỉ đọc bộ nhớ.

    Gài bẫy lên ``cv2.VideoCapture`` (đường mở camera của dự án) rồi gọi route
    cả khi có khung lẫn khi chưa có khung — không lần nào được chạm.
    """
    import cv2

    opened = []
    monkeypatch.setattr(
        cv2, "VideoCapture", lambda *a, **k: opened.append(a) or object()
    )

    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)

    # Chưa có khung: route phải trả 503 bằng cách đọc bộ nhớ, không mở camera.
    assert client.get("/api/frame").status_code == 503
    # Có khung: trả ảnh, cũng không mở camera.
    state.set_frame(_FRAME_A)
    assert client.get("/api/frame").status_code == 200

    assert opened == [], "route /api/frame không được mở camera"


def test_frame_khong_tao_tep_moi_trong_thu_muc_lam_viec():
    """Sau khi gọi route, không có tệp mới nào xuất hiện ở gốc repo.

    Đọc danh sách tệp bằng ``os.scandir`` (thao tác đọc) thay vì ``tmp_path``,
    vì sandbox của máy chặn thư mục tạm của pytest. So sánh **tên** tệp ở gốc
    workspace trước/sau — đủ để bắt một lần ``imwrite``/``open(..., "w")`` lọt
    vào đường phục vụ ảnh.
    """
    import os

    before = {entry.name for entry in os.scandir(_REPO_ROOT) if entry.is_file()}

    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(_FRAME_A)
    assert client.get("/api/frame").status_code == 200

    after = {entry.name for entry in os.scandir(_REPO_ROOT) if entry.is_file()}

    assert after == before, f"route không được tạo tệp: {sorted(after - before)}"


# --------------------------------------------------------------------------
# Khung phải là JPEG thật (bắt đầu bằng SOI ``FF D8``)
# --------------------------------------------------------------------------


def test_khung_tra_ve_bat_dau_bang_soi_marker():
    """Byte trả ra phải bắt đầu bằng ``FF D8`` (SOI) — dấu hiệu JPEG.

    Không giải mã ảnh (route cũng không giải mã), chỉ kiểm tra marker để chắc
    rằng thứ được đặt vào ``DashboardState`` và thứ đi ra là cùng một loại dữ
    liệu mà ``<Image>`` của React Native chấp nhận.
    """
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(_FRAME_A)

    data = client.get("/api/frame").data

    assert data[:2] == b"\xff\xd8", "khung phải bắt đầu bằng SOI marker của JPEG"
    assert data[-2:] == b"\xff\xd9", "khung phải kết thúc bằng EOI marker"


@pytest.mark.parametrize("frame", [_FRAME_A, _FRAME_B, b"\xff\xd8x\xff\xd9"])
def test_frame_chuyen_nguyen_ven_moi_do_dai(frame):
    """Không cắt, không nối, không mã hoá lại: độ dài vào == độ dài ra."""
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(frame)

    data = client.get("/api/frame").data

    assert len(data) == len(frame)
    assert data == frame


def test_frame_numpy_buffer_duoc_gui_nguyen_ven():
    """Đặt thẳng ``np.frombuffer`` (không ``.tobytes()``): Flask gửi đúng byte.

    Đây là hành vi **thật** đã đo, không phải giả định: ``flask.Response`` nhận
    đối tượng có buffer protocol và gửi nguyên nội dung, nên một mảng numpy
    ``uint8`` đi ra đúng ``_FRAME_A``. Route **không** kiểm tra kiểu và không
    từ chối — đó là lựa chọn có chủ ý: kiểm tra kiểu thêm ở đây chỉ tạo thêm
    một nhánh lỗi cho dữ liệu mà Flask vốn đã xử lý đúng.

    Điều phải chặn là **repr của mảng** lọt ra client: nếu ai đó sau này gọi
    ``str(frame)`` thay vì truyền thẳng, client sẽ nhận chuỗi ``"[255 216 ...]"``
    và không render được ảnh. Bài này bắt đúng lỗi đó.
    """
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    # Mảng numpy, KHÔNG gọi .tobytes() — để thấy Flask tự chuyển buffer.
    state.set_frame(np.frombuffer(_FRAME_A, dtype=np.uint8))

    response = client.get("/api/frame")

    assert response.status_code == 200
    assert isinstance(response.data, bytes)
    assert response.data == _FRAME_A, "phải đúng byte, không phải repr của mảng"
    assert b"[" not in response.data, "không được đẩy repr mảng ra client"


def test_frame_rong_bang_b_none_van_la_503():
    """``set_frame(b"")`` → 503, không phải 200 với thân rỗng.

    ``b""`` là "chưa có khung" chứ không phải "khung JPEG rỗng" (JPEG thật luôn
    có ít nhất SOI+EOI). Nếu route dùng ``frame is None`` thì ``b""`` lọt qua
    và app nhận 200 với 0 byte — đúng cái bẫy mà ``FRAME_MISSING_MESSAGE`` sinh
    ra để tránh.
    """
    state = DashboardState()
    client = _make_client(stream_enabled=True, state=state)
    state.set_frame(b"")

    response = client.get("/api/frame")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    assert "Chưa có khung hình nào" in payload["message"]

