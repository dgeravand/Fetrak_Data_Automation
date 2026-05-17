# ------------------------------------------------------------------------------
# CONFIG LOADER
# ------------------------------------------------------------------------------
# Loads job configurations from YAML files in the configs directory.
# Supports query file includes and active/inactive job filtering.
# Also provides save and delete functions for job management.
# ------------------------------------------------------------------------------
import yaml
from pathlib import Path


# ------------------------------------------------------------------------------
# LOAD JOBS
# ------------------------------------------------------------------------------
def load_jobs(config_dir="configs", target_job=None):
    jobs = []
    inactive_jobs = []

    config_path = Path(config_dir)

    for file in config_path.glob("*.y*ml"):
        print(f"[CONFIG] loading: {file}")

        with open(file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        file_jobs = data.get("jobs", [data])

        for job in file_jobs:
            job_name = job.get("name", "unknown")

            if target_job and job_name != target_job:
                continue

            is_active = job.get("active", True)

            if not is_active:
                print(f"[SKIP] job '{job_name}' is inactive (active: false)")
                inactive_jobs.append(job_name)
                continue

            source = job.get("source", {})

            if "query_file" in source:
                query_file_path = Path(source["query_file"])

                if not query_file_path.is_absolute():
                    query_file_path = config_path / query_file_path

                if not query_file_path.exists():
                    print(f"[WARNING] query file not found for job '{job_name}': {query_file_path}")
                    continue

                with open(query_file_path, "r", encoding="utf-8") as qf:
                    source["query"] = qf.read()

                print(f"[SQL] loaded query for '{job_name}' from: {query_file_path}")

            jobs.append(job)
            print(f"[JOB] ready: {job_name}")

    return jobs, inactive_jobs


# ------------------------------------------------------------------------------
# GET ALL CONFIGS WITH JOBS
# ------------------------------------------------------------------------------
def get_all_configs_with_jobs(config_dir="configs"):
    """Return all config files with their jobs."""
    config_path = Path(config_dir)
    configs = []

    for file in sorted(config_path.glob("*.y*ml")):
        with open(file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        file_name = file.name
        jobs = data.get("jobs", [])

        configs.append({
            "file": file_name,
            "path": str(file),
            "jobs": jobs
        })

    return configs


# ------------------------------------------------------------------------------
# GET QUERY FILES
# ------------------------------------------------------------------------------
def get_query_files(config_name=None, query_dir="queries"):
    """Return list of query files for a specific config.

    Args:
        config_name: If provided, look in configs/queries/<config_name>/
                  If not provided, look in configs/queries/ (backward compatibility)
    """
    # If config_name is provided, look in config-specific folder
    if config_name:
        query_path = Path("configs") / query_dir / config_name
    else:
        # For backward compatibility, look in configs/queries/ (the old flat location)
        query_path = Path("configs") / query_dir

    if not query_path.exists():
        return []

    return sorted(query_path.glob("*.sql"))


# ------------------------------------------------------------------------------
# GET ALL QUERIES WITH CONFIGS
# ------------------------------------------------------------------------------
def get_all_queries_with_configs():
    """Return all query files grouped by config.

    Returns:
        List of dicts with: config_name, config_file, queries[]
    """
    all_configs = get_all_configs_with_jobs()
    result = []

    for config in all_configs:
        config_name = config.get("file", "").replace(".yaml", "").replace(".yml", "")

        # Get queries from config-specific folder
        query_files = get_query_files(config_name=config_name)

        # Also check backward compatibility - flat queries folder
        flat_queries = get_query_files()
        # Filter to only include queries that might belong to this config
        # by checking if file name starts with config name pattern
        for qf in flat_queries:
            if qf.name.startswith(config_name + "_") or qf.name.startswith(config_name.lower() + "_"):
                query_files.append(qf)

        queries = []
        for qf in query_files:
            # Load metadata for this query
            metadata = load_query_metadata(qf)
            queries.append({
                "file": qf.name,
                "path": str(qf),
                "size": qf.stat().st_size if qf.exists() else 0,
                "description": metadata.get("description", ""),
                "connection_type": metadata.get("connection_type", "sqlserver")
            })

        result.append({
            "config_name": config_name,
            "config_file": config.get("file"),
            "queries": queries
        })

    return result


# ------------------------------------------------------------------------------
# LOAD QUERY
# ------------------------------------------------------------------------------
def load_query(query_file_path, config_name=None):
    """Load a specific query file.

    Args:
        query_file_path: Path to the query file
        config_name: If provided, look in configs/queries/<config_name>/ first,
                    then fall back to flat location (configs/queries/) matching pattern
    """
    path = Path(query_file_path)
    if not path.is_absolute():
        # If config_name is provided, try config-specific folder first
        if config_name:
            config_path = Path("configs") / "queries" / config_name / path
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    return f.read()
            # Fall back to flat location (configs/queries/) matching pattern
            flat_path = Path("configs") / "queries" / path
            if flat_path.exists():
                with open(flat_path, "r", encoding="utf-8") as f:
                    return f.read()
        else:
            # Try the path as-is (supports config_name/filename.sql format)
            direct_path = Path("configs") / "queries" / path
            if direct_path.exists():
                with open(direct_path, "r", encoding="utf-8") as f:
                    return f.read()
            # If path has a parent (e.g., config_name/filename), try just the filename
            # in all config subfolders for backward compatibility
            if path.parent != Path("."):
                filename = path.name
                queries_dir = Path("configs") / "queries"
                if queries_dir.exists():
                    # Search in all subdirectories
                    for subdir in queries_dir.iterdir():
                        if subdir.is_dir():
                            candidate = subdir / filename
                            if candidate.exists():
                                with open(candidate, "r", encoding="utf-8") as f:
                                    return f.read()
                    # Also check flat location
                    flat = queries_dir / filename
                    if flat.exists():
                        with open(flat, "r", encoding="utf-8") as f:
                            return f.read()
            else:
                # Just a filename - try flat location
                flat_path = Path("configs") / "queries" / path
                if flat_path.exists():
                    with open(flat_path, "r", encoding="utf-8") as f:
                        return f.read()
    elif path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# ------------------------------------------------------------------------------
# SAVE QUERY
# ------------------------------------------------------------------------------
def save_query(query_file_path, content, config_name=None, description=None, connection_type=None):
    """Save a query file.

    Args:
        query_file_path: Relative path for the query file
        content: The SQL content to save
        config_name: If provided, save in configs/queries/<config_name>/
                   Falls back to configs/queries/ if config folder doesn't exist
        description: Optional description of the query
        connection_type: Optional connection type (sqlserver, clickhouse)
    """
    path = Path(query_file_path)
    if not path.is_absolute():
        # If config_name is provided, try config-specific folder first
        if config_name:
            config_path = Path("configs") / "queries" / config_name / path
            # Only save to config folder if it exists, otherwise use flat location
            if config_path.parent.exists():
                path = config_path
            else:
                path = Path("configs") / "queries" / path
        else:
            path = Path("configs") / "queries" / path

    # Ensure queries directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Normalize line endings and strip trailing newlines
    if content:
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        # Strip trailing newlines but keep one at the end
        content = content.rstrip('\n') + '\n'

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # Save metadata (including description and connection_type) to a sidecar file
    if description is not None or connection_type is not None:
        meta_path = path.with_suffix(path.suffix + ".meta")
        import json
        meta_data = {}
        if description is not None:
            meta_data["description"] = description
        if connection_type is not None:
            meta_data["connection_type"] = connection_type
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)

    print(f"[QUERY] saved: {path}")
    return str(path)


# ------------------------------------------------------------------------------
# LOAD QUERY METADATA
# ------------------------------------------------------------------------------
def load_query_metadata(query_path):
    """Load metadata for a query file.

    Args:
        query_path: Path to the query file

    Returns:
        Dict with metadata (description, etc.) or empty dict if no metadata exists
    """
    path = Path(query_path)
    meta_path = path.with_suffix(path.suffix + ".meta")
    if meta_path.exists():
        import json
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}


