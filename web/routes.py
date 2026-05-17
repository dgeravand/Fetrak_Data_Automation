# ------------------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------------------
# Flask routes for the data automation UI.
# Uses SQLAlchemy 2.0 style.
# ------------------------------------------------------------------------------
import yaml
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, render_template, redirect, url_for, flash, request, g, jsonify

from web import models
from web.models import Run
from core.config_loader import (
    load_jobs, save_job_config, delete_job_config,
    get_all_configs_with_jobs, get_query_files, load_query, save_query,
    get_all_queries_with_configs
)
from core.job_runner import JobRunner

bp = Blueprint("main", __name__)

# Thread pool for non-blocking manual job execution
_manual_executor = ThreadPoolExecutor(max_workers=4)

# Track running manual jobs for the UI
_running_manual_jobs = {}


# ------------------------------------------------------------------------------
# CONFIGS - Show all config files with jobs
# ------------------------------------------------------------------------------
@bp.route("/configs")
def configs():
    """Show all config files with their jobs."""
    search_query = request.args.get("search", "").strip().lower()
    config_filter = request.args.get("config", "").strip()
    all_configs = get_all_configs_with_jobs()
    all_configs_original = list(all_configs)  # Keep original for dropdown

    # Get query counts for each config
    all_queries = get_all_queries_with_configs()
    query_counts = {}
    for qc in all_queries:
        query_counts[qc.get("config_file")] = len(qc.get("queries", []))

    # Add query count to each config
    for config in all_configs:
        config["query_count"] = query_counts.get(config.get("file"), 0)

    # Filter by config file if selected
    if config_filter:
        filtered_configs = [c for c in all_configs if c.get("file") == config_filter]
        all_configs = filtered_configs

    # Filter by search query
    elif search_query:
        filtered_configs = []
        for config in all_configs:
            # Filter by config file name
            if search_query in config.get("file", "").lower():
                filtered_configs.append(config)
            else:
                # Filter jobs within config
                filtered_jobs = [job for job in config.get("jobs", []) if search_query in job.get("name", "").lower()]
                if filtered_jobs:
                    config_copy = dict(config)
                    config_copy["jobs"] = filtered_jobs
                    filtered_configs.append(config_copy)
        all_configs = filtered_configs

    # Fetch last run for each job
    session = g.get("session")
    last_runs = {}
    if session:
        from sqlalchemy import func
        subq = session.query(
            Run.job_name,
            func.max(Run.start_time).label("max_start")
        ).group_by(Run.job_name).subquery()

        runs = session.query(Run).join(
            subq,
            (Run.job_name == subq.c.job_name) & (Run.start_time == subq.c.max_start)
        ).all()

        for r in runs:
            last_runs[r.job_name] = {
                "status": r.status,
                "end_time": r.end_time,
            }

    # Attach last run to each job
    for config in all_configs:
        for job in config.get("jobs", []):
            job["last_run"] = last_runs.get(job.get("name"))

    return render_template("configs.html", configs=all_configs, all_configsdropdown=all_configs_original, config_filter=config_filter)


# ------------------------------------------------------------------------------
# NEW CONFIG FILE
# ------------------------------------------------------------------------------
@bp.route("/configs/new", methods=["GET", "POST"])
def configs_new():
    """Create new config file."""
    if request.method == "POST":
        filename = request.form.get("filename", "").strip()
        if filename:
            if not filename.endswith('.yaml') and not filename.endswith('.yml'):
                filename = filename + '.yaml'

            # Create empty config file
            config_path = Path("configs") / filename
            config_path.write_text("jobs: []\n")

            # Create corresponding queries folder
            config_name = filename.replace('.yaml', '').replace('.yml', '')
            queries_folder = Path("configs") / "queries" / config_name
            queries_folder.mkdir(parents=True, exist_ok=True)

            flash(f"Config file '{filename}' created", "success")
            return redirect(url_for("main.configs"))

    return render_template("config_new.html")


# ------------------------------------------------------------------------------
# DASHBOARD - Show all jobs (flat list)
# ------------------------------------------------------------------------------
@bp.route("/")
def index():
    """Redirect to configs page."""
    return redirect(url_for("main.configs"))

    # Flatten all jobs with their config file
    job_list = []
    for config in all_configs:
        for job in config.get("jobs", []):
            job_list.append({
                "name": job.get("name", "unknown"),
                "active": job.get("active", True),
                "schedule": job.get("schedule", ""),
                "source_type": job.get("source", {}).get("type", "none"),
                "query_file": job.get("source", {}).get("query_file", ""),
                "config_file": config.get("file"),
            })

    return render_template("index.html", jobs=job_list)


# ------------------------------------------------------------------------------
# JOB TOGGLE
# ------------------------------------------------------------------------------
@bp.route("/job/<config_file>/<name>/toggle", methods=["GET", "POST"])
def job_toggle(config_file, name):
    """Toggle job active status."""
    all_configs = get_all_configs_with_jobs()

    for config in all_configs:
        if config.get("file") == config_file:
            for job in config.get("jobs", []):
                if job.get("name") == name:
                    job["active"] = not job.get("active", True)
                    save_job_config(job, config_file=config_file)
                    flash(f"Job '{name}' {'activated' if job['active'] else 'deactivated'}", "success")
                    break
            break

    return redirect(url_for("main.configs"))


