"""Quyết định **phát gì, khi nào** ra loa của camera IP (spec v3 §5.15).

Module này **không** mở socket và **không** tự giữ một kết nối RTSP nào: mọi
việc đẩy tiếng ra loa đã nằm trong :class:`posture_monitor.camera.audio.SpeakController`.
Ở đây chỉ còn ba câu hỏi:

- **Phát gì**: một trong ba câu tiếng Việt ở :data:`ALERT_TEXT`, hoặc tiếng bíp
  khi không phát được câu.
- **Khi nào**: khi tầng gọi đã quyết định xong (cổng giờ học, ``hold_s`` và
  ``cooldown_s`` thuộc :func:`posture_monitor.domain.schedule.should_alert`).
- **Khi hai sự kiện cùng lúc**: chỉ phát loại **nghiêm trọng nhất** theo
  :data:`PRIORITY` (người lạ > vắng mặt > dùng điện thoại).
"""

from __future__ import annotations

import inspect
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..camera.audio import (
    CameraAudioError,
    CameraAudioUnavailable,
    SpeakController,
    section_value,
)
from ..core.labels import (
    DEFAULT_SPEECH_SPEED,
    DEFAULT_VOICE,
    DEFAULT_VOLUME,
    MAX_SPEECH_SPEED,
    MAX_VOLUME,
    MIN_SPEECH_SPEED,
    MIN_VOLUME,
    VOICE_DIRS,
    VOICE_LABELS,
    VOICE_SYNTH,
    VOICES,
    normalise_speed,
    normalise_voice,
    normalise_volume,
)
from ..core.logging_setup import get_logger
from ..domain.schedule import (
    KIND_LABELS,
    KIND_LEAVE_FRAME,
    KIND_PHONE,
    KIND_STRANGER,
)
from . import espeak_synth, voice_library
from .espeak_synth import (
    DEFAULT_LANGUAGE,
    ESPEAK_BINARY,
    ESPEAK_FALLBACK_PATHS,
    ESPEAK_TIMEOUT_S,
    wav_is_current as _wav_is_current,
    wav_is_usable as _wav_is_usable,
)
from .voice_library import VoiceClipError

logger = get_logger(__name__)

#: Bí danh dùng chung helper đọc thuộc tính/dict với ``camera.audio``.
_section_value = section_value

# --------------------------------------------------------------------------
# Loại cảnh báo — dùng lại đúng tên của schedule, không đặt tên thứ hai
# --------------------------------------------------------------------------
ALERT_ABSENT = KIND_LEAVE_FRAME
ALERT_PHONE_USE = KIND_PHONE
ALERT_IMPOSTOR = KIND_STRANGER

ALERT_KINDS = (ALERT_ABSENT, ALERT_PHONE_USE, ALERT_IMPOSTOR)
PRIORITY = (ALERT_IMPOSTOR, ALERT_ABSENT, ALERT_PHONE_USE)

ALERT_TEXT = {
    ALERT_ABSENT: "Bạn ơi, quay lại bàn học nhé",
    ALERT_PHONE_USE: "Cất điện thoại và tập trung học nhé",
    ALERT_IMPOSTOR: "Người đang ngồi không phải người đã đăng ký học",
}

# --------------------------------------------------------------------------
# Kết quả phát
# --------------------------------------------------------------------------
MODE_SPEECH = "speech"
MODE_TONE = "tone"
MODE_SKIPPED = "skipped"

ALERT_TONE_HZ = 880.0
ALERT_TONE_DURATION_S = 0.6

ALERT_VOLUME = DEFAULT_VOLUME
MIN_ALERT_VOLUME = MIN_VOLUME
MAX_ALERT_VOLUME = MAX_VOLUME


def find_espeak_binary() -> str | None:
    """Đường dẫn tới ``espeak-ng`` dùng được, hoặc ``None``.

    Uỷ quyền xuống :mod:`espeak_synth` nhưng truyền ``ESPEAK_FALLBACK_PATHS`` và
    ``shutil.which`` của chính module này để mọi monkeypatch trong test tiếp tục
    có hiệu lực.
    """
    return espeak_synth.find_espeak_binary(
        fallback_paths=ESPEAK_FALLBACK_PATHS,
        which_fn=shutil.which,
    )


