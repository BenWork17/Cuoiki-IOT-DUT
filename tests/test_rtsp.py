"""Kiểm thử nguồn ảnh camera IP qua RTSP (spec v2 §5.1).

Không cần camera thật: mọi ``cv2.VideoCapture`` đều được thay bằng bản giả, và
đồng hồ được điều khiển qua seam :func:`capture._monotonic`.

Bài quan trọng nhất là logic **xả bộ đệm**: camera IP đẩy khung nhanh hơn nhịp
đọc của pipeline, nên nếu mỗi lần chỉ ``read()`` một khung thì khung trả về là
khung cũ nhất trong đệm và độ trễ tăng dần (đo trên PC: pipeline nghỉ 5 s thì
đệm tích 101 khung, độ trễ ~3,6 s — phá tiêu chí §8). Vì vậy ``read()`` phải
trả khung **mới nhất**.

Ghi chú bảo mật: file này **không** chứa thông tin đăng nhập thật. Hằng
``SECRET`` dưới đây là mật khẩu bịa đặt, có hình dạng giống thật để test bắt
được rò rỉ; URL thật chỉ được đặt trong ``config.local.yaml`` (đã bị
``.gitignore`` chặn) hoặc biến môi trường ``POSTURE_CAMERA_SOURCE``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pytest

# Cho phép chạy `pytest tests/` từ gốc repo mà không cần cài gói.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import capture  # noqa: E402
from posture_monitor.capture import (  # noqa: E402
    CameraError,
    FileSource,
    RTSPSource,
    capture_from_config,
)
from posture_monitor.config import (  # noqa: E402
    CAMERA_SOURCE_ENV,
    Config,
    ConfigError,
    load_config,
    parse_camera_source,
    redact_camera_source,
)

#: Mật khẩu bịa đặt — KHÔNG phải mật khẩu thật của camera nào.
SECRET = "mat-khau-gia-123"
URL = f"rtsp://admin:{SECRET}@192.168.1.50:554/1/2"
URL_REDACTED = "rtsp://***:***@192.168.1.50:554/1/2"


# --------------------------------------------------------------------------
# parse_camera_source — nhánh rtsp
# --------------------------------------------------------------------------


def test_parse_rtsp_keeps_url_intact() -> None:
    """URL còn nguyên, kể cả ``:`` trong thông tin đăng nhập và cổng."""
    assert parse_camera_source(f"rtsp:{URL}") == ("rtsp", URL)


def test_parse_rtsp_accepts_rtsps() -> None:
    url = f"rtsps://admin:{SECRET}@camera.local/1/2"
    assert parse_camera_source(f"rtsp:{url}") == ("rtsp", url)


def test_parse_rtsp_rejects_empty() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source("rtsp:")
    assert "thiếu URL RTSP" in str(excinfo.value)


def test_parse_rtsp_rejects_non_rtsp_scheme() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source("rtsp:http://192.168.1.50/1/2")
    assert "rtsp://" in str(excinfo.value)


def test_parse_rtsp_rejects_plain_host() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source("rtsp:192.168.1.50")
    assert "rtsps://" in str(excinfo.value)


# -- không hồi quy các loại cũ ---------------------------------------------


def test_parse_usb_still_works() -> None:
    assert parse_camera_source("usb:0") == ("usb", 0)
    assert parse_camera_source("usb:7") == ("usb", 7)


def test_parse_picamera_still_works() -> None:
    assert parse_camera_source("picamera") == ("picamera", None)


def test_parse_file_with_windows_path_still_works() -> None:
    assert parse_camera_source(r"file:C:\a b.mp4") == ("file", r"C:\a b.mp4")


# --------------------------------------------------------------------------
# Che mật khẩu
# --------------------------------------------------------------------------


def test_redact_hides_user_and_password() -> None:
    assert redact_camera_source(URL) == URL_REDACTED
    assert SECRET not in redact_camera_source(URL)
    assert "admin" not in redact_camera_source(URL)


def test_redact_keeps_url_without_credentials() -> None:
    plain = "rtsp://192.168.1.50:554/1/2"
    assert redact_camera_source(plain) == plain


def test_redact_user_only() -> None:
    assert redact_camera_source("rtsp://admin@host/1") == "rtsp://***@host/1"


def test_redact_handles_non_string() -> None:
    assert redact_camera_source(None) == "None"


#: Mật khẩu **có chứa ``@``** — lớp lỗi mà ``[^/@]*`` để lọt phần đuôi.
#: ``@`` hợp lệ trong mật khẩu, và ``parse_camera_source`` chấp nhận các URL
#: này, nên chúng thật sự đi vào log/repr/ConfigError.
_AT_PASSWORD_CASES = [
    ("rtsp://admin:pa@ss@1.2.3.4:554/1/2", "rtsp://***:***@1.2.3.4:554/1/2"),
    (
        "rtsp://admin:@secret@10.0.0.9:554/1/2",
        "rtsp://***:***@10.0.0.9:554/1/2",
    ),
    (
        "rtsp://admin:a@b@c@10.0.0.9:554/1/2",
        "rtsp://***:***@10.0.0.9:554/1/2",
    ),
    (
        "rtsp://admin:p@ssw0rd!@10.0.0.9:554/1/2",
        "rtsp://***:***@10.0.0.9:554/1/2",
    ),
    ("rtsp://admin:pa%40ss@1.2.3.4/1/2", "rtsp://***:***@1.2.3.4/1/2"),
]


def _password_fragments(wire: str) -> list[str]:
    """Các mảnh mật khẩu tách theo ``@``, chỉ giữ mảnh đủ dài để có ý nghĩa.

    Mảnh 1 ký tự (``'p'`` trong ``p@ssw0rd!``) không mang thông tin mật khẩu và
    sẽ khớp bừa với chữ trong ``rtsp``/``https``/thông điệp lỗi, nên bỏ qua.
    """
    password = wire.split("://", 1)[1].rsplit("@", 1)[0].split(":", 1)[1]
    return [part for part in password.split("@") if len(part) >= 2]


@pytest.mark.parametrize(("wire", "expected"), _AT_PASSWORD_CASES)
def test_redact_password_containing_at_sign(wire: str, expected: str) -> None:
    """``@`` trong mật khẩu không được để lộ phần đuôi ra ngoài chuỗi đã che."""
    redacted = redact_camera_source(wire)
    assert redacted == expected
    for fragment in _password_fragments(wire):
        assert fragment not in redacted


@pytest.mark.parametrize(
    "wire",
    [
        "rtsp://admin:pa@ss@1.2.3.4:554/1/2",
        "rtsp://admin:@secret@10.0.0.9:554/1/2",
        "rtsp://admin:a@b@c@10.0.0.9:554/1/2",
        "rtsp://admin:p@ssw0rd!@10.0.0.9:554/1/2",
    ],
)
def test_at_password_accepted_then_never_leaks(wire: str) -> None:
    """URL có ``@`` trong mật khẩu được chấp nhận, và lỗi/log đều đã che."""
    assert parse_camera_source(f"rtsp:{wire}") == ("rtsp", wire)

    # Đường lỗi: ép một lỗi cú pháp để chắc chắn thông điệp dùng bản đã che.
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source(f"tcp:{wire}")
    message = str(excinfo.value)
    for fragment in _password_fragments(wire):
        assert fragment not in message
    assert "admin" not in message


def test_redact_hides_credentials_in_embedded_urls() -> None:
    """Hai URL trong cùng một chuỗi: cả hai đều phải bị che."""
    wire = "rtsp://a:b@h:554/x/rtsp://c:d@h2/y"
    redacted = redact_camera_source(wire)
    assert redacted == "rtsp://***:***@h:554/x/rtsp://***:***@h2/y"


def test_config_error_does_not_leak_password() -> None:
    """``parse_camera_source`` chèn nguồn vào lỗi — phải che trước khi chèn."""
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source(URL)
    message = str(excinfo.value)
    assert SECRET not in message
    assert "admin" not in message


def test_config_error_redacts_rtsp_url_in_unknown_kind() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source(f"tcp:rtsp://admin:{SECRET}@host:554/1")
    assert SECRET not in str(excinfo.value)


def test_invalid_usb_message_does_not_leak_credentials() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source(f"usb:rtsp://admin:{SECRET}@host")
    assert SECRET not in str(excinfo.value)


def test_invalid_rtsp_scheme_message_does_not_leak_credentials() -> None:
    with pytest.raises(ConfigError) as excinfo:
        parse_camera_source(f"rtsp:http://admin:{SECRET}@host/1")
    assert SECRET not in str(excinfo.value)


# --------------------------------------------------------------------------
# Ghi đè bằng biến môi trường
# --------------------------------------------------------------------------


def test_env_override_wins_over_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(CAMERA_SOURCE_ENV, f"rtsp:{URL}")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    config = load_config(config_path)
    assert config.camera.source == f"rtsp:{URL}"


def test_empty_env_override_is_ignored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "   ")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:1\n", encoding="utf-8")

    config = load_config(config_path)
    assert config.camera.source == "usb:1"


def test_env_override_is_validated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "rtsp:khong-hop-le")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_env_override_accepts_bare_rtsp_url(tmp_path: Path, monkeypatch) -> None:
    """Dạng người dùng tự nhiên gõ: URL trần, không tiền tố loại nguồn."""
    monkeypatch.setenv(CAMERA_SOURCE_ENV, URL)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    config = load_config(config_path)
    assert config.camera.source == f"rtsp:{URL}"
    assert parse_camera_source(config.camera.source) == ("rtsp", URL)


def test_env_override_accepts_bare_rtsps_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "rtsps://host:554/1/2")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    config = load_config(config_path)
    assert parse_camera_source(config.camera.source) == (
        "rtsp",
        "rtsps://host:554/1/2",
    )


def test_env_override_keeps_explicit_prefix(tmp_path: Path, monkeypatch) -> None:
    """Dạng tường minh vẫn chạy, không bị thêm ``rtsp:`` lần thứ hai."""
    monkeypatch.setenv(CAMERA_SOURCE_ENV, f"rtsp:{URL}")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    config = load_config(config_path)
    assert config.camera.source == f"rtsp:{URL}"
    assert parse_camera_source(config.camera.source) == ("rtsp", URL)


def test_env_override_keeps_non_rtsp_prefix(tmp_path: Path, monkeypatch) -> None:
    """``usb:1`` không được biến thành ``rtsp:usb:1``."""
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "usb:1")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    config = load_config(config_path)
    assert config.camera.source == "usb:1"
    assert parse_camera_source(config.camera.source) == ("usb", 1)


@pytest.mark.parametrize("garbage", ["http://x", "rác", "usb:rtsp://h/1"])
def test_env_override_garbage_is_rejected(
    tmp_path: Path, monkeypatch, garbage: str
) -> None:
    monkeypatch.setenv(CAMERA_SOURCE_ENV, garbage)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


@pytest.mark.parametrize(
    "garbage", [f"http://admin:{SECRET}@host/x", f"hls://u:{SECRET}@host/x"]
)
def test_env_override_garbage_does_not_leak_credentials(
    tmp_path: Path, monkeypatch, garbage: str
) -> None:
    monkeypatch.setenv(CAMERA_SOURCE_ENV, garbage)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(config_path)
    assert SECRET not in str(excinfo.value)


# --------------------------------------------------------------------------
# VideoCapture giả
# --------------------------------------------------------------------------

#: Giá trị pixel đánh dấu từng khung; ``_frame(i)`` mang giá trị ``i``.
#: Đồng hồ giả dùng chung trong fixture ``fake_clock``.


class _FakeCapture:
    """``cv2.VideoCapture`` giả mô phỏng **luồng RTSP đang sống**.

    Hành vi thật của một luồng trực tiếp: ``grab()`` không bao giờ "cạn đệm" —
    nếu không còn khung đệm thì nó **chờ** khung kế tiếp từ camera (đo trên PC
    ~50 ms, tức 1/20 fps), còn khi mất kết nối thì trả ``False``.

    Vì vậy mô hình ở đây là:

    - ``queue`` là các khung đã nằm sẵn trong đệm: ``grab`` lấy lần lượt, mỗi
      lần tốn 1 ms (đo trên PC: 0,29 ms).
    - Khi ``queue`` rỗng, ``grab`` trả ``live_frame`` và tốn 50 ms — vượt
      ngưỡng :data:`capture.RTSP_DRAIN_STEP_LIMIT_S`, đúng tín hiệu "đã đuổi
      kịp luồng trực tiếp, dừng xả".
    - ``dead=True`` (hoặc mở thất bại): ``grab`` trả ``False`` như OpenCV thật,
      và khung đang chờ bị xoá — OpenCV thật cũng hành xử vậy (kiểm bằng
      ``cv2.VideoCapture`` trên file: sau ``grab()`` thất bại, ``retrieve()``
      báo "Picture does not contain data").
    """

    def __init__(
        self,
        queue,
        opened: bool = True,
        dead: bool = False,
        live_value: int = 99,
    ) -> None:
        self.queue = list(queue)
        self._opened = opened
        self.dead = dead
        self.live_frame = _frame(live_value)
        self.released = 0
        self.grabs = 0
        self.retrieves = 0
        self.set_calls: list[tuple[int, float]] = []
        self._pending = None
        self.clock: dict[str, float] | None = None
        self.env_at_open = os.environ.get(capture.FFMPEG_OPTIONS_ENV)

    # -- giao diện VideoCapture ----------------------------------------

    def isOpened(self) -> bool:  # noqa: N802 - tên của OpenCV
        return self._opened

    def set(self, prop: int, value: float) -> bool:
        self.set_calls.append((prop, value))
        return True

    def get(self, _prop: int) -> float:
        return 0.0

    def grab(self) -> bool:
        self.grabs += 1
        if self.dead or not self._opened:
            self._pending = None
            return False
        if self.queue:
            self._pending = self.queue.pop(0)
            cost = 0.001
        else:
            self._pending = self.live_frame
            cost = 0.05
        if self.clock is not None:
            self.clock["now"] += cost
        return True

    def retrieve(self):
        self.retrieves += 1
        frame, self._pending = self._pending, None
        if frame is None:
            return False, None
        return True, frame

    def read(self):
        if not self.grab():
            return False, None
        return self.retrieve()

    def release(self) -> None:
        self.released += 1
        self._opened = False


def _frame(value: int) -> np.ndarray:
    """Khung đồng màu mang giá trị ``value`` — dùng để nhận biết khung nào."""
    return np.full((48, 64, 3), value % 256, dtype=np.uint8)


@pytest.fixture
def fake_clock(monkeypatch):
    """Đồng hồ giả, để test không phụ thuộc ``time.monotonic`` thật."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(capture, "_monotonic", lambda: clock["now"])
    return clock


