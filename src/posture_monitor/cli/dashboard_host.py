"""Khởi tạo và chạy nền bộ dịch vụ Dashboard Web + Storage + People + Speaker + StudySession."""

from __future__ import annotations

import threading
from pathlib import Path


def _build_face_processor(recognizer, face, logger, *, skip_gate=None, note_box=None):
    """Đóng gói đường ống khuôn mặt có cổng nhịp ``face.interval_s`` cho ``PeopleService``."""
    from .. import cli as _cli  # noqa: PLC0415
    from ..domain.people_service import OBSERVATION_SKIPPED  # noqa: PLC0415
    from ..vision.faces import build_face_processor  # noqa: PLC0415

    return build_face_processor(
        recognizer,
        face,
        logger,
        skipped_sentinel=OBSERVATION_SKIPPED,
        skip_gate=skip_gate,
        note_box=note_box,
        clock=lambda: _cli.time.monotonic(),
    )


def _create_study_session(config, logger):
    """Dựng :class:`~posture_monitor.domain.study_session.StudySession` từ cấu hình (không ném)."""
    try:
        from ..domain.study_session import StudySession  # noqa: PLC0415

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
    """Dựng :class:`~posture_monitor.domain.people_service.PeopleService` thật khi ``face.enabled`` bật."""
    face = getattr(config, "face", None)
    if face is None or not getattr(face, "enabled", False):
        return None
    try:
        from .. import cli as _cli  # noqa: PLC0415
        from ..core.config import resolve_model_path  # noqa: PLC0415
        from ..domain.people_service import PeopleService  # noqa: PLC0415
        from ..vision.faces import FaceRecognizer, FaceStore  # noqa: PLC0415

        store_path = Path(face.store_path)
        store_dir = store_path.parent if str(store_path.parent) else Path(".")
        store = FaceStore(store_dir)
        recognizer = FaceRecognizer(
            resolve_model_path(face.detector),
            resolve_model_path(face.recognizer),
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
            _cli._build_face_processor(
                recognizer,
                face,
                logger,
                skip_gate=service.is_enrolling,
                note_box=service.note_face_box,
            )
        )
        return service
    except Exception:  # noqa: BLE001
        logger.exception(
            "Không dựng được dịch vụ người học; dashboard vẫn chạy nhưng các "
            "tính năng người học sẽ trả 503."
        )
        return None


def _create_speaker(config, logger):
    """Dựng loa cảnh báo một lần dùng chung cho cả vòng lặp và dashboard."""
    from ..alerts.speaker_alert import SpeakerAlerter  # noqa: PLC0415

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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chưa chuẩn bị được giọng đọc cảnh báo: %s", exc)
    return alerter


def _serve_web(app, config, logger) -> None:
    """Chạy dashboard web trong luồng nền; cổng bận chỉ là cảnh báo."""
    from ..web import run_server  # noqa: PLC0415

    try:
        run_server(app, config)
    except (OSError, SystemExit) as exc:
        logger.warning(
            "Không mở được dashboard web (%s); chương trình vẫn giám sát. "
            "Kiểm tra 'web.host'/'web.port' và cổng đã bị chiếm.",
            exc,
        )


class _Dashboard:
    """Tổ hợp ``DashboardState`` + ``Storage`` + dịch vụ phụ trợ + Flask server chạy nền."""

    def __init__(self, config, logger) -> None:
        from ..storage import Storage  # noqa: PLC0415
        from ..web import DashboardState, create_app  # noqa: PLC0415

        self.config = config
        self.logger = logger
        self.state = DashboardState()
        self.storage = Storage(config)
        self.storage.open()
        self.people = _create_people_service(config, logger)
        self.study_session = _create_study_session(config, logger)
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