def run_espeak(
    text: str, out_path: str, *, language: str = DEFAULT_LANGUAGE
) -> None:
    """Sinh một file WAV từ ``text`` bằng ``espeak-ng`` (đường mặc định)."""
    espeak_synth.run_espeak(
        text,
        out_path,
        language=language,
        find_binary_fn=find_espeak_binary,
    )


def _call_prepare_clip(source: Path, target: Path, speed: float) -> None:
    """Gọi ``voice_library.prepare_clip`` qua tham chiếu module.

    Tương thích cả hàm thật ``prepare_clip(source, target, *, speed=...)`` lẫn
    hàm giả hai tham số ``lambda src, dst: ...`` trong unit test.
    """
    fn = voice_library.prepare_clip
    try:
        params = inspect.signature(fn).parameters.values()
        accepts_speed = any(
            param.name == "speed"
            or param.kind is inspect.Parameter.VAR_KEYWORD
            for param in params
        )
    except (TypeError, ValueError):
        accepts_speed = True
    if accepts_speed:
        fn(source, target, speed=speed)
    else:
        fn(source, target)


@dataclass(frozen=True)
class AlertOutcome:
    """Kết quả một lần quyết định phát cảnh báo."""

    kind: str | None
    text: str | None
    spoken: bool
    mode: str
    reason: str
    error: str | None = None
    at: float = 0.0
    retryable: bool = False

    @property
    def speech_expected(self) -> bool:
        """``True`` khi câu cần nói nhưng lần này chỉ có tiếng bíp."""
        return self.mode == MODE_TONE


