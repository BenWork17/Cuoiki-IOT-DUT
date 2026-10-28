"""Unit test cho loa camera qua RTSP backchannel (``camera_audio`` + ``/api/speak``).

Chạy trên PC, **không cần camera thật, không cần mạng, không cần ffmpeg**:

- Transport backchannel được thay bằng :class:`FakeTransport` ghi lại từng gói
  RTP; nhịp gửi được thay bằng pacer không ngủ, nên test tất định và nhanh.
- Không test nào mở socket. Địa chỉ trong test là ``camera.test`` — tên dành
  riêng cho tài liệu (RFC 2606), không phân giải được, nên nếu có ai quên thay
  transport thì test fail chứ không lặng lẽ gọi ra mạng LAN.
- Mật khẩu trong mọi test là chuỗi giả ``mat-khau-gia``; không có mật khẩu thật.
"""

from __future__ import annotations

import importlib
import struct
import sys
import threading
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import camera_audio  # noqa: E402
from posture_monitor.camera_audio import (  # noqa: E402
    CameraAudioBusy,
    CameraAudioConfigError,
    CameraAudioError,
    CameraAudioInputError,
    CameraAudioUnavailable,
    MAX_SPEAK_DURATION_S,
    ONVIF_PASSWORD_ENV,
    SAMPLES_PER_PACKET,
    SpeakController,
    SpeakerConfig,
    ffmpeg_available,
    speaker_config_from_config,
)
from posture_monitor.config import REDACTED, Config  # noqa: E402
from posture_monitor.web import create_app  # noqa: E402

FAKE_PASSWORD = "mat-khau-gia"
FAKE_HOST = "camera.test"

#: Một số test cố ý dùng **mã G.711 và bộ đóng gói RTP thật** của thư viện
#: ``rtsp-backchannel`` (chỉ thay phần mạng), vì thứ cần chứng minh chính là
#: "gói RTP sinh ra đúng". Máy chưa cài thư viện thì các test đó báo *skip* kèm
#: lý do thay vì fail giả; phần import-an-toàn và cấu hình vẫn chạy được ở mọi
#: máy vì chúng không chạm tới thư viện.
def _library_available() -> bool:
    """Thử import thật, không chỉ dò ``find_spec``.

    ``find_spec`` trả về spec cho cả module bị chặn ở tầng loader (đúng kiểu
    test "máy thiếu thư viện" dựng bằng meta-path hook), nên chỉ dò spec sẽ
    đánh dấu "có" rồi fail — import thật mới đúng câu hỏi.
    """
    try:
        # ``importlib.import_module`` thay vì ``import`` để pyflakes không coi
        # đây là import thừa, và để lỗi loader thật sự bị bắt.
        for module_name in ("rtsp_backchannel", "backchannel_rtp", "onvif_play"):
            importlib.import_module(module_name)
    except ImportError:
        return False
    return True


requires_library = pytest.mark.skipif(
    not _library_available(),
    reason=(
        "cần 'rtsp-backchannel' để chạy mã G.711/RTP thật: "
        "pip install rtsp-backchannel==0.5.2"
    ),
)


#: SDP mà camera của dự án trả về khi DESCRIBE kèm ``Require: ...backchannel``.
#: Track 3 là ``sendonly`` — không có header ``Require`` thì camera chỉ trả hai
#: track ``recvonly`` và loa "biến mất".
FAKE_SEND_TRACK = "\r\n".join(
    (
        "m=audio 0 RTP/AVP 0 8",
        "a=sendonly",
        "a=control:rtsp://camera.test:554/1/2/trackID=3",
        "a=rtpmap:0 PCMU/8000/1",
        "a=rtpmap:8 PCMA/8000/1",
    )
)


# --------------------------------------------------------------------------
# Thay thế mạng: transport giả + pacer không ngủ
# --------------------------------------------------------------------------
class FakeTransport:
    """Đóng vai ``BackchannelTransport``: ghi lại gói RTP, không mở socket."""

    def __init__(self, send_track: str = FAKE_SEND_TRACK, rtp_channel: int = 4):
        self.send_track = send_track
        self.rtp_channel = rtp_channel
        self.packets: list[bytes] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        return False

    def check_keepalive(self):
        return None

    def send_rtp(self, packet):
        self.packets.append(bytes(packet))


