#!/usr/bin/env python3
"""
NF Curator MCP Server

Unified MCP server providing tools for both:
- Portal metadata generation and submission
- Project review and dataset classification

Tools are exposed selectively to different recipes via available_tools configuration.
"""

import json
import sys
import logging
import math
from typing import Optional, Dict, List, Any
from pathlib import Path

import pandas as pd
import numpy as np
import synapseclient
from synapseclient.core.exceptions import SynapseHTTPError
import requests
import jsonschema
from jsonschema import Draft7Validator
import yaml
from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.types import Tool, TextContent
import os

# Configure logging to stderr (MCP uses stdout for protocol messages)
# Force remove any existing handlers and reconfigure
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Create stderr handler explicitly
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logging.root.addHandler(stderr_handler)
logging.root.setLevel(logging.INFO)

# CRITICAL: Disable synapseclient logging completely to prevent stdout pollution
# synapseclient has its own logging that can write to stdout even with silent=True
synapse_logger = logging.getLogger('synapseclient')
synapse_logger.handlers = []
synapse_logger.addHandler(logging.NullHandler())  # Discard all synapseclient logs
synapse_logger.setLevel(logging.CRITICAL)  # Only critical errors
synapse_logger.propagate = False  # Don't propagate to root logger

# Configure other noisy loggers to use stderr
for logger_name in ['httpx', 'urllib3', 'requests']:
    noisy_logger = logging.getLogger(logger_name)
    noisy_logger.handlers = []
    noisy_logger.addHandler(stderr_handler)
    noisy_logger.setLevel(logging.WARNING)
    noisy_logger.propagate = False

logger = logging.getLogger(__name__)

# Initialize Synapse client
syn = None

# ---------------------------------------------------------------------------
# OpenAPI Spec Loading (optional, enabled via OPENAPI_SPEC_URI env var)
# ---------------------------------------------------------------------------

_openapi_spec: Optional[dict] = None
_openapi_spec_uri: Optional[str] = None


def load_openapi_spec(uri: str) -> dict:
    """Load an OpenAPI spec from a file path or URL.

    Args:
        uri: Either a local file path or HTTP(S) URL to the OpenAPI spec

    Returns:
        Parsed OpenAPI spec as a dictionary
    """
    if uri.startswith(('http://', 'https://')):
        response = requests.get(uri, timeout=30)
        response.raise_for_status()
        content = response.text
        # Determine format from content-type or URL
        if uri.endswith(('.yaml', '.yml')) or 'yaml' in response.headers.get('content-type', ''):
            return yaml.safe_load(content)
        return json.loads(content)
    else:
        # Local file path
        path = Path(uri)
        content = path.read_text()
        if path.suffix in ('.yaml', '.yml'):
            return yaml.safe_load(content)
        return json.loads(content)


def get_openapi_schemas() -> dict:
    """Get all schemas from the loaded OpenAPI spec."""
    if _openapi_spec is None:
        return {}
    components = _openapi_spec.get("components", {})
    return components.get("schemas", {})


def validate_against_openapi_schema(payload: dict, schema_name: str) -> dict:
    """Validate a payload against a named schema from the OpenAPI spec."""
    schemas = get_openapi_schemas()

    if schema_name not in schemas:
        return {
            "valid": False,
            "error": f"Schema '{schema_name}' not found. Available: {list(schemas.keys())}",
        }

    schema = schemas[schema_name]

    # Create a resolver that understands OpenAPI-style refs
    # Wrap schemas in a JSON Schema compatible structure
    full_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "definitions": schemas,
        **schema,
    }

    # Rewrite $ref paths from #/components/schemas/X to #/definitions/X
    full_schema_str = json.dumps(full_schema)
    full_schema_str = full_schema_str.replace(
        "#/components/schemas/", "#/definitions/"
    )
    full_schema = json.loads(full_schema_str)

    validator = Draft7Validator(full_schema)
    errors = list(validator.iter_errors(payload))

    if not errors:
        return {"valid": True, "errors": []}

    return {
        "valid": False,
        "errors": [
            {
                "path": "/" + "/".join(str(p) for p in e.absolute_path),
                "message": e.message,
                "schema_path": "/" + "/".join(str(p) for p in e.schema_path),
            }
            for e in errors
        ],
    }


def _init_openapi_spec():
    """Initialize OpenAPI spec from environment variable if set."""
    global _openapi_spec, _openapi_spec_uri

    uri = os.environ.get('OPENAPI_SPEC_URI')
    if not uri:
        return

    try:
        logger.info(f"Loading OpenAPI spec from: {uri}")
        _openapi_spec_uri = uri
        _openapi_spec = load_openapi_spec(uri)
        schemas = get_openapi_schemas()
        logger.info(f"Loaded OpenAPI spec with {len(schemas)} schemas")
    except Exception as e:
        logger.error(f"Failed to load OpenAPI spec from {uri}: {e}")
        _openapi_spec = None
        _openapi_spec_uri = None