class SpeakerAlerter:
    """Quyết định phát câu cảnh báo nào ra loa camera, và phát nó."""

    def __init__(
        self,
        controller: Any,
        *,
        audio_dir: str | Path = "data/audio",
        say: bool = True,
        tone_fallback: bool = True,
        language: str = DEFAULT_LANGUAGE,
        voice: str = DEFAULT_VOICE,
        volume: float = ALERT_VOLUME,
        speed: float = DEFAULT_SPEECH_SPEED,
        espeak_runner: Callable[[str, str], None] | None = None,
        clock: Callable[[], float] | None = None,
        logger: Any = None,
    ) -> None:
        self._controller = controller
        self._audio_dir = Path(audio_dir)
        self._say = bool(say)
        self._tone_fallback = bool(tone_fallback)
        self._language = str(language or DEFAULT_LANGUAGE)
        self._espeak_runner = espeak_runner
        self._clock = clock if clock is not None else time.monotonic
        self._logger = logger if logger is not None else get_logger(__name__)
        self._volume = normalise_volume(volume, ALERT_VOLUME)
        self._speed = normalise_speed(speed)
        self._voice = normalise_voice(voice)
        self._wav_paths: dict[str, Path] = {}
        self._wav_sources: dict[str, Path] = {}
        self._prepared = False
        self._prepare_error: str | None = None
        self._fallback_notes: dict[str, str] = {}

    # -- thuộc tính -----------------------------------------------------
    @property
    def available(self) -> bool:
        """``True`` khi có controller loa, tức tính năng dùng được."""
        return self._controller is not None

    @property
    def audio_dir(self) -> Path:
        return self._audio_dir

    @property
    def say(self) -> bool:
        return self._say

    @property
    def tone_fallback(self) -> bool:
        return self._tone_fallback

    @property
    def voice(self) -> str:
        """Mã giọng đang chọn (``nam``/``nu``/``espeak``)."""
        return self._voice

    @property
    def volume(self) -> float:
        """Âm lượng gửi đi khi phát câu nói (0..1)."""
        return self._volume

    @property
    def speed(self) -> float:
        """Tốc độ đọc so với bản thu gốc (0,5..1,0)."""
        return self._speed

    @property
    def prepare_error(self) -> str | None:
        """Lý do gần nhất ``prepare`` không dùng được giọng nói; ``None`` = ổn."""
        return self._prepare_error

    def wav_path(self, kind: str) -> Path | None:
        """File WAV sẽ phát cho câu ``kind``; ``None`` nếu chưa có."""
        return self._wav_paths.get(kind)

    def speak_tone_now(self, kind: str | None = None) -> AlertOutcome:
        """Phát **tiếng bíp** ngay, bỏ qua mọi bước chuẩn bị giọng đọc."""
        moment = float(self._clock())
        if self._controller is None:
            return self._skipped(
                kind,
                None,
                "Chưa cấu hình loa camera (camera.speaker) nên không phát "
                "được tiếng bíp.",
                moment,
            )
        try:
            busy = bool(getattr(self._controller, "busy", False))
        except Exception:  # noqa: BLE001
            busy = False
        if busy:
            return self._skipped(
                kind,
                None,
                "Loa camera đang phát tiếng khác nên bỏ lần thử này.",
                moment,
            )
        try:
            self._controller.speak_tone(ALERT_TONE_HZ, ALERT_TONE_DURATION_S)
        except Exception as exc:  # noqa: BLE001
            return self._failure(kind or "", None, moment, exc)
        return AlertOutcome(
            kind=kind,
            text=None,
            spoken=True,
            mode=MODE_TONE,
            reason="Đã phát tiếng bíp thử ra loa camera.",
            error=None,
            at=moment,
        )

    def voice_report(self) -> dict[str, Any]:
        """Tình trạng giọng đang dùng + mọi giọng có sẵn, cho dashboard."""
        return {
            "voice": self._voice,
            "volume": self._volume,
            "speed": self._speed,
            "voices": voice_library.available_voices(
                self._audio_dir, ALERT_KINDS
            ),
            "fallbacks": dict(self._fallback_notes),
            "error": self._prepare_error,
        }

    def _reset_prepared_cache(self) -> None:
        self._wav_paths.clear()
        self._wav_sources.clear()
        self._fallback_notes.clear()
        self._prepared = False
        self._prepare_error = None

    def set_voice(self, voice: str) -> dict[str, Any]:
        """Đổi giọng đang dùng và dựng lại file phát; trả :meth:`voice_report`."""
        new_voice = normalise_voice(voice)
        if new_voice == self._voice and self._prepared:
            return self.voice_report()
        self._voice = new_voice
        try:
            voice_library.save_voice(self._audio_dir, new_voice)
        except VoiceClipError as exc:
            self._logger.warning(
                "Đã đổi sang %s nhưng chưa lưu được lựa chọn: %s",
                new_voice,
                exc,
            )
        self._reset_prepared_cache()
        self.prepare()
        return self.voice_report()

    def set_speed(self, speed: float) -> dict[str, Any]:
        """Đổi tốc độ đọc và dựng lại WAV; trả :meth:`voice_report`."""
        new_speed = normalise_speed(speed, self._speed)
        if new_speed == self._speed and self._prepared:
            return self.voice_report()
        self._speed = new_speed
        self._reset_prepared_cache()
        self.prepare()
        return self.voice_report()

    def set_volume(self, volume: float) -> dict[str, Any]:
        """Đổi âm lượng phát; trả :meth:`voice_report`."""
        self._volume = normalise_volume(volume, self._volume)
        return self.voice_report()

    def audio_path(self, kind: str) -> Path:
        """Đường dẫn file WAV của loại cảnh báo ``kind`` (chưa chắc đã tồn tại)."""
        return self._audio_dir / f"{kind}.wav"

    # -- sinh giọng đọc một lần -----------------------------------------
    def prepare(self) -> None:
        """Sinh file WAV cho cả ba câu vào ``audio_dir`` — **một lần**."""
        if self._prepared:
            return
        if not self._say:
            self._prepared = True
            self._logger.info(
                "Đã tắt giọng đọc (say=False): cảnh báo sẽ phát tiếng bíp."
            )
            return

        try:
            self._audio_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._prepare_error = (
                f"không tạo được thư mục âm thanh '{self._audio_dir}': {exc}"
            )
            self._log_prepare_failure()
            return

        missing: list[str] = []
        for kind in ALERT_KINDS:
            if kind in self._wav_paths:
                continue
            if self._prepare_voice_clip(kind):
                continue
            if self._prepare_espeak_clip(kind):
                continue
            missing.append(kind)

        if missing:
            self._prepare_error = "chưa có giọng đọc cho " + ", ".join(
                KIND_LABELS[kind] for kind in missing
            )
            self._log_prepare_failure()
            return

        self._prepare_error = None
        self._prepared = True

    def _prepare_voice_clip(self, kind: str) -> bool:
        """Dùng bản thu của giọng đang chọn cho câu ``kind``; ``True`` nếu xong."""
        if self._voice not in VOICE_DIRS:
            return False
        source = voice_library.find_clip(self._audio_dir, self._voice, kind)
        if source is None:
            return False
        target = self._voice_wav_path(kind, self._voice)
        if self._wav_is_current(target, source):
            self._wav_paths[kind] = target
            self._wav_sources[kind] = source
            self._logger.info(
                "Dùng lại bản thu %s cho cảnh báo '%s' tại '%s'.",
                voice_library.describe_clip(source),
                KIND_LABELS[kind],
                target,
            )
            return True
        try:
            _call_prepare_clip(source, target, self._speed)
        except VoiceClipError as exc:
            self._logger.warning(
                "Không dùng được bản thu '%s' cho cảnh báo '%s': %s",
                voice_library.describe_clip(source),
                KIND_LABELS[kind],
                exc,
            )
            return False
        self._wav_paths[kind] = target
        self._wav_sources[kind] = source
        self._logger.info(
            "Đã đổi bản thu %s sang WAV cho cảnh báo '%s' tại '%s'.",
            voice_library.describe_clip(source),
            KIND_LABELS[kind],
            target,
        )
        return True

    def _prepare_espeak_clip(self, kind: str) -> bool:
        """Sinh câu ``kind`` bằng ``espeak-ng`` (đường dự phòng); ``True`` nếu xong."""
        target = self.audio_path(kind)
        if _wav_is_usable(target):
            self._wav_paths[kind] = target
            self._wav_sources.pop(kind, None)
            self._logger.info(
                "Dùng lại giọng máy có sẵn cho cảnh báo '%s' tại '%s'.",
                KIND_LABELS[kind],
                target,
            )
            if self._voice in VOICE_DIRS:
                self._fallback_notes[kind] = (
                    f"Chưa có bản thu {VOICE_LABELS[self._voice].lower()} cho "
                    f"câu này nên tạm dùng giọng máy."
                )
            return True
        try:
            self._run_espeak(ALERT_TEXT[kind], str(target))
        except Exception as exc:  # noqa: BLE001 - thiếu TTS không được crash
            self._logger.warning(
                "Không sinh được giọng đọc cho cảnh báo '%s': %s: %s",
                KIND_LABELS[kind],
                type(exc).__name__,
                exc,
            )
            return False
        self._wav_paths[kind] = target
        self._wav_sources.pop(kind, None)
        if self._voice in VOICE_DIRS:
            self._fallback_notes[kind] = (
                f"Chưa có bản thu {VOICE_LABELS[self._voice].lower()} cho câu "
                f"này nên tạm dùng giọng máy."
            )
        self._logger.info(
            "Đã sinh giọng máy cho cảnh báo '%s' tại '%s'.",
            KIND_LABELS[kind],
            target,
        )
        return True

    def _voice_wav_path(self, kind: str, voice: str) -> Path:
        """File WAV phát được của bản thu ``voice`` cho câu ``kind``."""
        tag = f"{round(self._speed * 100):02d}"
        return self._audio_dir / f"{kind}.{voice}.s{tag}.wav"

    def _wav_is_current(self, target: Path, source: Path) -> bool:
        """Bản WAV ``target`` đã đổi từ ``source`` và còn mới hơn nó chưa."""
        return _wav_is_current(target, source, usable_fn=_wav_is_usable)

    def _run_espeak(self, text: str, out_path: str) -> None:
        if self._espeak_runner is not None:
            self._espeak_runner(text, out_path)
            return
        run_espeak(text, out_path, language=self._language)

    def _log_prepare_failure(self) -> None:
        if self._tone_fallback:
            self._logger.warning(
                "Giọng đọc tiếng Việt chưa dùng được (%s). Cảnh báo sẽ phát "
                "tiếng bíp thay vì im lặng.",
                self._prepare_error,
            )
        else:
            self._logger.warning(
                "Giọng đọc tiếng Việt chưa dùng được (%s). tone_fallback đang "
                "tắt nên cảnh báo sẽ KHÔNG phát ra loa.",
                self._prepare_error,
            )

    # -- phát ------------------------------------------------------------
    def alert(
        self,
        kind: str,
        *,
        now: float | None = None,
        muted: bool = False,
    ) -> AlertOutcome:
        """Phát cảnh báo một loại. Tương đương ``alert_many([kind])``."""
        return self.alert_many((kind,), now=now, muted=muted)

    def alert_many(
        self,
        kinds: Iterable[str],
        *,
        now: float | None = None,
        muted: bool = False,
    ) -> AlertOutcome:
        """Chọn **một** loại theo :data:`PRIORITY` rồi phát nó."""
        moment = float(self._clock() if now is None else now)
        chosen = self._choose(kinds)
        if chosen is None:
            return self._skipped(
                None,
                None,
                "Không có loại cảnh báo nào hợp lệ trong lời gọi nên không "
                "phát gì ra loa.",
                moment,
            )

        text = ALERT_TEXT[chosen]
        if muted:
            return self._skipped(
                chosen,
                text,
                "Dashboard đang tắt tiếng nên không phát cảnh báo ra loa.",
                moment,
            )
        if self._controller is None:
            return self._skipped(
                chosen,
                text,
                "Chưa cấu hình loa camera (camera.speaker) nên không phát "
                "được cảnh báo ra loa.",
                moment,
            )

        try:
            busy = bool(getattr(self._controller, "busy", False))
        except Exception:  # noqa: BLE001
            busy = False
        if busy:
            return self._skipped(
                chosen,
                text,
                "Loa camera đang phát tiếng khác nên bỏ lần cảnh báo này "
                "(không xếp hàng, không chờ).",
                moment,
                retryable=True,
            )

        wav = self._wav_paths.get(chosen)
        if self._say and wav is not None and wav.is_file():
            return self._emit_speech(chosen, text, wav, moment)
        if not self._say:
            why = "Đã tắt giọng đọc (say=False)."
        else:
            why = "Chưa có file giọng đọc cho câu này."
        return self._emit_tone(chosen, text, moment, why=why)

    def _emit_speech(
        self, kind: str, text: str, wav: Path, moment: float
    ) -> AlertOutcome:
        try:
            self._controller.speak_file(str(wav), self._volume)
        except CameraAudioUnavailable as exc:
            return self._emit_tone(
                kind,
                text,
                moment,
                why=f"Không phát được file giọng đọc ({exc}).",
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return self._failure(kind, text, moment, exc)
        self._logger.info(
            "Đã phát cảnh báo '%s' ra loa camera bằng giọng đọc.",
            KIND_LABELS[kind],
        )
        return AlertOutcome(
            kind=kind,
            text=text,
            spoken=True,
            mode=MODE_SPEECH,
            reason="Đã phát câu nhắc bằng giọng đọc ra loa camera.",
            error=None,
            at=moment,
        )

    def _emit_tone(
        self,
        kind: str,
        text: str,
        moment: float,
        *,
        why: str,
        error: str | None = None,
    ) -> AlertOutcome:
        if not self._tone_fallback:
            return self._skipped(
                kind,
                text,
                f"{why} tone_fallback đang tắt nên bỏ lần cảnh báo này, "
                "không phát gì ra loa.",
                moment,
                error=error,
            )
        try:
            self._controller.speak_tone(ALERT_TONE_HZ, ALERT_TONE_DURATION_S)
        except Exception as exc:  # noqa: BLE001
            return self._failure(kind, text, moment, exc)
        self._logger.info(
            "Đã phát cảnh báo '%s' ra loa camera bằng tiếng bíp (chưa nói "
            "được câu tiếng Việt: %s).",
            KIND_LABELS[kind],
            why,
        )
        return AlertOutcome(
            kind=kind,
            text=text,
            spoken=True,
            mode=MODE_TONE,
            reason=f"{why} Đã phát tiếng bíp thay cho câu nhắc.",
            error=error,
            at=moment,
        )

    # -- nội bộ ----------------------------------------------------------
    @staticmethod
    def _choose(kinds: Iterable[str]) -> str | None:
        """Loại ưu tiên cao nhất trong ``kinds``; ``None`` nếu không có loại hợp lệ."""
        if isinstance(kinds, str):
            kinds = (kinds,)
        requested = {kind for kind in kinds if kind in ALERT_TEXT}
        for kind in PRIORITY:
            if kind in requested:
                return kind
        return None

    def _skipped(
        self,
        kind: str | None,
        text: str | None,
        reason: str,
        moment: float,
        *,
        error: str | None = None,
        retryable: bool = False,
    ) -> AlertOutcome:
        if kind is not None:
            self._logger.info("Bỏ cảnh báo '%s': %s", KIND_LABELS[kind], reason)
        else:
            self._logger.info("Bỏ cảnh báo: %s", reason)
        return AlertOutcome(
            kind=kind,
            text=text,
            spoken=False,
            mode=MODE_SKIPPED,
            reason=reason,
            error=error,
            at=moment,
            retryable=retryable,
        )

    def _failure(
        self, kind: str | None, text: str | None, moment: float, exc: BaseException
    ) -> AlertOutcome:
        """Lỗi loa: ghi log, trả ``error`` để tầng gọi ghi ``SPEAK_FAILED``."""
        error = f"{type(exc).__name__}: {exc}"
        self._logger.warning(
            "Phát cảnh báo '%s' ra loa camera thất bại (%s); ghi SPEAK_FAILED "
            "và tiếp tục chạy.",
            KIND_LABELS.get(kind, kind or "(thử loa)"),
            error,
        )
        return AlertOutcome(
            kind=kind,
            text=text,
            spoken=False,
            mode=MODE_SKIPPED,
            reason=(
                "Phát cảnh báo ra loa camera thất bại; tầng gọi ghi sự kiện "
                "SPEAK_FAILED và vòng lặp camera tiếp tục chạy."
            ),
            error=error,
            at=moment,
        )

    # -- dựng từ Config --------------------------------------------------
    @classmethod
    def from_config(cls, config: Any, **kwargs: Any) -> "SpeakerAlerter":
        """Dựng alerter từ :class:`posture_monitor.core.config.Config`."""
        explicit_voice = "voice" in kwargs and kwargs["voice"] is not None

        section = getattr(config, "speaker_alert", None)
        for key, default in (
            ("say", True),
            ("tone_fallback", True),
            ("audio_dir", "data/audio"),
            ("language", DEFAULT_LANGUAGE),
            ("voice", DEFAULT_VOICE),
            ("volume", ALERT_VOLUME),
            ("speed", DEFAULT_SPEECH_SPEED),
        ):
            if key in kwargs and kwargs[key] is not None:
                continue
            value = _section_value(section, key, default)
            kwargs[key] = default if value is None else value

        audio_dir = Path(kwargs.get("audio_dir") or "data/audio")
        if explicit_voice:
            kwargs["voice"] = normalise_voice(kwargs["voice"])
        else:
            kwargs["voice"] = voice_library.load_voice(
                audio_dir, normalise_voice(kwargs["voice"])
            )

        controller: Any = None
        if "controller" not in kwargs:
            try:
                controller = SpeakController.from_config(config)
            except CameraAudioError as exc:
                logger.info(
                    "Chưa bật loa camera nên cảnh báo chỉ ghi sự kiện: %s", exc
                )
        return cls(kwargs.pop("controller", controller), **kwargs)


__all__ = [
    "ALERT_ABSENT",
    "ALERT_IMPOSTOR",
    "ALERT_KINDS",
    "ALERT_PHONE_USE",
    "ALERT_TEXT",
    "ALERT_TONE_DURATION_S",
    "ALERT_TONE_HZ",
    "ALERT_VOLUME",
    "AlertOutcome",
    "DEFAULT_LANGUAGE",
    "ESPEAK_BINARY",
    "ESPEAK_FALLBACK_PATHS",
    "ESPEAK_TIMEOUT_S",
    "MAX_ALERT_VOLUME",
    "MIN_ALERT_VOLUME",
    "MODE_SKIPPED",
    "MODE_SPEECH",
    "MODE_TONE",
    "PRIORITY",
    "SpeakerAlerter",
    "VOICE_SYNTH",
    "find_espeak_binary",
    "run_espeak",
]
