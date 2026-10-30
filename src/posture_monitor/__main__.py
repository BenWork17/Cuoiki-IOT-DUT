"""Điểm vào dòng lệnh: ``python -m posture_monitor <lệnh>``.

Các lệnh theo spec v2 §7::

    python -m posture_monitor run [--config config.yaml] [--no-gpio] [--view front|side]
    python -m posture_monitor calibrate
    python -m posture_monitor replay video.mp4 [--no-gpio] [--save-report out.json]
    python -m posture_monitor benchmark [--seconds 60]

``run`` (mốc M1) mở camera, suy luận pose và vẽ 17 keypoint + xương lên khung
hình trực tiếp; bấm ``q`` hoặc ``Esc`` để thoát. Cờ ``--save-overlay`` lưu
**một** khung đã vẽ ra file ảnh rồi thoát, dùng để kiểm chứng trên máy không
có màn hình.

``calibrate`` thu khung ở tư thế chuẩn rồi ghi baseline ra ``calibration.json``;
``replay`` chạy pipeline trên một video có sẵn và xuất báo cáo JSON;
``benchmark`` đo FPS/độ trễ/nhiệt/RAM/throttle trên máy đích. Cả bốn lệnh đều
đã triển khai, nên không còn nhánh "chưa triển khai" nào.

Không in bất kỳ số liệu hiệu năng nào ngoài ``benchmark``: mọi chỉ số FPS/độ
trễ phải do ``benchmark`` sinh ra trên máy đích (spec §11.6).
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from . import __version__
from .capture import capture_from_config
from .config import ConfigError, load_config, redact_camera_source
from .logging_setup import setup_logging
from .schedule import KIND_LABELS
from .voice_library import VOICES

#: Tên cửa sổ xem trước của OpenCV.
WINDOW_NAME = "Giam sat hoc tap — bam q de thoat"

#: Phím thoát (mã ASCII của ``q`` và ``Esc``).
QUIT_KEYS = (ord("q"), ord("Q"), 27)

#: Số khung tối đa đọc khi chờ có người cho ``--save-overlay``. Camera mới mở
#: thường trả vài khung tối/sai phơi sáng; đọc vài khung giúp ảnh lưu ra đúng
#: cảnh hơn. Không phải ngưỡng nghiệp vụ nên để trong code.
SAVE_OVERLAY_MAX_FRAMES = 10

#: Ba câu cảnh báo mà ``speak-test`` phát thử, **đúng thứ tự** đọc ra loa.
#: Trùng với ``should_alert`` nhưng khai báo riêng để parser không phải kéo
#: module ``speaker_alert`` (và qua đó ``camera_audio``) chỉ để lấy danh sách.
SPEAK_TEST_KINDS = ("leave_frame", "phone", "stranger")

#: Nghỉ giữa hai câu khi phát thử. Loa camera phát hết câu rồi mới nhận câu
#: sau; không nghỉ thì câu trước bị cắt cụt và người nghe tưởng file hỏng.
SPEAK_TEST_GAP_S = 0.6


def build_parser() -> argparse.ArgumentParser:
    """Dựng parser cho toàn bộ CLI."""
    parser = argparse.ArgumentParser(
        prog="posture_monitor",
        description="Hệ thống giám sát tư thế học tập trên Raspberry Pi 4.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"posture_monitor {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Chạy giám sát trực tiếp từ camera.")
    run.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    run.add_argument(
        "--no-gpio",
        action="store_true",
        help="Không dùng GPIO thật; dùng phần cứng giả lập.",
    )
    run.add_argument(
        "--view",
        choices=("front", "side"),
        default=None,
        help="Ghi đè góc đặt camera trong cấu hình.",
    )
    run.add_argument(
        "--save-overlay",
        default=None,
        metavar="DUONG_DAN",
        help=(
            "Lưu một khung đã vẽ ra file ảnh rồi thoát (dùng để kiểm chứng "
            "khi không có màn hình). Ví dụ: --save-overlay frame.jpg"
        ),
    )
    run.add_argument(
        "--fps",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Ghi đè 'model.target_fps' (mặc định 5). Đo trên laptop: nguồn "
            "RTSP đọc nền chịu được tới ~15 FPS; tăng lên để xem mượt hơn, "
            "hạ xuống nếu CPU yếu."
        ),
    )
    run.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Mở cửa sổ xem trước của OpenCV. MẶC ĐỊNH KHÔNG MỞ: hình đã có "
            "trên dashboard web, còn cửa sổ thì cần màn hình thật (trên Pi qua "
            "xrdp nó ném lỗi Qt) và mỗi khung phải vẽ lại cùng xử lý sự kiện "
            "cửa sổ. Chỉ thêm cờ này khi ngồi ngay máy có màn hình."
        ),
    )
    run.add_argument(
        "--no-preview",
        action="store_true",
        help=(
            "Giữ cho tương thích: không mở cửa sổ xem trước. Đây đã là mặc "
            "định, nên cờ này không cần thiết nữa."
        ),
    )
    run.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    calibrate = subparsers.add_parser(
        "calibrate",
        help="Hiệu chỉnh tư thế chuẩn và lưu baseline (calibration.json).",
    )
    # Import muộn: hằng số mặc định nằm cùng module với logic hiệu chỉnh, để
    # đường dẫn mặc định chỉ có một nguồn sự thật.
    from .calibration import DEFAULT_PATH  # noqa: PLC0415 - chỉ cần ở đây

    calibrate.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    calibrate.add_argument(
        "--output",
        default=DEFAULT_PATH,
        metavar="DUONG_DAN",
        help=f"File baseline ghi ra (mặc định: {DEFAULT_PATH}).",
    )
    calibrate.add_argument(
        "--no-gpio",
        action="store_true",
        help=(
            "Chấp nhận cho đồng bộ với 'run'; calibrate không dùng GPIO nên "
            "cờ này là no-op."
        ),
    )
    calibrate.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    replay = subparsers.add_parser(
        "replay", help="Chạy lại trên video có sẵn và xuất báo cáo JSON."
    )
    replay.add_argument("video", help="Đường dẫn video (mp4/avi/mkv).")
    replay.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    replay.add_argument(
        "--no-gpio",
        action="store_true",
        help="Tương thích CLI chung; replay không dùng GPIO.",
    )
    replay.add_argument(
        "--save-report",
        default=None,
        metavar="DUONG_DAN",
        help="Ghi báo cáo JSON (UTF-8) ra file. Ví dụ: --save-report out.json",
    )
    replay.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    benchmark = subparsers.add_parser(
        "benchmark", help="Đo hiệu năng trên máy đích (spec §8)."
    )
    # Cờ dưới đây giữ đúng bộ cờ của ``python -m posture_monitor.benchmark``
    # để ``cmd_benchmark`` chuyển thẳng được sang ``benchmark.main``.
    benchmark.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="Thời lượng đo, giây (mặc định: 60).",
    )
    benchmark.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    benchmark.add_argument(
        "--source",
        default=None,
        metavar="NGUON",
        help=(
            "Ghi đè nguồn ảnh: usb:0 | picamera | file:anh.jpg | "
            "file:video.mp4. Trên Pi chưa có camera, dùng ảnh tĩnh."
        ),
    )
    benchmark.add_argument(
        "--json",
        default=None,
        metavar="DUONG_DAN",
        help="Ghi báo cáo JSON ra file (ngoài bảng in trên màn hình).",
    )
    benchmark.add_argument(
        "--profile",
        default=None,
        metavar="HO_SO",
        help=(
            "Hồ sơ đo: pose (mặc định) | pose_phone | pose_phone_face. "
            "Hồ sơ cần module/cấu hình chưa có sẽ bị từ chối rõ ràng, không "
            "đo thiếu model."
        ),
    )
    benchmark.add_argument(
        "--no-gpio",
        action="store_true",
        help="Tương thích CLI chung; benchmark không dùng GPIO.",
    )
    benchmark.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    speak_test = subparsers.add_parser(
        "speak-test",
        help="Phát thử giọng đọc ra loa camera rồi thoát (không mở camera).",
        description=(
            "Phát thử câu cảnh báo ra loa của camera IP qua RTSP backchannel. "
            "Lệnh này KHÔNG mở luồng hình, KHÔNG đụng GPIO và KHÔNG ghi DB, "
            "nên chạy được trong lúc 'run' đang chạy — miễn là loa rảnh. "
            "Dùng để kiểm tra âm thanh thật sự ra loa trước khi trình diễn."
        ),
    )
    speak_test.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    speak_test.add_argument(
        "--kind",
        choices=(*SPEAK_TEST_KINDS, "all"),
        default="all",
        help=(
            "Câu cần phát thử; 'all' (mặc định) phát lần lượt cả ba câu để "
            "nghe được câu nào còn thiếu bản thu."
        ),
    )
    speak_test.add_argument(
        "--voice",
        choices=VOICES,
        default=None,
        help=(
            "Ghi đè giọng cho riêng lần thử này (nam | nu | espeak). "
            "KHÔNG lưu vào data/audio/voice.json — lựa chọn trên dashboard "
            "giữ nguyên."
        ),
    )
    speak_test.add_argument(
        "--volume",
        type=float,
        default=None,
        metavar="0..1",
        help=(
            "Âm lượng gửi ra loa cho riêng lần thử này (mặc định lấy "
            "'speaker_alert.volume'). Hạ xuống 0.6–0.7 nếu loa nhỏ bị rè."
        ),
    )
    speak_test.add_argument(
        "--speed",
        type=float,
        default=None,
        metavar="0.5..1.0",
        help=(
            "Tốc độ đọc cho riêng lần thử này (mặc định lấy "
            "'speaker_alert.speed', thường là 0.9 = chậm lại 10 %). Chậm hơn "
            "thì giữ nguyên cao độ, không làm giọng trầm."
        ),
    )
    speak_test.add_argument(
        "--tone",
        action="store_true",
        help=(
            "Phát tiếng bíp thay vì câu nói. Đường này KHÔNG cần ffmpeg và "
            "không cần bản thu, nên dùng để tách 'loa không nhận backchannel' "
            "khỏi 'file giọng đọc hỏng'."
        ),
    )
    speak_test.add_argument(
        "--list",
        action="store_true",
        help="Chỉ liệt kê giọng/câu đang có rồi thoát, không phát gì.",
    )
    speak_test.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    return parser


def _print_status(
    config, hardware, source, view: str, backend: str, show_preview: bool = False
) -> None:
    """In khối trạng thái khởi động cho người dùng.

    ``show_preview`` phải phản ánh đúng việc cửa sổ OpenCV có mở hay không:
    in "bấm q trong cửa sổ" khi mặc định không có cửa sổ là chỉ dẫn sai, người
    dùng sẽ ngồi chờ một cửa sổ không bao giờ hiện.
    """
    camera_cfg = config.camera
    print()
    print("=" * 60)
    print("  GIÁM SÁT HỌC TẬP — TRẠNG THÁI KHỞI ĐỘNG")
    print("=" * 60)
    print(f"  Cấu hình      : {config.path or '(mặc định)'}")
    print(f"  Nguồn camera  : {redact_camera_source(camera_cfg.source)}")
    print(f"  Độ phân giải  : {camera_cfg.width}x{camera_cfg.height}, view={view}")
    print(
        f"  Model         : {config.model.name} ({backend}), imgsz={config.model.imgsz}"
    )

    if source is None:
        print("  Camera        : KHÔNG MỞ ĐƯỢC (xem log phía trên)")
    else:
        print(f"  Camera        : đã mở (backend={source.backend})")

    state = getattr(hardware, "state", "?")
    print(f"  Phần cứng     : {type(hardware).__name__}, trạng thái giả={state}")
    print(
        "  Ngưỡng chính  : "
        f"head_down={config.thresholds.head_down_ratio}, "
        f"too_close={config.thresholds.too_close_ratio}, "
        f"shoulder_tilt={config.thresholds.shoulder_tilt_deg}°"
    )
    print(
        "  Thời gian     : "
        f"bad_hold={config.timing.bad_hold_s}s, "
        f"good_hold={config.timing.good_hold_s}s, "
        f"cooldown={config.timing.alert_cooldown_s}s"
    )
    print("-" * 60)
    if show_preview:
        print("  Vẽ xương trong cửa sổ OpenCV; bấm q hoặc Esc để thoát.")
    else:
        print("  Không mở cửa sổ OpenCV. Xem hình trực tiếp trên dashboard web;")
        print("  dừng bằng Ctrl+C. (Muốn mở cửa sổ: thêm cờ --preview.)")
    print("  Ba tín hiệu: có mặt / dùng điện thoại / đúng người.")
    session_cfg = getattr(config, "session", None)
    if session_cfg is not None and not getattr(session_cfg, "auto_start", False):
        print("-" * 60)
        print(
            "  Phiên học      : TẮT cho tới khi bấm “Bắt đầu học” trên dashboard web."
        )
        print(
            f"                   Model AI chỉ chạy trong phiên "
            f"(mặc định {getattr(session_cfg, 'default_minutes', 60)} phút)."
        )
        print("                   Ngoài phiên vẫn xem camera và nhận diện khuôn mặt.")
    print("=" * 60)
    print()


def _save_one_overlay(estimator, source, config, target: Path, logger) -> int:
    """Lưu **một** khung đã vẽ ra ``target`` rồi trả mã thoát.

    Đọc tối đa :data:`SAVE_OVERLAY_MAX_FRAMES` khung để tránh khung đầu tiên
    còn tối, nhưng chỉ vẽ và lưu khung đọc được sau cùng. Không có ai trong
    khung là trạng thái hợp lệ, không phải lỗi: ghi ``persons=0``.
    """
    from .overlay import draw_pose  # noqa: PLC0415 - chỉ nhánh này cần

    frame = None
    for _ in range(SAVE_OVERLAY_MAX_FRAMES):
        candidate = source.read()
        if candidate is None:
            break
        frame = candidate

    if frame is None:
        logger.error("Không đọc được khung nào từ camera; không lưu được %s.", target)
        return 1

    pose = estimator.detect(frame)
    persons = estimator.last_person_count
    if pose is None:
        drawn = frame.copy()
    else:
        drawn = draw_pose(frame, pose.xy, pose.conf, config.model.kp_conf_min)

    target.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target), drawn):
        logger.error(
            "Không ghi được file ảnh '%s' (kiểm tra phần mở rộng và quyền ghi).",
            target,
        )
        return 1

    print(f"Đã lưu khung đã vẽ: {target.resolve()}")
    print(f"persons={persons}")
    if persons == 0:
        print(
            "persons=0: không có người trong khung ở thời điểm chụp — đây là "
            "trạng thái hợp lệ, không phải lỗi code."
        )
    return 0


class _Dashboard:
    """Bộ ba state + storage + app Flask chạy nền cho dashboard web.

    Chỉ dựng ở nhánh chạy dài của ``run`` (không dựng cho ``--save-overlay``):
    web chỉ đọc :class:`~posture_monitor.web.DashboardState` mà vòng lặp ghi,
    **không** mở camera và không nhận ``source`` — nhờ vậy hai bên không tranh
    nhau thiết bị.

    ``start()`` đẩy server vào một luồng ``daemon`` để lỗi cổng bận (do
    ``_serve_web`` nuốt) không làm chết vòng lặp giám sát.
    """

    def __init__(self, config, logger) -> None:
        # Import muộn: chỉ nhánh chạy dài cần Flask.
        from .storage import Storage  # noqa: PLC0415
        from .web import DashboardState, create_app  # noqa: PLC0415

        self.config = config
        self.logger = logger
        self.state = DashboardState()
        self.storage = Storage(config)
        self.storage.open()
        self.people = _create_people_service(config, logger)
        # Phiên học: dựng **một lần** rồi tiêm cho cả vòng lặp lẫn web. Nút
        # Bắt đầu trên dashboard phải điều khiển đúng đối tượng mà vòng lặp
        # đọc mỗi khung; hai đối tượng riêng thì bấm nút không có tác dụng.
        self.study_session = _create_study_session(config, logger)
        # Loa cảnh báo dựng **một lần** ở đây rồi tiêm cho cả vòng lặp lẫn web:
        # hai bên phải thấy cùng một đối tượng, vì chọn giọng trên dashboard
        # có hiệu lực tức thì cho lần cảnh báo kế tiếp. Dựng lỗi không làm sập
        # dashboard — ``_create_speaker`` trả ``None`` và chỉ ghi log.
        self.speaker = _create_speaker(config, logger)
        try:
            self.app = create_app(
                config,
                state=self.state,
                storage=self.storage,
                people=self.people,
                speaker=self.speaker,
                study_session=self.study_session,
            )
        except BaseException:
            # Không để rò kết nối ghi hoặc luồng thu mẫu khi dựng app hỏng.
            self.storage.close()
            if self.people is not None:
                self.people.close()
            raise
        self.thread = threading.Thread(
            target=_serve_web,
            args=(self.app, config, logger),
            name="dashboard-web",
            daemon=True,
        )

    def start(self) -> None:
        """Chạy server web ở luồng nền (không chặn vòng lặp giám sát)."""
        self.thread.start()


def _create_study_session(config, logger):
    """Dựng :class:`~posture_monitor.study_session.StudySession` từ cấu hình.

    Không bao giờ ném: một ``session.default_minutes`` sai đã bị ``config.py``
    chặn lúc nạp, còn lỗi bất ngờ ở đây chỉ làm mất tính năng phiên học —
    dashboard và vòng lặp vẫn chạy (spec §11.3).

    ``auto_start`` mặc định ``False``: đúng yêu cầu "bấm bắt đầu học tập thì
    mới dùng các model AI". Đặt ``true`` chỉ khi demo, vì khi đó model chạy
    suốt thời gian tiến trình còn sống.
    """
    try:
        from .study_session import StudySession  # noqa: PLC0415

        session_cfg = getattr(config, "session", None)
        session = StudySession(
            default_minutes=int(getattr(session_cfg, "default_minutes", 60))
        )
        if bool(getattr(session_cfg, "auto_start", False)):
            snapshot = session.start()
            logger.info(
                "Tự động vào phiên học (%s phút, 'session.auto_start: true').",
                snapshot.minutes,
            )
        return session
    except Exception as exc:  # noqa: BLE001 - spec §11.3
        logger.warning(
            "Không dựng được phiên học (%s); nút Bắt đầu/Dừng sẽ không dùng "
            "được và model AI vẫn chạy như bản cũ.",
            exc,
        )
        return None


def _create_people_service(config, logger):
    """Dựng :class:`~posture_monitor.people_service.PeopleService` **thật**.

    Trả ``None`` — và dashboard chạy như trước — khi ``face.enabled`` tắt.
    Đó là mặc định của ``config.yaml``: chưa đo ``match_threshold`` thì tính
    năng nhận diện không được chạy (spec §5.13). Bật cờ đó lên thì cả chín
    route ``/api/people*``, ``/api/enroll*``, ``/api/select``,
    ``/api/schedule``, ``/api/signals`` mới có dịch vụ thật để gọi.

    Hàm **không bao giờ ném**: thiếu model hay thư mục kho chỉ là cảnh báo,
    dashboard và vòng lặp giám sát vẫn phải chạy (spec §11.3).

    ``FaceRecognizer`` nạp model ở lần dùng đầu, nên dựng đối tượng ở đây
    không cần tệp ``yunet.onnx``/``sface.onnx`` có mặt.
    """
    face = getattr(config, "face", None)
    if face is None or not getattr(face, "enabled", False):
        return None
    try:
        from .faces import FaceRecognizer, FaceStore  # noqa: PLC0415
        from .people_service import PeopleService  # noqa: PLC0415

        # ``face.store_path`` trỏ tới TỆP kho; ``FaceStore`` nhận thư mục.
        store_path = Path(face.store_path)
        store_dir = store_path.parent if str(store_path.parent) else Path(".")
        store = FaceStore(store_dir)
        recognizer = FaceRecognizer(
            face.detector,
            face.recognizer,
            score_threshold=float(getattr(face, "score_threshold", 0.9)),
        )
        service = PeopleService(
            store,
            recognizer,
            threshold=face.match_threshold,
            step_s=float(face.enroll_step_s),
            samples_needed=int(face.enroll_min_samples),
            schedule=getattr(config, "schedule", None),
            logger=logger,
        )
        service.set_processor(
            _build_face_processor(
                recognizer,
                face,
                logger,
                skip_gate=service.is_enrolling,
                note_box=service.note_face_box,
            )
        )
        return service
    except Exception:  # noqa: BLE001 - thiếu model kho không được giết dashboard
        logger.exception(
            "Không dựng được dịch vụ người học; dashboard vẫn chạy nhưng các "
            "tính năng người học sẽ trả 503."
        )
        return None


def _build_face_processor(recognizer, face, logger, *, skip_gate=None, note_box=None):
    """Đóng gói đường ống khuôn mặt **thật** cho :meth:`PeopleService.set_processor`.

    Ba việc:

    1. **Cổng nhịp ``face.interval_s``.** Hàm được gọi mỗi khung (5–6 FPS)
       nhưng YuNet + SFace tốn 86,1 ms/lượt (§4.2), nên lượt bị chặn trả
       :data:`~posture_monitor.people_service.OBSERVATION_SKIPPED` — **không**
       trả ``None``, vì ``None`` nghĩa là "đã nhìn, không thấy mặt" và sẽ ghi
       đè danh tính vừa nhận ra.
    2. **Phát hiện rồi trích embedding trên khung gốc**, dùng chung một ảnh
       cho cả hai bước nên toạ độ hộp mặt nhất quán, không cần ánh xạ ngược.
       Không thấy mặt → ``None`` (UNKNOWN, đúng nghĩa). Lỗi model →
       ``OBSERVATION_SKIPPED`` kèm cảnh báo: lỗi không phải "vắng mặt".
    3. **Báo hộp mặt ra ngoài** qua ``note_box`` (thường là
       ``PeopleService.note_face_box``). ``processor`` chỉ được trả **một**
       giá trị — embedding — nên hộp phải đi kênh phụ. Thiếu bước này thì
       không lớp hiển thị nào biết khuôn mặt nằm ở đâu, dù lượt detect vừa
       tìm ra nó.

    **Ngoại lệ của cổng: đang đăng ký khuôn mặt thì detect MỖI khung.**
    ``skip_gate`` (thường là ``PeopleService.is_enrolling``) được hỏi **trước**
    phép so cổng; trả True thì chạy detect ngay và vẫn cập nhật nhịp, để sau
    khi đăng ký xong cổng không bị "nợ" một lượt. Lý do là đo thật: cửa sổ
    đăng ký chỉ dài ``len(steps) * step_s`` = 7,5 s và mỗi bước chỉ nhận một
    mẫu, nên hai lần trượt detect rơi đúng nhịp cổng 2 s là đủ làm phiên thất
    bại. Bảng đo (5 FPS, ``samples_needed=3``, ``step_s=1.5``, kết quả
    ``(state, số mẫu, giây)``)::

        kịch bản                          có cổng 2 s        bỏ cổng
        không rơi khung nào              ('done', 3, 4.0)    ('done', 3, 3.0)
        miss 1 khung @2.0                ('done', 3, 6.0)    ('done', 3, 3.0)
        miss 2 khung @2.0,4.0            ('failed', 0, 7.6)  ('done', 3, 3.0)
        miss 2 khung @4.0,6.0            ('failed', 0, 7.6)  ('done', 3, 3.0)
        miss 2 khung ngoài nhịp @2.2,4.2 ('done', 3, 4.0)    ('done', 3, 3.0)

    ``failed`` kèm log "Đăng ký 'A' thất bại: chỉ có 2/3 mẫu."

    **Cố ý KHÔNG thu nhỏ khung về ``face.detect_width``.** Spec §5.13 yêu cầu
    bước thu nhỏ, nhưng đo thật (OpenCV 4.13.0, model và ảnh thật) cho thấy
    làm vậy sẽ mất mặt: ở ngưỡng detector mặc định ``0.9``, khung 704x576
    phát hiện 1 mặt, còn khung 320x262 phát hiện **0 mặt**; quét 11 mức ảnh
    nguồn thì ``@320 + 0.9`` không phát hiện được mặt nào. Thủ phạm là ngưỡng
    điểm ``score_threshold`` của YuNet, không phải ``min_face_px`` (mặt ở 320
    vẫn còn 68–74 px, trên mức lọc 40). Hạ ngưỡng xuống 0.6 sẽ bù lại được
    nhưng thêm mặt giả — mỗi cái là một vector rác vào bộ phân loại danh
    tính — và đổi ngưỡng ngoài ``config.yaml`` là điều spec §11 cấm. Vì vậy
    detect chạy trên khung gốc, đúng hành vi đã được chứng minh hoạt động;
    ``detect_width``/``clahe_enabled`` hiện vẫn chưa có người đọc.
    """
    from .people_service import OBSERVATION_SKIPPED  # noqa: PLC0415

    interval_s = float(getattr(face, "interval_s", 2.0) or 2.0)
    #: Lượt đầu phải luôn chạy: ``-inf`` bảo đảm ``now - last_at >= interval_s``.
    #: ``error`` là thông điệp lỗi của lần trước, để cảnh báo chỉ ghi khi lỗi
    #: **đổi**: thiếu/hỏng ``yunet.onnx`` là lỗi lặp lại mọi lượt, ghi hết sẽ
    #: ngập log. ``process_frame`` có cơ chế tương tự nhưng chỉ áp cho exception
    #: thoát ra ngoài ``processor``; ở đây lỗi được nuốt bên trong nên phải có
    #: bộ chống ngập riêng.
    state = {"last_at": -math.inf, "error": None}

    def _report_box(box):
        """Báo hộp mặt cho lớp hiển thị; lỗi ở đây **không** được giết detect.

        Hộp chỉ để vẽ. Một ``note_box`` hỏng (dịch vụ nửa vời, hộp lạ) không
        được biến lượt nhận diện đang tốt thành ``OBSERVATION_SKIPPED`` — làm
        vậy là đánh đổi danh tính (chức năng chính) lấy hình vẽ.
        """
        if note_box is None:
            return
        try:
            note_box(box)
        except Exception:  # noqa: BLE001 - spec §11.3
            pass

    def processor(frame):
        now = time.monotonic()
        if skip_gate is not None and skip_gate():
            # Đang đăng ký: bỏ cổng, detect mỗi khung; vẫn ghi nhịp để cổng
            # không "nợ" một lượt khi phiên kết thúc.
            state["last_at"] = now
        elif now - state["last_at"] < interval_s:
            return OBSERVATION_SKIPPED
        else:
            state["last_at"] = now
        try:
            prepared = frame  # KHÔNG thu nhỏ — xem docstring ở trên.
            faces = recognizer.detect(prepared)
            if not faces:
                state["error"] = None
                _report_box(None)
                return None
            largest = max(faces, key=lambda detected: detected.area)
            _report_box((largest.x, largest.y, largest.width, largest.height))
            embedding = recognizer.embedding(prepared, largest)
        except Exception as exc:  # noqa: BLE001 - lỗi model không phải vắng mặt
            message = str(exc)
            if message != state["error"]:
                state["error"] = message
                logger.warning(
                    "Không nhận diện được khuôn mặt ở khung này (%s); giữ "
                    "nguyên danh tính gần nhất.",
                    exc,
                )
            return OBSERVATION_SKIPPED
        state["error"] = None
        return embedding

    return processor


def _create_speaker(config, logger):
    """Dựng loa cảnh báo **một lần** cho cả vòng lặp và dashboard.

    Trả ``None`` khi không dựng được; spec §11.3: thiếu loa không được giết
    chương trình. ``prepare`` (đổi bản thu sang WAV, sinh giọng máy) chạy ở
    đây chứ không phải trong vòng lặp, để dashboard mở lên đã biết giọng nào
    có sẵn thay vì phải chờ khung đầu tiên.
    """
    from .speaker_alert import SpeakerAlerter  # noqa: PLC0415

    try:
        alerter = SpeakerAlerter.from_config(config)
    except Exception as exc:  # noqa: BLE001 - spec §11.3
        logger.warning(
            "Không dựng được loa cảnh báo (%s); cảnh báo trong giờ học chỉ "
            "được ghi log. Các chức năng khác vẫn chạy.",
            exc,
        )
        return None
    try:
        alerter.prepare()
    except Exception as exc:  # noqa: BLE001 - prepare đã nuốt lỗi, phòng hờ
        logger.warning("Chưa chuẩn bị được giọng đọc cảnh báo: %s", exc)
    return alerter


def _serve_web(app, config, logger) -> None:
    """Chạy dashboard web trong luồng nền; cổng bận chỉ là cảnh báo.

    Werkzeug báo cổng đã dùng bằng ``OSError`` (nhánh thường) hoặc
    ``SystemExit`` (khi tự gọi ``sys.exit``); cả hai đều không được làm chết
    tiến trình giám sát — mất dashboard còn hơn mất chức năng chính.
    """
    from .web import run_server  # noqa: PLC0415 - chỉ luồng này cần

    try:
        run_server(app, config)
    except (OSError, SystemExit) as exc:
        logger.warning(
            "Không mở được dashboard web (%s); chương trình vẫn giám sát. "
            "Kiểm tra 'web.host'/'web.port' và cổng đã bị chiếm.",
            exc,
        )


def _presence_state(state_text: str) -> str:
    """Đổi trạng thái của máy trạng thái sang tín hiệu presence của web.

    ``ABSENT`` là trạng thái duy nhất được coi là vắng; mọi trạng thái còn
    lại (GOOD/WARN/BAD) đều chứng minh còn người trong khung.
    """
    from . import state as state_mod  # noqa: PLC0415 - tránh vòng import
    from . import presence as presence_mod  # noqa: PLC0415

    if state_text == state_mod.STATE_ABSENT:
        return presence_mod.STATE_ABSENT
    return presence_mod.STATE_PRESENT


def _loc_nhan_tu_the(labels, enabled: bool):
    """Lọc nhãn tư thế khỏi tập nhãn sinh cảnh báo.

    Chủ đề của sản phẩm là theo dõi người học, không chấm điểm tư thế, nên
    khi ``enabled`` là ``False`` mọi nhãn tư thế (``HEAD_DOWN``, ``LEAN``,
    ``LOOK_AWAY``, ...) bị bỏ khỏi tập nhãn đi tiếp. ``classify`` vẫn được
    gọi như cũ — nhãn vẫn được tính để hiển thị/debug, chỉ là không sinh
    cảnh báo.

    ``ABSENT`` **luôn được giữ**, kể cả khi ``enabled`` là ``False``: cảnh
    báo "đi ra khỏi khung hình" phụ thuộc vào nó.
    """
    from .classifier import ABSENT  # noqa: PLC0415 - tránh vòng import

    if enabled:
        return frozenset(labels)
    return frozenset(label for label in labels if label == ABSENT)


def _warn_phone_threshold_mismatch(config, phone_ready: bool, logger) -> None:
    """Cảnh báo khi ngưỡng giữ điện thoại của web và của loa lệch nhau.

    Dashboard hiện "đang dùng điện thoại" theo ``phone.hold_s``, còn loa quyết
    định theo ``schedule.kinds.phone.hold_s``. Hai giá trị này là hai nguồn
    riêng, nên lệch nhau nghĩa là có khoảng thời gian web đã báo mà loa im —
    hiện tượng rất khó đoán ra vì cả hai đều "đúng" theo cấu hình của nó.

    Không tự sửa giá trị: người dùng có thể cố ý muốn web nhạy hơn loa. Chỉ
    ghi log để lý do hiện ra ngay từ lúc khởi động.
    """
    if not phone_ready:
        return
    try:
        dashboard_hold = float(config.phone.hold_s)
        kind = (config.schedule.kinds or {}).get("phone")
        speaker_hold = float(kind.hold_s) if kind is not None else None
    except (AttributeError, TypeError, ValueError):
        return
    if speaker_hold is None:
        return
    if dashboard_hold >= speaker_hold:
        return
    logger.warning(
        "Ngưỡng 'dùng điện thoại' đang lệch: dashboard báo ở %.1f giây "
        "(phone.hold_s) còn loa chỉ nhắc ở %.1f giây "
        "(schedule.kinds.phone.hold_s). Dùng điện thoại trong khoảng giữa hai "
        "mốc này sẽ thấy web báo mà loa không báo. Đặt hai giá trị bằng nhau "
        "trong config.yaml nếu muốn chúng khớp.",
        dashboard_hold,
        speaker_hold,
    )


def _monitor_loop(
    estimator,
    source,
    config,
    logger,
    state=None,
    storage=None,
    sensor=None,
    dispatcher=None,
    stream_enabled=False,
    people=None,
    speaker=None,
    show_preview=True,
    study_session=None,
    clock=None,
    wall_clock=None,
) -> int:
    """Vòng lặp giám sát: đọc khung → pose → đặc trưng → phân loại → trạng thái.

    Vẫn giữ nguyên hành vi xem trước cũ (cửa sổ OpenCV, phím ``q``/``Esc``,
    nhịp ``target_fps``, mã thoát); phần web chỉ là đích ghi thêm:

    - ``state.update(...)`` mỗi khung, ``state.set_frame(jpeg)`` **chỉ khi**
      ``stream_enabled`` (không mã hoá JPEG để vứt đi).
    - ``storage.record(update, distance_cm)`` mỗi khung.
    - ``dispatcher.dispatch(update)``; khi dashboard đang tắt tiếng, hoặc khi
      ``alerts.gpio_alert_enabled`` tắt (mặc định), đẩy bản sao có
      ``alerts=()`` để phần cứng không kêu, còn sự kiện vẫn được ghi vào DB
      và hiện trên web.
    - Yêu cầu hiệu chỉnh từ web **không** tự chạy ở đây: chỉ log hướng dẫn
      chạy lệnh ``calibrate`` rồi khởi động lại, vì hiệu chỉnh cần một cửa sổ
      thu riêng và người dùng phải ngồi đúng tư thế.
    - ``people`` (dịch vụ người học) nhận khung qua ``observe`` và tín hiệu
      presence/phone qua ``update_signals``; mỗi lời gọi được bọc ``try`` và
      chỉ **ghi log**, vì lỗi của tính năng mới không được làm chết camera.
    - Cảnh báo trong giờ học: ``PresenceTracker`` + ``PhoneSignal`` + tín
      hiệu danh tính của ``PeopleService`` → ``held`` →
      ``schedule.should_alert`` → ``SpeakerAlerter``. Toàn bộ khối nằm trong
      ``try`` vì cùng lý do trên.

    Args:
        show_preview: ``False`` thì không mở cửa sổ OpenCV. Máy chỉ xem qua
            dashboard nên tắt: cửa sổ cần màn hình thật và mỗi khung phải vẽ
            lại, trong khi ảnh đã có đường ``state.set_frame``.
        study_session: :class:`~posture_monitor.study_session.StudySession`
            dùng chung với web. ``None`` = bản cũ: model chạy suốt. Có đối
            tượng thì **chỉ khi phiên đang chạy** mới gọi ``estimator.detect``
            và dò điện thoại; ngoài phiên vẫn đọc camera và đẩy khung lên
            dashboard, nhưng bỏ qua pose/dò điện thoại/cảnh báo.
        clock: hàm trả giây đơn điệu (mặc định ``time.monotonic``). Dùng cho
            các bộ lọc thời gian (presence/phone), **không** dùng cho cổng
            giờ học.
        wall_clock: hàm trả ``datetime`` cho ``schedule.should_alert`` (mặc
            định ``datetime.now``). Hai đồng hồ khác nhau: ``held`` là khoảng
            thời gian, ``last_alert_at`` là datetime.
    """
    from .calibration import (  # noqa: PLC0415 - chỉ nhánh này cần
        DEFAULT_PATH,
        Baseline,
        CalibrationError,
    )
    from .calibration import load as load_calibration  # noqa: PLC0415
    from .classifier import LABEL_ORDER, classify  # noqa: PLC0415
    from .features import ALL_NAMES, extract  # noqa: PLC0415
    from .overlay import draw_detections, draw_pose  # noqa: PLC0415
    from .sensors import apply_distance  # noqa: PLC0415
    from .state import (  # noqa: PLC0415
        ALERT_EVENT_TYPE,
        EVENT_ALERT_END,
        EVENT_ALERT_START,
        EVENT_SPEAK_FAILED,
        EVENT_SPEAK_OK,
        PAUSED_MESSAGE,
        STATE_ABSENT,
        STATE_PAUSED,
        Event,
        Smoother,
        StateMachine,
        StateUpdate,
    )
    from .study_session import STATE_RUNNING  # noqa: PLC0415 - cổng phiên học
    from .web.app import LABEL_TEXT  # noqa: PLC0415 - nhãn tiếng Việt cho web

    interval = 1.0 / max(1, config.model.target_fps)
    view = config.camera.view
    kp_conf_min = config.model.kp_conf_min
    min_distance_cm = float(config.sensors.min_distance_cm)
    smooth_window_s = float(config.timing.smooth_window_s)

    try:
        baseline = load_calibration(DEFAULT_PATH)
        feature_baseline = baseline
    except FileNotFoundError:
        baseline = Baseline(
            values={name: None for name in ALL_NAMES},
            view=view,
            width=int(config.camera.width),
            height=int(config.camera.height),
            created_at="",
            frames=0,
        )
        feature_baseline = None
        logger.warning(
            "Chưa có %s: chạy không baseline, các nhãn phụ thuộc hiệu chỉnh "
            "(HEAD_DOWN/TOO_CLOSE/LEAN/HEAD_TILT/LOOK_AWAY) không được đánh "
            "giá. Chạy 'python -m posture_monitor calibrate' để hiệu chỉnh.",
            DEFAULT_PATH,
        )
    except CalibrationError as exc:
        baseline = Baseline(
            values={name: None for name in ALL_NAMES},
            view=view,
            width=int(config.camera.width),
            height=int(config.camera.height),
            created_at="",
            frames=0,
        )
        feature_baseline = None
        logger.warning(
            "%s hỏng (%s); chạy không baseline. Chạy lại lệnh 'calibrate'.",
            DEFAULT_PATH,
            exc,
        )

    smoother = Smoother(smooth_window_s)
    machine = StateMachine(config.timing)
    loop_start = time.monotonic()
    #: Nhãn đang có sự kiện cảnh báo đang mở, để dựng chữ ``alert`` cho web.
    active_alerts: dict[str, str] = {}

    #: Số lần dịch vụ người học ném lỗi; chỉ log lần đầu (xem vòng lặp).
    people_errors = 0

    # -- cảnh báo trong giờ học ------------------------------------------
    # Ba mảnh được nối ở đây, **một lần** ngoài vòng lặp: bộ lọc thời gian
    # (PresenceTracker), bộ phát hiện điện thoại (PhoneSignal) và loa
    # (SpeakerAlerter). Quyết định "lúc này có nên báo không" thuộc
    # ``schedule.should_alert`` — alerter không tự đếm cooldown lần nữa.
    #
    # ``presence.py`` cố ý không import ``config.py`` (ngưỡng là tham số
    # constructor), nên tầng này là nơi duy nhất đọc ``config.presence``.
    from . import schedule as schedule_mod  # noqa: PLC0415
    from .presence import (
        DEFAULT_ABSENT_HOLD_S,
        PresenceTracker,
    )  # noqa: PLC0415
    from .people_service import (
        IDENTITY_MISMATCH,
        PHONE_STATE_NONE,
        PHONE_STATE_USE,
    )  # noqa: PLC0415
    from .phone_detector import PhoneSignal  # noqa: PLC0415
    from .speaker_alert import SpeakerAlerter  # noqa: PLC0415

    alert_clock = clock if clock is not None else time.monotonic
    alert_wall_clock = wall_clock if wall_clock is not None else datetime.now
    schedule_cfg = getattr(config, "schedule", None)

    # Cổng phiên học: ``True``/``False`` ở khung trước, ``None`` khi chưa chạy
    # khung nào. So sánh với giá trị hiện tại để biết lúc nào vừa bật/tắt phiên
    # và phải xoá bộ đếm thời gian; ``None`` tách khung đầu tiên khỏi một lần
    # chuyển thật (chưa có phiên trước để mà "kết thúc").
    session_was_active: bool | None = None
    #: Số lần đọc trạng thái phiên thất bại; chỉ log lần đầu.
    session_errors = 0

    presence_tracker = None
    phone_signal = None
    speaker_alerter = None
    alert_errors = 0
    #: Số lần ghi sự kiện cảnh báo xuống DB thất bại; chỉ log lần đầu.
    event_errors = 0
    try:
        presence_cfg = getattr(config, "presence", None)
        presence_tracker = PresenceTracker(
            absent_hold_s=(
                presence_cfg.absent_grace_s
                if presence_cfg is not None
                else DEFAULT_ABSENT_HOLD_S
            ),
            kp_conf_min=kp_conf_min,
            clock=alert_clock,
        )
    except Exception as exc:  # noqa: BLE001 - spec §11.3
        logger.warning(
            "Không dựng được bộ theo dõi hiện diện (%s); cảnh báo 'rời "
            "khung hình' sẽ không chạy. Các chức năng khác vẫn chạy.",
            exc,
        )
    try:
        # Thiếu trọng số không làm hỏng ở đây: PhoneDetector nạp lười, lỗi
        # chỉ hiện ở lần detect đầu và PhoneSignal tự tắt tính năng.
        phone_signal = PhoneSignal(config)
    except Exception as exc:  # noqa: BLE001 - spec §11.3
        logger.warning(
            "Không dựng được bộ phát hiện điện thoại (%s); cảnh báo 'dùng "
            "điện thoại' sẽ không chạy. Các chức năng khác vẫn chạy.",
            exc,
        )

    _warn_phone_threshold_mismatch(config, phone_signal is not None, logger)
    try:
        speaker_alerter = speaker
        if speaker_alerter is None:
            speaker_alerter = SpeakerAlerter.from_config(config)
        if speaker_alerter.available:
            # Chỉ sinh WAV khi thật sự có loa: không có loa thì không phát
            # được, và việc gọi ``espeak-ng`` ở đây là I/O vô ích.
            speaker_alerter.prepare()
    except Exception as exc:  # noqa: BLE001 - spec §11.3
        speaker_alerter = None
        logger.warning(
            "Không dựng được loa cảnh báo (%s); cảnh báo trong giờ học chỉ "
            "được ghi log. Các chức năng khác vẫn chạy.",
            exc,
        )

    #: Mốc cảnh báo gần nhất **của từng loại**, dạng datetime cùng dạng với
    #: ``now``. ``schedule.should_alert`` chỉ áp cooldown khi khóa này có mặt;
    #: thiếu nó thì mỗi khung đều đủ điều kiện và loa kêu liên tục.
    last_alert_at: dict[str, datetime] = {}

    #: Mốc ``alert_now`` (giây monotonic) của lần đầu tín hiệu danh tính là
    #: ``MISMATCH`` liên tục; ``None`` khi khung trước không phải mismatch
    #: (hoặc chưa có người được chọn). Đây là **float cùng gốc với
    #: ``alert_now``** — cố ý không dùng datetime và cố ý không nằm chung
    #: ``last_alert_at``: ``held`` là khoảng thời gian, ``last_alert_at`` là
    #: mốc ``datetime`` cho cooldown.
    stranger_since: float | None = None

    def _keypoints_array(pose_result):
        """Ghép ``(17, 3)`` [x, y, conf] từ ``pose.xy``/``pose.conf``.

        ``PhoneSignal.observe`` cần cả ba cột; ``PoseResult`` giữ hai mảng
        riêng. Không có pose thì trả ``None`` để dịch vụ biết khung này không
        xét được (xem ``_usable_keypoints``).
        """
        if pose_result is None:
            return None
        try:
            return np.concatenate(
                (
                    np.asarray(pose_result.xy, dtype=float),
                    np.asarray(pose_result.conf, dtype=float).reshape(-1, 1),
                ),
                axis=1,
            )
        except (AttributeError, TypeError, ValueError):
            return None

    #: Cửa sổ xem trước còn dùng được không. Không phải máy nào cũng có
    #: display/backend Qt lành: trên Pi qua xrdp, thiếu thư mục font làm Qt
    #: không tạo được ``guiReceiver``, và mọi lời gọi cửa sổ ném ``cv2.error``
    #: (-27:Null pointer). Spec §11.3: thiếu display/phần cứng không được giết
    #: chạy giám sát — chỉ mất cửa sổ xem trước, dashboard web vẫn chạy. Hỏng
    #: lần đầu thì cảnh báo đúng một lần rồi thôi thử lại, tránh spam ở 5 FPS.
    preview_ok = True

    def _disable_preview(exc) -> None:
        """Đánh dấu cửa sổ hỏng và cảnh báo đúng một lần cho cả phiên."""
        nonlocal preview_ok
        if not preview_ok:
            return
        preview_ok = False
        logger.warning(
            "Không dùng được cửa sổ xem trước OpenCV (%s); vẫn tiếp tục giám "
            "sát, xem trực tiếp trên dashboard web. Sẽ không thử mở lại cửa "
            "sổ trong phiên chạy này.",
            exc,
        )

    if not show_preview:
        # Người dùng chủ động tắt: không phải lỗi, không cần cảnh báo. Ghi
        # info để khi đọc log vẫn biết vì sao không có cửa sổ.
        preview_ok = False
        logger.info(
            "Không mở cửa sổ xem trước (mặc định); xem hình trên dashboard web."
        )
    else:
        try:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        except Exception as exc:  # noqa: BLE001 - spec §11.3: thiếu display không được chết
            _disable_preview(exc)
        else:
            logger.info("Cửa sổ xem trước đã mở. Bấm q hoặc Esc để thoát.")

    try:
        while True:
            started = time.monotonic()
            frame = source.read()
            if frame is None:
                # Mất camera: capture đã ghi log lý do; dừng vòng lặp thay vì
                # quay vòng liên tục làm nóng CPU.
                logger.error("Không còn khung nào từ camera; dừng xem trước.")
                return 1

            now = time.monotonic() - loop_start

            # -- cổng phiên học ------------------------------------------
            # Đây là chỗ **duy nhất** quyết định model AI có chạy hay không.
            # ``session_active`` đọc từ ``StudySession`` (máy chủ giữ, nút bấm
            # trên web ghi vào) chứ không phải từ một cờ riêng trong vòng lặp.
            #
            # Ngoài phiên vẫn phải:
            #   - đọc camera và đẩy khung lên dashboard (người dùng cần thấy
            #     mình đã ngồi đúng khung trước khi bấm Bắt đầu);
            #   - chạy nhận diện khuôn mặt (``people.observe``) để biết ai
            #     đang ngồi;
            # nhưng **không** chạy pose, không dò điện thoại, không cảnh báo —
            # đó chính là yêu cầu "bấm Bắt đầu thì mới dùng model AI".
            session_active = True
            session_snapshot = None
            if study_session is not None:
                try:
                    session_snapshot = study_session.tick()
                    session_active = session_snapshot.state == STATE_RUNNING
                except Exception as exc:  # noqa: BLE001 - spec §11.3
                    # Module thuần, gần như không thể ném; nếu có thì **chạy
                    # tiếp như bản cũ** thay vì lặng lẽ tắt model cả buổi học.
                    session_active = True
                    if session_errors == 0:
                        logger.warning(
                            "Không đọc được trạng thái phiên học (%s); tạm "
                            "coi như đang trong phiên. Các lỗi sau không ghi "
                            "log để tránh ngập log.",
                            exc,
                        )
                    session_errors += 1
                if session_snapshot is not None and session_snapshot.finished_message:
                    # ``tick`` chỉ trả câu này **một lần** cho mỗi phiên, nên
                    # dòng log này cũng chỉ xuất hiện một lần dù vòng lặp còn
                    # chạy thêm hàng nghìn khung nữa.
                    logger.info(
                        "PHIÊN HỌC: %s (đã học %d phút).",
                        session_snapshot.finished_message,
                        session_snapshot.minutes,
                    )

            if session_active != session_was_active:
                first_frame = session_was_active is None
                session_was_active = session_active
                # Bắt đầu hoặc kết thúc một phiên: xoá mọi bộ đếm thời gian.
                # Không xoá thì một chuỗi "vắng 4 giây" từ trước giờ nghỉ sẽ
                # làm khung đầu tiên của phiên mới báo vắng oan, và một hộp
                # điện thoại cũ sẽ làm báo "đang dùng điện thoại" ngay.
                try:
                    smoother.reset()
                    machine.reset()
                except Exception:  # noqa: BLE001 - spec §11.3
                    pass
                for tracker in (presence_tracker, phone_signal):
                    try:
                        if tracker is not None:
                            tracker.reset()
                    except Exception:  # noqa: BLE001 - spec §11.3
                        pass
                active_alerts.clear()
                last_alert_at.clear()
                stranger_since = None
                # Khung đầu tiên không phải một "lần chuyển": chưa có phiên
                # trước để kết thúc. Chỉ log khi thật sự vừa bật/vừa tắt.
                if first_frame:
                    if session_active:
                        logger.info(
                            "Đang trong phiên học %s phút: phân tích tư thế "
                            "và dò điện thoại đang chạy.",
                            getattr(session_snapshot, "minutes", "?"),
                        )
                    else:
                        logger.info(
                            "Chưa bắt đầu phiên học: đang xem camera và nhận "
                            "diện khuôn mặt; chưa phân tích tư thế, chưa dò "
                            "điện thoại, chưa cảnh báo."
                        )
                elif session_active:
                    logger.info(
                        "Bắt đầu phiên học %s phút: bật phân tích tư thế và "
                        "dò điện thoại.",
                        getattr(session_snapshot, "minutes", "?"),
                    )
                else:
                    logger.info(
                        "Kết thúc phiên học: tắt phân tích tư thế và dò điện "
                        "thoại; vẫn nhận diện khuôn mặt và xem camera."
                    )

            # Chỉ chạy model pose trong phiên. Ngoài phiên ``pose`` là
            # ``None`` nên phần còn lại (đặc trưng/trạng thái) đi đúng nhánh
            # "không thấy người" có sẵn — rẻ và không phải viết thêm đường
            # thứ hai cho cùng một khung.
            pose = estimator.detect(frame) if session_active else None
            if pose is None:
                features = extract(
                    None,
                    None,
                    view=view,
                    kp_conf_min=kp_conf_min,
                    baseline=feature_baseline,
                )
                drawn = frame
            else:
                features = extract(
                    pose.xy,
                    pose.conf,
                    view=view,
                    kp_conf_min=kp_conf_min,
                    baseline=feature_baseline,
                )
                drawn = draw_pose(
                    frame,
                    pose.xy,
                    pose.conf,
                    config.model.kp_conf_min,
                    copy=False,
                )

            distance_cm = None if sensor is None else sensor.read()

            if session_active:
                smoothed = smoother.push(now, features)
                classification = classify(smoothed, baseline, config.thresholds)
                labels = apply_distance(
                    classification.labels, distance_cm, min_distance_cm
                )
                labels = _loc_nhan_tu_the(labels, config.posture_labels_enabled)
                update = machine.update(now, labels, classification.score)

                for event in update.events:
                    if event.label is None:
                        continue
                    if event.type == EVENT_ALERT_START:
                        active_alerts[event.label] = LABEL_TEXT.get(
                            event.label, event.label
                        )
                    elif event.type == EVENT_ALERT_END:
                        active_alerts.pop(event.label, None)
                alert_text = (
                    ", ".join(active_alerts[label] for label in sorted(active_alerts))
                    if active_alerts
                    else None
                )
            else:
                # Ngoài phiên: không chấm tư thế, không đếm "ngồi liên tục",
                # không mở/đóng đợt cảnh báo. Vẫn phát một trạng thái để
                # dashboard biết vòng lặp còn sống (``data_age_s`` không lớn
                # dần thành "dữ liệu đã cũ") và để người dùng thấy lý do các
                # ô số liệu đang trống. ``update`` vẫn có kiểu ``StateUpdate``
                # để các khối bên dưới không phải rẽ nhánh thêm.
                state_text = STATE_PAUSED
                update = StateUpdate(
                    now=now,
                    state=state_text,
                    labels=frozenset(),
                    score=0.0,
                    sitting_s=0.0,
                )
                alert_text = None

            if state is not None:
                state.update(
                    state=update.state,
                    labels=[label for label in LABEL_ORDER if label in update.labels],
                    score=update.score,
                    sitting_s=update.sitting_s,
                    distance_cm=distance_cm,
                    alert=alert_text,
                    message="" if session_active else PAUSED_MESSAGE,
                )
                if state.consume_calibration_request():
                    logger.info(
                        "Dashboard có yêu cầu hiệu chỉnh lại: hiệu chỉnh cần "
                        "người ngồi đúng tư thế nên không chạy tự động ở đây. "
                        "Hãy thoát và chạy 'python -m posture_monitor "
                        "calibrate', rồi khởi động lại 'run'."
                    )

            # Chỉ ghi DB khi thật sự có phân tích: ngoài phiên ``update`` là
            # trạng thái giả, ghi vào sẽ làm lịch sử đầy những khung 0 điểm
            # không phải kết quả đo nào.
            if storage is not None and session_active:
                storage.record(update, distance_cm)

            # Tính năng người học: ``observe`` chỉ cất tham chiếu khung rồi
            # trả về ngay (xem docstring ``PeopleService``). Lỗi ở đây —
            # kể cả ``AttributeError`` vì dịch vụ nửa vời — phải bị nuốt và
            # đếm, không được giết vòng lặp camera.
            if people is not None:
                try:
                    # Đồng hồ của dịch vụ là ``time.monotonic`` (giây tuyệt
                    # đối), **không** phải ``now`` tương đối so với
                    # ``loop_start`` ở trên — trộn hai gốc thời gian sẽ khiến
                    # tuổi tín hiệu sai hàng nghìn giây.
                    people_now = time.monotonic()
                    # Ngoài phiên thì **không** đẩy tín hiệu presence: hệ
                    # thống đang không đo, nên báo "Có mặt" hay "Vắng mặt" đều
                    # là đoán. Để yên cho tín hiệu tự hết hạn và dashboard
                    # hiện "chưa có dữ liệu mới" — đúng sự thật (spec §5.16).
                    if session_active:
                        people.update_signals(
                            presence=_presence_state(update.state),
                            now=people_now,
                        )
                    people.observe(frame, people_now)
                except Exception as exc:  # noqa: BLE001 - spec §11.3
                    people_errors += 1
                    if people_errors == 1:
                        logger.warning(
                            "Dịch vụ người học lỗi khi nhận khung (%s); vẫn "
                            "giám sát, chỉ tính năng người học bị ảnh hưởng. "
                            "Các lỗi sau không ghi log để tránh ngập log.",
                            exc,
                        )

            # Cảnh báo trong giờ học: presence + phone + danh tính → ``held``
            # → ``schedule.should_alert`` → loa. Mọi lỗi ở đây bị nuốt và chỉ
            # ghi log lần đầu, đúng lý do của khối ``people`` phía trên.
            #
            # ``alert_now`` khởi tạo ngoài khối: phần vẽ hộp bên dưới cần cùng
            # mốc thời gian với lần ``phone_signal.observe`` vừa rồi — hộp chỉ
            # còn hạn trong ``phone.box_ttl_s`` kể từ đúng mốc đó, nên đọc
            # đồng hồ lần hai sẽ làm sai lệch hạn dùng của hộp.
            alert_now: float | None = None
            if (
                session_active
                and schedule_cfg is not None
                and (
                    presence_tracker is not None
                    or phone_signal is not None
                    or speaker_alerter is not None
                    or people is not None
                )
            ):
                try:
                    alert_now = alert_clock()
                    held: dict[str, float] = {}
                    if presence_tracker is not None:
                        presence_result = presence_tracker.update(pose)
                        held["leave_frame"] = presence_result.absent_for_s
                    if phone_signal is not None:
                        phone_result = phone_signal.observe(
                            frame, _keypoints_array(pose), alert_now
                        )
                        # ``observe`` trả ``None`` khi keypoint không dùng
                        # được (vd. người quay lưng), và khi đó ``_held_s``
                        # ĐỨNG YÊN ở giá trị cũ. Đọc thẳng ``held_s`` nghĩa
                        # là coi người vừa quay lưng là "đã chạm 10 giây" mãi
                        # mãi — một lỗi im lặng. Vì vậy chỉ tin ``held_s`` khi
                        # lần quan sát này thực sự có kết quả.
                        held["phone"] = (
                            phone_signal.held_s if phone_result is not None else 0.0
                        )

                        # Dashboard đọc people.signals()["phone"], còn loa đọc
                        # held["phone"] — hai nguồn rời nhau. Không đẩy sang dịch
                        # vụ thì dòng "Điện thoại" đứng ở "chưa có dữ liệu" mãi
                        # dù loa vẫn báo dùng.
                        #
                        # Đọc trong ``try`` riêng, đúng như khối danh tính bên
                        # dưới: một dịch vụ nửa vời (thiếu ``note_phone``) chỉ
                        # được làm mất dòng điện thoại, **không** được làm rơi
                        # cả khối và mất luôn cảnh báo rời khung/danh tính của
                        # khung này.
                        if people is not None:
                            try:
                                people.note_phone(
                                    PHONE_STATE_USE
                                    if phone_result is not None and phone_signal.in_use
                                    else PHONE_STATE_NONE,
                                    now=alert_now,
                                )
                            except Exception:  # noqa: BLE001 - spec §11.3
                                pass

                    # "Người khác ngồi học hộ": chỉ tin ``identity`` khi nó
                    # còn MỚI. ``PeopleService.signals`` ghi rõ ``fresh is
                    # False`` nghĩa là hết dữ liệu, không phải "vẫn đúng như
                    # lần trước"; đọc thẳng ``state`` sẽ biến một kết luận
                    # cũ thành kết luận hiện tại (spec §5.16). Và chỉ báo
                    # khi **đã có người được chọn**: ``MISMATCH`` lúc chưa
                    # chọn nghĩa là "khuôn mặt không khớp ai trong kho", xảy
                    # ra cả khi kho rỗng/đang hiệu chỉnh — báo nhầm. Yêu cầu
                    # của đề tài là "người khác vào học hộ", tức phải có một
                    # người đang học để bị thay thế.
                    #
                    # Thời gian giữ tự tích lũy bằng ``alert_now`` (float,
                    # gốc monotonic, là một DURATION); **không** dùng
                    # ``alert_wall_clock()`` ở đây — đó là datetime và chỉ
                    # dành cho ``last_alert_at``.
                    # Tín hiệu danh tính đọc trong ``try`` riêng: một dịch vụ
                    # nửa vời (thiếu ``signals``) không được làm rơi cả khối
                    # và mất luôn cảnh báo rời khung/điện thoại của khung
                    # này. Lỗi ở đây coi như "chưa có dữ liệu danh tính".
                    if people is not None:
                        try:
                            identity = people.signals().get("identity") or {}
                            selected = people.selected_person()
                        except Exception:  # noqa: BLE001 - spec §11.3
                            identity, selected = {}, None
                        if (
                            identity.get("fresh") is True
                            and identity.get("state") == IDENTITY_MISMATCH
                            and selected is not None
                        ):
                            if stranger_since is None:
                                stranger_since = alert_now
                            held["stranger"] = max(0.0, alert_now - stranger_since)
                        else:
                            stranger_since = None

                    decision = schedule_mod.should_alert(
                        schedule_cfg,
                        alert_wall_clock(),
                        held=held,
                        last_alert_at=last_alert_at,
                    )
                    if decision is not None:
                        # Spec v3 §3.3: dashboard tắt tiếng thì **không phát ra
                        # loa** nhưng vẫn ghi sự kiện. Giá trị này phải đọc ở
                        # ĐÂY, trước lời gọi loa; cổng GPIO phía dưới chỉ chặn
                        # tiếng của dispatcher, không chặn loa camera.
                        muted = bool(state is not None and state.muted)
                        # Spec v3 §6: quyết định cảnh báo phải vào bảng
                        # ``events``, không chỉ khi loa kêu. Ghi theo QUYẾT
                        # ĐỊNH nên vẫn có bản ghi khi tắt tiếng hoặc loa lỗi
                        # (hai ca đó có ``SPEAK_FAILED``/không phát riêng).
                        # Một mốc thời gian duy nhất với cảnh báo: ``alert_now``.
                        event_type = ALERT_EVENT_TYPE.get(decision.kind)
                        if event_type is None:
                            logger.warning(
                                "Không có loại sự kiện cho cảnh báo '%s'; "
                                "không ghi vào bảng events.",
                                decision.kind,
                            )
                        elif storage is not None:
                            # ``duration_s`` là thời gian điều kiện đã duy trì
                            # liên tục — chính là giá trị ``should_alert`` vừa
                            # dùng để quyết định, có sẵn trong ``held``. Bỏ
                            # trống thì cột luôn 0,0 và lịch sử báo mọi cảnh
                            # báo kéo dài 0 giây. ``held`` khởi tạo là ``{}``
                            # ngay đầu khối nên luôn có ``.get``.
                            #
                            # Bọc riêng lời ghi DB: ``record_event`` ném thì
                            # khối ``try`` ngoài nhảy thẳng vào ``except`` và
                            # BỎ QUA ``last_alert_at[kind] = ...`` ở cuối khối
                            # → cooldown không tiến → khung sau báo lại, lặp
                            # mỗi khung. Lỗi ghi DB không được chặn bước tiến
                            # cooldown, và cũng không được nuốt luôn phần loa
                            # phía dưới (bài học ~18 000 dòng/giờ ở cuối khối).
                            try:
                                storage.record_event(
                                    Event(
                                        ts=float(alert_now),
                                        type=event_type,
                                        label=decision.kind,
                                        duration_s=float(held.get(decision.kind, 0.0)),
                                        alert=True,
                                    )
                                )
                            except Exception as exc:  # noqa: BLE001 - spec §11.3
                                event_errors += 1
                                if event_errors == 1:
                                    logger.warning(
                                        "Không ghi được sự kiện cảnh báo '%s' "
                                        "vào DB (%s); vẫn giám sát tiếp. Các "
                                        "lỗi sau không ghi log để tránh ngập "
                                        "log.",
                                        decision.kind,
                                        exc,
                                    )
                        # ``speaker_alerter is None`` nghĩa là chưa cấu hình
                        # loa: không có gì để nói, nên cũng không ghi sự kiện
                        # loa giả. Cooldown vẫn phải tiến ở nhánh đó.
                        outcome = None
                        if speaker_alerter is not None:
                            outcome = speaker_alerter.alert_many(
                                (decision.kind,), now=alert_now, muted=muted
                            )
                            if outcome.spoken:
                                logger.info(
                                    "SPEAK_OK: đã phát cảnh báo '%s' ra loa camera.",
                                    decision.kind,
                                )
                                if storage is not None:
                                    storage.record_event(
                                        Event(
                                            ts=float(alert_now),
                                            type=EVENT_SPEAK_OK,
                                            label=decision.kind,
                                            alert=False,
                                        )
                                    )
                            if outcome.error is not None:
                                # Tầng ``_failure`` đã log một lần; dòng này
                                # giữ đúng từ khoá ``SPEAK_FAILED`` mà spec
                                # §5.15/§6 yêu cầu để grep được trong log.
                                logger.warning(
                                    "SPEAK_FAILED: cảnh báo '%s' không phát "
                                    "được ra loa (%s); vẫn giám sát tiếp.",
                                    decision.kind,
                                    outcome.error,
                                )
                                if storage is not None:
                                    storage.record_event(
                                        Event(
                                            ts=float(alert_now),
                                            type=EVENT_SPEAK_FAILED,
                                            label=decision.kind,
                                            alert=False,
                                        )
                                    )
                        # VÔ ĐIỀU KIỆN sau mỗi quyết định: ``should_alert``
                        # không có cooldown nào nếu ``last_alert_at`` rỗng, nên
                        # quên dòng này nghĩa là loa kêu/log kín ở MỌI khung.
                        # Gắn nó vào ``outcome.spoken`` biến mỗi lần cảnh báo
                        # thành log storm (~18 000 dòng/giờ) ở cấu hình mặc
                        # định (``camera.speaker.enabled: false``).
                        # ``retryable`` (loa đang bận) là ngoại lệ duy nhất:
                        # chưa nói gì thì không được tiêu cooldown, nếu không
                        # một lần trùng nhịp với cảnh báo khác sẽ nuốt luôn sự
                        # kiện này và người dùng thấy "chỉ báo được lần đầu".
                        if outcome is None or not outcome.retryable:
                            last_alert_at[decision.kind] = alert_wall_clock()
                except Exception as exc:  # noqa: BLE001 - spec §11.3
                    alert_errors += 1
                    if alert_errors == 1:
                        logger.warning(
                            "Tính năng cảnh báo trong giờ học lỗi khi xử lý "
                            "khung (%s); vẫn giám sát, chỉ cảnh báo bị ảnh "
                            "hưởng. Các lỗi sau không ghi log để tránh ngập "
                            "log.",
                            exc,
                        )

            if dispatcher is not None and session_active:
                if (state is not None and state.muted) or not (
                    config.alerts.gpio_alert_enabled
                ):
                    # Chỉ chặn tiếng; sự kiện vẫn đi vào DB và lên dashboard.
                    # Công tắc `gpio_alert_enabled` tắt (mặc định) cũng đi
                    # đường im lặng này: LED vẫn cập nhật trạng thái nhưng
                    # không kêu/không rung.
                    dispatcher.dispatch(replace(update, alerts=()))
                else:
                    dispatcher.dispatch(update)
            elif dispatcher is not None:
                # Ngoài phiên: không có kết luận tư thế nào để hiện, nên đẩy
                # trạng thái vắng + không cảnh báo. Không đẩy gì thì LED/loa
                # giữ nguyên trạng thái cuối của phiên trước, người dùng thấy
                # đèn đỏ sáng mãi dù đã bấm Dừng.
                dispatcher.dispatch(replace(update, state=STATE_ABSENT, alerts=()))

            # -- vẽ hộp phát hiện ------------------------------------------
            # Vẽ **sau** ``phone_signal.observe``/``people.observe`` và **trước**
            # ``imshow``/``imencode``: hộp là kết quả của chính khung này (hoặc
            # hộp gần nhất còn hạn), nên chỗ dựng ``drawn`` ở đầu vòng lặp —
            # trước cả hai lần detect — không bao giờ có hộp. Đổi thứ tự này
            # cũng là lý do ``cv2.imencode``/``state.set_frame`` được dời xuống
            # đây: luồng web phải thấy đúng thứ cửa sổ xem trước thấy.
            phone_boxes = ()
            face_box = None
            if phone_signal is not None and session_active:
                # Không có giờ học thì khối cảnh báo ở trên không chạy và
                # ``alert_now`` vẫn ``None``; đọc đồng hồ ngay đây. Cùng một
                # đồng hồ với ``PhoneSignal.observe`` nhờ ``alert_clock``.
                # Ngoài phiên thì không vẽ hộp: ``PhoneSignal`` đã được
                # ``reset``, hộp cũ không còn nghĩa gì và một ô vuông đứng
                # trên hình sẽ làm người dùng tưởng hệ thống vẫn đang dò.
                if alert_now is None:
                    try:
                        alert_now = alert_clock()
                    except Exception:  # noqa: BLE001 - spec §11.3
                        alert_now = None
                try:
                    if alert_now is not None:
                        phone_boxes = phone_signal.boxes(alert_now)
                except Exception:  # noqa: BLE001 - spec §11.3
                    phone_boxes = ()
            if people is not None:
                try:
                    face_box = people.latest_face_box()
                except Exception:  # noqa: BLE001 - spec §11.3
                    face_box = None
            if phone_boxes or face_box is not None:
                # ``copy=True`` bắt buộc ở đây: ``drawn`` **chính là** ``frame``
                # (``draw_pose(copy=False)`` và ``drawn = frame`` đều trả đúng
                # đối tượng gốc), mà ``people.observe`` phía trên vừa cất tham
                # chiếu ``frame`` cho luồng nhận diện đọc. Vẽ chồng lên nó là
                # sửa ảnh trong lúc YuNet đang đọc — một khung bị xé giữa
                # chừng chỉ để tiết kiệm một lần copy 1,2 MB là đánh đổi sai.
                drawn = draw_detections(
                    drawn,
                    phone_boxes=phone_boxes,
                    face_box=face_box,
                    copy=True,
                )

            if state is not None and stream_enabled:
                ok, buffer = cv2.imencode(".jpg", drawn)
                if ok:
                    state.set_frame(buffer.tobytes())

            if preview_ok:
                try:
                    cv2.imshow(WINDOW_NAME, drawn)
                    # waitKey phải được gọi để OpenCV xử lý sự kiện cửa sổ.
                    key = cv2.waitKey(1) & 0xFF
                except Exception as exc:  # noqa: BLE001 - spec §11.3
                    _disable_preview(exc)
                else:
                    if key in QUIT_KEYS:
                        logger.info("Nhận phím thoát; đóng cửa sổ.")
                        return 0
                    try:
                        visible = cv2.getWindowProperty(
                            WINDOW_NAME, cv2.WND_PROP_VISIBLE
                        )
                    except Exception as exc:  # noqa: BLE001 - spec §11.3
                        _disable_preview(exc)
                    else:
                        if visible < 1:
                            # Người dùng bấm nút X của cửa sổ.
                            logger.info("Cửa sổ đã đóng; thoát.")
                            return 0

            # Giữ nhịp theo target_fps, không ngủ nếu xử lý đã lâu hơn.
            elapsed = time.monotonic() - started
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        if preview_ok:
            try:
                cv2.destroyAllWindows()
            except Exception as exc:  # noqa: BLE001 - spec §11.3
                _disable_preview(exc)


def cmd_run(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``run``: cấu hình → phần cứng → camera → pose + overlay."""
    logger = setup_logging(args.log_level)

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except ConfigError as exc:
        logger.error("Cấu hình không hợp lệ: %s", exc)
        return 2

    view = args.view or config.camera.view
    if args.view and args.view != config.camera.view:
        logger.info(
            "Ghi đè góc camera từ cấu hình (%s) bằng --view %s.",
            config.camera.view,
            args.view,
        )

    override_fps = getattr(args, "fps", None)
    if override_fps is not None:
        if override_fps <= 0:
            logger.error("'--fps' phải là số dương, nhận được %s.", override_fps)
            return 2
        old_fps = config.model.target_fps
        config.model.target_fps = int(override_fps)
        logger.info(
            "Ghi đè 'model.target_fps' từ cấu hình (%s) bằng --fps %s.",
            old_fps,
            config.model.target_fps,
        )

    # Import muộn: chỉ lệnh này cần phần cứng.
    from .hardware import create_hardware  # noqa: PLC0415

    hardware = create_hardware(config, no_gpio=args.no_gpio)

    source = capture_from_config(config)
    if source is None:
        logger.error(
            "Không mở được nguồn ảnh '%s' nên không thể suy luận pose. Chạy "
            "'python scripts/camera_probe.py' để kiểm tra phần cứng.",
            redact_camera_source(config.camera.source),
        )
        hardware.close()
        return 1

    # Import muộn: kéo ultralytics/torch chỉ khi thật sự chạy suy luận.
    from .pose import PoseError, PoseEstimator  # noqa: PLC0415

    try:
        estimator = PoseEstimator(config)
    except PoseError as exc:
        logger.error("%s", exc)
        source.close()
        hardware.close()
        return 2
    except KeyboardInterrupt:  # pragma: no cover - export có thể bị dừng tay
        raise

    try:
        if args.save_overlay:
            return _save_one_overlay(
                estimator, source, config, Path(args.save_overlay), logger
            )

        # Mặc định KHÔNG mở cửa sổ OpenCV: người dùng xem trên web.
        # ``--preview`` mới bật; ``--no-preview`` được giữ để lệnh cũ vẫn chạy
        # được. Tính một lần rồi dùng cho cả banner lẫn vòng lặp để hai nơi
        # không bao giờ nói ngược nhau.
        show_preview = bool(getattr(args, "preview", False))

        _print_status(config, hardware, source, view, estimator.backend, show_preview)

        # Nhánh chạy dài: dựng dashboard web (state + storage + Flask) và chạy
        # server ở luồng nền trước khi vào vòng lặp. Nhánh --save-overlay ở
        # trên đã return sớm nên không dựng gì.
        from .alerts import AlertDispatcher  # noqa: PLC0415
        from .sensors import create_sensor  # noqa: PLC0415

        sensor = None
        dispatcher = None
        dashboard = None
        try:
            dashboard = _Dashboard(config, logger)
            dashboard.start()
            sensor = create_sensor(config)
            dispatcher = AlertDispatcher(hardware, config.alerts)
            return _monitor_loop(
                estimator,
                source,
                config,
                logger,
                state=dashboard.state,
                storage=dashboard.storage,
                sensor=sensor,
                dispatcher=dispatcher,
                stream_enabled=bool(config.web.stream_enabled),
                people=getattr(dashboard, "people", None),
                speaker=getattr(dashboard, "speaker", None),
                show_preview=show_preview,
                study_session=getattr(dashboard, "study_session", None),
            )
        finally:
            if dashboard is not None:
                dashboard.storage.close()
                dashboard.thread.join(timeout=1.0)
                people_service = getattr(dashboard, "people", None)
                if people_service is not None:
                    people_service.close()
            if dispatcher is not None:
                dispatcher.close()
            if sensor is not None:
                sensor.close()
    finally:
        source.close()
        hardware.close()


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``benchmark``: chuyển tiếp sang :func:`benchmark.main`.

    Chọn **chuyển tiếp** thay vì gọi ``run_benchmark``/``format_report`` trực
    tiếp: ``benchmark.main`` đã giữ toàn bộ quy ước của bài đo (nạp cấu hình,
    kiểm ``--seconds``, in bảng, ghi JSON UTF-8, ánh xạ mã thoát 2/1/130/0).
    Chép lại thân hàm đó sẽ tạo bản thứ hai dễ lệch nhau; dựng lại ``argv``
    giữ cho ``python -m posture_monitor benchmark`` và
    ``python -m posture_monitor.benchmark`` chạy đúng **một** thân code.
    """
    from . import benchmark as bench  # noqa: PLC0415 - import muộn (kéo model)

    argv: list[str] = ["--seconds", str(args.seconds), "--config", args.config]
    if args.source is not None:
        argv += ["--source", args.source]
    if args.json is not None:
        argv += ["--json", args.json]
    if getattr(args, "profile", None):
        argv += ["--profile", args.profile]
    if args.no_gpio:
        argv.append("--no-gpio")
    argv += ["--log-level", args.log_level]
    return bench.main(argv)


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``calibrate``: đếm ngược → thu khung → lưu baseline.

    Chỉ **thu** dữ liệu chứ không tự quyết định baseline: việc lọc khung và
    lấy trung vị nằm ở :mod:`posture_monitor.calibration` (đã có test riêng).
    Nhờ vậy lệnh này chỉ còn lo phần tương tác — nhịp thu, thông báo tiếng
    Việt và mã thoát.

    Mã thoát: ``0`` thành công, ``1`` không mở được nguồn ảnh / không ghi
    được file, ``2`` cấu hình hoặc model sai, hoặc không đủ khung hợp lệ.
    """
    logger = setup_logging(args.log_level)

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except ConfigError as exc:
        logger.error("Cấu hình không hợp lệ: %s", exc)
        return 2

    # Import muộn: chỉ lệnh này cần tới calibration/features.
    from .calibration import (  # noqa: PLC0415
        CAPTURE_S,
        COUNTDOWN_S,
        CalibrationError,
        compute_baseline,
        save,
    )
    from .features import extract  # noqa: PLC0415

    camera = config.camera
    view = camera.view
    kp_conf_min = config.model.kp_conf_min
    output = Path(args.output)
    #: Khi nguồn tạm thời không trả khung, nghỉ một chút rồi thử lại thay vì
    #: quay vòng liên tục làm nóng CPU trong suốt cửa sổ thu.
    sample_retry_s = 0.05

    if args.no_gpio:
        # calibrate không chạm phần cứng nào; cờ này chỉ để dùng chung cú
        # pháp với ``run``.
        logger.info(
            "--no-gpio: calibrate không dùng GPIO nên cờ này không có tác dụng (no-op)."
        )

    source = capture_from_config(config)
    if source is None:
        logger.error(
            "Không mở được nguồn ảnh '%s' nên không thể hiệu chỉnh. Kiểm tra "
            "phần cứng bằng 'python scripts/camera_probe.py', hoặc chạy "
            "'python -m posture_monitor run' để xem trực tiếp.",
            redact_camera_source(camera.source),
        )
        return 1

    try:
        from .pose import PoseError, PoseEstimator  # noqa: PLC0415

        try:
            estimator = PoseEstimator(config)
        except PoseError as exc:
            logger.error("%s", exc)
            return 2

        # Nạp trước model **trước khi mở cửa sổ thu**. Lần suy luận đầu tiên
        # của ultralytics nạp bộ nhớ đệm nên chậm hơn hẳn (đo trên Pi: ~3,7 s
        # so với ~143 ms). Nếu để nó rơi vào CAPTURE_S thì gần hết cửa sổ bị
        # một lần gọi nguội ăn mất và không đủ khung cho baseline. Dùng chung
        # WARMUP_FRAMES với `benchmark` để hai lệnh có cùng định nghĩa "khởi
        # động"; khung khởi động không được đưa vào baseline.
        from .benchmark import WARMUP_FRAMES  # noqa: PLC0415 - chỉ nhánh này cần

        logger.info(
            "Đang nạp trước model (%d khung; lần suy luận đầu chậm hơn hẳn, "
            "có thể mất vài giây)...",
            WARMUP_FRAMES,
        )
        for _ in range(WARMUP_FRAMES):
            frame = source.read()
            if frame is None:
                break
            try:
                estimator.detect(frame)
            except Exception as exc:  # noqa: BLE001 - khung khởi động lỗi thì thôi
                logger.warning("Khung khởi động lỗi: %s", exc)
                break
        logger.info("Nạp trước xong.")
        logger.info(
            "Hiệu chỉnh tư thế chuẩn: ngồi đúng tư thế và giữ yên. Đếm ngược "
            "%.0f giây (view=%s, %dx%d).",
            COUNTDOWN_S,
            view,
            camera.width,
            camera.height,
        )

        # Đếm ngược ~COUNTDOWN_S giây, log từng giây để người dùng kịp ngồi.
        remaining = float(COUNTDOWN_S)
        while remaining > 0:
            logger.info("Bắt đầu thu sau %.0f giây...", remaining)
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step

        logger.info(
            "Bắt đầu thu %.0f giây ở nhịp tự nhiên của vòng lặp (không chờ "
            "theo target_fps: lấy mẫu càng nhiều thì trung vị càng vững).",
            CAPTURE_S,
        )

        frames = []
        read_count = 0
        deadline = time.monotonic() + float(CAPTURE_S)
        while time.monotonic() < deadline:
            frame = source.read()
            if frame is None:
                logger.warning("Không đọc được khung từ nguồn ảnh; bỏ qua nhịp này.")
                time.sleep(sample_retry_s)
                continue

            read_count += 1
            pose = estimator.detect(frame)
            if pose is None:
                # Không thấy người vẫn là mẫu hợp lệ để calibration tự
                # lọc; tránh tự quyết định ở đây.
                frames.append(extract(None, None, view=view, kp_conf_min=kp_conf_min))
            else:
                frames.append(
                    extract(
                        pose.xy,
                        pose.conf,
                        view=view,
                        kp_conf_min=kp_conf_min,
                    )
                )

        logger.info(
            "Thu xong %d khung (%d lần đọc thành công); đang tính baseline.",
            len(frames),
            read_count,
        )

        if read_count == 0:
            # Nguồn mở được nhưng không trả khung nào: coi như hỏng camera,
            # không phải lỗi hiệu chỉnh. Nêu cùng lối kiểm tra với nhánh
            # không mở được nguồn.
            logger.error(
                "Không đọc được khung nào từ nguồn ảnh '%s' trong %.0f giây "
                "nên không thể hiệu chỉnh. Kiểm tra bằng 'python "
                "scripts/camera_probe.py' hoặc chạy 'python -m "
                "posture_monitor run' để xem trực tiếp.",
                redact_camera_source(camera.source),
                CAPTURE_S,
            )
            return 1

        try:
            baseline = compute_baseline(
                frames,
                view=view,
                width=camera.width,
                height=camera.height,
            )
        except CalibrationError as exc:
            # Thông điệp của calibration đã kèm hướng dẫn chỉnh camera; in
            # nguyên văn thay vì bọc lại.
            logger.error("%s", exc)
            return 2

        try:
            saved = save(baseline, output)
        except OSError as exc:
            logger.error("Không ghi được file baseline '%s': %s", output, exc)
            return 1

        print()
        print("=" * 60)
        print("  HIỆU CHỈNH XONG — BASELINE TƯ THẾ CHUẨN")
        print("=" * 60)
        print(f"  File baseline : {saved.resolve()}")
        print(f"  Số khung dùng : {baseline.frames}")
        print(f"  Chế độ camera : {baseline.view} ({baseline.width}x{baseline.height})")
        print(f"  Thời điểm     : {baseline.created_at}")
        print("-" * 60)
        for name, unit in (
            ("shoulder_width", " px"),
            ("shoulder_tilt_deg", "°"),
            ("head_height", ""),
            ("neck_angle", "°"),
            ("torso_angle", "°"),
        ):
            value = baseline.get(name)
            if value is None:
                # Thiếu đặc trưng phụ là chuyện bình thường (spec §5.3);
                # nói rõ để người dùng không tưởng hiệu chỉnh hỏng.
                print(f"  {name:<18}: (không đủ dữ liệu ở lần thu này)")
            else:
                print(f"  {name:<18}: {value:.3f}{unit}")
        print("-" * 60)
        print("  closeness và lean_x là đại lượng tương đối, được tính khi")
        print("  chạy 'python -m posture_monitor run' dựa trên baseline này.")
        print("=" * 60)
        print()
        return 0
    finally:
        source.close()