# ------------------------------------------------------------------------------
# JOB NEW - Create in specific config file
# ------------------------------------------------------------------------------
@bp.route("/configs/<config_file>/new", methods=["GET", "POST"])
def job_new(config_file):
    """Create new job in specific config file."""
    if request.method == "POST":
        job = {
            "name": request.form.get("name"),
            "active": False,  # new jobs always start inactive
            "schedule": request.form.get("schedule") or "0 8 * * *",
            "source": {
                "type": request.form.get("source_type"),
            },
            "output": {
                "sharepoint": {
                    "library": request.form.get("sp_library"),
                    "folder": request.form.get("sp_folder"),
                },
                "file": {
                    "name": request.form.get("file_name"),
                    "write_mode": request.form.get("write_mode"),
                    "sheet": {
                        "name": request.form.get("sheet_name"),
                    },
                },
            },
        }

        query = request.form.get("query", "").strip()
        query_file = request.form.get("query_file", "").strip()
        if query:
            # Save query to file
            if query_file:
                save_query(query_file, query)
                job["source"]["query_file"] = query_file
            else:
                job["source"]["query"] = query
        elif query_file:
            job["source"]["query_file"] = query_file

        owners = request.form.get("owners", "").strip()
        if owners:
            job["owners"] = [o.strip() for o in owners.split(",") if o.strip()]
        else:
            job["owners"] = []

        developer = request.form.get("developer", "").strip()
        if developer:
            job["developer"] = developer

        save_job_config(job, config_file=config_file)
        flash(f"Job '{job['name']}' created successfully. It is inactive — enable it when ready.", "success")
        return redirect(url_for("main.configs"))

    # Get query files for selection (with config info)
    all_queries = get_all_queries_with_configs()
    # Flatten to list of dicts with config_name
    query_files = []
    for config_queries in all_queries:
        for q in config_queries["queries"]:
            query_files.append({
                "name": q["file"],
                "config_name": config_queries["config_name"]
            })
    return render_template("editor.html", title="New Job", config_file=config_file, query_files=query_files)


# ------------------------------------------------------------------------------
# JOB EDIT
# ------------------------------------------------------------------------------
@bp.route("/configs/<config_file>/<name>", methods=["GET", "POST"])
def job_edit(config_file, name):
    """Edit existing job."""
    all_configs = get_all_configs_with_jobs()

    # Find job
    job = None
    for config in all_configs:
        if config.get("file") == config_file:
            for j in config.get("jobs", []):
                if j.get("name") == name:
                    job = j
                    break

    if not job:
        flash(f"Job '{name}' not found", "error")
        return redirect(url_for("main.configs"))

    if request.method == "POST":
        old_name = job.get("name")
        job["name"] = request.form.get("name")
        job["active"] = "active" in request.form
        job["schedule"] = request.form.get("schedule") or "0 8 * * *"

        job["source"] = {
            "type": request.form.get("source_type"),
        }

        query = request.form.get("query", "").strip()
        query_file = request.form.get("query_file", "").strip()
        if query:
            if query_file:
                save_query(query_file, query)
                job["source"]["query_file"] = query_file
                job["source"].pop("query", None)
            else:
                job["source"]["query"] = query
                job["source"].pop("query_file", None)
        elif query_file:
            job["source"]["query_file"] = query_file
            job["source"].pop("query", None)
        else:
            job["source"].pop("query", None)
            job["source"].pop("query_file", None)

        job["output"] = {
            "sharepoint": {
                "library": request.form.get("sp_library"),
                "folder": request.form.get("sp_folder"),
            },
            "file": {
                "name": request.form.get("file_name"),
                "write_mode": request.form.get("write_mode"),
                "sheet": {
                    "name": request.form.get("sheet_name"),
                },
            },
        }

        owners = request.form.get("owners", "").strip()
        if owners:
            job["owners"] = [o.strip() for o in owners.split(",") if o.strip()]
        else:
            job["owners"] = []

        developer = request.form.get("developer", "").strip()
        if developer:
            job["developer"] = developer
        else:
            job.pop("developer", None)

        save_job_config(job, config_file=config_file, old_job_name=old_name)
        flash(f"Job '{name}' updated successfully", "success")
        return redirect(url_for("main.configs"))

    # Get query files for selection (with config info)
    all_queries = get_all_queries_with_configs()
    # Flatten to list of dicts with config_name
    query_files = []
    for config_queries in all_queries:
        for q in config_queries["queries"]:
            query_files.append({
                "name": q["file"],
                "config_name": config_queries["config_name"]
            })
    return render_template(
        "editor.html",
        title=f"Edit: {name}",
        job=job,
        config_file=config_file,
        query_files=query_files
    )


# ------------------------------------------------------------------------------
# JOB COPY
# ------------------------------------------------------------------------------
@bp.route("/configs/<config_file>/<name>/copy", methods=["POST"])
def job_copy(config_file, name):
    """Copy a job with a new name."""
    all_configs = get_all_configs_with_jobs()

    # Find the job to copy
    job = None
    for config in all_configs:
        if config.get("file") == config_file:
            for j in config.get("jobs", []):
                if j.get("name") == name:
                    job = j
                    break

    if not job:
        flash(f"Job '{name}' not found", "error")
        return redirect(url_for("main.configs"))

    new_name = request.form.get("new_name", "").strip()
    if not new_name:
        flash("New job name is required", "error")
        return redirect(url_for("main.configs"))

    # Check for duplicate name across all configs
    for config in all_configs:
        for j in config.get("jobs", []):
            if j.get("name") == new_name:
                flash(f"Job name '{new_name}' already exists", "error")
                return redirect(url_for("main.configs"))

    # Deep copy the job and update name
    import copy
    new_job = copy.deepcopy(job)
    new_job["name"] = new_name
    # Default to inactive for copied job
    new_job["active"] = False

    save_job_config(new_job, config_file=config_file)
    flash(f"Job '{name}' copied to '{new_name}'. It is inactive — enable it when ready.", "success")
    return redirect(url_for("main.configs"))


# ------------------------------------------------------------------------------
# JOB DELETE
# ------------------------------------------------------------------------------
@bp.route("/configs/<config_file>/<name>/delete", methods=["GET", "POST"])
def job_delete(config_file, name):
    """Delete a job and its run history."""
    search = request.args.get("search", "").strip()
    config_filter = request.args.get("config", "").strip()
    if delete_job_config(name):
        # Also delete run history for this job
        session = g.get("session")
        if session:
            session.query(Run).filter(Run.job_name == name).delete()
            session.commit()
        flash(f"Job '{name}' deleted successfully", "success")
    else:
        flash(f"Job '{name}' not found", "error")

    args = {}
    if search:
        args["search"] = search
    if config_filter:
        args["config"] = config_filter
    return redirect(url_for("main.configs", **args))


