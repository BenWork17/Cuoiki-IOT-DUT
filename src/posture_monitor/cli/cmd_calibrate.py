"""Lệnh ``calibrate``: đếm ngược, thu khung ở tư thế chuẩn và lưu ``calibration.json``."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..core.config import ConfigError, redact_camera_source
from ..core.logging_setup import setup_logging


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``calibrate``: đếm ngược → thu khung → lưu baseline."""
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

    from ..vision.calibration import (  # noqa: PLC0415
        CAPTURE_S,
        COUNTDOWN_S,
        CalibrationError,
        compute_baseline,
        save,
    )
    from ..vision.features import extract  # noqa: PLC0415

    camera = config.camera
    view = camera.view
    kp_conf_min = config.model.kp_conf_min
    output = Path(args.output)
    sample_retry_s = 0.05

    if args.no_gpio:
        logger.info(
            "--no-gpio: calibrate không dùng GPIO nên cờ này không có tác dụng (no-op)."
        )

    source = _cli.capture_from_config(config)
    if source is None:
        logger.error(
            "Không mở được nguồn ảnh '%s' nên không thể hiệu chỉnh. Kiểm tra "
            "phần cứng bằng 'python scripts/camera_probe.py', hoặc chạy "
            "'python -m posture_monitor run' để xem trực tiếp.",
            redact_camera_source(camera.source),
        )
        return 1

    try:
        from ..vision.pose import PoseError, PoseEstimator  # noqa: PLC0415

        try:
            estimator = PoseEstimator(config)
        except PoseError as exc:
            logger.error("%s", exc)
            return 2

        from .benchmark import WARMUP_FRAMES  # noqa: PLC0415

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
            except Exception as exc:  # noqa: BLE001
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

        remaining = float(COUNTDOWN_S)
        while remaining > 0:
            logger.info("Bắt đầu thu sau %.0f giây...", remaining)
            step = min(1.0, remaining)
            _cli.time.sleep(step)
            remaining -= step

        logger.info(
            "Bắt đầu thu %.0f giây ở nhịp tự nhiên của vòng lặp (không chờ "
            "theo target_fps: lấy mẫu càng nhiều thì trung vị càng vững).",
            CAPTURE_S,
        )

        frames = []
        read_count = 0
        deadline = _cli.time.monotonic() + float(CAPTURE_S)
        while _cli.time.monotonic() < deadline:
            frame = source.read()
            if frame is None:
                logger.warning("Không đọc được khung từ nguồn ảnh; bỏ qua nhịp này.")
                _cli.time.sleep(sample_retry_s)
                continue

            read_count += 1
            pose = estimator.detect(frame)
            if pose is None:
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
