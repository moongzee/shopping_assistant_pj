from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import SETTINGS
from .routes_admin import router as admin_router
from .routes_chat import router as chat_router


def create_app() -> FastAPI:
    app = FastAPI(title="Shopping Assistant Agent API", version="0.2.0")
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

