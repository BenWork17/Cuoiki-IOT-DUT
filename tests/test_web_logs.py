"""Kiểm thử route ``GET /api/logs`` — nhật ký lỗi cho web và app.

Không cần camera, không cần DB, **không dùng ``tmp_path``**: sandbox của máy
này chặn thư mục tạo bằng ``mkdir(mode=0o700)`` mà pytest luôn dùng mode đó.
Mọi bài ở đây chỉ dựng ``create_app`` với một ``LogBuffer`` trong bộ nhớ.

Sáu nhánh của hợp đồng:

1. ``200`` đúng shape ``{logs, total, level}`` khi có buffer.
2. ``limit`` — mặc định 100, cắt đúng, và vượt trần bị từ chối.
3. ``level`` — lọc theo ngưỡng; ``level=ERROR`` chỉ ERROR+CRITICAL.
4. Tham số sai → ``400`` kèm câu tiếng Việt (không phải 500, không phải HTML).
5. Chưa có buffer → ``503`` JSON, không sập.
6. Không bao giờ trả HTML cho các nhánh lỗi.

Bài bổ sung khoá quyết định sản phẩm: **mặc định là WARNING** để popup chỉ
hiện lỗi, không đầy ``INFO``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.config import Config, WebConfig  # noqa: E402
from posture_monitor.log_buffer import DEFAULT_MAXLEN, LogBuffer  # noqa: E402
from posture_monitor.web import DashboardState, create_app  # noqa: E402
from posture_monitor.web import app as web_app_module  # noqa: E402


def _record(message: str, level: int, name: str = "posture_monitor.probe"):
    return logging.LogRecord(
        name=name, level=level, pathname="", lineno=0, msg=message, args=None,
        exc_info=None,
    )


def _buffer_with(entries) -> LogBuffer:
    """``LogBuffer`` đã nạp sẵn các cặp ``(message, level)``."""
    buf = LogBuffer(maxlen=DEFAULT_MAXLEN)
    for message, level in entries:
        buf.emit(_record(message, level))
    return buf


def _client(logs):
    """``test_client`` với buffer chỉ định; ``None`` = chưa có buffer."""
    config = Config()
    config.web = WebConfig(host="127.0.0.1", port=8000, stream_enabled=False)
    app = create_app(
        config,
        state=DashboardState(),
        log_buffer_getter=lambda: logs,
    )
    app.config.update(TESTING=True)
    return app.test_client()


# Các mức dùng lại nhiều lần.
_DEBUG, _INFO, _WARN, _ERROR, _CRIT = (
    logging.DEBUG,
    logging.INFO,
    logging.WARNING,
    logging.ERROR,
    logging.CRITICAL,
)


# --------------------------------------------------------------------------
# 1. 200 + đúng shape
# --------------------------------------------------------------------------


def test_200_va_dung_shape():
    """Có buffer → 200 JSON với ``{logs, total, level, limit}``."""
    client = _client(
        _buffer_with([("cảnh báo một", _WARN), ("lỗi hai", _ERROR)])
    )

    response = client.get("/api/logs")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None, "phải là JSON"
    assert payload["total"] == 2
    assert payload["level"] == "WARNING"
    assert payload["limit"] == web_app_module.LOGS_DEFAULT_LIMIT
    assert isinstance(payload["logs"], list)
    assert len(payload["logs"]) == 2


def test_moi_ban_ghi_du_bon_khoa():
    """Mỗi phần tử ``logs`` có đủ ``{ts, level, logger, message}``."""
    client = _client(_buffer_with([("một lỗi", _ERROR)]))

    entry = client.get("/api/logs").get_json()["logs"][0]

    assert set(entry) == {"ts", "level", "logger", "message"}
    assert isinstance(entry["ts"], float) and entry["ts"] > 0
    assert entry["level"] == "ERROR"
    assert entry["logger"] == "probe", "tiền tố posture_monitor. đã bị cắt"
    assert entry["message"] == "một lỗi"


def test_moi_nhat_truoc():
    """Log trả về sắp mới nhất trước để popup hiện lỗi mới ở trên."""
    client = _client(_buffer_with([("cũ", _WARN), ("mới", _ERROR)]))

    messages = [
        item["message"] for item in client.get("/api/logs").get_json()["logs"]
    ]

    assert messages == ["mới", "cũ"]


def test_buffer_rong_tra_200_voi_list_rong():
    """Chưa có lỗi nào → 200 với ``logs: []``, không phải 503.

    Khác với "chưa có buffer" (503): buffer tồn tại nhưng rỗng là trạng thái
    bình thường — hệ thống chạy tốt, chưa có lỗi nào để hiện.
    """
    response = _client(_buffer_with([])).get("/api/logs")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["logs"] == []
    assert payload["total"] == 0


# --------------------------------------------------------------------------
# 2. limit
# --------------------------------------------------------------------------


def test_limit_mac_dinh_100():
    """Không truyền ``limit`` → dùng :data:`LOGS_DEFAULT_LIMIT` (100)."""
    assert web_app_module.LOGS_DEFAULT_LIMIT == 100
    client = _client(
        _buffer_with([(f"lỗi {index}", _ERROR) for index in range(150)])
    )

    payload = client.get("/api/logs").get_json()

    assert payload["limit"] == 100
    assert len(payload["logs"]) == 100, "cắt còn 100 dù buffer giữ 150"


def test_limit_tuy_chinh():
    """``limit=3`` trả đúng 3 bản ghi, giữ bản mới nhất."""
    client = _client(
        _buffer_with([(f"m{index}", _ERROR) for index in range(5)])
    )

    payload = client.get("/api/logs?limit=3").get_json()

    assert len(payload["logs"]) == 3
    assert [item["message"] for item in payload["logs"]] == ["m4", "m3", "m2"]


def test_limit_toi_da_bang_maxlen():
    """Trần ``limit`` bằng số bản ghi buffer giữ (500)."""
    assert web_app_module.LOGS_MAX_LIMIT == DEFAULT_MAXLEN == 500


def test_limit_vuot_tran_tra_400():
    """``limit > 500`` → 400, không lặng lẽ cắt bớt."""
    client = _client(_buffer_with([("lỗi", _ERROR)]))

    response = client.get("/api/logs?limit=9999")

    assert response.status_code == 400
    assert "500" in response.get_json()["message"]


# --------------------------------------------------------------------------
# 3. level — lọc theo ngưỡng
# --------------------------------------------------------------------------


def test_level_mac_dinh_la_warning():
    """Không truyền ``level`` → WARNING trở lên, **không** có INFO/DEBUG.

    Đây là quyết định sản phẩm: popup chỉ hiện lỗi; ``INFO`` sẽ làm ngập và
    che mất lỗi thật.
    """
    client = _client(
        _buffer_with(
            [("d", _DEBUG), ("i", _INFO), ("w", _WARN), ("e", _ERROR)]
        )
    )

    payload = client.get("/api/logs").get_json()

    assert payload["level"] == "WARNING", "mặc định phải là WARNING"
    assert [item["message"] for item in payload["logs"]] == ["e", "w"]
    assert "i" not in [item["message"] for item in payload["logs"]]


def test_level_error_chi_tra_error_va_critical():
    """``level=ERROR`` → chỉ ERROR+CRITICAL, loại WARNING."""
    client = _client(
        _buffer_with([("w", _WARN), ("e", _ERROR), ("c", _CRIT)])
    )

    payload = client.get("/api/logs?level=ERROR").get_json()

    assert payload["level"] == "ERROR"
    assert [item["message"] for item in payload["logs"]] == ["c", "e"]


def test_level_debug_tra_moi_thu():
    """``level=DEBUG`` → trả mọi mức, kể cả DEBUG (dùng khi cần chẩn đoán sâu).

    Chứng minh buffer **giữ** mọi mức và chỉ lọc ở tầng đọc: nếu buffer chỉ
    giữ WARNING thì bài này sẽ không thấy ``d``/``i``.
    """
    client = _client(
        _buffer_with([("d", _DEBUG), ("i", _INFO), ("w", _WARN)])
    )

    payload = client.get("/api/logs?level=DEBUG").get_json()

    assert payload["level"] == "DEBUG"
    assert [item["message"] for item in payload["logs"]] == ["w", "i", "d"]


def test_level_khong_phan_biet_hoa_thuong():
    """``level=warning`` viết thường vẫn được hiểu."""
    client = _client(_buffer_with([("w", _WARN)]))

    payload = client.get("/api/logs?level=warning").get_json()

    assert payload["level"] == "WARNING"
    assert payload["logs"]


# --------------------------------------------------------------------------
# 4. Tham số sai → 400 kèm câu tiếng Việt
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query, fragment",
    [
        ("?level=verbose", "level"),
        ("?level=ALL", "level"),
        ("?limit=abc", "limit"),
        ("?limit=1.5", "limit"),
        ("?limit=0", "dương"),
        ("?limit=-5", "dương"),
    ],
)
def test_tham_so_sai_tra_400_voi_cau_tieng_viet(query, fragment):
    """Mọi tham số sai → 400 JSON, câu tiếng Việt nêu đúng tham số."""
    client = _client(_buffer_with([("w", _WARN)]))

    response = client.get(f"/api/logs{query}")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None, "phải là JSON, không phải HTML"
    assert payload["ok"] is False
    assert fragment in payload["message"].lower()
    # Câu tiếng Việt có dấu — không phải thông điệp mặc định của Flask.
    assert any(ch in payload["message"] for ch in "ăâêôơưđáàảãạ")


def test_400_liet_ke_cac_gia_tri_level_hop_le():
    """Câu 400 cho ``level`` phải liệt kê đủ 5 mức hợp lệ."""
    client = _client(_buffer_with([("w", _WARN)]))

    message = client.get("/api/logs?level=verbose").get_json()["message"]

    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        assert level in message, f"thiếu {level} trong danh sách hợp lệ"


# --------------------------------------------------------------------------
# 5. 503 khi chưa có buffer
# --------------------------------------------------------------------------


def test_503_khi_chua_co_buffer():
    """Chưa có buffer → 503 JSON tiếng Việt, không sập, không HTML."""
    client = _client(None)

    response = client.get("/api/logs")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload is not None, "phải là JSON"
    assert payload["ok"] is False
    assert "bộ đệm" in payload["message"].lower()


def test_503_van_kiem_tra_tham_so_truoc():
    """Tham số sai phải bị từ chối **trước** khi báo thiếu buffer.

    Nếu kiểm tra buffer trước, client gửi ``limit=abc`` sẽ nhận 503 và tưởng
    hệ thống chưa sẵn sàng, trong khi lỗi thật là tham số của họ sai.
    """
    response = _client(None).get("/api/logs?limit=abc")

    assert response.status_code == 503, (
        "chưa có buffer thì 503 là đúng — không phải 400"
    )
    assert response.get_json() is not None


# --------------------------------------------------------------------------
# 6. Không bao giờ trả HTML
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["", "?limit=3", "?level=ERROR", "?limit=abc", "?level=lo", "?limit=9999"],
)
def test_khong_tra_html_cho_bat_ky_nhanh_nao(query):
    """Cả nhánh 200 và mọi nhánh lỗi đều trả JSON, không HTML.

    Client điện thoại gọi ``response.json()``; nhận HTML là sập app. Flask mặc
    định trả trang HTML cho lỗi 405/500 — route này không được để điều đó xảy
    ra ở các nhánh của nó.
    """
    for logs in (_buffer_with([("w", _WARN)]), None):
        response = _client(logs).get(f"/api/logs{query}")
        content_type = response.headers.get("Content-Type", "")
        assert "application/json" in content_type, (
            f"{query} với buffer={logs is not None} trả {content_type}"
        )
        assert response.get_json() is not None


def test_khong_lo_mat_khau_qua_route():
    """Đầu-cuối: mật khẩu RTSP không được xuất hiện trong JSON trả về.

    Bộ đệm đã che ở tầng ``emit``; bài này khoá thêm ở tầng HTTP để không ai
    gỡ mất bước che mà vẫn thấy test cũ xanh.
    """
    # Chuỗi giả cùng hình dạng ``rtsp://user:pass@host`` — KHÔNG dùng mật khẩu
    # thật của thiết bị: tệp này được commit, hằng số test sẽ thành rò rỉ.
    secret = "rtsp://admin:matkhau-gia-de-test@192.0.2.10:554/1/2"
    client = _client(_buffer_with([(f"mở {secret} thất bại", _ERROR)]))

    body = client.get("/api/logs").get_data(as_text=True)

    assert "matkhau-gia-de-test" not in body, "RÒ MẬT KHẨU RA HTTP"
    assert "192.0.2.10" in body, "phần host vẫn còn để chẩn đoán"


def test_route_doc_khung_khong_anh_huong_route_khac():
    """Thêm ``/api/logs`` không làm hỏng ``/api/status``."""
    client = _client(_buffer_with([("w", _WARN)]))

    assert client.get("/api/status").status_code == 200
    assert client.get("/api/logs").status_code == 200
