"""Test thư viện giọng đọc thu sẵn (``voice_library``) và đường phát giọng.

Trọng tâm:
- Nhận đúng file bản thu theo tên trùng mã loại **và** theo từ khoá trong tên
  (người dùng đặt tên theo câu đọc, không theo mã).
- Không đoán bừa khi tên file mơ hồ — thà rơi về giọng máy còn hơn đọc sai câu.
- Chọn giọng sai/thiếu file không được làm mất tiếng nói (rơi xuống espeak).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from posture_monitor import voice_library as vl
from posture_monitor.speaker_alert import (
    ALERT_KINDS,
    MODE_SPEECH,
    MODE_TONE,
    SpeakerAlerter,
)

KINDS = ("leave_frame", "phone", "stranger")


def _fake_wav(path: Path, *, frames: int = 2000) -> Path:
    """WAV hợp lệ tối thiểu: RIFF/WAVE + ``data`` chunk có dữ liệu."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\x00\x01" * (frames // 2)
    header = (
        b"RIFF"
        + (36 + len(payload)).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (22050).to_bytes(4, "little")
        + (44100).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + len(payload).to_bytes(4, "little")
        + payload
    )
    path.write_bytes(header)
    return path


# --------------------------------------------------------------------------
# Nhận dạng tên file
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name, expected",
    [
        # Tên trùng mã loại: chắc chắn tuyệt đối.
        ("phone.wav", "phone"),
        ("phone.mp3", "phone"),
        ("leave_frame.wav", "leave_frame"),
        ("stranger.m4a", "stranger"),
        # Tên theo câu đọc (đúng các file người dùng gửi kèm).
        ("Banoiquaylaibanhocnhegiongnam.mp3", "leave_frame"),
        ("catdienthoaigongnam.mp3", "phone"),
        ("khongphainguoidangkigiongnam.mp3", "stranger"),
        ("Banoiquaylaibanhocnhegiongnu.mp3", "leave_frame"),
        ("catdienthoaigiongnu.mp3", "phone"),
        ("khongphainguoidangkigiongnu.mp3", "stranger"),
        # Có dấu và khoảng trắng cũng nhận.
        ("Cất điện thoại.mp3", "phone"),
        ("Bạn ơi quay lại bàn học.mp3", "leave_frame"),
    ],
)
def test_classify_filename_recognises_real_names(name, expected):
    assert vl.classify_filename(name, KINDS) == expected


@pytest.mark.parametrize(
    "name",
    [
        "abc.mp3",
        "ghi_am_1.mp3",
        "",
        # Hai câu trong một tên: không được đoán, vì đọc sai nội dung còn tệ
        # hơn dùng giọng máy đúng nội dung.
        "dienthoai_va_nguoila.mp3",
        "quaylai_va_catdienthoai.mp3",
    ],
)
def test_classify_filename_refuses_ambiguous_names(name):
    assert vl.classify_filename(name, KINDS) is None


def test_classify_filename_requires_margin_between_top_two():
    """Một từ khoá duy nhất thì nhận; hai từ khoá của hai loại thì từ chối."""
    # "dienthoai" (9) khớp phone; không khớp gì khác.
    assert vl.classify_filename("dienthoai.mp3", KINDS) == "phone"
    # Tên chứa từ khoá của hai loại -> từ chối.
    assert vl.classify_filename("phone_stranger.mp3", KINDS) is None


def test_exact_name_wins_even_if_keyword_points_elsewhere():
    """Tên trùng mã loại thắng từ khoá — không có chuyện 'phone' thành stranger."""
    assert vl.classify_filename("phone.mp3", KINDS) == "phone"


# --------------------------------------------------------------------------
# Tìm file trong thư mục
# --------------------------------------------------------------------------
def test_find_clip_prefers_exact_kind_name(tmp_path):
    voice = tmp_path / "giongnam"
    _fake_wav(voice / "phone.mp3")
    _fake_wav(voice / "catdienthoaigongnam.mp3")
    found = vl.find_clip(tmp_path, "nam", "phone")
    assert found is not None
    assert found.name == "phone.mp3"