class InstantPacer:
    """``RtpPacer`` không ngủ — chỉ ghi lại số mẫu đã đặt nhịp."""

    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.waited: list[int] = []
        self.finished = False

    def wait(self, samples):
        self.waited.append(samples)

    def finish(self):
        self.finished = True


def make_controller(**kwargs):
    """Controller trỏ vào camera giả, transport giả, pacer không ngủ."""
    transport = FakeTransport(**kwargs.pop("transport_kwargs", {}))
    opener_calls = []

    def opener(uri, user, password):
        opener_calls.append((uri, user, password))
        return transport

    controller = SpeakController(
        SpeakerConfig(
            host=FAKE_HOST,
            port=554,
            stream_path="/1/2",
            user="admin",
            password=FAKE_PASSWORD,
        ),
        transport_opener=opener,
        pacer_factory=InstantPacer,
        **kwargs,
    )
    return controller, transport, opener_calls


def rtp_header(packet: bytes) -> tuple[int, int, int]:
    """``(payload_type, sequence, timestamp)`` của một gói RTP v2."""
    first, second, sequence, timestamp = struct.unpack("!BBHI", packet[:8])
    assert first & 0xC0 == 0x80, "gói phải là RTP v2"
    return second & 0x7F, sequence, timestamp


# --------------------------------------------------------------------------
# Phát tiếng bíp
# --------------------------------------------------------------------------
@requires_library
def test_speak_tone_sends_expected_packet_count():
    """500 ms ở 8 kHz chia 320 mẫu/gói → 13 gói (12 gói đầy + 1 gói lẻ)."""
    controller, transport, _ = make_controller()

    result = controller.speak_tone(880, 0.5)

    expected_samples = 8000 * 500 // 1000  # 4000 mẫu
    expected_packets = -(-expected_samples // SAMPLES_PER_PACKET)  # 13
    assert result.packets_sent == expected_packets
    assert len(transport.packets) == expected_packets
    assert result.duration_seconds == pytest.approx(0.5)
    assert result.codec == "PCMA"
    assert transport.closed, "phiên backchannel phải được đóng sau khi phát"


@requires_library
def test_speak_tone_encodes_g711_pcma_and_uses_payload_type_8():
    """Mỗi gói mang payload type của PCMA và payload G.711 đúng số mẫu."""
    controller, transport, _ = make_controller()

    controller.speak_tone(440, 0.1)  # 800 mẫu → 3 gói: 320, 320, 160

    assert [len(packet) - 12 for packet in transport.packets] == [320, 320, 160]
    payload_types = {rtp_header(packet)[0] for packet in transport.packets}
    assert payload_types == {8}, "PCMA là payload type tĩnh 8"

    sequences = [rtp_header(packet)[1] for packet in transport.packets]
    assert sequences == [(sequences[0] + index) & 0xFFFF
                         for index in range(len(sequences))]

    timestamps = [rtp_header(packet)[2] for packet in transport.packets]
    gaps = [
        (timestamps[index + 1] - timestamps[index]) & 0xFFFFFFFF
        for index in range(len(timestamps) - 1)
    ]
    assert gaps == [320, 320], "dấu thời gian phải tăng đúng số mẫu mỗi gói"

    # Marker bit bật ở gói đầu (không phải gói cuối) — đúng cách thư viện làm.
    assert transport.packets[0][1] & 0x80


def test_speak_tone_rejects_duration_above_limit_before_touching_network():
    """Thời lượng quá lớn bị chặn ở 400 và không mở phiên nào."""
    controller, transport, opener_calls = make_controller()

    with pytest.raises(CameraAudioInputError) as info:
        controller.speak_tone(440, MAX_SPEAK_DURATION_S + 0.5)

    assert "tối đa" in str(info.value)
    assert opener_calls == []
    assert transport.packets == []


@pytest.mark.parametrize(
    "frequency,duration",
    [
        (0, 0.5),
        (440, 0),
        (9000, 0.5),  # trên Nyquist của 8 kHz
        ("880", 0.5),
        (440, "0.5"),
        (True, 0.5),  # bool là int trong Python — phải bị từ chối
        (float("nan"), 0.5),
        (440, float("inf")),
    ],
)
def test_speak_tone_rejects_bad_parameters(frequency, duration):
    controller, _, opener_calls = make_controller()

    with pytest.raises(CameraAudioInputError):
        controller.speak_tone(frequency, duration)
    assert opener_calls == []


@requires_library
def test_speak_tone_uses_configured_max_duration():
    """Chặn trên đặt qua constructor được tôn trọng (route không cần biết)."""
    controller, _, _ = make_controller(max_duration_s=0.2)

    with pytest.raises(CameraAudioInputError):
        controller.speak_tone(440, 0.25)
    assert controller.speak_tone(440, 0.2).packets_sent == 5  # 1600 / 320


@requires_library
def test_speak_tone_survives_camera_without_g711():
    """Camera chỉ mời G.726/AAC → lỗi tiếng Việt, không traceback."""
    only_g726 = "\r\n".join(
        (
            "m=audio 0 RTP/AVP 99",
            "a=sendonly",
            "a=control:rtsp://camera.test:554/1/2/trackID=3",
            "a=rtpmap:99 G726-32/8000/1",
        )
    )
    controller, transport, _ = make_controller(
        transport_kwargs={"send_track": only_g726}
    )

    with pytest.raises(CameraAudioError) as info:
        controller.speak_tone(440, 0.2)
    assert "G.711" in str(info.value)
    assert transport.packets == []


@requires_library
def test_speak_tone_wraps_camera_failure_in_vietnamese_message():
    """Lỗi mạng/RTSP → CameraAudioError tiếng Việt, không lộ traceback."""

    class ExplodingTransport(FakeTransport):
        def send_rtp(self, packet):
            raise OSError("socket đứt giữa chừng")

    transport = ExplodingTransport()
    controller = SpeakController(
        SpeakerConfig(host=FAKE_HOST, user="admin", password=FAKE_PASSWORD),
        transport_opener=lambda uri, user, password: transport,
        pacer_factory=InstantPacer,
    )

    with pytest.raises(CameraAudioError) as info:
        controller.speak_tone(440, 0.2)
    message = str(info.value)
    assert "Không phát được tiếng ra loa camera" in message
    assert "socket đứt giữa chừng" in message
    assert FAKE_PASSWORD not in message


# --------------------------------------------------------------------------
# Phát file
# --------------------------------------------------------------------------
def test_speak_file_without_ffmpeg_gives_clear_vietnamese_error(tmp_path, monkeypatch):
    """Máy không có ffmpeg → lỗi tiếng Việt chỉ cách cài, không traceback."""
    monkeypatch.setattr(camera_audio, "ffmpeg_available", lambda: False)
    monkeypatch.setattr(camera_audio.shutil, "which", lambda name: None)
    audio_file = tmp_path / "tieng.mp3"
    audio_file.write_bytes(b"khong-phai-mp3-that")
    controller, transport, opener_calls = make_controller()

    with pytest.raises(CameraAudioUnavailable) as info:
        controller.speak_file(str(audio_file))

    message = str(info.value)
    assert "ffmpeg" in message
    assert "Cài" in message or "cài" in message
    assert "tiếng bíp" in message
    # Không được mở kết nối chỉ để rồi thất bại.
    assert opener_calls == []
    assert transport.packets == []


def test_speak_file_rejects_missing_file_before_checking_ffmpeg(tmp_path, monkeypatch):
    """File không tồn tại → lỗi tham số, dù ffmpeg có hay không."""
    monkeypatch.setattr(camera_audio, "ffmpeg_available", lambda: False)
    controller, _, opener_calls = make_controller()

    with pytest.raises(CameraAudioInputError) as info:
        controller.speak_file(str(tmp_path / "khong-ton-tai.mp3"))
    assert "Không thấy file" in str(info.value)
    assert opener_calls == []


def test_speak_file_calls_library_play_file_with_credentials(tmp_path, monkeypatch):
    """Có ffmpeg → gọi ``play_file`` của thư viện với URL sạch + user/mật khẩu."""
    audio_file = tmp_path / "tieng.wav"
    audio_file.write_bytes(b"RIFF....WAVE")
    calls = []

    class FakePlayback:
        codec = "PCMA"
        sample_rate = 8000
        packets_sent = 25
        duration_seconds = 0.5

    def fake_play_file(**kwargs):
        calls.append(kwargs)
        return FakePlayback()

    # Thay cả bảng thư viện: ``_play_file`` chỉ dùng khóa ``play_file``.
    monkeypatch.setattr(camera_audio, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        camera_audio, "_load_library", lambda: {"play_file": fake_play_file}
    )
    controller, transport, opener_calls = make_controller()

    result = controller.speak_file(str(audio_file))

    assert result.mode == "file"
    assert result.codec == "PCMA"
    assert result.packets_sent == 25
    assert result.duration_seconds == pytest.approx(0.5)
    assert len(calls) == 1
    assert calls[0]["file"] == str(audio_file)
    assert calls[0]["user"] == "admin"
    assert calls[0]["password"] == FAKE_PASSWORD
    assert calls[0]["host"] == "rtsp://camera.test:554/1/2"
    assert FAKE_PASSWORD not in calls[0]["host"]
    assert calls[0]["codec"] == "auto"
    # ``play_file`` tự mở phiên riêng; controller không mở thêm phiên nào.
    assert opener_calls == []
    assert transport.packets == []


def test_speak_file_wraps_library_failure_in_vietnamese(tmp_path, monkeypatch):
    """Lỗi từ thư viện → CameraAudioError tiếng Việt, mật khẩu bị che."""

    def fake_play_file(**kwargs):
        raise RuntimeError(f"401 Unauthorized for admin:{FAKE_PASSWORD}")

    monkeypatch.setattr(camera_audio, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        camera_audio, "_load_library", lambda: {"play_file": fake_play_file}
    )
    audio_file = tmp_path / "tieng.wav"
    audio_file.write_bytes(b"RIFF....WAVE")
    controller, _, _ = make_controller()

    with pytest.raises(CameraAudioError) as info:
        controller.speak_file(str(audio_file))

    assert "Không phát được file ra loa camera" in str(info.value)
    assert FAKE_PASSWORD not in str(info.value)


def test_speak_file_rejects_bad_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_audio, "ffmpeg_available", lambda: True)
    audio_file = tmp_path / "tieng.wav"
    audio_file.write_bytes(b"RIFF....WAVE")
    controller, _, opener_calls = make_controller()

    with pytest.raises(CameraAudioInputError) as info:
        controller.speak_file(str(audio_file), volume=2.0)
    assert "volume" in str(info.value)
    assert opener_calls == []


