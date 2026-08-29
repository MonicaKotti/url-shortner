from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.cache import LinkCache
from app.errors import LinkConflict, LinkError, LinkGone
from app.repository import LinkRepository
from app.time_utils import utc_now

ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,30}[a-z0-9]$")
RESERVED = {"api", "docs", "redoc", "health", "ready", "metrics", "openapi.json", "favicon.ico"}


class LinkService:
    def __init__(self, repository: LinkRepository, cache: LinkCache, base_url: str, analytics_salt: str):
        self.repository = repository
        self.cache = cache
        self.base_url = base_url.rstrip("/")
        self.analytics_salt = analytics_salt

    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise LinkError("Only absolute HTTP and HTTPS URLs are allowed")
        if parsed.username or parsed.password:
            raise LinkError("URLs containing credentials are not allowed")
        if len(url) > 2048:
            raise LinkError("URL exceeds 2048 characters")
        return url

    @staticmethod
    def validate_alias(alias: str) -> str:
        alias = alias.lower()
        if alias in RESERVED or not ALIAS_PATTERN.fullmatch(alias):
            raise LinkError("Alias must be 4-32 URL-safe characters and may not be reserved")
        return alias

    @staticmethod
    def normalize_expiration(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        if value <= utc_now():
            raise LinkError("Expiration must be in the future")
        return value.isoformat()

    def _response(self, row: dict) -> dict:
        return {
            "code": row["code"],
            "target_url": row["target_url"],
            "short_url": f"{self.base_url}/{row['code']}",
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "disabled": row["disabled_at"] is not None,
            "click_count": row["click_count"],
        }

    def create(
        self, target_url: str, custom_alias: str | None, expires_at: datetime | None, idempotency_key: str | None
    ) -> dict:
        target_url = self.validate_url(target_url)
        expiration = self.normalize_expiration(expires_at)
        alias = self.validate_alias(custom_alias) if custom_alias else None
        request_hash = hashlib.sha256(
            json.dumps({"url": target_url, "alias": alias, "expires_at": expiration}, sort_keys=True).encode()
        ).hexdigest()
        if idempotency_key:
            if len(idempotency_key) > 128:
                raise LinkError("Idempotency-Key exceeds 128 characters")
            existing = self.repository.find_idempotent(idempotency_key)
            if existing:
                code, old_hash = existing
                if old_hash != request_hash:
                    raise LinkConflict("Idempotency-Key was already used with another request")
                return self._response(self.repository.get(code))

        codes = [alias] if alias else [secrets.token_urlsafe(7)[:8].lower() for _ in range(5)]
        try:
            code = self.repository.try_insert_codes(codes, target_url, expiration, idempotency_key, request_hash)
        except sqlite3.IntegrityError as error:
            if alias:
                raise LinkConflict("Alias is already in use") from error
            existing = self.repository.find_idempotent(idempotency_key) if idempotency_key else None
            if existing and existing[1] == request_hash:
                return self._response(self.repository.get(existing[0]))
            raise LinkConflict("Conflicting create request") from error
        if code is None:
            raise LinkConflict("Unable to allocate a unique short code; retry the request")
        return self._response(self.repository.get(code))

    def get(self, code: str) -> dict:
        return self._response(self.repository.get(code.lower()))

    def list(self, limit: int, offset: int) -> list[dict]:
        return [self._response(row) for row in self.repository.list(limit, offset)]

    def resolve(self, code: str, referrer: str, user_agent: str, client_ip: str) -> str:
        code = code.lower()
        entry = self.cache.get(code)
        if entry:
            row = {
                "target_url": entry.target_url,
                "expires_at": entry.expires_at,
                "disabled_at": "set" if entry.disabled else None,
            }
        else:
            row = self.repository.get(code)
            self.cache.put(code, row["target_url"], row["expires_at"], row["disabled_at"] is not None)
        if row["disabled_at"]:
            raise LinkGone("Short link is disabled")
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= utc_now():
            raise LinkGone("Short link has expired")
        ip_hash = hashlib.sha256(f"{self.analytics_salt}:{client_ip}".encode()).hexdigest()[:20]
        self.repository.record_click(code, referrer, user_agent, ip_hash)
        return row["target_url"]

    def disable(self, code: str) -> bool:
        disabled = self.repository.disable(code.lower())
        self.cache.invalidate(code.lower())
        return disabled

    def analytics(self, code: str) -> dict:
        return self.repository.analytics(code.lower())
