import base64
import hashlib
import json
from http.client import HTTPConnection
from pathlib import Path

import pytest

from netspeedtray.core import chatgpt_weekly as weekly


def test_extension_origin_matches_manifest_key():
    extension = Path(__file__).resolve().parents[4] / "assets" / "chatgpt-weekly"
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()
    extension_id = digest[:32].translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))
    assert weekly.ORIGIN == "chrome-extension://" + extension_id


def test_weekly_receiver_lifecycle(monkeypatch):
    receiver = weekly.WeeklyReceiver(port=0)
    try:
        assert receiver.read() == "Open usage"
        port = receiver._server.server_port

        def post(path, body, origin=weekly.ORIGIN):
            conn = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                conn.request("POST", path, body, {"Origin": origin})
                return conn.getresponse().status
            finally:
                conn.close()

        assert post("/ready", "") == 204
        value = '{"left":71,"minutes":2700}'
        assert post("/weekly", value, "https://example.invalid") == 403
        assert receiver.read() == "Open usage"
        assert post("/weekly", value) == 204
        assert receiver.read() == "71% · 1d 21h"
        assert post("/weekly", '{"left":true,"minutes":123}') == 400
        assert post("/weekly", "null") == 204
        assert receiver.read() == "No data"
        monkeypatch.setattr(weekly, "MAX_AGE", 0)
        assert receiver.read() == "Open usage"
    finally:
        receiver.stop()
    assert receiver._last is None and receiver._server is None


@pytest.mark.parametrize(("left", "minutes", "expected"), [
    (0, 0, "0% · 0m"), (100, 10080, "100% · 7d 0h"), (87, 124, "87% · 2h 4m"),
])
def test_weekly_countdown(left, minutes, expected):
    assert weekly.weekly_readout({"left": left, "minutes": minutes}) == expected