class RedirectStdout:
    """Context manager to redirect stdout to stderr

    The MCP protocol uses stdout for JSON-RPC messages, so any library
    that writes to stdout will corrupt the protocol stream. This redirects
    stdout to stderr temporarily during operations.
    """
    def __enter__(self):
        self.old_stdout = sys.stdout
        sys.stdout = sys.stderr
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.old_stdout
        return False


def get_synapse_client():
    """Get or create Synapse client using SYNAPSE_AUTH_TOKEN environment variable

    Requires: SYNAPSE_AUTH_TOKEN environment variable to be set
    """
    global syn
    if syn is None:
        auth_token = os.environ.get('SYNAPSE_AUTH_TOKEN')
        if not auth_token:
            raise ValueError(
                "SYNAPSE_AUTH_TOKEN environment variable not set. "
                "Get your token from https://www.synapse.org/ -> Account Settings -> Personal Access Tokens"
            )

        logger.info("Authenticating with Synapse using SYNAPSE_AUTH_TOKEN")

        # Redirect stdout to prevent synapseclient from corrupting MCP protocol
        with RedirectStdout():
            # Create Synapse client with all output suppression flags
            syn = synapseclient.Synapse(
                silent=True,           # Suppress messages
                skip_checks=True,      # Skip version and endpoint checks
                debug=False            # Disable debug output
            )
            syn.login(authToken=auth_token, silent=True)

    return syn


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def get_study_fileview_id(entity_or_id: Any, syn_client: Optional[synapseclient.Synapse] = None) -> Optional[str]:
    """Return the study file view ID defined on the parent study annotations."""

    syn_client = syn_client or get_synapse_client()

    def _extract_value(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            for entry in value:
                if entry:
                    return str(entry)
            return None
        return str(value)

    if isinstance(entity_or_id, str):
        current_entity = syn_client.get(entity_or_id, downloadFile=False)
    else:
        current_entity = entity_or_id

    visited: set[str] = set()

    while current_entity is not None:
        try:
            annotations = syn_client.get_annotations(current_entity)
        except SynapseHTTPError as annotation_error:
            logger.warning(
                "Unable to load annotations for %s: %s",
                getattr(current_entity, "id", entity_or_id),
                annotation_error,
            )
            annotations = {}

        fileview_value = annotations.get("studyFileviewId")
        fileview_id = _extract_value(fileview_value)
        if fileview_id:
            return fileview_id

        parent_id = getattr(current_entity, "parentId", None)
        if not parent_id or parent_id in visited:
            break
        visited.add(parent_id)
        current_entity = syn_client.get(parent_id, downloadFile=False)

    return None


# Create MCP server
server = Server("nf-curator")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools"""
    tools = [
        # Portal Metadata Tools
        Tool(
            name="synapse_query",
            description="Execute SQL query against a Synapse table to extract metadata",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "Synapse table ID (e.g., syn12345678)"
                    },
                    "query": {
                        "type": "string",
                        "description": "SQL query string (use <table_id> as placeholder)"
                    }
                },
                "required": ["table_id", "query"]
            }
        ),
        Tool(
            name="fetch_schema",
            description="Fetch a JSON schema from the metadata dictionary and optionally save to file",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema_name": {
                        "type": "string",
                        "description": "Schema name (e.g., 'PortalDataset', 'PortalPublication')",
                        "default": "PortalDataset"
                    },
                    "schema_url": {
                        "type": "string",
                        "description": "Optional: Full URL to schema (overrides schema_name)"
                    },
                    "save_to_file": {
                        "type": "string",
                        "description": "Optional: File path to save schema (e.g., 'PortalDataset.json')"
                    }
                }
            }
        ),
        Tool(
            name="validate_metadata",
            description="Validate JSON metadata against a saved schema file",
            inputSchema={
                "type": "object",
                "properties": {
                    "metadata": {
                        "type": "object",
                        "description": "JSON metadata object to validate"
                    },
                    "schema_file": {
                        "type": "string",
                        "description": "Path to saved schema file (e.g., 'PortalDataset.json')"
                    }
                },
                "required": ["metadata", "schema_file"]
            }
        ),
        Tool(
            name="create_dataset",
            description="Create a Dataset entity from a Folder (enables SQL queries over files)",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "string",
                        "description": "Synapse folder ID to convert to dataset"
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional: Name for the dataset (defaults to folder name + ' Dataset')"
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "Optional: Parent project/folder ID (defaults to folder's parent)"
                    }
                },
                "required": ["folder_id"]
            }
        ),
        Tool(
            name="submit_metadata",
            description="Submit validated metadata by adding annotations to any Synapse entity (dataset, file, folder, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Synapse entity ID (e.g., syn12345678)"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Validated JSON metadata to submit as annotations"
                    }
                },
                "required": ["entity_id", "metadata"]
            }
        ),

        # Project Review Tools
        Tool(
            name="get_data_classes",
            description="Fetch available data class templates from metadata dictionary",
            inputSchema={
                "type": "object",
                "properties": {
                    "templates_url": {
                        "type": "string",
                        "description": "URL to Data.yaml templates",
                        "default": "https://raw.githubusercontent.com/nf-osi/nf-metadata-dictionary/refs/heads/main/modules/Template/Data.yaml"
                    }
                }
            }
        ),
        Tool(
            name="get_project_children",
            description="Get immediate children (folders/files) of a Synapse container",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Synapse project or folder ID"
                    },
                    "include_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by entity types (folder, file, table, etc.)",
                        "default": ["folder", "file"]
                    }
                },
                "required": ["entity_id"]
            }
        ),
        Tool(
            name="get_entity_info",
            description="Get detailed information about a Synapse entity including annotations",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Synapse entity ID"
                    },
                    "include_annotations": {
                        "type": "boolean",
                        "description": "Include entity annotations",
                        "default": True
                    }
                },
                "required": ["entity_id"]
            }
        ),
        Tool(
            name="walk_project_tree",
            description="Recursively walk through project structure to find all folders",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Synapse project ID"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth to traverse",
                        "default": 5
                    }
                },
                "required": ["project_id"]
            }
        ),
        Tool(
            name="count_folder_contents",
            description="Count files and subfolders in a folder",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "string",
                        "description": "Synapse folder ID"
                    }
                },
                "required": ["folder_id"]
            }
        ),

        # Shared Tools
        Tool(
            name="get_data_sharing_plan",
            description="Retrieve Data Sharing Plan for a study",
            inputSchema={
                "type": "object",
                "properties": {
                    "study_id": {
                        "type": "string",
                        "description": "Synapse study/project ID (e.g., syn12345678)"
                    }
                },
                "required": ["study_id"]
            }
        )
    ]

    # Conditionally add OpenAPI validation tools if spec is loaded
    if _openapi_spec is not None:
        tools.extend([
            Tool(
                name="openapi_list_schemas",
                description="List all available schemas in the loaded OpenAPI spec",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
            Tool(
                name="openapi_validate",
                description="Validate JSON payload(s) against a schema from the OpenAPI spec. Accepts a single object or an array of objects for batch validation.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "schema_name": {
                            "type": "string",
                            "description": "Name of the schema from #/components/schemas"
                        },
                        "payload": {
                            "description": "A single JSON object or an array of JSON objects to validate"
                        }
                    },
                    "required": ["schema_name", "payload"]
                }
            ),
            Tool(
                name="openapi_get_schema",
                description="Get the full schema definition for a named schema from the OpenAPI spec",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "schema_name": {
                            "type": "string",
                            "description": "Name of the schema from #/components/schemas"
                        }
                    },
                    "required": ["schema_name"]
                }
            )
        ])

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls"""

    try:
        logger.info(f"Calling tool: {name} with arguments: {arguments}")

        # Portal metadata tools
        if name == "synapse_query":
            result = await synapse_query(arguments)
        elif name == "fetch_schema":
            result = await fetch_schema(arguments)
        elif name == "validate_metadata":
            result = await validate_metadata(arguments)
        elif name == "create_dataset":
            result = await create_dataset(arguments)
        elif name == "submit_metadata":
            result = await submit_metadata(arguments)

        # Project review tools
        elif name == "get_data_classes":
            result = await get_data_classes(arguments)
        elif name == "get_project_children":
            result = await get_project_children(arguments)
        elif name == "get_entity_info":
            result = await get_entity_info(arguments)
        elif name == "walk_project_tree":
            result = await walk_project_tree(arguments)
        elif name == "count_folder_contents":
            result = await count_folder_contents(arguments)

        # Shared tools
        elif name == "get_data_sharing_plan":
            result = await get_data_sharing_plan(arguments)

        # OpenAPI validation tools
        elif name == "openapi_list_schemas":
            result = await openapi_list_schemas(arguments)
        elif name == "openapi_validate":
            result = await openapi_validate(arguments)
        elif name == "openapi_get_schema":
            result = await openapi_get_schema(arguments)
        else:
            result = [TextContent(type="text", text=f"Unknown tool: {name}")]

        logger.info(f"Tool {name} completed successfully")
        return result

    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}", exc_info=True)
        return [TextContent(type="text", text=f"Error in {name}: {str(e)}")]


