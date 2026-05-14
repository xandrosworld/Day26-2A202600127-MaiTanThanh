from __future__ import annotations

import pytest

from implementation.db import SQLiteAdapter, ValidationError
from implementation.init_db import create_database


def make_adapter(tmp_path) -> SQLiteAdapter:
    db_path = create_database(tmp_path / "lab.sqlite3", reset=True)
    return SQLiteAdapter(db_path)


def test_search_filters_ordering_and_pagination(tmp_path):
    adapter = make_adapter(tmp_path)

    result = adapter.search(
        "students",
        filters={"cohort": "A1"},
        columns=["student_code", "name", "cohort", "gpa"],
        limit=2,
        offset=0,
        order_by="gpa",
        descending=True,
    )

    assert result["count"] == 2
    assert all(row["cohort"] == "A1" for row in result["rows"])
    assert result["rows"][0]["gpa"] >= result["rows"][1]["gpa"]


def test_insert_returns_generated_payload(tmp_path):
    adapter = make_adapter(tmp_path)

    result = adapter.insert(
        "students",
        {
            "student_code": "2A202600999",
            "name": "Test Student",
            "cohort": "A3",
            "email": "test.student@example.edu",
            "gpa": 3.33,
        },
    )

    assert result["inserted_count"] == 1
    row = result["rows"][0]
    assert row["id"] > 0
    assert row["student_code"] == "2A202600999"


def test_aggregate_supports_avg_grouped_by_cohort(tmp_path):
    adapter = make_adapter(tmp_path)

    result = adapter.aggregate("students", "avg", column="gpa", group_by="cohort")

    cohorts = {row["cohort"] for row in result["rows"]}
    assert {"A1", "A2", "B1"} <= cohorts
    assert all(isinstance(row["value"], float) for row in result["rows"])


def test_schema_contains_tables_columns_and_foreign_keys(tmp_path):
    adapter = make_adapter(tmp_path)

    schema = adapter.get_database_schema()

    assert {"students", "courses", "enrollments"} <= set(schema["tables"])
    assert any(
        column["name"] == "student_code"
        for column in schema["tables"]["students"]["columns"]
    )
    assert schema["tables"]["enrollments"]["foreign_keys"]


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda adapter: adapter.search("missing_table"), "Unknown table"),
        (
            lambda adapter: adapter.search("students", columns=["missing_column"]),
            "Unknown column",
        ),
        (
            lambda adapter: adapter.search(
                "students",
                filters=[{"column": "cohort", "op": "regex", "value": "A.*"}],
            ),
            "Unsupported filter operator",
        ),
        (
            lambda adapter: adapter.aggregate("students", "median", column="gpa"),
            "Unsupported aggregate metric",
        ),
        (
            lambda adapter: adapter.aggregate("students", "sum", column="name"),
            "requires a numeric column",
        ),
        (lambda adapter: adapter.insert("students", {}), "Insert values cannot be empty"),
    ],
)
def test_validation_errors_are_clear(tmp_path, call, message):
    adapter = make_adapter(tmp_path)

    with pytest.raises(ValidationError, match=message):
        call(adapter)


def test_sql_injection_like_identifier_is_rejected(tmp_path):
    adapter = make_adapter(tmp_path)

    with pytest.raises(ValidationError, match="Unknown table"):
        adapter.search("students; DROP TABLE students; --")

