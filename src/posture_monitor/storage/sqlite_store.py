"""Lưu thống kê tư thế vào SQLite (spec v2 §5.9).

Ba bảng đúng schema spec:

- ``sessions(id, start_ts, end_ts)`` — một dòng cho mỗi lần chạy.
- ``events(id, session_id, ts, type, label, duration_s, extra_json)`` — ghi cả
  lúc sự kiện bắt đầu lẫn lúc kết thúc.
- ``minute_stats(session_id, minute_ts, good_pct, avg_score, absent_s,
  distance_cm_avg)`` — tổng hợp theo phút.

**Chỉ lưu số liệu. Không lưu ảnh, không lưu video, không lưu khung hình**
(spec v2 §11.5).
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Sequence

from ..core.labels import (
    ABSENT,
    STATE_ABSENT,
    STATE_BAD,
    STATE_GOOD,
    STATE_WARN,
    VIOLATION_KINDS,
)
from ..core.logging_setup import get_logger

if TYPE_CHECKING:
    from ..domain.state import Event, StateUpdate

_logger = get_logger(__name__)

#: Chu kỳ ghi theo lô (spec v2 §5.9).
FLUSH_INTERVAL_S = 10.0

#: Độ dài một phút, đơn vị giây.
MINUTE_S = 60

#: Khoảng cách tối đa giữa hai khung được tính vào thống kê.
MAX_FRAME_GAP_S = 5.0

#: Số dòng tối đa giữ trong hàng đợi khi DB liên tục lỗi.
MAX_PENDING_ROWS = 2000

#: Số ngày trong khoảng "7 ngày" của dashboard.
HISTORY_7D_DAYS = 7

#: Số giây trong một ngày.
DAY_S = 86400

#: Ba mã vi phạm mà :meth:`Storage.violations` trả về (nguồn sự thật từ ``core.labels``).
VIOLATION_KIND_CODES = VIOLATION_KINDS

#: Các trường số liệu song song trong kết quả ``history()``.
_STAT_SERIES_KEYS = ("good_pct", "avg_score", "absent_s", "distance_cm_avg")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts REAL NOT NULL,
    end_ts   REAL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ts          REAL NOT NULL,
    type        TEXT NOT NULL,
    label       TEXT,
    duration_s  REAL NOT NULL DEFAULT 0,
    extra_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts
    ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_session
    ON events(session_id, ts);

CREATE TABLE IF NOT EXISTS minute_stats (
    session_id       INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    minute_ts        INTEGER NOT NULL,
    good_pct         REAL,
    avg_score        REAL,
    absent_s         REAL NOT NULL DEFAULT 0,
    distance_cm_avg  REAL,
    PRIMARY KEY (session_id, minute_ts)
);

CREATE INDEX IF NOT EXISTS idx_minute_ts
    ON minute_stats(minute_ts);
"""


@dataclass
class _Bucket:
    """Bộ cộng dồn số liệu của một phút."""

    minute_ts: int
    present_s: float = 0.0
    good_s: float = 0.0
    absent_s: float = 0.0
    score_sum: float = 0.0
    distance_sum: float = 0.0
    distance_n: int = 0

    @property
    def has_data(self) -> bool:
        return (
            self.present_s > 0.0
            or self.absent_s > 0.0
            or self.distance_n > 0
        )

    @property
    def good_pct(self) -> float | None:
        if self.present_s <= 0.0:
            return None
        return round(100.0 * self.good_s / self.present_s, 2)

    @property
    def avg_score(self) -> float | None:
        if self.present_s <= 0.0:
            return None
        return round(self.score_sum / self.present_s, 2)

    @property
    def distance_cm_avg(self) -> float | None:
        if self.distance_n <= 0:
            return None
        return round(self.distance_sum / self.distance_n, 2)


def _local_midnight(ts: float) -> float | None:
    """Mốc 00:00 giờ địa phương của ngày chứa ``ts``; ``None`` nếu ngoài dải."""
    try:
        moment = datetime.fromtimestamp(ts).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return moment.timestamp()
    except (OSError, OverflowError, ValueError, TypeError):
        return None


