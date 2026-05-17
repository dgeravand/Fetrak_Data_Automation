# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] - 2024-05-17

### Added

- **Job Configuration System** — Define ETL jobs entirely in YAML files. No code changes needed to add or modify jobs.
- **Multi-Database Support** — Connect to Microsoft SQL Server or ClickHouse as data sources.
- **Independent Scheduler** — Standalone daemon process using APScheduler with `ThreadPoolExecutor` for parallel job execution. Fully decoupled from Flask; survives logoff and auto-starts via Windows Service.
- **SharePoint Integration** — Upload generated Excel files to SharePoint via REST API with NTLM authentication. Features: nested folder creation, file locking detection with retry, owner permission management, view link generation.
- **AI-Assisted Development** — AI was involved across every layer and phase of the project: the core ETL pipeline, the independent scheduler daemon, the Flask web UI (templates, CSS, JavaScript for live log streaming, real-time progress, SSE), deployment setup, and rapid debugging/iteration. This dramatically reduced development time and time-to-fix errors at every layer.
- **Excel Export** — Generate `.xlsx` files using `openpyxl`, with support for append and replace write modes.
- **Dynamic Filenames** — Use date placeholders (`{YYYY_MM_DD}`, `{YYYY_MM}`) in output filenames.
- **Windows Service Deployment** — Install the scheduler as a Windows Service for automatic startup on boot and survival across user logoffs.
- **Run History Tracking** — SQLite-backed run history with status, trigger type (manual/scheduled), row counts, and captured logs.
- **SharePoint Permission Management** — Set file ownership directly from YAML config using SharePoint `ensureuser` and role assignment APIs.
- **Future-Ready Architecture** — YAML-first design makes it straightforward to add new source types, destinations, and alerting pipelines.

### Core Modules

| Module | Purpose |
|--------|---------|
| `core/job_runner.py` | Orchestrates the full ETL pipeline |
| `core/config_loader.py` | Loads and saves YAML job configs and SQL queries |
| `core/db_client.py` | Manages SQL Server and ClickHouse connections |
| `core/excel_manager.py` | Handles Excel file creation and updates |
| `core/sharepoint_client.py` | SharePoint REST API client — upload, permissions, folder creation |
| `scheduler/daemon.py` | Standalone APScheduler daemon with parallel execution |
| `scheduler/service.py` | Windows Service wrapper for the daemon |
| `web/app.py` | Flask application entry point |
| `web/routes.py` | All HTTP routes and job execution handlers |