from collections.abc import Generator
from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def get_session(request: Request) -> Generator[Session, None, None]:
    factory = cast(sessionmaker[Session] | None, request.app.state.session_factory)
    if factory is None:
        raise HTTPException(status_code=503, detail="database_not_configured")
    with factory() as session:
        yield session


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
