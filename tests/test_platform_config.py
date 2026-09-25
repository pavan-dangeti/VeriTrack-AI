"""Deployment-facing behaviour: config normalisation, headers, compression."""

import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+asyncpg://u:p@h/db?ssl=require"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
    ],
)
def test_provider_database_urls_are_normalised(given, expected):
    assert Settings(database_url=given).database_url == expected


def test_production_refuses_insecure_defaults():
    with pytest.raises(ValueError):
        Settings(environment="production", jwt_secret_key="short")
    with pytest.raises(ValueError):
        Settings(environment="production", jwt_secret_key="x" * 40, cors_origins="https://*.example.com")


def test_cross_site_cookies_force_secure():
    s = Settings(cookie_samesite="none")
    assert s.cookie_secure is True
    assert Settings().cookie_secure is False


async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers


async def test_large_json_is_gzip_compressed(client, ma_user_id):
    from tests.helpers import admin

    h = await admin(client)
    r = await client.get("/api/v1/audit-logs?limit=200", headers={**h, "Accept-Encoding": "gzip"})
    assert r.status_code == 200
    if len(r.content) > 1024:
        assert r.headers.get("content-encoding") == "gzip"


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_storage_backend_selection_in_production(monkeypatch):
    from app.core.config import settings
    from app.services import storage

    monkeypatch.setattr(settings, "environment", "production")
    for backend, ok in (("local", False), ("volume", True)):
        monkeypatch.setattr(settings, "storage_backend", backend)
        storage.reset_storage_for_tests()
        if ok:
            assert isinstance(storage.get_storage(), storage.LocalDiskBackend)
        else:
            with pytest.raises(storage.StorageError):
                storage.get_storage()
    storage.reset_storage_for_tests()
