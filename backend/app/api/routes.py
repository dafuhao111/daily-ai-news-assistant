import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.preferences import get_preferences, save_preferences
from app.application.profiles import get_profile, save_profile
from app.db.session import get_session
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile
from app.schemas.preferences import PreferencesRead, PreferencesWrite
from app.schemas.profile import ProfileRead, ProfileWrite

logger = logging.getLogger(__name__)
router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/profile", response_model=ProfileRead)
def read_profile(session: SessionDep) -> UserProfile:
    return get_profile(session)


@router.put("/profile", response_model=ProfileRead)
def update_profile(payload: ProfileWrite, session: SessionDep) -> UserProfile:
    return save_profile(session, payload)


@router.get("/preferences", response_model=PreferencesRead)
def read_preferences(session: SessionDep) -> SubscriptionPreferences:
    return get_preferences(session)


@router.put("/preferences", response_model=PreferencesRead)
def update_preferences(payload: PreferencesWrite, session: SessionDep) -> SubscriptionPreferences:
    return save_preferences(session, payload)


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    factory = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="database_not_configured")
    try:
        with factory() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.warning("database health check failed (%s)", type(error).__name__)
        raise HTTPException(status_code=503, detail="database_unavailable") from None
    return {"status": "ok", "database": "connected"}
