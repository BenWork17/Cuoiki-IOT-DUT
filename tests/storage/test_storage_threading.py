"""Khoá lỗi SQLite xuyên luồng — lỗi làm route trả **rỗng** chứ không báo lỗi.

Vì sao tệp này tồn tại
----------------------

``Storage`` mở kết nối SQLite ở **luồng chính** (``__main__._Dashboard``), còn
Flask phục vụ request ở luồng khác (``dashboard-web``, và ``app.run(threaded=True)``
còn tạo thêm luồng cho từng request). Mặc định ``sqlite3`` **chặn** việc dùng
một ``Connection`` ở luồng khác với nơi tạo ra nó.

Lỗi này đặc biệt nguy hiểm vì nó **không** làm sập gì cả. Route
``/api/violations`` nuốt ``sqlite3.Error`` rồi trả ``200`` với danh sách rỗng
(đúng ý "web không được sập vì một truy vấn hỏng"). Hệ quả với người dùng:
popup nhật ký **luôn** hiện "Chưa có vi phạm nào" dù họ vừa rời bàn chục lần.
Không có lỗi nào hiện ra để mà lần theo.

Vì sao bộ test cũ không bắt được: ``tests/test_web.py`` và
``tests/test_web_violations.py`` gọi ``test_client()`` **trong cùng luồng** với
``Storage``, nên luôn xanh. Phải gọi route từ **một luồng khác** mới thấy.

Cách sửa đang được khoá ở đây: ``sqlite3.connect(..., check_same_thread=False)``
cộng một ``threading.RLock`` quanh mọi lần chạm kết nối. Hai thứ phải đi cùng
nhau — bỏ khoá thì hai luồng cùng dùng một ``Connection`` và hỏng theo kiểu im
lặng khác.

Không dùng fixture ``tmp_path``: sandbox chặn ``mkdir(mode=0o700)``, xem
``docs/TESTING_ON_WINDOWS_SANDBOX.md``.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

from posture_monitor.core.config import StorageConfig  # noqa: E402
from posture_monitor.domain.state import (  # noqa: E402
    EVENT_ABSENT,
    EVENT_IMPOSTOR,
    EVENT_PHONE_USE,
    Event,
)
from posture_monitor.storage import Storage  # noqa: E402
from posture_monitor.web.app import create_app  # noqa: E402


class _Scratch:
    """Thư mục tạm tự quản trong ``.scratch/``, không dùng ``tmp_path``."""

    def __init__(self, name: str) -> None:
        self.path = _REPO_ROOT / ".scratch" / f"threading_test_{name}"

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


def _store_with(directory: Path, codes: list[str]) -> Storage:
    store = Storage(StorageConfig(db_path=str(directory / "t.db")))
    store.open()
    base = time.time()
    for index, code in enumerate(codes):
        store.record_event(
            Event(ts=base + index, type=code, label="x", duration_s=float(index)),
            now=base + index,
        )
    store.flush()
    return store


def _from_other_thread(fn):
    """Chạy ``fn`` ở luồng khác, trả kết quả; ném lại exception nếu có.

    Dùng ``join`` có timeout để test hỏng vì treo chứ không treo cả bộ test.
    """
    box: dict[str, object] = {}

    def runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - test cần thấy mọi lỗi
            box["error"] = exc

    thread = threading.Thread(target=runner, name="other-thread")
    thread.start()
    thread.join(timeout=10.0)
    assert not thread.is_alive(), "luồng khác treo quá 10 giây"
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")


# ---------------------------------------------------------------------------
# Tầng storage
# ---------------------------------------------------------------------------


def test_violations_doc_duoc_tu_luong_khac():
    """Bài quan trọng nhất: trước khi sửa, đây trả **0** dòng.

    Không phải 0 vì không có dữ liệu — dữ liệu có thật, cùng luồng đọc ra 3.
    Đó chính là kiểu hỏng khó thấy nhất: sai mà không báo.
    """
    with _Scratch("viol_other") as directory:
        store = _store_with(
            directory, [EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR]
        )
        try:
            same = store.violations()
            other = _from_other_thread(store.violations)
        finally:
            store.close()

    assert len(same) == 3
    assert len(other) == 3, (
        "đọc từ luồng khác phải thấy đủ 3 vi phạm; nếu 0 thì kết nối SQLite "
        "chưa được mở với check_same_thread=False"
    )
    assert {row["kind"] for row in other} == {"ABSENT", "PHONE_USE", "IMPOSTOR"}


def test_history_doc_duoc_tu_luong_khac():
    """``history`` mở kết nối riêng nên cũng phải chạy được — kiểm để chắc."""
    with _Scratch("hist_other") as directory:
        store = _store_with(directory, [EVENT_ABSENT])
        try:
            result = _from_other_thread(lambda: store.history("today"))
        finally:
            store.close()

    assert isinstance(result, dict)
    assert "labels" in result


def test_nhieu_luong_doc_song_song_khong_raise():
    """8 luồng đọc cùng lúc trên cùng ``Storage`` — khoá phải chống chịu."""
    with _Scratch("concurrent") as directory:
        store = _store_with(directory, [EVENT_ABSENT, EVENT_PHONE_USE])
        try:
            results: list[int] = []
            lock = threading.Lock()

            def reader() -> None:
                rows = store.violations()
                with lock:
                    results.append(len(rows))

            threads = [threading.Thread(target=reader) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10.0)
                assert not thread.is_alive()
        finally:
            store.close()

    assert results == [2] * 8, f"mọi luồng phải thấy 2 dòng, nhận {results}"


def test_doc_va_ghi_song_song_khong_raise():
    """Luồng đọc chạy trong lúc luồng chính ghi — không được ném."""
    with _Scratch("rw") as directory:
        store = _store_with(directory, [EVENT_ABSENT])
        errors: list[BaseException] = []
        lock = threading.Lock()
        stop = threading.Event()

        def reader() -> None:
            try:
                while not stop.is_set():
                    store.violations()
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        thread = threading.Thread(target=reader, name="reader")
        thread.start()
        try:
            base = time.time()
            for index in range(20):
                store.record_event(
                    Event(
                        ts=base + index,
                        type=EVENT_PHONE_USE,
                        label="x",
                        duration_s=0.0,
                    ),
                    now=base + index,
                )
            store.flush()
        finally:
            stop.set()
            thread.join(timeout=10.0)
            store.close()

    assert errors == [], f"luồng đọc ném lỗi khi đang ghi: {errors}"


# ---------------------------------------------------------------------------
# Tầng HTTP — đúng điều kiện production
# ---------------------------------------------------------------------------


def test_route_violations_tra_du_lieu_khi_goi_tu_luong_khac():
    """Đầu-cuối: Flask ở luồng khác phải thấy đủ 3 vi phạm.

    Đây là bài tái hiện đúng triệu chứng người dùng gặp: popup luôn rỗng dù
    dữ liệu có thật, vì Flask phục vụ ở luồng khác với nơi mở kết nối.
    """
    with _Scratch("http_other") as directory:
        store = _store_with(
            directory, [EVENT_ABSENT, EVENT_PHONE_USE, EVENT_IMPOSTOR]
        )
        try:
            client = create_app(storage=store).test_client()

            def call() -> dict:
                response = client.get("/api/violations")
                assert response.status_code == 200
                return response.get_json()

            payload = _from_other_thread(call)
        finally:
            store.close()

    assert payload["total"] == 3, (
        "route trả rỗng khi gọi từ luồng khác; xem docstring đầu tệp"
    )
    assert payload["counts"] == {
        "ABSENT": 1,
        "PHONE_USE": 1,
        "IMPOSTOR": 1,
    }
    labels = {row["kind_text"] for row in payload["violations"]}
    assert "Rời khỏi bàn học" in labels


def test_route_violations_khong_bao_loi_ra_ngoai_khi_luong_khac():
    """Không được trả 500: hỏng DB phải thành 200-rỗng hoặc 503, không sập."""
    with _Scratch("http_status") as directory:
        store = _store_with(directory, [EVENT_ABSENT])
        try:
            client = create_app(storage=store).test_client()

            def call() -> int:
                return client.get("/api/violations").status_code

            status = _from_other_thread(call)
        finally:
            store.close()

    assert status == 200
