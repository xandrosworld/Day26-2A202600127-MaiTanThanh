from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from fastmcp import Client


logging.getLogger("fastmcp").setLevel(logging.CRITICAL)

try:
    from .db import DEFAULT_DB_PATH, SQLiteAdapter
    from .init_db import create_database
    from .mcp_server import create_server
except ImportError:
    from db import DEFAULT_DB_PATH, SQLiteAdapter
    from init_db import create_database
    from mcp_server import create_server


def _print_pass(message: str) -> None:
    print(f"PASS: {message}")


async def verify(db_path: Path) -> None:
    create_database(db_path, reset=True)
    server = create_server(SQLiteAdapter(db_path))

    async with Client(server) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        assert {"search", "insert", "aggregate"} == tool_names
        _print_pass("exactly search, insert, aggregate tools are discoverable")

        resources = await client.list_resources()
        resource_uris = {str(resource.uri) for resource in resources}
        assert "schema://database" in resource_uris
        _print_pass("schema://database resource is discoverable")

        templates = await client.list_resource_templates()
        template_uris = {str(template.uriTemplate) for template in templates}
        assert "schema://table/{table_name}" in template_uris
        _print_pass("schema://table/{table_name} resource template is discoverable")

        database_schema = await client.read_resource("schema://database")
        parsed_database_schema = json.loads(database_schema[0].text)
        assert {"students", "courses", "enrollments"} <= set(parsed_database_schema["tables"])
        _print_pass("full schema resource is readable")

        student_schema = await client.read_resource("schema://table/students")
        parsed_student_schema = json.loads(student_schema[0].text)
        assert parsed_student_schema["table"] == "students"
        _print_pass("single table schema resource is readable")

        search_result = await client.call_tool(
            "search",
            {
                "table": "students",
                "filters": {"cohort": "A1"},
                "columns": ["student_code", "name", "cohort", "gpa"],
                "order_by": "gpa",
                "descending": True,
                "limit": 2,
            },
        )
        assert search_result.data["count"] == 2
        assert search_result.data["rows"][0]["gpa"] >= search_result.data["rows"][1]["gpa"]
        _print_pass("valid search call returns ordered rows")

        insert_result = await client.call_tool(
            "insert",
            {
                "table": "students",
                "values": {
                    "student_code": "2A202699999",
                    "name": "Demo Student",
                    "cohort": "A3",
                    "email": "demo.student@example.edu",
                    "gpa": 3.51,
                },
            },
        )
        assert insert_result.data["inserted_count"] == 1
        assert insert_result.data["rows"][0]["id"] > 0
        _print_pass("valid insert call returns inserted payload with generated id")

        aggregate_result = await client.call_tool(
            "aggregate",
            {
                "table": "students",
                "metric": "avg",
                "column": "gpa",
                "group_by": "cohort",
            },
        )
        cohorts = {row["cohort"] for row in aggregate_result.data["rows"]}
        assert {"A1", "A2", "A3", "B1"} <= cohorts
        _print_pass("valid aggregate call returns grouped metrics")

        invalid_result = await client.call_tool(
            "search",
            {"table": "missing_table"},
            raise_on_error=False,
        )
        assert invalid_result.is_error
        assert "Unknown table" in invalid_result.content[0].text
        _print_pass("invalid tool call returns a clear MCP error")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeatable MCP server verification.")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH.with_name("verify.sqlite3")),
        help="Temporary SQLite database used for verification.",
    )
    args = parser.parse_args()
    asyncio.run(verify(Path(args.db_path)))
    print("All verification checks passed.")


if __name__ == "__main__":
    main()
