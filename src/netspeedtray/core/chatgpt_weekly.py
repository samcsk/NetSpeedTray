"""Read the weekly limit shared through the user's dedicated browser connection folder."""
import json
from pathlib import Path
import re
import time
import uuid

MAX_AGE = 150  # The extension reports once a minute. Expire closed and discarded tabs.
FOLDER = Path.home() / "NetSpeedTray" / "ChatGPT weekly"


def weekly_readout(data):
    if data is None:
        return "No data"
    if not isinstance(data, dict) or data.keys() != {"left", "minutes"}:
        raise ValueError("unexpected quota fields")
    left, minutes = data["left"], data["minutes"]
    if type(left) is not int or not 0 <= left <= 100:
        raise ValueError("invalid percentage")
    if type(minutes) is not int or not 0 <= minutes <= 7 * 24 * 60:
        raise ValueError("invalid weekly countdown")
    hours, mins = divmod(minutes, 60)
    days, hrs = divmod(hours, 24)
    if days:
        countdown = f"{days}d {hrs}h"
    elif hours:
        countdown = f"{hours}h {mins}m"
    else:
        countdown = f"{mins}m"
    return f"{left}% · {countdown}"


class WeeklyReceiver:
    def __init__(self, folder=None):
        self.folder = folder or FOLDER
        self.session = uuid.uuid4().hex
        self._next_heartbeat = 0

    def read(self):
        try:
            if time.monotonic() >= self._next_heartbeat:
                self.folder.mkdir(parents=True, exist_ok=True)
                pending = self.folder / "active.tmp"
                pending.write_text(json.dumps({"session": self.session, "time": time.time()}),
                                   encoding="utf8")
                pending.replace(self.folder / "active.json")
                self._next_heartbeat = time.monotonic() + 30
        except OSError:
            return "Folder error"

        try:
            with (self.folder / "browser.json").open("rb") as file:
                browser = json.loads(file.read(65))
            if not isinstance(browser, str) or not re.fullmatch(r"[a-f0-9]{32}", browser):
                return "Open usage"
            path = self.folder / f"weekly-{browser}.json"
            with path.open("rb") as file:
                data = json.loads(file.read(513))
            if (isinstance(data, dict) and data.get("session") == self.session
                    and 0 <= time.time() - path.stat().st_mtime < MAX_AGE):
                return weekly_readout(data["weekly"])
        except (OSError, ValueError, RecursionError, KeyError):
            pass
        return "Open usage"

    def stop(self):
        for name in ("active.json", "active.tmp"):
            try:
                (self.folder / name).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            for path in self.folder.glob("weekly-*.json"):
                if re.fullmatch(r"weekly-[a-f0-9]{32}\.json", path.name):
                    path.unlink(missing_ok=True)
        except OSError:
            pass
