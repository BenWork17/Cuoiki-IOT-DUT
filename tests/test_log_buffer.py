"""Kiểm thử :mod:`posture_monitor.log_buffer` — bộ đệm log trong RAM.

Không cần camera, không cần mạng, **không dùng ``tmp_path``**: sandbox của máy
này chặn thư mục tạo bằng ``mkdir(mode=0o700)`` mà pytest luôn dùng mode đó.
Mọi bài ở đây chỉ dựng ``LogBuffer`` trong bộ nhớ và ghi ``LogRecord`` tổng
hợp, nên chạy được bằng lệnh trần.

Cái được khoá:

1. Giới hạn ``maxlen`` — bản ghi cũ nhất bị bỏ, không phải giữ vô hạn.
2. ``LogBuffer`` là ``logging.Handler`` thật, gắn được vào logger.
3. Format bản ghi đủ 4 khoá ``{ts, level, logger, message}`` với kiểu đúng.
4. Lọc theo mức ở tầng **đọc**, và bộ đệm vẫn giữ mọi mức.
5. REDACT: mật khẩu RTSP không được lọt ra bộ đệm.
6. Thread-safety cơ bản: nhiều luồng ghi đồng thời không mất/làm hỏng dữ liệu.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import log_buffer as lb  # noqa: E402
from posture_monitor.log_buffer import (  # noqa: E402
    DEFAULT_MAXLEN,
    DEFAULT_MIN_LEVEL,
    LEVEL_ORDER,
    LogBuffer,
    meets_level,
    normalize_level,
    short_logger_name,
)


def _record(
    message: str = "x",
    level: int = logging.WARNING,
    name: str = "posture_monitor.probe",
) -> logging.LogRecord:
    """``LogRecord`` tổng hợp — không cần logger thật."""
    return logging.LogRecord(
        name=name, level=level, pathname="", lineno=0, msg=message, args=None,
        exc_info=None,
    )


# --------------------------------------------------------------------------
# 1. Giữ tối đa N bản ghi
# --------------------------------------------------------------------------


def test_default_maxlen_is_500():
    """Mặc định giữ 500 bản ghi — khớp hằng của hợp đồng."""
    assert DEFAULT_MAXLEN == 500
    assert LogBuffer().maxlen == 500


def test_keeps_only_maxlen_oldest_dropped():
    """Ghi nhiều hơn ``maxlen`` thì bản ghi **cũ nhất** bị bỏ."""
    buf = LogBuffer(maxlen=3)

    for index in range(5):
        buf.emit(_record(f"m{index}"))

    assert len(buf) == 3
    messages = [item["message"] for item in buf.snapshot(min_level="DEBUG")]
    # Mới nhất trước: m4, m3, m2. m0 và m1 đã bị đẩy ra.
    assert messages == ["m4", "m3", "m2"]


def test_maxlen_non_positive_rejected():
    """``maxlen <= 0`` bị từ chối thay vì tạo deque vô dụng."""
    for bad in (0, -1):
        with pytest.raises(ValueError):
            LogBuffer(maxlen=bad)


def test_clear_empties_buffer():
    buf = LogBuffer(maxlen=10)
    buf.emit(_record("a"))
    buf.emit(_record("b"))

    buf.clear()

    assert len(buf) == 0
    assert buf.snapshot(min_level="DEBUG") == []


# --------------------------------------------------------------------------
# 2. Là logging.Handler thật
# --------------------------------------------------------------------------


def test_is_logging_handler_and_attaches_to_logger():
    """Gắn được vào logger và nhận bản ghi qua đường logging chuẩn."""
    buf = LogBuffer(maxlen=10)
    logger = logging.getLogger("posture_monitor.test_attach")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(buf)
    try:
        assert isinstance(buf, logging.Handler)
        logger.warning("qua duong logging")
    finally:
        logger.removeHandler(buf)

    messages = [item["message"] for item in buf.snapshot(min_level="DEBUG")]
    assert messages == ["qua duong logging"]


def test_emit_never_raises_on_broken_format():
    """Bản ghi hỏng (args không format được) không được làm sập handler.

    Handler chạy trong tiến trình thật trên Pi; một ``__str__`` ném lỗi không
    được phép giết vòng lặp camera.
    """

    class _Boom:
        def __str__(self):
            raise RuntimeError("nổ")

    record = logging.LogRecord(
        name="posture_monitor.x", level=logging.ERROR, pathname="", lineno=0,
        msg="giá trị: %s", args=(_Boom(),), exc_info=None,
    )

    buf = LogBuffer(maxlen=5)
    buf.emit(record)  # không được ném

    assert len(buf) == 1
    assert "không format được" in buf.snapshot()[0]["message"]


# --------------------------------------------------------------------------
# 3. Format bản ghi
# --------------------------------------------------------------------------


def test_entry_has_exactly_four_keys_with_right_types():
    """Mỗi bản ghi có đủ ``{ts, level, logger, message}`` với kiểu đúng."""
    buf = LogBuffer(maxlen=10)
    buf.emit(
        _record("noi dung", level=logging.ERROR, name="posture_monitor.capture")
    )

    entry = buf.snapshot()[0]

    assert set(entry) == {"ts", "level", "logger", "message"}
    assert isinstance(entry["ts"], float) and entry["ts"] > 0
    assert entry["level"] == "ERROR"
    assert isinstance(entry["logger"], str)
    assert entry["message"] == "noi dung"


def test_short_logger_name_strips_prefix():
    """Tên logger ngắn: bỏ tiền tố ``posture_monitor.``."""
    assert short_logger_name("posture_monitor.capture") == "capture"
    assert short_logger_name("posture_monitor.web.app") == "web.app"
    # Logger ngoài dự án giữ nguyên.
    assert short_logger_name("urllib3.connectionpool") == (
        "urllib3.connectionpool"
    )
    # Chính logger gốc cũng giữ nguyên (không cắt thành chuỗi rỗng).
    assert short_logger_name("posture_monitor") == "posture_monitor"


def test_short_logger_name_matches_root_logger_name():
    """Tên gốc trong ``log_buffer`` phải khớp ``logging_setup``.

    Hai module cố ý không import nhau (sẽ tạo vòng tròn), nên giá trị được
    chép. Bài này khoá chúng không trôi lệch.
    """
    from posture_monitor.logging_setup import ROOT_LOGGER_NAME

    assert lb._ROOT_LOGGER_NAME == ROOT_LOGGER_NAME


def test_message_is_formatted_with_args():
    """``message`` đã format: ``%s`` được thay, không còn nguyên mẫu."""
    record = logging.LogRecord(
        name="posture_monitor.x", level=logging.WARNING, pathname="", lineno=0,
        msg="mở %s thất bại sau %d lần", args=("camera", 3), exc_info=None,
    )
    buf = LogBuffer(maxlen=5)
    buf.emit(record)

    assert buf.snapshot()[0]["message"] == "mở camera thất bại sau 3 lần"


# --------------------------------------------------------------------------
# 4. Lọc theo mức — ở tầng ĐỌC
# --------------------------------------------------------------------------


def test_buffer_keeps_all_levels_but_snapshot_defaults_to_warning():
    """Giữ **mọi** mức; ``snapshot()`` mặc định chỉ trả WARNING trở lên.

    Đây là quyết định thiết kế: nếu chỉ giữ WARNING từ đầu thì khi cần chẩn
    đoán sâu ("vì sao phiên học không bắt đầu") sẽ không còn manh mối ``INFO``.
    """
    buf = LogBuffer(maxlen=20)
    for name, level in (
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
    ):
        buf.emit(_record(name, level=level))

    assert len(buf) == 4, "bộ đệm giữ cả 4 mức"

    default_levels = [item["level"] for item in buf.snapshot()]
    assert default_levels == ["ERROR", "WARNING"], "mặc định bỏ INFO/DEBUG"

    all_levels = [
        item["level"] for item in buf.snapshot(min_level="DEBUG")
    ]
    assert all_levels == ["ERROR", "WARNING", "INFO", "DEBUG"]


def test_snapshot_filters_by_threshold():
    """``min_level=ERROR`` chỉ trả ERROR+CRITICAL; WARNING loại ERROR ra."""
    buf = LogBuffer(maxlen=20)
    for name, level in (
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ):
        buf.emit(_record(name, level=level))

    assert [x["level"] for x in buf.snapshot(min_level="ERROR")] == [
        "CRITICAL",
        "ERROR",
    ]
    assert [x["level"] for x in buf.snapshot(min_level="CRITICAL")] == (
        ["CRITICAL"]
    )


def test_snapshot_newest_first():
    """Kết quả sắp **mới nhất trước** — popup hiện lỗi mới ở trên."""
    buf = LogBuffer(maxlen=10)
    for index in range(3):
        buf.emit(_record(f"m{index}"))

    assert [x["message"] for x in buf.snapshot()] == ["m2", "m1", "m0"]


def test_snapshot_limit_keeps_newest():
    """``limit`` cắt từ phía cũ, giữ bản ghi mới nhất."""
    buf = LogBuffer(maxlen=10)
    for index in range(5):
        buf.emit(_record(f"m{index}"))

    assert [x["message"] for x in buf.snapshot(limit=2)] == ["m4", "m3"]


def test_snapshot_returns_copy_not_internal_state():
    """Sửa list/dict trả về không được đổi bộ đệm."""
    buf = LogBuffer(maxlen=5)
    buf.emit(_record("goc"))

    snapshot = buf.snapshot()
    snapshot.append(
        {"ts": 0.0, "level": "ERROR", "logger": "x", "message": "chen"}
    )
    snapshot[0]["message"] = "bi sua"

    assert len(buf) == 1
    assert buf.snapshot()[0]["message"] == "goc"


# --------------------------------------------------------------------------
# 5. REDACT — không lộ mật khẩu RTSP
# --------------------------------------------------------------------------

#: URL có mật khẩu trong userinfo — dùng **giá trị giả** cùng hình dạng với
#: URL camera thật của dự án.
#:
#: Không dùng mật khẩu thật ở đây: tệp này được commit lên GitHub, nên nó sẽ
#: biến một hằng số test thành rò rỉ mật khẩu của thiết bị. Phép thử chỉ cần
#: *hình dạng* ``rtsp://user:pass@host`` — chuỗi cụ thể không quan trọng.
_SECRET_URL = "rtsp://admin:matkhau-gia-de-test@192.0.2.10:554/1/2"


def test_redacts_rtsp_password():
    """Mật khẩu trong ``rtsp://user:pass@host`` không được vào bộ đệm."""
    buf = LogBuffer(maxlen=5)
    buf.emit(_record(f"Không mở được luồng {_SECRET_URL} sau 3 lần."))

    message = buf.snapshot()[0]["message"]

    assert "matkhau-gia-de-test" not in message, "RÒ MẬT KHẨU"
    assert "admin" not in message, "cũng không được lộ tên đăng nhập"
    assert "***" in message
    # Phần còn lại của URL giữ nguyên để còn chẩn đoán được.
    # Phần còn lại của URL giữ nguyên để còn chẩn đoán được (host và cổng vẫn
    # phải đọc được — đó là mục đích của việc che chứ không xoá cả URL).
    assert "192.0.2.10:554/1/2" in message