@pytest.fixture
def make_source(monkeypatch, fake_clock):
    """Trả hàm tạo ``RTSPSource`` với ``cv2.VideoCapture`` giả.

    Patch được đặt trên ``monkeypatch`` của cả test (không phải context chỉ
    sống trong ``factory``), để các ``read()`` sau khi nguồn đã dựng — ví dụ
    trong test ``close()`` — cũng không chạm mạng thật.
    """

    def factory(queue, opened: bool = True, live_value: int = 99, **kwargs):
        fakes: list[_FakeCapture] = []

        def fake_video_capture(*_args, **_kwargs):
            fake = _FakeCapture(queue, opened=opened, live_value=live_value)
            fake.clock = fake_clock
            fakes.append(fake)
            return fake

        monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)
        monkeypatch.setattr(capture.cv2, "VideoCapture", fake_video_capture)
        source = RTSPSource(URL, **kwargs)
        source._fakes = fakes  # để test kiểm tra số lần grab
        return source

    return factory


# --------------------------------------------------------------------------
# RTSPSource — cơ bản
# --------------------------------------------------------------------------


def test_rtsp_source_backend(make_source) -> None:
    source = make_source([_frame(1), _frame(2)])
    try:
        assert source.backend == "rtsp"
    finally:
        source.close()


