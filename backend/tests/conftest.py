"""Never trust application DATABASE_URL. Allocate a fresh disposable database before imports."""

import os
import tempfile
import uuid
from pathlib import Path

import pytest

if os.environ.get("DATABASE_URL"):
    raise pytest.UsageError(
        "Refusing DATABASE_URL in tests. Unset it; use EASY_TEST_POSTGRES_ADMIN_URL only for an isolated temporary database."
    )
TEST_ROOT = Path(tempfile.mkdtemp(prefix="easy_test_"))
TEST_NAME = "easy_test_" + uuid.uuid4().hex
admin = os.environ.get("EASY_TEST_POSTGRES_ADMIN_URL")
if admin:
    from urllib.parse import urlsplit, urlunsplit

    import psycopg
    from psycopg import sql

    conn = psycopg.connect(admin, autocommit=True)
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_NAME)))
    conn.close()
    parts = urlsplit(admin)
    TEST_URL = urlunsplit(
        (parts.scheme, parts.netloc, "/" + TEST_NAME, parts.query, parts.fragment)
    ).replace("postgresql://", "postgresql+psycopg://")
else:
    TEST_URL = "sqlite:///" + str(TEST_ROOT / "test.db")
os.environ["DATABASE_URL"] = TEST_URL
os.environ["STAFF_TOKEN"] = "test-only-local-secret"
os.environ["REQUEST_LIMIT_PER_MINUTE"] = "100000"
os.environ["RAG_PATH"] = str(TEST_ROOT / "index")

from datetime import UTC, datetime

from app import clock
from app.config import settings
from app.db import Base, engine
from app.seed import seed


@pytest.fixture(autouse=True)
def disposable(monkeypatch):
    # A second enforceable guard surrounds every destructive call.
    if engine.url.render_as_string(hide_password=False) != TEST_URL or (
        admin and engine.url.database != TEST_NAME
    ):
        raise RuntimeError("Unsafe test engine")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed()
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2030, 6, 1, 15, 0, tzinfo=UTC))
    monkeypatch.setattr(settings, "ai_mode", "deterministic")
    monkeypatch.setattr(settings, "request_limit_per_minute", 100000)
    yield


@pytest.fixture
def client():
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    if admin:
        import psycopg
        from psycopg import sql

        conn = psycopg.connect(admin, autocommit=True)
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(TEST_NAME)))
        conn.close()
