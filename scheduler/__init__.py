# ------------------------------------------------------------------------------
# SCHEDULER MODULE
# ------------------------------------------------------------------------------
# Standalone scheduler package. All scheduler-related files live here.
# ------------------------------------------------------------------------------
from pathlib import Path

# Module paths
MODULE_DIR = Path(__file__).parent
DATA_DIR = MODULE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PID_FILE = DATA_DIR / "scheduler.pid"
STATUS_FILE = DATA_DIR / "scheduler_status.json"
LOG_FILE = DATA_DIR / "scheduler.log"
CMD_FILE = DATA_DIR / "scheduler.cmd"
HEARTBEAT_FILE = DATA_DIR / "scheduler.heartbeat"
