"""Vòng đo hiệu năng chính (:func:`run_benchmark`) và điểm vào CLI ``benchmark.main``."""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from ...core.config import Config, ConfigError, load_config
from ...core.logging_setup import get_logger, setup_logging
from ...domain.state import StateMachine
from ...vision.calibration import Baseline, CalibrationError
from ...vision.calibration import load as load_calibration
from ...vision.classifier import classify
from ...vision.features import extract
from ...vision.pose import PoseError
from .profiles import DEFAULT_PROFILE, normalise_profile
from .report import build_parser, build_report, format_report
from .sources import resolve_source
from .telemetry import (
    MAX_FRAME_ERRORS,
    MEMORY_EVERY_FRAMES,
    SAMPLE_INTERVAL_S,
    WARMUP_FRAMES,
    BenchmarkError,
    describe_throttle,
    parse_temp,
    parse_throttled,
    rss_mib,
)

logger = get_logger("posture_monitor.cli.benchmark.runner")


class _StageTap:
    """Gom ``preprocess/inference/postprocess`` (ms) từ callback của Ultralytics."""

    def __init__(self) -> None:
        self.latest: dict[str, float] | None = None
        self.count = 0

    def on_batch_end(self, predictor: Any) -> None:  # pragma: no cover
        results = getattr(predictor, "results", None) or []
        for result in results:
            speed = getattr(result, "speed", None)
            if isinstance(speed, dict):
                self.latest = dict(speed)
                self.count += 1

    def attach(self, estimator: Any) -> bool:
        model = getattr(estimator, "_model", None)
        if model is None or not hasattr(model, "add_callback"):
            logger.warning(
                "Không gắn được callback vào model pose; bỏ qua thời gian "
                "preprocess/inference/postprocess (không ước lượng thay)."
            )
            return False
        try:
            model.add_callback("on_predict_batch_end", self.on_batch_end)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Không gắn được callback thời gian từng khâu: %s", exc)
            return False


def _neutral_baseline(config: Config) -> tuple[Baseline, dict[str, Any]]:
    path = "calibration.json"
    try:
        baseline = load_calibration(path)
    except FileNotFoundError:
        return (
            Baseline.empty(
                view=config.camera.view,
                width=int(config.camera.width),
                height=int(config.camera.height),
            ),
            {
                "loaded": False,
                "path": path,
                "note": (
                    "Chưa có calibration.json: baseline rỗng, các nhãn phụ "
                    "thuộc baseline không được đánh giá. Thời gian phân loại "
                    "vẫn đo trên đường code thật."
                ),
            },
        )
    except CalibrationError as exc:
        logger.warning("Không đọc được '%s': %s", path, exc)
        return (
            Baseline.empty(
                view=config.camera.view,
                width=int(config.camera.width),
                height=int(config.camera.height),
            ),
            {
                "loaded": False,
                "path": path,
                "note": f"calibration.json hỏng ({exc}); dùng baseline rỗng.",
            },
        )
    return baseline, {
        "loaded": True,
        "path": path,
        "note": "Đã nạp baseline hiệu chỉnh có sẵn.",
    }


