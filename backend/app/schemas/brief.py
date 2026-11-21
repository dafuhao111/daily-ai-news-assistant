from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BriefItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    article_id: str = Field(min_length=16, max_length=64)
    summary: str = Field(min_length=1, max_length=800)
    relevance_reason: str = Field(min_length=1, max_length=240)


class BriefDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    items: list[BriefItemDraft] = Field(max_length=5)
    empty_reason: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_empty_reason_and_unique_articles(self) -> "BriefDraft":
        article_ids = [item.article_id for item in self.items]
        if len(set(article_ids)) != len(article_ids):
            raise ValueError("duplicate_article_id")
        if self.items and self.empty_reason:
            raise ValueError("empty_reason_requires_empty_brief")
        if not self.items and not self.empty_reason:
            raise ValueError("empty_brief_requires_reason")
        return self


class BriefItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_id: str
    title: str
    summary: str
    source_excerpt: str
    relevance_reason: str
    source_id: str
    source_name: str
    category: str
    url: str
    canonical_url: str
    published_at_raw: str | None
    published_at_utc: str | None
    published_at_field: str | None
    fetched_at_utc: str


class BriefContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_date: date
    generated_at: datetime
    item_count: int = Field(ge=0, le=5)
    items: list[BriefItem] = Field(max_length=5)
    empty_reason: str | None = None

    @model_validator(mode="after")
    def item_count_matches_items(self) -> "BriefContent":
        if self.item_count != len(self.items):
            raise ValueError("brief_item_count_mismatch")
        if bool(self.items) == bool(self.empty_reason):
            raise ValueError("brief_empty_reason_mismatch")
        return self


class BriefRead(BaseModel):
    id: int
    run_id: str
    run_status: Literal["completed", "empty"]
    report_date: date
    generated_at: datetime
    item_count: int
    items: list[BriefItem]
    empty_reason: str | None