def test_find_clip_falls_back_to_keyword_name(tmp_path):
    voice = tmp_path / "giongnam"
    _fake_wav(voice / "catdienthoaigongnam.mp3")
    found = vl.find_clip(tmp_path, "nam", "phone")
    assert found is not None
    assert found.name == "catdienthoaigongnam.mp3"


def test_find_clip_prefers_wav_over_mp3_for_same_kind(tmp_path):
    voice = tmp_path / "giongnu"
    _fake_wav(voice / "phone.mp3")
    _fake_wav(voice / "phone.wav")
    found = vl.find_clip(tmp_path, "nu", "phone")
    assert found is not None
    assert found.suffix == ".wav"


def test_find_clip_ignores_empty_files(tmp_path):
    voice = tmp_path / "giongnam"
    voice.mkdir(parents=True)
    (voice / "phone.mp3").write_bytes(b"")
    assert vl.find_clip(tmp_path, "nam", "phone") is None


def test_find_clip_returns_none_for_synth_voice(tmp_path):
    """``espeak`` không có thư mục bản thu — không phải lỗi."""
    assert vl.find_clip(tmp_path, "espeak", "phone") is None


def test_find_clip_missing_directory_is_not_an_error(tmp_path):
    assert vl.find_clip(tmp_path, "nam", "phone") is None


def test_list_clips_only_returns_present_kinds(tmp_path):
    voice = tmp_path / "giongnam"
    _fake_wav(voice / "phone.mp3")
    _fake_wav(voice / "stranger.mp3")
    found = vl.list_clips(tmp_path, "nam", KINDS)
    assert set(found) == {"phone", "stranger"}


def test_available_voices_reports_missing_kinds(tmp_path):
    voice = tmp_path / "giongnam"
    _fake_wav(voice / "phone.mp3")
    report = vl.available_voices(tmp_path, KINDS)
    assert report["nam"]["ready"] is False
    assert set(report["nam"]["missing"]) == {"leave_frame", "stranger"}
    assert report["nam"]["clips"] == {"phone": "phone.mp3"}
    # Giọng máy luôn sẵn sàng (không phụ thuộc thư mục).
    assert report["espeak"]["ready"] is True


def test_available_voices_ready_when_all_three_present(tmp_path):
    voice = tmp_path / "giongnu"
    for kind in KINDS:
        _fake_wav(voice / f"{kind}.mp3")
    report = vl.available_voices(tmp_path, KINDS)
    assert report["nu"]["ready"] is True
    assert report["nu"]["missing"] == []


# --------------------------------------------------------------------------
# Nhớ giọng đã chọn
# --------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["nam", "nu", "espeak", "NAM", " nu ", "giongnam"])
def test_normalise_voice_accepts_valid(value):
    assert vl.normalise_voice(value) in vl.VOICES


@pytest.mark.parametrize("value", [None, "", "ten-la", 42, object()])
def test_normalise_voice_falls_back_on_garbage(value):
    assert vl.normalise_voice(value) == vl.DEFAULT_VOICE


def test_save_and_load_voice_roundtrip(tmp_path):
    vl.save_voice(tmp_path, "nu")
    assert vl.load_voice(tmp_path) == "nu"
    payload = json.loads((tmp_path / vl.SETTINGS_FILENAME).read_text("utf-8"))
    assert payload["voice"] == "nu"


def test_load_voice_without_file_uses_default(tmp_path):
    assert vl.load_voice(tmp_path, "espeak") == "espeak"


def test_load_voice_with_corrupt_file_uses_default(tmp_path):
    (tmp_path / vl.SETTINGS_FILENAME).write_text("{khong phai json", "utf-8")
    assert vl.load_voice(tmp_path, "nam") == "nam"


# --------------------------------------------------------------------------
# Alerter: bản thu thắng espeak; thiếu bản thu thì rơi xuống espeak
# --------------------------------------------------------------------------
class _RecordingController:
    """Ghi lại lời gọi phát, không chạm camera."""

    busy = False

    def __init__(self) -> None:
        self.files: list[str] = []
        self.tones: list[tuple[float, float]] = []

    def speak_file(self, path: str, volume: float = 1.0) -> object:
        self.files.append(path)
        return object()

    def speak_tone(self, frequency: float, duration: float) -> object:
        self.tones.append((frequency, duration))
        return object()