def test_rtsp_source_sets_buffersize(make_source) -> None:
    source = make_source([_frame(1), _frame(2)])
    try:
        set_props = [prop for prop, _ in source._fakes[0].set_calls]
        assert capture.cv2.CAP_PROP_BUFFERSIZE in set_props
    finally:
        source.close()


def test_rtsp_source_repr_hides_password(make_source) -> None:
    source = make_source([_frame(1), _frame(2)])
    try:
        text = repr(source)
        assert SECRET not in text
        assert "admin" not in text
        assert "***" in text
    finally:
        source.close()


# --------------------------------------------------------------------------
# Xả bộ đệm — bài quan trọng nhất
# --------------------------------------------------------------------------


def test_read_returns_last_frame_of_small_backlog(make_source) -> None:
    """Đệm nhỏ: 5 khung cũ → phải trả khung mới nhất, không phải khung đầu."""
    frames = [_frame(i) for i in range(5)]
    source = make_source(frames, live_value=6)
    try:
        result = source.read()
        assert result is not None
        assert int(result[0, 0, 0]) == 6, "phải là khung mới nhất, không phải khung cũ"
        assert source._last_dropped == 5
    finally:
        source.close()


def test_read_returns_latest_after_five_second_stall(make_source) -> None:
    """Pipeline nghỉ 5 s (đo trên PC: 101 khung đệm) → trả khung mới nhất.

    Đây là ca tương ứng đúng số đo của Lead: nếu ``read()`` chỉ lấy khung đầu
    thì độ trễ ~3,6 s. Test khẳng định khung trả về là khung thứ 102 (khung
    vừa được camera đẩy), không phải khung đầu đệm.
    """
    buffered = [_frame(i) for i in range(101)]  # khung cũ tích trong đệm
    source = make_source(buffered, live_value=200)  # 200 = khung mới nhất
    try:
        result = source.read()
        assert result is not None
        assert int(result[0, 0, 0]) == 200, (
            "read() phải trả khung mới nhất, không phải khung đầu đệm"
        )
        assert source._last_dropped == 101
        # 1 lần grab đầu + 101 lần grab tiếp theo (xả hết đệm rồi chờ khung mới).
        assert source._fakes[0].grabs == 102
        assert source._fakes[0].retrieves == 1
    finally:
        source.close()