# ============================================================================
# PORTAL METADATA TOOLS
# ============================================================================

async def synapse_query(args: dict) -> list[TextContent]:
    """Execute Synapse SQL query"""
    try:
        table_id = args["table_id"]
        query = args["query"].replace("<table_id>", table_id)

        # Validate SELECT * queries to prevent returning too much data
        import re
        max_rows_without_limit = 1000  # Maximum rows allowed for SELECT * without LIMIT

        has_select_star = re.search(r'\bSELECT\s+\*\s+FROM\b', query, re.IGNORECASE)
        has_limit = re.search(r'\bLIMIT\s+\d+', query, re.IGNORECASE)
        has_where = re.search(r'\bWHERE\b', query, re.IGNORECASE)

        if has_select_star and not has_limit:
            # SELECT * without LIMIT is allowed if there's a WHERE clause
            # We'll check the result size after execution
            if not has_where:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "SELECT * queries require a LIMIT clause or WHERE filter",
                        "message": "Please add a LIMIT clause (e.g., LIMIT 100), a WHERE filter, or specify explicit column names",
                        "reason": "SELECT * without LIMIT or WHERE can return excessive data and cause performance issues"
                    }, indent=2)
                )]

        syn_client = get_synapse_client()
        logger.info(f"Executing query: {query}")

        # Redirect stdout during query execution to prevent output corruption
        with RedirectStdout():
            results = syn_client.tableQuery(query)
            df = results.asDataFrame()

        row_count = len(df)
        logger.info(f"Query returned {row_count} rows with columns: {df.columns.tolist()}")

        # Check if result set is too large for SELECT * without LIMIT
        if has_select_star and not has_limit and row_count > max_rows_without_limit:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "Query returned too many rows",
                    "row_count": row_count,
                    "max_allowed": max_rows_without_limit,
                    "message": f"Your WHERE filter returned {row_count} rows, which exceeds the maximum of {max_rows_without_limit} rows for SELECT * queries without LIMIT.",
                    "suggestion": f"Please add a LIMIT clause (e.g., LIMIT {max_rows_without_limit}) or make your WHERE filter more selective to reduce the result set.",
                    "query": query
                }, indent=2)
            )]

        # Convert DataFrame to records, handling Synapse-specific types
        records = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                value = row[col]
                # Handle different value types safely
                try:
                    # Check for None/NaN first (works for scalars and arrays)
                    if value is None:
                        record[col] = None
                    # Handle list/array types (common in Synapse tables)
                    elif isinstance(value, (list, tuple)):
                        record[col] = list(value)
                    elif isinstance(value, dict):
                        record[col] = value
                    # Handle numpy arrays
                    elif isinstance(value, np.ndarray):
                        record[col] = value.tolist()
                    # Handle pandas NA types
                    elif pd.isna(value):
                        record[col] = None
                    # Handle numeric types
                    elif isinstance(value, (np.integer, np.floating)):
                        # Check for NaN/inf in numeric scalars only
                        if np.isnan(value) or np.isinf(value):
                            record[col] = None
                        else:
                            record[col] = value.item()
                    # Handle boolean types
                    elif isinstance(value, (np.bool_, bool)):
                        record[col] = bool(value)
                    # Handle strings and other types
                    else:
                        record[col] = value
                except Exception as conv_error:
                    # If conversion fails, log and use string representation
                    logger.warning(f"Failed to convert column '{col}' value: {conv_error}")
                    record[col] = str(value) if value is not None else None
            records.append(record)

        # Convert to JSON-serializable format
        result_data = {
            "row_count": len(df),
            "columns": df.columns.tolist(),
            "data": records
        }

        # Ensure all values are JSON serializable
        json_text = json.dumps(result_data, indent=2, default=str)
        logger.info(f"Successfully serialized query results to JSON ({len(json_text)} bytes)")

        return [TextContent(
            type="text",
            text=json_text
        )]

    except SynapseHTTPError as e:
        logger.error(f"Synapse HTTP error: {str(e)}")
        error_detail = str(e)

        # Provide helpful context for column errors
        if "Unknown column" in error_detail or "no such column" in error_detail.lower():
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "Column not found",
                    "message": error_detail,
                    "suggestion": "Query 'SELECT * FROM <table_id> LIMIT 1' to see available columns"
                }, indent=2)
            )]

        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Synapse query failed",
                "message": error_detail
            }, indent=2)
        )]
    except json.JSONDecodeError as e:
        logger.error(f"JSON encoding error: {str(e)}", exc_info=True)
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "JSON encoding failed",
                "message": str(e)
            }, indent=2)
        )]
    except Exception as e:
        logger.error(f"Query execution error: {str(e)}", exc_info=True)
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Query execution error",
                "message": str(e)
            }, indent=2)
        )]


