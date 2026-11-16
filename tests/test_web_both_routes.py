"""Hai route nhật ký CÙNG SỐNG trong một ``create_app`` — kiểm bằng chạy thật.

Vì sao cần tệp này
==================
``tests/test_web_logs.py`` và ``tests/test_web_violations.py`` đều xanh, nhưng
mỗi tệp dựng ``create_app`` **một mình** với đúng một nguồn dữ liệu. Chưa có
bài nào chứng minh hai route đó chạy được **cùng lúc** trong một app thật — mà
đó chính là cách hệ thống chạy: ``run`` truyền cả ``storage`` lẫn logging có
buffer vào một ``create_app`` duy nhất.

Hai rủi ro cụ thể mà chỉ test tích hợp mới bắt được:

1. **Giẫm lên nhau.** ``/api/logs`` đọc bộ đệm RAM, ``/api/violations`` đọc
   bảng ``events`` trong SQLite. Nếu một ngày ai đó cho ``/api/logs`` đọc nhầm
   ``storage`` (hoặc ngược lại), hai tệp test đơn lẻ vẫn có thể xanh vì mỗi tệp
   chỉ có một nguồn. Bài dưới khẳng định **nội dung** hai bên khác nhau trên
   cùng một app, không chỉ mã trạng thái.

2. **Tham số trùng tên nhưng khác nghĩa.** Cả hai route đều nhận ``limit``
   nhưng với trần khác nhau (500 vs 500 — nhưng là hai hằng riêng) và
   ``/api/violations`` còn nhận ``kinds``/``since_s`` mà ``/api/logs`` không
   biết. Gọi lẫn tham số không được làm route kia hiểu sai.

Còn một việc nữa: xác nhận **độc lập** rằng ba mã vi phạm trong
``storage.VIOLATION_KIND_CODES`` trùng **giá trị** với hằng của ``state``. Bài
này đã có trong ``test_web_violations.py``, nhưng người viết yêu cầu kiểm lại
từ một chỗ thứ hai — nếu một lần ai đó sửa một bên, hai bài cùng đỏ thì rõ hơn
một bài.

Không dùng fixture ``tmp_path``: sandbox chặn ``mkdir(mode=0o700)``. Dùng
``_Scratch`` như ``tests/test_calibrate_reacquire.py``.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.config import StorageConfig  # noqa: E402
from posture_monitor.log_buffer import LogBuffer  # noqa: E402
from posture_monitor.state import (  # noqa: E402
    EVENT_ABSENT,
    EVENT_IMPOSTOR,
    EVENT_PHONE_USE,
    Event,
)
from posture_monitor.storage import (  # noqa: E402
    VIOLATION_KIND_CODES,
    Storage,
)
from posture_monitor.web.app import (  # noqa: E402
    VIOLATION_KINDS,
    VIOLATIONS_DEFAULT_LIMIT,
    create_app,
)


class _Scratch:
    """Thư mục tạm tự quản trong ``.scratch/``, không dùng ``tmp_path``."""

    def __init__(self, name: str) -> None:
        self.path = _REPO_ROOT / ".scratch" / f"bothroutes_test_{name}"

    def __enter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        for stale in self.path.glob("*.db*"):
            try:
                stale.unlink()
            except OSError:  # pragma: no cover - phòng vệ
                pass
        return self.path

    def __exit__(self, *exc_info) -> None:
        for item in self.path.glob("*"):
            try:
                item.unlink()
            except OSError:  # pragma: no cover - phòng vệ
                pass
        try:
            self.path.rmdir()
        except OSError:  # pragma: no cover - phòng vệ
            pass


#: Câu dùng làm "log chẩn đoán" — cố ý khác hẳn nội dung vi phạm để nếu hai
#: route lẫn nhau thì assert phân biệt được ngay.
_LOG_MESSAGE = "Không mở được camera USB sau 3 lần thử"

#: Bản ghi log dùng chung cho các bài dưới.
_LOG_LEVEL = logging.ERROR

#: Thời điểm gốc cho các sự kiện vi phạm.
_BASE_TS = time.time() - 60.0


def _buffer_with_log() -> LogBuffer:
    """Bộ đệm đã có **một** dòng lỗi (mức ERROR)."""
    buf = LogBuffer(maxlen=50)
    buf.emit(
        logging.LogRecord(
            name="posture_monitor.capture",
            level=_LOG_LEVEL,
            pathname="",
            lineno=0,
            msg=_LOG_MESSAGE,
            args=None,
            exc_info=None,
        )
    )
    return buf


def _storage_with_violations(directory: Path) -> Storage:
    """Storage đã mở, có đúng **một** dòng cho mỗi loại vi phạm."""
    store = Storage(StorageConfig(db_path=str(directory / "both.db")))
    store.open()
    for index, code in enumerate(VIOLATION_KIND_CODES):
        moment = _BASE_TS + index
        store.record_event(
            Event(
                ts=moment,
                type=code,
                label="x",
                duration_s=12.0 + index,
                alert=True,
            ),
            now=moment,
        )
    store.flush()
    return store


class _BothRoutes:
    """App có **cả** storage lẫn log buffer — như ``run`` thật dựng.

    Giữ cả hai nguồn trong một ``create_app`` là điểm mấu chốt của tệp này:
    hai tệp test kia mỗi tệp chỉ tiêm một nguồn.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.logs = _buffer_with_log()
        self.storage = _storage_with_violations(directory)
        self.app = create_app(
            storage=self.storage,
            log_buffer_getter=lambda: self.logs,
        )
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def close(self) -> None:
        self.storage.close()

    def __enter__(self) -> "_BothRoutes":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 1. Hai route cùng sống, không giẫm lên nhau
