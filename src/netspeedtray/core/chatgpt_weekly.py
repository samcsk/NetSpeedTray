"""Receive the two visible weekly limit fields from the paired Chromium extension."""
import json
import threading
import time

from netspeedtray.core.metrics_endpoint import LoopbackRequestHandler, _LoopbackHTTPServer

PORT = 42179
ORIGIN = "chrome-extension://hjjplmkmjappbjiocjimcofbifdjkemn"
MAX_AGE = 150  # The extension reports once a minute. Also expire a closed or discarded tab.


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


class _WeeklyHandler(LoopbackRequestHandler):
    def do_POST(self):
        if (self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                or self.headers.get("Origin") != ORIGIN):
            self.send_error(403)
            return
        if not self.server.bucket.take():
            self.send_error(429)
            return
        if self.path not in ("/ready", "/weekly"):
            self.send_error(404)
            return
        if self.path == "/weekly":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 128:
                    raise ValueError("invalid size")
                value = weekly_readout(json.loads(self.rfile.read(length)))
            except (ValueError, RecursionError):
                self.send_error(400)
                return
            self.server.store.publish(value)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        pass


class WeeklyReceiver:
    def __init__(self, port=PORT):
        self._port = port
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._last = None

    def read(self):
        if self._server is None:
            try:
                self._server = _LoopbackHTTPServer(self._port, self, handler=_WeeklyHandler)
            except OSError:
                return "Port busy"
            self._thread = threading.Thread(target=self._server.serve_forever, args=(0.05,),
                                            name="quota-weekly", daemon=True)
            self._thread.start()
        with self._lock:
            if self._last and time.monotonic() - self._last[0] < MAX_AGE:
                return self._last[1]
        return "Open usage"

    def publish(self, value):
        with self._lock:
            self._last = (time.monotonic(), value)

    def stop(self):
        if self._server:
            self._server.stopping.set()
            self._server.shutdown()
            self._server.server_close()
            self._thread.join()
            self._server.join_handlers(1.0)
            self._server = self._thread = None
        with self._lock:
            self._last = None
