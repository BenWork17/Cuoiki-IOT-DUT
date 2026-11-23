"""Lệnh ``run`` và ``benchmark`` (chuyển tiếp)."""

from __future__ import annotations

import argparse
import builtins
from pathlib import Path

from ..core.config import ConfigError, redact_camera_source
from ..core.logging_setup import setup_logging
from .parser import SAVE_OVERLAY_MAX_FRAMES


def _print_status(
    config, hardware, source, view: str, backend: str, show_preview: bool = False
) -> None:
    """In khối trạng thái khởi động cho người dùng."""
    from .. import cli as _cli  # noqa: PLC0415

    out = getattr(_cli, "print", builtins.print)
    camera_cfg = config.camera
    out()
    out("=" * 60)
    out("  GIÁM SÁT HỌC TẬP — TRẠNG THÁI KHỞI ĐỘNG")
    out("=" * 60)
    out(f"  Cấu hình      : {config.path or '(mặc định)'}")
    out(f"  Nguồn camera  : {redact_camera_source(camera_cfg.source)}")
    out(f"  Độ phân giải  : {camera_cfg.width}x{camera_cfg.height}, view={view}")
    out(f"  Model         : {config.model.name} ({backend}), imgsz={config.model.imgsz}")

    if source is None:
        out("  Camera        : KHÔNG MỞ ĐƯỢC (xem log phía trên)")
    else:
        out(f"  Camera        : đã mở (backend={source.backend})")

    state = getattr(hardware, "state", "?")
    out(f"  Phần cứng     : {type(hardware).__name__}, trạng thái giả={state}")
    out(
        "  Ngưỡng chính  : "
        f"head_down={config.thresholds.head_down_ratio}, "
        f"too_close={config.thresholds.too_close_ratio}, "
        f"shoulder_tilt={config.thresholds.shoulder_tilt_deg}°"
    )
    out(
        "  Thời gian     : "
        f"bad_hold={config.timing.bad_hold_s}s, "
        f"good_hold={config.timing.good_hold_s}s, "
        f"cooldown={config.timing.alert_cooldown_s}s"
    )
    out("-" * 60)
    if show_preview:
        out("  Vẽ xương trong cửa sổ OpenCV; bấm q hoặc Esc để thoát.")
    else:
        out("  Không mở cửa sổ OpenCV. Xem hình trực tiếp trên dashboard web;")
        out("  dừng bằng Ctrl+C. (Muốn mở cửa sổ: thêm cờ --preview.)")
    out("  Ba tín hiệu: có mặt / dùng điện thoại / đúng người.")
    session_cfg = getattr(config, "session", None)
    if session_cfg is not None and not getattr(session_cfg, "auto_start", False):
        out("-" * 60)
        out("  Phiên học      : TẮT cho tới khi bấm “Bắt đầu học” trên dashboard web.")
        out(
            f"                   Model AI chỉ chạy trong phiên "
            f"(mặc định {getattr(session_cfg, 'default_minutes', 60)} phút)."
        )
        out("                   Ngoài phiên vẫn xem camera và nhận diện khuôn mặt.")
    out("=" * 60)
    out()


def _save_one_overlay(estimator, source, config, target: Path, logger) -> int:
    """Lưu **một** khung đã vẽ ra ``target`` rồi trả mã thoát."""
    from .. import cli as _cli  # noqa: PLC0415
    from ..vision.overlay import draw_pose  # noqa: PLC0415

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
    if not _cli.cv2.imwrite(str(target), drawn):
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


def cmd_run(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``run``: cấu hình → phần cứng → camera → pose + dashboard + vòng lặp."""
    from .. import cli as _cli  # noqa: PLC0415

    logger = setup_logging(args.log_level)

    try:
        config = _cli.load_config(args.config)
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

    from ..hardware import create_hardware  # noqa: PLC0415

    hardware = create_hardware(config, no_gpio=args.no_gpio)

    source = _cli.capture_from_config(config)
    if source is None:
        logger.error(
            "Không mở được nguồn ảnh '%s' nên không thể suy luận pose. Chạy "
            "'python scripts/camera_probe.py' để kiểm tra phần cứng.",
            redact_camera_source(config.camera.source),
        )
        hardware.close()
        return 1

    from ..vision.pose import PoseError, PoseEstimator  # noqa: PLC0415

    try:
        estimator = PoseEstimator(config)
    except PoseError as exc:
        logger.error("%s", exc)
        source.close()
        hardware.close()
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        raise

    try:
        if args.save_overlay:
            return _cli._save_one_overlay(
                estimator, source, config, Path(args.save_overlay), logger
            )

        show_preview = bool(getattr(args, "preview", False))
        _cli._print_status(
            config, hardware, source, view, estimator.backend, show_preview
        )

        from ..alerts import AlertDispatcher  # noqa: PLC0415
        from ..hardware.sensors import create_sensor  # noqa: PLC0415

        sensor = None
        dispatcher = None
        dashboard = None
        try:
            dashboard = _cli._Dashboard(config, logger)
            dashboard.start()
            sensor = create_sensor(config)
            dispatcher = AlertDispatcher(hardware, config.alerts)
            return _cli._monitor_loop(
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
    """Chuyển tiếp lệnh ``benchmark`` sang :func:`posture_monitor.cli.benchmark.main`."""
    from . import benchmark as bench  # noqa: PLC0415

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