def test_ffmpeg_available_reflects_shutil_which(monkeypatch):
    """Hàm dò ffmpeg phải đi qua ``shutil.which`` — chỗ test thay được."""
    monkeypatch.setattr(camera_audio.shutil, "which", lambda name: None)
    assert ffmpeg_available() is False
    monkeypatch.setattr(camera_audio.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert ffmpeg_available() is True


# --------------------------------------------------------------------------
# Khóa: một luồng phát tại một thời điểm
# --------------------------------------------------------------------------
@requires_library
def test_concurrent_speak_is_rejected_not_queued():
    """Lời gọi thứ hai khi đang phát → CameraAudioBusy ngay, không xếp hàng."""
    started = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    results = []

    class BlockingTransport(FakeTransport):
        def send_rtp(self, packet):
            started.set()
            assert release.wait(timeout=5.0), "test tự treo: cờ không được bật"
            super().send_rtp(packet)

    transport = BlockingTransport()
    controller = SpeakController(
        SpeakerConfig(host=FAKE_HOST, user="admin", password=FAKE_PASSWORD),
        transport_opener=lambda uri, user, password: transport,
        pacer_factory=InstantPacer,
    )

    def first_call():
        try:
            results.append(controller.speak_tone(440, 0.5))
        except BaseException as exc:  # noqa: BLE001 - ghi lại để assert
            errors.append(exc)

    worker = threading.Thread(target=first_call)
    worker.start()
    try:
        assert started.wait(timeout=5.0), "lời gọi đầu chưa kịp gửi gói nào"
        assert controller.busy is True

        with pytest.raises(CameraAudioBusy) as info:
            controller.speak_tone(880, 0.2)
        assert "đang phát" in str(info.value)
    finally:
        release.set()
        worker.join(timeout=5.0)

    assert not worker.is_alive(), "luồng đầu phải kết thúc sau khi mở khóa"
    assert errors == []
    assert len(results) == 1
    # Chỉ có gói của lời gọi đầu; lời gọi bị từ chối không gửi gì thêm.
    assert len(transport.packets) == results[0].packets_sent
    assert controller.busy is False


@requires_library
def test_lock_released_when_playback_raises():
    """Lỗi giữa chừng vẫn phải nhả khóa, nếu không loa chết vĩnh viễn."""

    class ExplodingTransport(FakeTransport):
        def send_rtp(self, packet):
            raise OSError("hỏng")

    transport = ExplodingTransport()
    controller = SpeakController(
        SpeakerConfig(host=FAKE_HOST, user="admin", password=FAKE_PASSWORD),
        transport_opener=lambda uri, user, password: transport,
        pacer_factory=InstantPacer,
    )

    with pytest.raises(CameraAudioError):
        controller.speak_tone(440, 0.2)
    assert controller.busy is False

    transport.send_rtp = FakeTransport.send_rtp.__get__(transport)
    assert controller.speak_tone(440, 0.2).packets_sent == 5


# --------------------------------------------------------------------------
# Cấu hình
# --------------------------------------------------------------------------
def test_speaker_config_from_config_requires_onvif_section():
    """Config không có ``camera.onvif`` → lỗi tiếng Việt, không AttributeError."""
    with pytest.raises(CameraAudioConfigError) as info:
        speaker_config_from_config(Config())
    assert "camera.onvif" in str(info.value)


def test_speaker_config_reads_password_from_environment(monkeypatch):
    """Mật khẩu chỉ đến từ biến môi trường, không từ file cấu hình."""
    monkeypatch.setenv(ONVIF_PASSWORD_ENV, FAKE_PASSWORD)
    config = Config()
    config.camera = _camera_with_onvif(
        {"host": FAKE_HOST, "port": 554, "user": "admin", "stream_path": "/1/2"}
    )

    speaker = speaker_config_from_config(config)

    assert speaker.host == FAKE_HOST
    assert speaker.user == "admin"
    assert speaker.password == FAKE_PASSWORD
    assert speaker.stream_uri == "rtsp://camera.test:554/1/2"
    assert FAKE_PASSWORD not in speaker.stream_uri
    assert FAKE_PASSWORD not in repr(speaker), "repr() lọt vào log — phải che"


def test_environment_password_wins_over_config_file(monkeypatch, caplog):
    """Biến môi trường thắng mật khẩu trong file — file cấu hình được commit."""
    monkeypatch.setenv(ONVIF_PASSWORD_ENV, "mat-khau-tu-moi-truong")
    config = Config()
    config.camera = _camera_with_onvif(
        {"host": FAKE_HOST, "user": "admin", "password": FAKE_PASSWORD}
    )

    with caplog.at_level("WARNING", logger="posture_monitor.camera_audio"):
        speaker = speaker_config_from_config(config)

    assert speaker.password == "mat-khau-tu-moi-truong"
    assert FAKE_PASSWORD not in caplog.text
    assert not [r for r in caplog.records if "file cấu hình" in r.getMessage()]


def test_password_taken_from_config_file_is_flagged(monkeypatch, caplog):
    """Không có biến môi trường → dùng được nhưng phải cảnh báo rõ."""
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)
    config = Config()
    config.camera = _camera_with_onvif(
        {"host": FAKE_HOST, "user": "admin", "password": FAKE_PASSWORD}
    )

    with caplog.at_level("WARNING", logger="posture_monitor.camera_audio"):
        speaker = speaker_config_from_config(config)

    assert speaker.password == FAKE_PASSWORD
    assert any("biến môi trường" in r.getMessage() for r in caplog.records)
    assert FAKE_PASSWORD not in caplog.text, "cảnh báo không được chứa mật khẩu"


