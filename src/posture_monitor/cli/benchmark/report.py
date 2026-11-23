"""Tổng hợp dict báo cáo benchmark, định dạng bảng tiếng Việt & dựng parser CLI."""

from __future__ import annotations

import argparse
from typing import Any, Sequence

from ...core.config import Config
from .profiles import DEFAULT_PROFILE, PROFILES, _ExtraModel
from .telemetry import (
    MAX_RAM_MB,
    MAX_TEMP_C,
    MIN_FPS,
    compute_stats,
    describe_throttle,
    host_info,
    now_iso,
)

REPORT_VERSION = 1


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def build_report(
    *,
    config: Config,
    seconds: float,
    source_meta: dict[str, Any],
    estimator: Any,
    profile: str = DEFAULT_PROFILE,
    extras: Sequence[_ExtraModel] = (),
    baseline_meta: dict[str, Any],
    measured: int,
    with_person: int,
    errors: int,
    capture_ms: list[float],
    detect_ms: list[float],
    features_ms: list[float],
    classify_ms: list[float],
    state_ms: list[float],
    total_ms: list[float],
    pre_ms: list[float],
    infer_ms: list[float],
    post_ms: list[float],
    samples: list[dict[str, Any]],
    memory_samples: list[float],
    psutil_available: bool,
    notices: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Ghép báo cáo kết quả từ các danh sách mẫu đo thô."""
    total_stats = compute_stats(total_ms)
    median_total = None if total_stats is None else total_stats["median"]
    fps_median = (
        1000.0 / median_total
        if median_total is not None and median_total > 0
        else None
    )

    temps = [
        float(sample["temp_c"])
        for sample in samples
        if sample.get("temp_c") is not None
    ]
    temp_stats = compute_stats(temps)
    temp_reason = None
    if not temps:
        temp_reason = next(
            (sample["temp_reason"] for sample in samples if sample.get("temp_reason")),
            None,
        ) or "Không lấy được mẫu nhiệt độ nào."
        notices.append(f"Nhiệt độ CPU: null — {temp_reason}")
    temperature = {
        "min": None if temp_stats is None else temp_stats["min"],
        "median": None if temp_stats is None else temp_stats["median"],
        "max": None if temp_stats is None else temp_stats["max"],
        "samples": len(temps),
        "available": bool(temps),
        "reason": temp_reason,
    }

    described = [
        describe_throttle(int(sample["throttled"], 16))
        for sample in samples
        if sample.get("throttled") is not None
    ]
    throttle_flag_map: dict[int, str] = {}
    for value in described:
        for flag in value["flags"]:
            throttle_flag_map[int(flag["bit"], 16)] = flag["meaning"]
    final_throttle = next(
        (
            sample["throttled"]
            for sample in reversed(samples)
            if sample.get("throttled") is not None
        ),
        None,
    )
    invalidates = any(value["invalidates_fps"] for value in described)
    any_set = any(value["any_set"] for value in described)
    throttle_reason = None
    if not described:
        throttle_reason = next(
            (
                sample["throttle_reason"]
                for sample in samples
                if sample.get("throttle_reason")
            ),
            None,
        ) or "Không lấy được mẫu throttle nào."
        notices.append(f"Throttle: null — {throttle_reason}")
    if invalidates:
        warnings.append(
            "THROTTLE: có mẫu bật bit 0x4/0x40000 — số FPS đo được KHÔNG HỢP "
            "LỆ theo spec §8. Sửa tản nhiệt/nguồn rồi đo lại."
        )
    elif any_set:
        warnings.append(
            "THROTTLE: có bit khác 0 đã bật (xem danh sách cờ) — đối chiếu "
            "bảng bitmask §8 trước khi dùng số."
        )
    throttle = {
        "final": final_throttle,
        "any_set": any_set,
        "invalidates_fps": invalidates,
        "flags": [
            {"bit": f"0x{bit:05x}", "meaning": meaning}
            for bit, meaning in sorted(throttle_flag_map.items())
        ],
        "samples": [
            {
                "t_s": sample["t_s"],
                "temp_c": sample["temp_c"],
                "throttled": sample["throttled"],
                "invalidates_fps": sample["invalidates_fps"],
            }
            for sample in samples
        ],
        "available": bool(described),
        "reason": throttle_reason,
    }

    ram_start = memory_samples[0] if memory_samples else None
    ram_end = memory_samples[-1] if memory_samples else None
    ram_peak = max(memory_samples) if memory_samples else None
    ram_reason = None
    if ram_peak is None:
        ram_reason = (
            "Thiếu psutil nên không đọc được RSS."
            if not psutil_available
            else "Không đọc được RSS của tiến trình."
        )
    memory = {
        "start": _round(ram_start),
        "end": _round(ram_end),
        "peak": _round(ram_peak),
        "available": ram_peak is not None,
        "reason": ram_reason,
    }
    if ram_peak is not None and ram_peak >= MAX_RAM_MB:
        warnings.append(
            f"RAM đỉnh {ram_peak:.0f} MiB vượt mức {MAX_RAM_MB:.0f} MiB của spec §8."
        )

    throttle_checked = bool(described)
    fps_valid = throttle_checked and not invalidates
    fps_note = "FPS pipeline đầy đủ, KHÔNG phải FPS suy luận thuần."
    if invalidates:
        fps_note += " KHÔNG HỢP LỆ: throttle đã bật bit 0x4/0x40000."
    elif not throttle_checked:
        fps_note += (
            " Chưa kiểm được throttle (thiếu vcgencmd) nên chưa thể coi là "
            "bằng chứng đạt §8."
        )
    if source_meta.get("is_static"):
        fps_note += " Nguồn ảnh tĩnh nên đây chỉ là cận trên."

    if fps_median is None:
        fps_pass: bool | None = None
    elif invalidates:
        fps_pass = False
    elif not throttle_checked:
        fps_pass = None
    else:
        fps_pass = bool(fps_median >= MIN_FPS)

    criteria = [
        {
            "key": "fps",
            "label": "FPS pipeline (median toàn khung)",
            "target": f">= {MIN_FPS:g} FPS",
            "measured": _round(fps_median, 3),
            "pass": fps_pass,
            "note": fps_note,
        },
        {
            "key": "temperature",
            "label": "Nhiệt độ CPU (max)",
            "target": f"< {MAX_TEMP_C:g} °C",
            "measured": None if temp_stats is None else _round(temp_stats["max"]),
            "pass": (
                None if temp_stats is None else bool(temp_stats["max"] < MAX_TEMP_C)
            ),
            "note": temp_reason or "",
        },
        {
            "key": "memory",
            "label": "RAM tiến trình (đỉnh)",
            "target": f"< {MAX_RAM_MB:g} MiB",
            "measured": None if ram_peak is None else _round(ram_peak),
            "pass": None if ram_peak is None else bool(ram_peak < MAX_RAM_MB),
            "note": ram_reason or "",
        },
        {
            "key": "throttle",
            "label": "Không bit throttle nào bật",
            "target": "0x0",
            "measured": final_throttle,
            "pass": None if not described else bool(not any_set),
            "note": throttle_reason or "",
        },
    ]

    timing = {
        "pipeline_total": compute_stats(total_ms),
        "capture": compute_stats(capture_ms),
        "pose_detect": compute_stats(detect_ms),
        "pose_preprocess": compute_stats(pre_ms),
        "pose_inference": compute_stats(infer_ms),
        "pose_postprocess": compute_stats(post_ms),
        "features": compute_stats(features_ms),
        "classify": compute_stats(classify_ms),
        "state_update": compute_stats(state_ms),
    }

    models: list[dict[str, Any]] = [
        {
            "name": config.model.name,
            "role": "pose",
            "cadence": "mỗi khung",
            "format": config.model.format,
            "imgsz": int(config.model.imgsz),
            "backend": getattr(estimator, "backend", "không rõ"),
            "errors": errors,
            "timing_ms": timing.get("pose_detect"),
        }
    ]
    models.extend(extra.describe() for extra in extras)
    if profile != DEFAULT_PROFILE:
        notices.append(
            f"Hồ sơ đo '{profile}': {PROFILES.get(profile, profile)}. Chỉ "
            "được dùng số FPS của bài đo này cho đúng hồ sơ đó; đừng suy sang "
            "cấu hình khác (spec §8)."
        )

    return {
        "report_version": REPORT_VERSION,
        "generated_at": now_iso(),
        "duration_s": round(seconds, 3),
        "profile": profile,
        "models": models,
        "host": host_info(),
        "source": dict(source_meta),
        "model": {
            "name": config.model.name,
            "format": config.model.format,
            "backend": getattr(estimator, "backend", "không rõ"),
            "imgsz": int(config.model.imgsz),
        },
        "baseline": dict(baseline_meta),
        "frames": {
            "measured": measured,
            "with_person": with_person,
            "errors": errors,
        },
        "timing_ms": timing,
        "fps": {
            "pipeline_median": _round(fps_median, 3),
            "valid": fps_valid,
            "throttle_checked": throttle_checked,
            "note": (
                "FPS = 1000 / median(toàn khung). Đây là FPS pipeline đầy đủ "
                "(capture→detect→extract→classify→state), không phải FPS suy "
                "luận thuần; chưa gồm làm mượt, vẽ overlay, web. Bài đo chạy "
                "hết tốc lực, KHÔNG áp target_fps; lúc chạy thật ứng dụng tự "
                "giữ nhịp target_fps nên FPS thực tế thấp hơn hoặc bằng số này."
            ),
        },
        "temperature_c": temperature,
        "memory_mb": memory,
        "throttle": throttle,
        "criteria": criteria,
        "notices": notices,
        "warnings": warnings,
    }


def _fmt(value: Any, digits: int = 2, unit: str = "") -> str:
    if value is None:
        return "không đo được"
    if isinstance(value, bool):
        return "có" if value else "không"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}{unit}"
    return str(value)


def _pass_text(value: bool | None) -> str:
    if value is None:
        return "KHÔNG KẾT LUẬN"
    return "ĐẠT" if value else "KHÔNG ĐẠT"


def format_report(report: dict[str, Any]) -> str:
    """Dựng bảng báo cáo tiếng Việt dễ đọc từ dict báo cáo."""
    lines: list[str] = []
    host = report["host"]
    source = report["source"]
    model = report["model"]
    frames = report["frames"]
    timing = report["timing_ms"]
    fps = report["fps"]
    temperature = report["temperature_c"]
    memory = report["memory_mb"]
    throttle = report["throttle"]

    lines.append("=" * 78)
    lines.append("  BÁO CÁO BENCHMARK — HỆ THỐNG GIÁM SÁT HỌC TẬP")
    lines.append("=" * 78)
    lines.append(f"  Thời điểm    : {report['generated_at']}")
    lines.append(f"  Máy          : {host['cpu']} | {host['machine']}")
    lines.append(f"  Hệ điều hành : {host['platform']}")
    lines.append(f"  Python       : {host['python']}")
    lines.append("  Raspberry Pi : " + ("có" if host["is_raspberry_pi"] else "không"))
    lines.append(
        f"  Model        : {model['name']} ({model['backend']}, imgsz={model['imgsz']})"
    )
    lines.append(f"  Hồ sơ đo     : {report.get('profile', DEFAULT_PROFILE)}")
    for entry in report.get("models", []):
        if entry.get("role") == "pose":
            continue
        lines.append(
            f"    + model phụ : {entry.get('name')} — {entry.get('role')} "
            f"({entry.get('cadence')}, lỗi={entry.get('errors', 0)})"
        )
    lines.append(
        f"  Nguồn ảnh    : {source['kind']} — {source['note']} "
        f"({source['spec']}) [backend={source['backend']}]"
    )
    lines.append(
        "  Baseline     : "
        + (
            "đã nạp calibration.json"
            if report["baseline"]["loaded"]
            else "rỗng (chưa hiệu chỉnh)"
        )
    )
    lines.append(
        f"  Thời lượng   : {report['duration_s']:.1f} s, "
        f"{frames['measured']} khung ({frames['with_person']} có người)"
    )
    lines.append("-" * 78)
    lines.append(
        "  THỜI GIAN TỪNG KHÂU (ms)          N       Min    Median      P95      Max"
    )
    labels = {
        "pipeline_total": "TỔNG toàn khung",
        "capture": "  capture (đọc khung)",
        "pose_detect": "  pose.detect",
        "pose_preprocess": "    ├ preprocess (UL)",
        "pose_inference": "    ├ inference (UL)",
        "pose_postprocess": "    └ postprocess (UL)",
        "features": "  features.extract",
        "classify": "  classifier.classify",
        "state_update": "  state.update",
    }
    for key, label in labels.items():
        stats = timing.get(key)
        if stats is None:
            lines.append(f"  {label:<32} {'-':>5}  {'không đo được':>30}")
            continue
        digits = 2 if stats["median"] >= 1.0 else 3
        lines.append(
            f"  {label:<32} {stats['count']:>5} "
            f"{stats['min']:>8.{digits}f} {stats['median']:>9.{digits}f} "
            f"{stats['p95']:>8.{digits}f} {stats['max']:>8.{digits}f}"
        )
    lines.append("-" * 78)
    if throttle["invalidates_fps"]:
        fps_flag = "   <-- KHÔNG HỢP LỆ: throttle đã bật bit 0x4/0x40000"
    elif not throttle["available"]:
        fps_flag = (
            "   <-- CHƯA XÁC NHẬN: máy không có vcgencmd nên chưa kiểm được throttle"
        )
    else:
        fps_flag = ""
    lines.append(
        f"  FPS pipeline (từ median toàn khung): {_fmt(fps['pipeline_median'], 2)}"
        + fps_flag
    )
    lines.append(f"  {fps['note']}")
    lines.append("-" * 78)
    lines.append(
        "  NHIỆT ĐỘ CPU (°C)  : "
        + (
            "không đo được"
            if not temperature["available"]
            else (
                f"min={_fmt(temperature['min'])} "
                f"median={_fmt(temperature['median'])} "
                f"max={_fmt(temperature['max'])} "
                f"({temperature['samples']} mẫu)"
            )
        )
    )
    if not temperature["available"]:
        lines.append(f"    lý do: {temperature['reason']}")
    lines.append(
        "  RAM (MiB)          : "
        + (
            "không đo được"
            if not memory["available"]
            else (
                f"đầu={_fmt(memory['start'], 1)} "
                f"cuối={_fmt(memory['end'], 1)} "
                f"đỉnh={_fmt(memory['peak'], 1)}"
            )
        )
    )
    if not memory["available"]:
        lines.append(f"    lý do: {memory['reason']}")
    if not throttle["available"]:
        lines.append("  THROTTLE           : không đo được")
        lines.append(f"    lý do: {throttle['reason']}")
    else:
        lines.append(
            "  THROTTLE           : "
            f"cuối={throttle['final']} | "
            f"bit bật={'có' if throttle['any_set'] else 'không'}"
        )
        for flag in throttle["flags"]:
            lines.append(f"    {flag['bit']}: {flag['meaning']}")
    lines.append("-" * 78)
    lines.append("  TIÊU CHÍ NGHIỆM THU (spec §8)")
    for criterion in report["criteria"]:
        measured = criterion["measured"]
        shown = "không đo được" if measured is None else _fmt(measured)
        lines.append(
            f"  - {criterion['label']}: đo được: {shown}; "
            f"mục tiêu {criterion['target']} => {_pass_text(criterion['pass'])}"
        )
        if criterion["note"]:
            lines.append(f"      {criterion['note']}")
    if report["notices"]:
        lines.append("-" * 78)
        lines.append("  GHI CHÚ")
        for notice in report["notices"]:
            lines.append(f"  * {notice}")
    if report["warnings"]:
        lines.append("-" * 78)
        lines.append("  CẢNH BÁO")
        for warning in report["warnings"]:
            lines.append(f"  ! {warning}")
    lines.append("=" * 78)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Parser riêng cho ``python -m posture_monitor.benchmark``."""
    parser = argparse.ArgumentParser(
        prog="python -m posture_monitor.benchmark",
        description=(
            "Đo FPS/độ trễ/nhiệt/RAM/throttle trên chính máy đang chạy (spec §8, §11.6)."
        ),
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="Thời lượng đo, giây (mặc định: 60).",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    parser.add_argument(
        "--source",
        default=None,
        metavar="NGUON",
        help=(
            "Ghi đè nguồn ảnh: usb:0 | picamera | file:anh.jpg | "
            "file:video.mp4. Trên Pi chưa có camera, dùng ảnh tĩnh."
        ),
    )
    parser.add_argument(
        "--json",
        default=None,
        metavar="DUONG_DAN",
        help="Ghi báo cáo JSON ra file (ngoài bảng in trên màn hình).",
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        metavar="HO_SO",
        help=(
            "Hồ sơ đo: "
            + "; ".join(f"{key} = {value}" for key, value in PROFILES.items())
            + f". Mặc định: {DEFAULT_PROFILE}."
        ),
    )
    parser.add_argument(
        "--no-gpio",
        action="store_true",
        help="Tương thích CLI chung; benchmark không dùng GPIO.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )
    return parser
