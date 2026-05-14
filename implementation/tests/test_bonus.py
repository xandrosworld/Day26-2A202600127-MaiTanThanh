from __future__ import annotations

import asyncio

import pytest

from implementation.db import SQLiteAdapter, ValidationError
from implementation.mcp_server import create_adapter, create_auth_provider
from implementation.postgres_db import PostgresAdapter


def test_static_auth_provider_accepts_only_configured_token():
    async def scenario() -> None:
        provider = create_auth_provider("demo-token")
        assert provider is not None

        good = await provider.verify_token("demo-token")
        bad = await provider.verify_token("wrong-token")

        assert good is not None
        assert good.client_id == "sqlite-lab-demo-client"
        assert bad is None

    asyncio.run(scenario())


def test_sqlite_factory_initializes_database(tmp_path):
    adapter = create_adapter("sqlite", db_path=tmp_path / "lab.sqlite3")

    assert isinstance(adapter, SQLiteAdapter)
    assert {"students", "courses", "enrollments"} <= set(adapter.list_tables())


def test_postgres_factory_is_optional_and_lazy():
    adapter = create_adapter(
        "postgres",
        postgres_dsn="postgresql://user:password@localhost:5432/lab",
    )

    assert isinstance(adapter, PostgresAdapter)


def test_postgres_factory_requires_dsn(monkeypatch):
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="no DSN"):
        create_adapter("postgres")