def test_read_stops_draining_when_grab_blocks(make_source) -> None:
    """Khi grab phải chờ (đệm đã cạn), dừng xả ngay — không chờ vô ích."""
    source = make_source([_frame(0), _frame(1), _frame(2), _frame(3)], live_value=9)
    try:
        result = source.read()
        assert result is not None
        assert int(result[0, 0, 0]) == 9
        # 4 grab lấy đệm + 1 grab chờ khung trực tiếp (50 ms > 30 ms) rồi dừng.
        assert source._fakes[0].grabs == 5
        assert source._last_dropped == 4
    finally:
        source.close()


def test_read_respects_max_drain_frames(make_source) -> None:
    """Trần ``max_drain_frames`` chặn đệm phình bất thường."""
    frames = [_frame(i) for i in range(20)]
    source = make_source(frames, max_drain_frames=5)
    try:
        result = source.read()
        assert result is not None
        # 1 grab ngoài vòng + 4 lần trong vòng: dừng vì chạm trần, không vét
        # hết 20 khung.
        assert source._fakes[0].grabs == 5
        assert source._last_dropped == 4
    finally:
        source.close()


def test_drain_constants_fit_measured_backlog() -> None:
    """Hằng số phải đủ lớn cho số khung đệm đã đo trên PC (128 khung/8 s)."""
    assert capture.RTSP_MAX_DRAIN_FRAMES > 128
    # Đo trên PC: grab trên khung đệm 0,29 ms; grab phải chờ khung mới ~50 ms.
    assert 0.005 < capture.RTSP_DRAIN_STEP_LIMIT_S < 0.04
    # Lần xả lâu nhất đo được trên PC là 137 ms (mức nghỉ 3 s).
    assert capture.RTSP_DRAIN_TIME_LIMIT_S > 0.137


