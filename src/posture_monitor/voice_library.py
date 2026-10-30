"""Thư viện giọng đọc thu sẵn (nam/nữ) thay cho giọng máy ``espeak-ng``.

Vì sao có module này: ``espeak-ng`` là giọng tổng hợp kiểu máy — đúng chữ nhưng
người nghe phải "dịch" từng âm tiết, nên trên loa nhỏ của camera IP rất khó
nghe. Bản thu giọng người thật dễ nghe hơn hẳn; đo bằng STOI qua đúng chuỗi
của camera (8 kHz → A-law 8 bit → loa nhỏ) cho 0,958–0,972 so với 0,929–0,945
của ``espeak-ng``.

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

**Tên file phải trùng mã loại cảnh báo** (``leave_frame``/``phone``/``stranger``)
và phần mở rộng nào trong :data:`AUDIO_SUFFIXES` cũng được. Quy ước này cố ý
chặt: đoán tên bằng từ khoá thì hai file gần giống nhau sẽ tranh nhau cùng một
câu, và người dùng không có cách nào biết file nào đang được dùng.

Module này **không** gọi ``espeak-ng`` và không quyết định phát gì — nó chỉ trả
lời "có file nào cho câu này không" và "đổi file đó sang WAV để phát được
không". Việc quyết định thuộc :mod:`posture_monitor.speaker_alert`.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from .logging_setup import get_logger

logger = get_logger(__name__)

# --------------------------------------------------------------------------
# Mã giọng
# --------------------------------------------------------------------------
#: Giọng nam thu sẵn (thư mục ``giongnam``).
VOICE_MALE = "nam"
#: Giọng nữ thu sẵn (thư mục ``giongnu``).
VOICE_FEMALE = "nu"
#: Giọng tổng hợp ``espeak-ng`` — đường cũ, giữ lại làm dự phòng.
VOICE_SYNTH = "espeak"

#: Mọi mã giọng hợp lệ, theo thứ tự hiện trên dashboard.
VOICES = (VOICE_MALE, VOICE_FEMALE, VOICE_SYNTH)

#: Nhãn tiếng Việt cho giao diện.
VOICE_LABELS = {
    VOICE_MALE: "Giọng nam",
    VOICE_FEMALE: "Giọng nữ",
    VOICE_SYNTH: "Giọng máy",
}

#: Mặc định: giọng nam, vì đó là thư mục người dùng gửi kèm. Nếu thư mục rỗng
#: thì ``speaker_alert`` tự rơi về ``espeak`` (xem ``prepare``), nên mặc định
#: này không bao giờ làm mất tiếng.
DEFAULT_VOICE = VOICE_MALE

#: Tên thư mục con cho từng giọng thu sẵn (dưới ``speaker_alert.audio_dir``).
VOICE_DIRS = {
    VOICE_MALE: "giongnam",
    VOICE_FEMALE: "giongnu",
}

#: Phần mở rộng được chấp nhận, **theo thứ tự ưu tiên**. Cùng một câu mà có cả
#: ``.wav`` lẫn ``.mp3`` thì ``.wav`` thắng — nó không mất gì qua một lần giải
#: mã nữa.
AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus")

#: Từ khoá để nhận ra một bản thu thuộc câu nào, khi tên file **không** trùng
#: mã loại (``phone.mp3``). Người dùng thường đặt tên theo câu đọc, ví dụ
#: ``catdienthoaigongnam.mp3``; bắt họ đổi tên là việc không cần thiết.
#:
#: Mỗi danh sách được so trên tên file đã bỏ dấu và bỏ mọi ký tự không phải
#: chữ/số (xem :func:`_fingerprint`), nên ``Cất điện thoại.mp3`` và
#: ``catdienthoai.mp3`` cho cùng một khoá.
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

#: Tốc độ đọc mặc định so với bản thu gốc (0,9 = chậm lại 10 %).
#:
#: Vì sao cần chậm lại: loa camera chỉ rộng 2 cm và chỉ nhận 8 kHz, nên phụ âm
#: bị nén vào rất ngắn — người nghe phải "đuổi" từng âm tiết và dễ nghe thành
#: tiếng rè. Chậm 10 % giữ nguyên cao độ (``atempo``) nên giọng vẫn là giọng
#: của người thu, chỉ có khoảng cách giữa các âm tiết rộng ra.
#:
#: Chỉnh được bằng ``speaker_alert.speed`` (0,5–1,0) hoặc ``speak-test --speed``.
DEFAULT_SPEECH_SPEED = 0.9

#: Khoảng tốc độ ``atempo`` chấp nhận cho giọng đọc. Dưới 0,5 là quá chậm để
#: còn là câu nhắc; trên 1,0 là nhanh hơn bản thu, ngược hẳn mục đích ở đây.
MIN_SPEECH_SPEED = 0.5
MAX_SPEECH_SPEED = 1.0


#: Âm lượng gửi đi khi phát câu nói, mặc định. Đặt ở đây (không đặt trong
#: ``speaker_alert``) để ``config`` kiểm tra được mà không tạo vòng import.
DEFAULT_VOLUME = 0.7
#: Khoảng âm lượng hợp lệ. Trên 1,0 là khuếch đại số, chỉ làm tăng méo.
MIN_VOLUME = 0.05
MAX_VOLUME = 1.0


def normalise_volume(value: Any, default: float = DEFAULT_VOLUME) -> float:
    """Đổi ``value`` thành âm lượng hợp lệ; hỏng/ngoài khoảng thì ``default``."""
    try:
        level = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(level) or not MIN_VOLUME <= level <= MAX_VOLUME:
        return default
    return level


def normalise_speed(value: Any, default: float = DEFAULT_SPEECH_SPEED) -> float:
    """Đổi giá trị bất kỳ thành tốc độ đọc hợp lệ; hỏng thì về ``default``.

    Không ném lỗi vì hàm này còn dùng cho giá trị đọc từ tệp lưu và từ cờ dòng
    lệnh; nơi kiểm tra cấu hình (``config._parse_speaker_alert``) mới là chỗ
    báo lỗi gõ tay.
    """
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(speed):
        return default
    if not MIN_SPEECH_SPEED <= speed <= MAX_SPEECH_SPEED:
        return default
    return speed


def prepare_filter(speed: Any = DEFAULT_SPEECH_SPEED) -> str:
    """Chuỗi lọc ffmpeg khi đổi bản thu sang WAV để phát, theo ``speed``.

    1. ``silenceremove`` hai đầu (lật file để cắt cả đuôi) — bản thu tay thường
       có 0,2–0,3 s im lặng đầu và tới 0,9 s im lặng cuối; cắt đi thì câu nhắc
       tới sớm hơn gần một giây.
    2. ``atempo`` chỉnh tốc độ **không đổi cao độ**. Dùng ``atempo`` chứ không
       dùng ``asetrate``: ``asetrate`` hạ cao độ xuống theo, giọng nam thành
       giọng rất trầm và càng khó nghe trên loa nhỏ.
    3. ``loudnorm`` đưa về −16 LUFS: loa camera nhỏ nên mức thu thấp (−20 dBFS
       RMS ở các bản thu này) nghe rất nhỏ. Đầu ra giới hạn đỉnh −1,5 dBTP nên
       không bị vỡ tiếng.
    4. ``aresample`` về 22 050 Hz: ``backchannel_audio`` tự hạ tiếp xuống 8 kHz
       bằng bộ lọc ``swr`` có chống chồng phổ, nên đây chỉ là mức trung gian.
    5. ``ac 1``: ép mono — loa camera chỉ có một kênh.
    """
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

#: Chặn trên thời gian một lần ``ffmpeg``; file 3 giây chạy xong trong <1 s,
#: nên 30 s là dư rộng và chỉ để một lần treo không giữ mãi bước khởi động.
FFMPEG_TIMEOUT_S = 30.0

#: Tên file cấu hình giọng đang chọn, đặt ngay trong ``audio_dir`` để nó đi
#: cùng các file âm thanh mà nó mô tả.
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
    """Bỏ dấu tiếng Việt và mọi ký tự không phải chữ/số, viết thường.

    ``"Cất điện thoại.mp3"`` → ``"catdienthoai"``. Nhờ vậy từ khoá so được với
    tên file dù người dùng đặt tên có dấu, có khoảng trắng hay gạch dưới.
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # "đ" không có dạng NFD tách dấu nên phải đổi tay.
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in stripped.lower() if ch.isalnum())


