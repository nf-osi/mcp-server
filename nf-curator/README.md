# NF Curator MCP Server

Unified MCP (Model Context Protocol) server providing specialized tools for Synapse data curation workflows.

## Overview

This server provides tools for two main workflows:
- **Portal Metadata Generation** (recipe_release.yaml) - Tools for generating and submitting dataset metadata to the NF Portal
- **Project Review & Classification** (recipe.yaml) - Tools for reviewing Synapse projects and classifying datasets

Both workflows use the same MCP server but access different subsets of tools via the `available_tools` configuration in their respective recipes.

## Installation

### Using uvx (Recommended)

The recommended way to run this MCP server is using `uvx`, which handles dependencies automatically:

```bash
# From the mcp-server directory (parent of nf-curator):
uvx --from . nf-curator

# Or install in development mode
uv pip install -e .
```

### Using pip

From the `mcp-server` directory (parent of `nf-curator`):

```bash
pip install .
```

For development:
```bash
pip install -e .
```

## Environment Setup

### Required Environment Variables

**1. Synapse Authentication:**
```bash
export SYNAPSE_AUTH_TOKEN="your-synapse-token"
```
Get your token from: https://www.synapse.org/ → Account Settings → Personal Access Tokens

**2. GitHub Authentication (for issue management):**
```bash
export GITHUB_PERSONAL_ACCESS_TOKEN="your-github-token"
```
Create your token at: https://github.com/settings/personal-access-tokens/new

**Required token scopes:**
- `repo` – Repository operations
- `read:org` – Organization team access (if using org repositories)

### Docker Requirement

The GitHub MCP server runs via Docker. Ensure Docker is installed and running:
```bash
docker --version
```

Install Docker from: https://docs.docker.com/get-docker/

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

### GitHub Integration (Separate MCP Server)
GitHub issue management (creating issues, adding comments) is handled through the **official GitHub MCP server** running in Docker, not this NF curator server.

**Available GitHub Tools:**
- `issue_write` - Create or update issues
- `issue_read` - Get details of a specific issue
- `add_issue_comment` - Add comments to existing issues

**Configuration:** Both recipes automatically include the GitHub MCP server extension. No additional setup needed beyond setting the `GITHUB_PERSONAL_ACCESS_TOKEN` environment variable.

## Usage

The MCP server is automatically invoked by the Goose recipe system. Each recipe specifies which tools it needs:

**recipe.yaml** (Project Review):
```yaml
extensions:
- type: mcp
  name: nf-curator
  command: uvx
  args:
    - --from
    - .
    - nf-curator
  available_tools:
    - get_data_sharing_plan
    - get_data_classes
    - walk_project_tree
    - get_entity_info
    - get_project_children
    - count_folder_contents
- type: mcp
  name: github
  command: docker
  args:
    - run
    - -i
    - --rm
    - -e
    - GITHUB_PERSONAL_ACCESS_TOKEN
    - ghcr.io/github/github-mcp-server
  env:
    GITHUB_TOOLSETS: issues
  available_tools:
    - issue_write
    - issue_read
    - add_issue_comment
```

**recipe_release.yaml** (Portal Metadata):
```yaml
extensions:
- type: mcp
  name: nf-curator
  command: uvx
  args:
    - --from
    - .
    - nf-curator
  available_tools:
    - synapse_query
    - fetch_schema
    - validate_metadata
    - get_data_sharing_plan
    - get_entity_info
    - submit_metadata
- type: mcp
  name: github
  command: docker
  args:
    - run
    - -i
    - --rm
    - -e
    - GITHUB_PERSONAL_ACCESS_TOKEN
    - ghcr.io/github/github-mcp-server
  env:
    GITHUB_TOOLSETS: issues
  available_tools:
    - issue_write
    - issue_read
    - add_issue_comment
```

## Architecture

The unified server provides domain-specific tools for Synapse data curation:
- Recipes specify only the tools they need via `available_tools` configuration
- The MCP protocol ensures agents can only call authorized tools
- Single codebase for easier maintenance
- Shared authentication and error handling
- GitHub operations are handled by the official GitHub MCP server (configured separately)

## Testing

Test the server manually from the `mcp-server` directory:

```bash
# Ensure SYNAPSE_AUTH_TOKEN is set
uvx --from . nf-curator

# Or if installed in development mode:
nf-curator
```

## Troubleshooting

**Synapse Authentication Error**:
- Ensure `SYNAPSE_AUTH_TOKEN` environment variable is set
- Verify token is valid at https://www.synapse.org/

**GitHub MCP Server Issues**:
- Ensure `GITHUB_PERSONAL_ACCESS_TOKEN` environment variable is set
- Verify Docker is running: `docker ps`
- Test Docker access: `docker run --rm hello-world`
- Pull the latest image: `docker pull ghcr.io/github/github-mcp-server`
- Check token has required scopes: `repo`, `read:org`

**Import Errors**:
- If using uvx: Dependencies are automatically managed
- If using pip: Run `pip install .` or `pip install -e .`
- Ensure Python 3.10+ is installed

**Tool Not Found**:
- Check that the tool is listed in `available_tools` for your recipe
- Verify tool name matches exactly (case-sensitive)
- For GitHub tools: Ensure Docker container started successfully
