#!/usr/bin/env python3
"""The NF-OSI MCP server.

Synapse metadata generation, submission, and project review, as one MCP
server. The tool functions live in nfty/curation.py; this module builds the
MCPServer instance and registers them onto it.
"""

import os
import sys

from mcp.server.mcpserver import MCPServer

from .curation import register_curation_tools

INSTRUCTIONS = """\
Synapse metadata generation, submission, and project review tools.

Two tools change things: create_dataset creates an entity, and submit_metadata
overwrites an entity's annotations. Both are marked in their annotations;
confirm with the user before calling either.
"""

DEFAULT_TRANSPORT = "stdio"


def create_server() -> MCPServer:
    """The server, with the curation tools registered onto it."""
    mcp = MCPServer(
        name="nfty",
        title="NF-OSI curation",
        instructions=INSTRUCTIONS,
    )
    count = register_curation_tools(mcp)
    print(f"Registered {count} curation tools", file=sys.stderr)
    return mcp


def main() -> int:
    """Entry point for the `nfty` command.

    Transport is chosen via MCP_TRANSPORT: "stdio" (the default) for a local
    client, or "streamable-http" to serve over HTTP. HTTP mode runs stateless,
    since these tools keep no state between calls, so it can run behind a
    load balancer without sticky sessions.
    """
    transport = os.environ.get("MCP_TRANSPORT", DEFAULT_TRANSPORT)
    server = create_server()

    if transport == "streamable-http":
        server.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8000")),
            stateless_http=True,
        )
    else:
        server.run(transport=transport)

    return 0


if __name__ == "__main__":
    sys.exit(main())