# ------------------------------------------------------------------------------
# CONFIG ADMIN - Manage Config Files
# ------------------------------------------------------------------------------
@bp.route("/configs/admin")
def configs_admin():
    """Admin page to manage config files."""
    import os
    from pathlib import Path

    configs_dir = Path("configs")
    config_list = []

    if configs_dir.exists():
        for config_file in sorted(configs_dir.glob("*.y*ml")):
            # Load config to get job count and check if inactive
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except:
                data = {}

            job_count = len(data.get("jobs", []))
            is_active = data.get("active", True)  # Default to active if not specified
            created_timestamp = os.path.getctime(config_file)
            created_date = datetime.fromtimestamp(created_timestamp).strftime("%Y-%m-%d %H:%M")

            # Get query files count for this config
            query_folder = Path("configs") / "queries" / config_file.stem
            if query_folder.exists():
                query_files = list(query_folder.glob("*.sql"))
                query_count = len(query_files)
            else:
                query_count = 0

            config_list.append({
                "file": config_file.name,
                "name": config_file.stem,
                "job_count": job_count,
                "query_count": query_count,
                "active": is_active,
                "created_date": created_date,
                "path": str(config_file)
            })

    return render_template("configs_admin.html", configs=config_list)


@bp.route("/configs/<config_file>/deactivate", methods=["POST"])
def config_deactivate(config_file):
    """Deactivate a config (virtually) by adding active: false to the config file."""
    config_path = Path("configs") / config_file

    if not config_path.exists():
        flash(f"Config '{config_file}' not found", "error")
        return redirect(url_for("main.configs_admin"))

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Add active: false at config level
        data["active"] = False

        # Write back
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

        flash(f"Config '{config_file}' deactivated", "success")
    except Exception as e:
        flash(f"Error deactivating config: {e}", "error")

    return redirect(url_for("main.configs_admin"))


@bp.route("/configs/<config_file>/activate", methods=["POST"])
def config_activate(config_file):
    """Activate a config by setting active: true in the config file."""
    config_path = Path("configs") / config_file

    if not config_path.exists():
        flash(f"Config '{config_file}' not found", "error")
        return redirect(url_for("main.configs_admin"))

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Set active: true at config level
        data["active"] = True

        # Write back
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

        flash(f"Config '{config_file}' activated", "success")
    except Exception as e:
        flash(f"Error activating config: {e}", "error")

    return redirect(url_for("main.configs_admin"))


@bp.route("/configs/<config_file>/delete_config", methods=["POST"])
def config_delete_physically(config_file):
    """Delete a config file, its query folder, and all related run history."""
    from pathlib import Path
    import shutil

    config_path = Path("configs") / config_file

    try:
        # Collect job names from this config before deleting the file
        job_names = []
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            job_names = [j.get("name") for j in data.get("jobs", []) if j.get("name")]

        # Delete run history for all jobs in this config
        if job_names:
            session = g.get("session")
            if session:
                session.query(Run).filter(Run.job_name.in_(job_names)).delete(synchronize_session=False)
                session.commit()

        # Delete config file
        if config_path.exists():
            config_path.unlink()

        # Delete query folder for this config
        query_folder = Path("configs") / "queries" / Path(config_file).stem
        if query_folder.exists():
            shutil.rmtree(query_folder)

        flash(f"Config '{config_file}' deleted", "success")
    except Exception as e:
        flash(f"Error deleting config: {e}", "error")

    return redirect(url_for("main.configs_admin"))


@bp.route("/configs/<config_file>/delete", methods=["GET"])
def configs_admin_delete(config_file):
    """Delete a config file, its query folder, and all related run history."""
    from pathlib import Path
    import shutil

    config_path = Path("configs") / config_file

    if not config_path.exists():
        flash(f"Config '{config_file}' not found", "error")
        return redirect(url_for("main.scheduler_admin"))

    try:
        # Collect job names from this config before deleting the file
        job_names = []
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        job_names = [j.get("name") for j in data.get("jobs", []) if j.get("name")]

        # Delete run history for all jobs in this config
        if job_names:
            session = g.get("session")
            if session:
                session.query(Run).filter(Run.job_name.in_(job_names)).delete(synchronize_session=False)
                session.commit()

        # Delete config file
        config_path.unlink()

        # Delete query folder if exists
        query_folder = Path("configs") / "queries" / config_file.replace('.yaml', '').replace('.yml', '')
        if query_folder.exists():
            shutil.rmtree(query_folder)

        flash(f"Config '{config_file}' deleted", "success")
    except Exception as e:
        flash(f"Error deleting config: {e}", "error")

    return redirect(url_for("main.scheduler_admin"))