# ------------------------------------------------------------------------------
# SAVE JOB CONFIG
# ------------------------------------------------------------------------------
def save_job_config(job, config_dir="configs", config_file=None, old_job_name=None):
    """Save or update a job configuration."""
    job_name = job.get("name")
    if not job_name:
        raise ValueError("Job name is required")

    config_path = Path(config_dir)

    # Convert string config_file to Path if needed
    if config_file and isinstance(config_file, str):
        config_file = config_path / config_file

    # Find existing config file for this job if not provided
    if not config_file:
        for file in config_path.glob("*.y*ml"):
            with open(file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            file_jobs = data.get("jobs", [])
            for existing_job in file_jobs:
                if existing_job.get("name") == job_name:
                    config_file = file
                    break
            if config_file:
                break

    # Create new config file if not found
    if not config_file:
        config_file = config_path / f"{job_name}.yaml"

    # Load existing config
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {"jobs": []}

    # Find and update job or add new
    # Use old_job_name for lookup when renaming so the correct job is replaced
    lookup_name = old_job_name or job_name
    jobs = data.get("jobs", [])
    found = False
    for i, existing_job in enumerate(jobs):
        if existing_job.get("name") == lookup_name:
            jobs[i] = job
            found = True
            break

    if not found:
        jobs.append(job)

    data["jobs"] = jobs

    # Save
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    print(f"[CONFIG] saved job '{job_name}' to {config_file}")
    return config_file


# ------------------------------------------------------------------------------
# DELETE JOB CONFIG
# ------------------------------------------------------------------------------
def delete_job_config(job_name, config_dir="configs"):
    """Delete a job configuration."""
    config_path = Path(config_dir)

    for file in config_path.glob("*.y*ml"):
        with open(file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        jobs = data.get("jobs", [])
        original_count = len(jobs)

        # Remove job
        jobs = [j for j in jobs if j.get("name") != job_name]

        if len(jobs) < original_count:
            data["jobs"] = jobs

            # Save
            with open(file, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

            print(f"[CONFIG] deleted job '{job_name}' from {file}")
            return True

    return False
