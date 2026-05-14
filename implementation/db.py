from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "lab.sqlite3"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ValidationError(ValueError):
    """Raised when a request cannot be safely executed."""


class SQLiteAdapter:
    """Small, validated SQLite data layer for the MCP tools."""

    OPERATOR_ALIASES = {
        "=": "=",
        "eq": "=",
        "==": "=",
        "!=": "!=",
        "<>": "!=",
        "ne": "!=",
        ">": ">",
        "gt": ">",
        ">=": ">=",
        "gte": ">=",
        "<": "<",
        "lt": "<",
        "<=": "<=",
        "lte": "<=",
        "like": "LIKE",
        "contains": "CONTAINS",
        "startswith": "STARTSWITH",
        "endswith": "ENDSWITH",
        "in": "IN",
        "is_null": "IS NULL",
        "null": "IS NULL",
        "not_null": "IS NOT NULL",
        "is_not_null": "IS NOT NULL",
    }

    AGGREGATE_METRICS = {"count", "avg", "sum", "min", "max"}
    NUMERIC_TYPE_MARKERS = ("INT", "REAL", "NUM", "DEC", "DOUBLE", "FLOAT")

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def list_tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        return [row["name"] for row in rows]

    def get_table_schema(self, table: str) -> dict[str, Any]:
        table_name = self._require_table(table)
        quoted_table = self._quote_identifier(table_name)

        with self.connect() as conn:
            column_rows = conn.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            foreign_key_rows = conn.execute(
                f"PRAGMA foreign_key_list({quoted_table})"
            ).fetchall()
            row_count = conn.execute(
                f"SELECT COUNT(*) AS row_count FROM {quoted_table}"
            ).fetchone()["row_count"]

        columns = [
            {
                "name": row["name"],
                "type": row["type"],
                "nullable": not bool(row["notnull"]),
                "default": row["dflt_value"],
                "primary_key": bool(row["pk"]),
            }
            for row in column_rows
        ]
        foreign_keys = [
            {
                "column": row["from"],
                "references_table": row["table"],
                "references_column": row["to"],
                "on_update": row["on_update"],
                "on_delete": row["on_delete"],
            }
            for row in foreign_key_rows
        ]
        return {
            "table": table_name,
            "row_count": row_count,
            "columns": columns,
            "foreign_keys": foreign_keys,
        }

    def get_database_schema(self) -> dict[str, Any]:
        return {
            "database": str(self.db_path),
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
        sql = f"SELECT {select_sql} FROM {self._quote_identifier(table_name)}{where_sql}"

        if order_by is not None:
            order_column = self._require_column(table_name, order_by)
            direction = "DESC" if self._coerce_bool(descending) else "ASC"
            sql += f" ORDER BY {self._quote_identifier(order_column)} {direction}"

        sql += " LIMIT ? OFFSET ?"
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
        schema = self.get_table_schema(table_name)
        known_columns = {column["name"] for column in schema["columns"]}
        primary_keys = [column["name"] for column in schema["columns"] if column["primary_key"]]

        for record in records:
            unknown_columns = sorted(set(record) - known_columns)
            if unknown_columns:
                raise ValidationError(
                    f"Unknown column(s) for table '{table_name}': {', '.join(unknown_columns)}."
                )

        inserted_rows: list[dict[str, Any]] = []
        try:
            with self.connect() as conn:
                for record in records:
                    columns = list(record.keys())
                    quoted_columns = ", ".join(self._quote_identifier(column) for column in columns)
                    placeholders = ", ".join("?" for _ in columns)
                    sql = (
                        f"INSERT INTO {self._quote_identifier(table_name)} "
                        f"({quoted_columns}) VALUES ({placeholders})"
                    )
                    cursor = conn.execute(sql, [record[column] for column in columns])
                    inserted_rows.append(
                        self._fetch_inserted_row(
                            conn=conn,
                            table=table_name,
                            record=record,
                            primary_keys=primary_keys,
                            lastrowid=cursor.lastrowid,
                        )
                    )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Insert failed integrity checks: {exc}.") from exc

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
        sql = (
            f"SELECT {group_select}{expression} AS value "
            f"FROM {self._quote_identifier(table_name)}{where_sql}"
        )
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

    def _fetch_inserted_row(
        self,
        conn: sqlite3.Connection,
        table: str,
        record: Mapping[str, Any],
        primary_keys: Sequence[str],
        lastrowid: int | None,
    ) -> dict[str, Any]:
        if len(primary_keys) == 1:
            primary_key = primary_keys[0]
            key_value = record.get(primary_key, lastrowid)
            if key_value is not None:
                row = conn.execute(
                    (
                        f"SELECT * FROM {self._quote_identifier(table)} "
                        f"WHERE {self._quote_identifier(primary_key)} = ?"
                    ),
                    [key_value],
                ).fetchone()
                if row is not None:
                    return dict(row)
        return dict(record)

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
            item["name"]: item["type"].upper()
            for item in self.get_table_schema(table)["columns"]
        }
        return any(marker in column_types[column] for marker in self.NUMERIC_TYPE_MARKERS)

    def _build_where_clause(self, table: str, filters: Any) -> tuple[str, list[Any]]:
        normalized_filters = self._normalize_filters(filters)
        if not normalized_filters:
            return "", []

        clauses: list[str] = []
        params: list[Any] = []
        for column, operator, value in normalized_filters:
            column_name = self._require_column(table, column)
            quoted_column = self._quote_identifier(column_name)
            sql_operator = self._normalize_operator(operator)

            if sql_operator == "IS NULL":
                clauses.append(f"{quoted_column} IS NULL")
            elif sql_operator == "IS NOT NULL":
                clauses.append(f"{quoted_column} IS NOT NULL")
            elif sql_operator == "IN":
                values = self._normalize_in_values(column_name, value)
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{quoted_column} IN ({placeholders})")
                params.extend(values)
            elif value is None and sql_operator == "=":
                clauses.append(f"{quoted_column} IS NULL")
            elif value is None and sql_operator == "!=":
                clauses.append(f"{quoted_column} IS NOT NULL")
            elif sql_operator in {"LIKE", "CONTAINS", "STARTSWITH", "ENDSWITH"}:
                pattern = self._like_pattern(sql_operator, value)
                clauses.append(f"{quoted_column} LIKE ?")
                params.append(pattern)
            else:
                clauses.append(f"{quoted_column} {sql_operator} ?")
                params.append(value)

        return " WHERE " + " AND ".join(clauses), params

    def _normalize_filters(self, filters: Any) -> list[tuple[str, str, Any]]:
        if filters in (None, "", [], {}):
            return []

        normalized: list[tuple[str, str, Any]] = []
        if isinstance(filters, Mapping):
            for column, spec in filters.items():
                if isinstance(spec, Mapping):
                    operator = spec.get("op", spec.get("operator", "="))
                    if "value" in spec:
                        value = spec["value"]
                    elif "values" in spec:
                        value = spec["values"]
                    elif str(operator).strip().lower() in {"is_null", "null", "not_null", "is_not_null"}:
                        value = None
                    else:
                        raise ValidationError(f"Filter for column '{column}' is missing a value.")
                elif isinstance(spec, Sequence) and not isinstance(spec, (str, bytes, bytearray)):
                    operator = "in"
                    value = list(spec)
                else:
                    operator = "="
                    value = spec
                normalized.append((str(column), str(operator), value))
            return normalized

        if isinstance(filters, Sequence) and not isinstance(filters, (str, bytes, bytearray)):
            for index, item in enumerate(filters):
                if not isinstance(item, Mapping):
                    raise ValidationError(f"Filter at index {index} must be an object.")
                column = item.get("column", item.get("field"))
                if not column:
                    raise ValidationError(f"Filter at index {index} is missing 'column'.")
                operator = item.get("op", item.get("operator", "="))
                if "value" in item:
                    value = item["value"]
                elif "values" in item:
                    value = item["values"]
                elif str(operator).strip().lower() in {"is_null", "null", "not_null", "is_not_null"}:
                    value = None
                else:
                    raise ValidationError(f"Filter for column '{column}' is missing a value.")
                normalized.append((str(column), str(operator), value))
            return normalized

        raise ValidationError("Filters must be an object or a list of filter objects.")

    def _normalize_operator(self, operator: str) -> str:
        normalized = str(operator).strip().lower()
        if normalized not in self.OPERATOR_ALIASES:
            raise ValidationError(
                f"Unsupported filter operator '{operator}'. Supported operators: "
                f"{', '.join(sorted(self.OPERATOR_ALIASES))}."
            )
        return self.OPERATOR_ALIASES[normalized]

    def _normalize_in_values(self, column: str, value: Any) -> list[Any]:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
            raise ValidationError(f"Filter operator 'in' for column '{column}' requires a list.")
        values = list(value)
        if not values:
            raise ValidationError(f"Filter operator 'in' for column '{column}' cannot use an empty list.")
        if len(values) > MAX_LIMIT:
            raise ValidationError(f"Filter operator 'in' supports at most {MAX_LIMIT} values.")
        return values

    def _like_pattern(self, sql_operator: str, value: Any) -> str:
        if value is None:
            raise ValidationError("LIKE-style filters require a non-null value.")
        text = str(value)
        if sql_operator == "CONTAINS":
            return f"%{text}%"
        if sql_operator == "STARTSWITH":
            return f"{text}%"
        if sql_operator == "ENDSWITH":
            return f"%{text}"
        return text

    def _normalize_insert_records(
        self, values: Mapping[str, Any] | Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        if isinstance(values, Mapping):
            records = [dict(values)]
        elif isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            records = []
            for index, item in enumerate(values):
                if not isinstance(item, Mapping):
                    raise ValidationError(f"Insert record at index {index} must be an object.")
                records.append(dict(item))
        else:
            raise ValidationError("Insert values must be an object or a list of objects.")

        if not records:
            raise ValidationError("Insert values cannot be empty.")
        for record in records:
            if not record:
                raise ValidationError("Insert values cannot be empty.")
        return records

    def _normalize_column_list(self, table: str, columns: Sequence[str] | str | None) -> list[str]:
        if columns is None or columns == "*":
            return self._columns_for_table(table)
        if isinstance(columns, str):
            selected_columns = [column.strip() for column in columns.split(",")]
        elif isinstance(columns, Sequence):
            selected_columns = [str(column).strip() for column in columns]
        else:
            raise ValidationError("Columns must be a string, a list of strings, or null.")

        selected_columns = [column for column in selected_columns if column]
        if not selected_columns:
            raise ValidationError("Columns cannot be empty.")
        return [self._require_column(table, column) for column in selected_columns]

    def _normalize_group_by(self, table: str, group_by: Sequence[str] | str | None) -> list[str]:
        if group_by in (None, "", []):
            return []
        if isinstance(group_by, str):
            group_columns = [column.strip() for column in group_by.split(",")]
        elif isinstance(group_by, Sequence):
            group_columns = [str(column).strip() for column in group_by]
        else:
            raise ValidationError("group_by must be a string, a list of strings, or null.")

        group_columns = [column for column in group_columns if column]
        if not group_columns:
            raise ValidationError("group_by cannot be empty.")
        return [self._require_column(table, column) for column in group_columns]

    def _normalize_limit(self, limit: int | str | None) -> int:
        if limit is None:
            return DEFAULT_LIMIT
        if isinstance(limit, bool):
            raise ValidationError("Limit must be an integer.")
        try:
            normalized = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Limit must be an integer.") from exc
        if normalized < 1 or normalized > MAX_LIMIT:
            raise ValidationError(f"Limit must be between 1 and {MAX_LIMIT}.")
        return normalized

    def _normalize_offset(self, offset: int | str | None) -> int:
        if offset is None:
            return 0
        if isinstance(offset, bool):
            raise ValidationError("Offset must be an integer.")
        try:
            normalized = int(offset)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Offset must be an integer.") from exc
        if normalized < 0:
            raise ValidationError("Offset must be zero or greater.")
        return normalized

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)

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

