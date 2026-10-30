"""Phiên học bật/tắt bằng tay: đếm ngược theo thời lượng đặt trước.

Trước mô-đun này hệ thống chỉ có **khung giờ học** (:mod:`posture_monitor.schedule`):
một lịch theo tuần, tự động, không ai bấm gì. Yêu cầu mới là ngược lại — người
dùng ngồi xuống, chọn thời lượng, bấm **Bắt đầu**, hết giờ thì hệ thống tự
dừng và báo một câu (ghi log + hiện trên dashboard). Vì vậy hai khái niệm tồn
tại song song và **không** thay thế nhau:

- ``schedule`` trả lời "bây giờ có nằm trong giờ được phép cảnh báo không".
- :class:`StudySession` trả lời "có ai đang mở phiên học ngay lúc này không".

Cổng cuối cùng là **hội** của hai: ngoài giờ học thì không cảnh báo, và chưa
bấm Bắt đầu thì cũng không (xem ``_monitor_loop``).

Bốn quyết định thiết kế
-----------------------

**1. Module thuần.** Không đọc file, không đọc đồng hồ hệ thống, không phụ
thuộc camera/model/Flask. Mọi thời điểm đến từ tham số ``now``. Nhờ vậy test
điều khiển được thời gian mà không phải ``sleep``.

**2. Trạng thái nằm sau một khóa.** Vòng lặp camera đọc trạng thái mỗi khung
(5–6 lần/giây) trong khi nút bấm trên web ghi ở một luồng khác. Không khóa thì
lúc chuyển phiên có thể đọc ra cặp ``(đang chạy, hết hạn)`` không tồn tại.

**3. Hết giờ là **tự dừng**, không phải "vẫn chạy nhưng báo hết".** Đây là
điểm dễ hiểu sai nhất: người dùng đặt 60 phút để học, không phải để hệ thống
nhắc "đã hết 60 phút" rồi tiếp tục phân tích tư thế thêm hai tiếng. Khi
``now >= ends_at``, :meth:`StudySession.tick` chuyển sang ``FINISHED`` **một
lần** và trả tín hiệu để tầng gọi phát câu thông báo.

**4. ``FINISHED`` khác ``IDLE``.** Cả hai đều "không chạy model", nhưng
``FINISHED`` còn giữ thời lượng đã đặt và số phút đã học để dashboard hiện
"Đã học xong 60 phút". Gộp hai trạng thái sẽ khiến màn hình nhảy về "Chưa bắt
đầu" ngay sau khi hết giờ, người dùng không biết phiên vừa rồi có thành công
hay bị lỗi.

Về ``now``
----------

Mọi mốc thời gian trong module là **giây đơn điệu** (``time.monotonic``), không
phải ``datetime``. Lý do: đây là đo **khoảng** thời gian ("còn 42 phút"), không
phải ghi mốc lịch sự ("lúc 19:03"). ``monotonic`` không nhảy khi đồng hồ hệ
thống được chỉnh (NTP, đổi giờ mùa), nên phiên 60 phút không bị kéo dài hay cắt
ngắn vì một lần chỉnh giờ.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

#: Chưa từng bắt đầu phiên nào (hoặc đã bấm Dừng và xoá trạng thái).
STATE_IDLE = "idle"
#: Đang trong phiên: model AI chạy, cảnh báo được phép phát.
STATE_RUNNING = "running"
#: Đã hết thời lượng đặt trước. Vẫn giữ số liệu để hiện tổng kết.
STATE_FINISHED = "finished"

#: Thời lượng ngắn nhất cho một phiên, tính bằng phút.
#: Dưới mức này thì ``hold_s`` của cảnh báo điện thoại (1–2 s) và thời gian
#: khởi động model đã ăn hết phiên, người dùng không kịp thấy gì.
MIN_MINUTES = 1
#: Thời lượng dài nhất, tính bằng phút (12 giờ). Không phải giới hạn kỹ thuật
#: mà là chốt chống gõ nhầm ``600`` thành ``6000`` (bốn ngày) rồi bỏ quên.
MAX_MINUTES = 720
#: Thời lượng mặc định khi dashboard mở lần đầu, tính bằng phút.
DEFAULT_MINUTES = 60

#: Câu thông báo khi phiên hết giờ. Viết ở đây để **một** nguồn: vòng lặp ghi
#: câu này vào log, web hiện nó (``finish_text``), hai nơi không lệch nhau.
#:
#: Câu này **chưa** được đọc ra loa camera: ba câu cảnh báo
#: (``leave_frame``/``phone``/``stranger``) mới có bản thu, còn câu "hết giờ"
#: chưa có file và cũng không nằm trong ``speaker_alert.ALERT_TEXT`` nên không
#: đi qua đường phát. Muốn nói ra loa thì phải thêm một loại cảnh báo thứ tư
#: (bản thu hoặc espeak) — đó là thay đổi có chủ đích, không tự thêm.
FINISHED_MESSAGE = "Đã hết giờ học. Nghỉ ngơi nhé."


class StudySessionError(ValueError):
    """Thời lượng phiên không hợp lệ (người dùng sửa được)."""


def normalise_minutes(value: Any) -> int:
    """Kiểm tra thời lượng phiên, trả số **phút** nguyên.

    Chấp nhận ``int`` và ``float`` tròn (``60.0``); từ chối ``bool`` (vì
    ``True`` là ``1`` trong Python và người dùng gõ ``true`` không có nghĩa là
    "một phút"), chuỗi, ``NaN``/``inf`` và giá trị ngoài
    :data:`MIN_MINUTES`–:data:`MAX_MINUTES`.

    Raises:
        StudySessionError: khi giá trị không dùng được, kèm câu tiếng Việt chỉ
            đúng khoảng hợp lệ.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudySessionError(
            "Thời lượng phiên học phải là số phút, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise StudySessionError(
            f"Thời lượng phiên học phải là số hữu hạn, nhận được {value!r}."
        )
    rounded = int(round(number))
    if abs(number - rounded) > 1e-9:
        raise StudySessionError(
            f"Thời lượng phiên học phải là số phút nguyên, nhận được {value!r}."
        )
    if not MIN_MINUTES <= rounded <= MAX_MINUTES:
        raise StudySessionError(
            f"Thời lượng phiên học phải trong khoảng {MIN_MINUTES}–"
            f"{MAX_MINUTES} phút, nhận được {rounded} phút."
        )
    return rounded


