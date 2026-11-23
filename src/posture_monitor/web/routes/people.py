"""Nhóm route người học, đăng ký khuôn mặt, tín hiệu và khung giờ học."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from flask import Flask, Response, jsonify, request

from ...core.logging_setup import get_logger
from ..constants import PEOPLE_DISABLED_MESSAGE
from ..context import WebContext, json_error
from ..people_service import PeopleServiceError
from ..privacy import public_person, scrub_biometrics

_logger = get_logger("posture_monitor.web.routes.people")


def register_people_routes(app: Flask, ctx: WebContext) -> None:
    """Đăng ký 9 route thuộc nhóm ``/api/people*``, ``/api/enroll*``, ``/api/select``, ``/api/signals``, ``/api/schedule``."""

    def _people_unavailable() -> Response:
        return json_error(PEOPLE_DISABLED_MESSAGE, 503)

    def _people_call(call: Callable[[], Any]) -> tuple[bool, Any]:
        try:
            return True, call()
        except PeopleServiceError as exc:
            return False, json_error(str(exc), 400)
        except Exception:  # noqa: BLE001
            _logger.exception("Lỗi không lường trước từ dịch vụ người học.")
            return False, json_error(
                "Dịch vụ người học đang gặp sự cố. Xem log để biết chi tiết.",
                503,
            )

    @app.get("/api/people")
    def api_people() -> Response:
        if ctx.people is None:
            return _people_unavailable()
        ok, result = _people_call(
            lambda: (
                [public_person(item) for item in ctx.people.list_people()],  # type: ignore[union-attr]
                ctx.people.selected_person(),  # type: ignore[union-attr]
            )
        )
        if not ok:
            return result
        directory, selected = result
        return jsonify({"people": directory, "selected": selected})

    @app.post("/api/people")
    def api_people_add() -> Response:
        if ctx.people is None:
            return _people_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return json_error('Thân request phải là JSON dạng {"name": "..."}.', 400)
        name = body.get("name")
        if not isinstance(name, str):
            return json_error("Tên người học phải là chữ.", 400)
        name = name.strip()
        if not name:
            return json_error("Tên người học không được để trống.", 400)

        ok, result = _people_call(lambda: ctx.people.start_enroll(name))  # type: ignore[union-attr]
        if not ok:
            return result
        payload = {"ok": True, "name": name}
        payload.update(result)
        return jsonify(payload), 201

    @app.delete("/api/people/<person_id>")
    def api_people_delete(person_id: str) -> Response:
        if ctx.people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: ctx.people.delete_person(person_id))  # type: ignore[union-attr]
        if not ok:
            return result
        if not result:
            return json_error(f"Không tìm thấy người học có mã {person_id!r}.", 404)
        return jsonify({"ok": True, "message": "Đã xoá người học."})

    @app.get("/api/enroll/<enroll_id>")
    def api_enroll_status(enroll_id: str) -> Response:
        if ctx.people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: ctx.people.enroll_status(enroll_id))  # type: ignore[union-attr]
        if not ok:
            return result
        return jsonify({"ok": True, "enroll_id": enroll_id, **dict(result)})

    @app.post("/api/enroll/<enroll_id>/cancel")
    def api_enroll_cancel(enroll_id: str) -> Response:
        if ctx.people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: ctx.people.cancel_enroll(enroll_id))  # type: ignore[union-attr]
        if not ok:
            return result
        if not result:
            return json_error(
                f"Không có phiên đăng ký nào đang chạy với mã {enroll_id!r}.",
                404,
            )
        return jsonify({"ok": True, "message": "Đã huỷ phiên đăng ký."})

    @app.post("/api/select")
    def api_select() -> Response:
        if ctx.people is None:
            return _people_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping) or "person_id" not in body:
            return json_error(
                'Thân request phải có khóa "person_id" (chuỗi hoặc null).',
                400,
            )
        person_id = body["person_id"]
        if person_id is not None and not isinstance(person_id, str):
            return json_error('"person_id" phải là chuỗi hoặc null.', 400)

        ok, result = _people_call(lambda: ctx.people.select_person(person_id))  # type: ignore[union-attr]
        if not ok:
            return result
        if not result:
            return json_error(f"Không tìm thấy người học có mã {person_id!r}.", 404)
        message = (
            "Đã bỏ chọn người đang học."
            if person_id is None
            else "Đã chọn người đang học."
        )
        return jsonify({"ok": True, "selected": person_id, "message": message})

    @app.get("/api/signals")
    def api_signals() -> Response:
        if ctx.people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: ctx.people.signals())  # type: ignore[union-attr]
        if not ok:
            return result
        return jsonify(scrub_biometrics(dict(result)))

    @app.get("/api/schedule")
    def api_schedule_get() -> Response:
        if ctx.people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: ctx.people.get_schedule())  # type: ignore[union-attr]
        if not ok:
            return result
        return jsonify({"ok": True, "schedule": result})

    @app.put("/api/schedule")
    def api_schedule_put() -> Response:
        if ctx.people is None:
            return _people_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return json_error(
                "Thân request phải là một đối tượng JSON mô tả giờ học.", 400
            )
        ok, result = _people_call(lambda: ctx.people.put_schedule(dict(body)))  # type: ignore[union-attr]
        if not ok:
            return result
        return jsonify({"ok": True, "schedule": result})