async def fetch_schema(args: dict) -> list[TextContent]:
    """Fetch schema from metadata dictionary and optionally save to file"""
    # Allow explicit URL override, otherwise construct from schema name
    if "schema_url" in args and args["schema_url"]:
        schema_url = args["schema_url"]
    else:
        schema_name = args.get("schema_name", "PortalDataset")
        base_url = "https://raw.githubusercontent.com/nf-osi/nf-metadata-dictionary/refs/heads/main/registered-json-schemas"
        schema_url = f"{base_url}/{schema_name}.json"

    try:
        logger.info(f"Fetching schema from: {schema_url}")
        response = requests.get(schema_url, timeout=10)
        response.raise_for_status()
        schema = response.json()

        # Optionally save to file
        save_to_file = args.get("save_to_file")
        if save_to_file:
            try:
                with open(save_to_file, 'w') as f:
                    json.dump(schema, f, indent=2)
                logger.info(f"Schema saved to {save_to_file}")
                message = f"Schema fetched and saved to {save_to_file}"
            except IOError as e:
                logger.error(f"Failed to save schema to file: {str(e)}")
                message = f"Schema fetched but failed to save to file: {str(e)}"
        else:
            message = "Schema fetched successfully"

        result = {
            "message": message,
            "schema": schema
        }

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except requests.RequestException as e:
        return [TextContent(
            type="text",
            text=f"Failed to fetch schema from {schema_url}: {str(e)}"
        )]