def _matches_kind(fingerprint: str, kind: str) -> bool:
    """Tên file có chứa từ khoá nào của loại ``kind`` không."""
    return any(keyword in fingerprint for keyword in CLIP_KEYWORDS.get(kind, ()))


def classify_filename(name: str, kinds: Any) -> str | None:
    """Đoán một tên file thuộc loại cảnh báo nào; ``None`` khi không chắc.

    Hai đường, theo thứ tự:

    1. **Tên trùng mã loại** (``phone.wav``) — chắc chắn tuyệt đối.
    2. **Từ khoá trong tên** (``catdienthoaigongnam.mp3``) — chỉ nhận khi tên
       khớp từ khoá của **đúng một** loại.

    Tên khớp từ khoá của hai loại (``dienthoai_va_nguoila.mp3``) bị từ chối
    thay vì chọn loại có từ khoá dài hơn: một câu nhắc sai nội dung còn tệ hơn
    phát giọng máy đúng nội dung, và người dùng không có cách nào đoán được vì
    sao câu bị đọc sai.
    """
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
    """Trả file bản thu của câu ``kind`` cho ``voice``, hoặc ``None``.

    Nhận cả tên trùng mã loại (``phone.mp3``) lẫn tên mô tả theo câu đọc
    (``catdienthoaigongnam.mp3``) — xem :func:`classify_filename`. Có nhiều
    phần mở rộng cùng tên thì chọn theo :data:`AUDIO_SUFFIXES`.
    """
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

    # Không có file tên trùng mã loại: quét thư mục một lượt và chọn file
    # khớp từ khoá. Sắp xếp tên để kết quả ổn định giữa các lần chạy (thứ tự
    # ``iterdir`` phụ thuộc hệ tệp, không được để nó quyết định).
    best: Path | None = None
    for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_file() or entry.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        if entry.stat().st_size <= 0:
            continue
        if classify_filename(entry.name, (kind,)) != kind:
            continue
        # Đã lọc theo đúng ``kind`` nên nhiều file cùng loại là chuyện của
        # người dùng; chọn file đầu theo tên để hành vi tất định.
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
    """Tình trạng từng giọng, để dashboard hiện được mà không cần thử phát.

    Trả ``{voice: {"label", "dir", "clips": {kind: tên_file}, "ready": bool}}``.
    ``ready`` chỉ ``True`` khi **đủ** bản thu cho mọi ``kinds`` — thiếu một câu
    vẫn phát được (câu thiếu rơi về ``espeak``) nhưng người dùng cần biết.
    """
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