def test_speaker_config_requires_password_when_user_is_set(monkeypatch):
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)
    config = Config()
    config.camera = _camera_with_onvif({"host": FAKE_HOST, "user": "admin"})

    with pytest.raises(CameraAudioConfigError) as info:
        speaker_config_from_config(config)
    assert ONVIF_PASSWORD_ENV in str(info.value)


def test_speaker_config_from_stream_uri_strips_credentials():
    config = Config()
    config.camera = _camera_with_onvif(
        {"stream_uri": "rtsp://admin:mat-khau-gia@camera.test:554/1/2"}
    )

    speaker = speaker_config_from_config(config)

    assert speaker.user == "admin"
    assert speaker.password == FAKE_PASSWORD
    assert speaker.stream_uri == "rtsp://camera.test:554/1/2"


def test_speaker_config_rejects_scheme_in_host():
    with pytest.raises(CameraAudioConfigError) as info:
        SpeakerConfig(host="rtsp://camera.test")
    assert "host" in str(info.value)


def _camera_with_onvif(onvif: dict):
    """Gắn object ``onvif`` kiểu dict vào ``config.camera`` như Peer kia làm."""
    camera = Config().camera
    camera.onvif = dict(onvif)
    return camera


# --------------------------------------------------------------------------
# Route Flask
# --------------------------------------------------------------------------
def _app_without_config():
    return create_app().test_client()