# ---------------------------------------------------------------------------


def test_hai_route_cung_tra_200_tren_cung_mot_app():
    """``/api/logs`` và ``/api/violations`` đều 200 trong **một** app.

    Đây là điều chưa từng được kiểm: hai tệp test cũ mỗi tệp dựng app riêng.
    """
    with _Scratch("both200") as directory, _BothRoutes(directory) as both:
        logs = both.client.get("/api/logs")
        violations = both.client.get("/api/violations")

        assert logs.status_code == 200, logs.get_data(as_text=True)[:200]
        assert violations.status_code == 200, (
            violations.get_data(as_text=True)[:200]
        )


def test_violations_khong_tra_log_va_logs_khong_tra_vi_pham():
    """Nội dung hai route **khác hẳn** nhau — không route nào trả dữ liệu kia.

    Không chỉ so mã trạng thái: nếu một ngày ``/api/logs`` bị sửa để đọc nhầm
    ``storage``, bài này đỏ vì thấy chuỗi vi phạm trong khung ``logs``.
    """
    with _Scratch("distinct") as directory, _BothRoutes(directory) as both:
        logs_payload = both.client.get("/api/logs").get_json()
        violations_payload = both.client.get("/api/violations").get_json()

        # --- /api/logs: đúng hình dạng của log, không có khoá của vi phạm.
        assert set(logs_payload) == {"logs", "total", "level", "limit"}
        assert "violations" not in logs_payload
        assert "counts" not in logs_payload
        assert logs_payload["logs"], "phải có ít nhất một dòng log"
        assert all(
            set(entry) == {"ts", "level", "logger", "message"}
            for entry in logs_payload["logs"]
        )
        # Nội dung log KHÔNG được chứa mã vi phạm như một trường.
        assert all("kind" not in entry for entry in logs_payload["logs"])

        # --- /api/violations: đúng hình dạng của vi phạm, không có khoá log.
        assert set(violations_payload) == {
            "violations",
            "total",
            "counts",
            "limit",
        }
        assert "logs" not in violations_payload
        assert "level" not in violations_payload
        assert violations_payload["violations"], "phải có vi phạm"
        assert all(
            set(entry) == {"ts", "kind", "kind_text", "duration_s"}
            for entry in violations_payload["violations"]
        )
        # Nội dung vi phạm KHÔNG được chứa trường của log.
        assert all(
            "message" not in entry and "logger" not in entry
            for entry in violations_payload["violations"]
        )