@bp.route("/configs/<config_file>/rename", methods=["GET", "POST"])
def config_rename(config_file):
    """Rename a config file."""
    from pathlib import Path
    import shutil
    import os

    # Ensure absolute paths for reliability on Windows
    base_dir = Path(__file__).parent.parent.resolve()
    config_path = (base_dir / "configs" / config_file).resolve()
    config_stem = config_file.replace('.yaml', '').replace('.yml', '')
    query_folder = (base_dir / "configs" / "queries" / config_stem).resolve()

    print(f"[RENAME] config_file={config_file}, config_path={config_path}, exists={config_path.exists()}")

    if not config_path.exists():
        flash(f"Config '{config_file}' not found", "error")
        return redirect(url_for("main.scheduler_admin"))

    if request.method == "POST":
        new_name = request.form.get("new_name", "").strip()
        if not new_name:
            flash("New name cannot be empty", "error")
            return redirect(url_for("main.scheduler_admin"))

        # Add .yaml extension if not provided
        if not new_name.endswith('.yaml') and not new_name.endswith('.yml'):
            new_name = new_name + '.yaml'

        new_path = (base_dir / "configs" / new_name).resolve()
        new_stem = new_name.replace('.yaml', '').replace('.yml', '')
        new_query_folder = (base_dir / "configs" / "queries" / new_stem).resolve()

        print(f"[RENAME] new_path={new_path}, new_stem={new_stem}")
        print(f"[RENAME] new_path exists={new_path.exists()}")

        if new_path.exists():
            flash(f"A config with name '{new_name}' already exists", "error")
            return redirect(url_for("main.scheduler_admin"))

        try:
            # Read the YAML content
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Update job names inside to match new config name
            jobs = data.get("jobs", [])
            jobs_to_update = []
            for job in jobs:
                old_job_name = job.get("name", "")
                if old_job_name == config_stem:
                    job["name"] = new_stem
                    jobs_to_update.append((old_job_name, new_stem))
                    print(f"[RENAME] updated job name: '{old_job_name}' -> '{new_stem}'")

            # Update job_name in Run history table for all renamed jobs
            for old_job_name, new_job_name in jobs_to_update:
                try:
                    from web.models import db, Run
                    updated = db.session.query(Run).filter(
                        Run.job_name == old_job_name
                    ).update({"job_name": new_job_name})
                    if updated > 0:
                        print(f"[RENAME] updated {updated} run history record(s)")
                except Exception as db_err:
                    print(f"[RENAME] warning: could not update run history: {db_err}")

            # Save content to new file
            with open(new_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
            print(f"[RENAME] wrote new file: {new_path}")

            # Remove old file - use os.remove for Windows compatibility
            if config_path.exists():
                os.remove(str(config_path))
                print(f"[RENAME] deleted old file: {config_path}")
            else:
                print(f"[RENAME] old file already gone: {config_path}")

            # Rename the query folder if it exists
            if query_folder.exists():
                shutil.move(str(query_folder), str(new_query_folder))

            flash(f"Config renamed to '{new_name}'", "success")
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash(f"Error renaming config: {e}", "error")

        return redirect(url_for("main.scheduler_admin"))

    # GET request - show rename form
    return render_template("config_rename.html", config_file=config_file)


# ------------------------------------------------------------------------------
# QUERY EDIT
# ------------------------------------------------------------------------------
@bp.route("/query/<name>", methods=["GET", "POST"])
def query_edit(name):
    """Edit query file for a job."""
    all_configs = get_all_configs_with_jobs()

    # Find job
    job = None
    config_file = None
    for config in all_configs:
        for j in config.get("jobs", []):
            if j.get("name") == name:
                job = j
                config_file = config.get("file")
                break

    if not job:
        flash(f"Job '{name}' not found", "error")
        return redirect(url_for("main.configs"))

    query_file = job.get("source", {}).get("query_file", "")

    if request.method == "POST":
        action = request.form.get("action", "save")
        content = request.form.get("query", "").strip()

        if action == "test":
            # Test query against source
            from core.db_client import run_query

            if not content:
                flash("No query provided", "error")
                return redirect(url_for("main.query_edit", name=name))

            try:
                source_type = job.get("source", {}).get("type", "sqlserver")
                df = run_query(source_type, content)

                row_count = len(df)
                sample = df.head(5).to_dict("records") if row_count > 0 else []

                return render_template(
                    "query_test.html",
                    title=f"Test: {name}",
                    job_name=name,
                    query=content,
                    sample=sample,
                    row_count=row_count,
                    columns=list(df.columns) if row_count > 0 else []
                )
            except Exception as e:
                flash(f"Query test failed: {str(e)}", "error")
                # Load current query for redisplay
                current_query = ""
                if query_file:
                    current_query = load_query(query_file)
                return render_template(
                    "query_editor.html",
                    title=f"Query: {name}",
                    job_name=name,
                    query_file=query_file,
                    query=current_query
                )

        # Save action
        if query_file:
            save_query(query_file, content)
        else:
            # Create new query file
            query_file = f"queries/{name}.sql"
            save_query(query_file, content)
            job["source"]["query_file"] = query_file
            save_job_config(job)

        flash(f"Query for '{name}' saved successfully", "success")
        return redirect(url_for("main.configs"))

    # Load current query - check both query_file and inline query
    current_query = ""
    query_file = job.get("source", {}).get("query_file", "")
    if query_file:
        current_query = load_query(query_file)
    else:
        # Also check for inline query
        current_query = job.get("source", {}).get("query", "")

    return render_template(
        "query_editor.html",
        title=f"Query: {name}",
        job_name=name,
        query_file=query_file,
        query=current_query
    )


# ------------------------------------------------------------------------------
# QUERIES LIST
# ------------------------------------------------------------------------------
@bp.route("/queries")
def queries():
    """Show all query files from jobs."""
    all_configs = get_all_configs_with_jobs()

    # Extract jobs with query files
    jobs_with_queries = []
    for config in all_configs:
        for job in config.get("jobs", []):
            query_file = job.get("source", {}).get("query_file")
            if query_file:
                jobs_with_queries.append({
                    "job": job.get("name"),
                    "query_file": query_file,
                    "config": config.get("file")
                })

    return render_template("queries.html", jobs_with_queries=jobs_with_queries)


# ------------------------------------------------------------------------------
# QUERIES LIST - Show all queries grouped by config
# ------------------------------------------------------------------------------
@bp.route("/queries/list")
def queries_list():
    """Show all query files grouped by config (like configs page)."""
    all_queries = get_all_queries_with_configs()

    # Filter if needed
    search_query = request.args.get("search", "").strip().lower()
    config_filter = request.args.get("config", "").strip()

    # Filter by config
    if config_filter:
        all_queries = [q for q in all_queries if q.get("config_file") == config_filter]

    # Filter by search query
    elif search_query:
        filtered_queries = []
        for q in all_queries:
            # Filter by config name
            if search_query in q.get("config_name", "").lower():
                filtered_queries.append(q)
            else:
                # Filter queries within config
                filtered_qs = [query for query in q.get("queries", []) if search_query in query.get("file", "").lower()]
                if filtered_qs:
                    q_copy = dict(q)
                    q_copy["queries"] = filtered_qs
                    filtered_queries.append(q_copy)
        all_queries = filtered_queries

    return render_template("queries_list.html", queries_by_config=all_queries)


# ------------------------------------------------------------------------------
# NEW QUERY
# ------------------------------------------------------------------------------
@bp.route("/queries/new/<config_name>", methods=["GET", "POST"])
def query_new(config_name):
    """Create new query file for a config."""
    sample_data = None
    test_error = None
    test_row_count = None
    test_columns = None

    if request.method == "POST":
        query_name = request.form.get("query_name", "").strip()
        query_content = request.form.get("query_content", "").strip()
        query_description = request.form.get("query_description", "").strip()
        connection_type = request.form.get("connection_type", "sqlserver")
        action = request.form.get("action", "save")

        if action == "test":
            # Test query against source
            if not query_content:
                test_error = "No query provided"
            else:
                try:
                    from core.db_client import run_query
                    df = run_query(connection_type, query_content)
                    test_row_count = len(df)
                    sample_data = df.head(5).to_dict("records") if test_row_count > 0 else []
                    test_columns = list(df.columns) if test_row_count > 0 else []
                    if test_row_count == 0:
                        test_error = "Query returned no results"
                except Exception as e:
                    test_error = str(e)
                    test_row_count = 0

            return render_template(
                "query_new.html",
                config_name=config_name,
                query_name=query_name,
                query_content=query_content,
                query_description=query_description,
                connection_type=connection_type,
                sample_data=sample_data,
                test_error=test_error,
                test_row_count=test_row_count,
                test_columns=test_columns
            )

        # Save action
        if query_name and query_content:
            # Ensure .sql extension
            if not query_name.endswith('.sql'):
                query_name = query_name + '.sql'

            save_query(query_name, query_content, config_name=config_name, description=query_description, connection_type=connection_type)
            flash(f"Query '{query_name}' created", "success")
            return redirect(url_for("main.queries_list"))
        else:
            flash("Query name and content are required", "error")

    return render_template("query_new.html", config_name=config_name, connection_type="sqlserver")


# ------------------------------------------------------------------------------
# EDIT QUERY FILE
# ------------------------------------------------------------------------------
@bp.route("/queries/edit/<config_name>/<query_file>", methods=["GET", "POST"])
def query_edit_file(config_name, query_file):
    """Edit query file SQL content."""
    sample_data = None
    test_error = None
    test_row_count = None
    test_columns = None

    # Load existing content and metadata
    from core.config_loader import load_query_metadata

    # Determine the correct path for the query file
    query_path = Path("configs") / "queries" / config_name / query_file
    if not query_path.exists():
        query_path = Path("configs") / "queries" / query_file

    content = load_query(query_file, config_name=config_name)
    existing_meta = load_query_metadata(query_path)
    existing_description = existing_meta.get("description", "")
    existing_connection_type = existing_meta.get("connection_type", "sqlserver")

    if request.method == "POST":
        query_content = request.form.get("query_content", "").strip()
        query_description = request.form.get("query_description", "").strip()
        connection_type = request.form.get("connection_type", "sqlserver")
        action = request.form.get("action", "save")

        if action == "test":
            if not query_content:
                test_error = "No query provided"
            else:
                try:
                    from core.db_client import run_query
                    df = run_query(connection_type, query_content)
                    test_row_count = len(df)
                    sample_data = df.head(5).to_dict("records") if test_row_count > 0 else []
                    test_columns = list(df.columns) if test_row_count > 0 else []
                    if test_row_count == 0:
                        test_error = "Query returned no results"
                except Exception as e:
                    test_error = str(e)
                    test_row_count = 0

            return render_template(
                "query_edit.html",
                config_name=config_name,
                query_file=query_file,
                content=query_content,
                query_description=query_description,
                connection_type=connection_type,
                sample_data=sample_data,
                test_error=test_error,
                test_row_count=test_row_count,
                test_columns=test_columns
            )

        # Save action
        save_query(query_file, query_content, config_name=config_name, description=query_description, connection_type=connection_type)
        flash(f"Query '{query_file}' saved", "success")
        return redirect(url_for("main.queries_list"))

    return render_template("query_edit.html", config_name=config_name, query_file=query_file, content=content, query_description=existing_description, connection_type=existing_connection_type)


# ------------------------------------------------------------------------------
# DELETE QUERY
# ------------------------------------------------------------------------------
@bp.route("/queries/delete/<config_name>/<query_file>")
def query_delete(config_name, query_file):
    """Delete a query file."""
    from core.config_loader import load_query
    # Try config-specific folder first
    config_path = Path("configs") / "queries" / config_name / query_file
    # Fall back to flat location
    flat_path = Path("configs") / "queries" / query_file

    deleted = False
    if config_path.exists():
        config_path.unlink()
        deleted = True
    elif flat_path.exists():
        flat_path.unlink()
        deleted = True

    if deleted:
        flash(f"Query '{query_file}' deleted", "success")
    else:
        flash(f"Query '{query_file}' not found", "error")

    return redirect(url_for("main.queries_list"))


# ------------------------------------------------------------------------------
# RUN PAGE
# ------------------------------------------------------------------------------
@bp.route("/run")
def run_page():
    """Run jobs page."""
    config_filter = request.args.get("config", "").strip()

    jobs_with_config = []

    all_configs = get_all_configs_with_jobs()
    for config in all_configs:
        # Apply config filter
        if config_filter and config.get("file") != config_filter:
            continue

        for job in config.get("jobs", []):
            if job.get("active", True):
                jobs_with_config.append({
                    "name": job.get("name"),
                    "schedule": job.get("schedule", "Manual"),
                    "config_file": config.get("file"),
                    "config_name": config.get("file").replace('.yaml', '').replace('.yml', ''),
                })

    return render_template("run.html", jobs=jobs_with_config, config_filter=config_filter)


# ------------------------------------------------------------------------------
# RUN JOB
# ------------------------------------------------------------------------------
@bp.route("/run/<config_file>/<name>")
def run_job(config_file, name):
    """Run a specific job on-demand, non-blocking."""
    all_configs = get_all_configs_with_jobs()

    # Find job
    job = None
    for config in all_configs:
        if config.get("file") == config_file:
            for j in config.get("jobs", []):
                if j.get("name") == name:
                    job = j
                    break

    if not job:
        flash(f"Job '{name}' not found", "error")
        config_filter = request.args.get("config", "").strip()
        if config_filter:
            return redirect(url_for("main.run_page", config=config_filter))
        return redirect(url_for("main.run_page"))

    session = g.get("session")

    # Create run record
    run = Run(job_name=name, status="running", trigger_type="manual")
    session.add(run)
    session.commit()
    run_id = run.id

    config_filter = request.args.get("config", "").strip()

    # Submit to background thread so UI stays responsive
    _running_manual_jobs[name] = {
        "status": "running",
        "progress": "Initializing...",
        "start_time": datetime.utcnow().isoformat(),
        "logs": ""
    }
    _manual_executor.submit(_run_job_async, run_id, job, name)

    flash(f"Job '{name}' started in background", "info")
    if config_filter:
        return redirect(url_for("main.history", config=config_filter, job=name))
    return redirect(url_for("main.history", job=name))


def _run_job_async(run_id, job, job_name):
    """Execute job in background thread without blocking the web server."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from pathlib import Path

    # Create our own database connection (SQLAlchemy sessions aren't thread-safe)
    db_path = Path("data/run_history.db")
    if not db_path.is_absolute():
        db_path = Path(__file__).parent.parent / "data" / "run_history.db"

    engine = create_engine(f"sqlite:///{db_path}", echo=False, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    def on_log(line):
        """Callback to update live logs in the running jobs tracker."""
        if job_name in _running_manual_jobs:
            _running_manual_jobs[job_name]["logs"] += line

    try:
        run = session.query(Run).filter_by(id=run_id).first()
        if not run:
            # Remove from running jobs
            _running_manual_jobs.pop(job_name, None)
            return

        # Update running jobs progress
        _running_manual_jobs[job_name]["progress"] = "Running job..."

        runner = JobRunner()
        row_count, logs = runner.run(job, on_log=on_log)
        run.status = "success"
        run.end_time = datetime.utcnow()
        run.rows_processed = row_count or 0
        run.logs = logs
        session.commit()

        # Update running jobs tracker
        _running_manual_jobs[job_name] = {
            "status": "completed",
            "progress": f"Completed: {row_count} rows",
            "start_time": _running_manual_jobs.get(job_name, {}).get("start_time", datetime.utcnow().isoformat()),
            "logs": logs
        }
    except Exception as e:
        if run:
            run.status = "failed"
            run.end_time = datetime.utcnow()
            run.error_message = str(e)
            session.commit()

        # Update running jobs tracker
        _running_manual_jobs[job_name] = {
            "status": "failed",
            "progress": f"Failed: {str(e)[:100]}",
            "start_time": _running_manual_jobs.get(job_name, {}).get("start_time", datetime.utcnow().isoformat()),
            "logs": str(e)
        }
    finally:
        session.close()

    # Remove from running jobs after a delay to allow UI to refresh
    import time
    time.sleep(5)
    _running_manual_jobs.pop(job_name, None)


# ------------------------------------------------------------------------------
# SCHEDULE
# ------------------------------------------------------------------------------
@bp.route("/schedule")
def schedule():
    """Schedule management page."""
    config_filter = request.args.get("config", "").strip()

    # Check if standalone scheduler daemon is running
    scheduler_running = False
    scheduled_jobs_count = 0
    try:
        from scheduler.daemon import SchedulerDaemon
        scheduler_running = SchedulerDaemon.is_running()
        if scheduler_running:
            status = SchedulerDaemon.get_status()
            scheduled_jobs_count = status.get("job_count", 0)
    except Exception:
        pass

    all_configs = get_all_configs_with_jobs()

    # Collect all jobs with schedule info
    jobs_with_schedule = []
    for config in all_configs:
        # Apply config filter
        if config_filter and config.get("file") != config_filter:
            continue

        for job in config.get("jobs", []):
            if job.get("schedule"):
                jobs_with_schedule.append({
                    "name": job.get("name"),
                    "schedule": job.get("schedule", ""),
                    "active": job.get("active", True),
                    "config_file": config.get("file"),
                    "config_name": config.get("file").replace('.yaml', '').replace('.yml', ''),
                })

    return render_template("schedule.html", jobs=jobs_with_schedule, scheduler_running=scheduler_running, scheduled_jobs_count=scheduled_jobs_count, config_filter=config_filter)


# ------------------------------------------------------------------------------
# SCHEDULE EDIT
# ------------------------------------------------------------------------------
@bp.route("/schedule/<config_file>/<name>", methods=["GET", "POST"])
def schedule_edit(config_file, name):
    """Edit job schedule."""
    all_configs = get_all_configs_with_jobs()

    # Find job
    job = None
    for config in all_configs:
        if config.get("file") == config_file:
            for j in config.get("jobs", []):
                if j.get("name") == name:
                    job = j
                    break

    if not job:
        flash(f"Job '{name}' not found", "error")
        config_filter = request.args.get("config", "").strip()
        if config_filter:
            return redirect(url_for("main.schedule", config=config_filter))
        return redirect(url_for("main.schedule"))

    if request.method == "POST":
        job["schedule"] = request.form.get("schedule", "")
        save_job_config(job)
        flash(f"Schedule for '{name}' updated", "success")
        config_filter = request.args.get("config", "").strip()
        if config_filter:
            return redirect(url_for("main.schedule", config=config_filter))
        return redirect(url_for("main.schedule"))

    return render_template(
        "schedule_edit.html",
        title=f"Schedule: {name}",
        job_name=name,
        schedule=job.get("schedule", "")
    )


# ------------------------------------------------------------------------------
# HISTORY
# ------------------------------------------------------------------------------
@bp.route("/history")
def history():
    """Run history page."""
    page = request.args.get("page", 1, type=int)
    per_page = 20
    job_filter = request.args.get("job", "")
    config_filter = request.args.get("config", "").strip()

    session = g.get("session")

    # Get all jobs for config filter
    all_configs = get_all_configs_with_jobs()
    config_jobs = {}
    for config in all_configs:
        for job in config.get("jobs", []):
            config_jobs[job.get("name")] = config.get("file")

    if job_filter:
        query = session.query(Run).filter(Run.job_name == job_filter)
    else:
        query = session.query(Run)

    # Apply config filter
    if config_filter:
        job_names_for_config = [name for name, cf in config_jobs.items() if cf == config_filter]
        # Apply filter - show only jobs from this config, or empty if no jobs
        query = query.filter(Run.job_name.in_(job_names_for_config)) if job_names_for_config else session.query(Run).filter(False)

    total = query.count()
    runs = query.order_by(Run.start_time.desc()).offset((page - 1) * per_page).limit(per_page).all()

    pages = (total + per_page - 1) // per_page
    has_prev = page > 1
    has_next = page < pages

    run_list = []
    for r in runs:
        run_list.append({
            "id": r.id,
            "job_name": r.job_name,
            "status": r.status,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "duration": r.duration,
            "rows_processed": r.rows_processed,
            "error_message": r.error_message,
            "logs": getattr(r, "logs", None),
            "config_file": config_jobs.get(r.job_name, ""),
            "trigger_type": r.trigger_type,
        })

    return render_template("history.html", runs=run_list, page=page, pages=pages, has_prev=has_prev, has_next=has_next, job_filter=job_filter, config_filter=config_filter)


# ------------------------------------------------------------------------------
# SCHEDULER CONTROL (Standalone Daemon)
# ------------------------------------------------------------------------------
@bp.route("/scheduler/start", methods=["POST"])
def scheduler_start():
    """Start the standalone scheduler daemon."""
    try:
        from scheduler.daemon import SchedulerDaemon
        import subprocess
        import sys

        if SchedulerDaemon.is_running():
            flash("Scheduler is already running", "info")
        else:
            # Start scheduler as a separate process
            subprocess.Popen(
                [sys.executable, "-m", "scheduler.daemon"],
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            flash("Scheduler started", "success")
    except Exception as e:
        import traceback
        flash(f"Failed to start scheduler: {str(e)}", "error")
        traceback.print_exc()
    config_filter = request.args.get("config", "").strip()
    if config_filter:
        return redirect(url_for("main.schedule", config=config_filter))
    return redirect(url_for("main.schedule"))


@bp.route("/scheduler/stop", methods=["POST"])
def scheduler_stop():
    """Stop the standalone scheduler daemon."""
    try:
        from scheduler.daemon import SchedulerDaemon

        if SchedulerDaemon.stop_daemon():
            flash("Scheduler stopped", "success")
        else:
            flash("Scheduler is not running", "info")
    except Exception as e:
        flash(f"Failed to stop scheduler: {str(e)}", "error")
    config_filter = request.args.get("config", "").strip()
    if config_filter:
        return redirect(url_for("main.schedule", config=config_filter))
    return redirect(url_for("main.schedule"))


@bp.route("/scheduler/reload", methods=["POST"])
def scheduler_reload():
    """Reload scheduler with current jobs."""
    try:
        from scheduler.daemon import SchedulerDaemon

        if SchedulerDaemon.send_command("reload"):
            flash("Scheduler reload command sent", "success")
        else:
            flash("Scheduler is not running", "info")
    except Exception as e:
        flash(f"Failed to reload scheduler: {str(e)}", "error")
    config_filter = request.args.get("config", "").strip()
    if config_filter:
        return redirect(url_for("main.schedule", config=config_filter))
    return redirect(url_for("main.schedule"))


# ------------------------------------------------------------------------------
# SCHEDULER STATUS API (for health checks / CLI)
# ------------------------------------------------------------------------------
@bp.route("/api/scheduler/status")
def scheduler_status():
    """Return scheduler status as JSON."""
    from scheduler.daemon import SchedulerDaemon
    from flask import jsonify
    status = SchedulerDaemon.get_status()
    status["running"] = SchedulerDaemon.is_running()
    return jsonify(status)


@bp.route("/api/scheduler/running-jobs")
def scheduler_running_jobs():
    """Return currently running jobs with their progress and logs."""
    from scheduler.daemon import SchedulerDaemon
    from flask import jsonify
    status = SchedulerDaemon.get_status()

    # Merge scheduler running jobs with manual running jobs
    all_running = dict(status.get("running_jobs", {}))
    all_running.update(_running_manual_jobs)

    return jsonify({
        "running": all_running,
        "scheduler_running": SchedulerDaemon.is_running()
    })


@bp.route("/api/logs/<job_name>")
def api_logs(job_name):
    """Return live logs for a running job by job name."""
    from scheduler.daemon import SchedulerDaemon

    status = SchedulerDaemon.get_status()
    running_jobs = status.get("running_jobs", {})

    # Check scheduler running jobs
    if job_name in running_jobs:
        return jsonify({
            "job_name": job_name,
            "status": running_jobs[job_name].get("status"),
            "progress": running_jobs[job_name].get("progress"),
            "logs": running_jobs[job_name].get("logs"),
            "start_time": running_jobs[job_name].get("start_time"),
        })

    # Check manual running jobs
    if job_name in _running_manual_jobs:
        return jsonify({
            "job_name": job_name,
            "status": _running_manual_jobs[job_name].get("status"),
            "progress": _running_manual_jobs[job_name].get("progress"),
            "logs": _running_manual_jobs[job_name].get("logs"),
            "start_time": _running_manual_jobs[job_name].get("start_time"),
        })

    return jsonify({"job_name": job_name, "status": "not_found", "logs": ""})


# ------------------------------------------------------------------------------
# SCHEDULER ADMIN
# ------------------------------------------------------------------------------
@bp.route("/admin/scheduler")
def scheduler_admin():
    """Scheduler admin page - show status and controls and config management."""
    import os
    from pathlib import Path
    from sqlalchemy import func

    # Scheduler info (from standalone daemon)
    try:
        from scheduler.daemon import SchedulerDaemon
        is_running = SchedulerDaemon.is_running()
        status = SchedulerDaemon.get_status()
        jobs = status.get("jobs", [])

        job_list = []
        for job in jobs:
            job_list.append({
                "name": job.get("name", ""),
                "id": job.get("id", ""),
                "next_run": job.get("next_run", "N/A"),
                "trigger": job.get("trigger", ""),
            })
    except Exception as e:
        is_running = False
        job_list = []
        error_msg = str(e)

    # Config admin info
    configs_dir = Path("configs")
    config_files = []
    for f in sorted(configs_dir.glob("*.y*ml")):
        # Count jobs
        try:
            import yaml
            with open(f, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file) or {}
            job_count = len(data.get("jobs", []))
        except:
            job_count = 0

        # Count queries
        config_name = f.stem
        query_count = len(list((configs_dir / "queries" / config_name).glob("*.sql"))) if (configs_dir / "queries" / config_name).exists() else 0

        config_files.append({
            "name": f.name,
            "path": str(f),
            "created": f.stat().st_ctime,
            "job_count": job_count,
            "query_count": query_count,
        })

    # Timezone info
    from core.timezone import get_timezone, list_timezones, format_dt
    current_tz = get_timezone()
    all_timezones = list_timezones()

    # Get last run info for each job
    session = g.get("session")
    last_runs = {}
    if session:
        subq = session.query(
            Run.job_name,
            func.max(Run.start_time).label("max_start")
        ).group_by(Run.job_name).subquery()

        runs = session.query(Run).join(
            subq,
            (Run.job_name == subq.c.job_name) & (Run.start_time == subq.c.max_start)
        ).all()

        for r in runs:
            last_runs[r.job_name] = {
                "status": r.status,
                "end_time": r.end_time,
            }

    # Attach last run to each job and convert next_run time to user timezone
    for job in job_list:
        job_name = job.get("name", "")
        job["last_run"] = last_runs.get(job_name)

        # Convert next_run time from string to datetime and format in user timezone
        next_run_str = job.get("next_run", "N/A")
        if next_run_str and next_run_str != "N/A":
            try:
                from datetime import datetime
                from dateutil import parser as dateutil_parser

                # Parse the next_run time (it includes timezone info like +03:30)
                next_run_dt = dateutil_parser.parse(next_run_str)

                # Format in user's timezone
                job["next_run_formatted"] = format_dt(next_run_dt)
            except Exception:
                job["next_run_formatted"] = next_run_str
        else:
            job["next_run_formatted"] = "N/A"

    return render_template("scheduler_admin.html",
                         is_running=is_running,
                         jobs=job_list,
                         error_msg=error_msg if 'error_msg' in locals() else None,
                         config_files=config_files,
                         current_timezone=current_tz,
                         timezones=all_timezones)


# ------------------------------------------------------------------------------
# SCHEDULER LOGS (static last 300 lines)
# ------------------------------------------------------------------------------
@bp.route("/admin/scheduler/logs")
def scheduler_logs():
    """Return scheduler logs as text/plain."""
    from scheduler.daemon import SchedulerDaemon
    from scheduler import LOG_FILE as SCHEDULER_LOG
    log_path = SCHEDULER_LOG
    if not log_path.exists():
        logs = "No scheduler logs yet."
    else:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            logs = "".join(all_lines[-300:])
    from flask import Response
    return Response(logs, mimetype="text/plain")


# ------------------------------------------------------------------------------
# SCHEDULER LIVE LOGS (SSE stream)
# ------------------------------------------------------------------------------
@bp.route("/admin/scheduler/logs/live")
def scheduler_logs_live():
    """Stream scheduler logs in real-time via Server-Sent Events."""
    from flask import Response, stream_with_context
    from scheduler import LOG_FILE as SCHEDULER_LOG
    import time

    log_path = SCHEDULER_LOG

    def follow_log():
        if not log_path.exists():
            yield "data: No scheduler logs yet.\n\n"
            return

        with open(log_path, "r", encoding="utf-8") as f:
            # Go to end of file
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                yield f"data: {line}\n\n"

    return Response(
        stream_with_context(follow_log()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ------------------------------------------------------------------------------
# TIMEZONE UPDATE
# ------------------------------------------------------------------------------
@bp.route("/admin/timezone", methods=["POST"])
def timezone_update():
    """Update application timezone."""
    from core.timezone import set_timezone, get_timezone_obj
    from core.scheduler import get_job_scheduler

    new_tz = request.form.get("timezone", "").strip()
    if not new_tz:
        flash("Timezone is required", "error")
        return redirect(url_for("main.scheduler_admin"))

    try:
        # Validate timezone
        from zoneinfo import ZoneInfo
        ZoneInfo(new_tz)
    except Exception:
        try:
            import pytz
            pytz.timezone(new_tz)
        except Exception:
            flash(f"Invalid timezone: {new_tz}", "error")
            return redirect(url_for("main.scheduler_admin"))

    set_timezone(new_tz)

    # Restart standalone scheduler daemon with new timezone if running
    from scheduler.daemon import SchedulerDaemon
    if SchedulerDaemon.is_running():
        SchedulerDaemon.stop_daemon()
        # Wait a moment for process to die
        import time
        time.sleep(1)
        # Start new daemon process (it will pick up new timezone)
        import subprocess
        import sys
        subprocess.Popen(
            [sys.executable, "-m", "scheduler.daemon"],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        flash(f"Timezone updated to {new_tz}. Scheduler restarted.", "success")
    else:
        flash(f"Timezone updated to {new_tz}", "success")

    return redirect(url_for("main.scheduler_admin"))


# ------------------------------------------------------------------------------
# HEALTH CHECK
# ------------------------------------------------------------------------------
@bp.route("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}