def ffmpeg_available() -> bool:
    """``True`` nếu tìm thấy ``ffmpeg`` trong ``PATH``."""
    from shutil import which

    return which("ffmpeg") is not None


# --------------------------------------------------------------------------
# Đổi bản thu sang WAV phát được
# --------------------------------------------------------------------------
def prepare_clip(
    source: str | Path,
    target: str | Path,
    *,
    speed: Any = DEFAULT_SPEECH_SPEED,
) -> None:
    """Đổi ``source`` (mp3/m4a/…) sang WAV mono 22 050 Hz tại ``target``.

    Args:
        source: bản thu gốc của người dùng.
        target: file WAV sẽ ghi.
        speed: tốc độ đọc (xem :func:`prepare_filter`). Đổi tốc độ phải gọi
            lại hàm này — người gọi (``speaker_alert``) quyết định khi nào.

    Ghi ra file tạm rồi ``os.replace`` để lần đọc song song không bao giờ thấy
    file WAV viết dở (cùng lý do ``people_service`` ghi ngưỡng theo cách này).

    Raises:
        VoiceClipError: thiếu ``ffmpeg``, ``ffmpeg`` trả lỗi, hoặc không ghi
            được file — thông điệp tiếng Việt nêu đúng việc cần làm.
    """
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
                # Phải nói rõ định dạng: tên tạm kết thúc bằng ``.tmp`` nên
                # ffmpeg không suy ra được container từ phần mở rộng và bỏ
                # cuộc ("Unable to choose an output format").
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
def normalise_voice(value: Any) -> str:
    """Đổi giá trị bất kỳ thành mã giọng hợp lệ; hỏng thì về mặc định.

    Không ném lỗi: file cấu hình do người sửa tay mà gõ sai thì dashboard vẫn
    phải mở được, chỉ là giọng về mặc định.
    """
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in VOICES:
            return candidate
        # Chấp nhận tên thư mục người dùng quen gõ.
        for voice, directory in VOICE_DIRS.items():
            if candidate == directory:
                return voice
    return DEFAULT_VOICE


def load_voice(audio_dir: str | Path, default: str = DEFAULT_VOICE) -> str:
    """Đọc giọng đã chọn từ ``voice.json``; thiếu/hỏng thì trả ``default``.

    Không bao giờ ném lỗi: tệp phụ hỏng không được làm dashboard không mở được.
    """
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
    """Ghi giọng đang chọn xuống ``voice.json`` (ghi tạm rồi thay).

    Raises:
        VoiceClipError: không ghi được — người gọi quyết định có coi là lỗi
            hay chỉ ghi log. Lựa chọn vẫn có hiệu lực trong phiên đang chạy
            kể cả khi ghi hỏng.
    """
    path = Path(audio_dir) / SETTINGS_FILENAME
    payload = {"version": 1, "voice": normalise_voice(voice)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
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
