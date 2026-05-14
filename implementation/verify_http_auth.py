from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from pathlib import Path

from fastmcp import Client

try:
    from .mcp_server import DEFAULT_AUTH_TOKEN
except ImportError:
    from mcp_server import DEFAULT_AUTH_TOKEN


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _print_pass(message: str) -> None:
    print(f"PASS: {message}")


async def _wait_for_server(url: str, token: str, proc: subprocess.Popen[str]) -> None:
    last_error: Exception | None = None
    for _ in range(60):
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"HTTP server exited early:\n{output}")
        try:
            async with Client(url, auth=token, timeout=5) as client:
                await client.list_tools()
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for HTTP MCP server: {last_error}")


async def _assert_rejected(url: str, auth: str | None, label: str) -> None:
    try:
        async with Client(url, auth=auth, timeout=5) as client:
            await client.list_tools()
    except Exception:
        _print_pass(f"{label} is rejected")
        return
    raise AssertionError(f"{label} unexpectedly connected")


async def _verify(url: str, token: str, proc: subprocess.Popen[str]) -> None:
    await _wait_for_server(url, token, proc)
    _print_pass("HTTP MCP server starts with bearer auth enabled")

    await _assert_rejected(url, None, "missing bearer token")
    await _assert_rejected(url, "wrong-token", "wrong bearer token")

    async with Client(url, auth=token, timeout=10) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {"search", "insert", "aggregate"}
        result = await client.call_tool(
            "aggregate",
            {"table": "students", "metric": "count"},
        )
        assert result.data["rows"][0]["value"] >= 6

    _print_pass("valid bearer token can discover tools and call aggregate")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    server = root / "implementation" / "mcp_server.py"
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"

    proc = subprocess.Popen(
        [
            sys.executable,
            str(server),
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--auth-token",
            DEFAULT_AUTH_TOKEN,
            "--no-show-banner",
        ],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        asyncio.run(_verify(url, DEFAULT_AUTH_TOKEN, proc))
        print("HTTP auth verification passed.")
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()


if __name__ == "__main__":
    main()