def test_speak_route_returns_4xx_without_onvif_config():
    """Thiếu ``camera.onvif`` → 403 tiếng Việt, không sập app.

    403 (không phải 503) để khớp cách ``/stream`` báo "tính năng chưa bật
    trong config", và vì đây là cấu hình thiếu chứ không phải máy chủ hỏng.
    """
    client = _app_without_config()

    response = client.post("/api/speak", json={"tone_hz": 440, "duration": 0.2})

    assert response.status_code == 403
    body = response.get_json()
    assert body["ok"] is False
    assert "camera.onvif" in body["message"]


@requires_library
def test_speak_route_plays_tone_with_injected_controller():
    controller, transport, _ = make_controller()
    client = create_app(speak_controller=controller).test_client()

    response = client.post("/api/speak", json={"tone_hz": 880, "duration": 0.2})

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["mode"] == "tone"
    assert body["codec"] == "PCMA"
    assert body["packets_sent"] == len(transport.packets) == 5
    assert body["duration_seconds"] == pytest.approx(0.2)


@requires_library
def test_speak_route_defaults_to_short_beep():
    """Không gửi thân JSON vẫn phát được tiếng bíp mặc định."""
    controller, transport, _ = make_controller()
    client = create_app(speak_controller=controller).test_client()

    response = client.post("/api/speak")

    assert response.status_code == 200
    assert response.get_json()["packets_sent"] == len(transport.packets)
    assert transport.packets, "mặc định phải thật sự phát, không phải no-op"


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"tone_hz": 440, "duration": 60}, 400),  # quá dài
        ({"tone_hz": 0, "duration": 0.2}, 400),  # tần số ngoài khoảng
        ({"tone_hz": "440", "duration": 0.2}, 400),  # kiểu sai
        ({"file": 123}, 400),  # file phải là chuỗi
        ([1, 2, 3], 400),  # thân không phải object
    ],
)
def test_speak_route_rejects_bad_input_with_4xx(payload, status):
    controller, transport, opener_calls = make_controller()
    client = create_app(speak_controller=controller).test_client()

    response = client.post("/api/speak", json=payload)

    assert response.status_code == status
    assert response.get_json()["ok"] is False
    assert opener_calls == []
    assert transport.packets == []


