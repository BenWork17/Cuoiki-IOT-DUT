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
        "calibrate", help="Hiệu chỉnh tư thế chuẩn (chưa triển khai)."
    )
    calibrate.add_argument("--config", default="config.yaml")

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
        logger.info(
            "replay không dùng GPIO; cờ --no-gpio chỉ để tương thích CLI."
        )

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
                "Không đọc được FPS từ video; dùng %s (%.1f) để tính mốc "
                "thời gian.",
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
            calibration_note = (
                f"calibration.json hỏng ({exc}); chạy KHÔNG baseline."
            )

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
                    logger.warning(
                        "Suy luận lỗi ở khung %d: %s", index, exc
                    )

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

                classification = classify(
                    features, baseline, config.thresholds
                )
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
                "Không đọc được khung nào từ video '%s'; không có gì để báo "
                "cáo.",
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
                logger.error(
                    "Không ghi được báo cáo '%s': %s", target, exc
                )
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
        print(
            f"  Khung đã xử lý : {len(rows)} "
            f"(có người: {frames_with_person})"
        )
        if frames_errored:
            print(f"  Khung lỗi      : {frames_errored}")
        print(
            "  Trạng thái     : "
            + ", ".join(f"{s}={state_counts[s]}" for s in STATES)
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
    elif args.command == "replay":
        try:
            return cmd_replay(args)
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
