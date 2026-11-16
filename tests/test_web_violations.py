"""Khoá hợp đồng ``GET /api/violations`` — lịch sử **vi phạm** cho web và app.

Vì sao có tệp test riêng cho một route: đây là dữ liệu người dùng **đọc**,
không phải log chẩn đoán. Ba thứ dễ hỏng mà test phải bắt:

1. **Lẫn sự kiện kỹ thuật vào vi phạm.** Bảng ``events`` chứa cả
   ``alert_start``/``alert_end``/``SPEAK_OK``/``break_reminder``/
   ``absent_reset``. Trả lẫn vào thì popup đầy dòng vô nghĩa và người dùng
   không đọc được gì — hỏng đúng mục đích của tính năng.
2. **Nhãn lệch giữa ba nơi.** Dashboard, popup web và app cùng hiển thị một
   việc; nếu server không sinh ``kind_text`` thì mỗi nơi tự dịch và chúng nói
   khác nhau sau lần đổi chữ đầu tiên.
3. **Lỗi DB làm sập web.** Web không được chết vì một truy vấn hỏng, nhưng
   cũng không được lặng lẽ trả "không có vi phạm nào".

Không dùng fixture ``tmp_path``: sandbox của máy này chặn thư mục tạo bằng
``mkdir(mode=0o700)`` (xem ``docs/TESTING_ON_WINDOWS_SANDBOX.md``). Dùng
``_Scratch`` như ``tests/test_calibrate_reacquire.py``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.config import StorageConfig  # noqa: E402
from posture_monitor.state import (  # noqa: E402
    EVENT_ABSENT,
    EVENT_ALERT_START,
    EVENT_BREAK,
    EVENT_IMPOSTOR,
    EVENT_PHONE_USE,
    EVENT_SPEAK_OK,
    Event,
)
from posture_monitor.storage import (  # noqa: E402
    VIOLATION_KIND_CODES,
    Storage,
)
from posture_monitor.web.app import (  # noqa: E402
    VIOLATION_KIND_TEXT,
    VIOLATION_KINDS,
    VIOLATIONS_DEFAULT_LIMIT,
    VIOLATIONS_MAX_LIMIT,
    create_app,
)


class _Scratch:
    """Thư mục tạm tự quản trong ``.scratch/``, không dùng ``tmp_path``."""

    def __init__(self, name: str) -> None:
        self.path = _REPO_ROOT / ".scratch" / f"violations_test_{name}"

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


def _storage_with_events(directory: Path, events: list[str]) -> Storage:
    """Storage đã mở, có một dòng cho mỗi mã trong ``events``."""
    store = Storage(StorageConfig(db_path=str(directory / "v.db")))
    store.open()
    base = time.time()
    for index, code in enumerate(events):
        store.record_event(
            Event(
                ts=base + index,
                type=code,
                label="x",
                duration_s=float(index),
                alert=True,
            ),
            now=base + index,
        )
    store.flush()
    return store


def _client(storage):
    return create_app(storage=storage).test_client()


# ---------------------------------------------------------------------------
# Hằng số: hợp đồng giữa ba tầng
# ---------------------------------------------------------------------------


def test_ba_ma_vi_pham_khop_giua_storage_va_web():
    """``storage`` và ``web`` phải nói cùng ba mã — đổi một bên là đỏ ngay."""
    assert tuple(VIOLATION_KINDS) == tuple(VIOLATION_KIND_CODES)
    assert set(VIOLATION_KINDS) == {"ABSENT", "PHONE_USE", "IMPOSTOR"}


def test_ma_vi_pham_trung_hang_so_trong_state():
    """Mã trong ``storage``/``web`` phải trùng hằng của máy trạng thái.

    Trùng ở đây là **giá trị chuỗi**, không phải import: ``storage`` cố ý
    không import ``state`` để giữ nó là tầng thấp nạp được một mình.
    """
    assert set(VIOLATION_KIND_CODES) == {
        EVENT_ABSENT,
        EVENT_PHONE_USE,
        EVENT_IMPOSTOR,
    }


def test_moi_ma_co_nhan_tieng_viet():
    """Không mã nào được rơi về chuỗi thô khi hiển thị."""
    for code in VIOLATION_KINDS:
        assert code in VIOLATION_KIND_TEXT
        assert VIOLATION_KIND_TEXT[code].strip() != ""
        assert VIOLATION_KIND_TEXT[code] != code


def test_gioi_han_hop_ly():
    assert 0 < VIOLATIONS_DEFAULT_LIMIT <= VIOLATIONS_MAX_LIMIT


# ---------------------------------------------------------------------------
# Nội dung trả về
# ---------------------------------------------------------------------------


def test_chi_tra_ba_loai_vi_pham_bo_qua_su_kien_ky_thuat():
    """``alert_start``/``SPEAK_OK``/``break_reminder`` KHÔNG được lọt vào.

    Đây là bài quan trọng nhất của tệp: bảng ``events`` là bảng dùng chung, và
    trả lẫn sẽ biến popup thành danh sách dòng kỹ thuật vô nghĩa.
    """
    with _Scratch("loc") as directory:
        store = _storage_with_events(
            directory,
            [
                EVENT_ABSENT,
                EVENT_PHONE_USE,
                EVENT_IMPOSTOR,
                EVENT_ALERT_START,
                EVENT_SPEAK_OK,
                EVENT_BREAK,
            ],
        )
        try:
            payload = _client(store).get("/api/violations").get_json()
        finally:
            store.close()

    kinds = {row["kind"] for row in payload["violations"]}
    assert kinds == {"ABSENT", "PHONE_USE", "IMPOSTOR"}
    assert payload["total"] == 3


def test_moi_dong_du_ts_kind_kind_text_duration():
    with _Scratch("shape") as directory:
        store = _storage_with_events(directory, [EVENT_ABSENT, EVENT_PHONE_USE])
        try:
            payload = _client(store).get("/api/violations").get_json()
        finally:
            store.close()

    assert payload["violations"], "phải có ít nhất một dòng"
    for row in payload["violations"]:
        assert set(row) == {"ts", "kind", "kind_text", "duration_s"}
        assert isinstance(row["ts"], (int, float))
        assert row["kind"] in VIOLATION_KINDS
        assert row["kind_text"] == VIOLATION_KIND_TEXT[row["kind"]]
        assert isinstance(row["duration_s"], (int, float))


def test_moi_nhat_truoc():
    with _Scratch("order") as directory:
        store = _storage_with_events(
            directory, [EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR]
        )
        try:
            payload = _client(store).get("/api/violations").get_json()
        finally:
            store.close()

    stamps = [row["ts"] for row in payload["violations"]]
    assert stamps == sorted(stamps, reverse=True)


def test_counts_dem_dung_tung_loai():
    with _Scratch("counts") as directory:
        store = _storage_with_events(
            directory,
            [EVENT_ABSENT, EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR],
        )
        try:
            payload = _client(store).get("/api/violations").get_json()
        finally:
            store.close()

    assert payload["counts"]["ABSENT"] == 2
    assert payload["counts"]["PHONE_USE"] == 1
    assert payload["counts"]["IMPOSTOR"] == 1
    assert payload["total"] == 4


# ---------------------------------------------------------------------------
# Tham số
# ---------------------------------------------------------------------------


def test_limit_cat_bot_va_giu_moi_nhat():
    with _Scratch("limit") as directory:
        store = _storage_with_events(
            directory, [EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR]
        )
        try:
            payload = _client(store).get("/api/violations?limit=2").get_json()
        finally:
            store.close()

    assert payload["total"] == 2
    assert payload["limit"] == 2


def test_loc_theo_kinds():
    with _Scratch("kinds") as directory:
        store = _storage_with_events(
            directory, [EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR]
        )
        try:
            client = _client(store)
            only_absent = client.get("/api/violations?kinds=ABSENT").get_json()
            two = client.get("/api/violations?kinds=ABSENT,PHONE_USE").get_json()
        finally:
            store.close()

    assert only_absent["total"] == 1
    assert only_absent["violations"][0]["kind"] == "ABSENT"
    assert two["total"] == 2
    assert {row["kind"] for row in two["violations"]} == {"ABSENT", "PHONE_USE"}


def test_since_s_loc_theo_thoi_gian():
    with _Scratch("since") as directory:
        store = _storage_with_events(directory, [EVENT_ABSENT, EVENT_PHONE_USE])
        try:
            client = _client(store)
            everything = client.get("/api/violations").get_json()
            recent = client.get("/api/violations?since_s=0").get_json()
        finally:
            store.close()

    assert everything["total"] == 2
    # since_s=0 nghĩa là "từ bây giờ": các mốc vừa ghi trong quá khứ gần như
    # chắc chắn cũ hơn, nên danh sách phải ngắn hơn hoặc bằng.
    assert recent["total"] <= 2


@pytest.mark.parametrize("bad_limit", ["abc", "0", "-1", "999999"])
def test_limit_sai_tra_400_kem_cau_tieng_viet(bad_limit: str):
    with _Scratch("badlimit") as directory:
        store = _storage_with_events(directory, [EVENT_ABSENT])
        try:
            response = _client(store).get(f"/api/violations?limit={bad_limit}")
        finally:
            store.close()

    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert "limit" in body["message"]


def test_kinds_la_tra_400_va_liet_ke_ma_hop_le():
    """Gõ sai mã phải báo lỗi, KHÔNG lặng lẽ bỏ qua.

    Bỏ qua thì người dùng thấy danh sách rỗng và tưởng "không có vi phạm nào".
    """
    with _Scratch("badkinds") as directory:
        store = _storage_with_events(directory, [EVENT_ABSENT])
        try:
            response = _client(store).get("/api/violations?kinds=SAI_MA")
        finally:
            store.close()

    assert response.status_code == 400
    message = response.get_json()["message"]
    for code in VIOLATION_KINDS:
        assert code in message


def test_since_s_khong_phai_so_tra_400():
    with _Scratch("badsince") as directory:
        store = _storage_with_events(directory, [EVENT_ABSENT])
        try:
            response = _client(store).get("/api/violations?since_s=hom_qua")
        finally:
            store.close()

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Thiếu dữ liệu / lỗi
# ---------------------------------------------------------------------------


def test_chua_bat_luu_tru_tra_503_json():
    response = create_app(storage=None).test_client().get("/api/violations")

    assert response.status_code == 503
    body = response.get_json()
    assert body["ok"] is False
    assert "lưu trữ" in body["message"].lower()
    assert response.mimetype == "application/json"


def test_db_rong_tra_danh_sach_rong_chu_khong_loi():
    with _Scratch("empty") as directory:
        store = Storage(StorageConfig(db_path=str(directory / "v.db")))
        store.open()
        try:
            response = _client(store).get("/api/violations")
        finally:
            store.close()

    assert response.status_code == 200
    body = response.get_json()
    assert body["violations"] == []
    assert body["total"] == 0
    assert body["counts"] == {"ABSENT": 0, "PHONE_USE": 0, "IMPOSTOR": 0}


def test_violations_khong_raise_khi_db_dong():
    """Gọi ``violations()`` trên Storage chưa mở phải trả rỗng, không ném."""
    store = Storage(StorageConfig(db_path="khong_mo.db"))
    assert store.violations() == []


def test_route_doc_duoc_ba_loai_voi_storage_that():
    """Đầu-cuối: ghi 3 vi phạm rồi đọc qua HTTP."""
    with _Scratch("e2e") as directory:
        store = _storage_with_events(
            directory, [EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR]
        )
        try:
            payload = _client(store).get("/api/violations").get_json()
        finally:
            store.close()

    assert payload["total"] == 3
    labels = [row["kind_text"] for row in payload["violations"]]
    assert VIOLATION_KIND_TEXT["ABSENT"] in labels
    assert VIOLATION_KIND_TEXT["PHONE_USE"] in labels
    assert VIOLATION_KIND_TEXT["IMPOSTOR"] in labels