def test_redacts_password_in_formatted_args():
    """Che mật khẩu cả khi URL đi qua ``%s`` trong ``args``."""
    record = logging.LogRecord(
        name="posture_monitor.capture", level=logging.ERROR, pathname="",
        lineno=0, msg="Nguồn ảnh lỗi: %s", args=(_SECRET_URL,), exc_info=None,
    )
    buf = LogBuffer(maxlen=5)
    buf.emit(record)

    assert "matkhau-gia-de-test" not in buf.snapshot()[0]["message"]


def test_redact_does_not_touch_url_without_credentials():
    """URL không có userinfo phải giữ nguyên, không bị thêm ``***``."""
    plain = "rtsp://192.168.17.108:554/1/2"
    buf = LogBuffer(maxlen=5)
    buf.emit(_record(f"Kết nối {plain}"))

    assert buf.snapshot()[0]["message"] == f"Kết nối {plain}"


def test_uses_shared_redact_function_not_a_second_one():
    """Phải dùng ``config.redact_camera_source`` — bản duy nhất của dự án.

    Hai hàm che khác nhau sẽ trôi lệch, và bản yếu hơn thành lỗ hổng. Bài này
    khẳng định kết quả của ``LogBuffer`` trùng khớp hàm chung.
    """
    from posture_monitor.config import redact_camera_source

    buf = LogBuffer(maxlen=5)
    buf.emit(_record(f"lỗi {_SECRET_URL}"))

    expected_message = f"lỗi {redact_camera_source(_SECRET_URL)}"
    assert buf.snapshot()[0]["message"] == expected_message


