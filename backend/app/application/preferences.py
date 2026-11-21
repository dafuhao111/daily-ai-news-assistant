from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.application.profiles import LOCAL_USER_ID
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile
from app.schemas.preferences import PreferencesWrite


def get_preferences(session: Session) -> SubscriptionPreferences:
    preferences = session.get(SubscriptionPreferences, LOCAL_USER_ID)
    if preferences is None:
        raise HTTPException(status_code=404, detail="preferences_not_configured")
    return preferences


def save_preferences(session: Session, payload: PreferencesWrite) -> SubscriptionPreferences:
    profile = session.get(UserProfile, LOCAL_USER_ID)
    if profile is None:
        raise HTTPException(status_code=409, detail="profile_not_configured")
    if payload.enabled and (not profile.recipient_email or profile.mail_test_status != "succeeded"):
        raise HTTPException(status_code=409, detail="mail_not_verified")

    preferences = session.get(SubscriptionPreferences, LOCAL_USER_ID)
    if preferences is None:
        preferences = SubscriptionPreferences(user_id=LOCAL_USER_ID)
        session.add(preferences)

    preferences.topics = payload.topics
    preferences.keywords = payload.keywords
    preferences.excluded_keywords = payload.excluded_keywords
    preferences.run_time = payload.run_time
    preferences.timezone = payload.timezone
    preferences.enabled = payload.enabled
    session.commit()
    session.refresh(preferences)
    return preferences
