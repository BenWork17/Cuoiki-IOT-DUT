"""Phát âm thanh ra **loa của camera IP** qua RTSP backchannel (ONVIF).

Thư viện ``rtsp-backchannel`` lo phần ONVIF và handshake RTSP. Module này bọc nó
cho đúng nhu cầu của dashboard và tầng cảnh báo:

- :meth:`SpeakController.speak_tone` — **đường chính**: tự sinh PCM G.711 bằng
  ``tone_audio`` rồi đóng gói RTP, **không cần ffmpeg**.
- :meth:`SpeakController.speak_file` — phát file có sẵn; đường này **cần**
  ffmpeg nên kiểm tra trước và báo lỗi tiếng Việt rõ ràng.
- Một khóa :class:`threading.Lock` cho mỗi controller: lời gọi thứ hai nhận
  :class:`CameraAudioBusy` ngay thay vì treo worker.
- Mọi thông điệp lỗi/log đi qua :func:`posture_monitor.core.config.redact_camera_source`
  và thay cả mật khẩu literal.
"""

from __future__ import annotations

import math
import os
import shutil
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ..core.config import (
    ONVIF_PASSWORD_ENV,
    REDACTED,
    camera_credentials,
    camera_source_host,
    redact_camera_source,
)
from ..core.logging_setup import get_logger

logger = get_logger(__name__)

#: Thư viện cung cấp handshake ONVIF + RTSP backchannel và bộ đóng gói RTP.
LIBRARY_NAME = "rtsp-backchannel"

#: Phiên bản đã đọc mã nguồn và đối chiếu API (xem docs/SPEC_V2.md §11.3).
LIBRARY_PIN = "0.5.2"

#: Đường dẫn luồng PHỤ của camera IP của dự án.
DEFAULT_STREAM_PATH = "/1/2"

#: Thời lượng tối đa của một lần phát, tính bằng giây.
MAX_SPEAK_DURATION_S = 10.0

#: Thời lượng tối thiểu — dưới mức này chưa đủ một gói RTP nghe ra gì.
MIN_SPEAK_DURATION_S = 0.1

#: Tần số tối thiểu/tối đa của tiếng bíp. Trần là Nyquist của G.711 8 kHz.
MIN_TONE_HZ = 100.0
MAX_TONE_HZ = 4000.0

#: Tiếng bíp mặc định của dashboard.
DEFAULT_TONE_HZ = 440.0
DEFAULT_TONE_DURATION_S = 0.5

#: Biên độ tương đối của tiếng bíp.
TONE_AMPLITUDE = 0.25

#: G.711 luôn 8 kHz một kênh; 320 mẫu/gói = 40 ms, đúng nhịp ptime phổ biến.
SAMPLE_RATE = 8000
SAMPLES_PER_PACKET = 320

#: Mã hóa mà module này tự sinh được (``tone_audio`` chỉ hỗ trợ G.711).
_TONE_CODECS = ("pcma", "pcmu")


# --------------------------------------------------------------------------
# Lỗi — tất cả thông điệp bằng tiếng Việt, đã che mật khẩu
# --------------------------------------------------------------------------
class CameraAudioError(Exception):
    """Lỗi gốc khi phát âm thanh ra loa camera."""


class CameraAudioInputError(CameraAudioError):
    """Tham số do người dùng gửi lên không hợp lệ (tần số, thời lượng, file)."""


class CameraAudioConfigError(CameraAudioError):
    """Chưa cấu hình đủ để mở backchannel (thiếu mục ``camera.speaker``...)."""


class CameraAudioUnavailable(CameraAudioError):
    """Thiếu thư viện hoặc thiếu ffmpeg — tính năng chưa dùng được ở máy này."""


class CameraAudioBusy(CameraAudioError):
    """Loa camera đang phát một lời gọi khác."""


