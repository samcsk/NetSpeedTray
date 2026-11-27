"""Read ChatGPT's rendered weekly limit with a dedicated, browser-managed Edge profile."""
import os
from pathlib import Path
import subprocess
import threading

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

USAGE = "https://chatgpt.com/settings/usage"
TIMEOUT_MS = 15_000
# A normal sign-in window and a headless poll must never open the profile together.
_profile_lock = threading.Lock()


def profile_dir():
    local = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    return Path(local) / "NetSpeedTray" / "ChatGPTProfile"


def edge_executable():
    for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if root := os.environ.get(key):
            edge = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if edge.is_file():
                return edge
    return None


class SignInWindow(QObject):
    """Share sign-in state between Settings and the poller, including across dialog closes."""
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
        edge = edge_executable()
        if edge is None:
            raise FileNotFoundError("Microsoft Edge")
        folder = profile_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self.active = True
        self.failed = False
        self.changed.emit()

        def run():
            try:
                with _profile_lock:
                    subprocess.run([str(edge), f"--user-data-dir={folder}", "--no-first-run",
                                    "--disable-background-mode", "--new-window", USAGE], check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ok = True
            except (OSError, subprocess.CalledProcessError):
                ok = False
            try:
                self._finished.emit(ok)
            except RuntimeError:
                pass  # Application closed while the user had the sign-in window open.

        threading.Thread(target=run, name="chatgpt-sign-in", daemon=True).start()

    def _closed(self, ok):
        self.active = False
        self.failed = not ok
        self.changed.emit()


def sign_in_window():
    app = QCoreApplication.instance()
    return app.findChild(SignInWindow) or SignInWindow(app)


def read_page(page):
    """Wait for a client-rendered card, including a genuine zero balance."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from netspeedtray.utils.helpers import get_app_asset_path

    response = page.goto(USAGE, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    if response and (response.status == 403 or response.header_value("cf-mitigated") == "challenge"):
        return "Blocked"
    if response and response.status == 401:
        return "Sign in"
    if response and response.status >= 400:
        return "Retry"
    parser = get_app_asset_path("chatgpt-weekly.js").read_text(encoding="utf-8")
    predicate = """() => {
        if (!document.body) return false;
        if (/^verify you are human$/im.test(document.body.innerText)) return 'Blocked';
    """ + parser + """
        if (location.origin === 'https://chatgpt.com' &&
            location.pathname.replace(/\\/$/, '') === '/settings/usage') {
            const weekly = readWeeklyPage(document.body);
            if (weekly) return weekly.left + '%';
        }
        if (document.querySelector('input[autocomplete=username], a[href*="/auth/login"]') ||
            /^(log in|sign in)$/im.test(document.body.innerText)) return 'Sign in';
        return false;
    }"""
    try:
        return page.wait_for_function(predicate, polling=300, timeout=TIMEOUT_MS).json_value()
    except PlaywrightTimeout:
        return "No data"


def fetch_weekly():
    edge = edge_executable()
    if not edge:
        return "Get Edge"
    folder = profile_dir()
    if not folder.is_dir():
        return "Sign in"
    from playwright.sync_api import sync_playwright

    if not _profile_lock.acquire(blocking=False):
        return "Sign in"
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                folder, executable_path=edge, headless=True, chromium_sandbox=True,
                timeout=TIMEOUT_MS, accept_downloads=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                return read_page(page)
            finally:
                context.close()
    finally:
        _profile_lock.release()
