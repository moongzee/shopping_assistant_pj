from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from ..core.config import SETTINGS
from .routes_admin import router as admin_router
from .routes_chat import router as chat_router

# Use uvicorn's logger so it shows up in container logs by default.
logger = logging.getLogger("uvicorn.error")
API_DEBUG = os.getenv("API_DEBUG", "").strip().lower() == "true"
API_DEBUG_BODY = os.getenv("API_DEBUG_BODY", "").strip().lower() == "true"
MAX_BODY_LOG = int(os.getenv("API_DEBUG_MAX_BODY", "2000") or "2000")

def create_app() -> FastAPI:
    app = FastAPI(title="Shopping Assistant Agent API", version="0.2.0")

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        t0 = time.time()
        logger.info("REQ start %s %s", request.method, request.url.path)
        try:
            if API_DEBUG:
                body_preview = ""
                if request.method in {"POST", "PUT", "PATCH"}:
                    body = await request.body()
                    if API_DEBUG_BODY and body:
                        body_text = body.decode("utf-8", errors="replace")
                        body_preview = (
                            f"{body_text[:MAX_BODY_LOG]}...<truncated>"
                            if len(body_text) > MAX_BODY_LOG
                            else body_text
                        )
                logger.info(
                    "REQ detail %s %s query=%s content-type=%s body=%s",
                    request.method,
                    request.url.path,
                    dict(request.query_params),
                    request.headers.get("content-type"),
                    body_preview,
                )
            resp = await call_next(request)
            return resp
        finally:
            dt_ms = int((time.time() - t0) * 1000)
            logger.info("REQ end   %s %s (%dms)", request.method, request.url.path, dt_ms)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=SETTINGS.frontend_origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(admin_router)
    app.include_router(chat_router)
    return app


app = create_app()

