# nfty - Nifty MCP Server for NF Data Curation

Unified MCP (Model Context Protocol) server providing nifty tools for Synapse data curation workflows.

## Overview

This server provides tools for two main workflows:
- **Portal Metadata Generation** (recipe_release.yaml) - Tools for generating and submitting dataset metadata to the NF Portal
- **Project Review & Classification** (recipe.yaml) - Tools for reviewing Synapse projects and classifying datasets

Both workflows use the same MCP server but access different subsets of tools via the `available_tools` configuration in their respective recipes.

Built on `mcp>=2.2` (MCPServer, the FastMCP 2.0 rename) and the MCP 2026-07-28
spec's stateless server model: every tool's JSON Schema comes from its
function signature and docstring rather than hand-written definitions, and
the server holds no session state between calls, so it can run behind a
load balancer with no sticky sessions.

## Installation

### Using uvx (Recommended)

The recommended way to run this MCP server is using `uvx`, which handles dependencies automatically:

```bash
# From the mcp-server directory (parent of nfty):
uvx --from . nfty

# Or install in development mode
uv pip install -e .
```

### Using pip

From the `mcp-server` directory (parent of `nfty`):

```bash
pip install .
```

For development:
```bash
pip install -e .
```

## Environment Setup

### Required Environment Variables

**Synapse Authentication**, one of:
```bash
export SYNAPSE_AUTH_TOKEN="your-synapse-token"
```
or a `~/.synapseConfig` file with a personal access token — the server checks
both (via synapseclient's own credential chain, which also supports AWS SSM
Parameter Store). Get a token from: https://www.synapse.org/ → Account Settings → Personal Access Tokens

### Optional Environment Variables

**Transport** (defaults to `stdio`, for a local MCP client):
```bash
export MCP_TRANSPORT="streamable-http"  # or "stdio" (default)
export MCP_HOST="127.0.0.1"             # streamable-http only, default 127.0.0.1
export MCP_PORT="8000"                  # streamable-http only, default 8000
```
See [Transports](#transports) below.

## Available Tools

### Portal Metadata Tools (recipe_release.yaml)
- `synapse_query` - Execute SQL queries against dataset tables
- `fetch_schema` - Get JSON schemas from metadata dictionary (supports PortalDataset, PortalPublication, etc.)
- `validate_metadata` - Validate metadata against saved schema file
- `submit_metadata` - Submit validated metadata as Synapse annotations (works with any entity type)
- `get_data_sharing_plan` - Retrieve Data Sharing Plan
- `get_entity_info` - Get entity information including annotations

### Project Review Tools (recipe.yaml)
- `get_data_sharing_plan` - Retrieve Data Sharing Plan
- `get_data_classes` - Fetch data class templates
- `walk_project_tree` - Recursively explore project structure
- `get_entity_info` - Get entity information including annotations
- `get_project_children` - Get immediate children of a container
- `count_folder_contents` - Count files and folders

## Usage

The MCP server is automatically invoked by the Goose recipe system. Each recipe specifies which tools it needs:

**recipe.yaml** (Project Review):
```yaml
extensions:
- type: mcp
  name: nfty
  command: uvx
  args:
    - --from
    - .
    - nfty
  available_tools:
    - get_data_sharing_plan
    - get_data_classes
    - walk_project_tree
    - get_entity_info
    - get_project_children
    - count_folder_contents
```

**recipe_release.yaml** (Portal Metadata):
```yaml
extensions:
- type: mcp
  name: nfty
  command: uvx
  args:
    - --from
    - .
    - nfty
  available_tools:
    - synapse_query
    - fetch_schema
    - validate_metadata
    - get_data_sharing_plan
    - get_entity_info
    - submit_metadata
```

## Transports

**stdio** (default) is how the examples above and the Goose recipes run the
server: the client spawns `nfty` as a subprocess and speaks MCP over its
stdin/stdout.

**streamable-http** runs the server as an HTTP service instead, for clients
that connect over the network rather than spawning a subprocess:

```bash
export SYNAPSE_AUTH_TOKEN="your-synapse-token"
export MCP_TRANSPORT="streamable-http"
export MCP_PORT="8000"
nfty
# now listening on http://127.0.0.1:8000/mcp
```

It runs stateless (no session tracking between requests), consistent with
the 2026-07-28 spec's stateless server updates, so it's safe to run multiple
replicas behind a load balancer without sticky sessions.

## Architecture

The unified server provides domain-specific tools for Synapse data curation:
- Recipes specify only the tools they need via `available_tools` configuration
- The MCP protocol ensures agents can only call authorized tools
- Single codebase for easier maintenance
- Shared authentication and error handling

## Testing

Test the server manually from the `mcp-server` directory:

```bash
# Ensure SYNAPSE_AUTH_TOKEN is set
uvx --from . nfty

# Or if installed in development mode:
nfty
```

## Troubleshooting

**Synapse Authentication Error**:
- Ensure `SYNAPSE_AUTH_TOKEN` is set, or `~/.synapseConfig` has a valid token
- Verify token is valid at https://www.synapse.org/

**Import Errors**:
- If using uvx: Dependencies are automatically managed
- If using pip: Run `pip install .` or `pip install -e .`
- Ensure Python 3.10+ is installed

**Tool Not Found**:
- Check that the tool is listed in `available_tools` for your recipe
- Verify tool name matches exactly (case-sensitive)