# --------------------------------------------------------------------------
# Cấu hình
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SpeakerConfig:
    """Đích phát âm thanh: một phiên RTSP backchannel tới camera."""

    host: str
    port: int = 554
    stream_path: str = DEFAULT_STREAM_PATH
    user: str = ""
    password: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        host = str(self.host or "").strip()
        if not host:
            raise CameraAudioConfigError(
                "Thiếu địa chỉ camera cho loa (camera.speaker.host)."
            )
        if "://" in host:
            raise CameraAudioConfigError(
                "camera.speaker.host phải là tên máy hoặc IP, không kèm "
                "'rtsp://'. Dùng camera.speaker.stream_uri nếu cần URL đầy đủ."
            )
        if not 1 <= int(self.port) <= 65535:
            raise CameraAudioConfigError(
                f"camera.speaker.port = {self.port!r} không hợp lệ "
                "(phải trong khoảng 1..65535)."
            )
        path = str(self.stream_path or "").strip() or DEFAULT_STREAM_PATH
        if not path.startswith("/"):
            path = "/" + path
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "port", int(self.port))
        object.__setattr__(self, "stream_path", path)
        object.__setattr__(self, "user", str(self.user or ""))
        object.__setattr__(self, "password", str(self.password or ""))

    @property
    def stream_uri(self) -> str:
        """URL luồng phụ — **không** chứa thông tin đăng nhập."""
        return (
            f"rtsp://{self.host}:{self.port}"
            f"{urllib.parse.quote(self.stream_path, safe='/?=&')}"
        )

    @classmethod
    def from_uri(
        cls, uri: str, *, user: str = "", password: str = ""
    ) -> "SpeakerConfig":
        """Dựng cấu hình từ một URL RTSP đầy đủ (bỏ userinfo trong URL)."""
        try:
            parts = urllib.parse.urlsplit(str(uri or "").strip())
            host = parts.hostname
            port = parts.port or 554
        except ValueError as exc:
            raise CameraAudioConfigError(
                "camera.speaker.stream_uri không phải URL RTSP hợp lệ."
            ) from exc
        if parts.scheme.lower() not in ("rtsp", "rtsps") or not host:
            raise CameraAudioConfigError(
                "camera.speaker.stream_uri phải bắt đầu bằng 'rtsp://' và có host."
            )
        return cls(
            host=host,
            port=port,
            stream_path=parts.path or DEFAULT_STREAM_PATH,
            user=user or urllib.parse.unquote(parts.username or ""),
            password=password or urllib.parse.unquote(parts.password or ""),
        )


def section_value(section: Any, name: str, default: Any = None) -> Any:
    """Đọc một khóa từ dataclass **hoặc** dict (cấu hình nạp tay trong test)."""
    if section is None:
        return default
    if isinstance(section, Mapping):
        return section.get(name, default)
    return getattr(section, name, default)


#: Bí danh nội bộ tương thích ngược.
_section_value = section_value


