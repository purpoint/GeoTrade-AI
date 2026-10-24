import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from geotrade_ai.api.cache import ResponseCache
from geotrade_ai.api.ratelimit import rate_limit_middleware
from geotrade_ai.api.routers import admin, auth, me, meta, public
from geotrade_ai.api.stream import hub
from geotrade_ai.api.stream import router as stream_router
from geotrade_ai.core.config import get_settings
from geotrade_ai.core.errors import install_error_handlers
from geotrade_ai.core.logging import request_id_var
from geotrade_ai.core.metrics import HTTP_REQUESTS

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    hub.start()
    yield
    await hub.stop()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="GeoTrade-AI API",
        version=s.app_version,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        lifespan=lifespan,
    )
    cache = ResponseCache(s.cache_ttl_seconds)
    hub.listeners.append(cache.clear)
    app.middleware("http")(cache.middleware)
    app.middleware("http")(rate_limit_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
        allow_credentials=True,
        expose_headers=["X-Request-ID", "ETag"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        route = request.scope.get("route")
        HTTP_REQUESTS.labels(getattr(route, "path", "unmatched"), response.status_code).observe(
            time.perf_counter() - started
        )
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        # internal only: the UI proxy forwards /api/v1/* and never this path
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    install_error_handlers(app)
    for router in (meta.router, auth.router, me.router, public.router, stream_router, admin.router):
        app.include_router(router, prefix=API_PREFIX)
    return app