def _alerter(tmp_path, controller, **kwargs):
    return SpeakerAlerter(
        controller,
        audio_dir=tmp_path,
        espeak_runner=kwargs.pop(
            "espeak_runner", lambda text, out: _fake_wav(Path(out))
        ),
        **kwargs,
    )


def test_voice_clip_is_used_when_present(tmp_path, monkeypatch):
    """Có bản thu thì phát bản thu, **không** gọi espeak."""
    voice = tmp_path / "giongnam"
    for kind in KINDS:
        _fake_wav(voice / f"{kind}.mp3")
    called: list[str] = []
    monkeypatch.setattr(vl, "prepare_clip", lambda src, dst: _fake_wav(Path(dst)))
    controller = _RecordingController()
    alerter = _alerter(
        tmp_path,
        controller,
        voice="nam",
        espeak_runner=lambda text, out: called.append(out),
    )
    alerter.prepare()
    assert alerter.prepare_error is None
    outcome = alerter.alert("phone")
    assert outcome.mode == MODE_SPEECH
    assert controller.files, "phải phát file ra loa"
    assert controller.files[0].endswith("phone.nam.s90.wav")
    assert called == [], "có bản thu thì không được sinh espeak"


def test_partial_clips_use_espeak_only_for_missing_kinds(tmp_path, monkeypatch):
    """Chỉ có bản thu cho một câu: câu đó dùng bản thu, hai câu kia dùng espeak."""
    monkeypatch.setattr(vl, "prepare_clip", lambda src, dst: _fake_wav(Path(dst)))
    voice = tmp_path / "giongnam"
    _fake_wav(voice / "phone.mp3")
    generated: list[str] = []

    def runner(text: str, out: str) -> None:
        generated.append(Path(out).name)
        _fake_wav(Path(out))

    alerter = _alerter(
        tmp_path, _RecordingController(), voice="nam", espeak_runner=runner
    )
    alerter.prepare()
    assert alerter.prepare_error is None
    assert "phone.nam.s90.wav" in {path.name for path in alerter._wav_paths.values()}
    assert set(generated) == {"leave_frame.wav", "stranger.wav"}


def test_missing_clip_falls_back_to_espeak_not_silence(tmp_path):
    """Chọn giọng nam mà thư mục trống: vẫn phải có tiếng nói, không chỉ bíp."""
    generated: list[str] = []

    def runner(text: str, out: str) -> None:
        generated.append(out)
        _fake_wav(Path(out))

    controller = _RecordingController()
    alerter = _alerter(tmp_path, controller, voice="nam", espeak_runner=runner)
    alerter.prepare()
    outcome = alerter.alert("phone")
    assert outcome.mode == MODE_SPEECH
    assert generated, "phải sinh giọng máy thay cho bản thu thiếu"
    assert controller.tones == [], "không được rơi xuống bíp khi espeak còn dùng được"


def test_fallback_note_explains_why_voice_differs(tmp_path):
    """Thiếu bản thu thì dashboard phải nói rõ, không im lặng đổi giọng."""
    alerter = _alerter(
        tmp_path,
        _RecordingController(),
        voice="nu",
        espeak_runner=lambda text, out: _fake_wav(Path(out)),
    )
    alerter.prepare()
    report = alerter.voice_report()
    assert report["fallbacks"], "phải có ghi chú giải thích"
    assert any("giọng máy" in note for note in report["fallbacks"].values())


def test_set_voice_rebuilds_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "prepare_clip", lambda src, dst: _fake_wav(Path(dst)))
    for voice in ("giongnam", "giongnu"):
        for kind in KINDS:
            _fake_wav(tmp_path / voice / f"{kind}.mp3")

    alerter = _alerter(tmp_path, _RecordingController(), voice="nam")
    alerter.prepare()
    first = {kind: path.name for kind, path in alerter._wav_paths.items()}
    assert set(first.values()) == {f"{k}.nam.s90.wav" for k in KINDS}

    report = alerter.set_voice("nu")
    assert report["voice"] == "nu"
    second = {kind: path.name for kind, path in alerter._wav_paths.items()}
    assert set(second.values()) == {f"{k}.nu.s90.wav" for k in KINDS}
    # Đã ghi xuống đĩa để lần chạy sau nhớ.
    assert vl.load_voice(tmp_path) == "nu"


