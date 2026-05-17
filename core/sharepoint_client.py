from requests_ntlm2 import HttpNtlmAuth
import requests
import urllib3
import os
from urllib.parse import urlparse

urllib3.disable_warnings()


class SharePointClient:

    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------
    def __init__(self, site_url, username, password, timeout=60):
        self.site_url = site_url.rstrip("/")
        self.timeout = timeout

        # Extract site path like /my/davood_geravand
        self.site_path = urlparse(self.site_url).path.rstrip("/")

        self.session = requests.Session()
        self.session.auth = HttpNtlmAuth(username, password, send_cbt=True)

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json;odata=verbose",
            "Connection": "Keep-Alive"
        })

    # ------------------------------------------------------------------
    # HTTP HELPERS
    # ------------------------------------------------------------------
    def _request_with_retry(self, method, url, max_retries=10, backoff=2, **kwargs):
        """Make HTTP request with retry and exponential backoff."""
        import time
        last_exception = None
        for attempt in range(max_retries):
            try:
                r = method(url, verify=False, timeout=self.timeout, **kwargs)
                if r.status_code == 401:
                    r = method(url, verify=False, timeout=self.timeout, **kwargs)
                return r
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    wait = backoff * (attempt + 1)
                    time.sleep(wait)
        raise last_exception

    def _post(self, url, **kwargs):
        return self._request_with_retry(self.session.post, url, **kwargs)

    def _get(self, url, **kwargs):
        return self._request_with_retry(self.session.get, url, **kwargs)

    # ------------------------------------------------------------------
    # HELPER: BUILD SERVER RELATIVE PATH
    # ------------------------------------------------------------------
    def _full_path(self, library, path=None):

        parts = [self.site_path, library]

        if path:
            parts.append(path)

        full = "/".join(p.strip("/") for p in parts if p)

        # SharePoint requires leading slash
        return "/" + full


    # ------------------------------------------------------------------
    # DIGEST
    # ------------------------------------------------------------------
    def get_digest(self):
        url = f"{self.site_url}/_api/contextinfo"

        headers = {
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose"
        }

        r = self._post(url, headers=headers)

        if r.status_code != 200:
            raise Exception(f"Digest failed: {r.status_code} {r.text}")

        return r.json()["d"]["GetContextWebInformation"]["FormDigestValue"]

    # ------------------------------------------------------------------
    # HEALTH
    # ------------------------------------------------------------------
    def health_check(self):
        url = f"{self.site_url}/_api/web"
        r = self._get(url)
        return r.status_code == 200

    # ------------------------------------------------------------------
    # PATH EXISTS
    # ------------------------------------------------------------------
    def path_exists(self, library, path, type="auto"):

        full_path = self._full_path(library, path)

        if type == "auto":
            type = "file" if "." in os.path.basename(path) else "folder"

        if type == "file":
            url = f"{self.site_url}/_api/web/GetFileByServerRelativeUrl('{full_path}')"
        else:
            url = f"{self.site_url}/_api/web/GetFolderByServerRelativeUrl('{full_path}')"

        r = self._get(url)

        return r.status_code == 200

    # ------------------------------------------------------------------
    # CREATE FOLDER
    # ------------------------------------------------------------------
    def ensure_folder(self, folder_relative_url):

        digest = self.get_digest()

        url = f"{self.site_url}/_api/web/folders/add"

        headers = {
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
            "X-RequestDigest": digest
        }

        body = {"ServerRelativeUrl": folder_relative_url}

        return self._post(url, json=body, headers=headers)

    # ------------------------------------------------------------------
    # ENSURE MULTI LEVEL FOLDER
    # ------------------------------------------------------------------
    def ensure_folder_path(self, library, folder):

        if not folder:
            return True

        parts = folder.strip("/").split("/")
        current = ""

        for p in parts:

            current = f"{current}/{p}".strip("/")

            if not self.path_exists(library, current, "folder"):

                full = self._full_path(library, current)

                print(f"📁 Creating folder: {full}")

                self.ensure_folder(full)

        return True

    # ------------------------------------------------------------------
    # CHECK FILE LOCK
    # ------------------------------------------------------------------
    def check_file_lock(self, library, path):
        """Check if a file is locked by another user."""
        full_path = self._full_path(library, path)

        url = f"{self.site_url}/_api/web/GetFileByServerRelativeUrl('{full_path}')/$value"

        try:
            # Try to get the file - if it's locked, we'll get a 423 error
            r = self._get(url)
            return None  # Not locked
        except Exception as e:
            error_str = str(e)
            if "423" in error_str or "SPFileLockException" in error_str:
                # Extract the locking user if present in error message
                import re
                locked_by_match = re.search(r'shared use by (.+?)\.', error_str)
                locked_by = locked_by_match.group(1) if locked_by_match else "unknown user"
                return locked_by
            raise

    # ------------------------------------------------------------------
    # UPLOAD FILE WITH RETRY
    # ------------------------------------------------------------------
    def upload_file(self, library, folder, filename, file_bytes, overwrite=True, max_retries=None, retry_delay=None):
        """
        Upload file with automatic retry on file lock errors.

        Args:
            library: SharePoint library name
            folder: Folder path in library
            filename: Name of file to upload
            file_bytes: File content as bytes
            overwrite: Whether to overwrite existing file
            max_retries: Number of retries (default: from SP_MAX_RETRIES env var or 12)
            retry_delay: Delay between retries in seconds (default: from SP_RETRY_DELAY env var or 300)
        """
        # Read from environment if not specified
        if max_retries is None:
            try:
                from core.utils import env
                max_retries = int(env("SP_MAX_RETRIES", "12"))
            except:
                max_retries = 12

        if retry_delay is None:
            try:
                from core.utils import env
                retry_delay = int(env("SP_RETRY_DELAY", "300"))
            except:
                retry_delay = 300

        # ensure folder exists
        self.ensure_folder_path(library, folder)

        folder_full = self._full_path(library, folder)
        file_path = f"{folder}/{filename}" if folder else filename

        import time

        for attempt in range(max_retries):
            try:
                # Check if file exists and is locked before uploading
                if self.path_exists(library, file_path, "file"):
                    locked_by = self.check_file_lock(library, file_path)
                    if locked_by:
                        if attempt < max_retries - 1:
                            print(f"⚠️  File is locked by {locked_by}. Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                            time.sleep(retry_delay)
                            continue
                        else:
                            raise Exception(f"File is locked by {locked_by}. Please ask them to close it or wait for the lock to be released.")

                digest = self.get_digest()

                url = (
                    f"{self.site_url}/_api/web/GetFolderByServerRelativeUrl('{folder_full}')"
                    f"/Files/add(url='{filename}',overwrite={'true' if overwrite else 'false'})"
                )

                headers = {
                    "X-RequestDigest": digest,
                    "Accept": "application/json;odata=verbose",
                    "Content-Type": "application/octet-stream"
                }

                r = self._post(url, data=file_bytes, headers=headers)

                if r.status_code not in [200, 201]:
                    # Check if it's a lock error
                    if r.status_code == 423:
                        if attempt < max_retries - 1:
                            print(f"⚠️  Upload failed: File is locked. Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                            time.sleep(retry_delay)
                            continue
                        else:
                            raise Exception(f"Upload failed: File is locked after {max_retries} attempts. Please ensure no one has the file open.")
                    raise Exception(f"Upload failed: {r.status_code} {r.text}")

                data = r.json()

                return data["d"]["ServerRelativeUrl"]

            except Exception as e:
                if "locked" in str(e).lower() or "423" in str(e):
                    if attempt < max_retries - 1:
                        print(f"⚠️  {str(e)} Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                raise


    # ------------------------------------------------------------------
    # DOWNLOAD FILE BYTES
    # ------------------------------------------------------------------
    def download_file_bytes(self, library, path):

        full_path = self._full_path(library, path)

        url = f"{self.site_url}/_api/web/GetFileByServerRelativeUrl('{full_path}')/$value"

        r = self._get(url)

        r.raise_for_status()

        return r.content

    # ------------------------------------------------------------------
    # DELETE FILE
    # ------------------------------------------------------------------
    def delete_file(self, library, path):

        digest = self.get_digest()

        full_path = self._full_path(library, path)

        url = f"{self.site_url}/_api/web/GetFileByServerRelativeUrl('{full_path}')"

        headers = {
            "X-RequestDigest": digest,
            "IF-MATCH": "*",
            "X-HTTP-Method": "DELETE"
        }

        return self._post(url, headers=headers)
    
    # ------------------------------------------------------------------
    # permissions FILE
    # ------------------------------------------------------------------
    def set_file_owners(self, file_url, owners):

        if not owners:
            return

        digest = self.get_digest()
        headers = {
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
            "X-RequestDigest": digest
        }

        base = f"{self.site_url}/_api/web/GetFileByServerRelativeUrl('{file_url}')/ListItemAllFields"

        # 1. break role inheritance (very important)
        break_url = f"{base}/breakroleinheritance(copyRoleAssignments=true, clearSubscopes=false)"
        self._post(break_url, headers=headers)

        for owner_login in owners:

            try:
                # 2. ensure user
                user_url = f"{self.site_url}/_api/web/ensureuser"
                res_user = self._post(user_url, json={'logonName': owner_login}, headers=headers)

                if res_user.status_code not in [200, 201]:
                    print(f"❌ ensureuser failed: {res_user.text}")
                    continue

                user_id = res_user.json()['d']['Id']

                # 3. give Edit permission
                role_id = 1073741827  # Edit (this is the standard number)

                perm_url = (
                    f"{base}/roleassignments/addroleassignment"
                    f"(principalid={user_id},roledefid={role_id})"
                )

                res_perm = self._post(perm_url, headers=headers)

                if res_perm.status_code in [200, 201, 204]:
                    print(f"✅ Access granted to {owner_login}")
                else:
                    print(f"❌ Permission error {res_perm.status_code}: {res_perm.text}")

            except Exception as e:
                print(f"🔥 Unexpected error for {owner_login}: {str(e)}")



    def get_file_view_link(self, file_url):

        api = (
            f"{self.site_url}"
            f"/_api/web/GetFileByServerRelativeUrl('{file_url}')"
            f"?$select=UniqueId,Name"
        )

        res = self.session.get(
            api,
            headers={"Accept": "application/json;odata=verbose"}
        )

        if res.status_code != 200:
            raise Exception(
                f"Failed to get file info: {res.status_code} - {res.text}"
            )

        data = res.json()["d"]

        guid = data["UniqueId"]
        name = data["Name"]

        view_link = (
            f"{self.site_url}/_layouts/15/WopiFrame.aspx"
            f"?sourcedoc={{{guid}}}"
            f"&file={name}"
            f"&action=default"
        )

        return view_link