@dataclass(frozen=True)
class SessionSnapshot:
    """Ảnh chụp trạng thái phiên tại một thời điểm.

    Attributes:
        state: một trong :data:`STATE_IDLE`, :data:`STATE_RUNNING`,
            :data:`STATE_FINISHED`.
        minutes: thời lượng đã đặt (phút); ``0`` khi chưa từng bắt đầu.
        remaining_s: số giây còn lại; ``0.0`` khi không chạy.
        elapsed_s: số giây đã trôi trong phiên (dừng lại khi hết giờ).
        ends_in_text: chuỗi ``"MM:SS"`` cho UI, hoặc ``None`` khi không chạy.
        finished_message: câu thông báo khi vừa hết giờ ở lần :meth:`tick`
            này; ``None`` ở mọi lần khác. Tầng gọi đọc trường này **một lần**
            để ghi log và hiện trên web — không tự so sánh ``ends_at`` nữa.
    """

    state: str
    minutes: int
    remaining_s: float
    elapsed_s: float
    ends_in_text: str | None
    finished_message: str | None


#: Ảnh chụp của một phiên chưa từng chạy.
IDLE_SNAPSHOT = SessionSnapshot(
    state=STATE_IDLE,
    minutes=0,
    remaining_s=0.0,
    elapsed_s=0.0,
    ends_in_text=None,
    finished_message=None,
)


def _format_countdown(seconds: float) -> str:
    """``"MM:SS"`` cho UI; làm tròn **lên** để 0,4 s còn lại không hiện ``00:00``."""
    total = max(0, int(math.ceil(seconds - 1e-9)))
    return f"{total // 60:02d}:{total % 60:02d}"


