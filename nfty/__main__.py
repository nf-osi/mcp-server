#!/usr/bin/env python3
"""The NF-OSI MCP server.

Synapse metadata generation, submission, and project review, as one MCP
server. The tool functions live in nfty/curation.py; this module builds the
MCPServer instance and registers them onto it.
"""

import sys

from mcp.server.mcpserver import MCPServer

from .curation import register_curation_tools

INSTRUCTIONS = """\
Synapse metadata generation, submission, and project review tools.

Two tools change things: create_dataset creates an entity, and submit_metadata
overwrites an entity's annotations. Both are marked in their annotations;
confirm with the user before calling either.
"""


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
    """Entry point for the `nfty` command."""
    create_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
