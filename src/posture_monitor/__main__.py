"""Điểm vào dòng lệnh: ``python -m posture_monitor <lệnh>``.

Các lệnh theo spec v2 §7::

    python -m posture_monitor run [--config config.yaml] [--no-gpio] [--view front|side]
    python -m posture_monitor calibrate
    python -m posture_monitor replay video.mp4 [--no-gpio] [--save-report out.json]
    python -m posture_monitor benchmark [--seconds 60]

Ở phạm vi M0 chỉ ``run`` được triển khai: nạp cấu hình, khởi tạo phần cứng
giả lập, thử mở camera (hoặc ghi rõ lý do không mở được), in trạng thái khởi
động. Ba lệnh còn lại in thông báo "chưa triển khai" và thoát với mã 0.

Không in bất kỳ số liệu hiệu năng nào: mọi chỉ số FPS/độ trễ phải do
``benchmark`` sinh ra trên máy đích (spec §11.6).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .capture import capture_from_config
from .config import ConfigError, load_config
from .logging_setup import setup_logging

#: Nội dung in ra cho các lệnh chưa có trong phạm vi M0.
NOT_IMPLEMENTED = (
    "Lệnh '{name}' chưa triển khai (đang ở mốc M0). "
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


def _print_status(config, hardware, source, view: str) -> None:
    """In khối trạng thái khởi động cho người dùng."""
    camera_cfg = config.camera
    print()
    print("=" * 60)
    print("  GIÁM SÁT TƯ THẾ — TRẠNG THÁI KHỞI ĐỘNG (M0)")
    print("=" * 60)
    print(f"  Cấu hình      : {config.path or '(mặc định)'}")
    print(f"  Nguồn camera  : {camera_cfg.source}")
    print(f"  Độ phân giải  : {camera_cfg.width}x{camera_cfg.height}, view={view}")

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
    print("  Suy luận tư thế chưa triển khai ở mốc M0 (xem spec §10).")
    print("=" * 60)
    print()


def cmd_run(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``run``: cấu hình → phần cứng → camera → trạng thái."""
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
        # Không có camera vẫn là trạng thái hợp lệ ở M0: báo rõ và chạy tiếp.
        logger.warning(
            "Không mở được nguồn ảnh '%s'. Hệ thống chạy ở chế độ không "
            "camera; chạy 'python scripts/camera_probe.py' để kiểm tra "
            "phần cứng.",
            config.camera.source,
        )
    else:
        frame = source.read()
        if frame is None:
            logger.warning("Camera đã mở nhưng chưa đọc được khung nào.")
        else:
            logger.info(
                "Đọc thử một khung thành công: %dx%d.",
                frame.shape[1],
                frame.shape[0],
            )

    try:
        _print_status(config, hardware, source, view)
    finally:
        if source is not None:
            source.close()
        hardware.close()

    return 0


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