class StudySession:
    """Bộ đếm một phiên học, an toàn đa luồng.

    Vòng lặp camera gọi :meth:`tick` mỗi khung; Flask gọi :meth:`start`,
    :meth:`stop`, :meth:`snapshot` khi người dùng bấm nút.

    Args:
        default_minutes: thời lượng gợi ý cho lần bắt đầu khi người dùng không
            truyền; phải qua :func:`normalise_minutes`.
        clock: hàm trả giây đơn điệu (mặc định ``time.monotonic``). Tiêm để
            test tất định.

    Raises:
        StudySessionError: khi ``default_minutes`` ngoài khoảng cho phép.
    """

    def __init__(
        self,
        default_minutes: int = DEFAULT_MINUTES,
        *,
        clock: Any = None,
    ) -> None:
        self._default_minutes = normalise_minutes(default_minutes)
        if clock is None:
            import time  # noqa: PLC0415 - chỉ cần khi không tiêm đồng hồ

            clock = time.monotonic
        self._clock = clock
        self._lock = threading.Lock()

        self._state = STATE_IDLE
        self._minutes = 0
        self._started_at: float | None = None
        self._ends_at: float | None = None
        #: Đã phát câu "hết giờ" cho phiên hiện tại chưa. Chốt để câu đó chỉ ra
        #: loa **một lần**, dù ``tick`` còn được gọi vài khung sau khi hết giờ.
        #:
        #: Điều kiện phát là "``FINISHED`` **và** chưa báo", không phải "lần
        #: này vừa đổi trạng thái". Lý do: ``snapshot()`` cũng chuyển
        #: ``RUNNING`` → ``FINISHED`` (dashboard hỏi mỗi giây). Nếu ``tick`` chỉ
        #: báo ở lần chuyển, một lần poll của web đúng nhịp sẽ nuốt mất câu
        #: "hết giờ" — im lặng hoàn toàn, không lỗi, rất khó lần ra.
        self._finish_announced = False

    # -- đọc ------------------------------------------------------------
    @property
    def state(self) -> str:
        """Trạng thái hiện tại (không tính việc hết giờ chưa được ``tick``)."""
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        """``True`` khi model AI nên chạy (đang trong phiên, chưa hết giờ)."""
        with self._lock:
            return self._state == STATE_RUNNING

    @property
    def default_minutes(self) -> int:
        return self._default_minutes

    def snapshot(self) -> SessionSnapshot:
        """Ảnh chụp trạng thái, **tự áp** việc hết giờ theo đồng hồ hiện tại.

        Đọc trạng thái phải phản ánh sự thật tại thời điểm gọi: nếu phiên đã
        quá ``ends_at`` thì ``state`` là ``FINISHED`` ngay cả khi vòng lặp
        chưa kịp ``tick`` (ví dụ camera đang chờ khung). Ngược lại dashboard
        sẽ hiện "còn 00:02" mãi mãi.

        Hàm này **không** phát câu thông báo — chỉ :meth:`tick` làm việc đó,
        để một lần ``GET /api/session`` không làm loa kêu.
        """
        with self._lock:
            now = float(self._clock())
            self._expire_locked(now)
            return self._snapshot_locked(now, finished_message=None)

    # -- ghi ------------------------------------------------------------
    def start(self, minutes: Any = None) -> SessionSnapshot:
        """Bắt đầu phiên mới, ghi đè phiên cũ nếu đang chạy.

        Args:
            minutes: thời lượng (phút); ``None`` dùng ``default_minutes``.

        Returns:
            Ảnh chụp ngay sau khi bắt đầu (``state == STATE_RUNNING``).

        Raises:
            StudySessionError: khi ``minutes`` không hợp lệ.
        """
        wanted = (
            self._default_minutes if minutes is None else normalise_minutes(minutes)
        )
        with self._lock:
            now = float(self._clock())
            self._state = STATE_RUNNING
            self._minutes = wanted
            self._started_at = now
            self._ends_at = now + wanted * 60.0
            self._finish_announced = False
            return self._snapshot_locked(now, finished_message=None)

    def stop(self) -> SessionSnapshot:
        """Dừng phiên và quay về :data:`STATE_IDLE` (xoá số liệu đã đặt).

        Dùng khi người dùng chủ động nghỉ giữa chừng. Khác hết giờ: hết giờ
        giữ lại tổng kết (:data:`STATE_FINISHED`), bấm Dừng thì không — người
        dùng vừa chủ động bỏ phiên, hiện "đã học 12 phút" là thông tin gây
        nhiễu chứ không phải thành tích.

        Gọi khi đang ``IDLE`` là no-op (bấm hai lần không lỗi).
        """
        with self._lock:
            self._state = STATE_IDLE
            self._minutes = 0
            self._started_at = None
            self._ends_at = None
            self._finish_announced = False
            return self._snapshot_locked(float(self._clock()), finished_message=None)

    def tick(self) -> SessionSnapshot:
        """Cập nhật theo đồng hồ; trả câu thông báo **một lần** khi phiên hết giờ.

        Vòng lặp camera gọi hàm này mỗi khung. Nó là nơi **duy nhất** phát
        sinh ``finished_message``, nên câu "đã hết giờ" không thể bị báo hai
        lần và cũng không thể bị bỏ qua vì dashboard không ai mở.

        Câu đó vẫn được trả ở lần gọi **sau** thời điểm hết giờ, kể cả khi
        :meth:`snapshot` (dashboard hỏi mỗi giây) đã kịp chuyển trạng thái
        sang ``FINISHED`` trước — xem ``_finish_announced``. Điều kiện là
        "đang ``FINISHED`` và chưa báo", không phải "lần này vừa đổi trạng
        thái"; nếu không, một lần poll đúng nhịp của web sẽ nuốt mất câu nói.
        """
        with self._lock:
            now = float(self._clock())
            self._expire_locked(now)
            if not self._finish_announced and self._state == STATE_FINISHED:
                self._finish_announced = True
                return self._snapshot_locked(now, finished_message=FINISHED_MESSAGE)
            return self._snapshot_locked(now, finished_message=None)

    # -- nội bộ ---------------------------------------------------------
    def _expire_locked(self, now: float) -> bool:
        """Chuyển ``RUNNING`` → ``FINISHED`` nếu đã quá giờ; trả ``True`` khi vừa đổi.

        Phải gọi trong ``self._lock``. Tách khỏi :meth:`tick` để
        :meth:`snapshot` dùng lại đúng một luật hết giờ.
        """
        if self._state != STATE_RUNNING:
            return False
        ends_at = self._ends_at
        if ends_at is None or now < ends_at:
            return False
        self._state = STATE_FINISHED
        return True

    def _snapshot_locked(
        self, now: float, *, finished_message: str | None
    ) -> SessionSnapshot:
        """Dựng ảnh chụp từ trạng thái đang giữ. Phải gọi trong ``self._lock``."""
        if self._state == STATE_RUNNING and self._ends_at is not None:
            remaining = max(0.0, self._ends_at - now)
            started = self._started_at if self._started_at is not None else now
            elapsed = max(0.0, now - started)
            return SessionSnapshot(
                state=STATE_RUNNING,
                minutes=self._minutes,
                remaining_s=remaining,
                elapsed_s=elapsed,
                ends_in_text=_format_countdown(remaining),
                finished_message=finished_message,
            )
        if self._state == STATE_FINISHED:
            total = float(self._minutes) * 60.0
            return SessionSnapshot(
                state=STATE_FINISHED,
                minutes=self._minutes,
                remaining_s=0.0,
                elapsed_s=total,
                ends_in_text=None,
                finished_message=finished_message,
            )
        return SessionSnapshot(
            state=STATE_IDLE,
            minutes=0,
            remaining_s=0.0,
            elapsed_s=0.0,
            ends_in_text=None,
            finished_message=finished_message,
        )


