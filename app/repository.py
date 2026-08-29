from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from urllib.parse import urlsplit

from app.database import Database
from app.errors import LinkNotFound
from app.time_utils import iso_now


class LinkRepository:
    def __init__(self, database: Database):
        self.database = database

    def insert_link(
        self,
        code: str,
        target_url: str,
        expires_at: str | None,
        idempotency_key: str | None,
        request_hash: str,
    ) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO links(code,target_url,created_at,expires_at) VALUES(?,?,?,?)",
                (code, target_url, iso_now(), expires_at),
            )
            if idempotency_key:
                connection.execute(
                    "INSERT INTO idempotency_keys(key,request_hash,code,created_at) VALUES(?,?,?,?)",
                    (idempotency_key, request_hash, code, iso_now()),
                )

    def find_idempotent(self, key: str) -> tuple[str, str] | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT code,request_hash FROM idempotency_keys WHERE key=?", (key,)).fetchone()
            return (row["code"], row["request_hash"]) if row else None

    def get(self, code: str) -> dict:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
            if not row:
                raise LinkNotFound("Short link not found")
            return dict(row)

    def list(self, limit: int, offset: int) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM links ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            return [dict(row) for row in rows]

    def disable(self, code: str) -> bool:
        with self.database.connection() as connection:
            result = connection.execute(
                "UPDATE links SET disabled_at=? WHERE code=? AND disabled_at IS NULL", (iso_now(), code)
            )
            if result.rowcount:
                return True
            if not connection.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone():
                raise LinkNotFound("Short link not found")
            return False

    def record_click(self, code: str, referrer: str, user_agent: str, ip_hash: str) -> None:
        normalized_referrer = ""
        if referrer:
            parsed = urlsplit(referrer)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                normalized_referrer = f"{parsed.scheme}://{parsed.netloc}/"
        user_agent_family = user_agent.split("/", maxsplit=1)[0][:80]
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO clicks(code,occurred_at,referrer,user_agent,ip_hash) VALUES(?,?,?,?,?)",
                (code, iso_now(), normalized_referrer, user_agent_family, ip_hash),
            )
            connection.execute("UPDATE links SET click_count=click_count+1 WHERE code=?", (code,))

    def analytics(self, code: str) -> dict:
        with self.database.connection() as connection:
            link = connection.execute("SELECT click_count FROM links WHERE code=?", (code,)).fetchone()
            if not link:
                raise LinkNotFound("Short link not found")
            by_day = connection.execute(
                """SELECT substr(occurred_at,1,10) AS day, COUNT(*) AS clicks
                   FROM clicks WHERE code=?
                   GROUP BY day ORDER BY day DESC LIMIT 30""",
                (code,),
            ).fetchall()
            referrers = connection.execute(
                """SELECT CASE WHEN referrer='' THEN 'direct' ELSE referrer END AS referrer,
                          COUNT(*) AS clicks
                   FROM clicks WHERE code=?
                   GROUP BY referrer ORDER BY clicks DESC LIMIT 10""",
                (code,),
            ).fetchall()
            recent = connection.execute(
                "SELECT occurred_at,referrer,user_agent FROM clicks WHERE code=? ORDER BY occurred_at DESC LIMIT 20",
                (code,),
            ).fetchall()
            return {
                "code": code,
                "total_clicks": link["click_count"],
                "clicks_by_day": [dict(row) for row in by_day],
                "top_referrers": [dict(row) for row in referrers],
                "recent_clicks": [dict(row) for row in recent],
            }

    def try_insert_codes(
        self,
        codes: Iterable[str],
        target_url: str,
        expires_at: str | None,
        idempotency_key: str | None,
        request_hash: str,
    ) -> str | None:
        for code in codes:
            try:
                self.insert_link(code, target_url, expires_at, idempotency_key, request_hash)
                return code
            except sqlite3.IntegrityError:
                if idempotency_key and self.find_idempotent(idempotency_key):
                    raise
        return None