def _format_local(ts: float, fmt: str, fallback: str = "?") -> str:
    """Định dạng mốc thời gian theo giờ địa phương, **không bao giờ** raise."""
    try:
        return datetime.fromtimestamp(ts).strftime(fmt)
    except (OSError, OverflowError, ValueError, TypeError):
        return fallback


def _local_day_key(ts: float) -> str | None:
    """Khoá ``YYYY-MM-DD`` của ngày địa phương; ``None`` nếu không biểu diễn được."""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError, TypeError):
        return None


def _finite_or_none(value: Any) -> float | None:
    """Ép về ``float``; ``None``/NaN/vô cực → ``None``."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _empty_history(
    range_key: str, message: str = "Chưa có dữ liệu."
) -> dict[str, Any]:
    """Kết quả rỗng nhưng cùng hình dạng với :meth:`Storage.history`."""
    unit = "hour" if range_key == "today" else "day"
    return {
        "range": range_key,
        "unit": unit,
        "labels": [],
        "good_pct": [],
        "avg_score": [],
        "absent_s": [],
        "distance_cm_avg": [],
        "has_data": False,
        "message": message,
    }


def _pack_stat_series(
    range_key: str,
    unit: str,
    entries: Iterable[tuple[str, Mapping[str, float | int | None] | None]],
) -> dict[str, Any]:
    """Đóng gói danh sách ``(label, raw_values_or_none)`` thành mảng song song.

    Dùng chung cho cả tổng hợp theo giờ (``today``) lẫn theo ngày (``7d``) để
    hình dạng JSON trả về của hai đường không bao giờ lệch nhau.
    """
    result: dict[str, Any] = {
        "range": range_key,
        "unit": unit,
        "labels": [],
        "good_pct": [],
        "avg_score": [],
        "absent_s": [],
        "distance_cm_avg": [],
        "has_data": True,
    }
    for label, values in entries:
        result["labels"].append(label)
        if values is None:
            for key in _STAT_SERIES_KEYS:
                result[key].append(None)
        else:
            summary = Storage._weighted(values)
            for key in _STAT_SERIES_KEYS:
                result[key].append(summary[key])
    return result


#: Thông báo trả cho dashboard khi ``clock`` nằm ngoài dải biểu diễn được.
CLOCK_OUT_OF_RANGE_MESSAGE = (
    "Không xác định được mốc ngày: đồng hồ hệ thống trả về giá trị nằm ngoài "
    "dải thời gian hợp lệ. Kiểm tra đồng hồ của thiết bị rồi tải lại trang."
)


class Storage:
    """Ghi và đọc thống kê tư thế trong SQLite."""

    def __init__(
        self,
        config,
        clock: Callable[[], float] | None = None,
    ) -> None:
        storage_cfg = getattr(config, "storage", config)
        self.db_path = Path(str(getattr(storage_cfg, "db_path")))
        self.retention_days = int(getattr(storage_cfg, "retention_days", 30))
        self._clock = clock or time.time

        self._conn: sqlite3.Connection | None = None
        #: Khoá bảo vệ **mọi** lần chạm ``self._conn`` xuyên luồng.
        self._db_lock = threading.RLock()
        self._session_id: int | None = None
        self._last_record_ts: float | None = None
        self._buckets: dict[int, _Bucket] = {}
        self._pending_events: deque[tuple[Any, ...]] = deque(
            maxlen=MAX_PENDING_ROWS
        )
        self._last_flush_ts = 0.0
        self._dropped_rows = 0
        self._warned_bad_clock = False

    # ------------------------------------------------------------------
    # Vòng đời
    # ------------------------------------------------------------------
    @property
    def session_id(self) -> int | None:
        """Id phiên đang mở, ``None`` khi chưa mở DB."""
        return self._session_id

    @property
    def is_open(self) -> bool:
        """Có kết nối ghi đang mở hay không."""
        return self._conn is not None

    def open(self) -> None:
        """Mở DB, tạo schema, dọn dữ liệu cũ và mở một phiên mới."""
        if self._conn is not None:
            return

        try:
            parent = self.db_path.parent
            if str(parent):
                parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=5.0,
                isolation_level=None,
                check_same_thread=False,
            )
        except (OSError, sqlite3.Error) as exc:
            _logger.error(
                "Không mở được cơ sở dữ liệu '%s': %s. Hệ thống vẫn chạy "
                "nhưng sẽ không lưu thống kê.",
                self.db_path,
                exc,
            )
            return

        self._conn = conn
        try:
            with self._db_lock:
                conn.row_factory = sqlite3.Row
                mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if str(mode).lower() != "wal":
                    _logger.warning(
                        "SQLite không bật được WAL (chế độ hiện tại: %s); vẫn "
                        "chạy nhưng trang web có thể phải chờ khi đang ghi.",
                        mode,
                    )
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(_SCHEMA)

                self._close_orphan_sessions()
                self._session_id = self._start_session()
                self._last_flush_ts = float(self._clock())
                removed = self.cleanup_retention()
            _logger.info(
                "Đã mở cơ sở dữ liệu '%s' (phiên %s), dọn %d dòng quá hạn.",
                self.db_path,
                self._session_id,
                removed,
            )
        except sqlite3.Error as exc:
            _logger.error(
                "Không khởi tạo được schema/lọc dữ liệu trên '%s': %s. "
                "Hệ thống vẫn chạy nhưng sẽ không lưu thống kê.",
                self.db_path,
                exc,
            )
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
            self._session_id = None

    def close(self) -> None:
        """Ghi nốt phần còn lại, đóng phiên và đóng kết nối."""
        if self._conn is None:
            return

        try:
            self.flush()
        except sqlite3.Error as exc:
            _logger.error("Không ghi nốt được dữ liệu trước khi đóng: %s", exc)

        with self._db_lock:
            conn = self._conn
            if conn is None:
                return
            try:
                if self._session_id is not None:
                    conn.execute(
                        "UPDATE sessions SET end_ts = ? "
                        "WHERE id = ? AND end_ts IS NULL",
                        (float(self._clock()), self._session_id),
                    )
            except sqlite3.Error as exc:
                _logger.error(
                    "Không đóng được phiên %s: %s", self._session_id, exc
                )

            try:
                conn.close()
            except sqlite3.Error as exc:
                _logger.error("Không đóng được kết nối cơ sở dữ liệu: %s", exc)
            finally:
                self._conn = None
                self._session_id = None
                self._buckets.clear()
                self._pending_events.clear()
                self._last_record_ts = None

    def __enter__(self) -> "Storage":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Ghi dữ liệu
    # ------------------------------------------------------------------
    def record(
        self,
        update: StateUpdate,
        distance_cm: float | None = None,
    ) -> None:
        """Nạp một :class:`StateUpdate` và (tùy chọn) khoảng cách siêu âm."""
        if self._conn is None:
            return

        now = float(self._clock())
        present = update.state != STATE_ABSENT and ABSENT not in update.labels
        good = present and update.state == STATE_GOOD
        score = None if not present else _finite_or_none(update.score)
        distance = _finite_or_none(distance_cm)

        try:
            self._ingest_span(now, present, good, score, distance)
            for event in update.events:
                self._queue_event(now, event)
            self._maybe_flush(now)
        except sqlite3.Error as exc:
            _logger.error("Lỗi khi ghi thống kê: %s", exc)
        except (TypeError, ValueError) as exc:
            _logger.error("Dữ liệu thống kê không hợp lệ, bỏ qua: %s", exc)

    def record_event(
        self, event: Event, now: float | None = None
    ) -> None:
        """Ghi một sự kiện rời (dùng khi tầng alerts phát sự kiện riêng)."""
        if self._conn is None:
            return
        moment = float(self._clock()) if now is None else float(now)
        try:
            self._queue_event(moment, event)
            self._maybe_flush(moment)
        except sqlite3.Error as exc:
            _logger.error("Lỗi khi ghi sự kiện: %s", exc)
        except (TypeError, ValueError) as exc:
            _logger.error("Sự kiện không hợp lệ, bỏ qua: %s", exc)

    def flush(self) -> None:
        """Ghi toàn bộ hàng đợi xuống DB trong một giao dịch."""
        if self._conn is None:
            return

        rows = [
            (
                self._session_id,
                bucket.minute_ts,
                bucket.good_pct,
                bucket.avg_score,
                round(bucket.absent_s, 3),
                bucket.distance_cm_avg,
            )
            for bucket in self._buckets.values()
            if bucket.has_data
        ]
        events = list(self._pending_events)

        if not rows and not events:
            self._last_flush_ts = float(self._clock())
            return

        try:
            with self._db_lock:
                if self._conn is None:
                    return
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    if events:
                        self._conn.executemany(
                            "INSERT INTO events "
                            "(session_id, ts, type, label, duration_s, extra_json) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            events,
                        )
                    if rows:
                        self._conn.executemany(
                            "INSERT INTO minute_stats "
                            "(session_id, minute_ts, good_pct, avg_score, "
                            "absent_s, distance_cm_avg) "
                            "VALUES (?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT(session_id, minute_ts) DO UPDATE SET "
                            "good_pct = excluded.good_pct, "
                            "avg_score = excluded.avg_score, "
                            "absent_s = excluded.absent_s, "
                            "distance_cm_avg = excluded.distance_cm_avg",
                            rows,
                        )
                    self._conn.commit()
                except sqlite3.Error:
                    self._conn.rollback()
                    raise
        except sqlite3.Error as exc:
            _logger.error(
                "Không ghi được lô dữ liệu (%d sự kiện, %d phút): %s. "
                "Sẽ thử lại ở lần ghi sau.",
                len(events),
                len(rows),
                exc,
            )
            self._last_flush_ts = float(self._clock())
            return

        self._pending_events.clear()
        if self._buckets:
            newest = max(self._last_record_ts or 0.0, self._clock())
            current_minute = self._minute_of(newest)
            for minute_ts in [
                key for key in self._buckets if key < current_minute
            ]:
                del self._buckets[minute_ts]
        self._last_flush_ts = float(self._clock())

    def cleanup_retention(self) -> int:
        """Xoá dữ liệu cũ hơn ``retention_days``; trả số dòng đã xoá."""
        if self._conn is None:
            return 0
        if self.retention_days <= 0:
            _logger.info(
                "retention_days=0: giữ toàn bộ dữ liệu, không dọn."
            )
            return 0

        cutoff = float(self._clock()) - self.retention_days * DAY_S
        removed = 0
        try:
            with self._db_lock:
                if self._conn is None:
                    return 0
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    removed += self._conn.execute(
                        "DELETE FROM events WHERE ts < ?", (cutoff,)
                    ).rowcount
                    removed += self._conn.execute(
                        "DELETE FROM minute_stats WHERE minute_ts < ?",
                        (cutoff,),
                    ).rowcount
                    cur = self._conn.execute(
                        "DELETE FROM sessions WHERE end_ts IS NOT NULL "
                        "AND end_ts < ?",
                        (cutoff,),
                    )
                    removed += cur.rowcount
                    self._conn.commit()
                except sqlite3.Error:
                    self._conn.rollback()
                    raise
        except sqlite3.Error as exc:
            _logger.error("Không dọn được dữ liệu quá hạn: %s", exc)
            return 0
        if removed:
            _logger.info(
                "Đã xoá %d dòng cũ hơn %d ngày (trước %s).",
                removed,
                self.retention_days,
                _format_local(cutoff, "%Y-%m-%d %H:%M", "mốc không xác định"),
            )
        return removed

    # ------------------------------------------------------------------
    # Đọc dữ liệu cho dashboard
    # ------------------------------------------------------------------
    def violations(
        self,
        limit: int = 100,
        kinds: Sequence[str] | None = None,
        since_ts: float | None = None,
    ) -> list[dict[str, Any]]:
        """Lịch sử **vi phạm** trong giờ học, mới nhất trước."""
        if self._conn is None:
            return []
        try:
            wanted = int(limit)
        except (TypeError, ValueError):
            return []
        if wanted <= 0:
            return []

        allowed = (
            list(VIOLATION_KIND_CODES)
            if kinds is None
            else [str(kind) for kind in kinds]
        )
        if not allowed:
            return []

        if self._pending_events:
            self.flush()

        placeholders = ", ".join("?" for _ in allowed)
        sql = (
            "SELECT ts, type, duration_s FROM events "
            f"WHERE type IN ({placeholders})"
        )
        params: list[Any] = list(allowed)
        if since_ts is not None:
            moment = _finite_or_none(since_ts)
            if moment is not None:
                sql += " AND ts >= ?"
                params.append(float(moment))
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(wanted)

        try:
            with self._db_lock:
                if self._conn is None:
                    return []
                rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            _logger.error("Không đọc được lịch sử vi phạm: %s", exc)
            return []
        return [
            {
                "ts": float(row[0]),
                "kind": str(row[1]),
                "duration_s": float(row[2] or 0.0),
            }
            for row in rows
        ]

    def history(
        self, range_key: str = "today", now: float | None = None
    ) -> dict[str, Any]:
        """Số liệu cho biểu đồ của dashboard."""
        if range_key not in ("today", "7d"):
            raise ValueError(
                f"range phải là 'today' hoặc '7d', nhận được {range_key!r}."
            )

        raw_moment = self._clock() if now is None else now
        moment = _finite_or_none(raw_moment)
        if moment is None:
            self._warn_bad_clock(raw_moment)
            return _empty_history(range_key, CLOCK_OUT_OF_RANGE_MESSAGE)

        midnight = _local_midnight(moment)
        if midnight is None:
            self._warn_bad_clock(raw_moment)
            return _empty_history(range_key, CLOCK_OUT_OF_RANGE_MESSAGE)
        if range_key == "today":
            start = midnight
            end = midnight + DAY_S
        else:
            start = midnight - (HISTORY_7D_DAYS - 1) * DAY_S
            end = midnight + DAY_S

        try:
            rows = self._query_hours(start, end)
        except (sqlite3.Error, OSError) as exc:
            _logger.error("Không đọc được số liệu lịch sử: %s", exc)
            result = _empty_history(range_key)
            result["message"] = "Không đọc được cơ sở dữ liệu."
            return result

        if not rows:
            return _empty_history(range_key)

        if range_key == "today":
            return self._build_hourly(rows, midnight, moment)
        return self._build_daily(rows, start, moment)

    def _warn_bad_clock(self, raw_moment: Any) -> None:
        """Cảnh báo **một lần** rằng ``clock`` không dùng để tính mốc ngày được."""
        if self._warned_bad_clock:
            return
        self._warned_bad_clock = True
        _logger.warning(
            "Đồng hồ trả về mốc %r không dùng được để xác định mốc ngày "
            "(ngoài dải datetime biểu diễn được); dashboard sẽ tạm hiện "
            "trống cho tới khi đồng hồ hợp lệ trở lại.",
            raw_moment,
        )

    # ------------------------------------------------------------------
    # Nội bộ — ghi
    # ------------------------------------------------------------------
    @staticmethod
    def _minute_of(ts: float) -> int:
        return int(ts // MINUTE_S) * MINUTE_S

    def _bucket_for(self, ts: float) -> _Bucket:
        minute_ts = self._minute_of(ts)
        bucket = self._buckets.get(minute_ts)
        if bucket is None:
            bucket = _Bucket(minute_ts=minute_ts)
            self._buckets[minute_ts] = bucket
        return bucket

    def _ingest_span(
        self,
        now: float,
        present: bool,
        good: bool,
        score: float | None,
        distance_cm: float | None,
    ) -> None:
        """Chia khoảng thời gian từ lần ghi trước tới ``now`` theo phút."""
        previous = self._last_record_ts
        self._last_record_ts = now

        if previous is None:
            gap = 0.0
        else:
            gap = now - previous
            if not math.isfinite(gap) or gap < 0.0:
                gap = 0.0
            gap = min(gap, MAX_FRAME_GAP_S)

        already = 0.0
        if gap > 0.0 and previous is not None:
            cursor = previous
            while already < gap:
                minute_ts = self._minute_of(cursor)
                boundary = float(minute_ts + MINUTE_S)
                span = min(boundary - cursor, gap - already)
                if span <= 0.0:
                    break
                bucket = self._bucket_for(cursor)
                if present:
                    bucket.present_s += span
                    if good:
                        bucket.good_s += span
                    if score is not None:
                        bucket.score_sum += score * span
                else:
                    bucket.absent_s += span
                cursor += span
                already += span
        else:
            self._bucket_for(now)

        if distance_cm is not None:
            bucket = self._bucket_for(now)
            bucket.distance_sum += distance_cm
            bucket.distance_n += 1

    def _queue_event(self, now: float, event: Event) -> None:
        extra = {
            "level": int(getattr(event, "level", 1)),
            "alert": bool(getattr(event, "alert", False)),
            "source_ts": float(getattr(event, "ts", now)),
        }
        if len(self._pending_events) == MAX_PENDING_ROWS:
            self._dropped_rows += 1
            if self._dropped_rows == 1 or self._dropped_rows % 100 == 0:
                _logger.warning(
                    "Hàng đợi sự kiện đã đầy (%d dòng); đã bỏ %d sự kiện cũ "
                    "nhất vì DB đang lỗi.",
                    MAX_PENDING_ROWS,
                    self._dropped_rows,
                )

        label = getattr(event, "label", None)
        duration = _finite_or_none(getattr(event, "duration_s", 0.0)) or 0.0
        self._pending_events.append(
            (
                self._session_id,
                float(now),
                str(getattr(event, "type", "unknown")),
                None if label is None else str(label),
                float(duration),
                json.dumps(extra, ensure_ascii=False),
            )
        )

    def _maybe_flush(self, now: float) -> None:
        if now - self._last_flush_ts >= FLUSH_INTERVAL_S:
            self.flush()

    def _close_orphan_sessions(self) -> None:
        """Đóng các phiên còn ``end_ts IS NULL`` do tiến trình trước chết."""
        assert self._conn is not None
        orphans = self._conn.execute(
            "SELECT id, start_ts FROM sessions WHERE end_ts IS NULL"
        ).fetchall()
        for row in orphans:
            session_id = int(row["id"])
            start_ts = float(row["start_ts"])
            last_event = self._conn.execute(
                "SELECT MAX(ts) AS ts FROM events WHERE session_id = ?",
                (session_id,),
            ).fetchone()["ts"]
            last_minute = self._conn.execute(
                "SELECT MAX(minute_ts) AS ts FROM minute_stats "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()["ts"]
            candidates = [
                float(value)
                for value in (last_event, last_minute)
                if value is not None
            ]
            end_ts = max(candidates) if candidates else start_ts
            end_ts = max(end_ts, start_ts)
            self._conn.execute(
                "UPDATE sessions SET end_ts = ? WHERE id = ?",
                (end_ts, session_id),
            )
            _logger.warning(
                "Phiên %d của lần chạy trước chưa được đóng (tiến trình có "
                "thể đã bị dừng đột ngột); đã đóng tạm ở %s dựa trên dữ liệu "
                "cuối cùng ghi được.",
                session_id,
                _format_local(
                    end_ts, "%Y-%m-%d %H:%M:%S", "mốc không xác định"
                ),
            )

    def _start_session(self) -> int | None:
        assert self._conn is not None
        cursor = self._conn.execute(
            "INSERT INTO sessions (start_ts, end_ts) VALUES (?, NULL)",
            (float(self._clock()),),
        )
        return int(cursor.lastrowid) if cursor.lastrowid is not None else None

    # ------------------------------------------------------------------
    # Nội bộ — đọc
    # ------------------------------------------------------------------
    def _query_hours(self, start: float, end: float) -> list[sqlite3.Row]:
        """Gộp ``minute_stats`` thành từng giờ, kèm trọng số thời gian có người."""
        if not self.db_path.is_file():
            return []
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            weight = (
                "CASE WHEN 60.0 - absent_s > 0.0 "
                "THEN 60.0 - absent_s ELSE 0.0 END"
            )
            return conn.execute(
                f"""
                SELECT
                    (minute_ts / 3600) * 3600 AS hour_ts,
                    SUM(absent_s) AS absent_s,
                    SUM(CASE WHEN good_pct IS NOT NULL THEN {weight}
                             ELSE 0.0 END) AS good_w,
                    SUM(CASE WHEN good_pct IS NOT NULL
                             THEN good_pct * ({weight}) ELSE 0.0 END)
                        AS good_sum,
                    SUM(CASE WHEN avg_score IS NOT NULL THEN {weight}
                             ELSE 0.0 END) AS score_w,
                    SUM(CASE WHEN avg_score IS NOT NULL
                             THEN avg_score * ({weight}) ELSE 0.0 END)
                        AS score_sum,
                    SUM(CASE WHEN distance_cm_avg IS NOT NULL THEN {weight}
                             ELSE 0.0 END) AS dist_w,
                    SUM(CASE WHEN distance_cm_avg IS NOT NULL
                             THEN distance_cm_avg * ({weight}) ELSE 0.0 END)
                        AS dist_sum
                FROM minute_stats
                WHERE minute_ts >= ? AND minute_ts < ?
                GROUP BY hour_ts
                ORDER BY hour_ts
                """,
                (int(start), int(end)),
            ).fetchall()
        finally:
            conn.close()

    @staticmethod
    def _ratio(total: float | None, weight: float | None) -> float | None:
        if total is None or weight is None or weight <= 0.0:
            return None
        return round(total / weight, 2)

    @staticmethod
    def _weighted(values: Mapping[str, float | int | None]) -> dict:
        return {
            "good_pct": Storage._ratio(
                values["good_sum"], values["good_w"]
            ),
            "avg_score": Storage._ratio(
                values["score_sum"], values["score_w"]
            ),
            "distance_cm_avg": Storage._ratio(
                values["dist_sum"], values["dist_w"]
            ),
            "absent_s": round(float(values["absent_s"] or 0.0), 1),
        }

    def _build_hourly(
        self, rows: Iterable[sqlite3.Row], midnight: float, now: float
    ) -> dict[str, Any]:
        by_hour = {int(row["hour_ts"]): row for row in rows}
        last_hour = min(
            int(now // 3600) * 3600,
            int(midnight + DAY_S - 3600),
        )
        entries: list[tuple[str, Mapping[str, float | int | None] | None]] = []
        hour = int(midnight)
        while hour <= last_hour:
            entries.append(
                (_format_local(hour, "%H:00", "--:--"), by_hour.get(hour))
            )
            hour += 3600
        return _pack_stat_series("today", "hour", entries)

    def _build_daily(
        self, rows: Iterable[sqlite3.Row], start: float, now: float
    ) -> dict[str, Any]:
        days: dict[str, dict[str, float]] = {}
        for row in rows:
            day = _local_day_key(int(row["hour_ts"]))
            if day is None:
                continue
            bucket = days.setdefault(
                day,
                {
                    "absent_s": 0.0,
                    "good_w": 0.0,
                    "good_sum": 0.0,
                    "score_w": 0.0,
                    "score_sum": 0.0,
                    "dist_w": 0.0,
                    "dist_sum": 0.0,
                },
            )
            for key in bucket:
                bucket[key] += float(row[key] or 0.0)

        entries: list[tuple[str, Mapping[str, float | int | None] | None]] = []
        for index in range(HISTORY_7D_DAYS):
            day_ts = start + index * DAY_S
            key = _local_day_key(day_ts)
            values = days.get(key) if key is not None else None
            entries.append((_format_local(day_ts, "%d/%m", "--/--"), values))
        return _pack_stat_series("7d", "day", entries)


__all__ = [
    "CLOCK_OUT_OF_RANGE_MESSAGE",
    "DAY_S",
    "FLUSH_INTERVAL_S",
    "HISTORY_7D_DAYS",
    "MAX_FRAME_GAP_S",
    "MAX_PENDING_ROWS",
    "MINUTE_S",
    "STATE_ABSENT",
    "STATE_BAD",
    "STATE_GOOD",
    "STATE_WARN",
    "Storage",
    "VIOLATION_KIND_CODES",
    "_format_local",
    "_local_day_key",
    "_local_midnight",
    "_pack_stat_series",
]