def test_set_voice_rejects_unknown_by_normalising(tmp_path):
    """Giá trị lạ không ném lỗi: về mặc định, dashboard vẫn dùng được."""
    alerter = _alerter(tmp_path, _RecordingController(), voice="nam")
    report = alerter.set_voice("khong-ton-tai")
    assert report["voice"] == vl.DEFAULT_VOICE


def test_from_config_prefers_saved_voice_over_config():
    """Lựa chọn đã lưu (bấm trên web) thắng ``config.yaml``."""
    import tempfile

    from posture_monitor.config import Config, SpeakerAlertConfig

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vl.save_voice(root, "nu")
        cfg = Config()
        cfg.speaker_alert = SpeakerAlertConfig(audio_dir=str(root), voice="nam")
        alerter = SpeakerAlerter.from_config(cfg, controller=_RecordingController())
        assert alerter.voice == "nu"


def test_from_config_uses_config_voice_when_nothing_saved():
    import tempfile

    from posture_monitor.config import Config, SpeakerAlertConfig

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config()
        cfg.speaker_alert = SpeakerAlertConfig(audio_dir=tmp, voice="espeak")
        alerter = SpeakerAlerter.from_config(cfg, controller=_RecordingController())
        assert alerter.voice == "espeak"


# --------------------------------------------------------------------------
# Cấu hình
# --------------------------------------------------------------------------
def test_config_rejects_unknown_voice():
    from posture_monitor.config import ConfigError, _parse_speaker_alert

    with pytest.raises(ConfigError) as info:
        _parse_speaker_alert({"voice": "gio-nguoi"})
    assert "speaker_alert.voice" in str(info.value)


def test_config_accepts_valid_voice_and_defaults():
    from posture_monitor.config import SpeakerAlertConfig, _parse_speaker_alert

    cfg = _parse_speaker_alert({"voice": "nu"})
    assert cfg.voice == "nu"
    assert cfg.say is True
    assert cfg.tone_fallback is True
    empty = _parse_speaker_alert(None)
    assert empty.voice == SpeakerAlertConfig.voice


def test_config_rejects_empty_audio_dir():
    from posture_monitor.config import ConfigError, _parse_speaker_alert

    with pytest.raises(ConfigError):
        _parse_speaker_alert({"audio_dir": "   "})


# --------------------------------------------------------------------------
# Tìm espeak-ng khi nó không có trên PATH
# --------------------------------------------------------------------------
def test_find_espeak_binary_prefers_path(monkeypatch):
    """Trên Pi, gói apt đưa ``espeak-ng`` vào PATH — phải dùng bản đó."""
    from posture_monitor import speaker_alert as sa

    monkeypatch.setattr(sa.shutil, "which", lambda name: "/usr/bin/espeak-ng")
    assert sa.find_espeak_binary() == "/usr/bin/espeak-ng"


def test_find_espeak_binary_uses_windows_fallback(monkeypatch, tmp_path):
    """Trình cài Windows không thêm PATH: phải tìm ở vị trí cài mặc định."""
    from posture_monitor import speaker_alert as sa

    fake = tmp_path / "espeak-ng.exe"
    fake.write_bytes(b"x")
    monkeypatch.setattr(sa.shutil, "which", lambda name: None)
    monkeypatch.setattr(sa, "ESPEAK_FALLBACK_PATHS", (str(fake),))
    assert sa.find_espeak_binary() == str(fake)


def test_find_espeak_binary_returns_none_when_absent(monkeypatch, tmp_path):
    from posture_monitor import speaker_alert as sa

    monkeypatch.setattr(sa.shutil, "which", lambda name: None)
    monkeypatch.setattr(sa, "ESPEAK_FALLBACK_PATHS", (str(tmp_path / "khong-co.exe"),))
    assert sa.find_espeak_binary() is None
