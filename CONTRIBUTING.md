# Contributing to Fetrak

Thank you for your interest in contributing to Fetrak! This guide will help you get started.

---

## Getting Started

### Prerequisites

- Python 3.10 or higher
- `pip`

### Local Setup

```bash
# 1. Fork the repository on GitHub

# 2. Clone your fork
git clone https://github.com/dgeravand/Fetrak_Data_Automation
cd Fetrak_Data_Automation

# 3. Create a virtual environment
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Copy environment template and configure
cp .env.example .env
# Then edit .env with your local database credentials
```

### Running the Application

```bash
# Web UI (Flask)
python -m web.app

# Or run a specific job from the command line
python main.py "JobName"
```

---

## Project Structure

```
Fetrak_Data_Automation/
├── configs/              # Job configuration files (YAML)
├── core/                 # Core pipeline modules
│   ├── job_runner.py     # Main job orchestration
│   ├── db_client.py      # SQL Server & ClickHouse connections
│   ├── config_loader.py  # YAML config loading
│   ├── sharepoint_client.py  # SharePoint upload
│   └── excel_manager.py # Excel file operations
├── web/                  # Flask web interface
│   ├── routes.py        # All web routes
│   ├── templates/       # Jinja2 HTML templates
│   └── models.py        # SQLAlchemy run history models
├── scheduler/           # Background scheduler
│   ├── daemon.py        # APScheduler daemon
│   └── service.py       # Windows service wrapper
├── main.py             # CLI entry point
└── requirements.txt
```

---

## Making Changes

### Workflow

1. **Fork** the repository
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Make your changes** — add tests if applicable
4. **Commit** with a clear message:
   ```
   git commit -m "Add: support for PostgreSQL source type"
   ```
5. **Push** to your fork:
   ```
   git push origin feature/your-feature-name
   ```
6. Open a **Pull Request** on GitHub

### Code Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use meaningful variable and function names
- Add docstrings for public functions
- Keep functions focused — one responsibility per function

### Commit Message Format

Use one of these prefixes:

| Prefix | Use case |
|--------|----------|
| `Add:` | New feature or capability |
| `Fix:` | Bug fix |
| `Refactor:` | Code restructure without behavior change |
| `Docs:` | Documentation only |
| `Chore:` | Maintenance, dependencies, tooling |

---

## Adding a New Job

Jobs are defined entirely in YAML — no code changes needed.

```yaml
# configs/MyConfig.yaml
jobs:
  - name: "My New Report"
    active: true
    schedule: "0 8 * * *"       # Cron: daily at 8:00 AM
    source:
      type: "clickhouse"       # or "sqlserver"
      query_file: "MyConfig/MyReport.sql"
    output:
      file:
        name: "Report_{YYYY_MM_DD}.xlsx"
        write_mode: "append"   # or "replace"
        sheet:
          name: "Sheet1"
      sharepoint:
        library: "Shared Documents"
        folder: "/Reports"
    owners:
      - "your@email.com"
```

Place your SQL query at: `configs/queries/MyConfig/MyReport.sql`

---

## Testing

```bash
# Run a job manually to verify your setup
python main.py "YourJobName"

# Check the Flask web UI at http://localhost:5000
```

---

## Reporting Issues

Please report bugs via [GitHub Issues](https://github.com/dgeravand/Fetrak_Data_Automation/issues). Include:

- Python version
- Steps to reproduce
- Expected vs actual behavior
- Full error traceback if applicable

---

## Questions?

Feel free to open a Discussion on the GitHub repository or reach out to the maintainers.