# --------------------------------------------------------------------------
# Biến môi trường FFmpeg — không rò sang nguồn khác
# --------------------------------------------------------------------------


def test_ffmpeg_options_used_at_open(make_source) -> None:
    source = make_source([_frame(1), _frame(2)])
    try:
        seen = source._fakes[0].env_at_open
        assert seen is not None
        assert "rtsp_transport;udp" in seen
        assert "fflags;nobuffer+discardcorrupt" in seen
        assert "flags;low_delay" in seen
        assert "framedrop;1" in seen
        assert "probesize;500000" in seen
        assert "analyzeduration;1000000" in seen
        assert "max_delay;500000" in seen
    finally:
        source.close()


def test_ffmpeg_options_absent_after_open(make_source, monkeypatch) -> None:
    monkeypatch.delenv(capture.FFMPEG_OPTIONS_ENV, raising=False)
    source = make_source([_frame(1), _frame(2)])
    try:
        assert capture.FFMPEG_OPTIONS_ENV not in os.environ
    finally:
        source.close()


def test_ffmpeg_options_restore_previous_value(make_source, monkeypatch) -> None:
    monkeypatch.setenv(capture.FFMPEG_OPTIONS_ENV, "rtsp_transport;tcp")
    source = make_source([_frame(1), _frame(2)])
    try:
        assert os.environ[capture.FFMPEG_OPTIONS_ENV] == "rtsp_transport;tcp"
    finally:
        source.close()


