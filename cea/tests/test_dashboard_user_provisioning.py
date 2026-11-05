"""First-login provisioning: a non-local User has no sign-up step, so their User row is
created on their first authenticated request (ensure_user_cached in lib/database/models.py)."""
import asyncio

import pytest

SUB = "f3b1c2d4-0000-4000-8000-keycloak-sub"


class _FakeCache:
    def __init__(self, seen_keys=()):
        self.store = {key: True for key in seen_keys}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=None):
        self.store[key] = value


@pytest.fixture
def user_store(monkeypatch):
    """models.ensure_user_cached with a fake cache and a recorded ensure_user."""
    import cea.interfaces.dashboard.lib.cache.provider as cache_provider
    import cea.interfaces.dashboard.lib.database.models as models

    cache = _FakeCache()
    inserted = []

    async def fake_ensure_user(user_id):
        inserted.append(user_id)

    monkeypatch.setattr(models.database_settings, "url", "postgresql+asyncpg://test")
    monkeypatch.setattr(cache_provider, "get_cache", lambda: cache)
    monkeypatch.setattr(models, "ensure_user", fake_ensure_user)
    return models, cache, inserted


def test_first_login_provisions_the_user_once(user_store):
    models, cache, inserted = user_store

    asyncio.run(models.ensure_user_cached(SUB))
    asyncio.run(models.ensure_user_cached(SUB))

    assert inserted == [SUB]


def test_user_seen_by_another_worker_is_not_provisioned_again(user_store):
    models, cache, inserted = user_store
    asyncio.run(cache.set(f"user_seen_{SUB}", True))

    asyncio.run(models.ensure_user_cached(SUB))

    assert inserted == []


def test_concurrent_first_logins_do_not_fail(monkeypatch):
    """Two requests from a new User race on INSERT; the loser must not get an error."""
    from contextlib import asynccontextmanager

    from sqlalchemy.exc import IntegrityError

    import cea.interfaces.dashboard.lib.database.models as models

    class _NoRowYet:
        def scalar(self):
            return None

    class _Session:
        async def execute(self, statement):
            return _NoRowYet()

        def add(self, row):
            pass

    @asynccontextmanager
    async def losing_session():
        yield _Session()
        raise IntegrityError("INSERT INTO user", {}, Exception("duplicate key"))  # raised at commit

    monkeypatch.setattr(models, "get_session_context", losing_session)

    asyncio.run(models.ensure_user(SUB))
