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

**Returns:** JSON with row_count, columns, and data

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
Validate metadata JSON against a saved schema file.

**Parameters:**
- `metadata` (object, required) - JSON metadata to validate
- `schema_file` (string, required) - Path to saved schema file (e.g., "PortalDataset.json")

**Returns:** Validation results with errors, warnings, and completeness score

**Example:**
```python
# First, fetch and save the schema
fetch_schema({"save_to_file": "PortalDataset.json"})

# Then validate metadata using the saved schema
validate_metadata({
  "metadata": {...},
  "schema_file": "PortalDataset.json"
})
```

**Workflow:** Always fetch and save the schema first, then reuse it for validating multiple datasets.

#### `create_dataset`
Create a Dataset entity from a Folder to enable SQL queries over the files.

**Parameters:**
- `folder_id` (string, required) - Synapse folder ID to convert to dataset
- `name` (string, optional) - Name for the dataset (defaults to folder name + ' Dataset')
- `parent_id` (string, optional) - Parent project/folder ID (defaults to folder's parent)

**Returns:** Dataset ID, name, source folder, and item count

**Use Case:** When you need to query files within a Folder using SQL, first convert it to a Dataset entity. This is required because `synapse_query` only works with Dataset entities, not Folders.

**Example:**
```python
# Convert folder to dataset for querying
create_dataset({
  "folder_id": "syn12345678"
})

# Returns: {"dataset_id": "syn87654321", "item_count": 150, ...}
# Now you can query: synapse_query({"table_id": "syn87654321", ...})
```

#### `submit_metadata`
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

**Note:** This tool is also used by recipe_release.yaml as it provides more complete information than the basic version.

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

**Returns:** Complete DSP JSON or error if not found

**API Endpoint:** https://dsp.nf.synapse.org/api/dsp/json/{study_id}


---

### 🔍 OpenAPI Validation Tools (Optional)
Available when `OPENAPI_SPEC_URI` environment variable is set at server startup. Useful for validating JSON payloads against an OpenAPI specification.

**Configuration:**
```bash
# Load from local file
export OPENAPI_SPEC_URI="/path/to/openapi.yaml"

# Or load from URL
export OPENAPI_SPEC_URI="https://example.com/openapi.json"
```

Supports both YAML and JSON formats.

#### `openapi_list_schemas`
List all available schemas defined in the loaded OpenAPI spec.

**Parameters:** None

**Returns:** List of schema names with count and spec URI

**Example:**
```json
{
  "spec_uri": "https://example.com/openapi.json",
  "schemas": ["User", "Order", "Product"],
  "count": 3
}
```

#### `openapi_validate`
Validate JSON payload(s) against a schema from the OpenAPI spec. Supports both single objects and batch validation with arrays.

**Parameters:**
- `schema_name` (string, required) - Name of the schema from `#/components/schemas`
- `payload` (object or array, required) - A single JSON object or an array of objects to validate

**Returns:** Validation result with errors if invalid. For batch validation, includes summary counts.

**Examples:**
```python
# Single object - valid
openapi_validate({
  "schema_name": "User",
  "payload": {"id": 1, "name": "John"}
})
# Returns: {"valid": true, "errors": []}

# Single object - invalid
openapi_validate({
  "schema_name": "User",
  "payload": {"id": "not-an-int"}
})
# Returns: {"valid": false, "errors": [{"path": "/id", "message": "'not-an-int' is not of type 'integer'", ...}]}

# Batch validation - array of objects
openapi_validate({
  "schema_name": "User",
  "payload": [
    {"id": 1, "name": "John"},
    {"id": 2, "name": "Jane"},
    {"id": "bad", "name": "Invalid"}
  ]
})
# Returns:
# {
#   "batch": true,
#   "count": 3,
#   "all_valid": false,
#   "valid_count": 2,
#   "invalid_count": 1,
#   "results": [
#     {"valid": true, "errors": [], "index": 0},
#     {"valid": true, "errors": [], "index": 1},
#     {"valid": false, "errors": [...], "index": 2}
#   ]
# }
```

#### `openapi_get_schema`
Get the full schema definition for a named schema.

**Parameters:**
- `schema_name` (string, required) - Name of the schema from `#/components/schemas`

**Returns:** Complete JSON schema definition

**Example:**
```python
openapi_get_schema({"schema_name": "User"})
# Returns the full schema with type, properties, required fields, etc.
```

---

## Error Handling

All tools return errors in a consistent format:

```json
{
  "error": "Error description",
  "details": "Additional context"
}
```

Common errors:
- **Authentication**: SYNAPSE_AUTH_TOKEN not set or invalid
- **Not Found**: Entity or resource doesn't exist
- **Permission Denied**: User lacks access to resource
- **Validation**: Metadata doesn't conform to schema

---

## Authentication

All Synapse tools require the `SYNAPSE_AUTH_TOKEN` environment variable:

```bash
export SYNAPSE_AUTH_TOKEN="your-personal-access-token"
```

Get your token from: https://www.synapse.org/ → Account Settings → Personal Access Tokens

---

## Examples

### Portal Metadata Workflow
```python
# 1. Fetch schema
fetch_schema({})

# 2. Get entity info
get_entity_info({"entity_id": "syn51234567"})

# 3. Query metadata
synapse_query({
  "table_id": "syn51234567",
  "query": "SELECT DISTINCT species FROM <table_id>"
})

# 4. Validate metadata
validate_metadata({
  "metadata": {...},
  "schema": {...}
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