def test_ffmpeg_options_restored_when_open_fails(monkeypatch) -> None:
    """Mở thất bại vẫn phải trả biến môi trường về giá trị cũ."""
    monkeypatch.delenv(capture.FFMPEG_OPTIONS_ENV, raising=False)
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)
    monkeypatch.setattr(
        capture.cv2,
        "VideoCapture",
        lambda *a, **k: _FakeCapture([], opened=False),
    )

    with pytest.raises(CameraError):
        RTSPSource(URL, max_attempts=1)

    assert capture.FFMPEG_OPTIONS_ENV not in os.environ


def test_file_source_sees_clean_environment_after_rtsp(
    tmp_path: Path, monkeypatch, fake_clock
) -> None:
    """``file:`` mở sau RTSP phải không thấy cờ FFmpeg của RTSP.

    Biến môi trường là toàn tiến trình, nên nếu quên khôi phục thì
    ``nobuffer``/``discardcorrupt`` sẽ áp cho cả video file. Test dùng
    ``cv2.VideoCapture`` giả ghi lại môi trường tại thời điểm mở.
    """
    fake_file = _FakeCapture([_frame(9)])
    fake_file.clock = fake_clock
    opens: list[_FakeCapture] = []

    def fake_video_capture(*_args, **_kwargs):
        fake = fake_file if opens else _FakeCapture([_frame(1), _frame(2)])
        fake.clock = fake_clock
        opens.append(fake)
        return fake

    with monkeypatch.context() as patch:
        patch.setattr(capture, "_sleep", lambda _seconds: None)
        patch.setattr(capture.cv2, "VideoCapture", fake_video_capture)

        rtsp = RTSPSource(URL)
        try:
            assert rtsp.read() is not None
        finally:
            rtsp.close()

        video = tmp_path / "a.mp4"
        video.write_bytes(b"")
        file_source = FileSource(video)
        try:
            assert file_source.backend == "file"
            assert file_source.read() is not None
        finally:
            file_source.close()

    assert fake_file.env_at_open is None, (
        "cờ FFmpeg của RTSP phải được khôi phục trước khi file: mở"
    )


