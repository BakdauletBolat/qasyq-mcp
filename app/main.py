from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import init_db
from app.entries.routes import router as entries_router
from app.mcp.auth import BearerAuthASGI
from app.mcp.server import build_mcp
from app.oauth.endpoints import router as oauth_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    init_db(settings.db_path)
    mcp = build_mcp(settings.db_path)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="qasyq food log", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(oauth_router)
    app.include_router(entries_router)
    # Registered last: serves /mcp, everything above takes precedence.
    app.mount("/", BearerAuthASGI(mcp_app, settings))
    return app


def app_factory() -> FastAPI:
    return create_app()
