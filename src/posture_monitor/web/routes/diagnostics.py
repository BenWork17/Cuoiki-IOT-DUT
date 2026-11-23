"""Nhóm route chẩn đoán hệ thống & lịch sử vi phạm: ``GET /api/logs``, ``GET /api/violations``."""

from __future__ import annotations

import time

from flask import Flask, Response, jsonify, request

from ...core import log_buffer as logs_module
from ...core.logging_setup import get_logger
from ..constants import (
    LOGS_DEFAULT_LIMIT,
    LOGS_MAX_LIMIT,
    VIOLATION_KIND_TEXT,
    VIOLATION_KINDS,
    VIOLATIONS_DEFAULT_LIMIT,
    VIOLATIONS_MAX_LIMIT,
)
from ..context import WebContext, json_error, parse_limit_arg

_logger = get_logger("posture_monitor.web.routes.diagnostics")


def register_diagnostics_routes(app: Flask, ctx: WebContext) -> None:
    """Đăng ký ``GET /api/logs`` và ``GET /api/violations``."""

    @app.get("/api/logs")
    def api_logs() -> Response:
        logs = ctx.logs_buffer_provider()
        if logs is None:
            return json_error(
                "Chưa có bộ đệm nhật ký trong phiên chạy này nên chưa đọc "
                "được log. Bật logging của ứng dụng rồi thử lại.",
                503,
            )

        limit, err = parse_limit_arg(
            request.args.get("limit"),
            default=LOGS_DEFAULT_LIMIT,
            max_limit=LOGS_MAX_LIMIT,
            unit_hint="bản ghi",
        )
        if err is not None or limit is None:
            return err  # type: ignore[return-value]

        raw_level = request.args.get("level")
        level = logs_module.normalize_level(raw_level)
        if level is None:
            return json_error(
                f"Tham số 'level' phải là một trong "
                f"{', '.join(logs_module.LEVEL_ORDER)}; nhận được {raw_level!r}.",
                400,
            )

        entries = logs.snapshot(limit=limit, min_level=level)
        return jsonify(
            {
                "logs": entries,
                "total": len(entries),
                "level": level,
                "limit": limit,
            }
        )

    @app.get("/api/violations")
    def api_violations() -> Response:
        """Trả lịch sử 3 loại vi phạm từ bảng ``events`` (trả HTTP 503 JSON khi thiếu/lỗi DB)."""
        if ctx.storage is None:
            return json_error(
                "Chưa bật lưu trữ nên chưa có lịch sử vi phạm. Bật mục "
                "'storage' trong config.yaml rồi chạy lại.",
                503,
            )

        limit, err = parse_limit_arg(
            request.args.get("limit"),
            default=VIOLATIONS_DEFAULT_LIMIT,
            max_limit=VIOLATIONS_MAX_LIMIT,
            unit_hint="dòng",
        )
        if err is not None or limit is None:
            return err  # type: ignore[return-value]

        raw_kinds = request.args.get("kinds")
        kinds: list[str] | None = None
        if raw_kinds is not None and str(raw_kinds).strip() != "":
            parsed_kinds: list[str] = []
            for piece in str(raw_kinds).split(","):
                code = piece.strip().upper()
                if not code:
                    continue
                if code not in VIOLATION_KINDS:
                    return json_error(
                        f"Tham số 'kinds' chỉ nhận {', '.join(VIOLATION_KINDS)}; "
                        f"gặp mã lạ {piece.strip()!r}.",
                        400,
                    )
                parsed_kinds.append(code)
            kinds = parsed_kinds or None

        raw_since = request.args.get("since_s")
        since_ts: float | None = None
        if raw_since is not None and str(raw_since).strip() != "":
            try:
                since_s = float(str(raw_since).strip())
            except (TypeError, ValueError):
                return json_error(
                    f"Tham số 'since_s' phải là số giây, nhận được {raw_since!r}.",
                    400,
                )
            if since_s < 0:
                return json_error("'since_s' không được âm.", 400)
            since_ts = time.time() - since_s

        try:
            rows = ctx.storage.violations(limit=limit, kinds=kinds, since_ts=since_ts)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Không đọc được lịch sử vi phạm từ DB.")
            return json_error(
                f"Không đọc được lịch sử vi phạm từ cơ sở dữ liệu ({exc}). "
                "Xem log của máy chủ.",
                503,
            )

        counts = {kind: 0 for kind in VIOLATION_KINDS}
        for row in rows:
            kind = row.get("kind")
            if kind in counts:
                counts[kind] += 1

        return jsonify(
            {
                "violations": [
                    {
                        "ts": row["ts"],
                        "kind": row["kind"],
                        "kind_text": VIOLATION_KIND_TEXT.get(
                            row["kind"], str(row["kind"])
                        ),
                        "duration_s": row["duration_s"],
                    }
                    for row in rows
                ],
                "total": len(rows),
                "counts": counts,
                "limit": limit,
            }
        )