async def validate_metadata(args: dict) -> list[TextContent]:
    """Validate metadata against schema"""
    metadata = args["metadata"]
    schema_file = args["schema_file"]

    # Load schema from file
    try:
        logger.info(f"Loading schema from file: {schema_file}")
        with open(schema_file, 'r') as f:
            schema = json.load(f)
    except FileNotFoundError:
        return [TextContent(
            type="text",
            text=json.dumps({
                "valid": False,
                "errors": [{"message": f"Schema file not found: {schema_file}"}]
            }, indent=2)
        )]
    except json.JSONDecodeError as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "valid": False,
                "errors": [{"message": f"Invalid JSON in schema file: {str(e)}"}]
            }, indent=2)
        )]

    try:
        jsonschema.validate(instance=metadata, schema=schema)

        # Calculate completeness
        total_fields = len(schema.get("properties", {}))
        filled_fields = len([k for k in metadata.keys() if metadata[k] is not None])
        completeness = filled_fields / total_fields if total_fields > 0 else 0

        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "completeness": round(completeness, 2),
            "filled_fields": filled_fields,
            "total_fields": total_fields
        }

        # Check required fields
        required = schema.get("required", [])
        missing_required = [field for field in required if field not in metadata or metadata[field] is None]
        if missing_required:
            result["warnings"].append(f"Missing required fields: {', '.join(missing_required)}")

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except jsonschema.ValidationError as e:
        result = {
            "valid": False,
            "errors": [
                {
                    "message": e.message,
                    "path": list(e.path),
                    "schema_path": list(e.schema_path)
                }
            ]
        }
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]