def payload(snapshot: SessionSnapshot) -> dict[str, Any]:
    """Đổi ảnh chụp thành dict thuần cho JSON của dashboard.

    Không có khoá nào là dữ liệu cá nhân: chỉ trạng thái, phút và chuỗi đếm
    ngược. ``finished_message`` được gửi kèm để web hiện **đúng** câu mà hệ
    thống vừa báo, nhưng web **không** được tự bịa câu khác.

    ``finish_text`` khác ``finished_message`` ở chỗ nó **bền**: có mặt ở mọi
    lần đọc trong lúc trạng thái là ``finished``, không chỉ đúng một lần
    ``tick`` vừa hết giờ. Web hỏi trạng thái mỗi giây nên rất dễ lỡ đúng lần
    duy nhất đó; không có trường này thì màn hình sẽ quay về "Chưa bắt đầu"
    ngay sau khi hết giờ (xem ``FINISHED`` khác ``IDLE`` ở đầu module).
    """
    return {
        "state": snapshot.state,
        "minutes": snapshot.minutes,
        "remaining_s": round(snapshot.remaining_s, 1),
        "elapsed_s": round(snapshot.elapsed_s, 1),
        "ends_in_text": snapshot.ends_in_text,
        "finished_message": snapshot.finished_message,
        "finish_text": (FINISHED_MESSAGE if snapshot.state == STATE_FINISHED else None),
    }
