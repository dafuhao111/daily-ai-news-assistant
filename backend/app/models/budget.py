from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.profile import utc_now


class TokenBudgetRecord(Base):
    __tablename__ = "token_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    limit_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    uncertain_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    blocked: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class TokenUsageRecord(Base):
    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("token_budget.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
