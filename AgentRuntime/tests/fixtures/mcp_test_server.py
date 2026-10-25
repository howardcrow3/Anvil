"""Tiny MCP server used by tests. ``python mcp_test_server.py`` serves stdio;
``python mcp_test_server.py http <port>`` serves streamable HTTP at /mcp."""

import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("anvil-test")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@server.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return f"echo:{text}"


@server.tool()
def boom() -> str:
    """Always fails."""
    raise RuntimeError("kaboom")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        import anyio

        port = int(sys.argv[2])

        async def _serve() -> None:
            await server.run_streamable_http_async(host="127.0.0.1", port=port)

        anyio.run(_serve)
    else:
        server.run("stdio")
