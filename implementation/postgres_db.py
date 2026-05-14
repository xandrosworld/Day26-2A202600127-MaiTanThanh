from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

try:
    from .db import DEFAULT_LIMIT, MAX_LIMIT, SQLiteAdapter, ValidationError
except ImportError:
    from db import DEFAULT_LIMIT, MAX_LIMIT, SQLiteAdapter, ValidationError


class PostgresAdapter:
    """Optional PostgreSQL adapter with the same MCP surface as SQLiteAdapter.

    The default lab path uses SQLite. This adapter is intentionally optional so
    students and graders can run the base lab without a PostgreSQL service or
    psycopg installed, while still showing a clean swap point for bonus work.
    """

    AGGREGATE_METRICS = SQLiteAdapter.AGGREGATE_METRICS
    OPERATOR_ALIASES = SQLiteAdapter.OPERATOR_ALIASES
    NUMERIC_TYPE_NAMES = {
        "smallint",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "real",
        "double precision",
        "smallserial",
        "serial",
        "bigserial",
    }

    def __init__(self, dsn: str, schema: str = "public"):
        if not dsn:
            raise ValidationError("PostgreSQL DSN must be provided.")
        self.dsn = dsn
        self.schema = schema

    def connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL support requires psycopg. Install with "
                "`python -m pip install -r requirements-postgres.txt`."
            ) from exc

        return psycopg.connect(self.dsn, row_factory=dict_row)

    def list_tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                [self.schema],
            ).fetchall()
        return [row["table_name"] for row in rows]

    def get_table_schema(self, table: str) -> dict[str, Any]:
        table_name = self._require_table(table)
        with self.connect() as conn:
            columns = conn.execute(
                """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                [self.schema, table_name],
            ).fetchall()
            primary_keys = conn.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                 AND tc.table_name = kcu.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = %s
                  AND tc.table_name = %s
                """,
                [self.schema, table_name],
            ).fetchall()
            foreign_keys = conn.execute(
                """
                SELECT
                    kcu.column_name AS column_name,
                    ccu.table_name AS references_table,
                    ccu.column_name AS references_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                 AND tc.table_name = kcu.table_name
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = %s
                  AND tc.table_name = %s
                """,
                [self.schema, table_name],
            ).fetchall()
            row_count = conn.execute(
                f"SELECT COUNT(*) AS row_count FROM {self._table_ref(table_name)}"
            ).fetchone()["row_count"]

        pk_names = {row["column_name"] for row in primary_keys}
        return {
            "table": table_name,
            "row_count": row_count,
            "columns": [
                {
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES",
                    "default": row["column_default"],
                    "primary_key": row["column_name"] in pk_names,
                }
                for row in columns
            ],
            "foreign_keys": [
                {
                    "column": row["column_name"],
                    "references_table": row["references_table"],
                    "references_column": row["references_column"],
                    "on_update": None,
                    "on_delete": None,
                }
                for row in foreign_keys
            ],
        }

    def get_database_schema(self) -> dict[str, Any]:
        return {
            "database": self._redacted_dsn(),
            "schema": self.schema,
            "tables": {
                table_name: self.get_table_schema(table_name)
                for table_name in self.list_tables()
            },
        }

    def search(
        self,
        table: str,
        columns: Sequence[str] | str | None = None,
        filters: Any = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
    ) -> dict[str, Any]:
        table_name = self._require_table(table)
        selected_columns = self._normalize_column_list(table_name, columns)
        normalized_limit = self._normalize_limit(limit)
        normalized_offset = self._normalize_offset(offset)
        where_sql, params = self._build_where_clause(table_name, filters)

        select_sql = ", ".join(self._quote_identifier(column) for column in selected_columns)
        sql = f"SELECT {select_sql} FROM {self._table_ref(table_name)}{where_sql}"
        if order_by is not None:
            order_column = self._require_column(table_name, order_by)
            direction = "DESC" if self._coerce_bool(descending) else "ASC"
            sql += f" ORDER BY {self._quote_identifier(order_column)} {direction}"
        sql += " LIMIT %s OFFSET %s"
        params.extend([normalized_limit, normalized_offset])

        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

        return {
            "table": table_name,
            "columns": selected_columns,
            "filters": filters or {},
            "limit": normalized_limit,
            "offset": normalized_offset,
            "order_by": order_by,
            "descending": self._coerce_bool(descending),
            "count": len(rows),
            "rows": rows,
        }

    def insert(self, table: str, values: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        table_name = self._require_table(table)
        records = self._normalize_insert_records(values)
        known_columns = set(self._columns_for_table(table_name))

        inserted_rows: list[dict[str, Any]] = []
        with self.connect() as conn:
            for record in records:
                unknown_columns = sorted(set(record) - known_columns)
                if unknown_columns:
                    raise ValidationError(
                        f"Unknown column(s) for table '{table_name}': {', '.join(unknown_columns)}."
                    )
                columns = list(record.keys())
                quoted_columns = ", ".join(self._quote_identifier(column) for column in columns)
                placeholders = ", ".join("%s" for _ in columns)
                sql = (
                    f"INSERT INTO {self._table_ref(table_name)} "
                    f"({quoted_columns}) VALUES ({placeholders}) RETURNING *"
                )
                inserted_rows.append(
                    dict(conn.execute(sql, [record[column] for column in columns]).fetchone())
                )
            conn.commit()

        return {
            "table": table_name,
            "inserted_count": len(inserted_rows),
            "rows": inserted_rows,
        }

    def aggregate(
        self,
        table: str,
        metric: str,
        column: str | None = None,
        filters: Any = None,
        group_by: Sequence[str] | str | None = None,
    ) -> dict[str, Any]:
        table_name = self._require_table(table)
        metric_name = str(metric).strip().lower()
        if metric_name not in self.AGGREGATE_METRICS:
            raise ValidationError(
                "Unsupported aggregate metric. Use one of: "
                f"{', '.join(sorted(self.AGGREGATE_METRICS))}."
            )

        aggregate_column = self._aggregate_column(table_name, metric_name, column)
        group_columns = self._normalize_group_by(table_name, group_by)
        where_sql, params = self._build_where_clause(table_name, filters)

        group_select = ""
        if group_columns:
            group_select = ", ".join(self._quote_identifier(column) for column in group_columns)
            group_select += ", "
        expression = self._aggregate_expression(metric_name, aggregate_column)
        sql = f"SELECT {group_select}{expression} AS value FROM {self._table_ref(table_name)}{where_sql}"
        if group_columns:
            group_sql = ", ".join(self._quote_identifier(column) for column in group_columns)
            sql += f" GROUP BY {group_sql} ORDER BY {group_sql}"

        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

        return {
            "table": table_name,
            "metric": metric_name,
            "column": aggregate_column or "*",
            "filters": filters or {},
            "group_by": group_columns,
            "rows": rows,
        }

    def _build_where_clause(self, table: str, filters: Any) -> tuple[str, list[Any]]:
        normalized_filters = SQLiteAdapter._normalize_filters(self, filters)
        if not normalized_filters:
            return "", []

        clauses: list[str] = []
        params: list[Any] = []
        for column, operator, value in normalized_filters:
            column_name = self._require_column(table, column)
            quoted_column = self._quote_identifier(column_name)
            sql_operator = SQLiteAdapter._normalize_operator(self, operator)

            if sql_operator == "IS NULL":
                clauses.append(f"{quoted_column} IS NULL")
            elif sql_operator == "IS NOT NULL":
                clauses.append(f"{quoted_column} IS NOT NULL")
            elif sql_operator == "IN":
                values = SQLiteAdapter._normalize_in_values(self, column_name, value)
                placeholders = ", ".join("%s" for _ in values)
                clauses.append(f"{quoted_column} IN ({placeholders})")
                params.extend(values)
            elif value is None and sql_operator == "=":
                clauses.append(f"{quoted_column} IS NULL")
            elif value is None and sql_operator == "!=":
                clauses.append(f"{quoted_column} IS NOT NULL")
            elif sql_operator in {"LIKE", "CONTAINS", "STARTSWITH", "ENDSWITH"}:
                pattern = SQLiteAdapter._like_pattern(self, sql_operator, value)
                clauses.append(f"{quoted_column} LIKE %s")
                params.append(pattern)
            else:
                clauses.append(f"{quoted_column} {sql_operator} %s")
                params.append(value)

        return " WHERE " + " AND ".join(clauses), params

    def _aggregate_column(self, table: str, metric: str, column: str | None) -> str | None:
        if metric == "count":
            if column in (None, "", "*"):
                return None
            return self._require_column(table, column)
        if column in (None, "", "*"):
            raise ValidationError(f"Aggregate metric '{metric}' requires a concrete column.")
        column_name = self._require_column(table, column)
        if metric in {"avg", "sum"} and not self._is_numeric_column(table, column_name):
            raise ValidationError(
                f"Aggregate metric '{metric}' requires a numeric column; "
                f"'{column_name}' is not numeric."
            )
        return column_name

    def _aggregate_expression(self, metric: str, column: str | None) -> str:
        if metric == "count" and column is None:
            return "COUNT(*)"
        return f"{metric.upper()}({self._quote_identifier(column or '')})"

    def _is_numeric_column(self, table: str, column: str) -> bool:
        column_types = {
            item["name"]: item["type"].lower()
            for item in self.get_table_schema(table)["columns"]
        }
        return column_types[column] in self.NUMERIC_TYPE_NAMES

    def _normalize_column_list(self, table: str, columns: Sequence[str] | str | None) -> list[str]:
        return SQLiteAdapter._normalize_column_list(self, table, columns)

    def _normalize_group_by(self, table: str, group_by: Sequence[str] | str | None) -> list[str]:
        return SQLiteAdapter._normalize_group_by(self, table, group_by)

    def _normalize_insert_records(
        self, values: Mapping[str, Any] | Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        return SQLiteAdapter._normalize_insert_records(self, values)

    def _normalize_limit(self, limit: int | str | None) -> int:
        return SQLiteAdapter._normalize_limit(self, limit)

    def _normalize_offset(self, offset: int | str | None) -> int:
        return SQLiteAdapter._normalize_offset(self, offset)

    def _coerce_bool(self, value: Any) -> bool:
        return SQLiteAdapter._coerce_bool(self, value)

    def _require_table(self, table: str) -> str:
        if not isinstance(table, str) or not table.strip():
            raise ValidationError("Table name must be a non-empty string.")
        table_name = table.strip()
        tables = self.list_tables()
        if table_name not in tables:
            available = ", ".join(tables) if tables else "none"
            raise ValidationError(
                f"Unknown table '{table_name}'. Available tables: {available}."
            )
        return table_name

    def _require_column(self, table: str, column: str) -> str:
        if not isinstance(column, str) or not column.strip():
            raise ValidationError("Column name must be a non-empty string.")
        column_name = column.strip()
        columns = self._columns_for_table(table)
        if column_name not in columns:
            raise ValidationError(
                f"Unknown column '{column_name}' for table '{table}'. "
                f"Available columns: {', '.join(columns)}."
            )
        return column_name

    def _columns_for_table(self, table: str) -> list[str]:
        schema = self.get_table_schema(table)
        return [column["name"] for column in schema["columns"]]

    def _quote_identifier(self, identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _table_ref(self, table: str) -> str:
        return f"{self._quote_identifier(self.schema)}.{self._quote_identifier(table)}"

    def _redacted_dsn(self) -> str:
        if "@" not in self.dsn or "://" not in self.dsn:
            return "postgresql://<redacted>"
        prefix, rest = self.dsn.split("://", 1)
        return f"{prefix}://<redacted>@{rest.split('@', 1)[1]}"
