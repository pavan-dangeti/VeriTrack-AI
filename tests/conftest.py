import os
import tempfile

# Test DB + inline processing + local storage must be configured before app imports.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://veritrack:veritrack@localhost:5432/veritrack_test",
)
os.environ.setdefault("PROCESSING_MODE", "inline")
_TEST_STORAGE = tempfile.mkdtemp(prefix="veritrack-storage-")
os.environ.setdefault("LOCAL_STORAGE_ROOT", _TEST_STORAGE)
os.environ.setdefault("OCR_ENGINE", "test")

import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import engine

TABLES = ("users", "audit_logs", "approved_m365_domains", "refresh_tokens")


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
async def clean_state():
    """Full isolation between tests: truncate everything, reset rate limiter."""
    await engine.dispose()  # drop pooled connections bound to a previous loop
    limiter.reset()
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        )
    yield
    # tests that switch to the real OCR engine must not leak it to others
    from app.services.extraction.ocr import reset_ocr_engine_for_tests

    reset_ocr_engine_for_tests()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app_for_tests())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def app_for_tests():
    from app.main import app

    return app


async def seed_master_admin(email: str, password: str):
    from app.cli import create_master_admin

    rc, created = await create_master_admin(email, password, if_not_exists=False)
    assert rc == 0 and created
    from app.services.auth_service import get_user_by_email

    async with open_session() as db:
        user = await get_user_by_email(db, email)
        assert user is not None
        return user.id


def open_session():
    from app.db.session import get_session_factory

    return get_session_factory()()


MA_EMAIL = "ma@veritrack.io"
MA_PASSWORD = "Master!Pass123"


@pytest_asyncio.fixture
async def ma_user_id():
    return await seed_master_admin(MA_EMAIL, MA_PASSWORD)


async def login_access_token(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


__all__ = [
    "MA_EMAIL",
    "MA_PASSWORD",
    "auth_headers",
    "clean_state",
    "client",
    "login_access_token",
    "ma_user_id",
    "migrated_database",
    "settings",
]
