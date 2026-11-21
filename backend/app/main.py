import logging
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.local_request import LocalRequestMiddleware
from app.db.session import build_session_factory

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    database_engine = engine
    if database_engine is None and app_settings.database_url:
        engine_options = {"pool_pre_ping": True, "pool_timeout": 5}
        if app_settings.database_url.startswith("mysql+pymysql:"):
            engine_options["connect_args"] = {
                "connect_timeout": 5,
                "read_timeout": 10,
                "write_timeout": 10,
            }
        database_engine = create_engine(app_settings.database_url, **engine_options)
    session_factory = build_session_factory(database_engine) if database_engine else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        current_engine = cast(Engine | None, app.state.engine)
        if current_engine is not None:
            current_engine.dispose()

    app = FastAPI(title="Daily AI News Assistant API", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.engine = database_engine
    app.state.session_factory = session_factory
    app.add_middleware(LocalRequestMiddleware)
    app.include_router(router, prefix=app_settings.api_prefix)

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(_request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.warning("database request failed (%s)", type(error).__name__)
        return JSONResponse({"detail": "database_unavailable"}, status_code=503)

    return app


app = create_app()
