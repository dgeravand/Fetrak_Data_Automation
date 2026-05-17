# ------------------------------------------------------------------------------
# WINDOWS SERVICE WRAPPER
# ------------------------------------------------------------------------------
# Allows the scheduler daemon to run as a Windows service.
# Install:   python scheduler\service.py install
# Start:     python scheduler\service.py start
# Stop:      python scheduler\service.py stop
# Remove:    python scheduler\service.py remove
#
# Requires pywin32: pip install pywin32
# ------------------------------------------------------------------------------
import os
import sys
import traceback

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError as e:
    print("pywin32 is required for Windows service support.")
    print("Install it: pip install pywin32")
    sys.exit(1)

from scheduler.daemon import SchedulerDaemon


class FetrakSchedulerService(win32serviceutil.ServiceFramework):
    """Windows service wrapper for the Fetrak scheduler daemon."""

    _svc_name_ = "FetrakScheduler"
    _svc_display_name_ = "Fetrak Scheduler Service"
    _svc_description_ = (
        "Runs scheduled data automation jobs for Fetrak independently of the web UI. "
        "Auto-starts on boot and survives user logoff."
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.daemon = None

    def SvcStop(self):
        """Called when Windows requests the service to stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.daemon:
            try:
                self.daemon.stop()
            except Exception:
                traceback.print_exc()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        """Main service loop."""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            self.daemon = SchedulerDaemon()
            # Start daemon in background thread so SvcStop can still run
            import threading
            self.daemon_thread = threading.Thread(target=self.daemon.start, daemon=True)
            self.daemon_thread.start()
            # Block until stop event is signaled
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        except Exception:
            traceback.print_exc()
            servicemanager.LogErrorMsg(traceback.format_exc())
        finally:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, ""),
            )


def custom_install():
    """Install the service with auto-start and delayed start."""
    import win32api
    import win32con

    win32serviceutil.HandleCommandLine(FetrakSchedulerService, argv=[sys.argv[0], "install"])

    # Configure auto-start (Delayed Auto Start = 2)
    try:
        hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
        hs = win32service.OpenService(hscm, FetrakSchedulerService._svc_name_, win32service.SERVICE_ALL_ACCESS)
        win32service.ChangeServiceConfig(
            hs,
            win32service.SERVICE_NO_CHANGE,
            win32service.SERVICE_AUTO_START,  # Auto start on boot
            win32service.SERVICE_NO_CHANGE,
            None, None, None, None, None, None, None,
        )
        # Set delayed auto-start (Windows 7+)
        try:
            win32service.ChangeServiceConfig2(hs, win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, 1)
        except Exception:
            pass  # Older Windows
        win32service.CloseServiceHandle(hs)
        win32service.CloseServiceHandle(hscm)
        print("Service configured to start automatically (delayed) on boot.")
    except Exception as e:
        print(f"Could not configure auto-start: {e}")


def custom_remove():
    """Remove the service."""
    win32serviceutil.HandleCommandLine(FetrakSchedulerService, argv=[sys.argv[0], "remove"])


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No args: run in debug mode (console) for testing
        print("Running scheduler in console mode (not as service)...")
        print("To install as Windows service, run: python scheduler\\service.py install")
        daemon = SchedulerDaemon()
        daemon.start()
    elif sys.argv[1] == "install":
        custom_install()
    elif sys.argv[1] == "remove":
        custom_remove()
    else:
        win32serviceutil.HandleCommandLine(FetrakSchedulerService)
