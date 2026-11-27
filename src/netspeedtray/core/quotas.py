"""Poll the enabled Devin and ChatGPT quota providers off the UI thread."""
from __future__ import annotations

import json
import math
import re
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from netspeedtray.utils import https

TOKEN_ENTROPY = b"NetSpeedTray/Devin quota/v1"
POLL_MS = 5 * 60_000
TIMEOUT = 15
MAX_RESPONSE = 256 * 1024


def remaining(windows):
    """Compact percentage and period of the binding (most used) window."""
    valid = [(min(100, used), period) for used, period in windows
             if type(used) in (int, float) and 0 <= used and math.isfinite(used)]
    if not valid:
        return "No data"
    used, period = max(valid, key=lambda pair: pair[0])
    percent = "<1" if 99 < used < 100 else str(round(100 - used))
    return f"{percent}% {period}".rstrip()


def devin_readout(data):
    if data.get("is_quota_plan") is False or data.get("has_quota_allocation") is False:
        return "No quota"
    return remaining((data.get(f"{window}_percentage"), label)
                     for window, label in (("daily", "1d"), ("weekly", "7d"))
                     if not data.get(f"hide_{window}_quota"))


def fetch_devin(org, protected_token):
    from netspeedtray.utils.secret_store import unprotect
    token = (unprotect(protected_token, TOKEN_ENTROPY) or "").strip()
    token = re.sub(r"^(?:Authorization:\s*)?Bearer\s+", "", token, flags=re.IGNORECASE)
    if not re.fullmatch(r"org[-_][a-zA-Z0-9_-]+", org) or not re.fullmatch(r"[!-~]+", token):
        return "Set up"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}", "x-cog-org-id": org}
    conn = https.connection("app.devin.ai", timeout=TIMEOUT)
    try:
        conn.request("GET", f"/api/{org}/billing/quota/usage", headers=headers)
        response = conn.getresponse()
        if response.status == 404:
            conn.close()
            conn.request("GET", f"/api/organizations/{org}/billing/quota/usage", headers=headers)
            response = conn.getresponse()
        if response.status in (401, 403):
            return "Sign in"
        if response.status != 200:
            return "Retry"
        payload = response.read(MAX_RESPONSE + 1)
        if len(payload) > MAX_RESPONSE:
            return "No data"
        return devin_readout(json.loads(payload))
    finally:
        conn.close()


class QuotaPoller(QObject):
    changed = pyqtSignal()
    _finished = pyqtSignal(str, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = {}
        self._active = {}   # provider -> generation that enabled it
        self._pending = set()
        self._generation = 0
        self._devin_login = ("", "")
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._finished.connect(self._accept)
        from netspeedtray.core.chatgpt_weekly import sign_in_window
        self._chatgpt_login = sign_in_window()
        self._chatgpt_login.changed.connect(self._login_changed)

    def configure(self, config):
        enabled = {name for name in ("devin", "codex") if config.get(f"quota_{name}", False)}
        login = (config.get("quota_devin_org", ""), config.get("quota_devin_token_protected", ""))
        if enabled == self._active.keys() and ("devin" not in enabled or login == self._devin_login):
            return
        if login != self._devin_login:
            self._active.pop("devin", None)
            self.values.pop("devin", None)
            self._devin_login = login
        self._generation += 1
        for name in self._active.keys() - enabled:
            del self._active[name]
            self.values.pop(name, None)
        for name in enabled - self._active.keys():
            self._active[name] = self._generation
            self._start(name)
        if not enabled:
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start()
        self.changed.emit()

    def _poll(self):
        for name in self._active:
            self._start(name)

    def _login_changed(self):
        if "codex" in self._active:
            # A result from before an account change must never replace the new balance.
            self._generation += 1
            self._active["codex"] = self._generation
            self.values.pop("codex", None)
            self._start("codex")
            self.changed.emit()

    def _start(self, name):
        generation = self._active[name]
        if name == "codex" and self._chatgpt_login.active:
            self.values[name] = "Sign in"
            return
        if name in self._pending:
            return
        self._pending.add(name)
        login = self._devin_login

        def run():
            try:
                if name == "devin":
                    value = fetch_devin(*login)
                else:
                    from netspeedtray.core.chatgpt_weekly import fetch_weekly
                    value = fetch_weekly()
            except Exception:
                # Never log provider output, credentials, or an exception containing either.
                value = "Retry"
            try:
                self._finished.emit(name, generation, value)
            except RuntimeError:
                pass  # parent was destroyed during a bounded read

        threading.Thread(target=run, name=f"quota-{name}", daemon=True).start()

    def _accept(self, name, generation, value):
        self._pending.discard(name)
        if self._active.get(name) == generation:
            self.values[name] = value
            self.changed.emit()
        elif name in self._active:
            self._start(name)
