import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from geotrade_ai.api.routers import meta
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.errors import install_error_handlers
from geotrade_ai.core.logging import request_id_var

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="GeoTrade-AI API", version=s.app_version, openapi_url=f"{API_PREFIX}/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "ETag"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    install_error_handlers(app)
    app.include_router(meta.router, prefix=API_PREFIX)
    return app