def cmd_replay(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``replay``: chạy pipeline trên video, xuất báo cáo.

    Thứ tự dây nối từng khung theo đúng ``benchmark.run_benchmark``: đọc
    khung → ``detect`` → ``extract`` → ``classify`` → ``StateMachine.update``.
    Không mở camera, không tạo phần cứng, không vẽ cửa sổ, nên chạy được trên
    PC không có GPIO (spec §7, §9).

    Báo cáo JSON chỉ chứa dữ liệu tất định: không đường dẫn tuyệt đối, không
    tên máy, không mốc thời gian thực trong từng khung. Chỉ ``duration_s``
    của phần tóm tắt là số đo thời gian chạy thật.
    """
    import json  # noqa: PLC0415 - chỉ nhánh này cần
    import math  # noqa: PLC0415 - chỉ nhánh này cần

    from .calibration import Baseline, CalibrationError  # noqa: PLC0415
    from .calibration import load as load_calibration  # noqa: PLC0415
    from .capture import CameraError, FileSource  # noqa: PLC0415
    from .classifier import LABEL_ORDER, classify  # noqa: PLC0415
    from .features import ALL_NAMES, extract  # noqa: PLC0415
    from .pose import PoseError, PoseEstimator  # noqa: PLC0415
    from .state import STATES, StateMachine  # noqa: PLC0415

    logger = setup_logging(args.log_level)

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except ConfigError as exc:
        logger.error("Cấu hình không hợp lệ: %s", exc)
        return 2

    if args.no_gpio:
        logger.info("replay không dùng GPIO; cờ --no-gpio chỉ để tương thích CLI.")

    try:
        source = FileSource(args.video, loop=False)
    except CameraError as exc:
        logger.error("%s", exc)
        return 2

    def _empty_baseline() -> "Baseline":
        """Baseline rỗng: mọi nhãn phụ thuộc baseline không được đánh giá."""
        return Baseline(
            values={name: None for name in ALL_NAMES},
            view=config.camera.view,
            width=int(config.camera.width),
            height=int(config.camera.height),
            created_at="",
            frames=0,
        )

    try:
        # Mốc thời gian của máy trạng thái là trục thời gian của video, không
        # phải đồng hồ thực: nhờ vậy báo cáo tất định và hold/hysteresis được
        # đánh giá trên đúng nhịp video. ``FileSource`` không công bố FPS nên
        # đọc metadata qua một lần mở riêng; file hỏng đã bị chặn ở trên.
        fps = 0.0
        probe = cv2.VideoCapture(str(Path(args.video)))
        try:
            if probe.isOpened():
                fps = float(probe.get(cv2.CAP_PROP_FPS) or 0.0)
        finally:
            probe.release()

        fps_source = "container"
        if not math.isfinite(fps) or fps <= 0:
            fps = float(config.model.target_fps)
            fps_source = "config.model.target_fps"
            logger.warning(
                "Không đọc được FPS từ video; dùng %s (%.1f) để tính mốc thời gian.",
                fps_source,
                fps,
            )
            if not math.isfinite(fps) or fps <= 0:
                # Cấu hình cũng vô lý: không có trục thời gian nào dùng được.
                logger.error(
                    "Cả video lẫn 'model.target_fps' đều không cho FPS hợp "
                    "lệ; không tính được mốc thời gian."
                )
                return 2

        calibration_path = "calibration.json"
        try:
            baseline = load_calibration(calibration_path)
            calibration_loaded = True
            calibration_note = "Đã nạp baseline hiệu chỉnh có sẵn."
        except FileNotFoundError:
            baseline = _empty_baseline()
            calibration_loaded = False
            calibration_note = (
                "Chưa có calibration.json: chạy KHÔNG baseline. Các nhãn phụ "
                "thuộc baseline (HEAD_DOWN ở view front, TOO_CLOSE, LEAN, "
                "HEAD_TILT, LOOK_AWAY) không được đánh giá."
            )
        except CalibrationError as exc:
            baseline = _empty_baseline()
            calibration_loaded = False
            calibration_note = f"calibration.json hỏng ({exc}); chạy KHÔNG baseline."

        if not calibration_loaded:
            logger.warning("%s", calibration_note)

        try:
            estimator = PoseEstimator(config)
        except PoseError as exc:
            logger.error("%s", exc)
            return 2

        # ``extract`` đọc thẳng ``baseline.shoulder_width`` (thuộc tính ném
        # lỗi khi thiếu) nên khi chưa hiệu chỉnh phải truyền ``None``;
        # ``classify`` chỉ dùng ``baseline.get()`` nên nhận baseline rỗng.
        feature_baseline = baseline if calibration_loaded else None

        view = config.camera.view
        kp_conf_min = float(config.model.kp_conf_min)
        machine = StateMachine(config.timing)

        rows: list[dict[str, object]] = []
        state_counts = {state: 0 for state in STATES}
        label_counts = {label: 0 for label in LABEL_ORDER}
        frames_with_person = 0
        frames_errored = 0

        started = time.monotonic()
        index = 0
        try:
            while True:
                frame = source.read()
                if frame is None:
                    break

                pose = None
                try:
                    pose = estimator.detect(frame)
                except Exception as exc:  # noqa: BLE001 - 1 khung lỗi không sập
                    frames_errored += 1
                    logger.warning("Suy luận lỗi ở khung %d: %s", index, exc)

                if pose is None:
                    features = extract(
                        None,
                        None,
                        view=view,
                        kp_conf_min=kp_conf_min,
                        baseline=feature_baseline,
                    )
                else:
                    features = extract(
                        pose.xy,
                        pose.conf,
                        view=view,
                        kp_conf_min=kp_conf_min,
                        baseline=feature_baseline,
                    )

                classification = classify(features, baseline, config.thresholds)
                timestamp = round(index / fps, 3)
                update = machine.update(
                    timestamp, classification.labels, classification.score
                )

                labels = list(classification.sorted_labels)
                rows.append(
                    {
                        "frame": index,
                        "timestamp_s": timestamp,
                        "person": pose is not None,
                        "labels": labels,
                        "score": round(float(classification.score), 2),
                        "state": update.state,
                    }
                )
                if pose is not None:
                    frames_with_person += 1
                state_counts[update.state] += 1
                for label in labels:
                    label_counts[label] += 1
                index += 1
        except KeyboardInterrupt:
            print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
            return 130
        finally:
            source.close()

        duration_s = round(time.monotonic() - started, 3)

        if not rows:
            logger.error(
                "Không đọc được khung nào từ video '%s'; không có gì để báo cáo.",
                Path(args.video).name,
            )
            return 1

        report = {
            "version": 1,
            "command": "replay",
            "video": Path(args.video).name,
            "view": view,
            "backend": estimator.backend,
            "video_fps": round(fps, 3),
            "fps_source": fps_source,
            "calibration": {
                "loaded": calibration_loaded,
                "path": calibration_path,
                "note": calibration_note,
            },
            "summary": {
                "frames": len(rows),
                "frames_with_person": frames_with_person,
                "frames_errored": frames_errored,
                "duration_s": duration_s,
                "states": state_counts,
                "labels": label_counts,
            },
            "frames": rows,
        }

        if args.save_report:
            target = Path(args.save_report)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.error("Không ghi được báo cáo '%s': %s", target, exc)
                return 2

        active_labels = [
            f"{label}={label_counts[label]}"
            for label in LABEL_ORDER
            if label_counts[label]
        ]
        print()
        print("=" * 60)
        print("  REPLAY — KẾT QUẢ CHẠY LẠI VIDEO")
        print("=" * 60)
        print(f"  Video          : {Path(args.video).name}")
        print(f"  Khung đã xử lý : {len(rows)} (có người: {frames_with_person})")
        if frames_errored:
            print(f"  Khung lỗi      : {frames_errored}")
        print(
            "  Trạng thái     : " + ", ".join(f"{s}={state_counts[s]}" for s in STATES)
        )
        print(
            "  Nhãn           : "
            + (", ".join(active_labels) if active_labels else "(không có)")
        )
        print(
            "  Hiệu chỉnh     : "
            + ("đã nạp baseline" if calibration_loaded else "KHÔNG có baseline")
        )
        if args.save_report:
            print(f"  Báo cáo        : {Path(args.save_report).name}")
        print("=" * 60)
        print()
        return 0
    finally:
        source.close()


def cmd_speak_test(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``speak-test``: phát thử giọng đọc ra loa camera.

    Vì sao cần lệnh riêng thay vì dùng ``POST /api/speak``: người triển khai
    cần kiểm chứng âm thanh **trước** khi trình diễn, khi chưa chắc dashboard
    chạy được, và cần nghe lần lượt cả ba câu bằng đúng giọng đang cấu hình.
    Gọi HTTP thì phải mở app, phải tự dựng JSON cho từng câu, và không thấy
    được câu nào đang thiếu bản thu.

    Lệnh này **không** mở luồng hình và **không** đụng GPIO/DB, nên chạy được
    song song với ``run`` (loa chỉ chịu được một phiên backchannel; nếu bận
    thì báo rõ chứ không xếp hàng — spec §3.4).

    Mã thoát: ``0`` phát được hết, ``1`` có câu không phát được (loa lỗi, bận,
    thiếu ffmpeg), ``2`` cấu hình sai/lệnh không dùng được, ``130`` bị dừng
    bằng Ctrl+C.
    """
    logger = setup_logging(args.log_level)

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 2
    except ConfigError as exc:
        logger.error("Cấu hình không hợp lệ: %s", exc)
        return 2

    # Import muộn: chỉ lệnh này cần loa. ``speak-test --list`` cũng cần, vì
    # danh sách giọng nằm trong chính bộ dựng alerter (cùng nguồn với ``run``).
    from .speaker_alert import SpeakerAlerter

    kinds = list(SPEAK_TEST_KINDS) if args.kind == "all" else [args.kind]

    # ``--voice`` chỉ đổi cho lần thử này. Truyền tường minh để
    # ``from_config`` KHÔNG đọc ``voice.json`` ghi đè lên. ``--volume`` và
    # ``--speed`` cũng chỉ có hiệu lực cho lần chạy này và không ghi xuống đĩa.
    kwargs: dict[str, object] = {}
    if args.voice is not None:
        kwargs["voice"] = args.voice
    if args.volume is not None:
        kwargs["volume"] = args.volume
    if args.speed is not None:
        kwargs["speed"] = args.speed

    try:
        alerter = SpeakerAlerter.from_config(config, **kwargs)
    except Exception as exc:  # noqa: BLE001 - thiếu loa không được ném traceback
        logger.error("Không dựng được loa cảnh báo: %s", exc)
        return 2

    if not alerter.available:
        logger.error(
            "Chưa bật được loa camera nên không phát thử được. Bật "
            "'camera.speaker.enabled: true' và đặt 'camera.speaker.host' "
            "(hoặc dùng 'camera.source' là URL rtsp:// để tự suy ra host), "
            "rồi thử lại. Muốn chỉ kiểm tra cấu hình giọng, dùng "
            "'speak-test --list'."
        )
        return 2

    report = alerter.voice_report()

    if args.list:
        _print_speak_test_list(report, kinds)
        return 0

    # Chuẩn bị file phát **trước** khi in, để lỗi ffmpeg/thiếu bản thu hiện ra
    # ngay đầu thay vì xen giữa các câu đang phát.
    alerter.prepare()
    report = alerter.voice_report()

    _print_speak_test_header(alerter, report, kinds, args.tone)

    failures: list[str] = []
    for index, kind in enumerate(kinds):
        if index:
            time.sleep(SPEAK_TEST_GAP_S)
        if args.tone:
            outcome = alerter.speak_tone_now(kind)
        else:
            outcome = alerter.alert(kind)

        label = KIND_LABELS.get(kind, kind)
        if outcome.spoken and outcome.error is None:
            print(f"  [OK]   {label:<20} — {outcome.reason}")
        elif outcome.spoken:
            # Đã phát ra loa nhưng không phải câu tiếng Việt (rơi về bíp).
            print(f"  [BÍP]  {label:<20} — {outcome.reason}")
            print(f"         lỗi: {outcome.error}")
            failures.append(kind)
        else:
            print(f"  [LỖI]  {label:<20} — {outcome.reason}")
            if outcome.error is not None:
                print(f"         lỗi: {outcome.error}")
            failures.append(kind)

    print()
    if failures:
        print(
            f"Không phát được {len(failures)}/{len(kinds)} câu: "
            + ", ".join(KIND_LABELS.get(k, k) for k in failures)
            + "."
        )
        print(
            "Xem log phía trên để biết lý do cụ thể. Kiểm tra: camera có bật "
            "loa/backchannel không, 'camera.speaker' đúng chưa, ffmpeg đã cài "
            "chưa (câu nói cần ffmpeg; --tone thì không)."
        )
        print()
        return 1

    print(f"Đã phát được {len(kinds)}/{len(kinds)} câu ra loa camera.")
    print()
    return 0


def _print_speak_test_header(alerter, report: dict, kinds, tone: bool) -> None:
    """In khối mở đầu của ``speak-test``: giọng, nguồn file, cảnh báo thiếu."""
    from .voice_library import VOICE_LABELS

    voice = report.get("voice")
    print()
    print("=" * 66)
    print("  PHÁT THỬ GIỌNG ĐỌC RA LOA CAMERA")
    print("=" * 66)
    print(f"  Giọng đang dùng : {VOICE_LABELS.get(voice, voice)} ({voice})")
    print(f"  Thư mục âm thanh: {alerter.audio_dir}")
    print(f"  Chế độ          : {'tiếng bíp' if tone else 'câu nói'}")
    if not tone:
        print(f"  Âm lượng        : {alerter.volume:.2f}")
        print(f"  Tốc độ đọc      : {alerter.speed:.2f}×")
    print(f"  Số câu          : {len(kinds)}")
    if report.get("error"):
        print(f"  Cảnh báo        : {report['error']}")
    print("-" * 66)
    print(f"  {'Câu':<20} {'Nguồn phát'}")
    print("-" * 66)
    for kind in kinds:
        label = KIND_LABELS.get(kind, kind)
        wav = alerter.wav_path(kind)
        if tone:
            source = "(tiếng bíp)"
        elif wav is not None:
            source = wav.name
        else:
            source = "THIẾU — sẽ dùng tiếng bíp"
        print(f"  {label:<20} {source}")
    print("-" * 66)
    print("  Loa sẽ phát ngay; tăng âm lượng loa camera nếu không nghe rõ.")
    print()


def _print_speak_test_list(report: dict, kinds) -> None:
    """In danh sách giọng và câu có sẵn, không phát gì (``--list``)."""
    from .voice_library import VOICE_LABELS

    voice = report.get("voice")
    print()
    print("=" * 66)
    print("  GIỌNG ĐỌC ĐANG CÓ (không phát gì)")
    print("=" * 66)
    print(f"  Đang chọn: {VOICE_LABELS.get(voice, voice)} ({voice})")
    print(
        f"  Âm lượng : {report.get('volume', 0):.2f}   "
        f"Tốc độ: {report.get('speed', 0):.2f}×"
    )
    print("-" * 66)
    for key, info in (report.get("voices") or {}).items():
        mark = "*" if key == voice else " "
        label = info.get("label") or VOICE_LABELS.get(key, key)
        clips = info.get("clips") or {}
        missing = info.get("missing") or []
        print(f" {mark} {label:<12} {len(clips)}/{len(kinds)} câu")
        for kind in kinds:
            name = clips.get(kind)
            kind_label = KIND_LABELS.get(kind, kind)
            if name:
                print(f"       {kind_label:<20} {name}")
            elif key in ("nam", "nu"):
                print(f"       {kind_label:<20} THIẾU")
    print("-" * 66)
    fallbacks = report.get("fallbacks") or {}
    for note in fallbacks.values():
        print(f"  Lưu ý: {note}")
    if report.get("error"):
        print(f"  Lỗi  : {report['error']}")
    print("=" * 66)
    print()


def main(argv: list[str] | None = None) -> int:
    """Hàm chính; trả mã thoát của tiến trình."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        try:
            return cmd_run(args)
        except KeyboardInterrupt:
            print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001 - lỗi cuối cùng phải có thông báo
            print(f"Lỗi không mong muốn: {exc}", file=sys.stderr)
            return 1

    elif args.command == "benchmark":
        # ``benchmark.main`` tự đổi lỗi trong lúc đo thành 1/2/130, nhưng phần
        # in báo cáo và ghi file nằm **sau** khối try của nó, nên một lỗi ở đó
        # vẫn thoát ra ngoài. Bọc ở đây để ``benchmark`` có cùng mức xử lý với
        # ba lệnh kia; các mã thoát đã có (0/1/2/130) vẫn giữ nguyên.
        try:
            return cmd_benchmark(args)
        except KeyboardInterrupt:
            print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001 - lỗi cuối cùng phải có thông báo
            print(f"Lỗi không mong muốn: {exc}", file=sys.stderr)
            return 1
    elif args.command == "calibrate":
        try:
            return cmd_calibrate(args)
        except KeyboardInterrupt:
            print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001 - lỗi cuối cùng phải có thông báo
            print(f"Lỗi không mong muốn: {exc}", file=sys.stderr)
            return 1
    elif args.command == "replay":
        try:
            return cmd_replay(args)
        except KeyboardInterrupt:
            print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001 - lỗi cuối cùng phải có thông báo
            print(f"Lỗi không mong muốn: {exc}", file=sys.stderr)
            return 1
    elif args.command == "speak-test":
        try:
            return cmd_speak_test(args)
        except KeyboardInterrupt:
            print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001 - lỗi cuối cùng phải có thông báo
            print(f"Lỗi không mong muốn: {exc}", file=sys.stderr)
            return 1

    # ``subparsers(dest="command", required=True)`` chỉ cho qua bốn lệnh đã
    # khai báo và đều có nhánh riêng ở trên, nên không còn lệnh nào rơi xuống
    # đây. Giữ một lỗi rõ ràng thay vì trả 0 trong im lặng, phòng khi sau này
    # có người thêm lệnh vào parser mà quên thêm nhánh dispatch.
    print(f"Lệnh không có nhánh xử lý: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
