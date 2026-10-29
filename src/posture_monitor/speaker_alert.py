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

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .camera_audio import CameraAudioUnavailable, SpeakController
from .logging_setup import get_logger
from .schedule import KIND_LABELS, KIND_LEAVE_FRAME, KIND_PHONE, KIND_STRANGER

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

#: Âm lượng khi phát file WAV. 1.0 là mức camera nhận nguyên bản; muốn nhỏ hơn
#: thì chỉnh ở loa của camera, không chỉnh ở đây.
ALERT_VOLUME = 1.0

#: Chương trình sinh giọng đọc và giọng tiếng Việt (spec §5.15).
ESPEAK_BINARY = "espeak-ng"
DEFAULT_LANGUAGE = "vi"

#: Chặn trên thời gian chạy ``espeak-ng`` để một lần treo không giữ mãi bước
#: khởi động.
ESPEAK_TIMEOUT_S = 30.0


def run_espeak(text: str, out_path: str, *, language: str = DEFAULT_LANGUAGE) -> None:
    """Sinh một file WAV từ ``text`` bằng ``espeak-ng`` (đường mặc định).

    Tách thành hàm công khai để test (và người triển khai) thay được bằng
    ``espeak_runner`` khác mà không phải cài ``espeak-ng``.

    Raises:
        RuntimeError: mọi lỗi đều đổi thành tiếng Việt đọc được — thiếu
            ``espeak-ng``, mã trả về khác 0, hoặc chạy quá lâu.
    """
    try:
        subprocess.run(
            [ESPEAK_BINARY, "-v", language, "-w", out_path, text],
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
    """

    kind: str | None
    text: str | None
    spoken: bool
    mode: str
    reason: str
    error: str | None = None
    at: float = 0.0

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
        #: Đường dẫn WAV đã sinh **thành công**; khóa là tên loại cảnh báo.
        self._wav_paths: dict[str, Path] = {}
        #: ``True`` khi ``prepare`` đã xong trọn vẹn (không sinh lại nữa).
        self._prepared = False
        #: Lý do gần nhất khiến ``prepare`` không sinh được giọng đọc.
        self._prepare_error: str | None = None

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
            target = self.audio_path(kind)
            try:
                self._run_espeak(ALERT_TEXT[kind], str(target))
            except Exception as exc:  # noqa: BLE001 - thiếu TTS không được crash
                missing.append(kind)
                self._logger.warning(
                    "Không sinh được giọng đọc cho cảnh báo '%s': %s: %s",
                    KIND_LABELS[kind],
                    type(exc).__name__,
                    exc,
                )
                continue
            self._wav_paths[kind] = target
            self._logger.info(
                "Đã sinh giọng đọc cho cảnh báo '%s' tại '%s'.",
                KIND_LABELS[kind],
                target,
            )

        if missing:
            self._prepare_error = (
                "chưa sinh được giọng đọc cho "
                + ", ".join(KIND_LABELS[kind] for kind in missing)
            )
            self._log_prepare_failure()
            return

        self._prepare_error = None
        self._prepared = True

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
    def alert(self, kind: str, *, now: float | None = None) -> AlertOutcome:
        """Phát cảnh báo một loại. Tương đương ``alert_many([kind])``."""
        return self.alert_many((kind,), now=now)

    def alert_many(
        self, kinds: Iterable[str], *, now: float | None = None
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
            self._controller.speak_file(str(wav), ALERT_VOLUME)
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
    ) -> AlertOutcome:
        if kind is not None:
            self._logger.info(
                "Bỏ cảnh báo '%s': %s", KIND_LABELS[kind], reason
            )
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
        )

    def _failure(
        self, kind: str, text: str, moment: float, exc: BaseException
    ) -> AlertOutcome:
        """Lỗi loa: ghi log, trả ``error`` để tầng gọi ghi ``SPEAK_FAILED``."""
        error = f"{type(exc).__name__}: {exc}"
        self._logger.warning(
            "Phát cảnh báo '%s' ra loa camera thất bại (%s); ghi SPEAK_FAILED "
            "và tiếp tục chạy.",
            KIND_LABELS[kind],
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
        ``language``) nếu có, và dựng controller bằng
        :meth:`SpeakController.from_config`. Loa **tắt hoặc thiếu cấu hình**
        không phải lỗi khởi động: alerter vẫn dựng được với ``controller=None``
        (``available`` là ``False``) để vòng lặp chạy tiếp và ghi log.
        """
        section = getattr(config, "speaker_alert", None)
        for key, default in (
            ("say", True),
            ("tone_fallback", True),
            ("audio_dir", "data/audio"),
            ("language", DEFAULT_LANGUAGE),
        ):
            if key in kwargs:
                continue
            value = _section_value(section, key, default)
            kwargs[key] = default if value is None else value

        controller: Any = None
        if "controller" not in kwargs:
            from .camera_audio import CameraAudioError

            try:
                controller = SpeakController.from_config(config)
            except CameraAudioError as exc:
                logger.info(
                    "Chưa bật loa camera nên cảnh báo chỉ ghi sự kiện: %s", exc
                )
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
    "MODE_SKIPPED",
    "MODE_SPEECH",
    "MODE_TONE",
    "PRIORITY",
    "SpeakerAlerter",
    "run_espeak",
]
