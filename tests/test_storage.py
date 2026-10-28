"""Unit test cho ``storage.py`` (spec v2 §5.9, §9).

Tất cả chạy trên PC với DB tạm trong ``tmp_path``; không cần camera hay phần
cứng. Đồng hồ được bơm từ ngoài (:class:`FakeClock`) để mốc thời gian trong
``sessions``/``events``/``minute_stats`` tất định.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.classifier import ABSENT, GOOD, HEAD_DOWN  # noqa: E402
from posture_monitor.config import StorageConfig  # noqa: E402
from posture_monitor.state import (  # noqa: E402
    EVENT_ALERT_END,
    EVENT_ALERT_START,
    STATE_ABSENT,
    STATE_GOOD,
    STATE_WARN,
    Event,
    StateUpdate,
)
from posture_monitor.storage import (  # noqa: E402
    FLUSH_INTERVAL_S,
    MAX_FRAME_GAP_S,
    MINUTE_S,
    Storage,
)

#: Mốc bắt đầu cố định: 10/10/2026 08:00:00 giờ địa phương. Dùng giờ địa
#: phương để ``history('today')`` và retention cùng một hệ quy chiếu.
BASE_TS = datetime(2026, 10, 10, 8, 0, 0).timestamp()


class FakeClock:
    """Đồng hồ giả: chỉ nhích khi test gọi :meth:`advance`/``set``."""

    def __init__(self, now: float = BASE_TS) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


def make_update(
    now: float,
    state: str = STATE_GOOD,
    score: float = 90.0,
    labels: frozenset[str] | None = None,
    events: tuple[Event, ...] = (),
) -> StateUpdate:
    """Dựng :class:`StateUpdate` tối thiểu để test."""
    if labels is None:
        labels = frozenset({GOOD}) if state == STATE_GOOD else frozenset()
    return StateUpdate(
        now=now,
        state=state,
        labels=labels,
        score=score,
        sitting_s=max(0.0, now - BASE_TS),
        events=events,
        alerts=tuple(event for event in events if event.alert),
    )


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def storage(tmp_path, clock) -> Storage:
    store = Storage(
        StorageConfig(db_path=str(tmp_path / "data" / "posture.db")),
        clock=clock,
    )
    store.open()
    yield store
    store.close()


def fetch_all(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Đọc trực tiếp DB bằng kết nối riêng (không qua API của module)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Mở/đóng, schema
# ---------------------------------------------------------------------------


def test_open_tao_thu_muc_va_schema(tmp_path, clock):
    db_path = tmp_path / "long" / "nested" / "posture.db"
    store = Storage(StorageConfig(db_path=str(db_path)), clock=clock)
    store.open()
    try:
        assert db_path.is_file(), "phải tạo thư mục cha rồi mới mở DB"
        rows = fetch_all(db_path, "SELECT name FROM sqlite_master WHERE type='table'")
        names = {row["name"] for row in rows}
        assert {"sessions", "events", "minute_stats"} <= names
        assert store.session_id is not None
    finally:
        store.close()


def test_wal_duoc_bat(storage):
    rows = fetch_all(storage.db_path, "PRAGMA journal_mode")
    assert rows[0][0].lower() == "wal"


def test_phien_mo_khi_bat_dau_va_dong_khi_ket_thuc(tmp_path, clock):
    db_path = tmp_path / "posture.db"
    store = Storage(StorageConfig(db_path=str(db_path)), clock=clock)
    store.open()
    session_id = store.session_id

    row = fetch_all(db_path, "SELECT * FROM sessions WHERE id = ?", (session_id,))[0]
    assert row["start_ts"] == pytest.approx(BASE_TS)
    assert row["end_ts"] is None, "phiên đang chạy phải chưa có end_ts"

    clock.advance(120)
    store.close()

    row = fetch_all(db_path, "SELECT * FROM sessions WHERE id = ?", (session_id,))[0]
    assert row["end_ts"] == pytest.approx(BASE_TS + 120)


def test_khong_tao_phien_mo_coi_khi_tien_trinh_chet(tmp_path, clock):
    """Phiên còn ``end_ts IS NULL`` của lần chạy trước phải được đóng lại."""
    db_path = tmp_path / "posture.db"
    first = Storage(StorageConfig(db_path=str(db_path)), clock=clock)
    first.open()
    first_session = first.session_id
    first.record(make_update(BASE_TS + 1, score=80.0))
    clock.advance(30)
    first.record(make_update(BASE_TS + 31, score=82.0))
    first.flush()
    # Không gọi close(): mô phỏng tiến trình bị kill.
    first._conn.close()
    first._conn = None

    clock.advance(600)
    second = Storage(StorageConfig(db_path=str(db_path)), clock=clock)
    second.open()
    try:
        assert second.session_id != first_session
        rows = fetch_all(
            db_path, "SELECT * FROM sessions WHERE end_ts IS NULL"
        )
        assert len(rows) == 1, "chỉ phiên mới được để mở"
        assert rows[0]["id"] == second.session_id

        old = fetch_all(
            db_path, "SELECT * FROM sessions WHERE id = ?", (first_session,)
        )[0]
        assert old["end_ts"] is not None, "phiên mồ côi phải được đóng"
        assert old["end_ts"] >= old["start_ts"]
    finally:
        second.close()


def test_mo_db_loi_khong_crash(tmp_path, clock):
    """Đường dẫn trỏ vào file thường (không phải thư mục) → mở lỗi, không raise."""
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    store = Storage(StorageConfig(db_path=str(blocker / "posture.db")), clock=clock)
    store.open()  # không được raise
    assert not store.is_open
    store.record(make_update(BASE_TS))  # no-op
    store.flush()  # no-op
    assert store.cleanup_retention() == 0
    assert store.history("today")["has_data"] is False
    store.close()


# ---------------------------------------------------------------------------
# minute_stats
# ---------------------------------------------------------------------------


def test_good_pct_va_absent_s_theo_phut(storage, clock):
    # 10 giây GOOD rồi 10 giây ABSENT trong cùng một phút.
    storage.record(make_update(clock.now))
    for _ in range(10):
        clock.advance(1)
        storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))

    for _ in range(10):
        clock.advance(1)
        storage.record(
            make_update(
                clock.now,
                state=STATE_ABSENT,
                score=0.0,
                labels=frozenset({ABSENT}),
            )
        )
    storage.flush()

    rows = fetch_all(storage.db_path, "SELECT * FROM minute_stats")
    assert len(rows) == 1
    row = rows[0]
    assert row["minute_ts"] == int(BASE_TS // MINUTE_S) * MINUTE_S
    # 10 giây có người (mẫu số good_pct) trong tổng 20 giây.
    assert row["good_pct"] == pytest.approx(100.0, abs=0.01)
    assert row["absent_s"] == pytest.approx(10.0, abs=0.1)


def test_avg_score_loai_khung_absent(storage, clock):
    """ABSENT trả score 0 nhưng không được kéo ``avg_score`` xuống."""
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    for _ in range(5):
        clock.advance(1)
        storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    for _ in range(5):
        clock.advance(1)
        storage.record(
            make_update(
                clock.now,
                state=STATE_ABSENT,
                score=0.0,
                labels=frozenset({ABSENT}),
            )
        )
    storage.flush()

    row = fetch_all(storage.db_path, "SELECT * FROM minute_stats")[0]
    assert row["avg_score"] == pytest.approx(90.0, abs=0.01)
    assert row["absent_s"] == pytest.approx(5.0, abs=0.1)


def test_good_pct_tinh_theo_thoi_gian_khong_phai_so_khung(storage, clock):
    """9 giây GOOD rồi 1 giây WARN → 90%, không phải 50% như đếm khung."""
    storage.record(make_update(clock.now, state=STATE_GOOD, score=95.0))
    for _ in range(9):
        clock.advance(1)
        storage.record(make_update(clock.now, state=STATE_GOOD, score=95.0))
    clock.advance(1)
    storage.record(
        make_update(
            clock.now,
            state=STATE_WARN,
            score=70.0,
            labels=frozenset({HEAD_DOWN}),
        )
    )
    storage.flush()

    row = fetch_all(storage.db_path, "SELECT * FROM minute_stats")[0]
    assert row["good_pct"] == pytest.approx(90.0, abs=0.5)
    assert row["avg_score"] == pytest.approx(
        (95 * 9 + 70 * 1) / 10, abs=0.2
    )


def test_khoang_trong_dai_khong_bi_tinh_la_thoi_gian_quan_sat(storage, clock):
    """Khoảng nghỉ dài hơn MAX_FRAME_GAP_S không cộng vào thống kê.

    Không cap thì 600 giây sẽ rải ra 10 phút ``good_pct`` = 100 %, tức là bịa
    ra thời gian quan sát không hề có.
    """
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    clock.advance(600)
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    storage.flush()

    rows = fetch_all(storage.db_path, "SELECT * FROM minute_stats")
    assert rows, "khoảng ngắn sau khi nối lại vẫn phải có dữ liệu"
    assert len(rows) == 1, "600 giây không được rải thành 10 phút"
    assert sum(row["absent_s"] for row in rows) == 0.0


def test_distance_trung_binh(storage, clock):
    for distance in (40.0, 50.0, 60.0):
        storage.record(make_update(clock.now, score=90.0), distance_cm=distance)
        clock.advance(1)
    storage.flush()

    row = fetch_all(storage.db_path, "SELECT * FROM minute_stats")[0]
    assert row["distance_cm_avg"] == pytest.approx(50.0)


def test_khung_qua_hai_phut_duoc_chia_dung(storage, clock):
    """Khung vắt qua ranh giới phút phải chia cho cả hai phút."""
    # Đặt đồng hồ ở giây 55 của phút, rồi nhích qua 60.
    minute_start = int(BASE_TS // MINUTE_S) * MINUTE_S
    clock.now = float(minute_start + 55)
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    clock.advance(MAX_FRAME_GAP_S)
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    clock.advance(MAX_FRAME_GAP_S)
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    storage.flush()

    rows = fetch_all(
        storage.db_path, "SELECT * FROM minute_stats ORDER BY minute_ts"
    )
    assert len(rows) == 2
    assert rows[0]["minute_ts"] == minute_start
    assert rows[1]["minute_ts"] == minute_start + MINUTE_S


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def test_su_kien_duoc_ghi_kem_extra_json(storage, clock):
    event = Event(
        ts=clock.now,
        type=EVENT_ALERT_START,
        label=HEAD_DOWN,
        duration_s=5.5,
        level=1,
        alert=True,
    )
    storage.record(make_update(clock.now, events=(event,)))
    end_event = Event(
        ts=clock.now + 10,
        type=EVENT_ALERT_END,
        label=HEAD_DOWN,
        duration_s=15.5,
        level=2,
    )
    clock.advance(10)
    storage.record(make_update(clock.now, events=(end_event,)))
    storage.flush()

    rows = fetch_all(storage.db_path, "SELECT * FROM events ORDER BY ts")
    assert [row["type"] for row in rows] == [EVENT_ALERT_START, EVENT_ALERT_END]
    assert rows[0]["label"] == HEAD_DOWN
    assert rows[0]["duration_s"] == pytest.approx(5.5)
    assert rows[0]["session_id"] == storage.session_id

    extra = json.loads(rows[0]["extra_json"])
    assert extra["alert"] is True
    assert extra["level"] == 1
    assert extra["source_ts"] == pytest.approx(clock.now - 10, abs=0.001)


def test_record_event_rieng(storage, clock):
    storage.record_event(
        Event(ts=clock.now, type=EVENT_ALERT_START, label=HEAD_DOWN)
    )
    storage.flush()
    rows = fetch_all(storage.db_path, "SELECT * FROM events")
    assert len(rows) == 1


def test_flush_ghi_theo_lo_va_flush_lai_khong_nhan_doi(storage, clock):
    storage.record(make_update(clock.now, score=90.0))
    clock.advance(1)
    storage.record(make_update(clock.now, score=90.0))
    storage.flush()
    storage.flush()  # gọi lại không được nhân đôi dữ liệu

    rows = fetch_all(storage.db_path, "SELECT * FROM minute_stats")
    assert len(rows) == 1


def test_ghi_theo_lo_khong_ghi_db_moi_khung(storage, clock):
    """Trong chu kỳ 10 giây, DB chưa được ghi cho tới khi flush."""
    storage.record(make_update(clock.now, score=90.0))
    for _ in range(5):
        clock.advance(1)
        storage.record(make_update(clock.now, score=90.0))
    assert fetch_all(storage.db_path, "SELECT * FROM minute_stats") == []

    # Nhích qua chu kỳ 10 giây: lần ghi kế tiếp tự flush.
    clock.advance(FLUSH_INTERVAL_S)
    storage.record(make_update(clock.now, score=90.0))
    assert fetch_all(storage.db_path, "SELECT * FROM minute_stats")


def test_close_ghi_not_phan_con_lai(tmp_path, clock):
    db_path = tmp_path / "posture.db"
    store = Storage(StorageConfig(db_path=str(db_path)), clock=clock)
    store.open()
    store.record(make_update(clock.now, score=90.0))
    clock.advance(1)
    store.record(make_update(clock.now, score=88.0))
    store.close()  # không gọi flush tay

    rows = fetch_all(db_path, "SELECT * FROM minute_stats")
    assert len(rows) == 1
    assert rows[0]["avg_score"] == pytest.approx(88.0, abs=0.01)


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def test_retention_xoa_dung_du_lieu_cu(tmp_path, clock):
    db_path = tmp_path / "posture.db"
    store = Storage(
        StorageConfig(db_path=str(db_path), retention_days=30), clock=clock
    )
    store.open()
    try:
        # Ghi một phiên cũ 40 ngày trước bằng tay.
        old_ts = BASE_TS - 40 * 86400
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO sessions (start_ts, end_ts) VALUES (?, ?)",
            (old_ts, old_ts + 60),
        )
        old_session = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO events (session_id, ts, type, label, duration_s) "
            "VALUES (?, ?, 'alert_start', 'HEAD_DOWN', 5)",
            (old_session, old_ts + 10),
        )
        conn.execute(
            "INSERT INTO minute_stats (session_id, minute_ts, good_pct, "
            "avg_score, absent_s, distance_cm_avg) VALUES (?, ?, 50, 70, 0, 40)",
            (old_session, int(old_ts // MINUTE_S) * MINUTE_S),
        )
        conn.commit()
        conn.close()

        # Dữ liệu mới trong phiên hiện tại phải được giữ.
        store.record(make_update(clock.now, score=90.0))
        clock.advance(1)
        store.record(make_update(clock.now, score=90.0))
        store.flush()

        removed = store.cleanup_retention()
        assert removed > 0
        assert fetch_all(
            db_path, "SELECT * FROM events WHERE session_id = ?", (old_session,)
        ) == []
        assert fetch_all(
            db_path,
            "SELECT * FROM minute_stats WHERE session_id = ?",
            (old_session,),
        ) == []
        assert fetch_all(
            db_path, "SELECT * FROM sessions WHERE id = ?", (old_session,)
        ) == []
        # Phiên đang mở và dữ liệu của nó còn nguyên.
        assert fetch_all(
            db_path, "SELECT * FROM minute_stats WHERE session_id = ?",
            (store.session_id,),
        )
        assert fetch_all(
            db_path, "SELECT * FROM sessions WHERE id = ?",
            (store.session_id,),
        )
    finally:
        store.close()


def test_retention_0_giu_toan_bo(tmp_path, clock):
    store = Storage(
        StorageConfig(db_path=str(tmp_path / "p.db"), retention_days=0),
        clock=clock,
    )
    store.open()
    try:
        assert store.cleanup_retention() == 0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


def test_history_ranges_va_hinh_dang(storage, clock):
    storage.record(make_update(clock.now, score=90.0))
    clock.advance(30)
    storage.record(make_update(clock.now, score=80.0))
    storage.flush()

    today = storage.history("today")
    assert today["range"] == "today"
    assert today["unit"] == "hour"
    assert today["has_data"] is True
    assert today["labels"], "phải có nhãn giờ để vẽ biểu đồ"
    assert len(today["labels"]) == len(today["good_pct"]) == len(today["avg_score"])
    assert len(today["labels"]) == len(today["absent_s"])
    # 08:00 là giờ có dữ liệu (BASE_TS = 08:00).
    index = today["labels"].index("08:00")
    assert today["good_pct"][index] == pytest.approx(100.0, abs=0.5)

    week = storage.history("7d")
    assert week["unit"] == "day"
    assert len(week["labels"]) == 7
    assert week["has_data"] is True
    assert week["good_pct"][-1] == pytest.approx(100.0, abs=0.5)


def test_history_khi_chua_co_du_lieu(storage):
    result = storage.history("today")
    assert result["has_data"] is False
    assert result["labels"] == []
    assert "Chưa có dữ liệu" in result["message"]


def test_history_range_sai_bi_tu_choi(storage):
    with pytest.raises(ValueError):
        storage.history("thang")


def test_history_loai_absent_khoi_diem_trung_binh(storage, clock):
    """Cùng dữ liệu với test minute_stats nhưng đọc qua API của dashboard."""
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    clock.advance(MAX_FRAME_GAP_S)
    storage.record(
        make_update(
            clock.now,
            state=STATE_ABSENT,
            score=0.0,
            labels=frozenset({ABSENT}),
        )
    )
    clock.advance(MAX_FRAME_GAP_S)
    storage.record(make_update(clock.now, state=STATE_GOOD, score=90.0))
    storage.flush()

    today = storage.history("today")
    index = today["labels"].index("08:00")
    assert today["good_pct"][index] == pytest.approx(100.0, abs=1.0)
    assert today["avg_score"][index] == pytest.approx(90.0, abs=1.0)
    assert today["absent_s"][index] == pytest.approx(MAX_FRAME_GAP_S, abs=0.5)


def test_history_khong_loi_khi_db_chua_ton_tai(tmp_path, clock):
    store = Storage(
        StorageConfig(db_path=str(tmp_path / "missing.db")), clock=clock
    )
    # Chưa open(): đọc phải trả rỗng, không raise.
    assert store.history("today")["has_data"] is False
