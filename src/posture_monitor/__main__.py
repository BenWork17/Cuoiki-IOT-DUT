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
from .config import ConfigError, load_config, redact_camera_source
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
    print(f"  Nguồn camera  : {redact_camera_source(camera_cfg.source)}")
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

        _print_status(config, hardware, source, view, estimator.backend)
        return _preview_loop(estimator, source, config, logger)
    finally:
        source.close()
        hardware.close()


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
            "--no-gpio: calibrate không dùng GPIO nên cờ này không có tác "
            "dụng (no-op)."
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
                logger.warning(
                    "Không đọc được khung từ nguồn ảnh; bỏ qua nhịp này."
                )
                time.sleep(sample_retry_s)
                continue

            read_count += 1
            pose = estimator.detect(frame)
            if pose is None:
                # Không thấy người vẫn là mẫu hợp lệ để calibration tự
                # lọc; tránh tự quyết định ở đây.
                frames.append(
                    extract(None, None, view=view, kp_conf_min=kp_conf_min)
                )
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
            logger.error(
                "Không ghi được file baseline '%s': %s", output, exc
            )
            return 1

        print()
        print("=" * 60)
        print("  HIỆU CHỈNH XONG — BASELINE TƯ THẾ CHUẨN")
        print("=" * 60)
        print(f"  File baseline : {saved.resolve()}")
        print(f"  Số khung dùng : {baseline.frames}")
        print(
            f"  Chế độ camera : {baseline.view} "
            f"({baseline.width}x{baseline.height})"
        )
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

    elif args.command == "calibrate":
        try:
            return cmd_calibrate(args)
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
