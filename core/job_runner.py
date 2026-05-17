# ------------------------------------------------------------------------------
# JOB RUNNER
# ------------------------------------------------------------------------------
# Orchestrates the data pipeline: fetches data, builds filename, processes
# Excel file, and uploads to SharePoint.
# ------------------------------------------------------------------------------
from datetime import datetime
import io
import sys
import traceback
import pandas as pd
import os
from pathlib import Path

from core.db_client import run_query
from core.sharepoint_client import SharePointClient
from core.excel_manager import ExcelManager
from core.config_loader import load_query
from core.timezone import now as tz_now
from core.utils import env


class LogCapture:
    """Context manager to capture stdout into a string, with optional live callback."""
    def __init__(self, on_line=None):
        """
        Args:
            on_line: Optional callback function that receives each line as it's written.
        """
        self._buffer = io.StringIO()
        self._on_line = on_line

    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = self  # Replace sys.stdout so print() calls write() on us
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._original_stdout

    def write(self, text):
        """Called by print() statements - writes to buffer AND calls callback."""
        self._buffer.write(text)

        # Write to sys.__stdout__ (original, un-wrapped) to avoid Windows console encoding issues
        # This bypasses any TextIOWrapper that can't encode emoji characters.
        try:
            _orig = getattr(sys, '__stdout__', None)
            if _orig is not None:
                try:
                    _orig.buffer.write(text.encode('utf-8'))
                    _orig.flush()
                except (AttributeError, OSError):
                    pass
        except Exception:
            pass

        if self._on_line:
            for line in text.splitlines(keepends=True):
                if line.strip():
                    self._on_line(line)

    def flush(self):
        """No-op since we use StringIO which doesn't need flushing."""
        pass

    def getvalue(self):
        return self._buffer.getvalue()


class JobRunner:

    def __init__(self):

        self.sp = SharePointClient(
            site_url=env("SP_SITE_URL"),
            username=env("SP_USERNAME"),
            password=env("SP_PASSWORD")
        )

        self.excel = ExcelManager()


    # ------------------------------------------------------------------------------
    # TEMP FOLDER
    # ------------------------------------------------------------------------------
    def _temp_dir(self, job):
        job_id = job.get("name", "unknown_job").replace(" ", "_")
        temp = Path("temp") / job_id
        temp.mkdir(parents=True, exist_ok=True)
        return temp


    # ------------------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------------------
    def run(self, job, on_log=None):
        """
        Args:
            job: Job configuration dict.
            on_log: Optional callback function called for each log line.
                    Useful for live-log streaming in UI.
        """
        job_name = job.get("name", "unknown_job")

        log_lines = []

        def on_line(line):
            log_lines.append(line)
            if on_log:
                on_log(line)

        with LogCapture(on_line=on_line) as capture:
            print(f"\n🚀 Running job: {job_name} at {tz_now().strftime('%Y-%m-%d %H:%M:%S')}")

            row_count = 0

            try:
                temp_dir = self._temp_dir(job)

                # Fetch data
                df = self._fetch_data(job)
                row_count = len(df)

                # Build filename
                filename = self._build_filename(job)

                # Upload logic
                self._process_file(job, df, filename, temp_dir)

                print(f"✅ Job completed: {job_name}")

            except Exception as e:
                print(f"❌ Job failed: {job_name}")
                print(str(e))
                traceback.print_exc()
                logs = capture.getvalue()
                raise Exception(f"Job failed: {e}\n\nLogs:\n{logs}") from e

        logs = capture.getvalue()
        return row_count, logs


    # ------------------------------------------------------------------------------
    # FETCH DATA
    # ------------------------------------------------------------------------------
    def _fetch_data(self, job):

        source = job.get("source", {})
        db_type = source.get("type", "none")

        print(f"📥 Source type: {db_type}")

        if db_type == "none":
            print("⚠️ No database source defined. Using empty dataframe.")
            return pd.DataFrame()

        query = source.get("query")
        query_file = source.get("query_file")

        if not query and query_file:
            query = load_query(query_file)

        if not query:
            raise Exception("Query is required for database sources")

        print("📥 Fetching data from database...")

        df = run_query(
            db_type,
            query
        )

        print(f"✅ Retrieved {len(df)} rows")
        return df


    # ------------------------------------------------------------------------------
    # BUILD FILENAME
    # ------------------------------------------------------------------------------
    def _build_filename(self, job):

        # Check if output section exists
        if "output" not in job:
            raise ValueError(f"Job '{job.get('name', 'unknown')}' is missing 'output' configuration - job skipped")

        now = datetime.now()
        file_conf = job["output"]["file"]
        filename = file_conf["name"]
        filename = filename.replace("{job_name}", job["name"])
        filename = filename.replace("{YYYY}", now.strftime("%Y"))
        filename = filename.replace("{YYYY_MM}", now.strftime("%Y_%m"))
        filename = filename.replace("{YYYY_MM_DD}", now.strftime("%Y_%m_%d"))

        print(f"📄 Target filename: {filename}")
        return filename


    # ------------------------------------------------------------------------------
    # PROCESS FILE
    # ------------------------------------------------------------------------------
    # Handles Excel file creation or appending, then uploads to SharePoint.
    # Supports both "replace" and "append" write modes.
    # ------------------------------------------------------------------------------
    def _process_file(self, job, df, filename, temp_dir):

        file_conf = job["output"]["file"]
        sp_conf = job["output"]["sharepoint"]

        library = sp_conf["library"]
        folder = sp_conf["folder"]

        sheet_name = file_conf["sheet"]["name"]
        write_mode = file_conf.get("write_mode", "append")

        path = f"{folder}/{filename}"

        file_exists = self.sp.path_exists(library, path)

        print(f"📁 File exists: {file_exists}")
        print(f"✏️ Write mode: {write_mode}")

        # Temp paths
        existing_file_path = temp_dir / "existing.xlsx"
        output_file_path = temp_dir / "output.xlsx"

        # Replace mode
        if write_mode == "replace":

            print("♻️ Replacing file...")

            file_bytes = self.excel.create_excel(
                df,
                sheet_name=sheet_name
            )

        # Append mode
        else:

            if file_exists:

                print("➕ Appending to existing file...")

                # Download file to temp
                file_bytes = self.sp.download_file_bytes(
                    library,
                    path
                )
                with open(existing_file_path, "wb") as f:
                    f.write(file_bytes)

                # Append
                file_bytes = self.excel.append_excel(
                    file_bytes,
                    df,
                    sheet_name=sheet_name
                )

            else:

                print("🆕 Creating new file...")

                file_bytes = self.excel.create_excel(
                    df,
                    sheet_name=sheet_name
                )

        # Save output to temp
        with open(output_file_path, "wb") as f:
            f.write(file_bytes)

        print(f"📦 Output saved to temp: {output_file_path}")

        # Upload
        print("☁️ Uploading to SharePoint...")

        file_url = self.sp.upload_file(
            library=library,
            folder=folder,
            filename=filename,
            file_bytes=file_bytes
        )

        print("✅ Upload completed")

        # Full link
        view_link = self.sp.get_file_view_link(file_url)
        print("🔗 Open in browser:", view_link)

        job_owners = job.get("owners", [])
        print("owners:", job_owners)
        if job_owners:
            self.sp.set_file_owners(file_url, job_owners)

        print("✅ grant_permissions")