# MCP Tools Reference

This document describes all tools available in the NF Curator MCP server and their usage across different recipes.

## Tool Categories

### 🔬 Portal Metadata Tools
Used by `recipe_release.yaml` for generating and submitting dataset metadata.

#### `synapse_query`
Execute SQL queries against Synapse dataset tables to extract metadata.

**Parameters:**
- `table_id` (string, required) - Synapse table ID (e.g., syn12345678)
- `query` (string, required) - SQL query string (use `<table_id>` as placeholder)

**Returns:** `{"row_count": ..., "columns": [...], "data": [...]}` on success.

A `SELECT *` query raises `ToolError` before it runs unless it has a `LIMIT`
or a `WHERE` clause; a `WHERE` clause that still returns more than 1000 rows
gets the same treatment after the fact. Any query Synapse itself rejects
(e.g. an unknown column) also raises `ToolError`.

**Example:**
```python
{
  "table_id": "syn51234567",
  "query": "SELECT DISTINCT assay FROM <table_id>"
}
```

#### `fetch_schema`
Fetch a JSON schema from the NF metadata dictionary. Supports multiple schema types.

**Parameters:**
- `schema_name` (string, optional) - Schema name: "PortalDataset" (default), "PortalPublication", etc.
- `schema_url` (string, optional) - Full URL to schema (overrides schema_name if provided)

**Returns:** Complete JSON schema definition

**Examples:**
```python
# Default: Fetch PortalDataset schema
fetch_schema({})

# Fetch specific schema by name
fetch_schema({"schema_name": "PortalPublication"})

# Fetch from custom URL
fetch_schema({"schema_url": "https://example.com/custom-schema.json"})
```

**Common Schema Names:**
- `PortalDataset` - Dataset metadata (default)
- `PortalPublication` - Publication metadata
- `PortalStudy` - Study-level metadata

#### `validate_metadata`
Validate a metadata object against a JSON schema, either supplied directly or fetched by name/URL.

**Parameters:**
- `metadata` (object, required) - Metadata to validate
- `schema` (object, optional) - A schema object, e.g. as returned by `fetch_schema`
- `schema_name` (string, optional) - Name of a registered schema to fetch (default: "PortalDataset")
- `schema_url` (string, optional) - URL to fetch a schema from directly

At least one of `schema`, `schema_name`, or `schema_url` is required. An
explicit `schema` takes precedence over fetching one; between `schema_name`
and `schema_url`, the URL wins.

**Returns:** `{"valid": bool, "errors": [...], "warnings": [...], "completeness": float, "filled_fields": int, "total_fields": int}`.
`completeness` is the fraction of the schema's own properties that are
present and non-null in `metadata` — fields outside the schema don't count
toward it, so it never exceeds 1.0.

**Example:**
```python
# Validate directly against a named schema
validate_metadata({
  "metadata": {...},
  "schema_name": "PortalDataset"
})

# Or fetch once and validate several records against the same schema object
schema = fetch_schema({"schema_name": "PortalDataset"})
validate_metadata({"metadata": record_1, "schema": schema})
validate_metadata({"metadata": record_2, "schema": schema})
```

#### `create_dataset` ⚠️ writes to Synapse — creates an entity
Create a Dataset entity from a Folder to enable SQL queries over the files.

