"""Unit test cho dashboard web (spec v2 §5.10, §9).

Chạy trên PC, không cần camera: web chỉ đọc từ :class:`DashboardState` trong bộ
nhớ, còn lịch sử đọc từ một DB tạm do :class:`posture_monitor.storage.Storage`
sinh ra. Dùng ``app.test_client()`` nên không cần mở cổng thật.

Kiểm tra ``GET /`` **có nội dung thật**, không chỉ mã 200: assert có chuỗi
tiếng Việt, có thẻ "Trạng thái học" với ba dòng tín hiệu, có khung cho phần
"Người học", và có viewport cho điện thoại. Một trang trắng cũng trả 200 nên
mã trạng thái một mình không chứng minh được gì.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.classifier import ABSENT, GOOD, HEAD_DOWN  # noqa: E402
from posture_monitor.config import (  # noqa: E402
    Config,
    SensorsConfig,
    StorageConfig,
    WebConfig,
)
from posture_monitor.state import (  # noqa: E402
    STATE_ABSENT,
    STATE_BAD,
    STATE_GOOD,
    StateUpdate,
)
from posture_monitor.storage import Storage  # noqa: E402
from posture_monitor.web import DashboardState, create_app  # noqa: E402

BASE_TS = datetime(2026, 10, 10, 8, 0, 0).timestamp()


class FakeClock:
    def __init__(self, now: float = BASE_TS) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


def make_config(db_path: Path, stream_enabled: bool = False) -> Config:
    config = Config()
    config.storage = StorageConfig(db_path=str(db_path), retention_days=30)
    config.web = WebConfig(host="127.0.0.1", port=8000, stream_enabled=stream_enabled)
    config.sensors = SensorsConfig(ultrasonic_enabled=True, min_distance_cm=35.0)
    return config


def make_update(now: float, state: str = STATE_GOOD, score: float = 90.0) -> StateUpdate:
    labels = frozenset({GOOD}) if state == STATE_GOOD else frozenset({HEAD_DOWN})
    if state == STATE_ABSENT:
        labels = frozenset({ABSENT})
    return StateUpdate(
        now=now,
        state=state,
        labels=labels,
        score=score,
        sitting_s=max(0.0, now - BASE_TS),
        events=(),
        alerts=(),
    )


@pytest.fixture()
def state() -> DashboardState:
    return DashboardState(clock=FakeClock())


@pytest.fixture()
def storage(tmp_path):
    """DB tạm kèm đồng hồ riêng để test tự nhích thời gian."""
    clock = FakeClock()
    store = Storage(
        StorageConfig(db_path=str(tmp_path / "posture.db")), clock=clock
    )
    store.open()
    yield store
    store.close()


def make_client(config, state, storage=None):
    app = create_app(config, state=state, storage=storage)
    app.config.update(TESTING=True)
    return app.test_client()


# ---------------------------------------------------------------------------
# DashboardState
# ---------------------------------------------------------------------------


def test_dashboard_state_mac_dinh(state):
    snapshot = state.snapshot()
    assert snapshot["state"] == "ABSENT"
    assert snapshot["state_text"] == "Không thấy người"
    assert snapshot["muted"] is False
    assert snapshot["stale"] is True, "chưa có cập nhật nào thì phải coi là cũ"


def test_dashboard_state_update_va_snapshot(state):
    state.update(
        state="GOOD",
        labels=["GOOD"],
        score=97.5,
        sitting_s=125.0,
        distance_cm=48.3,
    )
    snapshot = state.snapshot()
    assert snapshot["state"] == "GOOD"
    assert snapshot["state_text"] == "Tư thế tốt"
    assert snapshot["label_texts"] == ["Đúng tư thế"]
    assert snapshot["score"] == 97.5
    assert snapshot["sitting_s"] == 125.0
    assert snapshot["distance_cm"] == 48.3
    assert snapshot["stale"] is False
    assert snapshot["data_age_s"] == pytest.approx(0.0)


def test_dashboard_state_bo_qua_truong_la(state):
    state.update({"state": "BAD", "khong_ton_tai": 1})
    snapshot = state.snapshot()
    assert snapshot["state"] == "BAD"
    assert "khong_ton_tai" not in snapshot


def test_dashboard_state_nhan_tieng_viet_theo_thu_tu(state):
    state.update(state="BAD", labels=["LEAN", "HEAD_DOWN", "GOOD"])
    snapshot = state.snapshot()
    # Thứ tự theo LABEL_ORDER của classifier, không theo thứ tự đẩy vào.
    assert snapshot["label_texts"] == ["Cúi đầu", "Ngả người", "Đúng tư thế"]


def test_dashboard_state_stale_sau_khi_ngung_cap_nhat(state):
    clock = state._clock
    state.update(state="GOOD", labels=["GOOD"])
    clock.advance(30)
    snapshot = state.snapshot()
    assert snapshot["stale"] is True
    assert snapshot["data_age_s"] == pytest.approx(30.0)


def test_mute_toggle_va_dat_truc_tiep(state):
    assert state.muted is False
    assert state.toggle_mute() is True
    assert state.muted is True
    assert state.set_muted(False) is False
    assert state.muted is False


def test_co_hieu_chinh_chi_doc_mot_lan(state):
    assert state.consume_calibration_request() is False
    state.request_calibration()
    assert state.snapshot()["calibration_pending"] is True
    assert state.consume_calibration_request() is True
    # Đọc lần hai phải là False, nếu không vòng lặp sẽ hiệu chỉnh mãi.
    assert state.consume_calibration_request() is False
    assert state.snapshot()["calibration_pending"] is False


def test_frame_va_wait_frame(state):
    seq, frame = state.latest_frame()
    assert (seq, frame) == (0, None)
    state.set_frame(b"jpeg-bytes")
    seq2, frame2 = state.wait_frame(seq, timeout=0.1)
    assert seq2 > seq
    assert frame2 == b"jpeg-bytes"


def test_wait_frame_het_gio_khong_treo(state):
    seq, _ = state.latest_frame()
    new_seq, frame = state.wait_frame(seq, timeout=0.05)
    assert new_seq == seq
    assert frame is None


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


def test_trang_chu_la_html_tieng_viet_co_the_trang_thai_hoc(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    response = client.get("/")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    html = response.get_data(as_text=True)

    # 1) Có nội dung tiếng Việt thật, không phải trang trắng.
    for text in (
        "Giám sát tư thế học tập",
        "Trạng thái học",
        "Có mặt",
        "Điện thoại",
        "Danh tính",
        "Người học",
        "Tắt tiếng cảnh báo",
        "Hiệu chỉnh lại",
    ):
        assert text in html, f"thiếu chuỗi tiếng Việt: {text}"

    # 2) Đề tài đã bỏ nhận diện tư thế: không còn biểu đồ tư thế trên trang.
    assert "<canvas" not in html and 'id="chart"' not in html

    # 3) Dùng được trên điện thoại.
    assert 'name="viewport"' in html
    assert "width=device-width" in html

    # 4) Không nạp gì từ Internet.
    assert "cdn" not in html.lower()
    assert "http://" not in html and "https://" not in html


def test_trang_chu_hien_khung_cho_ba_tin_hieu_trang_thai_hoc(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    state.update(state="BAD", labels=["HEAD_DOWN"], score=42.0, sitting_s=3725)
    html = client.get("/").get_data(as_text=True)
    # Dữ liệu tín hiệu đi qua JS, nhưng khung hiển thị phải có sẵn chỗ điền.
    for kind in ("presence", "phone", "identity"):
        assert f'id="sign-{kind}"' in html, kind
        assert f'id="sign-{kind}-text"' in html, kind
        assert f'id="sign-{kind}-age"' in html, kind


def test_chart_js_ton_tai_trong_static_va_la_ban_that(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    response = client.get("/static/chart.umd.min.js")
    assert response.status_code == 200
    body = response.get_data()
    assert len(body) > 100_000, "Chart.js thật phải có kích thước đáng kể"
    assert b"Chart.js v4" in body


def test_css_va_js_cuc_bo_ton_tai(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    for name in ("style.css", "app.js"):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200, name
        assert response.get_data()


def test_chu_chua_co_so_lieu_khong_de_len_bieu_do(tmp_path, state):
    """``.chart-empty`` đặt ``display: grid`` nên đè ``[hidden]`` của trình duyệt.

    Thiếu rule ``[hidden]`` thì dòng "Chưa có số liệu." vẽ đè lên cột biểu đồ
    dù phần tử có thuộc tính ``hidden`` (đã thấy thật trên trình duyệt).
    """
    client = make_client(make_config(tmp_path / "p.db"), state)
    css = client.get("/static/style.css").get_data(as_text=True)
    assert ".chart-empty[hidden]" in css
    assert "display: none" in css.split(".chart-empty[hidden]", 1)[1][:80]


def test_bieu_tuong_nhung_khong_goi_mang_ngoai(tmp_path, state):
    """Favicon phải là ``data:`` URI: không có Internet và không 404 mỗi lần tải."""
    client = make_client(make_config(tmp_path / "p.db"), state)
    html = client.get("/").get_data(as_text=True)
    assert 'rel="icon"' in html
    assert "data:image/png;base64," in html
    # Chart.js không được kéo theo bản đồ nguồn (sẽ 404 vì không có file .map).
    chart = client.get("/static/chart.umd.min.js").get_data()
    assert b"sourceMappingURL" not in chart


# ---------------------------------------------------------------------------
# API trạng thái
# ---------------------------------------------------------------------------


def test_api_status(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    state.update(
        state="GOOD",
        labels=["GOOD"],
        score=88.0,
        sitting_s=600.0,
        distance_cm=44.0,
    )
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["state"] == "GOOD"
    assert payload["state_text"] == "Tư thế tốt"
    assert payload["score"] == 88.0
    assert payload["sitting_s"] == 600.0
    assert payload["distance_cm"] == 44.0
    assert payload["stream_enabled"] is False
    assert payload["min_distance_cm"] == 35.0
    assert payload["muted"] is False


def test_api_status_khi_vang_mat(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    state.update(state="ABSENT", labels=["ABSENT"], score=0.0)
    payload = client.get("/api/status").get_json()
    assert payload["state_text"] == "Không thấy người"
    assert payload["label_texts"] == ["Vắng mặt"]


# ---------------------------------------------------------------------------
# API lịch sử
# ---------------------------------------------------------------------------


def test_api_history_today_va_7d(tmp_path, state, storage):
    storage.record(make_update(BASE_TS, score=90.0))
    storage._clock.advance(5)
    storage.record(make_update(BASE_TS + 5, score=90.0))
    storage.flush()
    client = make_client(make_config(tmp_path / "p.db"), state, storage)

    today = client.get("/api/history?range=today").get_json()
    assert today["unit"] == "hour"
    assert today["labels"]
    assert "08:00" in today["labels"]
    assert len(today["labels"]) == len(today["good_pct"])

    week = client.get("/api/history?range=7d").get_json()
    assert week["unit"] == "day"
    assert len(week["labels"]) == 7


def test_api_history_mac_dinh_la_today(tmp_path, state, storage):
    client = make_client(make_config(tmp_path / "p.db"), state, storage)
    assert client.get("/api/history").get_json()["range"] == "today"


def test_api_history_range_sai_tra_400(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    response = client.get("/api/history?range=nam")
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "range" in payload["message"]


def test_api_history_khi_khong_co_storage(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state, storage=None)
    response = client.get("/api/history?range=today")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["has_data"] is False
    assert payload["labels"] == []


def test_api_history_khi_storage_loi_tra_503(tmp_path, state):
    class Hỏng:
        def history(self, range_key):
            raise RuntimeError("DB hỏng")

    client = make_client(make_config(tmp_path / "p.db"), state, Hỏng())
    response = client.get("/api/history?range=today")
    assert response.status_code == 503
    assert response.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Lệnh từ web xuống vòng lặp
# ---------------------------------------------------------------------------


def test_api_mute_dao_trang_thai(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    first = client.post("/api/mute").get_json()
    assert first["ok"] is True
    assert first["muted"] is True
    assert "tắt tiếng" in first["message"].lower()
    assert state.muted is True

    second = client.post("/api/mute").get_json()
    assert second["muted"] is False
    assert state.muted is False


def test_api_mute_dat_gia_tri_tuong_minh(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    assert client.post("/api/mute", json={"muted": True}).get_json()["muted"] is True
    assert state.muted is True
    # Gửi lại cùng giá trị phải giữ nguyên, không đảo.
    assert client.post("/api/mute", json={"muted": True}).get_json()["muted"] is True
    assert client.post("/api/mute", json={"muted": False}).get_json()["muted"] is False


def test_api_calibrate_dat_co_cho_vong_lap(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    response = client.post("/api/calibrate")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["calibration_pending"] is True
    assert "hiệu chỉnh" in payload["message"].lower()

    # Vòng lặp chính đọc được cờ này.
    assert state.consume_calibration_request() is True


# ---------------------------------------------------------------------------
# /stream
# ---------------------------------------------------------------------------


def test_stream_tat_mac_dinh_tu_choi_sach(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db", stream_enabled=False), state)
    response = client.get("/stream")
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["ok"] is False
    assert "stream_enabled" in payload["message"]
    # Thông báo phải là tiếng Việt có dấu và nêu cách bật.
    assert "Tính năng xem trực tiếp đang tắt" in payload["message"]


def test_stream_khong_treo_khi_tat(tmp_path, state):
    """Nếu route quay vòng vô hạn thì test này treo — phải trả ngay."""
    client = make_client(make_config(tmp_path / "p.db", stream_enabled=False), state)
    started = datetime.now()
    client.get("/stream")
    assert (datetime.now() - started).total_seconds() < 2.0


def test_stream_bat_tra_mjpeg(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db", stream_enabled=True), state)
    state.set_frame(b"\xff\xd8jpegdata")
    response = client.get("/stream", buffered=False)
    assert response.status_code == 200
    assert response.mimetype == "multipart/x-mixed-replace"
    chunk = next(iter(response.response))
    assert b"Content-Type: image/jpeg" in chunk
    assert b"jpegdata" in chunk
    response.close()


def test_stream_bat_nhung_chua_co_khung_bao_ro(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db", stream_enabled=True), state)
    response = client.get("/stream", buffered=False)
    chunk = next(iter(response.response))
    assert "Chưa có khung hình".encode("utf-8") in chunk
    response.close()


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------


def test_web_doc_cau_hinh_stream_va_khoang_cach(tmp_path, state):
    config = make_config(tmp_path / "p.db", stream_enabled=True)
    config.sensors.min_distance_cm = 50.0
    client = make_client(config, state)
    payload = client.get("/api/status").get_json()
    assert payload["stream_enabled"] is True
    assert payload["min_distance_cm"] == 50.0


def test_trang_chu_an_nut_stream_chua_bat(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db"), state)
    html = client.get("/").get_data(as_text=True)
    assert 'data-stream-enabled="0"' in html


def test_trang_chu_hien_camera_khi_bat_stream(tmp_path, state):
    """Bật stream thì trang chủ phải có thẻ <img> trỏ tới /stream.

    Kiểm tra nội dung thật, không chỉ mã 200: một trang 200 mà không có thẻ
    ảnh thì người dùng vẫn không thấy camera.
    """
    client = make_client(make_config(tmp_path / "p.db", stream_enabled=True), state)
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-stream-enabled="1"' in html
    assert 'id="camera-stream"' in html
    assert 'src="/stream"' in html
    # Có lời nhắn dự phòng tiếng Việt cho lúc chưa có hình/mất kết nối.
    assert 'id="camera-note"' in html


def test_trang_chu_khong_co_anh_khi_stream_tat(tmp_path, state):
    client = make_client(make_config(tmp_path / "p.db", stream_enabled=False), state)
    html = client.get("/").get_data(as_text=True)
    assert 'id="camera-stream"' not in html
    assert "Xem trực tiếp đang tắt" in html


def test_stream_mat_camera_giua_chung_khong_sap(tmp_path, state, monkeypatch):
    """Camera đứt giữa luồng: /stream trả placeholder thay vì lặp khung cũ.

    Đọc có giới hạn thời gian: nếu bản sửa bị gỡ (lặp lại khung cuối mãi
    mãi), khung thứ hai không bao giờ tới và test đỏ bằng assertion thay vì
    treo cả lượt chạy.
    """
    import threading

    from posture_monitor.web import app as web_app

    monkeypatch.setattr(web_app, "STREAM_POLL_S", 0.01)

    client = make_client(make_config(tmp_path / "p.db", stream_enabled=True), state)
    state.set_frame(b"\xff\xd8khungcu")
    response = client.get("/stream", buffered=False)
    chunks = iter(response.response)
    assert b"khungcu" in next(chunks)

    # Vòng lặp chính đã chết: chỉ còn khung cũ, không có khung mới.
    box = {}

    def _read_next():
        try:
            box["chunk"] = next(chunks)
        except Exception as exc:  # noqa: BLE001 - chuyển nguyên nhân cho assert
            box["error"] = exc

    reader = threading.Thread(target=_read_next, daemon=True)
    reader.start()
    # Chờ tối đa 6 giây — STREAM_WAIT_S mặc định là 2 giây, dư thoải mái.
    reader.join(timeout=6.0)
    response.close()

    assert not reader.is_alive(), (
        "/stream treo khi không có khung mới — camera đứt phải có placeholder"
    )
    assert "error" not in box, f"luồng stream ném lỗi: {box.get('error')!r}"
    assert "Chưa có khung hình".encode("utf-8") in box["chunk"]


def test_stream_khong_ghi_anh_ra_dia(tmp_path, state, monkeypatch):
    """Luồng stream chỉ đẩy byte qua bộ nhớ: không có đường ghi ảnh.

    Chứng minh bằng ba lớp, không phải bằng chú thích:

    1. Gài bẫy lên ``cv2.imwrite`` — mọi lời gọi bị ghi lại.
    2. Chạy cả ``/stream`` trong thư mục làm việc tạm và soát **mọi** file
       mới sinh (kể cả ``data/``), không chỉ ``tmp_path``.
    3. Đặt khung thật và khẳng định byte đi ra nguyên vẹn, để test không
       xanh nhờ không có gì chạy cả.
    """
    import cv2

    calls = []
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: calls.append(a))
    monkeypatch.chdir(tmp_path)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    client = make_client(make_config(tmp_path / "p.db", stream_enabled=True), state)
    state.set_frame(b"\xff\xd8khongluu")
    response = client.get("/stream", buffered=False)
    chunk = next(iter(response.response))
    response.close()

    assert b"khongluu" in chunk, "phải nhận được đúng khung đã đặt"
    assert calls == [], "đường stream không được gọi cv2.imwrite"
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    new_files = sorted(after - before)
    assert new_files == [], f"stream không được ghi file: {new_files}"


def test_config_repo_bat_stream_mac_dinh():
    """``config.yaml`` trong repo phải bật stream: web hiển thị camera là
    chức năng chính, không phải tuỳ chọn.

    Đọc thẳng file được commit (không phải ``WebConfig`` mặc định trong mã):
    chính cái người dùng nạp lúc chạy mới là thứ quyết định.
    """
    from posture_monitor.config import load_config

    config = load_config(_REPO_ROOT / "config.yaml")
    assert config.web.stream_enabled is True
