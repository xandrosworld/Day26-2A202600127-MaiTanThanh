from __future__ import annotations

import asyncio
import json

from fastmcp import Client

from implementation.db import SQLiteAdapter
from implementation.init_db import create_database
from implementation.mcp_server import create_server


def test_fastmcp_tools_resources_and_error_flow(tmp_path):
    async def scenario() -> None:
        db_path = create_database(tmp_path / "lab.sqlite3", reset=True)
        server = create_server(SQLiteAdapter(db_path))

        async with Client(server) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {"search", "insert", "aggregate"}

            resources = await client.list_resources()
            assert "schema://database" in {str(resource.uri) for resource in resources}

            templates = await client.list_resource_templates()
            assert "schema://table/{table_name}" in {
                str(template.uriTemplate) for template in templates
            }

            table_schema = await client.read_resource("schema://table/students")
            parsed_schema = json.loads(table_schema[0].text)
            assert parsed_schema["table"] == "students"

            search_result = await client.call_tool(
                "search",
                {
                    "table": "students",
                    "filters": {"cohort": "A1"},
                    "limit": 3,
                    "order_by": "gpa",
                    "descending": True,
                },
            )
            assert search_result.data["count"] == 3

            bad_result = await client.call_tool(
                "aggregate",
                {"table": "students", "metric": "median", "column": "gpa"},
                raise_on_error=False,
            )
            assert bad_result.is_error
            assert "Unsupported aggregate metric" in bad_result.content[0].text

    asyncio.run(scenario())

