"""Thư viện giọng đọc thu sẵn (nam/nữ) thay cho giọng máy ``espeak-ng``.

Bố cục thư mục mà module này đọc (do người dùng tự đặt file vào)::

    data/audio/
      giongnam/            # giọng nam
        leave_frame.mp3
        phone.mp3
        stranger.mp3
      giongnu/             # giọng nữ
        leave_frame.mp3
        phone.mp3
        stranger.mp3

Module này **không** gọi ``espeak-ng`` và không quyết định phát gì — nó chỉ trả
lời "có file nào cho câu này không" và "đổi file đó sang WAV để phát được
không". Việc quyết định thuộc :mod:`posture_monitor.alerts.speaker_alert`.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from ..camera.audio import ffmpeg_available
from ..core.atomic_io import write_json_atomic
from ..core.labels import (
    DEFAULT_SPEECH_SPEED,
    DEFAULT_VOICE,
    DEFAULT_VOLUME,
    MAX_SPEECH_SPEED,
    MAX_VOLUME,
    MIN_SPEECH_SPEED,
    MIN_VOLUME,
    VOICE_DIRS,
    VOICE_FEMALE,
    VOICE_LABELS,
    VOICE_MALE,
    VOICE_SYNTH,
    VOICES,
    normalise_speed,
    normalise_voice,
    normalise_volume,
)
from ..core.logging_setup import get_logger

logger = get_logger(__name__)

#: Phần mở rộng được chấp nhận, **theo thứ tự ưu tiên**. Cùng một câu mà có cả
#: ``.wav`` lẫn ``.mp3`` thì ``.wav`` thắng — nó không mất gì qua một lần giải mã nữa.
AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus")

#: Từ khoá để nhận ra một bản thu thuộc câu nào, khi tên file **không** trùng mã loại.
CLIP_KEYWORDS = {
    "leave_frame": (
        "banoi",
        "quaylai",
        "banhoc",
        "roikhoi",
        "leaveframe",
        "leave",
    ),
    "phone": (
        "catdienthoai",
        "dienthoai",
        "catdien",
        "dungdienthoai",
        "phone",
        "smartphone",
    ),
    "stranger": (
        "khongphainguoidangki",
        "khongphai",
        "nguoila",
        "nguoidangki",
        "stranger",
        "impostor",
    ),
}


def prepare_filter(speed: Any = DEFAULT_SPEECH_SPEED) -> str:
    """Chuỗi lọc ffmpeg khi đổi bản thu sang WAV để phát, theo ``speed``."""
    level = normalise_speed(speed)
    return (
        "silenceremove=start_periods=1:start_silence=0:start_threshold=-50dB,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0:start_threshold=-50dB,"
        "areverse,"
        f"atempo={level:g},"
        "loudnorm=I=-16:TP=-1.5:LRA=11,"
        "aresample=22050"
    )


#: Chuỗi lọc ở tốc độ mặc định — giữ tên cũ cho mã/test đang dùng.
PREPARE_FILTER = prepare_filter()

#: Chặn trên thời gian một lần ``ffmpeg``.
FFMPEG_TIMEOUT_S = 30.0

#: Tên file cấu hình giọng đang chọn, đặt ngay trong ``audio_dir``.
SETTINGS_FILENAME = "voice.json"


class VoiceClipError(RuntimeError):
    """Không đọc/đổi được bản thu — thông điệp đã là tiếng Việt đọc được."""


# --------------------------------------------------------------------------
# Tìm file
# --------------------------------------------------------------------------
def voice_dir(audio_dir: str | Path, voice: str) -> Path:
    """Thư mục chứa bản thu của ``voice`` (``audio_dir/giongnam`` …)."""
    name = VOICE_DIRS.get(voice)
    if name is None:
        raise VoiceClipError(
            f"Giọng '{voice}' không có thư mục bản thu (chỉ "
            f"{', '.join(VOICE_DIRS)} mới có)."
        )
    return Path(audio_dir) / name


def _fingerprint(name: str) -> str:
    """Bỏ dấu tiếng Việt và mọi ký tự không phải chữ/số, viết thường."""
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in stripped.lower() if ch.isalnum())


def _matches_kind(fingerprint: str, kind: str) -> bool:
    """Tên file có chứa từ khoá nào của loại ``kind`` không."""
    return any(keyword in fingerprint for keyword in CLIP_KEYWORDS.get(kind, ()))


def classify_filename(name: str, kinds: Any) -> str | None:
    """Đoán một tên file thuộc loại cảnh báo nào; ``None`` khi không chắc."""
    stem = Path(name).stem
    lowered = stem.strip().lower()
    for kind in kinds:
        if lowered == str(kind).lower():
            return kind

    fingerprint = _fingerprint(stem)
    matched = [kind for kind in kinds if _matches_kind(fingerprint, kind)]
    if len(matched) != 1:
        return None
    return matched[0]


def find_clip(audio_dir: str | Path, voice: str, kind: str) -> Path | None:
    """Trả file bản thu của câu ``kind`` cho ``voice``, hoặc ``None``."""
    try:
        directory = voice_dir(audio_dir, voice)
    except VoiceClipError:
        return None
    if not directory.is_dir():
        return None
    for suffix in AUDIO_SUFFIXES:
        candidate = directory / f"{kind}{suffix}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate

    best: Path | None = None
    for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_file() or entry.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        if entry.stat().st_size <= 0:
            continue
        if classify_filename(entry.name, (kind,)) != kind:
            continue
        if best is None or AUDIO_SUFFIXES.index(
            entry.suffix.lower()
        ) < AUDIO_SUFFIXES.index(best.suffix.lower()):
            best = entry
    return best


def list_clips(audio_dir: str | Path, voice: str, kinds: Any) -> dict[str, Path]:
    """Ánh xạ ``kind → file`` cho những câu **có** bản thu; thiếu thì vắng mặt."""
    found: dict[str, Path] = {}
    for kind in kinds:
        clip = find_clip(audio_dir, voice, kind)
        if clip is not None:
            found[kind] = clip
    return found


def available_voices(audio_dir: str | Path, kinds: Any) -> dict[str, dict[str, Any]]:
    """Tình trạng từng giọng, để dashboard hiện được mà không cần thử phát."""
    kinds = tuple(kinds)
    report: dict[str, dict[str, Any]] = {}
    for voice in VOICES:
        if voice not in VOICE_DIRS:
            report[voice] = {
                "label": VOICE_LABELS[voice],
                "dir": None,
                "clips": {},
                "ready": True,
                "missing": [],
            }
            continue
        directory = voice_dir(audio_dir, voice)
        clips = list_clips(audio_dir, voice, kinds)
        report[voice] = {
            "label": VOICE_LABELS[voice],
            "dir": str(directory),
            "clips": {kind: path.name for kind, path in clips.items()},
            "ready": len(clips) == len(kinds),
            "missing": [kind for kind in kinds if kind not in clips],
        }
    return report


# --------------------------------------------------------------------------
# Đổi bản thu sang WAV phát được
# --------------------------------------------------------------------------
def prepare_clip(
    source: str | Path,
    target: str | Path,
    *,
    speed: Any = DEFAULT_SPEECH_SPEED,
) -> None:
    """Đổi ``source`` (mp3/m4a/…) sang WAV mono 22 050 Hz tại ``target``."""
    if not ffmpeg_available():
        raise VoiceClipError(
            "Không tìm thấy ffmpeg nên chưa đổi được bản thu giọng nói sang "
            "WAV (Raspberry Pi: sudo apt install -y ffmpeg; Windows: winget "
            "install Gyan.FFmpeg)."
        )
    src = Path(source)
    dst = Path(target)
    chain = prepare_filter(speed)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VoiceClipError(f"Không tạo được thư mục '{dst.parent}': {exc}") from exc

    temporary = dst.with_name(f".{dst.name}.tmp")
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                os.fspath(src),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-ac",
                "1",
                "-ar",
                "22050",
                "-af",
                chain,
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                os.fspath(temporary),
            ],
            check=False,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise VoiceClipError(
            "Không tìm thấy ffmpeg nên chưa đổi được bản thu giọng nói sang "
            "WAV. Cài ffmpeg rồi khởi động lại."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise VoiceClipError(
            f"ffmpeg chạy quá {FFMPEG_TIMEOUT_S:g} giây khi đổi "
            f"'{src.name}' nên bị dừng."
        ) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        _unlink_quietly(temporary)
        raise VoiceClipError(
            f"Không đọc được file âm thanh '{src.name}'"
            f"{' : ' + detail if detail else '.'}"
        )

    try:
        if temporary.stat().st_size <= 44:
            _unlink_quietly(temporary)
            raise VoiceClipError(
                f"File âm thanh '{src.name}' không có tiếng sau khi xử lý "
                "(có thể là file im lặng hoặc hỏng)."
            )
        os.replace(temporary, dst)
    except OSError as exc:
        _unlink_quietly(temporary)
        raise VoiceClipError(f"Không ghi được file WAV '{dst}': {exc}") from exc


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------
# Lưu giọng đang chọn
# --------------------------------------------------------------------------
def load_voice(audio_dir: str | Path, default: str = DEFAULT_VOICE) -> str:
    """Đọc giọng đã chọn từ ``voice.json``; thiếu/hỏng thì trả ``default``."""
    path = Path(audio_dir) / SETTINGS_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return normalise_voice(default)
    except (OSError, ValueError) as exc:
        logger.warning(
            "Không đọc được '%s' (%s); dùng giọng mặc định '%s'.",
            path,
            exc,
            default,
        )
        return normalise_voice(default)
    if not isinstance(raw, dict):
        return normalise_voice(default)
    return normalise_voice(raw.get("voice", default))


def save_voice(audio_dir: str | Path, voice: str) -> None:
    """Ghi giọng đang chọn xuống ``voice.json`` một cách nguyên tử.

    Raises:
        VoiceClipError: không ghi được — người gọi quyết định có coi là lỗi
            hay chỉ ghi log. Lựa chọn vẫn có hiệu lực trong phiên đang chạy
            kể cả khi ghi hỏng.
    """
    path = Path(audio_dir) / SETTINGS_FILENAME
    payload = {"version": 1, "voice": normalise_voice(voice)}
    try:
        write_json_atomic(path, payload)
    except OSError as exc:
        raise VoiceClipError(
            f"Không lưu được lựa chọn giọng đọc vào '{path}': {exc}"
        ) from exc


def describe_clip(path: str | Path) -> str:
    """Mô tả ngắn một file bản thu cho log (tên + kích thước, không nội dung)."""
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError:
        return f"{target.name} (không đọc được)"
    return f"{target.name} ({size / 1024:.0f} KB)"


def is_finite_positive(value: Any) -> bool:
    """``True`` nếu ``value`` là số thực hữu hạn > 0 (dùng khi kiểm cấu hình)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


__all__ = [
    "AUDIO_SUFFIXES",
    "CLIP_KEYWORDS",
    "DEFAULT_SPEECH_SPEED",
    "DEFAULT_VOICE",
    "DEFAULT_VOLUME",
    "FFMPEG_TIMEOUT_S",
    "MAX_SPEECH_SPEED",
    "MAX_VOLUME",
    "MIN_SPEECH_SPEED",
    "MIN_VOLUME",
    "PREPARE_FILTER",
    "SETTINGS_FILENAME",
    "VOICES",
    "VOICE_DIRS",
    "VOICE_FEMALE",
    "VOICE_LABELS",
    "VOICE_MALE",
    "VOICE_SYNTH",
    "VoiceClipError",
    "available_voices",
    "classify_filename",
    "describe_clip",
    "ffmpeg_available",
    "find_clip",
    "is_finite_positive",
    "list_clips",
    "load_voice",
    "normalise_speed",
    "normalise_voice",
    "normalise_volume",
    "prepare_clip",
    "prepare_filter",
    "save_voice",
    "voice_dir",
]