@requires_library
def test_speak_route_returns_409_when_busy():
    started = threading.Event()
    release = threading.Event()

    class BlockingTransport(FakeTransport):
        def send_rtp(self, packet):
            started.set()
            release.wait(timeout=5.0)
            super().send_rtp(packet)

    transport = BlockingTransport()
    controller = SpeakController(
        SpeakerConfig(host=FAKE_HOST, user="admin", password=FAKE_PASSWORD),
        transport_opener=lambda uri, user, password: transport,
        pacer_factory=InstantPacer,
    )
    client = create_app(speak_controller=controller).test_client()
    worker = threading.Thread(
        target=lambda: controller.speak_tone(440, 0.5), daemon=True
    )
    worker.start()
    try:
        assert started.wait(timeout=5.0)
        response = client.post("/api/speak", json={"tone_hz": 880, "duration": 0.2})
    finally:
        release.set()
        worker.join(timeout=5.0)

    assert response.status_code == 409
    assert "đang phát" in response.get_json()["message"]


@requires_library
def test_speak_route_reports_camera_error_without_leaking_password(monkeypatch):
    """Lỗi camera → 502, thông điệp tiếng Việt và **không** chứa mật khẩu."""

    class LeakyTransport(FakeTransport):
        def send_rtp(self, packet):
            raise RuntimeError(f"auth failed for admin:{FAKE_PASSWORD}")

    transport = LeakyTransport()
    controller = SpeakController(
        SpeakerConfig(host=FAKE_HOST, user="admin", password=FAKE_PASSWORD),
        transport_opener=lambda uri, user, password: transport,
        pacer_factory=InstantPacer,
    )
    client = create_app(speak_controller=controller).test_client()

    response = client.post("/api/speak", json={"tone_hz": 440, "duration": 0.2})

    assert response.status_code == 502
    message = response.get_json()["message"]
    assert FAKE_PASSWORD not in message
    assert REDACTED in message or "loa camera" in message


