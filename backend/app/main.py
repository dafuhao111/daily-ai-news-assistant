import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from app.api.routes import router
from app.application.deliveries import MailDeliveryService
from app.application.mail_tests import MailTestService
from app.application.tasks import TaskCoordinator
from app.core.config import Settings, get_settings
from app.core.local_request import LocalRequestMiddleware
from app.db.session import build_session_factory
from app.delivery.smtp import SMTPMailer
from app.scheduler import DailyScheduler

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
    smtp_mailer = SMTPMailer(app_settings)
    delivery_service = (
        MailDeliveryService(session_factory, app_settings, smtp_mailer) if session_factory else None
    )
    task_coordinator = (
        TaskCoordinator(session_factory, app_settings, delivery_service)
        if session_factory and delivery_service
        else None
    )
    mail_test_service = MailTestService(session_factory, smtp_mailer) if session_factory else None
    daily_scheduler = (
        DailyScheduler(
            session_factory,
            task_coordinator,
            delivery_service,
            scheduling_enabled=app_settings.scheduler_enabled,
        )
        if session_factory and task_coordinator and delivery_service
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            if app.state.daily_scheduler is not None:
                await app.state.daily_scheduler.start()
            yield
        finally:
            if app.state.daily_scheduler is not None:
                await app.state.daily_scheduler.shutdown()
            current_engine = cast(Engine | None, app.state.engine)
            if current_engine is not None:
                current_engine.dispose()

    app = FastAPI(title="Daily AI News Assistant API", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.engine = database_engine
    app.state.session_factory = session_factory
    app.state.smtp_mailer = smtp_mailer
    app.state.mail_delivery_service = delivery_service
    app.state.mail_test_service = mail_test_service
    app.state.task_coordinator = task_coordinator
    app.state.daily_scheduler = daily_scheduler
    app.add_middleware(LocalRequestMiddleware)
    app.include_router(router, prefix=app_settings.api_prefix)
    frontend_dist = (
        Path(app_settings.frontend_dist_dir)
        if app_settings.frontend_dist_dir
        else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    if (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(_request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.warning("database request failed (%s)", type(error).__name__)
        return JSONResponse({"detail": "database_unavailable"}, status_code=503)

    return app


app = create_app()