async def create_dataset(args: dict) -> list[TextContent]:
    """Create a Dataset entity from a Folder"""
    from synapseclient import Dataset

    folder_id = args["folder_id"]

    try:
        syn_client = get_synapse_client()

        # Get the folder entity
        folder = syn_client.get(folder_id, downloadFile=False)

        # Determine dataset name and parent
        dataset_name = args.get("name", f"{folder.name} Dataset")
        parent_id = args.get("parent_id", folder.parentId)

        logger.info(f"Creating dataset '{dataset_name}' from folder {folder_id}")

        def safe_int(value: Any) -> Optional[int]:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                if isinstance(value, float) and math.isnan(value):
                    return None
                return int(value)
            value_str = str(value).strip()
            if not value_str:
                return None
            try:
                return int(value_str)
            except ValueError:
                try:
                    return int(float(value_str))
                except (TypeError, ValueError):
                    return None

        def gather_folder_ids(container_id: str, bucket: Optional[List[str]] = None) -> List[str]:
            if bucket is None:
                bucket = []
            bucket.append(container_id)
            for child in syn_client.getChildren(container_id, includeTypes=["folder"]):
                gather_folder_ids(child["id"], bucket)
            return bucket

        def collect_via_view(view_id: str) -> List[Dict[str, Any]]:
            folder_ids = gather_folder_ids(folder_id)
            dataset_map: Dict[str, Dict[str, Any]] = {}
            batch_size = 200

            for i in range(0, len(folder_ids), batch_size):
                batch = folder_ids[i:i + batch_size]
                folder_filter = ", ".join(f"'{fid}'" for fid in batch)
                sql = (
                    f"select id, currentVersion from {view_id} "
                    f"where parentId in ({folder_filter})"
                )

                query_result = syn_client.tableQuery(sql)
                rowset = query_result.asRowSet()
                header_index = {header.name: idx for idx, header in enumerate(rowset.headers)}
                id_idx = header_index.get("id") or header_index.get("entityId")
                version_idx = header_index.get("currentVersion") or header_index.get("versionNumber")

                if id_idx is None or version_idx is None:
                    raise ValueError(
                        f"File view {view_id} must include 'id' and 'currentVersion' columns"
                    )

                for row in rowset.rows:
                    values = row.values
                    entity_id = values[id_idx]
                    if not entity_id:
                        continue
                    version_number = safe_int(values[version_idx])
                    if version_number is None:
                        raise ValueError(
                            f"Missing version number for file {entity_id} in view {view_id}"
                        )
                    dataset_map[str(entity_id)] = {
                        "entityId": str(entity_id),
                        "versionNumber": version_number,
                    }

            return list(dataset_map.values())

        def collect_by_traversal(container_id: str) -> List[Dict[str, Any]]:
            items: List[Dict[str, Any]] = []

            def _walk(current_id: str) -> None:
                for child in syn_client.getChildren(current_id, includeTypes=["folder", "file"]):
                    child_type = (child.get("type") or "").lower()
                    if child_type.endswith("fileentity") or child_type == "file":
                        version_number = child.get("versionNumber")
                        if version_number is None:
                            try:
                                file_entity = syn_client.get(child["id"], downloadFile=False)
                                version_number = getattr(file_entity, "versionNumber", None)
                            except Exception as version_err:
                                logger.warning(
                                    "Unable to fetch version for %s: %s",
                                    child["id"],
                                    version_err,
                                )

                        if version_number is None:
                            raise ValueError(
                                f"Could not determine version number for file {child['id']}"
                            )

                        items.append(
                            {
                                "entityId": child["id"],
                                "versionNumber": int(version_number),
                            }
                        )
                    elif child_type.endswith("folder"):
                        _walk(child["id"])

            _walk(container_id)
            return items

        dataset_items: List[Dict[str, Any]] = []

        try:
            study_fileview_id = get_study_fileview_id(folder, syn_client)
        except Exception as fileview_error:
            logger.warning(
                "Unable to locate study file view for %s: %s",
                folder_id,
                fileview_error,
            )
            study_fileview_id = None

        if study_fileview_id:
            logger.info(
                f"Collecting file IDs for {folder_id} using study file view {study_fileview_id}"
            )
            try:
                dataset_items = collect_via_view(study_fileview_id)
            except Exception as view_error:
                logger.warning(
                    "Failed to use file view %s for %s: %s. Falling back to traversal.",
                    study_fileview_id,
                    folder_id,
                    view_error,
                )
                dataset_items = []

        if not dataset_items:
            dataset_items = collect_by_traversal(folder_id)

        if not dataset_items:
            logger.error(f"No files found in folder {folder_id} or any of its subfolders")
            result = {
                "status": "failed",
                "folder_id": folder_id,
                "error": "No files located",
                "message": "Folder and subfolders do not contain any files to include in the dataset"
            }
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]

        # Create the Dataset entity
        dataset = Dataset(
            name=dataset_name,
            parent=parent_id,
            dataset_items=dataset_items,
            description=f"Dataset created from folder {folder_id}"
        )

        # Store the dataset
        dataset = syn_client.store(dataset)

        result = {
            "status": "success",
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "source_folder": folder_id,
            "item_count": len(dataset_items),
            "message": f"Successfully created dataset {dataset.id} with {len(dataset_items)} files"
        }

        logger.info(f"✓ Created dataset {dataset.id} from folder {folder_id}")

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except SynapseHTTPError as e:
        logger.error(f"Failed to create dataset: {str(e)}")
        result = {
            "status": "failed",
            "folder_id": folder_id,
            "error": str(e),
            "message": "Failed to create dataset from folder"
        }
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]
    except Exception as e:
        logger.error(f"Unexpected error creating dataset: {str(e)}")
        result = {
            "status": "failed",
            "folder_id": folder_id,
            "error": str(e),
            "message": "Unexpected error during dataset creation"
        }
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]