def test_cau_log_khong_lot_vao_danh_sach_vi_pham():
    """Chuỗi của bản ghi log không được có trong thân ``/api/violations``."""
    with _Scratch("nolog") as directory, _BothRoutes(directory) as both:
        body = both.client.get("/api/violations").get_data(as_text=True)

        assert _LOG_MESSAGE not in body, "log chẩn đoán lọt vào lịch sử vi phạm"


def test_ma_vi_pham_khong_lot_vao_danh_sach_log():
    """Chiều ngược lại: mã vi phạm không được xuất hiện trong ``/api/logs``."""
    with _Scratch("noviolation") as directory, _BothRoutes(directory) as both:
        payload = both.client.get("/api/logs").get_json()
        messages = " ".join(entry["message"] for entry in payload["logs"])

        for code in VIOLATION_KINDS:
            assert code not in messages, (
                f"mã vi phạm {code} lọt vào log"
            )


def test_goi_lien_tiep_khong_lam_doi_trang_thai_route_kia():
    """Gọi route này rồi route kia (và lặp lại) vẫn cho cùng kết quả.

    Chốt chống tác dụng phụ: ``/api/logs`` không được xoá buffer, và
    ``/api/violations`` không được tiêu thụ hàng đợi của storage.
    """
    with _Scratch("idempotent") as directory, _BothRoutes(directory) as both:
        first_logs = both.client.get("/api/logs").get_json()
        first_violations = both.client.get("/api/violations").get_json()

        # Gọi chéo vài lượt.
        both.client.get("/api/violations")
        both.client.get("/api/logs")
        both.client.get("/api/violations")

        second_logs = both.client.get("/api/logs").get_json()
        second_violations = both.client.get("/api/violations").get_json()

        assert second_logs["total"] == first_logs["total"]
        assert second_logs["logs"] == first_logs["logs"]
        assert second_violations["total"] == first_violations["total"]
        assert second_violations["violations"] == first_violations["violations"]


def test_tham_so_rieng_cua_route_nay_khong_lam_hong_route_kia():
    """``kinds``/``since_s`` chỉ ``/api/violations`` hiểu; ``level`` chỉ logs.

    Gửi tham số lạ cho route kia không được làm nó đổi hành vi hay trả lỗi —
    cả hai đều bỏ qua tham số không biết, đúng như Flask mặc định. Điều phải
    khoá là chúng **không** dùng chung một hàm phân tích tham số.
    """
    with _Scratch("params") as directory, _BothRoutes(directory) as both:
        # ``kinds`` là tham số của violations; ``/api/logs`` phải bỏ qua.
        logs_with_foreign = both.client.get(
            "/api/logs?kinds=ABSENT"
        )
        assert logs_with_foreign.status_code == 200
        assert logs_with_foreign.get_json()["level"] == "WARNING"

        # ``level`` là tham số của logs; ``/api/violations`` phải bỏ qua.
        violations_with_foreign = both.client.get(
            "/api/violations?level=DEBUG"
        )
        assert violations_with_foreign.status_code == 200
        assert "level" not in violations_with_foreign.get_json()


