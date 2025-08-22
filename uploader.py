# uploader.py
import logging
import mimetypes
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple

import requests
from requests.exceptions import RequestException, InvalidHeader


class DreamCasterUploader:
    def __init__(self, base_url: str, target_path: str = "/image", logger: Optional[logging.Logger] = None):
        self.base = base_url.rstrip("/")
        self.dir = target_path if target_path.startswith("/") else f"/{target_path}"
        self.logger = logger or logging.getLogger("dreamcaster")
        self.session = requests.Session()

    def _field_for_ext(self, filename: str) -> str:
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext in ("jpg", "jpeg"):
            return "file"
        return "image"

    def _upload_url(self) -> str:
        return f"{self.base}/doUpload?dir={urllib.parse.quote(self.dir)}"

    def _remote_path(self, filename: str) -> str:
        return f"{self.dir}/{filename}"

    def upload_file(self, file_path: Path) -> Tuple[bool, str]:
        file_path = Path(file_path)
        url = self._upload_url()
        field = self._field_for_ext(file_path.name)
        mime, _ = mimetypes.guess_type(str(file_path))

        try:
            with open(file_path, "rb") as f:
                files = {field: (file_path.name, f, mime or "application/octet-stream")}
                r = self.session.post(url, files=files, timeout=60)
                self.logger.info("POST %s -> %s", url, r.status_code)
                r.raise_for_status()

            return True, self._remote_path(file_path.name)

        
        except InvalidHeader as e:
            
            self.logger.warning("Upload successful, but server sent a malformed response: %s", e)
            return True, self._remote_path(file_path.name)

        except RequestException as e:
            self.logger.error("Upload error: %s", e)
            return False, ""

    def set_current(self, remote_path: str) -> bool:
        url = f"{self.base}/set?img={urllib.parse.quote(remote_path, safe='/')}"
        try:
            r = self.session.get(url, timeout=30)
            self.logger.info("GET %s -> %s", url, r.status_code)
            return r.ok
        except Exception as e:
            self.logger.exception("Set image error: %s", e)
            return False

    def upload_and_set(self, file_path: Path) -> bool:
        ok, remote = self.upload_file(file_path)
        if not ok or not remote:
            return False
        return self.set_current(remote)