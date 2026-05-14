from __future__ import annotations

import argparse
import json
import os
import warnings
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

try:
    from .db import DEFAULT_DB_PATH, SQLiteAdapter, ValidationError
    from .init_db import ensure_database
    from .postgres_db import PostgresAdapter
except ImportError:
    from db import DEFAULT_DB_PATH, SQLiteAdapter, ValidationError
    from init_db import ensure_database
    from postgres_db import PostgresAdapter


DEFAULT_AUTH_TOKEN = "sqlite-lab-demo-token"


def create_auth_provider(auth_token: str | None) -> Any | None:
    if not auth_token:
        return None
    warnings.filterwarnings(
        "ignore",
        message="authlib.jose module is deprecated.*",
        category=Warning,
    )
    from fastmcp.server.auth import StaticTokenVerifier

    return StaticTokenVerifier(
        tokens={
            auth_token: {
                "client_id": "sqlite-lab-demo-client",
                "scopes": ["database:read", "database:write"],
            }
        }
    )


def create_adapter(
    backend: str = "sqlite",
    db_path: str | Path = DEFAULT_DB_PATH,
    postgres_dsn: str | None = None,
    postgres_schema: str = "public",
) -> Any:
    backend_name = backend.strip().lower()
    if backend_name == "sqlite":
        path = ensure_database(db_path)
        return SQLiteAdapter(path)
    if backend_name in {"postgres", "postgresql"}:
        dsn = postgres_dsn or os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL")
        if not dsn:
            raise ValidationError(
                "PostgreSQL backend selected but no DSN was provided. "
                "Use --postgres-dsn or POSTGRES_DSN."
            )
        return PostgresAdapter(dsn=dsn, schema=postgres_schema)
    raise ValidationError("Unsupported backend. Use 'sqlite' or 'postgres'.")


def create_server(adapter: Any | None = None, auth_token: str | None = None) -> FastMCP:
    db = adapter or SQLiteAdapter(DEFAULT_DB_PATH)
    server = FastMCP(
        "SQLite Lab MCP Server",
        auth=create_auth_provider(auth_token),
        list_page_size=50,
    )

    @server.tool(
        name="search",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def search(
        table: str,
        filters: dict[str, Any] | list[dict[str, Any]] | None = None,
        columns: list[str] | str | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
    ) -> dict[str, Any]:
        """Search table rows with validated filters, ordering, limit, and offset."""
        try:
            return db.search(
                table=table,
                columns=columns,
                filters=filters,
                limit=limit,
                offset=offset,
                order_by=order_by,
                descending=descending,
            )
        except ValidationError as exc:
            raise ValueError(str(exc))

    @server.tool(
        name="insert",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def insert(
        table: str,
        values: dict[str, Any] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Insert one or more rows after validating table and column names."""
        try:
            return db.insert(table=table, values=values)
        except ValidationError as exc:
            raise ValueError(str(exc))

    @server.tool(
        name="aggregate",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def aggregate(
        table: str,
        metric: str,
        column: str | None = None,
        filters: dict[str, Any] | list[dict[str, Any]] | None = None,
        group_by: list[str] | str | None = None,
    ) -> dict[str, Any]:
        """Run count, avg, sum, min, or max with optional filters and grouping."""
        try:
            return db.aggregate(
                table=table,
                metric=metric,
                column=column,
                filters=filters,
                group_by=group_by,
            )
        except ValidationError as exc:
            raise ValueError(str(exc))

    @server.resource(
        "schema://database",
        name="database_schema",
        description="Full SQLite database schema and row counts.",
        mime_type="application/json",
    )
    def database_schema() -> str:
        return json.dumps(db.get_database_schema(), indent=2)

    @server.resource(
        "schema://table/{table_name}",
        name="table_schema",
        description="Schema for a single SQLite table.",
        mime_type="application/json",
    )
    def table_schema(table_name: str) -> str:
        try:
            return json.dumps(db.get_table_schema(table_name), indent=2)
        except ValidationError as exc:
            raise ValueError(str(exc))

    return server


def _db_path_from_env() -> Path:
    return Path(os.environ.get("SQLITE_LAB_DB_PATH", str(DEFAULT_DB_PATH)))


def _backend_from_env() -> str:
    return os.environ.get("SQLITE_LAB_BACKEND", "sqlite")


def _auth_token_from_env() -> str | None:
    return os.environ.get("SQLITE_LAB_AUTH_TOKEN")


def build_default_server() -> FastMCP:
    adapter = create_adapter(
        backend=_backend_from_env(),
        db_path=_db_path_from_env(),
        postgres_dsn=os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL"),
        postgres_schema=os.environ.get("POSTGRES_SCHEMA", "public"),
    )
    return create_server(adapter, auth_token=_auth_token_from_env())


mcp = build_default_server()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SQLite lab MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP/SSE transports.")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP/SSE transports.")
    parser.add_argument(
        "--backend",
        choices=["sqlite", "postgres", "postgresql"],
        default=_backend_from_env(),
        help="Database backend. SQLite is the default; PostgreSQL is optional bonus support.",
    )
    parser.add_argument("--db-path", default=str(_db_path_from_env()), help="SQLite database path.")
    parser.add_argument(
        "--postgres-dsn",
        default=os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL"),
        help="PostgreSQL DSN for --backend postgres.",
    )
    parser.add_argument(
        "--postgres-schema",
        default=os.environ.get("POSTGRES_SCHEMA", "public"),
        help="PostgreSQL schema to expose.",
    )
    parser.add_argument(
        "--auth-token",
        default=_auth_token_from_env(),
        help=(
            "Optional bearer token for HTTP/SSE transports. "
            f"For local demos, use {DEFAULT_AUTH_TOKEN!r}."
        ),
    )
    parser.add_argument(
        "--show-banner",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Show FastMCP startup banner.",
    )
    args = parser.parse_args()

    adapter = create_adapter(
        backend=args.backend,
        db_path=args.db_path,
        postgres_dsn=args.postgres_dsn,
        postgres_schema=args.postgres_schema,
    )
    server = create_server(adapter, auth_token=args.auth_token)

    transport_kwargs: dict[str, Any] = {}
    if args.transport != "stdio":
        transport_kwargs.update({"host": args.host, "port": args.port})

    server.run(
        transport=args.transport,
        show_banner=args.show_banner,
        **transport_kwargs,
    )


if __name__ == "__main__":
    main()
