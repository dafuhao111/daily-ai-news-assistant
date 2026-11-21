from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile import UserProfile
from app.schemas.profile import ProfileWrite

LOCAL_USER_ID = 1


def get_profile(session: Session) -> UserProfile:
    profile = session.get(UserProfile, LOCAL_USER_ID)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile_not_configured")
    return profile


def save_profile(session: Session, payload: ProfileWrite) -> UserProfile:
    profile = session.scalar(select(UserProfile).where(UserProfile.id == LOCAL_USER_ID))
    if profile is None:
        profile = UserProfile(id=LOCAL_USER_ID, display_name=payload.display_name)
        session.add(profile)

    previous_email = profile.recipient_email
    profile.display_name = payload.display_name
    profile.role = payload.role
    profile.recipient_email = str(payload.recipient_email) if payload.recipient_email else None
    if previous_email != profile.recipient_email:
        profile.mail_test_status = "unconfigured"
        profile.mail_tested_at = None

    session.commit()
    session.refresh(profile)
    return profile