def test_speak_route_rejects_malformed_json_body():
    """JSON hỏng → 400, không được lặng lẽ phát bíp mặc định."""
    controller, transport, _ = make_controller()
    client = create_app(speak_controller=controller).test_client()

    response = client.post(
        "/api/speak",
        data="{tone_hz: ",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "JSON" in response.get_json()["message"]
    assert transport.packets == []


def test_speak_route_missing_ffmpeg_is_503(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_audio, "ffmpeg_available", lambda: False)
    audio_file = tmp_path / "tieng.wav"
    audio_file.write_bytes(b"RIFF....WAVE")
    controller, _, opener_calls = make_controller()
    client = create_app(speak_controller=controller).test_client()

    response = client.post("/api/speak", json={"file": str(audio_file)})

    assert response.status_code == 503
    assert "ffmpeg" in response.get_json()["message"]
    assert opener_calls == []


def test_existing_routes_still_work_after_adding_speak():
    """Thêm route không được đổi hành vi ``/api/mute`` và ``/api/status``."""
    client = create_app().test_client()

    assert client.get("/api/status").status_code == 200
    muted = client.post("/api/mute", json={"muted": True}).get_json()
    assert muted["ok"] is True and muted["muted"] is True


# --------------------------------------------------------------------------
# Import an toàn (spec §11.4)
# --------------------------------------------------------------------------
def test_module_imports_without_rtsp_backchannel(monkeypatch):
    """Thiếu thư viện → lỗi tiếng Việt khi gọi, không lỗi lúc import."""
    monkeypatch.setitem(sys.modules, "rtsp_backchannel", None)
    monkeypatch.setitem(sys.modules, "rtsp_backchannel.playback", None)
    monkeypatch.setitem(sys.modules, "onvif_play", None)
    monkeypatch.setitem(sys.modules, "backchannel_rtp", None)

    with pytest.raises(CameraAudioUnavailable) as info:
        camera_audio._load_library()

    message = str(info.value)
    assert "rtsp-backchannel" in message
    assert "pip install" in message
    assert camera_audio.SpeakController is not None  # module vẫn dùng được


def test_speak_tone_without_library_does_not_open_transport(monkeypatch):
    monkeypatch.setattr(
        camera_audio,
        "_load_library",
        lambda: (_ for _ in ()).throw(_missing_library_error()),
    )
    controller, transport, opener_calls = make_controller()

    with pytest.raises(CameraAudioUnavailable):
        controller.speak_tone(440, 0.2)
    assert opener_calls == []
    assert transport.packets == []
    assert controller.busy is False


def _missing_library_error() -> CameraAudioUnavailable:
    return CameraAudioUnavailable(
        "Thiếu thư viện 'rtsp-backchannel' nên chưa phát được tiếng ra loa camera."
    )