def test_moi_route_bao_loi_rieng_cua_minh():
    """Tham số sai của route này trả 400 của route này, không lẫn thông điệp.

    ``/api/logs?level=lo`` nói về ``level``; ``/api/violations?kinds=lo`` nói
    về ``kinds``. Nếu hai route dùng chung một bộ phân tích, thông điệp sẽ lẫn.
    """
    with _Scratch("errors") as directory, _BothRoutes(directory) as both:
        logs_error = both.client.get("/api/logs?level=lo")
        violations_error = both.client.get("/api/violations?kinds=lo")

        assert logs_error.status_code == 400
        assert violations_error.status_code == 400
        assert "'level'" in logs_error.get_json()["message"]
        assert "'kinds'" in violations_error.get_json()["message"]
        # Không lẫn: thông điệp của route này không nhắc tham số của route kia.
        assert "kinds" not in logs_error.get_json()["message"].lower()
        assert "level" not in violations_error.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# 2. /api/violations với dữ liệu THẬT từ record_event
# ---------------------------------------------------------------------------


def test_violations_doc_dung_du_lieu_record_event_ghi_ra():
    """Dữ liệu vào bằng ``record_event`` (đường thật) đọc ra đúng từng dòng.

    Đây là đường người dùng thật đi: ``storage.record_event`` → ``flush`` →
    ``/api/violations``. Không dựng DB bằng tay, không chèn SQL trực tiếp.
    """
    with _Scratch("realevents") as directory, _BothRoutes(directory) as both:
        payload = both.client.get("/api/violations").get_json()

        assert payload["total"] == len(VIOLATION_KIND_CODES)

        # Mới nhất trước (thứ tự do storage quyết định, ts tăng dần khi ghi).
        kinds = [entry["kind"] for entry in payload["violations"]]
        assert kinds == list(reversed(VIOLATION_KIND_CODES))

        # ``duration_s`` đúng giá trị đã ghi (12, 13, 14 theo thứ tự index).
        by_kind = {entry["kind"]: entry for entry in payload["violations"]}
        for index, code in enumerate(VIOLATION_KIND_CODES):
            expected = 12.0 + index
            assert by_kind[code]["duration_s"] == pytest.approx(expected)

        # ``ts`` là mốc đã ghi, không phải "bây giờ".
        assert all(entry["ts"] < time.time() for entry in payload["violations"])
        assert min(entry["ts"] for entry in payload["violations"]) >= _BASE_TS

        # ``counts`` đếm đúng từng loại.
        assert payload["counts"] == {code: 1 for code in VIOLATION_KINDS}


def test_violations_loc_theo_kinds_voi_du_lieu_that():
    """``kinds`` lọc đúng trên dữ liệu do ``record_event`` ghi."""
    with _Scratch("realkinds") as directory, _BothRoutes(directory) as both:
        payload = both.client.get(
            f"/api/violations?kinds={EVENT_ABSENT}"
        ).get_json()

        assert payload["total"] == 1
        assert [entry["kind"] for entry in payload["violations"]] == [
            EVENT_ABSENT
        ]
        # ``counts`` vẫn liệt kê đủ ba khoá, hai khoá còn lại bằng 0 — client
        # không phải tự bù khoá thiếu.
        assert payload["counts"] == {
            EVENT_ABSENT: 1,
            EVENT_PHONE_USE: 0,
            EVENT_IMPOSTOR: 0,
        }


def test_violations_kind_text_tieng_viet_cho_du_lieu_that():
    """Mỗi dòng có ``kind_text`` tiếng Việt, không rơi về mã thô."""
    with _Scratch("realtext") as directory, _BothRoutes(directory) as both:
        for entry in both.client.get("/api/violations").get_json()["violations"]:
            assert entry["kind_text"].strip() != ""
            assert entry["kind_text"] != entry["kind"], (
                f"{entry['kind']} chưa có nhãn tiếng Việt"
            )


