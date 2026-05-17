# Fetrak — Data Automation Platform

> A YAML-driven ETL automation platform for scheduling SQL queries, generating Excel reports, and uploading to SharePoint — with a Flask web UI and a self-contained background scheduler.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Overview

**Fetrak** lets you define data extraction jobs in plain YAML files — no code changes required to add, modify, or schedule new reports. It connects to SQL Server or ClickHouse, processes the results into Excel files, and uploads them to SharePoint on a cron schedule. A Flask web UI provides full management and monitoring.

**What makes it different:**
- **Independent Scheduler** — a standalone daemon process that handles concurrent jobs in parallel (`ThreadPoolExecutor`), fully decoupled from the Flask web UI. Survives user logoff and auto-starts on boot via Windows Service.
- **SharePoint-first** — currently designed around SharePoint as the primary destination, with built-in NTLM authentication, folder creation, file locking/retry, and permission management.
- **AI-assisted development** — AI was involved across every layer and phase of this project: the core ETL pipeline, the independent scheduler daemon, the web UI (templates, CSS, JavaScript), deployment, and rapid debugging. This dramatically reduced development and error-fix time at every step.
- **Extensible by design** — the YAML config format makes it trivial to add new job types; the roadmap includes support for more database sources, cloud storage destinations (S3, Google Drive), and alerting pipelines.

**Use cases:**
- Automating recurring BI reports from SQL databases to SharePoint
- Scheduling nightly data extracts with date-partitioned Excel outputs
- Centralizing report generation without scattered Excel macros

---

## Features

| Feature | Description |
|---------|-------------|
| **YAML-first jobs** | Add a job by writing one YAML file — no Python required |
| **Multi-database** | SQL Server and ClickHouse supported as data sources |
| **Scheduling** | Cron-based scheduling via APScheduler |
| **SharePoint integration** | Auto-upload Excel files to SharePoint — NTLM auth, folder creation, file locking/retry, owner permissions |
| **Independent scheduler** | Standalone daemon with `ThreadPoolExecutor` for parallel job execution, decoupled from Flask |
| **Windows Service** | Auto-start on boot, survives user logoff |
| **Web UI (Flask)** | Config editor, query editor with live test results, schedule view, run history with live logs, scheduler admin |
| **AI-built UI** | Web interface and templates created with AI assistance (Claude) for clean UX |
| **Run history** | SQLite-backed execution log with terminal output capture and error details |
| **Dynamic filenames** | `{YYYY_MM_DD}`, `{YYYY_MM}` date placeholders in output filenames |

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/dgeravand/Fetrak_Data_Automation.git
cd Fetrak_Data_Automation

python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Then edit .env with your database and SharePoint credentials
```

**`.env.example` template:**

```env
# SQL Server
SQLSERVER_HOST=localhost
SQLSERVER_DB=master
SQLSERVER_USER=sa
SQLSERVER_PASSWORD=

# ClickHouse
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_DB=default
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=

# SharePoint
SP_SITE_URL=https://your-sharepoint-site.com/sites/your-site
SP_USERNAME=your_user
SP_PASSWORD=
SP_MAX_RETRIES=12
SP_RETRY_DELAY=300
```

### 3. Create a Job

Create a YAML config file in `configs/`:

```yaml
# configs/MyReports.yaml
jobs:
  - name: "Daily Sales Report"
    active: true
    schedule: "0 8 * * *"           # Every day at 8:00 AM
    source:
      type: "clickhouse"           # or "sqlserver"
      query_file: "MyReports/DailySales.sql"
    output:
      file:
        name: "Sales_{YYYY_MM_DD}.xlsx"
        write_mode: "replace"      # "append" or "replace"
        sheet:
          name: "Sheet1"
      sharepoint:
        library: "Shared Documents"
        folder: "/Reports"
    owners:
      - "team@company.com"
```

Place the SQL query file at `configs/queries/MyReports/DailySales.sql`:

```sql
SELECT
    date,
    region,
    SUM(revenue) AS total_revenue
FROM sales
WHERE date >= today() - 7
GROUP BY date, region
ORDER BY date DESC
```

### 4. Run

```bash
# Start the web UI
python -m web.app

# Open http://localhost:5000
```

Or run a specific job from the command line:

```bash
python main.py "Daily Sales Report"
```

### 5. Deploy on Windows Server

```powershell
# Create and activate venv
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# Install as Windows Service (run as Administrator)
python scheduler\service.py install

# Start the service
python scheduler\service.py start

