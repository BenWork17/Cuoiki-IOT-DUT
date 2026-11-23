"""Lệnh ``replay``: chạy lại đường ống phân tích trên video có sẵn và xuất báo cáo JSON."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from ..core.config import ConfigError
from ..core.labels import LABEL_ORDER, STATES
from ..core.logging_setup import setup_logging


def cmd_replay(args: argparse.Namespace) -> int:
    """Xử lý lệnh ``replay``: chạy pipeline trên video, xuất báo cáo JSON tất định."""
    from .. import cli as _cli  # noqa: PLC0415
    from ..camera.capture import CameraError, FileSource  # noqa: PLC0415
    from ..domain.state import StateMachine  # noqa: PLC0415
    from ..vision.calibration import Baseline, CalibrationError  # noqa: PLC0415
    from ..vision.calibration import load as load_calibration  # noqa: PLC0415
    from ..vision.classifier import classify  # noqa: PLC0415
    from ..vision.features import extract  # noqa: PLC0415
    from ..vision.pose import PoseError, PoseEstimator  # noqa: PLC0415

    logger = setup_logging(args.log_level)

    try:
        config = _cli.load_config(args.config)
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

    try:
        fps = 0.0
        probe = _cli.cv2.VideoCapture(str(Path(args.video)))
        try:
            if probe.isOpened():
                fps = float(probe.get(_cli.cv2.CAP_PROP_FPS) or 0.0)
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
            baseline = Baseline.empty(
                view=config.camera.view,
                width=int(config.camera.width),
                height=int(config.camera.height),
            )
            calibration_loaded = False
            calibration_note = (
                "Chưa có calibration.json: chạy KHÔNG baseline. Các nhãn phụ "
                "thuộc baseline (HEAD_DOWN ở view front, TOO_CLOSE, LEAN, "
                "HEAD_TILT, LOOK_AWAY) không được đánh giá."
            )
        except CalibrationError as exc:
            baseline = Baseline.empty(
                view=config.camera.view,
                width=int(config.camera.width),
                height=int(config.camera.height),
            )
            calibration_loaded = False
            calibration_note = f"calibration.json hỏng ({exc}); chạy KHÔNG baseline."

        if not calibration_loaded:
            logger.warning("%s", calibration_note)

        try:
            estimator = PoseEstimator(config)
        except PoseError as exc:
            logger.error("%s", exc)
            return 2

        feature_baseline = baseline if calibration_loaded else None
        view = config.camera.view
        kp_conf_min = float(config.model.kp_conf_min)
        machine = StateMachine(config.timing)

        rows: list[dict[str, object]] = []
        state_counts = {state: 0 for state in STATES}
        label_counts = {label: 0 for label in LABEL_ORDER}
        frames_with_person = 0
        frames_errored = 0

        started = _cli.time.monotonic()
        index = 0
        try:
            while True:
                frame = source.read()
                if frame is None:
                    break

                pose = None
                try:
                    pose = estimator.detect(frame)
                except Exception as exc:  # noqa: BLE001
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

        duration_s = round(_cli.time.monotonic() - started, 3)

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
