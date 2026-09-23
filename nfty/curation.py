#!/usr/bin/env python3
"""Curation tools: Synapse metadata generation, submission, and project review.

These register onto a server built elsewhere: nfty/__main__.py owns the
MCPServer instance and calls register_curation_tools(mcp) to add them. Tools
raise ToolError on failure rather than returning an error string, which
would be indistinguishable from a legitimate answer.

Every tool below is a plain `def`, not `async def`. They all call blocking
synapseclient/requests methods without awaiting anything, and MCPServer only
offloads a sync tool to a worker thread; an `async def` would run directly on
the event loop and block every other in-flight request under streamable-http.
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
from synapseclient.core.exceptions import SynapseHTTPError, SynapseNoCredentialsError
import requests
import jsonschema
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
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
    """Get or create a Synapse client, authenticated via synapseclient's own credential chain

    That chain checks, in order: ~/.synapseConfig, the SYNAPSE_AUTH_TOKEN
    environment variable, then AWS SSM Parameter Store. Delegating to it
    (rather than only ever reading SYNAPSE_AUTH_TOKEN ourselves) is what makes
    a config-file-only setup work.
    """
    global syn
    if syn is None:
        logger.info("Authenticating with Synapse")

        # Redirect stdout to prevent synapseclient from corrupting MCP protocol
        with RedirectStdout():
            # Create Synapse client with all output suppression flags
            client = synapseclient.Synapse(
                silent=True,           # Suppress messages
                skip_checks=True,      # Skip version and endpoint checks
                debug=False            # Disable debug output
            )
            try:
                client.login(silent=True)
            except SynapseNoCredentialsError as e:
                raise ValueError(
                    "No Synapse credentials found. Set the SYNAPSE_AUTH_TOKEN "
                    "environment variable or configure ~/.synapseConfig. Get a "
                    "token from https://www.synapse.org/ -> Account Settings -> "
                    "Personal Access Tokens"
                ) from e

        syn = client

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


def walk_folders(syn_client: synapseclient.Synapse,
                  container_id: str,
                  max_depth: Optional[int] = None) -> List[Dict[str, Any]]:
    """Recursively list every folder under `container_id`, not including it.

    Shared by create_dataset (which only needs the ids) and walk_project_tree
    (which also wants path and depth), so there is one place that walks a
    folder tree instead of two.
    """
    folders: List[Dict[str, Any]] = []

    def _walk(current_id: str, depth: int, path: str) -> None:
        if max_depth is not None and depth > max_depth:
            return
        for child in syn_client.getChildren(current_id, includeTypes=["folder"]):
            child_path = f"{path}/{child['name']}" if path else child["name"]
            folders.append({**child, "depth": depth, "path": child_path})
            _walk(child["id"], depth + 1, child_path)

    _walk(container_id, 0, "")
    return folders


def walk_files(syn_client: synapseclient.Synapse, container_id: str) -> List[Dict[str, Any]]:
    """Recursively list every file under `container_id`, descending through all subfolders."""
    files: List[Dict[str, Any]] = []

    def _walk(current_id: str) -> None:
        for child in syn_client.getChildren(current_id, includeTypes=["folder", "file"]):
            child_type = (child.get("type") or "").lower()
            if child_type.endswith("folder"):
                _walk(child["id"])
            elif child_type.endswith("fileentity") or child_type == "file":
                files.append(child)

    _walk(container_id)
    return files


# Create MCP server


def synapse_query(table_id: str, query: str) -> dict:
    """Execute Synapse SQL query"""
    try:
        query = query.replace("<table_id>", table_id)

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
                return {
                        "error": "SELECT * queries require a LIMIT clause or WHERE filter",
                        "message": "Please add a LIMIT clause (e.g., LIMIT 100), a WHERE filter, or specify explicit column names",
                        "reason": "SELECT * without LIMIT or WHERE can return excessive data and cause performance issues"
                    }

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
            return {
                    "error": "Query returned too many rows",
                    "row_count": row_count,
                    "max_allowed": max_rows_without_limit,
                    "message": f"Your WHERE filter returned {row_count} rows, which exceeds the maximum of {max_rows_without_limit} rows for SELECT * queries without LIMIT.",
                    "suggestion": f"Please add a LIMIT clause (e.g., LIMIT {max_rows_without_limit}) or make your WHERE filter more selective to reduce the result set.",
                    "query": query
                }

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

        return json.loads(json_text)

    except SynapseHTTPError as e:
        logger.error(f"Synapse HTTP error: {str(e)}")
        error_detail = str(e)

        # Provide helpful context for column errors
        if "Unknown column" in error_detail or "no such column" in error_detail.lower():
            return {
                    "error": "Column not found",
                    "message": error_detail,
                    "suggestion": "Query 'SELECT * FROM <table_id> LIMIT 1' to see available columns"
                }

        return {
                "error": "Synapse query failed",
                "message": error_detail
            }
    except json.JSONDecodeError as e:
        logger.error(f"JSON encoding error: {str(e)}", exc_info=True)
        return {
                "error": "JSON encoding failed",
                "message": str(e)
            }
    except Exception as e:
        logger.error(f"Query execution error: {str(e)}", exc_info=True)
        return {
                "error": "Query execution error",
                "message": str(e)
            }


DATA_TEMPLATES_URL = (
    "https://raw.githubusercontent.com/nf-osi/nf-metadata-dictionary"
    "/refs/heads/main/modules/Template/Data.yaml"
)
SCHEMA_BASE_URL = (
    "https://raw.githubusercontent.com/nf-osi/nf-metadata-dictionary"
    "/refs/heads/main/registered-json-schemas"
)
DEFAULT_SCHEMA_NAME = "PortalDataset"


def resolve_schema_url(schema_name: Optional[str] = None,
                       schema_url: Optional[str] = None) -> str:
    """Where a named schema lives.

    Shared by fetch_schema and validate_metadata so the two cannot disagree
    about which registry a name resolves against. An explicit URL wins over a
    name, matching the precedence fetch_schema has always had.
    """
    if schema_url:
        return schema_url
    return f"{SCHEMA_BASE_URL}/{schema_name or DEFAULT_SCHEMA_NAME}.json"


def fetch_schema_json(schema_url: str) -> dict:
    """GET one schema. Raises requests.RequestException, which callers report."""
    logger.info(f"Fetching schema from: {schema_url}")
    response = requests.get(schema_url, timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_schema(schema_name: str = DEFAULT_SCHEMA_NAME,
                  schema_url: Optional[str] = None) -> dict:
    """Fetch a schema directly from the metadata dictionary repo and return it."""
    schema_url = resolve_schema_url(schema_name, schema_url)
    try:
        return fetch_schema_json(schema_url)
    except requests.RequestException as e:
        raise ToolError(f"Failed to fetch schema from {schema_url}: {str(e)}")


def validate_metadata(metadata: dict,
                       schema: Optional[dict] = None,
                       schema_name: Optional[str] = None,
                       schema_url: Optional[str] = None) -> dict:
    """Validate metadata against a schema supplied by the caller.

    Accepts either the schema itself, as returned by fetch_schema, or the
    name of a registered schema to fetch, so validating against a registered
    schema costs a single call. An explicit schema takes precedence over a
    name, the same precedence resolve_schema_url applies between a URL and a
    name.
    """
    if schema is None:
        if not (schema_name or schema_url):
            return {
                "valid": False,
                "errors": [{"message": "Provide either 'schema' or 'schema_name'."}]
            }
        schema_url = resolve_schema_url(schema_name, schema_url)
        try:
            schema = fetch_schema_json(schema_url)
        except requests.RequestException as e:
            return {
                "valid": False,
                "errors": [{"message": f"Failed to fetch schema from {schema_url}: {e}"}]
            }

    try:
        jsonschema.validate(instance=metadata, schema=schema)

        # Calculate completeness. Counting metadata keys directly would let
        # fields outside the schema (typos, deprecated fields) inflate the
        # ratio past 1.0, so only schema properties count as fillable.
        schema_properties = schema.get("properties", {})
        total_fields = len(schema_properties)
        filled_fields = len([
            k for k in schema_properties
            if k in metadata and metadata[k] is not None
        ])
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

        return result

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
        return result


def create_dataset(folder_id: str,
                    name: Optional[str] = None,
                    parent_id: Optional[str] = None) -> dict:
    """Create a Dataset entity from a Folder"""
    from synapseclient import Dataset


    try:
        syn_client = get_synapse_client()

        # Get the folder entity
        folder = syn_client.get(folder_id, downloadFile=False)

        # Determine dataset name and parent
        dataset_name = name or f"{folder.name} Dataset"
        parent_id = parent_id or folder.parentId

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

        def collect_via_view(view_id: str) -> List[Dict[str, Any]]:
            folder_ids = [folder_id] + [f["id"] for f in walk_folders(syn_client, folder_id)]
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

                def _column_index(*names: str) -> Optional[int]:
                    # `a or b` would treat a legitimate index 0 as falsy and fall
                    # through to `b`; the SQL above always puts 'id' first.
                    for name in names:
                        idx = header_index.get(name)
                        if idx is not None:
                            return idx
                    return None

                id_idx = _column_index("id", "entityId")
                version_idx = _column_index("currentVersion", "versionNumber")

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
            for child in walk_files(syn_client, container_id):
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
            raise ToolError(
                f"No files found in folder {folder_id} or any of its subfolders; "
                "a Dataset needs at least one file to include"
            )

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

        return result

    except SynapseHTTPError as e:
        raise ToolError(f"Failed to create dataset from folder {folder_id}: {str(e)}")
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Unexpected error creating dataset from folder {folder_id}: {str(e)}")


def submit_metadata(entity_id: str, metadata: dict) -> dict:
    """Submit metadata by adding annotations to any Synapse entity"""

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

        return result

    except SynapseHTTPError as e:
        raise ToolError(f"Failed to add annotations to {entity_id}: {str(e)}")
    except Exception as e:
        raise ToolError(f"Unexpected error submitting metadata for {entity_id}: {str(e)}")


# ============================================================================
# PROJECT REVIEW TOOLS
# ============================================================================

def get_data_classes(templates_url: str = DATA_TEMPLATES_URL) -> str:
    """Fetch data class templates"""

    try:
        response = requests.get(templates_url, timeout=10)
        response.raise_for_status()

        return response.text

    except requests.RequestException as e:
        raise ToolError(f"Failed to fetch data classes: {str(e)}")


def get_project_children(entity_id: str,
                          include_types: Optional[List[str]] = None) -> dict:
    """Get immediate children of a container"""
    include_types = include_types or ["folder", "file"]

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

        return result

    except SynapseHTTPError as e:
        raise ToolError(f"Failed to get children: {str(e)}")


def get_entity_info(entity_id: str, include_annotations: bool = True) -> dict:
    """Get detailed entity information"""

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

        return info

    except SynapseHTTPError as e:
        raise ToolError(f"Failed to get entity info: {str(e)}")


def walk_project_tree(project_id: str, max_depth: int = 5) -> dict:
    """Recursively walk project structure"""

    try:
        syn_client = get_synapse_client()

        all_folders = [
            {"id": f["id"], "name": f["name"], "path": f["path"], "depth": f["depth"]}
            for f in walk_folders(syn_client, project_id, max_depth=max_depth)
        ]

        result = {
            "project_id": project_id,
            "total_folders": len(all_folders),
            "folders": all_folders
        }

        return result

    except SynapseHTTPError as e:
        raise ToolError(f"Failed to walk project tree: {str(e)}")


def count_folder_contents(folder_id: str) -> dict:
    """Count contents of a folder"""

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

        return result

    except SynapseHTTPError as e:
        raise ToolError(f"Failed to count folder contents: {str(e)}")


# ============================================================================
# FREQUENTLY SHARED TOOLS
# ============================================================================

def get_data_sharing_plan(study_id: str) -> dict:
    """Retrieve Data Sharing Plan"""
    url = f"https://dsp.nf.synapse.org/api/dsp/json/{study_id}"

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            dsp = response.json()
            return dsp
        elif response.status_code == 404:
            return {"error": "No DSP found for this study", "study_id": study_id}
        else:
            raise ToolError(f"Failed to retrieve DSP: HTTP {response.status_code}")

    except requests.RequestException as e:
        raise ToolError(f"Error retrieving DSP: {str(e)}")


# Which tools change something. Nine of these only read; two write to Synapse,
# and an agent cannot tell them apart unless it is told.
READS = ToolAnnotations(read_only_hint=True)
CREATES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
OVERWRITES = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True)

CURATION_TOOLS = (
    (synapse_query, READS),
    (fetch_schema, READS),
    (validate_metadata, READS),
    (create_dataset, CREATES),
    (submit_metadata, OVERWRITES),
    (get_data_classes, READS),
    (get_project_children, READS),
    (get_entity_info, READS),
    (walk_project_tree, READS),
    (count_folder_contents, READS),
    (get_data_sharing_plan, READS),
)


def register_curation_tools(mcp) -> int:
    """Add the curation tools to `mcp`. Returns how many were added."""
    for fn, annotations in CURATION_TOOLS:
        mcp.add_tool(fn, annotations=annotations)
    return len(CURATION_TOOLS)
