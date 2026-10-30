"""Kiểm thử ``speaker_alert.py`` — quyết định **phát gì, khi nào** ra loa.

Chạy trên PC, **không cần camera, không cần loa, không cần ``espeak-ng``,
không cần ``ffmpeg``**:

- ``controller`` là bản giả ghi lại từng lời gọi (``speak_file``/``speak_tone``)
  và cờ ``busy``; không có socket nào được mở.
- ``espeak_runner`` là bản giả ghi file rỗng — nó kiểm tra *quyết định* của
  alerter, không kiểm tra chất lượng giọng đọc (chưa đo được, xem spec §18).
- ``audio_dir`` là ``tmp_path``; test không ghi vào ``data/`` thật.
- Đồng hồ tiêm bằng bộ đếm giả: không ``sleep``.

Ranh giới trách nhiệm được khoá ở đây: alerter **không** đếm cooldown (việc
đó thuộc ``schedule.should_alert``) và **không** xếp hàng khi loa bận.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.camera_audio import (  # noqa: E402
    CameraAudioBusy,
    CameraAudioError,
    CameraAudioUnavailable,
)
from posture_monitor.schedule import (  # noqa: E402
    KIND_LEAVE_FRAME,
    KIND_PHONE,
    KIND_STRANGER,
)
from posture_monitor.speaker_alert import (  # noqa: E402
    ALERT_ABSENT,
    ALERT_IMPOSTOR,
    ALERT_KINDS,
    ALERT_PHONE_USE,
    ALERT_TEXT,
    MODE_SKIPPED,
    MODE_SPEECH,
    MODE_TONE,
    PRIORITY,
    SpeakerAlerter,
)


class FakeController:
    """Controller giả: ghi lại lời gọi, không chạm phần cứng.

    Args:
        busy: giá trị ``busy`` trả về.
        error: nếu khác ``None``, mọi lời gọi phát đều ném lỗi này.
    """

    def __init__(self, *, busy: bool = False, error: BaseException | None = None):
        self.busy = busy
        self.error = error
        self.calls: list[tuple[str, object, object]] = []

    def speak_file(self, path: str, volume: float = 1.0):
        self.calls.append(("file", path, volume))
        if self.error is not None:
            raise self.error
        return object()

    def speak_tone(self, frequency_hz: float = 440.0, duration_s: float = 0.5):
        self.calls.append(("tone", frequency_hz, duration_s))
        if self.error is not None:
            raise self.error
        return object()


class FakeEspeak:
    """``espeak_runner`` giả: ghi file rỗng và đếm số lần gọi."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def __call__(self, text: str, out_path: str) -> None:
        self.calls.append((text, out_path))
        if self.error is not None:
            raise self.error
        Path(out_path).write_bytes(b"RIFF-fake")


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now


def _alerter(tmp_path, *, controller=None, **kwargs):
    """Alerter với ``espeak_runner`` giả đã ``prepare()`` sẵn (mặc định)."""
    runner = kwargs.pop("espeak_runner", None) or FakeEspeak()
    alerter = SpeakerAlerter(
        controller if controller is not None else FakeController(),
        audio_dir=tmp_path,
        espeak_runner=runner,
        **kwargs,
    )
    return alerter, runner


