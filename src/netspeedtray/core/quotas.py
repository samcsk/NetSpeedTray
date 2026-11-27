"""Read the Devin dashboard quota and Codex account limits. No provider starts a session."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
from http.client import HTTPSConnection
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from netspeedtray.utils.https import https_context

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


def codex_readout(result):
    limits = result.get("rateLimits") or {}
    windows = []
    for key in ("primary", "secondary"):
        window = limits.get(key)
        if isinstance(window, dict):
            minutes = window.get("windowDurationMins")
            label = ""
            if type(minutes) is int and 0 < minutes <= 99999:
                if minutes % 1440 == 0:
                    label = f"{minutes // 1440}d"
                elif minutes % 60 == 0:
                    label = f"{minutes // 60}h"
                else:
                    label = f"{minutes}m"
            windows.append((window.get("usedPercent"), label))
    return remaining(windows)


def fetch_devin(org, protected_token):
    from netspeedtray.utils.secret_store import unprotect
    token = (unprotect(protected_token, TOKEN_ENTROPY) or "").strip()
    token = re.sub(r"^(?:Authorization:\s*)?Bearer\s+", "", token, flags=re.IGNORECASE)
    if not re.fullmatch(r"org[-_][a-zA-Z0-9_-]+", org) or not re.fullmatch(r"[!-~]+", token):
        return "Set up"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}", "x-cog-org-id": org}
    conn = HTTPSConnection("app.devin.ai", timeout=TIMEOUT, context=https_context())
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


def codex_executable():
    """Native executable, including OpenAI's global npm package behind its Windows .cmd shim."""
    for entry in os.get_exec_path():
        directory = Path(entry.strip('"'))
        if not directory.is_absolute():
            continue
        exe = directory / "codex.exe"
        if exe.is_file():
            return exe
        if (directory / "codex.cmd").is_file():
            package = directory / "node_modules" / "@openai" / "codex"
            vendors = [package / "vendor"]
            vendors.extend(package.glob("node_modules/@openai/codex-win32-*/vendor"))
            vendors.extend(package.parent.glob("codex-win32-*/vendor"))
            for vendor in vendors:
                for name in ("bin", "codex"):
                    exe = next(vendor.glob(f"*-pc-windows-msvc/{name}/codex.exe"), None)
                    if exe and exe.is_file():
                        return exe
    return None


def fetch_codex():
    executable = codex_executable()
    if not executable:
        return "Install CLI"
    # Keep stdin open until the correlated response arrives. EOF immediately after sending the
    # request can make app-server exit before answering. Bound the whole exchange, including reads.
    with subprocess.Popen([str(executable), "app-server"], cwd=Path.home(),
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
        deadline = threading.Timer(TIMEOUT, proc.kill)
        deadline.start()
        def send(message):
            proc.stdin.write(json.dumps(message).encode() + b"\n")
            proc.stdin.flush()

        try:
            send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "netspeedtray", "title": "NetSpeedTray", "version": "1"},
            }})
            while True:
                line = proc.stdout.readline(MAX_RESPONSE + 1)
                if not line or len(line) > MAX_RESPONSE:
                    return "Retry"
                msg = json.loads(line)
                if msg.get("id") == 1:
                    if "error" in msg:
                        return "Retry"
                    send({"method": "initialized"})
                    send({"id": 2, "method": "account/rateLimits/read", "params": {}})
                elif msg.get("id") == 2:
                    if "error" in msg:
                        message = str(msg["error"]).lower()
                        return "Sign in" if any(k in message for k in ("login", "auth", "sign in")) else "Retry"
                    return codex_readout(msg["result"])
        finally:
            deadline.cancel()
            proc.kill()


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
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()
        self.changed.emit()

    def _poll(self):
        for name in self._active:
            self._start(name)

    def _start(self, name):
        generation = self._active[name]
        if name in self._pending:
            return
        self._pending.add(name)
        login = self._devin_login

        def run():
            try:
                value = fetch_devin(*login) if name == "devin" else fetch_codex()
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