# --------------------------------------------------------------------------
# 6. Thread-safety cơ bản
# --------------------------------------------------------------------------


def test_concurrent_writes_do_not_lose_or_corrupt():
    """8 luồng × 50 bản ghi: đếm đủ, không bản ghi hỏng.

    ``maxlen`` đặt lớn hơn tổng số bản ghi để phép đếm có nghĩa — nếu deque tự
    đẩy bớt thì không phân biệt được "mất do tranh chấp" với "mất do maxlen".
    """
    buf = LogBuffer(maxlen=1000)
    threads_count, per_thread = 8, 50

    def worker(worker_id: int) -> None:
        for index in range(per_thread):
            buf.emit(_record(f"w{worker_id}-{index}"))

    threads = [
        threading.Thread(target=worker, args=(worker_id,))
        for worker_id in range(threads_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(buf) == threads_count * per_thread
    entries = buf.snapshot(min_level="DEBUG", limit=1000)
    # Mọi bản ghi còn nguyên 4 khoá và message đúng định dạng.
    assert all(
        set(entry) == {"ts", "level", "logger", "message"} for entry in entries
    )
    assert all(entry["message"].startswith("w") for entry in entries)
    # Không mất bản ghi nào: tập message trùng với tập sinh ra.
    expected = {
        f"w{w}-{i}" for w in range(threads_count) for i in range(per_thread)
    }
    assert {entry["message"] for entry in entries} == expected


def test_concurrent_reads_while_writing_do_not_raise():
    """Đọc ``snapshot`` đồng thời với ghi không được ném lỗi nào.

    ``deque`` bị sửa trong lúc ``list()`` nó có thể ném "deque mutated during
    iteration" nếu không có khoá. Đây chính là lý do ``LogBuffer`` giữ
    ``threading.Lock`` riêng.
    """
    buf = LogBuffer(maxlen=100)
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        while not stop.is_set():
            buf.emit(_record("ghi"))

    def reader() -> None:
        try:
            while not stop.is_set():
                buf.snapshot(limit=10)
        except BaseException as exc:  # noqa: BLE001 - ghi lại để assert
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    threading.Event().wait(0.15)
    stop.set()
    for thread in threads:
        thread.join()

    assert errors == [], f"đọc đồng thời gặp lỗi: {errors}"


# --------------------------------------------------------------------------
# Tiện ích mức
# --------------------------------------------------------------------------


def test_level_order_covers_standard_levels():
    """``LEVEL_ORDER`` có đủ 5 mức chuẩn, đúng thứ tự tăng dần."""
    assert LEVEL_ORDER == {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }


def test_normalize_level_accepts_names_numbers_and_default():
    """Chấp nhận tên (mọi kiểu hoa/thường), số mức, và ``None``."""
    assert normalize_level("warning") == "WARNING"
    assert normalize_level("  error ") == "ERROR"
    assert normalize_level("CRITICAL") == "CRITICAL"
    assert normalize_level(30) == "WARNING"
    assert normalize_level(None) == DEFAULT_MIN_LEVEL
    assert normalize_level("") == DEFAULT_MIN_LEVEL


def test_normalize_level_rejects_unknown_and_bool():
    """Giá trị lạ trả ``None`` để tầng gọi phân biệt được và trả 400."""
    assert normalize_level("verbose") is None
    assert normalize_level("ALL") is None
    assert normalize_level(35) is None
    assert normalize_level(True) is None, "bool là int, phải loại riêng"


def test_meets_level_threshold_semantics():
    """``meets_level`` là "bằng hoặc cao hơn", không phải "khác"."""
    assert meets_level("WARNING", "WARNING") is True
    assert meets_level("ERROR", "WARNING") is True
    assert meets_level("CRITICAL", "ERROR") is True
    assert meets_level("INFO", "WARNING") is False
    assert meets_level("DEBUG", "DEBUG") is True


def test_default_min_level_is_warning():
    """Mặc định lọc phải là WARNING — popup chỉ hiện lỗi, không đầy INFO."""
    assert DEFAULT_MIN_LEVEL == "WARNING"
