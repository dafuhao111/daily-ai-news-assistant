from datetime import datetime, time

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.profile import utc_now


class SubscriptionPreferences(Base):
    __tablename__ = "subscription_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"), primary_key=True)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    excluded_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    run_time: Mapped[time] = mapped_column(Time, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )
