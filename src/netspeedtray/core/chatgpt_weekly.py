"""Read the default Codex seven-day allowance via the bundled OpenAI app-server."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlsplit

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from netspeedtray import __version__
from netspeedtray.utils.helpers import get_app_asset_path, neutral_cwd

CLIENT = {"name": "netspeedtray", "title": "NetSpeedTray", "version": __version__}
POLL_TIMEOUT = 30
LOGIN_TIMEOUT = 300
MAX_MESSAGE = 512 * 1024
_profile_lock = threading.Lock()


def profile_dir():
    local = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    return Path(local) / "NetSpeedTray" / "CodexQuota"


def weekly_readout(payload):
    buckets = payload.get("rateLimitsByLimitId")
    if buckets is None:
        bucket = payload.get("rateLimits")
        if not isinstance(bucket, dict) or bucket.get("limitId") != "codex":
            return "No data"
    else:
        bucket = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(bucket, dict) or bucket.get("limitId") not in ("codex", None):
        return "No data"
    windows = [window for window in (bucket.get("primary"), bucket.get("secondary"))
               if isinstance(window, dict) and window.get("windowDurationMins") == 7 * 24 * 60]
    if len(windows) != 1:
        return "No data"
    used = windows[0].get("usedPercent")
    if type(used) not in (int, float) or not 0 <= used <= 100:
        return "No data"
    return f"{100 - used:g}%"


class RpcError(Exception):
    """A display-safe status. Never include raw helper output or the OAuth URL."""


class AccountClient:
    def __init__(self, process):
        self.process = process
        self.next_id = 1
        self.completed_logins = {}

    def send(self, message):
        self.process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def receive(self):
        line = self.process.stdout.readline(MAX_MESSAGE + 1)
        if not line or len(line) > MAX_MESSAGE:
            raise RpcError("Retry")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise RpcError("Retry")
        if message.get("method") == "account/login/completed":
            event = message.get("params") or {}
            self.completed_logins[event.get("loginId")] = event.get("success") is True
        return message

    def request(self, method, params=None):
        ident = self.next_id
        self.next_id += 1
        request = {"method": method, "id": ident}
        if params is not None:
            request["params"] = params
        self.send(request)
        while True:
            msg = self.receive()
            if msg.get("id") == ident and "method" not in msg:
                break
        if "error" in msg:
            detail = str(msg["error"]).lower()
            if any(reason in detail for reason in ("authentication required", "sign in", "401 unauthorized")):
                raise RpcError("Sign in")
            raise RpcError("Retry")
        result = msg.get("result")
        if not isinstance(result, dict):
            raise RpcError("Retry")
        return result

    def sign_in(self):
        start = self.request("account/login/start", {"type": "chatgpt"})
        login_id = start.get("loginId")
        url = start.get("authUrl", "")
        target = urlsplit(url)
        if (start.get("type") != "chatgpt" or not isinstance(login_id, str) or not login_id
                or target.scheme != "https" or target.netloc != "auth.openai.com"):
            raise RpcError("Retry")
        # open_external logs the URL on failure. OAuth authorization URLs must stay out of logs.
        os.startfile(url, cwd=neutral_cwd())  # type: ignore[attr-defined]
        while login_id not in self.completed_logins:
            self.receive()
        return self.completed_logins[login_id]


@contextmanager
def account_client(executable, folder, timeout):
    # The helper manages its own sign-in. Do not inherit credentials or API overrides
    # from an unrelated Codex installation or the process that launched the widget.
    keep = ("SystemRoot", "WINDIR", "SystemDrive", "PATH", "PATHEXT", "COMSPEC",
            "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "TEMP", "TMP", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(CODEX_HOME=str(folder), RUST_LOG="off")
    command = [str(executable), "app-server", "--listen", "stdio://", "--startup-client-info",
               json.dumps(CLIENT), "-c", 'cli_auth_credentials_store="file"',
               "-c", "analytics.enabled=false", "-c", "feedback.enabled=false"]
    with subprocess.Popen(command, cwd=folder, env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        # A blocking stdio read must also expire when the login tab is abandoned.
        deadline = threading.Timer(timeout, process.kill)
        deadline.daemon = True
        deadline.start()
        try:
            client = AccountClient(process)
            client.request("initialize", {"clientInfo": CLIENT, "capabilities": None})
            client.send({"method": "initialized"})
            yield client
        finally:
            try:
                process.stdin.close()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
            finally:
                deadline.cancel()


def fetch_weekly():
    executable = get_app_asset_path("codex/codex.exe")
    if not executable.is_file():
        return "Reinstall"
    folder = profile_dir()
    if not folder.is_dir() or not _profile_lock.acquire(blocking=False):
        return "Sign in"
    try:
        with account_client(executable, folder, POLL_TIMEOUT) as client:
            return weekly_readout(client.request("account/rateLimits/read"))
    except RpcError as error:
        return str(error)
    finally:
        _profile_lock.release()


class SignInWindow(QObject):
    """Own an interactive login across settings dialog closes."""
    changed = pyqtSignal()
    _finished = pyqtSignal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.active = False
        self.failed = False
        self._finished.connect(self._closed)

    def open(self):
        if self.active:
            return
        executable = get_app_asset_path("codex/codex.exe")
        if not executable.is_file():
            raise FileNotFoundError("Bundled Codex helper")
        folder = profile_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self.active = True
        self.failed = False
        self.changed.emit()

        def run():
            try:
                with _profile_lock, account_client(executable, folder, LOGIN_TIMEOUT) as client:
                    ok = client.sign_in()
            except Exception:
                ok = False  # Never log an exception carrying account or OAuth details.
            try:
                self._finished.emit(ok)
            except RuntimeError:
                pass  # Application closed during sign-in.

        threading.Thread(target=run, name="chatgpt-sign-in", daemon=True).start()

    def _closed(self, ok):
        self.active = False
        self.failed = not ok
        self.changed.emit()


def sign_in_window():
    app = QCoreApplication.instance()
    return app.findChild(SignInWindow) or SignInWindow(app)