def run_benchmark(
    config: Config,
    seconds: float,
    source_override: Any = None,
    profile: str = DEFAULT_PROFILE,
) -> dict[str, Any]:
    """Đo hiệu năng pipeline trên máy đang chạy (spec §8, §11.6)."""
    from . import (  # noqa: PLC0415 - đọc động qua package để hỗ trợ monkeypatch trong test
        PoseEstimator,
        _build_extras,
        _Command,
        capture_from_config,
        psutil,
    )

    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"seconds phải là số hữu hạn dương, nhận được {seconds!r}.")

    profile = normalise_profile(profile)
    extras = _build_extras(config, profile)

    notices: list[str] = []
    warnings: list[str] = []

    source, source_meta, owned = resolve_source(
        config, source_override, capture_factory=capture_from_config
    )
    if source_meta["is_static"]:
        notices.append(
            "NGUỒN ẢNH TĨNH: số FPS dưới đây KHÔNG phải FPS camera thật; nó "
            "bỏ qua thời gian đọc cảm biến và chỉ là cận trên của pipeline."
        )
    if source_meta["kind"] == "synthetic":
        notices.append(
            "NGUỒN TỔNG HỢP: bài đo dùng khung giả cho kiểm thử, không dùng "
            "được làm số liệu nghiệm thu."
        )

    try:
        try:
            estimator = PoseEstimator(config)
        except PoseError as exc:
            raise BenchmarkError(str(exc)) from exc

        baseline, baseline_meta = _neutral_baseline(config)
        if not baseline_meta["loaded"]:
            notices.append(baseline_meta["note"])
        feature_baseline = baseline if baseline_meta["loaded"] else None

        stage_tap = _StageTap()
        stage_ok = stage_tap.attach(estimator)

        machine = StateMachine(config.timing)
        temp_cmd = _Command("vcgencmd", "measure_temp")
        throttle_cmd = _Command("vcgencmd", "get_throttled")

        view = config.camera.view
        kp_conf_min = float(config.model.kp_conf_min)

        capture_ms: list[float] = []
        detect_ms: list[float] = []
        features_ms: list[float] = []
        classify_ms: list[float] = []
        state_ms: list[float] = []
        total_ms: list[float] = []
        pre_ms: list[float] = []
        infer_ms: list[float] = []
        post_ms: list[float] = []

        samples: list[dict[str, Any]] = []
        measured = 0
        with_person = 0
        errors = 0
        memory_samples: list[float] = []

        def take_sample(elapsed: float) -> None:
            temp_text, temp_reason = temp_cmd.run()
            throttle_text, throttle_reason = throttle_cmd.run()
            temperature = parse_temp(temp_text)
            throttled = parse_throttled(throttle_text)
            samples.append(
                {
                    "t_s": round(elapsed, 3),
                    "temp_c": temperature,
                    "temp_reason": temp_reason if temperature is None else None,
                    "throttled": None if throttled is None else f"0x{throttled:x}",
                    "throttle_reason": (
                        throttle_reason if throttled is None else None
                    ),
                    "invalidates_fps": (
                        describe_throttle(throttled)["invalidates_fps"]
                        if throttled is not None
                        else False
                    ),
                }
            )
            logger.info(
                "Mẫu môi trường t=%.0fs: nhiệt=%s, throttled=%s",
                elapsed,
                "không đọc được" if temperature is None else f"{temperature:.1f}°C",
                "không đọc được" if throttled is None else f"0x{throttled:x}",
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

        start = time.monotonic()
        take_sample(0.0)
        last_sample_elapsed = 0.0
        start_rss = rss_mib(psutil)
        if start_rss is not None:
            memory_samples.append(start_rss)
        if psutil is None:
            warnings.append(
                "Thiếu psutil: không đo được RAM. Cài 'pip install psutil' "
                "(đã có trong requirements.txt)."
            )
            notices.append("RAM: null vì thiếu psutil.")

        first = True
        while first or (time.monotonic() - start < seconds):
            first = False

            t0 = time.perf_counter()
            try:
                frame = source.read()
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.warning("Đọc khung lỗi (%d): %s", errors, exc)
                frame = None
            if frame is None:
                if measured == 0:
                    raise BenchmarkError(
                        "Không đọc được khung nào từ nguồn ảnh; không có gì để đo."
                    )
                warnings.append(
                    f"Nguồn ảnh hết khung giữa bài đo; báo cáo chỉ gồm {measured} khung đã xử lý."
                )
                break
            t1 = time.perf_counter()

            pose = None
            frame_failed = False
            stage_before = stage_tap.count
            try:
                pose = estimator.detect(frame)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                frame_failed = True
                logger.warning("Suy luận lỗi (%d): %s", errors, exc)
                if measured == 0 and errors >= 3:
                    raise BenchmarkError(
                        f"Suy luận pose lỗi liên tục, không đo được: {exc}"
                    ) from exc
                if errors > MAX_FRAME_ERRORS:
                    warnings.append(
                        f"Vượt {MAX_FRAME_ERRORS} lỗi khung; dừng bài đo sớm."
                    )
                    break
            t2 = time.perf_counter()

            if extras and pose is not None and not frame_failed:
                extra_now = time.monotonic() - start
                for extra in extras:
                    extra.step(frame, pose, extra_now)

            if pose is None:
                features = extract(
                    None,
                    None,
                    view=view,
                    kp_conf_min=kp_conf_min,
                    baseline=feature_baseline,
                )
            else:
                with_person += 1
                features = extract(
                    pose.xy,
                    pose.conf,
                    view=view,
                    kp_conf_min=kp_conf_min,
                    baseline=feature_baseline,
                )
            t3 = time.perf_counter()

            classification = classify(features, baseline, config.thresholds)
            t4 = time.perf_counter()

            now = time.monotonic() - start
            try:
                machine.update(now, classification.labels, classification.score)
            except ValueError as exc:  # pragma: no cover
                logger.warning("Máy trạng thái từ chối mốc thời gian: %s", exc)
            t5 = time.perf_counter()

            if not frame_failed:
                capture_ms.append((t1 - t0) * 1000.0)
                detect_ms.append((t2 - t1) * 1000.0)
                features_ms.append((t3 - t2) * 1000.0)
                classify_ms.append((t4 - t3) * 1000.0)
                state_ms.append((t5 - t4) * 1000.0)
                total_ms.append((t5 - t0) * 1000.0)
                measured += 1

                if (
                    stage_ok
                    and stage_tap.count > stage_before
                    and stage_tap.latest is not None
                ):
                    speed = stage_tap.latest
                    for key, bucket in (
                        ("preprocess", pre_ms),
                        ("inference", infer_ms),
                        ("postprocess", post_ms),
                    ):
                        value = speed.get(key)
                        if isinstance(value, (int, float)) and math.isfinite(
                            float(value)
                        ):
                            bucket.append(float(value))

            if measured > 0 and measured % MEMORY_EVERY_FRAMES == 0:
                rss = rss_mib(psutil)
                if rss is not None:
                    memory_samples.append(rss)

            elapsed = time.monotonic() - start
            if elapsed - last_sample_elapsed >= SAMPLE_INTERVAL_S:
                take_sample(elapsed)
                last_sample_elapsed = elapsed

        take_sample(time.monotonic() - start)
        end_rss = rss_mib(psutil)
        if end_rss is not None:
            memory_samples.append(end_rss)

        if measured == 0:
            raise BenchmarkError(
                "Không có khung nào chạy trọn vẹn; không có số liệu để báo "
                "cáo. Xem log để biết lỗi cụ thể."
            )

        return build_report(
            config=config,
            seconds=seconds,
            source_meta=source_meta,
            estimator=estimator,
            profile=profile,
            extras=extras,
            baseline_meta=baseline_meta,
            measured=measured,
            with_person=with_person,
            errors=errors,
            capture_ms=capture_ms,
            detect_ms=detect_ms,
            features_ms=features_ms,
            classify_ms=classify_ms,
            state_ms=state_ms,
            total_ms=total_ms,
            pre_ms=pre_ms,
            infer_ms=infer_ms,
            post_ms=post_ms,
            samples=samples,
            memory_samples=memory_samples,
            psutil_available=psutil is not None,
            notices=notices,
            warnings=warnings,
        )
    finally:
        if owned:
            source.close()


def main(argv: list[str] | None = None) -> int:
    """Chạy bài đo từ dòng lệnh; trả mã thoát của tiến trình."""
    from . import run_benchmark as _run_fn  # noqa: PLC0415 - hỗ trợ monkeypatch bench.run_benchmark

    parser = build_parser()
    args = parser.parse_args(argv)
    logger_root = setup_logging(args.log_level)

    if args.no_gpio:
        logger_root.info(
            "Benchmark không dùng GPIO; cờ --no-gpio chỉ để tương thích CLI."
        )
    if args.seconds <= 0:
        logger_root.error("--seconds phải lớn hơn 0.")
        return 2

    try:
        try:
            config = load_config(args.config)
        except FileNotFoundError as exc:
            logger_root.error("%s", exc)
            return 2
        except ConfigError as exc:
            logger_root.error("Cấu hình không hợp lệ: %s", exc)
            return 2

        report = _run_fn(
            config,
            args.seconds,
            source_override=args.source,
            profile=args.profile,
        )
    except BenchmarkError as exc:
        logger_root.error("Không đo được: %s", exc)
        return 2
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        logger_root.error("Lỗi không mong muốn khi đo: %s", exc)
        logger_root.debug("Chi tiết:", exc_info=True)
        return 1

    print(format_report(report))

    if args.json:
        target = Path(args.json)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger_root.error("Không ghi được báo cáo JSON '%s': %s", target, exc)
            return 2
        print(f"Đã ghi báo cáo JSON: {target.resolve()}")

    return 0
