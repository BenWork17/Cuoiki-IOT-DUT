"""Quyết định **phát gì, khi nào** ra loa của camera IP (spec v3 §5.15).

Module này **không** mở socket và **không** tự giữ một kết nối RTSP nào: mọi
việc đẩy tiếng ra loa đã nằm trong :class:`posture_monitor.camera_audio.SpeakController`
(đã nghiệm thu — sinh G.711 không cần ffmpeg, khoá chống hai luồng cùng đẩy
RTP, chặn thời lượng, che mật khẩu trong log). Ở đây chỉ còn ba câu hỏi:

- **Phát gì**: một trong ba câu tiếng Việt ở :data:`ALERT_TEXT`, hoặc tiếng bíp
  khi không phát được câu. Không loại nào khác.
- **Khi nào**: khi tầng gọi đã quyết định xong. Cổng giờ học, ``hold_s`` và
  ``cooldown_s`` thuộc :func:`posture_monitor.schedule.should_alert` — alerter
  **không đếm lại lần nữa** (spec §5.15: "alerter không đếm lại lần nữa").
  Vì vậy gọi :meth:`SpeakerAlerter.alert` ba lần liên tiếp với cùng một loại
  sẽ phát **ba lần**; đó là ranh giới trách nhiệm, không phải lỗi.
- **Khi hai sự kiện cùng lúc**: chỉ phát loại **nghiêm trọng nhất** theo
  :data:`PRIORITY` (người lạ > vắng mặt > dùng điện thoại). Không bao giờ
  phát hai cảnh báo chồng nhau — loa camera chỉ có một phiên backchannel.

Vì sao file WAV được sinh **một lần lúc khởi động**
--------------------------------------------------

Spec §5.15: "file WAV tiếng Việt được sinh **một lần lúc khởi động** (hoặc lúc
cấu hình đổi) ... Sinh lại mỗi lần cảnh báo là lãng phí và gây trễ." Vậy
:meth:`SpeakerAlerter.prepare` gọi ``espeak-ng -v vi -w <out> <câu>`` cho từng
câu, lưu vào ``audio_dir``, và các lần gọi sau **không sinh lại** (đếm được
bằng số lần gọi ``espeak_runner``). Lần nào sinh lỗi thì ghi log rồi để
``prepare`` thử lại ở lần gọi sau — đó là đường "cấu hình đổi", còn cảnh báo
giữa chừng thì vẫn chạy bằng tiếng bíp.

Vì sao lỗi loa **không bao giờ** ném ra ngoài
---------------------------------------------

Spec §5.15 và §3.4: "Mọi lỗi loa (mất mạng, thiếu thư viện, camera từ chối
backchannel) → ghi sự kiện ``SPEAK_FAILED`` và **tiếp tục chạy**. Không được
crash, không được làm rơi vòng lặp camera." Vì thế mọi lời gọi controller đều
nằm trong ``try/except Exception``; kết quả là một :class:`AlertOutcome` có
``error``. Tầng gọi ghi ``SPEAK_FAILED`` từ đó.

Quy tắc riêng của dự án
-----------------------

- **Không** dùng từ bị cấm của spec v3 §11 quy tắc 12 (từ tiếng Anh chỉ việc
  dạy lại model, hay từ Hán-Việt tương ứng) ở bất kỳ đâu trong mã, log, hay
  chuỗi hiển thị: cách gọi đúng là "cập nhật bộ nhận diện".
- **Không** log URL camera, không log mật khẩu, không log ``repr`` của cấu
  hình loa. Module này chỉ log **tên loại cảnh báo** và **kết quả phát**;
  đường dẫn WAV nằm trong ``audio_dir`` do người triển khai tự đặt nên log
  được, nhưng không bao giờ ghép nó với địa chỉ camera.
- Không thêm dịch vụ TTS cloud (spec §12: "không truyền ra ngoài"). Âm thanh
  chỉ sinh cục bộ bằng ``espeak-ng``.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .camera_audio import CameraAudioUnavailable, SpeakController
from .logging_setup import get_logger
from .schedule import KIND_LABELS, KIND_LEAVE_FRAME, KIND_PHONE, KIND_STRANGER
from .voice_library import (
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
    VoiceClipError,
    available_voices,
    describe_clip,
    find_clip,
    load_voice,
    normalise_speed,
    normalise_voice,
    normalise_volume,
    prepare_clip,
    save_voice,
)

logger = get_logger(__name__)

# --------------------------------------------------------------------------
# Loại cảnh báo — dùng lại đúng tên của schedule, không đặt tên thứ hai
# --------------------------------------------------------------------------
#: Vắng mặt. Giá trị chuỗi là **đúng** khóa ``schedule.kinds`` (``leave_frame``),
#: nên không cần bảng ánh xạ ở bất kỳ tầng nào phía sau.
ALERT_ABSENT = KIND_LEAVE_FRAME

#: Đang dùng điện thoại (khóa ``phone`` của ``schedule.kinds``).
ALERT_PHONE_USE = KIND_PHONE

#: Người đang ngồi không phải người đã đăng ký (khóa ``stranger``).
ALERT_IMPOSTOR = KIND_STRANGER

#: Toàn bộ loại cảnh báo mà alerter biết.
ALERT_KINDS = (ALERT_ABSENT, ALERT_PHONE_USE, ALERT_IMPOSTOR)

#: Thứ tự ưu tiên **cao → thấp**: người lạ nghiêm trọng nhất (spec §5.15,
#: "người lạ ngồi vào là nghiêm trọng nhất"), rồi vắng mặt, rồi điện thoại.
PRIORITY = (ALERT_IMPOSTOR, ALERT_ABSENT, ALERT_PHONE_USE)

#: Câu tiếng Việt **nguyên văn** theo spec §5.15. Không sửa chữ, không thêm
#: dấu chấm cuối câu — web và giọng đọc phải nói cùng một câu.
ALERT_TEXT = {
    ALERT_ABSENT: "Bạn ơi, quay lại bàn học nhé",
    ALERT_PHONE_USE: "Cất điện thoại và tập trung học nhé",
    ALERT_IMPOSTOR: "Người đang ngồi không phải người đã đăng ký học",
}

# --------------------------------------------------------------------------
# Kết quả phát
# --------------------------------------------------------------------------
MODE_SPEECH = "speech"  #: phát file WAV tiếng Việt qua ``speak_file``
MODE_TONE = "tone"  #: phát tiếng bíp qua ``speak_tone``
MODE_SKIPPED = "skipped"  #: không phát gì (bận / thiếu đường / lỗi loa)

#: Tiếng bíp thay cho câu nhắc: 880 Hz — cao hơn tiếng bíp mặc định của
#: dashboard (440 Hz) để tai tách được "cảnh báo học tập" với "âm báo chung".
#: Cả hai giá trị đều nằm trong khoảng ``camera_audio`` cho phép.
ALERT_TONE_HZ = 880.0
ALERT_TONE_DURATION_S = 0.6

#: Âm lượng khi phát file WAV (0..1). Đây là mức gửi đi trong luồng PCMA, không
#: phải núm vặn của camera: hạ nó xuống thì loa nhận tín hiệu nhỏ hơn nên ít bị
#: đẩy vào vùng méo. 1.0 là mức nguyên bản; 0,6–0,7 hay dễ nghe hơn trên loa nhỏ.
#: Chỉnh bằng ``speaker_alert.volume`` hoặc ``speak-test --volume``.
ALERT_VOLUME = DEFAULT_VOLUME

#: Khoảng âm lượng hợp lệ (khai báo lại cho người đọc module này).
MIN_ALERT_VOLUME = MIN_VOLUME
MAX_ALERT_VOLUME = MAX_VOLUME

#: Chương trình sinh giọng đọc và giọng tiếng Việt (spec §5.15).
ESPEAK_BINARY = "espeak-ng"
DEFAULT_LANGUAGE = "vi"

#: Vị trí cài mặc định trên Windows, dùng khi ``espeak-ng`` không có trên PATH.
#: Trình cài đặt chính thức **không** thêm thư mục này vào PATH, nên trên máy
#: phát triển Windows gọi trần ``espeak-ng`` luôn thất bại dù đã cài — khi đó
#: chọn "Giọng máy" lại rơi về tiếng bíp một cách khó hiểu. Trên Pi gói apt có
#: đưa vào PATH nên danh sách này không ảnh hưởng.
ESPEAK_FALLBACK_PATHS = (
    r"C:\Program Files\eSpeak NG\espeak-ng.exe",
    r"C:\Program Files (x86)\eSpeak NG\espeak-ng.exe",
    "/usr/bin/espeak-ng",
    "/usr/local/bin/espeak-ng",
)


def find_espeak_binary() -> str | None:
    """Đường dẫn tới ``espeak-ng`` dùng được, hoặc ``None``.

    Tìm trên ``PATH`` trước (đúng cho Pi), rồi mới tới
    :data:`ESPEAK_FALLBACK_PATHS` (đúng cho Windows). Trả ``None`` thay vì ném
    lỗi để người gọi tự quyết định rơi về tiếng bíp.
    """
    found = shutil.which(ESPEAK_BINARY)
    if found:
        return found
    for candidate in ESPEAK_FALLBACK_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


#: Chặn trên thời gian chạy ``espeak-ng`` để một lần treo không giữ mãi bước
#: khởi động.
ESPEAK_TIMEOUT_S = 30.0


def _wav_is_usable(path: Path) -> bool:
    """``True`` khi ``path`` là file WAV đọc được và có dữ liệu tiếng.

    Chỉ kiểm phần đầu file (44 byte header) — đủ để loại file rỗng, file bị
    cắt dở và file không phải WAV. Không giải mã toàn bộ: hàm này chạy lúc
    khởi động, không cần chính xác tuyệt đối.
    """
    try:
        if not path.is_file():
            return False
        with path.open("rb") as handle:
            head = handle.read(44)
    except OSError:
        return False
    if len(head) < 44 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return False
    # ``data`` chunk phải có kích thước > 0, nếu không là file im lặng.
    data_size = int.from_bytes(head[40:44], "little")
    return data_size > 0 and path.stat().st_size > 44


def run_espeak(text: str, out_path: str, *, language: str = DEFAULT_LANGUAGE) -> None:
    """Sinh một file WAV từ ``text`` bằng ``espeak-ng`` (đường mặc định).

    Tách thành hàm công khai để test (và người triển khai) thay được bằng
    ``espeak_runner`` khác mà không phải cài ``espeak-ng``.

    Raises:
        RuntimeError: mọi lỗi đều đổi thành tiếng Việt đọc được — thiếu
            ``espeak-ng``, mã trả về khác 0, hoặc chạy quá lâu.
    """
    try:
        binary = find_espeak_binary()
        if binary is None:
            raise FileNotFoundError(ESPEAK_BINARY)
        subprocess.run(
            [binary, "-v", language, "-w", out_path, text],
            check=True,
            capture_output=True,
            timeout=ESPEAK_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Không tìm thấy '{ESPEAK_BINARY}' trên máy này nên chưa sinh được "
            "file giọng đọc tiếng Việt (Raspberry Pi: sudo apt install -y "
            "espeak-ng)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"'{ESPEAK_BINARY}' trả mã lỗi {exc.returncode} khi sinh giọng "
            f"đọc{' : ' + detail if detail else '.'}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"'{ESPEAK_BINARY}' chạy quá {ESPEAK_TIMEOUT_S:g} giây nên bị dừng."
        ) from exc


@dataclass(frozen=True)
class AlertOutcome:
    """Kết quả một lần quyết định phát cảnh báo.

    Attributes:
        kind: loại cảnh báo đã chọn (khóa của ``schedule``), ``None`` khi
            không có loại nào hợp lệ trong lời gọi.
        text: câu cần truyền đạt (:data:`ALERT_TEXT`), ``None`` cùng cảnh với
            ``kind``. Với ``mode="tone"`` câu này **chưa** được nói ra — chỉ
            tiếng bíp phát đi.
        spoken: ``True`` khi đã thật sự phát ra loa (câu hoặc bíp).
        mode: ``"speech"``, ``"tone"`` hoặc ``"skipped"``.
        reason: lý do đọc được cho người vận hành; ``"skipped"`` luôn có lý do
            rõ ràng, không bao giờ im lặng không giải thích.
        error: ``None`` hoặc mô tả lỗi loa (``"<Kiểu lỗi>: <thông điệp>"``).
            Có ``error`` là tầng gọi ghi sự kiện ``SPEAK_FAILED``.
        at: mốc thời gian (giây, từ ``clock``) của lần quyết định này.
        retryable: ``True`` khi lần này bị bỏ vì một lý do **tạm thời** (loa
            đang phát tiếng khác) nên khung sau còn đáng thử lại. Tầng gọi
            dùng cờ này để **không** tiêu mất cooldown: nếu vẫn đẩy
            ``last_alert_at`` thì lần dùng điện thoại đó không bao giờ được
            nhắc nữa, dù loa chưa hề nói gì.
    """

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
    """Quyết định phát câu cảnh báo nào ra loa camera, và phát nó.

    Args:
        controller: đối tượng có ``speak_tone``/``speak_file``/``busy`` —
            thường là :class:`posture_monitor.camera_audio.SpeakController`.
            ``None`` nghĩa là chưa cấu hình loa; mọi lời gọi trả
            ``mode="skipped"`` kèm lý do chứ không ném lỗi.
        audio_dir: thư mục chứa file WAV sinh sẵn. Mặc định ``data/audio``
            theo spec §5.15. Test truyền ``tmp_path``.
        say: ``True`` (mặc định) thì ưu tiên phát câu bằng giọng đọc;
            ``False`` thì đi thẳng đường tiếng bíp.
        tone_fallback: ``True`` (mặc định) thì rơi về tiếng bíp khi không có
            file/không có ffmpeg. ``False`` thì **bỏ** lần phát kèm lý do —
            vẫn không im lặng không giải thích.
        language: mã giọng của ``espeak-ng`` (mặc định ``vi``).
        voice: mã giọng đọc (``nam``/``nu``/``espeak``).
        volume: âm lượng phát file WAV, 0..1 (mặc định :data:`ALERT_VOLUME`).
        speed: tốc độ đọc so với bản thu gốc, 0,5..1,0 (mặc định
            :data:`voice_library.DEFAULT_SPEECH_SPEED`). Đổi tốc độ làm WAV
            phải dựng lại, nên tên file WAV mang theo tốc độ.
        espeak_runner: hàm ``(text, out_path) -> None`` sinh WAV. Tiêm được để
            test không cần ``espeak-ng``; ``None`` = :func:`run_espeak`.
        clock: hàm trả thời gian (giây), như ``presence.py``/``state.py``.
            Mặc định ``time.monotonic``; test tiêm bộ đếm giả.
        logger: logger dùng để ghi; ``None`` = logger của module.

    Attributes:
        available: ``True`` khi có controller, tức loa dùng được.
    """

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
        #: Âm lượng gửi đi khi phát câu nói. Kẹp vào khoảng hợp lệ thay vì ném
        #: lỗi: giá trị lạ chỉ làm tiếng nhỏ/to hơn, không nên chặn khởi động.
        self._volume = normalise_volume(volume, ALERT_VOLUME)
        #: Tốc độ đọc. Bản WAV phải dựng lại khi đổi, nên giá trị này nằm trong
        #: tên file (xem :meth:`_voice_wav_path`).
        self._speed = normalise_speed(speed)
        #: Giọng đang chọn. Đổi được lúc chạy qua :meth:`set_voice` (dashboard);
        #: giá trị này được đọc lại từ ``voice.json`` mỗi lần :meth:`prepare`
        #: hoặc đổi, nên khởi động lại vẫn nhớ lựa chọn.
        self._voice = normalise_voice(voice)
        #: Đường dẫn WAV đã sinh **thành công**; khóa là tên loại cảnh báo.
        self._wav_paths: dict[str, Path] = {}
        #: File nguồn tương ứng với từng WAV ở ``_wav_paths`` — dùng để biết
        #: bản thu đã đổi hay chưa khi người dùng đổi giọng giữa chừng.
        self._wav_sources: dict[str, Path] = {}
        #: ``True`` khi ``prepare`` đã xong trọn vẹn (không sinh lại nữa).
        self._prepared = False
        #: Lý do gần nhất khiến ``prepare`` không sinh được giọng đọc.
        self._prepare_error: str | None = None
        #: Giọng **thực tế** đang dùng cho mỗi câu, khi nó khác ``self._voice``
        #: (ví dụ chọn giọng nam nhưng thư mục trống nên rơi về giọng máy).
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
        """File WAV sẽ phát cho câu ``kind``; ``None`` nếu chưa có.

        Chỉ trả file **đã chuẩn bị xong** (``prepare`` chạy thành công), nên
        gọi sau ``prepare`` là thấy đúng thứ ``alert`` sẽ dùng. Dùng cho
        ``speak-test`` in bảng nguồn phát và cho chẩn đoán trên dashboard.
        """
        path = self._wav_paths.get(kind)
        if path is None:
            return None
        return path

    def speak_tone_now(self, kind: str | None = None) -> AlertOutcome:
        """Phát **tiếng bíp** ngay, bỏ qua mọi bước chuẩn bị giọng đọc.

        Dùng cho ``speak-test --tone``: đường này không cần ffmpeg và không
        cần bản thu, nên nó tách được "loa không nhận backchannel" khỏi "file
        giọng đọc hỏng" — hai nguyên nhân có cách sửa khác hẳn nhau.

        Không coi ``tone_fallback`` là điều kiện: người gọi đã chủ động xin
        tiếng bíp. Không bao giờ ném lỗi.
        """
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
        except Exception:  # noqa: BLE001 - thuộc tính hỏng không được giết lệnh
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
        except Exception as exc:  # noqa: BLE001 - lỗi loa không được ném ra ngoài
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
        """Tình trạng giọng đang dùng + mọi giọng có sẵn, cho dashboard.

        Trả về đủ để giao diện hiện được lựa chọn **và** cảnh báo mà không
        phải thử phát: giọng nào có đủ bản thu, câu nào còn thiếu, và câu nào
        đang thật sự phải rơi về giọng khác.
        """
        return {
            "voice": self._voice,
            "volume": self._volume,
            "speed": self._speed,
            "voices": available_voices(self._audio_dir, ALERT_KINDS),
            "fallbacks": dict(self._fallback_notes),
            "error": self._prepare_error,
        }

    def set_voice(self, voice: str) -> dict[str, Any]:
        """Đổi giọng đang dùng và dựng lại file phát; trả :meth:`voice_report`.

        Lựa chọn được ghi xuống ``voice.json`` để lần chạy sau vẫn nhớ. Nếu
        ghi hỏng, giọng mới **vẫn có hiệu lực trong phiên này** — mất một tệp
        cấu hình không đáng để người dùng bấm mà không thấy gì đổi.

        Không bao giờ ném lỗi: dashboard bấm đổi giọng không được làm sập
        vòng lặp giám sát.
        """
        new_voice = normalise_voice(voice)
        if new_voice == self._voice and self._prepared:
            return self.voice_report()
        self._voice = new_voice
        try:
            save_voice(self._audio_dir, new_voice)
        except VoiceClipError as exc:
            self._logger.warning(
                "Đã đổi sang %s nhưng chưa lưu được lựa chọn: %s",
                new_voice,
                exc,
            )
        # Dựng lại từ đầu: file WAV của giọng cũ không dùng được cho giọng mới.
        self._wav_paths.clear()
        self._wav_sources.clear()
        self._fallback_notes.clear()
        self._prepared = False
        self._prepare_error = None
        self.prepare()
        return self.voice_report()

    def set_speed(self, speed: float) -> dict[str, Any]:
        """Đổi tốc độ đọc và dựng lại WAV; trả :meth:`voice_report`.

        Không lưu xuống đĩa: tốc độ là tham số của người triển khai (đặt trong
        ``config.yaml``), không phải lựa chọn trên dashboard như giọng đọc.
        Không bao giờ ném lỗi vì ``speak-test --speed`` gọi thẳng hàm này.
        """
        new_speed = normalise_speed(speed, self._speed)
        if new_speed == self._speed and self._prepared:
            return self.voice_report()
        self._speed = new_speed
        # Tốc độ nằm trong nội dung WAV nên mọi bản cũ đều phải dựng lại.
        self._wav_paths.clear()
        self._wav_sources.clear()
        self._fallback_notes.clear()
        self._prepared = False
        self._prepare_error = None
        self.prepare()
        return self.voice_report()

    def set_volume(self, volume: float) -> dict[str, Any]:
        """Đổi âm lượng phát; trả :meth:`voice_report`.

        Âm lượng chỉ dùng lúc gửi đi nên **không** phải dựng lại WAV.
        """
        self._volume = normalise_volume(volume, self._volume)
        return self.voice_report()

    def audio_path(self, kind: str) -> Path:
        """Đường dẫn file WAV của loại cảnh báo ``kind`` (chưa chắc đã tồn tại)."""
        return self._audio_dir / f"{kind}.wav"

    # -- sinh giọng đọc một lần -----------------------------------------
    def prepare(self) -> None:
        """Sinh file WAV cho cả ba câu vào ``audio_dir`` — **một lần**.

        Gọi lần thứ hai (sau khi lần đầu thành công) **không** sinh lại và
        **không** gọi ``espeak_runner`` thêm lần nào; đó là điều spec §5.15
        yêu cầu ("sinh lại mỗi lần cảnh báo là lãng phí và gây trễ").

        Không bao giờ ném lỗi: thiếu ``espeak-ng`` hay lỗi I/O chỉ ghi log;
        khi đó các lời gọi :meth:`alert` rơi về tiếng bíp nếu
        ``tone_fallback`` bật. Lần gọi sau sẽ thử lại những câu còn thiếu
        (đường "cấu hình đổi" của spec).
        """
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
            # Ưu tiên 1: bản thu giọng người của giọng đang chọn. Đây là
            # đường chính — đo bằng STOI qua chuỗi camera cho 0,958–0,972 so
            # với 0,929–0,945 của espeak-ng, tức dễ nghe hơn hẳn.
            if self._prepare_voice_clip(kind):
                continue
            # Ưu tiên 2: giọng máy, để chọn giọng nam/nữ mà thư mục trống
            # thì vẫn có tiếng nói thay vì chỉ bíp.
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
        """Dùng bản thu của giọng đang chọn cho câu ``kind``; ``True`` nếu xong.

        Đổi bản thu sang WAV một lần rồi tái sử dụng. File đích nằm ngay trong
        ``audio_dir`` và **mang tên giọng** (``phone.nam.wav``) để đổi giọng
        không ghi đè lên bản của giọng kia.
        """
        if self._voice not in VOICE_DIRS:
            return False
        source = find_clip(self._audio_dir, self._voice, kind)
        if source is None:
            return False
        target = self._voice_wav_path(kind, self._voice)
        # Bản WAV đã đổi từ đúng file nguồn này rồi thì dùng lại. So cả mốc
        # sửa để người dùng thay file MP3 thì lần khởi động sau nhận bản mới.
        if self._wav_is_current(target, source):
            self._wav_paths[kind] = target
            self._wav_sources[kind] = source
            self._logger.info(
                "Dùng lại bản thu %s cho cảnh báo '%s' tại '%s'.",
                describe_clip(source),
                KIND_LABELS[kind],
                target,
            )
            return True
        try:
            prepare_clip(source, target, speed=self._speed)
        except VoiceClipError as exc:
            self._logger.warning(
                "Không dùng được bản thu '%s' cho cảnh báo '%s': %s",
                describe_clip(source),
                KIND_LABELS[kind],
                exc,
            )
            return False
        self._wav_paths[kind] = target
        self._wav_sources[kind] = source
        self._logger.info(
            "Đã đổi bản thu %s sang WAV cho cảnh báo '%s' tại '%s'.",
            describe_clip(source),
            KIND_LABELS[kind],
            target,
        )
        return True

    def _prepare_espeak_clip(self, kind: str) -> bool:
        """Sinh câu ``kind`` bằng ``espeak-ng`` (đường dự phòng); ``True`` nếu xong."""
        target = self.audio_path(kind)
        # Dùng lại file WAV đã sinh ở lần chạy trước: đó chính là ý của
        # spec §5.15 ("sinh một lần"), và nó cứu trường hợp máy đã có
        # file nhưng thiếu espeak-ng (ví dụ file được copy sang Pi) — nếu
        # sinh lại vô điều kiện thì loa mất giọng nói dù file vẫn còn.
        if _wav_is_usable(target):
            self._wav_paths[kind] = target
            self._wav_sources.pop(kind, None)
            self._logger.info(
                "Dùng lại giọng máy có sẵn cho cảnh báo '%s' tại '%s'.",
                KIND_LABELS[kind],
                target,
            )
            if self._voice in VOICE_DIRS:
                # Người dùng chọn giọng nam/nữ mà câu này không có bản thu:
                # nói rõ để dashboard hiện được lý do, thay vì im lặng đổi giọng.
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
        """File WAV phát được của bản thu ``voice`` cho câu ``kind``.

        Tên file mang theo tốc độ (``phone.nam.s90.wav``) vì tốc độ nằm trong
        nội dung WAV: đổi tốc độ mà dùng lại bản cũ thì đổi cấu hình không có
        tác dụng. Nhờ vậy cũng so được "bản này đã dựng ở tốc độ nào".
        """
        tag = f"{round(self._speed * 100):02d}"
        return self._audio_dir / f"{kind}.{voice}.s{tag}.wav"

    def _wav_is_current(self, target: Path, source: Path) -> bool:
        """Bản WAV ``target`` đã đổi từ ``source`` và còn mới hơn nó chưa."""
        if not _wav_is_usable(target):
            return False
        try:
            return target.stat().st_mtime >= source.stat().st_mtime
        except OSError:
            return False

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
        """Chọn **một** loại theo :data:`PRIORITY` rồi phát nó.

        Args:
            kinds: các loại đang đủ điều kiện ở thời điểm này (thường là kết
                quả của ``schedule.should_alert`` hoặc tập sự kiện của khung).
                Giá trị lạ bị bỏ qua; không có loại nào hợp lệ thì trả
                ``mode="skipped"`` kèm lý do.
            now: mốc thời gian để ghi vào kết quả/log; ``None`` thì đọc
                ``clock``. **Chỉ để ghi**, không dùng để chặn phát — cooldown
                thuộc ``schedule``.
            muted: ``True`` khi dashboard đang tắt tiếng. Spec v3 §3.3: tắt
                tiếng thì **không phát ra loa** nhưng sự kiện vẫn được ghi.
                Trả ``mode="skipped"``, ``error=None`` **trước khi** chạm
                controller (kể cả trước nhánh ``busy``): tắt tiếng là lựa
                chọn của người dùng, không phải lỗi loa.

        Returns:
            :class:`AlertOutcome`. Không bao giờ ném lỗi, kể cả khi loa chết.
        """
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
            # Spec v3 §3.3: dashboard tắt tiếng thì không phát ra loa nhưng
            # vẫn ghi sự kiện. Chặn **trước** mọi lần chạm ``controller`` —
            # kể cả nhánh ``busy`` — để tắt tiếng không bị báo thành lỗi loa.
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
        except Exception:  # noqa: BLE001 - thuộc tính hỏng không được giết vòng lặp
            busy = False
        if busy:
            # Spec §3.4: bỏ lần phát mới, không xếp hàng ("mất cảnh báo còn
            # hơn trễ 30 s").
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
            # Đúng ca spec §5.15 mô tả: máy thiếu ffmpeg nên chưa phát được
            # file. Không được im lặng — rơi về tiếng bíp. Lỗi vẫn được ghi
            # vào ``error`` để tầng gọi biết lần này câu tiếng Việt **không**
            # ra loa, kể cả khi tiếng bíp đã phát thành công.
            return self._emit_tone(
                kind,
                text,
                moment,
                why=f"Không phát được file giọng đọc ({exc}).",
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - lỗi loa không được ném ra ngoài
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
        except Exception as exc:  # noqa: BLE001 - lỗi loa không được ném ra ngoài
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
            # ``alert_many("phone")`` là hiểu nhầm dễ gặp; đừng lặng lẽ lặp
            # từng ký tự.
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
        # ``.get`` chứ không ``[]``: lỗi loa phải báo được **kể cả** khi lời
        # gọi không gắn với một câu cảnh báo cụ thể (``speak-test --tone``).
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
        """Dựng alerter từ :class:`posture_monitor.config.Config`.

        Đọc mục ``speaker_alert`` (``say``, ``tone_fallback``, ``audio_dir``,
        ``language``, ``voice``) nếu có, và dựng controller bằng
        :meth:`SpeakController.from_config`. Loa **tắt hoặc thiếu cấu hình**
        không phải lỗi khởi động: alerter vẫn dựng được với ``controller=None``
        (``available`` là ``False``) để vòng lặp chạy tiếp và ghi log.

        Giọng đang dùng lấy theo thứ tự **ưu tiên giảm dần**:

        1. ``voice`` truyền thẳng vào hàm (dùng cho ``speak-test --voice``):
           người gõ cờ muốn thử đúng giọng đó, không muốn bị tệp lưu chen vào.
        2. ``audio_dir/voice.json`` — lựa chọn người dùng vừa bấm trên
           dashboard, nên nó thắng ``config.yaml``.
        3. ``speaker_alert.voice`` trong cấu hình (giá trị khởi tạo).
        4. :data:`DEFAULT_VOICE`.
        """
        #: Khóa nào được người gọi truyền tường minh thì giữ nguyên; chỉ những
        #: khóa còn thiếu mới lấy từ cấu hình. ``explicit_voice`` quyết định
        #: bước đọc ``voice.json`` bên dưới có được chạy hay không.
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
            kwargs["voice"] = load_voice(audio_dir, normalise_voice(kwargs["voice"]))

        controller: Any = None
        if "controller" not in kwargs:
            from .camera_audio import CameraAudioError

            try:
                controller = SpeakController.from_config(config)
            except CameraAudioError as exc:
                logger.info("Chưa bật loa camera nên cảnh báo chỉ ghi sự kiện: %s", exc)
        return cls(kwargs.pop("controller", controller), **kwargs)


def _section_value(section: Any, name: str, default: Any = None) -> Any:
    """Đọc khóa từ dataclass **hoặc** dict (cấu hình nạp tay trong test)."""
    if section is None:
        return default
    if isinstance(section, Mapping):
        return section.get(name, default)
    return getattr(section, name, default)


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
    "MAX_ALERT_VOLUME",
    "MIN_ALERT_VOLUME",
    "MODE_SKIPPED",
    "MODE_SPEECH",
    "MODE_TONE",
    "PRIORITY",
    "SpeakerAlerter",
    "run_espeak",
]
