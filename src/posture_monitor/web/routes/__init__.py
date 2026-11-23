"""Bộ đăng ký toàn bộ các nhóm route HTTP cho ứng dụng Flask."""

from __future__ import annotations

from flask import Flask

from ..context import WebContext
from ..streaming import register_streaming_routes
from .core import register_core_routes
from .diagnostics import register_diagnostics_routes
from .media import register_media_routes
from .people import register_people_routes
from .session import register_session_routes


def register_all_routes(app: Flask, ctx: WebContext) -> None:
    """Gắn đủ 6 nhóm route vào ``app`` theo ranh giới miền rõ ràng."""
    register_core_routes(app, ctx)
    register_diagnostics_routes(app, ctx)
    register_session_routes(app, ctx)
    register_media_routes(app, ctx)
    register_streaming_routes(app, ctx)
    register_people_routes(app, ctx)