def speaker_config_from_config(config: Any) -> SpeakerConfig:
    """Đọc mục ``camera.speaker`` của :class:`posture_monitor.core.config.Config`."""
    speaker = section_value(getattr(config, "camera", None), "speaker", None)
    if speaker is None:
        raise CameraAudioConfigError(
            "Chưa cấu hình loa camera: thiếu mục 'camera.speaker' trong "
            "config.yaml (enabled, host, port, user, stream_path; mật khẩu "
            f"đặt ở biến môi trường {ONVIF_PASSWORD_ENV})."
        )

    if not bool(section_value(speaker, "enabled", False)):
        raise CameraAudioConfigError(
            "Loa camera đang tắt. Bật 'camera.speaker.enabled: true' trong "
            "config.yaml (kèm 'camera.speaker.host') rồi thử lại."
        )

    raw_user = str(section_value(speaker, "user", "") or "")
    camera = getattr(config, "camera", None)
    source = str(section_value(camera, "source", "") or "")

    user, password = camera_credentials(raw_user, source)
    if password and not user:
        user = "admin"

    stream_uri = section_value(speaker, "stream_uri", None)
    if not stream_uri:
        stream_uri = section_value(speaker, "url", None)
    if stream_uri:
        return SpeakerConfig.from_uri(
            str(stream_uri), user=user, password=password
        )

    host = str(section_value(speaker, "host", None) or "").strip()
    if not host:
        host = camera_source_host(source)
    if not host:
        raise CameraAudioConfigError(
            "Thiếu 'camera.speaker.host' nên chưa biết phát tiếng vào camera "
            "nào. Điền 'camera.speaker.host' trong config.yaml, hoặc đặt "
            "'camera.source' thành URL RTSP có host (ví dụ qua biến môi "
            "trường POSTURE_CAMERA_SOURCE)."
        )

    if user and not password:
        safe_host = redact_camera_source(host)
        raise CameraAudioConfigError(
            f"Đã đặt 'camera.speaker.user' nhưng chưa có mật khẩu cho camera "
            f"{safe_host!r}. Đặt biến môi trường {ONVIF_PASSWORD_ENV} rồi chạy "
            "lại (đừng ghi mật khẩu vào config.yaml vì file đó được commit)."
        )

    return SpeakerConfig(
        host=redact_camera_source(host),
        port=int(section_value(speaker, "port", 554) or 554),
        stream_path=str(
            section_value(speaker, "stream_path", DEFAULT_STREAM_PATH)
            or DEFAULT_STREAM_PATH
        ),
        user=user,
        password=password,
    )


# --------------------------------------------------------------------------
# Kết quả
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SpeakResult:
    """Tóm tắt một lần phát để route trả về JSON và để log."""

    mode: str
    codec: str
    sample_rate: int
    packets_sent: int
    duration_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "codec": self.codec,
            "sample_rate": self.sample_rate,
            "packets_sent": self.packets_sent,
            "duration_seconds": round(self.duration_seconds, 3),
        }


# --------------------------------------------------------------------------
# Nạp thư viện muộn
# --------------------------------------------------------------------------
def ffmpeg_available() -> bool:
    """``True`` nếu tìm thấy ``ffmpeg`` trong ``PATH``."""
    return shutil.which("ffmpeg") is not None


def _load_library():
    """Import các thành phần của ``rtsp-backchannel``; lỗi tiếng Việt nếu thiếu."""
    try:
        from backchannel_rtp import (  # noqa: PLC0415 - cố ý import muộn
            RtpBoundaryPlan,
            RtpPacer,
            RtpPacketizer,
        )
        from onvif_play import (  # noqa: PLC0415 - cố ý import muộn
            open_backchannel_transport,
            tone_audio,
        )
        from rtsp_backchannel import play_file  # noqa: PLC0415 - cố ý import muộn
        from rtsp_backchannel.playback import (  # noqa: PLC0415 - cố ý import muộn
            _select_codec,
        )
    except ImportError as exc:
        raise CameraAudioUnavailable(
            f"Thiếu thư viện '{LIBRARY_NAME}' nên chưa phát được tiếng ra loa "
            f"camera. Cài bằng: pip install {LIBRARY_NAME}=={LIBRARY_PIN} "
            "(gói thuần Python, không kéo thêm phụ thuộc nào)."
        ) from exc
    return {
        "RtpBoundaryPlan": RtpBoundaryPlan,
        "RtpPacer": RtpPacer,
        "RtpPacketizer": RtpPacketizer,
        "open_backchannel_transport": open_backchannel_transport,
        "tone_audio": tone_audio,
        "select_codec": _select_codec,
        "play_file": play_file,
    }