# Check status
python -c "from scheduler.daemon import SchedulerDaemon; print(SchedulerDaemon.get_status())"
```

---

## Project Structure

```
Fetrak_Data_Automation/
├── configs/                 # Job configuration files (YAML)
│   ├── *.yaml             # One config file per report group
│   └── queries/           # SQL query files
│       └── <config>/      # .sql files referenced by YAML
├── core/                   # Core ETL modules
│   ├── config_loader.py    # YAML loading/saving
│   ├── db_client.py        # SQL Server & ClickHouse connections
│   ├── excel_manager.py   # Excel file generation
│   ├── job_runner.py      # Job pipeline orchestration
│   └── sharepoint_client.py  # SharePoint REST API client
├── web/                    # Flask web application
│   ├── app.py             # Flask entry point
│   ├── routes.py         # HTTP route handlers
│   ├── models.py         # SQLAlchemy run history models
│   ├── forms.py          # WTForms
│   └── templates/        # Jinja2 HTML templates
├── scheduler/             # Background scheduler
│   ├── daemon.py         # APScheduler daemon with ThreadPoolExecutor
│   └── service.py       # Windows Service wrapper
├── main.py               # CLI entry point
├── requirements.txt
├── .env.example          # Environment variable template
├── LICENSE
├── CONTRIBUTING.md
└── CHANGELOG.md
```

---

## Cron Format

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6)
* * * * *
```

**Examples:**
| Expression | Meaning |
|------------|---------|
| `0 8 * * *` | Daily at 8:00 AM |
| `0 8 * * 1-5` | Weekdays at 8:00 AM |
| `0 0 1 * *` | Monthly on the 1st |
| `30 16 * * *` | Every day at 4:30 PM |

---

## Supported Data Sources

| Direction | Type | Details |
|-----------|------|---------|
| **Source** | SQL Server | via `pyodbc` |
| **Source** | ClickHouse | via `clickhouse-connect` |
| **Destination** | SharePoint | REST API with NTLM authentication, file locking, retry logic, permission management |

---

## Architecture Highlights

### Independent Scheduler

The scheduler daemon (`scheduler/daemon.py`) runs as a **completely separate process** from the Flask web UI. It uses a `ThreadPoolExecutor` (configurable max workers) to run multiple jobs in parallel, handles graceful shutdown, writes status to a JSON file for the UI to read, and communicates via PID/command files — no shared memory required.

### AI-Assisted Development

AI played a role across **every layer and phase** of this project — not just the UI:

- **Core / Backend logic** — AI helped design the job runner pipeline, database client adapters (SQL Server + ClickHouse), the SharePoint REST API client with NTLM auth, Excel manager, and YAML config loader
- **Scheduler** — AI helped architect the standalone daemon process, `ThreadPoolExecutor` for parallel execution, PID/status/heartbeat file communication, Windows Service wrapper, and graceful shutdown on SIGTERM/SIGINT
- **Web UI** — AI built the HTML templates, CSS styling, JavaScript for live log streaming via SSE, real-time job progress callbacks, inline query testing with sample result previews, and scheduler health monitoring
- **Deployment** — AI helped with Windows Service setup, cron scheduling design, `.env` configuration patterns, and server automation scripts
- **Debugging & iteration** — AI dramatically reduced the time to debug and resolve issues across all layers: SQLAlchemy threading in background jobs, SharePoint NTLM authentication edge cases, file locking/retry logic, APScheduler cron trigger behavior, and Windows Service process management

The result: a production-ready, multi-layer system built in a fraction of the traditional time — and a codebase that any developer can understand, maintain, and extend quickly.

### SharePoint Integration

Current destination integration is built around **SharePoint**:
- NTLM authentication via `requests_ntlm2`
- Auto-creates nested folder paths
- Handles file locks with configurable retry (max retries + exponential backoff)
- Sets file ownership permissions via SharePoint REST API
- Generates view links after upload

---

## Roadmap

Planned expansions (contributions welcome):

- [ ] **More database sources** — PostgreSQL, MySQL, BigQuery, Snowflake
- [ ] **More destinations** — S3, Google Drive, OneDrive, Azure Blob Storage
- [ ] **Alerting pipeline** — email/Slack notifications on job failure
- [ ] **Multi-user support** — authentication and per-user job ownership
- [ ] **Metrics dashboard** — charts for run success rates, row counts, durations
- [ ] **Job chaining** — trigger downstream jobs on upstream success
- [ ] **User managment**
---

## Author

**Davood Geravand**  
[GitHub](https://github.com/dgeravand/Fetrak_Data_Automation)

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines, then open a Pull Request.