# Model Context Protocol (MCP) Servers for NF-OSI

A collection of MCP servers that give your AI assistant access to NF-OSI resources and tools.

## Available Servers

### [nfty](nfty/) (Python)
Nifty tools for Synapse data curation workflows. Enables AI assistants to:

- Query and extract metadata from Synapse datasets
- Validate metadata against JSON schemas
- Submit metadata as Synapse annotations
- Review and classify Synapse projects
- Retrieve Data Sharing Plans

**Status**: ✅ Production ready
**Language**: Python 3.8+
**Dependencies**: synapseclient, mcp, requests, jsonschema

### [memory](memory/) (Coming Soon)
Institutional memory and knowledge base for NF-OSI. Preserves:

- Team history and design decisions from official documentation as well as sources like Slack
- Tribal knowledge captured from long-time team members
- Standard operating procedures and common patterns
- Historical context for curation decisions
- Project-specific context and conversation state

**Status**: 🚧 Under development
**Language**: TBD

## Overview

This repository is organized as a **monorepo** containing multiple independent MCP servers. Each server:

- Is self-contained with its own dependencies
- Can be installed and used independently
- May be written in different programming languages
- Follows the MCP protocol for AI assistant integration

## Quick Start

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd mcp-server
   ```

2. **Install the server(s) you want to use**

   Each server has its own installation instructions in its subdirectory:
   - [nfty installation](nfty/README.md#installation)
   - [memory installation](memory/README.md#installation) (when available)

   You can install and use multiple servers simultaneously - they run as independent processes.

### Configuration

Each server is configured independently in your MCP client. You can enable one or multiple servers.

#### For Claude Desktop

Add to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**Linux**: `~/.config/Claude/claude_desktop_config.json`

**Single Server Example (nfty only):**
```json
{
  "mcpServers": {
    "nfty": {
      "command": "python",
      "args": ["/absolute/path/to/mcp-server/nfty/mcp_server.py"],
      "env": {
        "SYNAPSE_AUTH_TOKEN": "your-synapse-personal-access-token"
      }
    }
  }
}
```

**Multiple Servers Example:**
```json
{
  "mcpServers": {
    "nfty": {
      "command": "python",
      "args": ["/absolute/path/to/mcp-server/nfty/mcp_server.py"],
      "env": {
        "SYNAPSE_AUTH_TOKEN": "your-synapse-personal-access-token"
      }
    },
    "memory": {
      "command": "node",
      "args": ["/absolute/path/to/mcp-server/memory/build/index.js"],
      "env": {}
    }
  }
}
```

**Important**: Replace `/absolute/path/to/mcp-server` with the actual path to your repository.

**Note**: Each server runs as an independent process. You can enable/disable servers by adding/removing them from the configuration.

```

#### For Other MCP Clients

Refer to your client's documentation for MCP server configuration. Each server's configuration follows this pattern:

**For nfty (Python):**
- **Command**: `python`
- **Args**: `["/path/to/mcp-server/nfty/mcp_server.py"]`
- **Environment**: `SYNAPSE_AUTH_TOKEN` with your token

**For memory (Node.js example):**
- **Command**: `node`
- **Args**: `["/path/to/mcp-server/memory/build/index.js"]`
- **Environment**: Server-specific env vars

**For compiled servers (Go/Rust example):**
- **Command**: `"/path/to/mcp-server/server-name/bin/executable"`
- **Args**: `[]` (or server-specific args)
- **Environment**: Server-specific env vars

### Verify Installation

Test each server directly:

**nfty:**
```bash
export SYNAPSE_AUTH_TOKEN="your-token"
python nfty/mcp_server.py
```

The server will start and wait for MCP protocol messages. Press Ctrl+C to stop.

**Other servers:** See each server's README for specific testing instructions.

## Usage

Once configured, your AI assistant can access the nifty tools provided by each enabled server.

See each server's documentation for specific capabilities and usage examples:
- [nfty documentation](nfty/README.md)
- [memory documentation](memory/README.md) (when available)

## Development

### Running Tests

#### Tests

- See tests within server-specific directory
- AI agent tests:

```bash
# Requires goose
export SYNAPSE_AUTH_TOKEN=$SYNAPSE_AUTH_TOKEN
goose run --recipe tests/curator_tester.yaml
```

### Adding New Tools

#### nfty

1. Add tool definition to `list_tools()` in `mcp_server.py`
2. Implement the async handler function
3. Add handler to `call_tool()` dispatcher
4. Update documentation in `TOOLS.md`
5. Update test prompt in `tests/curator_tester.yaml`