def test_violations_since_s_loai_du_lieu_cu():
    """``since_s`` nhỏ hơn tuổi dữ liệu → không còn dòng nào.

    Dữ liệu được ghi ở ``_BASE_TS`` (60 giây trước). Hỏi "10 giây gần nhất"
    thì phải rỗng; hỏi "10 000 giây gần nhất" thì phải thấy hết.
    """
    with _Scratch("realsince") as directory, _BothRoutes(directory) as both:
        recent = both.client.get("/api/violations?since_s=10").get_json()
        wide = both.client.get("/api/violations?since_s=10000").get_json()

        assert recent["total"] == 0, "dữ liệu 60 s trước không nằm trong 10 s"
        assert wide["total"] == len(VIOLATION_KIND_CODES)


def test_logs_van_doc_duoc_khi_storage_co_du_lieu():
    """Chiều ngược lại: storage có dữ liệu không làm ``/api/logs`` đọc sai."""
    with _Scratch("logsbeside") as directory, _BothRoutes(directory) as both:
        payload = both.client.get("/api/logs").get_json()

        assert payload["total"] == 1
        assert payload["logs"][0]["message"] == _LOG_MESSAGE
        assert payload["logs"][0]["level"] == "ERROR"
        assert payload["logs"][0]["logger"] == "capture"


# ---------------------------------------------------------------------------
# 3. Mã vi phạm trùng giá trị với hằng của state — xác nhận độc lập
# ---------------------------------------------------------------------------


def test_ma_vi_pham_trung_gia_tri_hang_state():
    """``storage.VIOLATION_KIND_CODES`` trùng **giá trị** hằng của ``state``.

    Kiểm lại lần thứ hai (lần đầu ở ``test_web_violations.py``) theo yêu cầu
    của người viết: nếu một lần ai đó sửa một bên, cả hai bài cùng đỏ thì
    nguyên nhân rõ hơn là một bài.
    """
    assert set(VIOLATION_KIND_CODES) == {
        EVENT_ABSENT,
        EVENT_PHONE_USE,
        EVENT_IMPOSTOR,
    }


def test_ma_vi_pham_trung_giua_storage_va_web():
    """``web.VIOLATION_KINDS`` và ``storage.VIOLATION_KIND_CODES`` cùng thứ tự.

    Trùng cả **thứ tự** chứ không chỉ tập hợp: route dùng thứ tự này để liệt kê
    trong câu 400, và ``counts`` được tạo theo nó.
    """
    assert tuple(VIOLATION_KINDS) == tuple(VIOLATION_KIND_CODES)


def test_moi_hang_state_khop_dung_mot_ma_trong_storage():
    """Ánh xạ một-một: mỗi hằng ``state`` ứng đúng một mã, không thừa thiếu."""
    from_state = {EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR}

    assert len(from_state) == len(VIOLATION_KIND_CODES) == 3
    assert from_state == set(VIOLATION_KIND_CODES)


# ---------------------------------------------------------------------------
# Giới hạn chung của hai route
# ---------------------------------------------------------------------------


def test_limit_mac_dinh_cua_hai_route_doc_lap():
    """Hai route có hằng ``limit`` riêng; mặc định mỗi bên áp đúng của mình.

    ``/api/logs`` trả thêm khoá ``limit`` nên đọc được trực tiếp;
    ``/api/violations`` cũng vậy. Không bên nào dùng hằng của bên kia.
    """
    with _Scratch("limits") as directory, _BothRoutes(directory) as both:
        logs_payload = both.client.get("/api/logs").get_json()
        violations_payload = both.client.get("/api/violations").get_json()

        assert logs_payload["limit"] > 0
        assert violations_payload["limit"] == VIOLATIONS_DEFAULT_LIMIT


def test_hai_route_deu_tra_json_du_json_mac_dinh_cua_flask():
    """Cả hai route đều ``application/json`` — app gọi ``.json()`` an toàn."""
    with _Scratch("ctype") as directory, _BothRoutes(directory) as both:
        for path in ("/api/logs", "/api/violations"):
            response = both.client.get(path)
            assert "application/json" in response.headers.get(
                "Content-Type", ""
            ), path
            assert response.get_json() is not None, path