async def submit_metadata(args: dict) -> list[TextContent]:
    """Submit metadata by adding annotations to any Synapse entity"""
    entity_id = args["entity_id"]
    metadata = args["metadata"]

    logger.info(f"Submitting metadata for {entity_id} as Synapse annotations")

    try:
        syn_client = get_synapse_client()

        # Get the entity (works for any type: dataset, file, folder, project, etc.)
        entity = syn_client.get(entity_id, downloadFile=False)
        entity_type = entity.__class__.__name__

        # Convert metadata to annotations
        # Synapse annotations support strings, integers, floats, and lists
        annotations_obj = syn_client.get_annotations(entity)
        annotations: Dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue

            if isinstance(value, (list, tuple)):
                annotations_value = list(value)
            elif isinstance(value, (int, float, str, bool)):
                annotations_value = value
            else:
                annotations_value = json.dumps(value)

            annotations_obj[key] = annotations_value
            annotations[key] = annotations_value

        # Update entity annotations and persist changes
        updated_annotations = syn_client.set_annotations(annotations_obj)

        result = {
            "status": "success",
            "entity_id": entity_id,
            "entity_type": entity_type,
            "message": f"Successfully added {len(annotations)} annotations to {entity_type} {entity_id}",
            "annotations_added": list(annotations.keys()),
            "annotation_count": len(annotations)
        }

        logger.info(f"✓ Submitted {len(annotations)} annotations to {entity_type} {entity_id}")

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except SynapseHTTPError as e:
        logger.error(f"Failed to submit metadata: {str(e)}")
        result = {
            "status": "failed",
            "entity_id": entity_id,
            "error": str(e),
            "message": "Failed to add annotations to Synapse entity"
        }
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]
    except Exception as e:
        logger.error(f"Unexpected error during submission: {str(e)}")
        result = {
            "status": "failed",
            "entity_id": entity_id,
            "error": str(e),
            "message": "Unexpected error during metadata submission"
        }
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]


# ============================================================================
# PROJECT REVIEW TOOLS
# ============================================================================

async def get_data_classes(args: dict) -> list[TextContent]:
    """Fetch data class templates"""
    templates_url = args.get(
        "templates_url",
        "https://raw.githubusercontent.com/nf-osi/nf-metadata-dictionary/refs/heads/main/modules/Template/Data.yaml"
    )

    try:
        response = requests.get(templates_url, timeout=10)
        response.raise_for_status()

        return [TextContent(
            type="text",
            text=response.text
        )]

    except requests.RequestException as e:
        return [TextContent(
            type="text",
            text=f"Failed to fetch data classes: {str(e)}"
        )]


async def get_project_children(args: dict) -> list[TextContent]:
    """Get immediate children of a container"""
    entity_id = args["entity_id"]
    include_types = args.get("include_types", ["folder", "file"])

    try:
        syn_client = get_synapse_client()

        children = list(syn_client.getChildren(entity_id, includeTypes=include_types))

        result = {
            "entity_id": entity_id,
            "child_count": len(children),
            "children": [
                {
                    "id": child["id"],
                    "name": child["name"],
                    "type": child["type"]
                }
                for child in children
            ]
        }

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except SynapseHTTPError as e:
        return [TextContent(
            type="text",
            text=f"Failed to get children: {str(e)}"
        )]


async def get_entity_info(args: dict) -> list[TextContent]:
    """Get detailed entity information"""
    entity_id = args["entity_id"]
    include_annotations = args.get("include_annotations", True)

    try:
        syn_client = get_synapse_client()
        entity = syn_client.get(entity_id, downloadFile=False)

        info = {
            "id": entity.id,
            "name": entity.name,
            "type": entity.__class__.__name__,
            "createdOn": str(entity.createdOn) if hasattr(entity, 'createdOn') else None,
            "modifiedOn": str(entity.modifiedOn) if hasattr(entity, 'modifiedOn') else None,
            "createdBy": entity.createdBy if hasattr(entity, 'createdBy') else None,
            "modifiedBy": entity.modifiedBy if hasattr(entity, 'modifiedBy') else None
        }

        if include_annotations:
            try:
                annotations = syn_client.get_annotations(entity)
                info["annotations"] = annotations
            except SynapseHTTPError as annotation_error:
                logger.warning(
                    "Unable to load annotations for %s: %s",
                    entity_id,
                    annotation_error,
                )
                info["annotations_error"] = str(annotation_error)

        return [TextContent(
            type="text",
            text=json.dumps(info, indent=2, default=str)
        )]

    except SynapseHTTPError as e:
        return [TextContent(
            type="text",
            text=f"Failed to get entity info: {str(e)}"
        )]