def _write_wav(path: Path, *, frames: int = 800) -> Path:
    """Ghi một WAV 8 kHz mono hợp lệ (im lặng) để ``prepare`` dùng lại."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * frames)
    return path


# --------------------------------------------------------------------------
# Hằng số — khớp hợp đồng spec §5.15 và tên khóa của schedule
# --------------------------------------------------------------------------
def test_alert_kinds_match_schedule_keys():
    """Ba hằng số phải trùng **đúng chuỗi** khóa của ``schedule.ALERT_KINDS``.

    Đặt tên thứ hai rồi ánh xạ ở nơi khác là cách chắc chắn nhất để hai tầng
    lệch nhau; test này chốt rằng không có tầng ánh xạ nào.
    """
    assert ALERT_ABSENT == KIND_LEAVE_FRAME
    assert ALERT_PHONE_USE == KIND_PHONE
    assert ALERT_IMPOSTOR == KIND_STRANGER
    assert set(ALERT_KINDS) == {KIND_LEAVE_FRAME, KIND_PHONE, KIND_STRANGER}


def test_priority_order_is_impostor_absent_phone():
    """Người lạ nghiêm trọng nhất, rồi vắng mặt, rồi điện thoại."""
    assert PRIORITY == (ALERT_IMPOSTOR, ALERT_ABSENT, ALERT_PHONE_USE)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (ALERT_ABSENT, "Bạn ơi, quay lại bàn học nhé"),
        (ALERT_PHONE_USE, "Cất điện thoại và tập trung học nhé"),
        (ALERT_IMPOSTOR, "Người đang ngồi không phải người đã đăng ký học"),
    ],
)
def test_alert_text_matches_spec_verbatim(kind, expected):
    """Câu tiếng Việt đúng nguyên văn spec §5.15, từng chữ."""
    assert ALERT_TEXT[kind] == expected


# --------------------------------------------------------------------------
# Test 1 — ưu tiên khi hai sự kiện cùng lúc
# --------------------------------------------------------------------------
def test_alert_many_plays_only_highest_priority(tmp_path):
    """PHONE_USE + IMPOSTOR cùng lúc → chỉ **một** lời gọi, đúng câu IMPOSTOR."""
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert_many([ALERT_PHONE_USE, ALERT_IMPOSTOR])

    assert outcome.kind == ALERT_IMPOSTOR
    assert outcome.text == ALERT_TEXT[ALERT_IMPOSTOR]
    assert outcome.spoken is True
    assert outcome.mode == MODE_SPEECH
    assert len(controller.calls) == 1, controller.calls
    verb, path, _volume = controller.calls[0]
    assert verb == "file"
    assert path.endswith(f"{ALERT_IMPOSTOR}.wav")


def test_alert_many_absent_beats_phone(tmp_path):
    """Vắng mặt đứng trên điện thoại: cùng lúc thì chỉ nói câu vắng mặt."""
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert_many([ALERT_PHONE_USE, ALERT_ABSENT])

    assert outcome.kind == ALERT_ABSENT
    assert len(controller.calls) == 1


# --------------------------------------------------------------------------
# Test 2 — loa bận: bỏ, không phát, không xếp hàng
# --------------------------------------------------------------------------
def test_busy_skips_without_playing(tmp_path):
    """``controller.busy is True`` → ``skipped``, không gọi phát, không raise."""
    controller = FakeController(busy=True)
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert(ALERT_ABSENT)

    assert outcome.mode == MODE_SKIPPED
    assert outcome.spoken is False
    assert "bận" in outcome.reason.lower() or "đang phát" in outcome.reason
    assert controller.calls == []
    assert outcome.error is None


# --------------------------------------------------------------------------
# Test 3, 4, 5 — lỗi loa không bao giờ ném ra ngoài
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("error", "expected_mode", "expected_calls"),
    [
        # Loa bận/ lỗi thiết bị: đã thử đúng một lần rồi dừng.
        (CameraAudioBusy("Loa camera đang phát tiếng khác."), MODE_SKIPPED, 1),
        # Thiếu thư viện: `speak_file` không chạy được nên *có* thử bíp — và
        # bản giả này cũng hỏng, nên kết quả cuối vẫn là `skipped`.
        (CameraAudioUnavailable("Thiếu thư viện 'rtsp-backchannel'."), MODE_SKIPPED, 2),
        (CameraAudioError("Camera từ chối backchannel."), MODE_SKIPPED, 1),
        (RuntimeError("lỗi bất ngờ của thiết bị"), MODE_SKIPPED, 1),
    ],
    ids=["busy", "unavailable", "audio_error", "runtime_error"],
)
def test_speaker_error_is_returned_not_raised(
    tmp_path, error, expected_mode, expected_calls
):
    """Mọi lỗi loa → ``AlertOutcome`` có ``error``, **không** ném ra ngoài.

    Đây là yêu cầu cứng của spec §5.15: lỗi loa không được làm rơi vòng lặp
    camera. Tầng gọi đọc ``outcome.error`` để ghi ``SPEAK_FAILED``.
    """
    controller = FakeController(error=error)
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert(ALERT_IMPOSTOR)  # không được raise

    assert outcome.spoken is False
    assert outcome.mode == expected_mode
    assert outcome.error is not None
    assert type(error).__name__ in outcome.error
    assert len(controller.calls) == expected_calls, controller.calls


def test_unavailable_file_falls_back_to_tone_and_reports_error(tmp_path):
    """Thiếu ffmpeg: câu tiếng Việt không ra loa, nhưng **bíp** vẫn phát.

    Lỗi vẫn nằm ở ``outcome.error`` để tầng gọi biết lần này là bíp chứ
    không phải câu nói — không được im lặng.
    """
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    def fail_file(path, volume=1.0):
        controller.calls.append(("file", path, volume))
        raise CameraAudioUnavailable("Không tìm thấy ffmpeg trên máy này.")

    controller.speak_file = fail_file

    outcome = alerter.alert(ALERT_PHONE_USE)

    assert outcome.mode == MODE_TONE
    assert outcome.spoken is True
    assert outcome.error is not None and "ffmpeg" in outcome.error
    assert controller.calls[0][0] == "file"
    assert controller.calls[1][0] == "tone"


# --------------------------------------------------------------------------
# Test 6, 7 — espeak_runner hỏng, và tone_fallback tắt
# --------------------------------------------------------------------------
def test_espeak_failure_does_not_crash_and_alert_still_beeps(tmp_path):
    """``prepare()`` không crash khi ``espeak_runner`` lỗi; ``alert()`` vẫn bíp."""
    runner = FakeEspeak(error=RuntimeError("Không tìm thấy 'espeak-ng'"))
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, espeak_runner=runner, controller=controller)

    alerter.prepare()  # không được raise

    outcome = alerter.alert(ALERT_ABSENT)

    assert outcome.mode == MODE_TONE
    assert outcome.spoken is True
    assert controller.calls and controller.calls[0][0] == "tone"


def test_wav_co_san_duoc_dung_lai_khi_thieu_espeak(tmp_path):
    """File WAV đã có phải được dùng lại, không phụ thuộc ``espeak-ng``.

    Đây là ca đã xảy ra thật: ``data/audio/`` có WAV từ lần chạy trước nhưng
    máy không còn ``espeak-ng``; ``prepare()`` cũ sinh lại vô điều kiện nên
    thất bại và loa rơi về tiếng bíp dù file vẫn còn. Nay phải phát giọng nói.
    """
    for kind in ALERT_KINDS:
        _write_wav(tmp_path / f"{kind}.wav")
    runner = FakeEspeak(error=RuntimeError("Không tìm thấy 'espeak-ng'"))
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller, espeak_runner=runner)

    alerter.prepare()

    assert runner.calls == [], "không được gọi espeak-ng khi WAV đã có"
    outcome = alerter.alert(ALERT_ABSENT)
    assert outcome.mode == MODE_SPEECH
    assert controller.calls and controller.calls[0][0] == "file"


def test_wav_hong_thi_sinh_lai(tmp_path):
    """WAV rỗng/không hợp lệ không được coi là "đã có" — phải sinh lại."""
    (tmp_path / f"{ALERT_ABSENT}.wav").write_bytes(b"")
    runner = FakeEspeak()
    alerter, _ = _alerter(tmp_path, espeak_runner=runner)

    alerter.prepare()

    assert any(path.endswith(f"{ALERT_ABSENT}.wav") for _, path in runner.calls)


def test_no_espeak_and_no_fallback_skips_with_reason(tmp_path):
    """Không có giọng đọc + ``tone_fallback=False`` → ``skipped`` **có lý do**."""
    runner = FakeEspeak(error=RuntimeError("Không tìm thấy 'espeak-ng'"))
    controller = FakeController()
    alerter, _ = _alerter(
        tmp_path,
        controller=controller,
        espeak_runner=runner,
        tone_fallback=False,
    )

    alerter.prepare()
    outcome = alerter.alert(ALERT_ABSENT)

    assert outcome.mode == MODE_SKIPPED
    assert outcome.spoken is False
    assert "tone_fallback" in outcome.reason
    assert controller.calls == []


# --------------------------------------------------------------------------
# Test 8 — WAV sinh một lần lúc khởi động, không sinh lại
# --------------------------------------------------------------------------
def test_prepare_is_idempotent(tmp_path):
    """``prepare()`` gọi hai lần → ``espeak_runner`` chỉ chạy một lượt.

    Spec §5.15: sinh lại mỗi lần cảnh báo là lãng phí và gây trễ.
    """
    alerter, runner = _alerter(tmp_path, controller=FakeController())

    alerter.prepare()
    first = len(runner.calls)
    alerter.prepare()
    alerter.prepare()

    assert first == len(ALERT_KINDS)
    assert len(runner.calls) == first, runner.calls


def test_alert_does_not_regenerate_audio(tmp_path):
    """Ba lần cảnh báo không sinh thêm file: giọng đọc chỉ sinh lúc ``prepare``."""
    alerter, runner = _alerter(tmp_path, controller=FakeController())
    alerter.prepare()
    calls_after_prepare = len(runner.calls)

    for _ in range(3):
        alerter.alert(ALERT_ABSENT)

    assert len(runner.calls) == calls_after_prepare


def test_prepare_retries_missing_audio_on_next_call(tmp_path):
    """Lần đầu sinh lỗi thì lần sau thử lại — đường "cấu hình đổi" của spec."""
    runner = FakeEspeak(error=RuntimeError("tạm thời hỏng"))
    alerter, _ = _alerter(tmp_path, espeak_runner=runner)

    alerter.prepare()
    assert len(runner.calls) == len(ALERT_KINDS)

    runner.error = None  # "cấu hình đã sửa": espeak-ng dùng được
    alerter.prepare()

    assert len(runner.calls) == len(ALERT_KINDS) * 2
    assert all((tmp_path / f"{kind}.wav").is_file() for kind in ALERT_KINDS)


# --------------------------------------------------------------------------
# Test 9 — alerter KHÔNG đếm cooldown
# --------------------------------------------------------------------------
def test_repeated_alerts_all_play(tmp_path):
    """Ba lần cùng một loại → **ba lần phát**. Cooldown thuộc ``schedule``.

    Test này khoá ranh giới trách nhiệm. Nếu ai thêm bộ đếm cooldown vào
    alerter, luật cooldown sẽ bị áp hai lần và ca biên "đổi loại cảnh báo"
    sẽ mất tiếng mà không ai giải thích được.
    """
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcomes = [alerter.alert(ALERT_PHONE_USE) for _ in range(3)]

    assert [o.mode for o in outcomes] == [MODE_SPEECH] * 3
    assert len(controller.calls) == 3


# --------------------------------------------------------------------------
# Hành vi phụ — không cấu hình loa, loại lạ, clock
# --------------------------------------------------------------------------
def test_no_controller_skips_with_reason(tmp_path):
    """Chưa cấu hình loa → ``skipped`` có lý do, ``available`` là ``False``."""
    alerter = SpeakerAlerter(None, audio_dir=tmp_path, espeak_runner=FakeEspeak())

    assert alerter.available is False
    outcome = alerter.alert(ALERT_ABSENT)

    assert outcome.mode == MODE_SKIPPED
    assert outcome.spoken is False
    assert "loa camera" in outcome.reason


def test_unknown_kind_is_ignored_with_reason(tmp_path):
    """Loại không biết → ``skipped`` có lý do, không đoán loại gần giống."""
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)

    outcome = alerter.alert("khong_ton_tai")

    assert outcome.kind is None
    assert outcome.mode == MODE_SKIPPED
    assert outcome.reason
    assert controller.calls == []


# --------------------------------------------------------------------------
# Chuỗi bị truyền nhầm chỗ danh sách — guard ``isinstance(kinds, str)``
# --------------------------------------------------------------------------
def test_alert_many_accepts_bare_string_without_silently_dropping(tmp_path):
    """``alert_many("phone")`` (chuỗi, không phải danh sách) **phải phát**.

    Chuỗi cũng là ``Iterable[str]``, nên nếu thiếu guard ``isinstance(kinds,
    str)`` thì ``"phone"`` bị lặp thành từng ký tự ``p, h, o, n, e``; không
    ký tự nào có trong ``ALERT_TEXT`` nên kết quả là ``mode="skipped"``. Hệ
    thống vẫn chạy, cooldown vẫn đúng, log vẫn sạch — và **không bao giờ báo
    động**. Đó là kiểu hỏng tệ nhất, nên chốt lại: đúng một lần phát và
    ``kind == "phone"``.
    """
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert_many(ALERT_PHONE_USE)  # chuỗi, không phải list

    assert outcome.kind == ALERT_PHONE_USE
    assert outcome.text == ALERT_TEXT[ALERT_PHONE_USE]
    assert outcome.mode == MODE_SPEECH
    assert outcome.spoken is True
    assert len(controller.calls) == 1, controller.calls
    assert controller.calls[0][0] == "file"


def test_alert_with_bare_string_reaches_speaker_via_tuple_path(tmp_path):
    """``alert("phone")`` phát được — đường này **không** đi qua guard chuỗi.

    ``alert`` bọc thành ``(kind,)`` rồi mới gọi ``alert_many``, nên guard
    ``isinstance(kinds, str)`` không tham gia. Ghi lại sự thật đó để hai đường
    hỏng không bị gộp làm một: bỏ guard thì ``alert`` **vẫn** chạy, còn đổi
    ``alert`` thành chuyền thẳng chuỗi thì lại cần guard.
    """
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert(ALERT_PHONE_USE)

    assert outcome.kind == ALERT_PHONE_USE
    assert outcome.mode == MODE_SPEECH
    assert outcome.spoken is True
    assert len(controller.calls) == 1, controller.calls
    assert controller.calls[0][0] == "file"


def test_alert_many_empty_string_is_skipped_without_error(tmp_path):
    """Chuỗi rỗng → ``skipped`` có lý do, không ném lỗi, không phát gì."""
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert_many("")

    assert outcome.kind is None
    assert outcome.mode == MODE_SKIPPED
    assert outcome.spoken is False
    assert outcome.reason
    assert controller.calls == []


@pytest.mark.parametrize(
    "kinds",
    [(ALERT_PHONE_USE,), [ALERT_PHONE_USE], {ALERT_PHONE_USE}],
    ids=["tuple", "list", "set"],
)
def test_alert_many_container_forms_all_play_phone(tmp_path, kinds):
    """Tuple, list, set cùng một phần tử cho cùng kết quả như chuỗi.

    Guard không được làm hỏng những cách gọi vốn đã đúng.
    """
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    outcome = alerter.alert_many(kinds)

    assert outcome.kind == ALERT_PHONE_USE
    assert outcome.text == ALERT_TEXT[ALERT_PHONE_USE]
    assert outcome.mode == MODE_SPEECH
    assert outcome.spoken is True
    assert len(controller.calls) == 1, controller.calls


def test_alert_uses_injected_clock(tmp_path):
    """``now`` và ``clock`` tiêm được, để tầng gọi log đúng thời điểm."""
    clock = FakeClock(500.0)
    alerter = SpeakerAlerter(
        FakeController(),
        audio_dir=tmp_path,
        espeak_runner=FakeEspeak(),
        clock=clock,
    )
    alerter.prepare()

    assert alerter.alert(ALERT_ABSENT).at == 500.0
    assert alerter.alert(ALERT_ABSENT, now=1234.0).at == 1234.0


def test_say_false_goes_straight_to_tone(tmp_path):
    """``say=False`` → không sinh giọng đọc, phát bíp ngay."""
    controller = FakeController()
    runner = FakeEspeak()
    alerter = SpeakerAlerter(
        controller, audio_dir=tmp_path, say=False, espeak_runner=runner
    )
    alerter.prepare()

    outcome = alerter.alert(ALERT_ABSENT)

    assert runner.calls == []
    assert outcome.mode == MODE_TONE
    assert outcome.spoken is True
    assert controller.calls[0][0] == "tone"


def test_from_config_without_speaker_section_is_not_fatal(tmp_path):
    """``from_config`` với cấu hình chưa bật loa: alerter vẫn dựng, không crash.

    Loa tắt là cấu hình hợp lệ của v3 mặc định (``camera.speaker.enabled``
    là ``false``). Khởi động hỏng vì thế là chuyện không được phép xảy ra.
    """
    from posture_monitor.config import Config

    config = Config()
    alerter = SpeakerAlerter.from_config(config, audio_dir=tmp_path)

    assert alerter.available is False
    outcome = alerter.alert(ALERT_ABSENT)
    assert outcome.mode == MODE_SKIPPED
    assert outcome.reason


def test_from_config_reads_section_values(tmp_path):
    """Mục ``speaker_alert`` (dataclass hoặc dict) được đọc đúng khóa."""
    from types import SimpleNamespace

    for section in (
        SimpleNamespace(
            say=False, tone_fallback=False, audio_dir=str(tmp_path), language="vi"
        ),
        {
            "say": False,
            "tone_fallback": False,
            "audio_dir": str(tmp_path),
            "language": "vi",
        },
    ):
        alerter = SpeakerAlerter.from_config(
            SimpleNamespace(speaker_alert=section, camera=None),
            controller=FakeController(),
            espeak_runner=FakeEspeak(),
        )
        assert alerter.say is False
        assert alerter.tone_fallback is False
        assert alerter.audio_dir == tmp_path


def test_no_camera_url_or_password_is_logged(tmp_path, caplog):
    """Log của alerter không chứa URL camera hay mật khẩu (spec §11)."""
    controller = FakeController()
    alerter, _ = _alerter(tmp_path, controller=controller)
    alerter.prepare()

    with caplog.at_level("DEBUG"):
        alerter.alert(ALERT_IMPOSTOR)

    text = caplog.text
    assert "rtsp://" not in text
    assert "@" not in text.replace("'", "")  # userinfo dạng user:pass@host
    assert "mat-khau" not in text
