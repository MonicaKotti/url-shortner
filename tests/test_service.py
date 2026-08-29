from __future__ import annotations

from datetime import timedelta

import pytest

from app.cache import LinkCache
from app.database import Database
from app.errors import LinkError, LinkGone
from app.repository import LinkRepository
from app.service import LinkService
from app.time_utils import utc_now


@pytest.fixture
def service(tmp_path) -> LinkService:
    database = Database(str(tmp_path / "service.db"))
    database.initialize()
    return LinkService(LinkRepository(database), LinkCache(30), "http://short.test", "salt")


def test_expiration_must_be_future(service: LinkService) -> None:
    with pytest.raises(LinkError, match="future"):
        service.create("https://example.com", None, utc_now() - timedelta(seconds=1), None)


def test_expired_link_is_not_resolved(service: LinkService) -> None:
    created = service.create("https://example.com", "expiring", utc_now() + timedelta(milliseconds=1), None)
    import time

    time.sleep(0.01)
    with pytest.raises(LinkGone, match="expired"):
        service.resolve(created["code"], "", "test", "127.0.0.1")