async def walk_project_tree(args: dict) -> list[TextContent]:
    """Recursively walk project structure"""
    project_id = args["project_id"]
    max_depth = args.get("max_depth", 5)

    try:
        syn_client = get_synapse_client()

        def walk_folder(folder_id, depth=0, path=""):
            if depth > max_depth:
                return []

            folders = []
            for child in syn_client.getChildren(folder_id, includeTypes=["folder"]):
                child_path = f"{path}/{child['name']}" if path else child['name']
                folders.append({
                    "id": child["id"],
                    "name": child["name"],
                    "path": child_path,
                    "depth": depth
                })
                # Recursively get subfolders
                folders.extend(walk_folder(child["id"], depth + 1, child_path))

            return folders

        all_folders = walk_folder(project_id)

        result = {
            "project_id": project_id,
            "total_folders": len(all_folders),
            "folders": all_folders
        }

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except SynapseHTTPError as e:
        return [TextContent(
            type="text",
            text=f"Failed to walk project tree: {str(e)}"
        )]


async def count_folder_contents(args: dict) -> list[TextContent]:
    """Count contents of a folder"""
    folder_id = args["folder_id"]

    try:
        syn_client = get_synapse_client()

        files = list(syn_client.getChildren(folder_id, includeTypes=["file"]))
        folders = list(syn_client.getChildren(folder_id, includeTypes=["folder"]))

        result = {
            "folder_id": folder_id,
            "file_count": len(files),
            "folder_count": len(folders),
            "has_data": len(files) > 0
        }

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    except SynapseHTTPError as e:
        return [TextContent(
            type="text",
            text=f"Failed to count folder contents: {str(e)}"
        )]


# ============================================================================
# FREQUENTLY SHARED TOOLS
# ============================================================================

async def get_data_sharing_plan(args: dict) -> list[TextContent]:
    """Retrieve Data Sharing Plan"""
    study_id = args["study_id"]
    url = f"https://dsp.nf.synapse.org/api/dsp/json/{study_id}"

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            dsp = response.json()
            return [TextContent(
                type="text",
                text=json.dumps(dsp, indent=2)
            )]
        elif response.status_code == 404:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "No DSP found for this study", "study_id": study_id}, indent=2)
            )]
        else:
            return [TextContent(
                type="text",
                text=f"Failed to retrieve DSP: HTTP {response.status_code}"
            )]

    except requests.RequestException as e:
        return [TextContent(
            type="text",
            text=f"Error retrieving DSP: {str(e)}"
        )]


# ============================================================================
# OPENAPI VALIDATION TOOLS
# ============================================================================

async def openapi_list_schemas(args: dict) -> list[TextContent]:
    """List all available schemas in the loaded OpenAPI spec."""
    schemas = get_openapi_schemas()
    result = {
        "spec_uri": _openapi_spec_uri,
        "schemas": list(schemas.keys()),
        "count": len(schemas),
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def openapi_validate(args: dict) -> list[TextContent]:
    """Validate JSON payload(s) against a schema from the OpenAPI spec.

    Accepts either a single object or an array of objects for batch validation.
    """
    schema_name = args.get("schema_name")
    payload = args.get("payload")

    if not schema_name:
        return [TextContent(
            type="text",
            text=json.dumps({"error": "schema_name is required"})
        )]
    if payload is None:
        return [TextContent(
            type="text",
            text=json.dumps({"error": "payload is required"})
        )]

    # Handle batch validation if payload is an array
    if isinstance(payload, list):
        results = []
        all_valid = True
        for i, item in enumerate(payload):
            item_result = validate_against_openapi_schema(item, schema_name)
            item_result["index"] = i
            results.append(item_result)
            if not item_result.get("valid", False):
                all_valid = False

        result = {
            "batch": True,
            "count": len(payload),
            "all_valid": all_valid,
            "valid_count": sum(1 for r in results if r.get("valid", False)),
            "invalid_count": sum(1 for r in results if not r.get("valid", False)),
            "results": results
        }
    else:
        result = validate_against_openapi_schema(payload, schema_name)

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def openapi_get_schema(args: dict) -> list[TextContent]:
    """Get the full schema definition for a named schema."""
    schema_name = args.get("schema_name")
    schemas = get_openapi_schemas()

    if not schema_name:
        return [TextContent(
            type="text",
            text=json.dumps({"error": "schema_name is required"})
        )]

    if schema_name not in schemas:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": f"Schema '{schema_name}' not found",
                "available": list(schemas.keys())
            })
        )]

    return [TextContent(type="text", text=json.dumps(schemas[schema_name], indent=2))]


async def async_main():
    """Run the MCP server"""
    # Ensure logging goes to stderr before any server operations
    logger.info("Starting NF Curator MCP Server")

    # Initialize OpenAPI spec if OPENAPI_SPEC_URI is set
    _init_openapi_spec()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


def main():
    """Entry point for the nfty command"""
    import asyncio
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