# --------------------------------------------------------------------------
# read() / close() khi camera chết
# --------------------------------------------------------------------------


def test_open_failure_raises_camera_error_without_password(monkeypatch) -> None:
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)
    monkeypatch.setattr(
        capture.cv2,
        "VideoCapture",
        lambda *a, **k: _FakeCapture([], opened=False),
    )

    with pytest.raises(CameraError) as excinfo:
        RTSPSource(URL, max_attempts=1)

    message = str(excinfo.value)
    assert SECRET not in message
    assert "admin" not in message


def test_read_returns_none_after_reconnect_budget_exhausted(
    monkeypatch, fake_clock
) -> None:
    """Mất luồng không nối lại được: ``read()`` chỉ trả ``None``, không raise."""
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    fakes: list[_FakeCapture] = []

    def fake_video_capture(*_args, **_kwargs):
        # Chỉ lần mở đầu tiên thành công nhưng luồng đã chết (grab trả False);
        # các lần mở lại đều thất bại, giống test tương ứng của OpenCVSource.
        fake = _FakeCapture([], opened=not fakes, dead=True)
        fake.clock = fake_clock
        fakes.append(fake)
        return fake

    monkeypatch.setattr(capture.cv2, "VideoCapture", fake_video_capture)

    source = RTSPSource(URL, max_attempts=2)
    try:
        for _ in range(10):
            assert source.read() is None
        assert source._gave_up is True
        # 1 lần mở ban đầu + tối đa 2 lần kết nối lại.
        assert len(fakes) <= 3
    finally:
        source.close()


def test_reconnect_budget_resets_after_successful_open(
    monkeypatch, fake_clock
) -> None:
    """Mở lại được thì cấp lại ngân sách — cùng mô hình với ``OpenCVSource``."""
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    def fake_video_capture(*_args, **_kwargs):
        fake = _FakeCapture([_frame(5)], opened=True, live_value=6)
        fake.clock = fake_clock
        return fake

    monkeypatch.setattr(capture.cv2, "VideoCapture", fake_video_capture)

    source = RTSPSource(URL, max_attempts=2)
    try:
        assert source.read() is not None
        assert source._reconnect_budget == 2
        assert source._gave_up is False
    finally:
        source.close()


def test_read_recovers_after_reconnect(monkeypatch, fake_clock) -> None:
    """Mất luồng rồi nối lại được: ``read()`` trả khung mới thay vì ``None``."""
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    fakes: list[_FakeCapture] = []

    def fake_video_capture(*_args, **_kwargs):
        # Handle đầu đã "chết" (grab trả False); handle thứ hai sống và có
        # một khung đệm mang giá trị 7, khung trực tiếp mang giá trị 8.
        if not fakes:
            fake = _FakeCapture([], opened=True, dead=True)
        else:
            fake = _FakeCapture([_frame(7)], opened=True, live_value=8)
        fake.clock = fake_clock
        fakes.append(fake)
        return fake

    monkeypatch.setattr(capture.cv2, "VideoCapture", fake_video_capture)

    source = RTSPSource(URL, max_attempts=2)
    try:
        result = source.read()
        assert result is not None
        assert int(result[0, 0, 0]) == 8
        assert len(fakes) == 2
    finally:
        source.close()


