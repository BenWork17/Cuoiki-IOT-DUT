"""Điểm vào dòng lệnh: ``python -m posture_monitor <lệnh>``.

Các lệnh theo spec v2 §7::

    python -m posture_monitor run [--config config.yaml] [--no-gpio] [--view front|side]
    python -m posture_monitor calibrate
    python -m posture_monitor replay video.mp4 [--no-gpio] [--save-report out.json]
    python -m posture_monitor benchmark [--seconds 60]

``run`` (mốc M1) mở camera, suy luận pose và vẽ 17 keypoint + xương lên khung
hình trực tiếp; bấm ``q`` hoặc ``Esc`` để thoát. Cờ ``--save-overlay`` lưu
**một** khung đã vẽ ra file ảnh rồi thoát, dùng để kiểm chứng trên máy không
có màn hình. Ba lệnh còn lại in thông báo "chưa triển khai" và thoát với mã 0.

Không in bất kỳ số liệu hiệu năng nào: mọi chỉ số FPS/độ trễ phải do
``benchmark`` sinh ra trên máy đích (spec §11.6).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

from . import __version__
from .capture import capture_from_config
from .config import ConfigError, load_config
from .logging_setup import setup_logging

#: Tên cửa sổ xem trước của OpenCV.
WINDOW_NAME = "Giam sat tu the — bam q de thoat"

#: Phím thoát (mã ASCII của ``q`` và ``Esc``).
QUIT_KEYS = (ord("q"), ord("Q"), 27)

#: Số khung tối đa đọc khi chờ có người cho ``--save-overlay``. Camera mới mở
#: thường trả vài khung tối/sai phơi sáng; đọc vài khung giúp ảnh lưu ra đúng
#: cảnh hơn. Không phải ngưỡng nghiệp vụ nên để trong code.
SAVE_OVERLAY_MAX_FRAMES = 10

#: Nội dung in ra cho các lệnh chưa có trong phạm vi M0/M1.
NOT_IMPLEMENTED = (
    "Lệnh '{name}' chưa triển khai (đang ở mốc M1). "
    "Xem docs/SPEC_V2.md §10 để biết lịch triển khai."
)


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

    run = subparsers.add_parser(
        "run", help="Chạy giám sát trực tiếp từ camera."
    )
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
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )

    calibrate = subparsers.add_parser(
        "calibrate", help="Hiệu chỉnh tư thế chuẩn (chưa triển khai)."
    )
    calibrate.add_argument("--config", default="config.yaml")

    replay = subparsers.add_parser(
        "replay", help="Chạy lại trên video có sẵn (chưa triển khai)."
    )
    replay.add_argument("video", help="Đường dẫn video.")
    replay.add_argument("--no-gpio", action="store_true")
    replay.add_argument("--save-report", default=None)

    benchmark = subparsers.add_parser(
        "benchmark", help="Đo hiệu năng trên máy đích (chưa triển khai)."
    )
    benchmark.add_argument("--seconds", type=int, default=60)

    return parser


def _print_status(config, hardware, source, view: str, backend: str) -> None:
    """In khối trạng thái khởi động cho người dùng."""
    camera_cfg = config.camera
    print()
    print("=" * 60)
    print("  GIÁM SÁT TƯ THẾ — TRẠNG THÁI KHỞI ĐỘNG (M1)")
    print("=" * 60)
    print(f"  Cấu hình      : {config.path or '(mặc định)'}")
    print(f"  Nguồn camera  : {camera_cfg.source}")
    print(f"  Độ phân giải  : {camera_cfg.width}x{camera_cfg.height}, view={view}")
    print(f"  Model         : {config.model.name} ({backend}), imgsz={config.model.imgsz}")

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
    print("  Vẽ xương trực tiếp; bấm q hoặc Esc trong cửa sổ để thoát.")
    print("  Phân loại tư thế chưa triển khai ở mốc M1 (xem spec §10).")
    print("=" * 60)
    print()


def _save_one_overlay(
    estimator, source, config, target: Path, logger
) -> int:
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
        logger.error(
            "Không đọc được khung nào từ camera; không lưu được %s.", target
        )
        return 1

    pose = estimator.detect(frame)
    persons = estimator.last_person_count
    if pose is None:
        drawn = frame.copy()
    else:
        drawn = draw_pose(
            frame, pose.xy, pose.conf, config.model.kp_conf_min
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target), drawn):
        logger.error(
            "Không ghi được file ảnh '%s' (kiểm tra phần mở rộng và quyền "
            "ghi).",
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


def _preview_loop(estimator, source, config, logger) -> int:
    """Vòng lặp xem trước: đọc khung → suy luận → vẽ → hiện; ``q`` để thoát."""
    from .overlay import draw_pose  # noqa: PLC0415 - chỉ nhánh này cần

    interval = 1.0 / max(1, config.model.target_fps)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
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

            pose = estimator.detect(frame)
            if pose is None:
                drawn = frame
            else:
                drawn = draw_pose(
                    frame,
                    pose.xy,
                    pose.conf,
                    config.model.kp_conf_min,
                    copy=False,
                )

            cv2.imshow(WINDOW_NAME, drawn)
            # waitKey phải được gọi để OpenCV xử lý sự kiện cửa sổ.
            key = cv2.waitKey(1) & 0xFF
            if key in QUIT_KEYS:
                logger.info("Nhận phím thoát; đóng cửa sổ.")
                return 0
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                # Người dùng bấm nút X của cửa sổ.
                logger.info("Cửa sổ đã đóng; thoát.")
                return 0

            # Giữ nhịp theo target_fps, không ngủ nếu xử lý đã lâu hơn.
            elapsed = time.monotonic() - started
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        cv2.destroyAllWindows()


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

    # Import muộn: chỉ lệnh này cần phần cứng.
    from .hardware import create_hardware  # noqa: PLC0415

    hardware = create_hardware(config, no_gpio=args.no_gpio)

    source = capture_from_config(config)
    if source is None:
        logger.error(
            "Không mở được nguồn ảnh '%s' nên không thể suy luận pose. Chạy "
            "'python scripts/camera_probe.py' để kiểm tra phần cứng.",
            config.camera.source,
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

        _print_status(config, hardware, source, view, estimator.backend)
        return _preview_loop(estimator, source, config, logger)
    finally:
        source.close()
        hardware.close()


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

    print(NOT_IMPLEMENTED.format(name=args.command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
