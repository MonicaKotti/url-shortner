from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class CreateLinkRequest(BaseModel):
    url: HttpUrl
    custom_alias: str | None = Field(default=None, min_length=4, max_length=32)
    expires_at: datetime | None = None

    @field_validator("custom_alias")
    @classmethod
    def lowercase_alias(cls, value: str | None) -> str | None:
        return value.lower() if value else None


class LinkResponse(BaseModel):
    code: str
    target_url: str
    short_url: str
    created_at: str
    expires_at: str | None
    disabled: bool
    click_count: int


class AnalyticsResponse(BaseModel):
    code: str
    total_clicks: int
    clicks_by_day: list[dict[str, Any]]
    top_referrers: list[dict[str, Any]]
    recent_clicks: list[dict[str, Any]]