def test_close_is_idempotent(make_source) -> None:
    """``close()`` gọi nhiều lần không raise; đóng là trạng thái cuối.

    ``read()`` sau khi đóng phải trả ``None`` và không được tạo thêm handle
    ``cv2.VideoCapture`` nào (với RTSP, mở lại là một kết nối mạng thật).
    """
    source = make_source([_frame(1), _frame(2)])
    source.close()
    source.close()

    opens_at_close = len(source._fakes)
    result = source.read()
    source.close()
    opens_after_read = len(source._fakes)

    assert result is None
    assert opens_after_read == opens_at_close, (
        "read() sau close() không được mở lại kết nối"
    )
    assert source._closed is True
    assert source._cap is None
    assert source._fakes[0].released >= 1


def test_read_after_close_does_not_log_reconnect(make_source, caplog) -> None:
    """Sau ``close()``, ``read()`` không được log "đang kết nối lại"."""
    source = make_source([_frame(1), _frame(2)])
    source.close()

    with caplog.at_level(logging.DEBUG, logger="posture_monitor"):
        assert source.read() is None

    assert "kết nối lại" not in caplog.text
    assert len(source._fakes) == 1


def test_close_releases_capture(make_source) -> None:
    source = make_source([_frame(1), _frame(2)])
    source.close()
    assert source._fakes[0].released >= 1


# --------------------------------------------------------------------------
# capture_from_config
# --------------------------------------------------------------------------


def test_capture_from_config_rtsp_failure_returns_none(monkeypatch) -> None:
    """Mở RTSP thất bại: trả ``None``, không raise (spec §11.4)."""

    def _fail(*_args, **_kwargs):
        raise CameraError("giả lập: không mở được RTSP")

    monkeypatch.setattr(capture, "RTSPSource", _fail)

    config = Config()
    config.camera.source = f"rtsp:{URL}"
    assert capture_from_config(config) is None


def test_capture_from_config_rtsp_failure_logs_without_password(
    monkeypatch, caplog
) -> None:
    """Log lỗi không được chứa mật khẩu."""
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)
    monkeypatch.setattr(
        capture.cv2,
        "VideoCapture",
        lambda *a, **k: _FakeCapture([], opened=False),
    )

    config = Config()
    config.camera.source = f"rtsp:{URL}"

    with caplog.at_level(logging.DEBUG, logger="posture_monitor"):
        result = capture_from_config(config)

    assert result is None
    assert SECRET not in caplog.text
    assert "admin:" not in caplog.text


def test_capture_from_config_rtsp_success_builds_source(
    monkeypatch, fake_clock
) -> None:
    monkeypatch.setattr(capture, "_sleep", lambda _seconds: None)

    def fake_video_capture(*_args, **_kwargs):
        fake = _FakeCapture([_frame(1), _frame(2)])
        fake.clock = fake_clock
        return fake

    monkeypatch.setattr(capture.cv2, "VideoCapture", fake_video_capture)

    config = Config()
    config.camera.source = f"rtsp:{URL}"
    source = capture_from_config(config)
    try:
        assert source is not None
        assert source.backend == "rtsp"
        assert source.read() is not None
    finally:
        if source is not None:
            source.close()


# --------------------------------------------------------------------------
# Cấu hình mẫu trong repo
# --------------------------------------------------------------------------


def test_repo_config_yaml_has_no_real_credentials() -> None:
    """``config.yaml`` chỉ được chứa ví dụ giữ chỗ, không có mật khẩu thật."""
    text = (_REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # chú thích: ví dụ giữ chỗ được phép
        assert "@" not in stripped, (
            f"config.yaml không được chứa URL có thông tin đăng nhập: {line!r}"
        )


def test_config_yaml_documents_rtsp_syntax() -> None:
    text = (_REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    assert "rtsp:" in text
    assert "POSTURE_CAMERA_SOURCE" in text or "config.local.yaml" in text