**Parameters:**
- `folder_id` (string, required) - Synapse folder ID to convert to dataset
- `name` (string, optional) - Name for the dataset (defaults to folder name + ' Dataset')
- `parent_id` (string, optional) - Parent project/folder ID (defaults to folder's parent)

**Returns:** Dataset ID, name, source folder, and item count

**Use Case:** When you need to query files within a Folder using SQL, first convert it to a Dataset entity. This is required because `synapse_query` only works with Dataset entities, not Folders.

File versions are resolved from the folder's study file view when one is
annotated on an ancestor (`studyFileviewId`), falling back to a recursive
folder traversal otherwise. Raises `ToolError` if the folder and its
subfolders contain no files.

**Example:**
```python
# Convert folder to dataset for querying
create_dataset({
  "folder_id": "syn12345678"
})

# Returns: {"dataset_id": "syn87654321", "item_count": 150, ...}
# Now you can query: synapse_query({"table_id": "syn87654321", ...})
```

#### `submit_metadata` ⚠️ writes to Synapse — overwrites annotations
Submit validated metadata by adding annotations to any Synapse entity (dataset, file, folder, project, paper, etc.).

**Parameters:**
- `entity_id` (string, required) - Synapse entity ID (e.g., syn12345678)
- `metadata` (object, required) - Validated metadata JSON to submit as annotations

**Returns:** Submission status, entity type, and annotation count

**Supported Entity Types:**
- Dataset (for portal dataset metadata)
- File (for individual file metadata)
- Folder (for collection-level metadata)
- Project (for study-level metadata)
- Any other Synapse entity with annotation support

**Note:** This tool is reusable across different curation workflows (datasets, papers, tools, etc.)

---

### 📁 Project Review Tools
Used by `recipe.yaml` for reviewing and classifying Synapse projects.

#### `get_data_classes`
Fetch available data classification templates from the metadata dictionary.

**Parameters:**
- `templates_url` (string, optional) - URL to Data.yaml templates

**Returns:** YAML content with all data class templates

#### `get_project_children`
Get immediate children (folders/files) of a Synapse container.

**Parameters:**
- `entity_id` (string, required) - Synapse project or folder ID
- `include_types` (array, optional) - Filter by types (default: ["folder", "file"])

**Returns:** List of children with id, name, and type

#### `get_entity_info`
Get detailed information about a Synapse entity including annotations.

**Parameters:**
- `entity_id` (string, required) - Synapse entity ID
- `include_annotations` (boolean, optional) - Include annotations (default: true)

**Returns:** Entity details with metadata and annotations

**Note:** Also used by `recipe_release.yaml` for entity lookups during portal metadata generation.

#### `walk_project_tree`
Recursively traverse project structure to find all folders.

**Parameters:**
- `project_id` (string, required) - Synapse project ID
- `max_depth` (integer, optional) - Maximum traversal depth (default: 5)

**Returns:** Complete folder tree with paths and depth information

#### `count_folder_contents`
Count files and subfolders in a folder to determine if data exists.

**Parameters:**
- `folder_id` (string, required) - Synapse folder ID

**Returns:** File count, folder count, and has_data flag

---

### 🔗 Shared Tools
Used by both recipes for common operations.

#### `get_data_sharing_plan`
Retrieve Data Sharing Plan document for a study.

**Parameters:**
- `study_id` (string, required) - Synapse project ID

**Returns:** Complete DSP JSON, or `{"error": "No DSP found for this study", "study_id": ...}` if none exists (404).

**API Endpoint:** https://dsp.nf.synapse.org/api/dsp/json/{study_id}


## Error Handling

Most tools raise `ToolError` on failure, which MCP surfaces as a tool-level
error rather than a normal result — clients should treat these as failures,
not answers to work with.

Two tools return a result with an `error` key instead, because the error is
itself part of the answer rather than a failed call:
- `get_data_sharing_plan` — no DSP exists for the study (404)
- `validate_metadata` — an invalid metadata/schema combination is a normal `"valid": false` result

Common failure causes:
- **Authentication**: no Synapse credentials found (see below)
- **Not Found**: entity or resource doesn't exist
- **Permission Denied**: caller lacks access to the resource

---

## Authentication

Synapse tools resolve credentials via synapseclient's own chain, in order: a
`~/.synapseConfig` file, the `SYNAPSE_AUTH_TOKEN` environment variable, or
AWS SSM Parameter Store.

```bash
export SYNAPSE_AUTH_TOKEN="your-personal-access-token"
```

Get your token from: https://www.synapse.org/ → Account Settings → Personal Access Tokens

See [nfty's README](README.md#environment-setup) for transport and other deployment configuration.

---

## Examples

### Portal Metadata Workflow
```python
# 1. Fetch schema
schema = fetch_schema({})

# 2. Get entity info
get_entity_info({"entity_id": "syn51234567"})

# 3. Query metadata
synapse_query({
  "table_id": "syn51234567",
  "query": "SELECT DISTINCT species FROM <table_id>"
})

# 4. Validate metadata against the schema fetched in step 1
validate_metadata({
  "metadata": {...},
  "schema": schema
})

# 5. Submit metadata
submit_metadata({
  "entity_id": "syn51234567",  # Works with any entity type
  "metadata": {...}
})
```

### Project Review Workflow
```python
# 1. Get DSP
get_data_sharing_plan({"study_id": "syn12345678"})

# 2. Get data classification templates
get_data_classes({})

# 3. Walk project tree
walk_project_tree({"project_id": "syn12345678"})

# 4. For each folder, get info
get_entity_info({"entity_id": "syn23456789"})

# 5. Count contents
count_folder_contents({"folder_id": "syn23456789"})
```
