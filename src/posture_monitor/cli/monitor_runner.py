"""Bộ thực thi vòng lặp giám sát chính (:class:`MonitorRunner` & :func:`_monitor_loop`).

Chia tách hàm ``_monitor_loop`` dài 835 dòng trước đây thành một lớp có các
phương thức nhỏ, đơn trách nhiệm, không còn phụ thuộc ngược lên ``web.app``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from ..core.labels import (
    ALERT_EVENT_TYPE,
    EVENT_ALERT_END,
    EVENT_ALERT_START,
    EVENT_SPEAK_FAILED,
    EVENT_SPEAK_OK,
    LABEL_ORDER,
    LABEL_TEXT,
    PAUSED_MESSAGE,
    STATE_ABSENT,
    STATE_PAUSED,
)
from .parser import QUIT_KEYS, WINDOW_NAME


def _presence_state(state_text: str) -> str:
    """Đổi trạng thái máy trạng thái sang tín hiệu ``presence`` của dashboard."""
    from ..domain import presence as presence_mod  # noqa: PLC0415
    from ..domain import state as state_mod  # noqa: PLC0415

    if state_text == state_mod.STATE_ABSENT:
        return presence_mod.STATE_ABSENT
    return presence_mod.STATE_PRESENT


def _loc_nhan_tu_the(labels, enabled: bool):
    """Lọc nhãn tư thế khỏi tập nhãn sinh cảnh báo (giữ ``ABSENT`` vô điều kiện)."""
    from ..vision.classifier import filter_posture_labels  # noqa: PLC0415

    return filter_posture_labels(labels, enabled)


def _warn_phone_threshold_mismatch(config, phone_ready: bool, logger) -> None:
    """Cảnh báo một lần lúc khởi động nếu ``phone.hold_s < schedule.kinds.phone.hold_s``."""
    if not phone_ready:
        return
    try:
        dashboard_hold = float(config.phone.hold_s)
        kind = (config.schedule.kinds or {}).get("phone")
        speaker_hold = float(kind.hold_s) if kind is not None else None
    except (AttributeError, TypeError, ValueError):
        return
    if speaker_hold is None or dashboard_hold >= speaker_hold:
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


class MonitorRunner:
    """Điều phối từng nhịp của vòng lặp giám sát trực tiếp."""

    def __init__(
        self,
        estimator,
        source,
        config,
        logger,
        *,
        state=None,
        storage=None,
        sensor=None,
        dispatcher=None,
        stream_enabled: bool = False,
        people=None,
        speaker=None,
        show_preview: bool = True,
        study_session=None,
        clock=None,
        wall_clock=None,
    ) -> None:
        from .. import cli as _cli  # noqa: PLC0415
        from ..alerts.speaker_alert import SpeakerAlerter  # noqa: PLC0415
        from ..domain.presence import DEFAULT_ABSENT_HOLD_S, PresenceTracker  # noqa: PLC0415
        from ..domain.state import Smoother, StateMachine  # noqa: PLC0415
        from ..vision.calibration import (  # noqa: PLC0415
            DEFAULT_PATH,
            Baseline,
            CalibrationError,
        )
        from ..vision.calibration import load as load_calibration  # noqa: PLC0415
        from ..vision.phone_detector import PhoneSignal  # noqa: PLC0415

        self._cli = _cli
        self.estimator = estimator
        self.source = source
        self.config = config
        self.logger = logger
        self.state = state
        self.storage = storage
        self.sensor = sensor
        self.dispatcher = dispatcher
        self.stream_enabled = bool(stream_enabled)
        self.people = people
        self.show_preview = bool(show_preview)
        self.study_session = study_session

        self.interval = 1.0 / max(1, config.model.target_fps)
        self.view = config.camera.view
        self.kp_conf_min = config.model.kp_conf_min
        self.min_distance_cm = float(config.sensors.min_distance_cm)

        self.baseline, self.feature_baseline = self._load_baseline(
            DEFAULT_PATH, Baseline, CalibrationError, load_calibration
        )
        self.smoother = Smoother(float(config.timing.smooth_window_s))
        self.machine = StateMachine(config.timing)
        self.loop_start = _cli.time.monotonic()

        self.active_alerts: dict[str, str] = {}
        self.last_alert_at: dict[str, datetime] = {}
        self.stranger_since: float | None = None
        self.session_was_active: bool | None = None

        self.people_errors = 0
        self.session_errors = 0
        self.alert_errors = 0
        self.event_errors = 0

        self.alert_clock = (
            clock if clock is not None else (lambda: self._cli.time.monotonic())
        )
        self.alert_wall_clock = wall_clock if wall_clock is not None else datetime.now
        self.schedule_cfg = getattr(config, "schedule", None)

        self.presence_tracker = self._init_presence_tracker(
            PresenceTracker, DEFAULT_ABSENT_HOLD_S
        )
        self.phone_signal = self._init_phone_signal(PhoneSignal)
        _warn_phone_threshold_mismatch(config, self.phone_signal is not None, logger)
        self.speaker_alerter = self._init_speaker(speaker, SpeakerAlerter)
        self.preview_ok = True

    def _load_baseline(
        self, default_path: str, baseline_cls, err_cls, loader
    ) -> tuple[Any, Any]:
        try:
            loaded = loader(default_path)
            return loaded, loaded
        except FileNotFoundError:
            self.logger.warning(
                "Chưa có %s: chạy không baseline, các nhãn phụ thuộc hiệu chỉnh "
                "(HEAD_DOWN/TOO_CLOSE/LEAN/HEAD_TILT/LOOK_AWAY) không được đánh "
                "giá. Chạy 'python -m posture_monitor calibrate' để hiệu chỉnh.",
                default_path,
            )
        except err_cls as exc:
            self.logger.warning(
                "%s hỏng (%s); chạy không baseline. Chạy lại lệnh 'calibrate'.",
                default_path,
                exc,
            )
        empty = baseline_cls.empty(
            view=self.view,
            width=int(self.config.camera.width),
            height=int(self.config.camera.height),
        )
        return empty, None

    def _init_presence_tracker(self, tracker_cls, default_hold: float):
        try:
            presence_cfg = getattr(self.config, "presence", None)
            return tracker_cls(
                absent_hold_s=(
                    presence_cfg.absent_grace_s
                    if presence_cfg is not None
                    else default_hold
                ),
                kp_conf_min=self.kp_conf_min,
                clock=self.alert_clock,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Không dựng được bộ theo dõi hiện diện (%s); cảnh báo 'rời "
                "khung hình' sẽ không chạy. Các chức năng khác vẫn chạy.",
                exc,
            )
            return None

    def _init_phone_signal(self, signal_cls):
        try:
            return signal_cls(self.config)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Không dựng được bộ phát hiện điện thoại (%s); cảnh báo 'dùng "
                "điện thoại' sẽ không chạy. Các chức năng khác vẫn chạy.",
                exc,
            )
            return None

    def _init_speaker(self, injected_speaker, alerter_cls):
        try:
            alerter = (
                injected_speaker
                if injected_speaker is not None
                else alerter_cls.from_config(self.config)
            )
            if alerter.available:
                alerter.prepare()
            return alerter
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Không dựng được loa cảnh báo (%s); cảnh báo trong giờ học chỉ "
                "được ghi log. Các chức năng khác vẫn chạy.",
                exc,
            )
            return None

    def _disable_preview(self, exc: BaseException) -> None:
        if not self.preview_ok:
            return
        self.preview_ok = False
        self.logger.warning(
            "Không dùng được cửa sổ xem trước OpenCV (%s); vẫn tiếp tục giám "
            "sát, xem trực tiếp trên dashboard web. Sẽ không thử mở lại cửa "
            "sổ trong phiên chạy này.",
            exc,
        )

    def _setup_preview(self) -> None:
        if not self.show_preview:
            self.preview_ok = False
            self.logger.info(
                "Không mở cửa sổ xem trước (mặc định); xem hình trên dashboard web."
            )
            return
        try:
            cv2 = self._cli.cv2
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        except Exception as exc:  # noqa: BLE001
            self._disable_preview(exc)
        else:
            self.logger.info("Cửa sổ xem trước đã mở. Bấm q hoặc Esc để thoát.")

    def _teardown_preview(self) -> None:
        if not self.preview_ok:
            return
        try:
            self._cli.cv2.destroyAllWindows()
        except Exception as exc:  # noqa: BLE001
            self._disable_preview(exc)

    def _sync_study_session(self) -> bool:
        from ..domain.study_session import STATE_RUNNING  # noqa: PLC0415

        session_active = True
        session_snapshot = None
        if self.study_session is not None:
            try:
                session_snapshot = self.study_session.tick()
                session_active = session_snapshot.state == STATE_RUNNING
            except Exception as exc:  # noqa: BLE001
                session_active = True
                if self.session_errors == 0:
                    self.logger.warning(
                        "Không đọc được trạng thái phiên học (%s); tạm coi như "
                        "đang trong phiên. Các lỗi sau không ghi log để tránh "
                        "ngập log.",
                        exc,
                    )
                self.session_errors += 1
            if session_snapshot is not None and session_snapshot.finished_message:
                self.logger.info(
                    "PHIÊN HỌC: %s (đã học %d phút).",
                    session_snapshot.finished_message,
                    session_snapshot.minutes,
                )

        if session_active != self.session_was_active:
            first_frame = self.session_was_active is None
            self.session_was_active = session_active
            self._reset_session_counters()
            minutes = getattr(session_snapshot, "minutes", "?")
            if first_frame:
                if session_active:
                    self.logger.info(
                        "Đang trong phiên học %s phút: phân tích tư thế và dò "
                        "điện thoại đang chạy.",
                        minutes,
                    )
                else:
                    self.logger.info(
                        "Chưa bắt đầu phiên học: đang xem camera và nhận diện "
                        "khuôn mặt; chưa phân tích tư thế, chưa dò điện thoại, "
                        "chưa cảnh báo."
                    )
            elif session_active:
                self.logger.info(
                    "Bắt đầu phiên học %s phút: bật phân tích tư thế và dò điện thoại.",
                    minutes,
                )
            else:
                self.logger.info(
                    "Kết thúc phiên học: tắt phân tích tư thế và dò điện thoại; "
                    "vẫn nhận diện khuôn mặt và xem camera."
                )
        return session_active

    def _reset_session_counters(self) -> None:
        try:
            self.smoother.reset()
            self.machine.reset()
        except Exception:  # noqa: BLE001
            pass
        for tracker in (self.presence_tracker, self.phone_signal):
            try:
                if tracker is not None:
                    tracker.reset()
            except Exception:  # noqa: BLE001
                pass
        self.active_alerts.clear()
        self.last_alert_at.clear()
        self.stranger_since = None

    def _evaluate_posture(self, frame, now: float, session_active: bool):
        from ..domain.state import StateUpdate  # noqa: PLC0415
        from ..hardware.sensors import apply_distance  # noqa: PLC0415
        from ..vision.classifier import classify  # noqa: PLC0415
        from ..vision.features import extract  # noqa: PLC0415
        from ..vision.overlay import draw_pose  # noqa: PLC0415

        pose = self.estimator.detect(frame) if session_active else None
        if pose is None:
            features = extract(
                None,
                None,
                view=self.view,
                kp_conf_min=self.kp_conf_min,
                baseline=self.feature_baseline,
            )
            drawn = frame
        else:
            features = extract(
                pose.xy,
                pose.conf,
                view=self.view,
                kp_conf_min=self.kp_conf_min,
                baseline=self.feature_baseline,
            )
            drawn = draw_pose(
                frame,
                pose.xy,
                pose.conf,
                self.config.model.kp_conf_min,
                copy=False,
            )

        distance_cm = None if self.sensor is None else self.sensor.read()

        if session_active:
            smoothed = self.smoother.push(now, features)
            classification = classify(smoothed, self.baseline, self.config.thresholds)
            labels = apply_distance(
                classification.labels, distance_cm, self.min_distance_cm
            )
            labels = self._cli._loc_nhan_tu_the(
                labels, self.config.posture_labels_enabled
            )
            update = self.machine.update(now, labels, classification.score)
            for event in update.events:
                if event.label is None:
                    continue
                if event.type == EVENT_ALERT_START:
                    self.active_alerts[event.label] = LABEL_TEXT.get(
                        event.label, event.label
                    )
                elif event.type == EVENT_ALERT_END:
                    self.active_alerts.pop(event.label, None)
            alert_text = (
                ", ".join(
                    self.active_alerts[label] for label in sorted(self.active_alerts)
                )
                if self.active_alerts
                else None
            )
        else:
            update = StateUpdate(
                now=now,
                state=STATE_PAUSED,
                labels=frozenset(),
                score=0.0,
                sitting_s=0.0,
            )
            alert_text = None

        return pose, drawn, update, alert_text, distance_cm

    def _sync_dashboard_and_storage(
        self, update, distance_cm: float | None, alert_text: str | None, session_active: bool
    ) -> None:
        if self.state is not None:
            self.state.update(
                state=update.state,
                labels=[label for label in LABEL_ORDER if label in update.labels],
                score=update.score,
                sitting_s=update.sitting_s,
                distance_cm=distance_cm,
                alert=alert_text,
                message="" if session_active else PAUSED_MESSAGE,
            )
            if self.state.consume_calibration_request():
                self.logger.info(
                    "Dashboard có yêu cầu hiệu chỉnh lại: hiệu chỉnh cần người "
                    "ngồi đúng tư thế nên không chạy tự động ở đây. Hãy thoát "
                    "và chạy 'python -m posture_monitor calibrate', rồi khởi "
                    "động lại 'run'."
                )
        if self.storage is not None and session_active:
            self.storage.record(update, distance_cm)

    def _observe_people(self, frame, update, session_active: bool) -> None:
        if self.people is None:
            return
        try:
            people_now = self._cli.time.monotonic()
            if session_active:
                self.people.update_signals(
                    presence=_presence_state(update.state),
                    now=people_now,
                )
            self.people.observe(frame, people_now)
        except Exception as exc:  # noqa: BLE001
            self.people_errors += 1
            if self.people_errors == 1:
                self.logger.warning(
                    "Dịch vụ người học lỗi khi nhận khung (%s); vẫn giám sát, "
                    "chỉ tính năng người học bị ảnh hưởng. Các lỗi sau không "
                    "ghi log để tránh ngập log.",
                    exc,
                )

    def _evaluate_study_alerts(self, frame, pose, session_active: bool) -> float | None:
        if not (
            session_active
            and self.schedule_cfg is not None
            and (
                self.presence_tracker is not None
                or self.phone_signal is not None
                or self.speaker_alerter is not None
                or self.people is not None
            )
        ):
            return None

        from ..domain import schedule as schedule_mod  # noqa: PLC0415
        from ..domain.people_service import (  # noqa: PLC0415
            IDENTITY_MISMATCH,
            PHONE_STATE_NONE,
            PHONE_STATE_USE,
        )
        from ..vision.pose import pose_to_keypoints_array  # noqa: PLC0415

        alert_now: float | None = None
        try:
            alert_now = self.alert_clock()
            held: dict[str, float] = {}
            if self.presence_tracker is not None:
                presence_result = self.presence_tracker.update(pose)
                held["leave_frame"] = presence_result.absent_for_s

            if self.phone_signal is not None:
                phone_result = self.phone_signal.observe(
                    frame, pose_to_keypoints_array(pose), alert_now
                )
                held["phone"] = (
                    self.phone_signal.held_s if phone_result is not None else 0.0
                )
                if self.people is not None:
                    try:
                        self.people.note_phone(
                            PHONE_STATE_USE
                            if phone_result is not None and self.phone_signal.in_use
                            else PHONE_STATE_NONE,
                            now=alert_now,
                        )
                    except Exception:  # noqa: BLE001
                        pass

            if self.people is not None:
                try:
                    identity = self.people.signals().get("identity") or {}
                    selected = self.people.selected_person()
                except Exception:  # noqa: BLE001
                    identity, selected = {}, None
                if (
                    identity.get("fresh") is True
                    and identity.get("state") == IDENTITY_MISMATCH
                    and selected is not None
                ):
                    if self.stranger_since is None:
                        self.stranger_since = alert_now
                    held["stranger"] = max(0.0, alert_now - self.stranger_since)
                else:
                    self.stranger_since = None

            decision = schedule_mod.should_alert(
                self.schedule_cfg,
                self.alert_wall_clock(),
                held=held,
                last_alert_at=self.last_alert_at,
            )
            if decision is not None:
                self._record_and_speak_alert(decision, held, alert_now)
        except Exception as exc:  # noqa: BLE001
            self.alert_errors += 1
            if self.alert_errors == 1:
                self.logger.warning(
                    "Tính năng cảnh báo trong giờ học lỗi khi xử lý khung (%s); "
                    "vẫn giám sát, chỉ cảnh báo bị ảnh hưởng. Các lỗi sau không "
                    "ghi log để tránh ngập log.",
                    exc,
                )
        return alert_now

    def _record_and_speak_alert(
        self, decision, held: dict[str, float], alert_now: float
    ) -> None:
        from ..domain.state import Event  # noqa: PLC0415

        muted = bool(self.state is not None and self.state.muted)
        event_type = ALERT_EVENT_TYPE.get(decision.kind)
        if event_type is None:
            self.logger.warning(
                "Không có loại sự kiện cho cảnh báo '%s'; không ghi vào bảng events.",
                decision.kind,
            )
        elif self.storage is not None:
            try:
                self.storage.record_event(
                    Event(
                        ts=float(alert_now),
                        type=event_type,
                        label=decision.kind,
                        duration_s=float(held.get(decision.kind, 0.0)),
                        alert=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.event_errors += 1
                if self.event_errors == 1:
                    self.logger.warning(
                        "Không ghi được sự kiện cảnh báo '%s' vào DB (%s); vẫn "
                        "giám sát tiếp. Các lỗi sau không ghi log để tránh ngập log.",
                        decision.kind,
                        exc,
                    )

        outcome = None
        if self.speaker_alerter is not None:
            outcome = self.speaker_alerter.alert_many(
                (decision.kind,), now=alert_now, muted=muted
            )
            if outcome.spoken:
                self.logger.info(
                    "SPEAK_OK: đã phát cảnh báo '%s' ra loa camera.",
                    decision.kind,
                )
                if self.storage is not None:
                    self.storage.record_event(
                        Event(
                            ts=float(alert_now),
                            type=EVENT_SPEAK_OK,
                            label=decision.kind,
                            alert=False,
                        )
                    )
            if outcome.error is not None:
                self.logger.warning(
                    "SPEAK_FAILED: cảnh báo '%s' không phát được ra loa (%s); "
                    "vẫn giám sát tiếp.",
                    decision.kind,
                    outcome.error,
                )
                if self.storage is not None:
                    self.storage.record_event(
                        Event(
                            ts=float(alert_now),
                            type=EVENT_SPEAK_FAILED,
                            label=decision.kind,
                            alert=False,
                        )
                    )

        if outcome is None or not outcome.retryable:
            self.last_alert_at[decision.kind] = self.alert_wall_clock()

    def _dispatch_gpio(self, update, session_active: bool) -> None:
        if self.dispatcher is None:
            return
        if session_active:
            if (self.state is not None and self.state.muted) or not (
                self.config.alerts.gpio_alert_enabled
            ):
                self.dispatcher.dispatch(replace(update, alerts=()))
            else:
                self.dispatcher.dispatch(update)
        else:
            self.dispatcher.dispatch(replace(update, state=STATE_ABSENT, alerts=()))

    def _render_and_publish(
        self, drawn, session_active: bool, alert_now: float | None
    ) -> int | None:
        from ..vision.overlay import draw_detections  # noqa: PLC0415

        cv2 = self._cli.cv2
        phone_boxes = ()
        face_box = None
        if self.phone_signal is not None and session_active:
            if alert_now is None:
                try:
                    alert_now = self.alert_clock()
                except Exception:  # noqa: BLE001
                    alert_now = None
            try:
                if alert_now is not None:
                    phone_boxes = self.phone_signal.boxes(alert_now)
            except Exception:  # noqa: BLE001
                phone_boxes = ()

        if self.people is not None:
            try:
                face_box = self.people.latest_face_box()
            except Exception:  # noqa: BLE001
                face_box = None

        if phone_boxes or face_box is not None:
            drawn = draw_detections(
                drawn,
                phone_boxes=phone_boxes,
                face_box=face_box,
                copy=True,
            )

        if self.state is not None and self.stream_enabled:
            ok, buffer = cv2.imencode(".jpg", drawn)
            if ok:
                self.state.set_frame(buffer.tobytes())

        if self.preview_ok:
            try:
                cv2.imshow(WINDOW_NAME, drawn)
                key = cv2.waitKey(1) & 0xFF
            except Exception as exc:  # noqa: BLE001
                self._disable_preview(exc)
            else:
                if key in QUIT_KEYS:
                    self.logger.info("Nhận phím thoát; đóng cửa sổ.")
                    return 0
                try:
                    visible = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE)
                except Exception as exc:  # noqa: BLE001
                    self._disable_preview(exc)
                else:
                    if visible < 1:
                        self.logger.info("Cửa sổ đã đóng; thoát.")
                        return 0
        return None

    def run(self) -> int:
        """Chạy vòng lặp giám sát cho tới khi hết khung hoặc người dùng thoát."""
        self._setup_preview()
        try:
            while True:
                started = self._cli.time.monotonic()
                frame = self.source.read()
                if frame is None:
                    self.logger.error("Không còn khung nào từ camera; dừng xem trước.")
                    return 1

                now = self._cli.time.monotonic() - self.loop_start
                session_active = self._sync_study_session()
                pose, drawn, update, alert_text, distance_cm = self._evaluate_posture(
                    frame, now, session_active
                )
                self._sync_dashboard_and_storage(
                    update, distance_cm, alert_text, session_active
                )
                self._observe_people(frame, update, session_active)
                alert_now = self._evaluate_study_alerts(frame, pose, session_active)
                self._dispatch_gpio(update, session_active)

                exit_code = self._render_and_publish(drawn, session_active, alert_now)
                if exit_code is not None:
                    return exit_code

                elapsed = self._cli.time.monotonic() - started
                remaining = self.interval - elapsed
                if remaining > 0:
                    self._cli.time.sleep(remaining)
        finally:
            self._teardown_preview()


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
    """Hàm bao tương thích cho :class:`MonitorRunner`."""
    return MonitorRunner(
        estimator,
        source,
        config,
        logger,
        state=state,
        storage=storage,
        sensor=sensor,
        dispatcher=dispatcher,
        stream_enabled=stream_enabled,
        people=people,
        speaker=speaker,
        show_preview=show_preview,
        study_session=study_session,
        clock=clock,
        wall_clock=wall_clock,
    ).run()