# --------------------------------------------------------------------------
# Kiểm tra tham số
# --------------------------------------------------------------------------
def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CameraAudioInputError(
            f"'{label}' phải là số, nhận được {value!r}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise CameraAudioInputError(f"'{label}' phải là số hữu hạn.")
    return number


def _check_tone(frequency_hz: Any, duration_s: Any, max_duration_s: float):
    frequency = _number(frequency_hz, "tone_hz")
    if not MIN_TONE_HZ <= frequency <= MAX_TONE_HZ:
        raise CameraAudioInputError(
            f"'tone_hz' phải trong khoảng {MIN_TONE_HZ:.0f}..{MAX_TONE_HZ:.0f} "
            f"Hz (G.711 lấy mẫu 8 kHz), nhận được {frequency:g}."
        )
    duration = _number(duration_s, "duration")
    if duration < MIN_SPEAK_DURATION_S:
        raise CameraAudioInputError(
            f"'duration' phải từ {MIN_SPEAK_DURATION_S:g} giây trở lên, "
            f"nhận được {duration:g}."
        )
    if duration > max_duration_s:
        raise CameraAudioInputError(
            f"'duration' tối đa {max_duration_s:g} giây để không giữ loa quá "
            f"lâu, nhận được {duration:g}."
        )
    return frequency, duration


# --------------------------------------------------------------------------
# Controller
# --------------------------------------------------------------------------
class SpeakController:
    """Phát tiếng ra loa camera, an toàn đa luồng, một phiên mỗi lần phát."""

    def __init__(
        self,
        speaker: SpeakerConfig,
        *,
        transport_opener: Callable[..., Any] | None = None,
        pacer_factory: Callable[[int], Any] | None = None,
        max_duration_s: float | None = None,
    ) -> None:
        if not isinstance(speaker, SpeakerConfig):
            raise CameraAudioConfigError(
                "SpeakController cần một SpeakerConfig hợp lệ."
            )
        self._speaker = speaker
        self._transport_opener = transport_opener
        self._pacer_factory = pacer_factory
        self._max_duration_s = float(
            MAX_SPEAK_DURATION_S if max_duration_s is None else max_duration_s
        )
        if not math.isfinite(self._max_duration_s) or self._max_duration_s <= 0:
            raise CameraAudioInputError(
                f"max_duration_s phải dương, nhận được {self._max_duration_s!r}."
            )
        self._lock = threading.Lock()

    # -- thuộc tính chỉ đọc --------------------------------------------
    @property
    def speaker(self) -> SpeakerConfig:
        return self._speaker

    @property
    def busy(self) -> bool:
        """``True`` nếu hiện có một lời gọi đang phát."""
        return self._lock.locked()

    # -- dựng từ Config ------------------------------------------------
    @classmethod
    def from_config(cls, config: Any, **kwargs: Any) -> "SpeakController":
        """Dựng controller từ :class:`posture_monitor.core.config.Config`."""
        return cls(speaker_config_from_config(config), **kwargs)

    # -- công khai ------------------------------------------------------
    def speak_tone(
        self,
        frequency_hz: float = DEFAULT_TONE_HZ,
        duration_s: float = DEFAULT_TONE_DURATION_S,
    ) -> SpeakResult:
        """Phát một tiếng bíp; **không cần ffmpeg**."""
        frequency, duration = _check_tone(
            frequency_hz, duration_s, self._max_duration_s
        )
        self._acquire()
        try:
            return self._play_tone(frequency, duration)
        finally:
            self._lock.release()

    def speak_file(self, path: str, volume: float = 1.0) -> SpeakResult:
        """Phát một file âm thanh qua loa camera; **cần ffmpeg**."""
        target = self._check_file(path, volume)
        self._acquire()
        try:
            return self._play_file(target, float(volume))
        finally:
            self._lock.release()

    # -- nội bộ ---------------------------------------------------------
    def _acquire(self) -> None:
        """Chiếm loa; đang có lời gọi khác thì báo bận ngay, không xếp hàng."""
        if not self._lock.acquire(blocking=False):
            raise CameraAudioBusy(
                "Loa camera đang phát tiếng khác, vui lòng thử lại sau khi "
                "tiếng hiện tại chạy xong."
            )

    def _safe(self, value: object) -> str:
        """Che userinfo RTSP **và** mật khẩu literal trước khi vào log/lỗi."""
        text = redact_camera_source(value)
        password = self._speaker.password
        if password:
            text = text.replace(password, REDACTED)
        return text

    def _fail(self, message: str) -> CameraAudioError:
        return CameraAudioError(self._safe(message))

    def _check_file(self, path: object, volume: object) -> str:
        if not isinstance(path, str) or not path.strip():
            raise CameraAudioInputError("Thiếu đường dẫn file cần phát.")
        target = path.strip().strip('"')
        if not os.path.isfile(target):
            raise CameraAudioInputError(
                f"Không thấy file âm thanh {self._safe(repr(target))} trên máy "
                "chạy dashboard."
            )
        level = _number(volume, "volume")
        if not 0.0 <= level <= 1.0:
            raise CameraAudioInputError(
                f"'volume' phải trong khoảng 0..1, nhận được {level:g}."
            )
        return target

    def _open(self, library: Mapping[str, Any] | None = None):
        opener = (
            self._transport_opener
            if self._transport_opener is not None
            else (library or _load_library())["open_backchannel_transport"]
        )
        return opener(
            self._speaker.stream_uri,
            self._speaker.user,
            self._speaker.password,
        )

    def _pacer(self, sample_rate: int, library: Mapping[str, Any]):
        if self._pacer_factory is not None:
            return self._pacer_factory(sample_rate)
        return library["RtpPacer"](sample_rate, mode="rebase")

    def _play_tone(self, frequency: float, duration: float) -> SpeakResult:
        library = _load_library()
        duration_ms = int(round(duration * 1000))
        uri = self._speaker.stream_uri
        logger.info(
            "Phát tiếng bíp %g Hz trong %g giây ra loa %s.",
            frequency,
            duration,
            self._safe(uri),
        )
        try:
            with self._open(library) as session:
                selected = self._select_tone_codec(
                    library["select_codec"], session.send_track
                )
                if selected.sample_rate != SAMPLE_RATE:
                    raise self._fail(
                        f"Camera đề nghị lấy mẫu {selected.sample_rate} Hz, "
                        "module này chỉ sinh được G.711 8 kHz."
                    )
                payload = library["tone_audio"](
                    frequency,
                    duration_ms,
                    selected.codec,
                    amp=TONE_AMPLITUDE,
                    rate=selected.sample_rate,
                )
                packetizer = library["RtpPacketizer"](selected.payload_type)
                pacer = self._pacer(selected.sample_rate, library)
                plan = library["RtpBoundaryPlan"].fixed(
                    payload,
                    SAMPLES_PER_PACKET,
                    sample_rate=selected.sample_rate,
                    bytes_per_sample=1,
                )
                sent = 0
                samples_sent = 0
                for boundary in plan.packets:
                    session.check_keepalive()
                    pacer.wait(boundary.samples)
                    packet = packetizer.build(
                        boundary.payload,
                        boundary.samples,
                        marker=sent == 0,
                    )
                    session.send_rtp(packet)
                    sent += 1
                    samples_sent += boundary.samples
                session.check_keepalive()
                pacer.finish()
        except CameraAudioError:
            raise
        except Exception as exc:  # noqa: BLE001 - mọi lỗi thiết bị → lỗi tiếng Việt
            logger.warning(
                "Phát tiếng ra loa %s thất bại: %s",
                self._safe(uri),
                self._safe(f"{type(exc).__name__}: {exc}"),
            )
            raise self._fail(
                f"Không phát được tiếng ra loa camera: {exc}. Kiểm tra mật "
                f"khẩu ở biến môi trường {ONVIF_PASSWORD_ENV}, địa chỉ camera "
                "và xem camera có bật loa hay không."
            ) from exc

        result = SpeakResult(
            mode="tone",
            codec=selected.codec.upper(),
            sample_rate=selected.sample_rate,
            packets_sent=sent,
            duration_seconds=samples_sent / selected.sample_rate,
        )
        logger.info(
            "Đã phát %d gói %s (%.2f giây) tới loa %s.",
            result.packets_sent,
            result.codec,
            result.duration_seconds,
            self._safe(uri),
        )
        return result

    @staticmethod
    def _select_tone_codec(select_codec: Callable[..., Any], send_track: Any):
        """Chọn codec G.711 mà chính module này sinh được."""
        errors = []
        for codec in _TONE_CODECS:
            try:
                return select_codec(send_track, codec)
            except RuntimeError as exc:
                errors.append(str(exc))
            except ValueError as exc:  # pragma: no cover - thư viện đổi API
                errors.append(str(exc))
        raise CameraAudioError(
            "Camera không mời codec G.711 (PCMA/PCMU) trên track backchannel "
            f"nên chưa phát được tiếng bíp: {'; '.join(errors) or 'không rõ'}. "
            "Dùng file âm thanh (nếu camera hỗ trợ codec khác) để phát."
        )

    def _play_file(self, path: str, volume: float) -> SpeakResult:
        if not ffmpeg_available():
            raise CameraAudioUnavailable(
                "Không tìm thấy ffmpeg trên máy này nên chưa phát được file âm "
                "thanh ra loa camera. Cài ffmpeg (Raspberry Pi: sudo apt "
                "install -y ffmpeg; Windows: winget install Gyan.FFmpeg) rồi "
                "thử lại. Trong lúc chưa có ffmpeg, dùng tiếng bíp "
                "(/api/speak với 'tone_hz'/'duration') — đường đó không cần "
                "ffmpeg."
            )
        library = _load_library()
        uri = self._speaker.stream_uri
        logger.info(
            "Phát file âm thanh %s ra loa %s (âm lượng %g).",
            self._safe(repr(path)),
            self._safe(uri),
            volume,
        )
        try:
            played = library["play_file"](
                host=uri,
                file=path,
                user=self._speaker.user,
                password=self._speaker.password,
                volume=volume,
                codec="auto",
            )
        except CameraAudioError:
            raise
        except Exception as exc:  # noqa: BLE001 - mọi lỗi thiết bị → lỗi tiếng Việt
            logger.warning(
                "Phát file ra loa %s thất bại: %s",
                self._safe(uri),
                self._safe(f"{type(exc).__name__}: {exc}"),
            )
            raise self._fail(
                f"Không phát được file ra loa camera: {exc}. Kiểm tra file "
                "có tiếng, mật khẩu ONVIF và kết nối tới camera."
            ) from exc

        result = SpeakResult(
            mode="file",
            codec=str(played.codec),
            sample_rate=int(played.sample_rate),
            packets_sent=int(played.packets_sent),
            duration_seconds=float(played.duration_seconds),
        )
        logger.info(
            "Đã phát file %d gói %s (%.2f giây) tới loa %s.",
            result.packets_sent,
            result.codec,
            result.duration_seconds,
            self._safe(uri),
        )
        return result


__all__ = [
    "CameraAudioBusy",
    "CameraAudioConfigError",
    "CameraAudioError",
    "CameraAudioInputError",
    "CameraAudioUnavailable",
    "DEFAULT_TONE_DURATION_S",
    "DEFAULT_TONE_HZ",
    "MAX_SPEAK_DURATION_S",
    "MIN_SPEAK_DURATION_S",
    "ONVIF_PASSWORD_ENV",
    "SAMPLES_PER_PACKET",
    "SpeakController",
    "SpeakResult",
    "SpeakerConfig",
    "ffmpeg_available",
    "section_value",
    "speaker_config_from_config",
]
