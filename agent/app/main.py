from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from ..core.config import SETTINGS
from .routes_admin import router as admin_router
from .routes_chat import router as chat_router

# Use uvicorn's logger so it shows up in container logs by default.
logger = logging.getLogger("uvicorn.error")

def create_app() -> FastAPI:
    app = FastAPI(title="Shopping Assistant Agent API", version="0.2.0")

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        t0 = time.time()
        logger.info("REQ start %s %s", request.method, request.url.path)
        try:
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

