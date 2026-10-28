"""Lưu thống kê tư thế vào SQLite (spec v2 §5.9).

Ba bảng đúng schema spec:

- ``sessions(id, start_ts, end_ts)`` — một dòng cho mỗi lần chạy.
- ``events(id, session_id, ts, type, label, duration_s, extra_json)`` — ghi cả
  lúc sự kiện bắt đầu lẫn lúc kết thúc.
- ``minute_stats(session_id, minute_ts, good_pct, avg_score, absent_s,
  distance_cm_avg)`` — tổng hợp theo phút.

**Chỉ lưu số liệu. Không lưu ảnh, không lưu video, không lưu khung hình**
(spec v2 §11.5). Module này không hề mở camera và không có cột nào chứa dữ
liệu hình ảnh; khung hình nếu cần xem thì đi qua ``/stream`` của
:mod:`posture_monitor.web` và mặc định bị tắt.

Quyết định thiết kế:

- **Đồng hồ thực (wall clock) do bên ngoài bơm vào.** Mốc thời gian ghi vào
  DB lấy từ ``clock`` (mặc định :func:`time.time`), **không** lấy từ
  ``StateUpdate.now`` — đồng hồ của máy trạng thái là đồng hồ nội bộ của
  pipeline và có thể là ``time.monotonic()``, không dùng để tính retention
  hay vẽ biểu đồ theo giờ/ngày được. Mốc gốc của sự kiện vẫn được giữ trong
  ``extra_json`` với khóa ``source_ts`` để đối chiếu khi cần.
- **Ghi theo lô 10 giây** (``FLUSH_INTERVAL_S``) để bảo vệ thẻ nhớ spec §5.9.
  Sự kiện và phút đã xong nằm trong hàng đợi; :meth:`Storage.flush` ghi một
  giao dịch, :meth:`Storage.close` ghi nốt phần còn lại.
- **``journal_mode=WAL`` + ``synchronous=NORMAL``.** WAL cho phép trang web
  đọc song song trong khi vòng lặp chính đang ghi, tránh khoá đọc/ghi lẫn
  nhau trên Pi; ``NORMAL`` giảm số lần fsync (thẻ nhớ bền hơn) mà vẫn an
  toàn khi tiến trình chết (chỉ mất tối đa giao dịch cuối chưa flush, đúng
  phần dữ liệu vốn đã nằm trong hàng đợi).
- **``avg_score`` loại khung ABSENT.** Spec §5.5 nói rõ ABSENT trả score 0
  "không phải tư thế tệ nhất"; nếu tính vào trung bình thì mỗi lần người dùng
  đứng dậy điểm trung bình tụt vô nghĩa. Thời gian vắng được đếm riêng vào
  ``absent_s``. Tương tự, ``good_pct`` lấy mẫu số là thời gian **có người**,
  nên ``good_pct`` cao không bị kéo xuống bởi lúc đi vắng.
- **Không bao giờ crash vì DB** (spec §11.4): mọi thao tác SQL nằm trong
  ``try/except sqlite3.Error``/``OSError``; lỗi được log rõ và hệ thống chạy
  tiếp. Nếu không mở được DB ngay từ đầu, mọi phương thức trở thành no-op.
- **Phiên mồ côi:** khi mở, mọi dòng ``sessions`` còn ``end_ts IS NULL`` bị
  coi là phiên của tiến trình đã chết đột ngột; ``end_ts`` được đóng bằng mốc
  muộn nhất có trong ``events``/``minute_stats`` của phiên đó (không có thì
  lấy ``start_ts``) và ghi log cảnh báo. Nhờ vậy lần chạy sau không tạo ra
  một phiên mới nằm chồng lên một phiên "đang mở" không có thật.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .classifier import ABSENT
from .logging_setup import get_logger
from .state import STATE_ABSENT, STATE_GOOD, Event, StateUpdate

_logger = get_logger(__name__)

#: Chu kỳ ghi theo lô (spec v2 §5.9).
FLUSH_INTERVAL_S = 10.0

#: Độ dài một phút, đơn vị giây.
MINUTE_S = 60

#: Khoảng cách tối đa giữa hai khung được tính vào thống kê. Nếu tiến trình bị
#: treo/ngủ dài, khoảng trống đó không phải thời gian quan sát được; cộng hết
#: vào một phút sẽ làm sai ``good_pct``/``absent_s``. Đây là hằng số bảo vệ dữ
#: liệu, không phải ngưỡng nghiệp vụ.
MAX_FRAME_GAP_S = 5.0

#: Số dòng tối đa giữ trong hàng đợi khi DB liên tục lỗi. Vượt mức thì bỏ dòng
#: cũ nhất và cảnh báo, để tiến trình giám sát không ăn hết RAM vì DB hỏng.
MAX_PENDING_ROWS = 2000

#: Số ngày trong khoảng "7 ngày" của dashboard.
HISTORY_7D_DAYS = 7

#: Số giây trong một ngày.
DAY_S = 86400

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
    """Bộ cộng dồn số liệu của một phút.

    ``present_s`` là thời gian **có người** (mẫu số của ``good_pct`` và
    ``avg_score``), ``score_sum`` là tổng ``score × dt`` để chia lại đúng
    trọng số thời gian.
    """

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


def _local_midnight(ts: float) -> float:
    """Mốc 00:00 giờ địa phương của ngày chứa ``ts``."""
    moment = datetime.fromtimestamp(ts).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return moment.timestamp()


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


def _empty_history(range_key: str) -> dict[str, Any]:
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
        "message": "Chưa có dữ liệu.",
    }


class Storage:
    """Ghi và đọc thống kê tư thế trong SQLite.

    Vòng lặp chính gọi :meth:`record` mỗi khung; web gọi :meth:`history` để
    vẽ biểu đồ. Hai bên dùng kết nối khác nhau: bên ghi giữ một kết nối suốt
    phiên, bên đọc mở kết nối ngắn hạn cho mỗi truy vấn (WAL cho phép đọc song
    song nên không chặn vòng lặp chính).
    """

    def __init__(
        self,
        config,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Khởi tạo nhưng **chưa** mở DB; gọi :meth:`open`.

        Args:
            config: :class:`posture_monitor.config.Config` hoặc trực tiếp
                ``StorageConfig``. Đường dẫn lấy từ ``config.storage.db_path``,
                không hardcode (spec §1).
            clock: hàm trả mốc thời gian thực (giây). Test truyền đồng hồ giả
                để kết quả tất định.
        """
        storage_cfg = getattr(config, "storage", config)
        self.db_path = Path(str(getattr(storage_cfg, "db_path")))
        self.retention_days = int(getattr(storage_cfg, "retention_days", 30))
        self._clock = clock or time.time

        self._conn: sqlite3.Connection | None = None
        self._session_id: int | None = None
        self._last_record_ts: float | None = None
        self._buckets: dict[int, _Bucket] = {}
        self._pending_events: deque[tuple[Any, ...]] = deque(
            maxlen=MAX_PENDING_ROWS
        )
        self._last_flush_ts = 0.0
        self._dropped_rows = 0

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
        """Mở DB, tạo schema, dọn dữ liệu cũ và mở một phiên mới.

        Không raise khi DB lỗi/khoá/không ghi được: log lỗi và để mọi phương
        thức sau đó thành no-op (spec §11.4).
        """
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
            conn.row_factory = sqlite3.Row
            # busy_timeout: chờ thay vì báo "database is locked" ngay khi web
            # đang đọc. WAL: đọc/ghi song song, hợp với một luồng ghi liên tục.
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
            # Bắt đầu đếm chu kỳ ghi từ lúc mở phiên: nếu để 0.0 thì lần ghi
            # đầu tiên (clock thực là số lớn) sẽ flush ngay, phá đúng ý định
            # "ghi theo lô 10 giây".
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
        """Ghi nốt phần còn lại, đóng phiên và đóng kết nối.

        An toàn khi gọi nhiều lần; không raise.
        """
        if self._conn is None:
            return

        try:
            self.flush()
        except sqlite3.Error as exc:  # phòng thủ: flush đã tự bắt lỗi
            _logger.error("Không ghi nốt được dữ liệu trước khi đóng: %s", exc)

        try:
            if self._session_id is not None:
                self._conn.execute(
                    "UPDATE sessions SET end_ts = ? "
                    "WHERE id = ? AND end_ts IS NULL",
                    (float(self._clock()), self._session_id),
                )
        except sqlite3.Error as exc:
            _logger.error("Không đóng được phiên %s: %s", self._session_id, exc)

        try:
            self._conn.close()
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
        """Nạp một :class:`StateUpdate` và (tùy chọn) khoảng cách siêu âm.

        Thời gian giữa hai lần gọi được chia vào đúng (các) phút mà nó trải
        qua. Khung ``ABSENT`` cộng vào ``absent_s`` và **không** vào
        ``avg_score``. Sự kiện trong ``update.events`` được đưa vào hàng đợi
        ghi theo lô.

        Lỗi DB chỉ được log; hàm này không raise (spec §11.4).
        """
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
        """Ghi toàn bộ hàng đợi xuống DB trong một giao dịch.

        Gọi được bất cứ lúc nào (ví dụ trước khi tắt máy); không raise.
        """
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
            # isolation_level=None: mọi câu lệnh đều autocommit nếu không có
            # BEGIN. Ghi cả lô trong một giao dịch tường minh để thẻ nhớ chỉ
            # phải chốt (fsync) một lần.
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
            # Giữ nguyên hàng đợi để lần flush sau thử lại; chặn phình bộ nhớ
            # bằng MAX_PENDING_ROWS ở _queue_event.
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
        # Phút đã qua thì không còn khung nào rơi vào nữa: bỏ khỏi bộ nhớ để
        # lần flush sau không phải ghi lại. Phút hiện tại vẫn giữ vì còn đang
        # cộng dồn (ghi đè bằng ON CONFLICT nên không nhân đôi dữ liệu).
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
            # 0 = giữ toàn bộ; chỉ rõ ý nghĩa trong log để không ai hiểu nhầm
            # là "xoá sạch".
            _logger.info(
                "retention_days=0: giữ toàn bộ dữ liệu, không dọn."
            )
            return 0

        cutoff = float(self._clock()) - self.retention_days * DAY_S
        removed = 0
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                removed += self._conn.execute(
                    "DELETE FROM events WHERE ts < ?", (cutoff,)
                ).rowcount
                removed += self._conn.execute(
                    "DELETE FROM minute_stats WHERE minute_ts < ?", (cutoff,)
                ).rowcount
                # Chỉ xoá phiên đã đóng; phiên đang mở (end_ts NULL) phải giữ.
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
                datetime.fromtimestamp(cutoff).strftime("%Y-%m-%d %H:%M"),
            )
        return removed

    # ------------------------------------------------------------------
    # Đọc dữ liệu cho dashboard
    # ------------------------------------------------------------------
    def history(
        self, range_key: str = "today", now: float | None = None
    ) -> dict[str, Any]:
        """Số liệu cho biểu đồ của dashboard.

        Args:
            range_key: ``"today"`` (theo giờ) hoặc ``"7d"`` (theo ngày).
            now: mốc "hiện tại" (giây); mặc định lấy từ ``clock``.

        Returns:
            dict gồm ``range``, ``unit``, các mảng song song ``labels``,
            ``good_pct``, ``avg_score``, ``absent_s``, ``distance_cm_avg``,
            ``has_data`` và (khi rỗng) ``message``.

        Khi nhiều phút gộp vào một giờ/ngày, ``good_pct`` và ``avg_score``
        được lấy trung bình **có trọng số** theo thời gian có người của từng
        phút, xấp xỉ bằng ``max(0, 60 - absent_s)``. Nhờ vậy một phút vắng
        50 giây không kéo lệch cả giờ như khi lấy trung bình cộng đơn thuần.

        Không raise khi DB chưa có/chưa mở: trả kết quả rỗng kèm thông báo.
        """
        if range_key not in ("today", "7d"):
            raise ValueError(
                f"range phải là 'today' hoặc '7d', nhận được {range_key!r}."
            )

        moment = float(self._clock()) if now is None else float(now)
        midnight = _local_midnight(moment)
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
                    # Phòng thủ: không để vòng lặp quay vô hạn nếu dữ liệu
                    # thời gian bất thường.
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
            # Chưa có mốc trước (khung đầu) hoặc hai khung trùng thời điểm:
            # vẫn tạo bucket để mẫu khoảng cách có chỗ nằm.
            self._bucket_for(now)

        if distance_cm is not None:
            bucket = self._bucket_for(now)
            bucket.distance_sum += distance_cm
            bucket.distance_n += 1

    def _queue_event(self, now: float, event: Event) -> None:
        extra = {
            "level": int(getattr(event, "level", 1)),
            "alert": bool(getattr(event, "alert", False)),
            # Mốc gốc của pipeline, giữ để đối chiếu; ts trong bảng là giờ thực.
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
                datetime.fromtimestamp(end_ts).strftime("%Y-%m-%d %H:%M:%S"),
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
        """Gộp ``minute_stats`` thành từng giờ, kèm trọng số thời gian có người.

        Mở kết nối ngắn hạn riêng cho truy vấn đọc: Flask phục vụ trong
        thread khác với vòng lặp chính, và kết nối sqlite3 mặc định không
        dùng chéo thread. WAL cho phép đọc song song nên thao tác này không
        chặn vòng lặp ghi.
        """
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
        result = {
            "range": "today",
            "unit": "hour",
            "labels": [],
            "good_pct": [],
            "avg_score": [],
            "absent_s": [],
            "distance_cm_avg": [],
            "has_data": True,
        }
        hour = int(midnight)
        while hour <= last_hour:
            row = by_hour.get(hour)
            result["labels"].append(
                datetime.fromtimestamp(hour).strftime("%H:00")
            )
            if row is None:
                result["good_pct"].append(None)
                result["avg_score"].append(None)
                result["absent_s"].append(None)
                result["distance_cm_avg"].append(None)
            else:
                summary = self._weighted(row)
                result["good_pct"].append(summary["good_pct"])
                result["avg_score"].append(summary["avg_score"])
                result["absent_s"].append(summary["absent_s"])
                result["distance_cm_avg"].append(
                    summary["distance_cm_avg"]
                )
            hour += 3600
        return result

    def _build_daily(
        self, rows: Iterable[sqlite3.Row], start: float, now: float
    ) -> dict[str, Any]:
        days: dict[str, dict[str, float]] = {}
        for row in rows:
            day = datetime.fromtimestamp(int(row["hour_ts"])).strftime(
                "%Y-%m-%d"
            )
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

        result = {
            "range": "7d",
            "unit": "day",
            "labels": [],
            "good_pct": [],
            "avg_score": [],
            "absent_s": [],
            "distance_cm_avg": [],
            "has_data": True,
        }
        for index in range(HISTORY_7D_DAYS):
            day_ts = start + index * DAY_S
            key = datetime.fromtimestamp(day_ts).strftime("%Y-%m-%d")
            values = days.get(key)
            result["labels"].append(
                datetime.fromtimestamp(day_ts).strftime("%d/%m")
            )
            if values is None:
                result["good_pct"].append(None)
                result["avg_score"].append(None)
                result["absent_s"].append(None)
                result["distance_cm_avg"].append(None)
            else:
                summary = self._weighted(values)
                result["good_pct"].append(summary["good_pct"])
                result["avg_score"].append(summary["avg_score"])
                result["absent_s"].append(summary["absent_s"])
                result["distance_cm_avg"].append(
                    summary["distance_cm_avg"]
                )
        return result
