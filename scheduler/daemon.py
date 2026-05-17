# ------------------------------------------------------------------------------
# SCHEDULER DAEMON
# ------------------------------------------------------------------------------
# Standalone scheduler process that runs independently of Flask.
# Uses APScheduler BackgroundScheduler in its own process.
# Communicates via PID file and status JSON file.
# ------------------------------------------------------------------------------
import json
import logging
import os
import signal
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scheduler import DATA_DIR, PID_FILE, STATUS_FILE, LOG_FILE, CMD_FILE, HEARTBEAT_FILE
from core.config_loader import get_all_configs_with_jobs
from core.job_runner import JobRunner
from core.timezone import get_timezone_obj
from web.models import Run

# Logging setup - only configure our logger, don't override root
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
file_handler.setFormatter(formatter)

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
logger.handlers = []
logger.addHandler(file_handler)
logger.propagate = False


class SchedulerDaemon:
    """Standalone scheduler daemon."""

    def __init__(self):
        tz = get_timezone_obj()
        self.scheduler = BackgroundScheduler(timezone=tz)
        self.runner = JobRunner()
        self.running = False
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.running_jobs = {}  # Track running jobs: {job_name: {"status": ..., "progress": ..., "start_time": ...}}
        self._job_lock = threading.Lock()
        logger.info(f"SchedulerDaemon initialized with timezone: {tz}")

    def load_jobs_from_config(self):
        """Load jobs from config files and add them to scheduler."""
        try:
            self.scheduler.remove_all_jobs()
            logger.info("Cleared all existing jobs")
        except Exception:
            pass

        logger.info("Loading jobs from config...")
        all_configs = get_all_configs_with_jobs()
        logger.info(f"Found {len(all_configs)} config files")

        jobs_added = 0
        for config in all_configs:
            config_file = config.get("file", "unknown")
            logger.info(f"Processing config: {config_file}")

            for job in config.get("jobs", []):
                job_name = job.get("name", "")
                schedule = job.get("schedule", "")
                active = job.get("active", True)

                logger.info(f"  Job: {job_name}, schedule: '{schedule}', active: {active}")

                if active and schedule:
                    try:
                        if isinstance(schedule, str):
                            trigger = CronTrigger.from_crontab(schedule)
                        elif isinstance(schedule, dict):
                            trigger = CronTrigger(**schedule)
                        else:
                            logger.warning(f"Invalid schedule format for {job_name}: {schedule}")
                            continue

                        self.scheduler.add_job(
                            self.run_job,
                            trigger,
                            args=[job],
                            id=job_name,
                            name=job_name,
                            replace_existing=True
                        )
                        logger.info(f"    -> Added job: {job_name} with schedule: {schedule}")
                        jobs_added += 1
                    except Exception as e:
                        logger.error(f"    -> Failed to add job {job_name}: {e}")

        logger.info(f"Total jobs added to scheduler: {jobs_added}")
        return jobs_added

    def run_job(self, job):
        """Run a job in background thread and record history."""
        # Run job in background thread to keep scheduler responsive
        self.executor.submit(self._run_job_internal, job)

    def _run_job_internal(self, job):
        """Internal method that actually runs the job (can block)."""
        job_name = job.get("name", "unknown")

        # Update running jobs tracking
        with self._job_lock:
            self.running_jobs[job_name] = {
                "status": "running",
                "progress": "Initializing...",
                "start_time": datetime.utcnow().isoformat(),
                "logs": ""
            }

        logger.info(f"Running scheduled job: {job_name}")
        self._update_job_progress(job_name, "Running job...")

        engine = create_engine("sqlite:///data/run_history.db", echo=False, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        run = Run(job_name=job_name, status="running", trigger_type="scheduled")
        session.add(run)
        session.commit()

        try:
            self._update_job_progress(job_name, "Fetching data from database...")
            row_count, logs = self.runner.run(job)
            run.status = "success"
            run.end_time = datetime.utcnow()
            run.rows_processed = row_count or 0
            run.logs = logs
            session.commit()

            with self._job_lock:
                if job_name in self.running_jobs:
                    self.running_jobs[job_name]["status"] = "completed"
                    self.running_jobs[job_name]["progress"] = f"Completed: {row_count} rows"
                    self.running_jobs[job_name]["logs"] = logs

            logger.info(f"Job {job_name} completed: {row_count} rows")
            self._update_job_progress(job_name, f"Completed: {row_count} rows")
        except Exception as e:
            run.status = "failed"
            run.end_time = datetime.utcnow()
            run.error_message = str(e)
            session.commit()

            with self._job_lock:
                if job_name in self.running_jobs:
                    self.running_jobs[job_name]["status"] = "failed"
                    self.running_jobs[job_name]["progress"] = f"Failed: {str(e)[:100]}"
                    self.running_jobs[job_name]["logs"] = logs

            logger.error(f"Error running job {job_name}: {e}")
            self._update_job_progress(job_name, f"Failed: {str(e)[:100]}")
        finally:
            session.close()

        self._write_status()

    def _update_job_progress(self, job_name, progress):
        """Update the progress of a running job."""
        with self._job_lock:
            if job_name in self.running_jobs:
                self.running_jobs[job_name]["progress"] = progress
        self._write_status()

    def _write_status(self):
        """Write current status to status file."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "name": job.name,
                "id": job.id,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger) if job.trigger else "",
            })

        # Get running jobs
        with self._job_lock:
            running_jobs = dict(self.running_jobs)

        status = {
            "running": self.scheduler.running,
            "job_count": len(jobs),
            "jobs": jobs,
            "running_jobs": running_jobs,
            "updated_at": datetime.utcnow().isoformat(),
        }
        try:
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to write status: {e}")

    def _write_pid(self):
        """Write PID file."""
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))

    def _remove_pid(self):
        """Remove PID file."""
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass

    def _check_commands(self):
        """Check for command file and execute commands."""
        if not CMD_FILE.exists():
            return
        try:
            cmd = CMD_FILE.read_text(encoding="utf-8").strip()
            CMD_FILE.unlink()
            if cmd == "reload":
                logger.info("Received reload command")
                self.load_jobs_from_config()
                self._write_status()
            elif cmd == "stop":
                logger.info("Received stop command")
                self.stop()
        except Exception as e:
            logger.error(f"Error processing command: {e}")

    def _get_config_mtime(self):
        """Get the most recent modification time of any config file."""
        configs_dir = Path("configs")
        if not configs_dir.exists():
            return 0
        max_mtime = 0
        for f in configs_dir.glob("*.y*ml"):
            try:
                mtime = f.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
            except OSError:
                pass
        return max_mtime

    def start(self):
        """Start the daemon."""
        if self.running:
            logger.info("Scheduler is already running")
            return

        # Check if another instance is running
        if PID_FILE.exists():
            try:
                old_pid = int(PID_FILE.read_text().strip())
                if self._is_process_running(old_pid):
                    logger.warning(f"Another scheduler instance is running (PID: {old_pid})")
                    return
            except (ValueError, OSError):
                pass

        self._write_pid()
        job_count = self.load_jobs_from_config()
        logger.info(f"Loaded {job_count} jobs, starting scheduler...")

        self.scheduler.start()
        self.running = True
        self._write_status()
        logger.info("Scheduler started successfully")

        # Track config file modification times for auto-reload
        last_config_mtime = self._get_config_mtime()

        # Keep the process alive
        # When running as Windows service, no Flask heartbeat is expected.
        is_windows_service = getattr(sys, 'frozen', False) or 'SERVICEMANAGER' in os.environ.get('_NT_SERVICE_NAME', '')
        heartbeat_timeout = 30  # Stop if no heartbeat from Flask in 30 seconds
        try:
            while self.running:
                self._check_commands()

                # Check Flask heartbeat only when NOT running as a service
                if not is_windows_service:
                    if HEARTBEAT_FILE.exists():
                        try:
                            heartbeat_time = float(HEARTBEAT_FILE.read_text().strip())
                            if time.time() - heartbeat_time > heartbeat_timeout:
                                logger.info("No heartbeat from Flask, stopping scheduler...")
                                self.stop()
                                break
                        except (ValueError, OSError):
                            pass
                    else:
                        # No heartbeat file yet, wait for Flask to start
                        pass

                # Auto-reload if config files changed
                current_mtime = self._get_config_mtime()
                if current_mtime > last_config_mtime:
                    logger.info("Config files changed, auto-reloading jobs...")
                    self.load_jobs_from_config()
                    last_config_mtime = current_mtime

                self._write_status()
                time.sleep(2)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            self.stop()

    def stop(self):
        """Stop the daemon, marking any running jobs as failed."""
        logger.info("Stopping scheduler...")
        self.running = False
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)

        # Mark all running jobs as failed (scheduler is stopping)
        self._mark_all_running_jobs_failed("Scheduler stopped while job was running")
        self._remove_pid()
        self._write_status()
        logger.info("Scheduler stopped")

    def _mark_all_running_jobs_failed(self, reason):
        """Mark all jobs currently in 'running' state as failed."""
        if not self.running_jobs:
            return
        try:
            engine = create_engine("sqlite:///data/run_history.db", echo=False, connect_args={"check_same_thread": False})
            SessionLocal = sessionmaker(bind=engine)
            session = SessionLocal()
            try:
                from datetime import datetime
                for job_name in list(self.running_jobs.keys()):
                    runs = session.query(Run).filter(
                        Run.job_name == job_name,
                        Run.status == "running"
                    ).order_by(Run.start_time.desc()).all()
                    for run in runs:
                        run.status = "failed"
                        run.end_time = datetime.utcnow()
                        run.error_message = reason
                    logger.info(f"Marked orphaned running job as failed: {job_name}")
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Failed to mark running jobs as failed: {e}")

    @staticmethod
    def _is_process_running(pid):
        """Check if a process is running."""
        try:
            import psutil
            return psutil.pid_exists(pid)
        except Exception:
            # Fallback to os.kill
            try:
                os.kill(pid, 0)
                return True
            except Exception:
                return False

    @classmethod
    def get_status(cls):
        """Read status from status file."""
        if not STATUS_FILE.exists():
            return {"running": False, "job_count": 0, "jobs": []}
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"running": False, "job_count": 0, "jobs": []}

    @classmethod
    def is_running(cls):
        """Check if scheduler is running via status file and PID verification."""
        # First check if status file exists and shows running
        if STATUS_FILE.exists():
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    status = json.load(f)
                    if status.get("running"):
                        # Check if status is recent (within last 30 seconds)
                        updated_at = status.get("updated_at")
                        if updated_at:
                            try:
                                from datetime import datetime, timedelta
                                updated_dt = datetime.fromisoformat(updated_at)
                                # Convert to UTC if needed
                                if updated_dt.tzinfo is None:
                                    updated_dt = updated_dt.replace(tzinfo=None)
                                now = datetime.utcnow()
                                # If status was updated within 30 seconds, consider it running
                                if (now - updated_dt) < timedelta(seconds=30):
                                    return True
                            except Exception:
                                pass
                        # If no timestamp or old, try PID verification
                        if PID_FILE.exists():
                            try:
                                pid = int(PID_FILE.read_text().strip())
                                # Try to verify process is running
                                try:
                                    import psutil
                                    if psutil.pid_exists(pid):
                                        return True
                                except ImportError:
                                    # psutil not available, use os.kill as fallback
                                    try:
                                        os.kill(pid, 0)
                                        return True
                                    except Exception:
                                        # Process doesn't exist
                                        pass
                            except (ValueError, Exception):
                                pass
            except Exception:
                pass
        return False

    @classmethod
    def _mark_orphaned_jobs_failed(cls, reason, source="all"):
        """Mark all 'running' jobs as failed due to scheduler being unavailable."""
        try:
            engine = create_engine("sqlite:///data/run_history.db", echo=False, connect_args={"check_same_thread": False})
            SessionLocal = sessionmaker(bind=engine)
            session = SessionLocal()
            try:
                from datetime import datetime
                runs = session.query(Run).filter(Run.status == "running")
                if source == "scheduled":
                    runs = runs.filter(Run.trigger_type == "scheduled")
                elif source == "manual":
                    runs = runs.filter(Run.trigger_type == "manual")
                runs = runs.all()
                for run in runs:
                    run.status = "failed"
                    run.end_time = datetime.utcnow()
                    run.error_message = reason
                if runs:
                    session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Failed to mark orphaned jobs as failed: {e}")

    @classmethod
    def send_command(cls, cmd):
        """Send command to running scheduler process via command file."""
        try:
            with open(CMD_FILE, "w", encoding="utf-8") as f:
                f.write(cmd)
            return True
        except Exception:
            return False

    @classmethod
    def stop_daemon(cls, mark_running_failed=True):
        """Stop the daemon process.

        If mark_running_failed is True, marks all running scheduled jobs as failed
        before terminating the process.
        """
        if not PID_FILE.exists():
            return False
        try:
            import psutil
            pid = int(PID_FILE.read_text().strip())
            if mark_running_failed:
                cls._mark_orphaned_jobs_failed(
                    "Scheduler stopped while job was running",
                    source="scheduled"
                )
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
            return True
        except ImportError:
            # psutil not installed, try os.kill approach
            try:
                import os
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, 9)  # SIGKILL
                return True
            except Exception:
                return False
        except psutil.NoSuchProcess:
            return True
        except Exception:
            return False


def main():
    """Entry point for standalone scheduler."""
    daemon = SchedulerDaemon()

    def handle_sigterm(signum, frame):
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    daemon.start()


if __name__ == "__main__":
    main()
