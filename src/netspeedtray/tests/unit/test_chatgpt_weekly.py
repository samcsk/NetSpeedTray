"""Offline checks for the bundled quota helper, browser sign-in, and taskbar refresh."""
import sys
import threading

import pytest

from netspeedtray.core import chatgpt_weekly as weekly, quotas


WEEK = {"windowDurationMins": 10080, "usedPercent": 80}
SHORT = {"windowDurationMins": 300, "usedPercent": 98}


@pytest.mark.parametrize(("payload", "expected"), [
    ({"rateLimitsByLimitId": {"codex": {"primary": SHORT, "secondary": WEEK}}}, "20%"),
    ({"rateLimits": {"limitId": "codex", "primary": WEEK, "secondary": SHORT}}, "20%"),
    ({"rateLimitsByLimitId": {"codex": {"primary": dict(WEEK, usedPercent=100)}}}, "0%"),
    ({"rateLimitsByLimitId": {"codex": {"primary": dict(WEEK, usedPercent=101)}}}, "0%"),
    ({"rateLimitsByLimitId": {"codex": {"primary": dict(WEEK, usedPercent=0)}}}, "100%"),
    ({"rateLimitsByLimitId": {"review": {"primary": WEEK}},
      "rateLimits": {"limitId": "codex", "primary": WEEK}}, "No data"),
    ({"rateLimitsByLimitId": {"codex": {"limitId": "other", "primary": WEEK}}}, "No data"),
    ({"rateLimits": {"limitId": "unknown", "primary": WEEK}}, "No data"),
    ({"rateLimitsByLimitId": {"codex": {"primary": WEEK, "secondary": WEEK}}}, "No data"),
    ({"rateLimitsByLimitId": {"codex": {"primary": SHORT}}}, "No data"),
])
def test_weekly_window(payload, expected):
    assert weekly.weekly_readout(payload) == expected


NOW = 1_800_000_000


@pytest.mark.parametrize(("reset", "expected"), [
    (NOW + 7 * 86400, "28% 7d"),
    (NOW + 6 * 86400 + 21 * 3600 + 59 * 60, "28% 6d 21h"),
    (NOW + 86400, "28% 1d"),
    (NOW + 86400 - 1, "28% 23h 59m"),
    (NOW + 3600, "28% 1h"),
    (NOW + 60, "28% 1m"),
    (NOW + 59, "28% <1m"),
    (NOW, "28%"),
    (NOW - 1, "28%"),
    (None, "28%"),
    ("invalid", "28%"),
    (True, "28%"),
])
def test_reset_comes_from_weekly_window(reset, expected, monkeypatch):
    monkeypatch.setattr(weekly, "time", lambda: NOW)
    bucket = {"limitId": "codex", "primary": dict(SHORT, resetsAt=NOW + 60),
              "secondary": dict(WEEK, usedPercent=72, resetsAt=reset)}
    assert str(weekly.weekly_readout({"rateLimits": bucket})) == expected


@pytest.mark.parametrize("used", [-1, float("inf"), float("nan"), True, None, "12"])
def test_invalid_percentage(used):
    window = dict(WEEK, usedPercent=used)
    assert weekly.weekly_readout({"rateLimitsByLimitId": {"codex": {"primary": window}}}) == "No data"


def test_first_poll(tmp_path, monkeypatch):
    folder = tmp_path / "login"
    helper = tmp_path / "helper"
    monkeypatch.setattr(weekly, "profile_dir", lambda: folder)
    monkeypatch.setattr(weekly, "get_app_asset_path", lambda _: helper)
    assert weekly.fetch_weekly() == "Reinstall"
    helper.touch()
    assert weekly.fetch_weekly() == "Sign in"
    assert not folder.exists()


# An independent helper process for each operation, including across widget restarts.
# The marker is synthetic and its contents are only a used percentage.
FAKE_SERVER = """
import json, os, sys
from pathlib import Path
folder = Path(os.environ['CODEX_HOME'])
assert folder == Path.cwd()
assert 'OPENAI_API_KEY' not in os.environ
marker = folder / 'used'
def send(message):
    print(json.dumps(message), flush=True)
for line in sys.stdin:
    msg = json.loads(line)
    method = msg['method']
    if method == 'initialize':
        assert msg['params']['clientInfo']['name'] == 'netspeedtray'
        result = {}
    elif method == 'initialized':
        continue
    elif method == 'account/login/start':
        assert msg['params'] == {'type':'chatgpt'}
        marker.write_text('80')
        send({'method':'account/login/completed','params':{'loginId':'test','success':True}})
        result = {'type':'chatgpt', 'authUrl':'https://auth.openai.com/test', 'loginId':'test'}
    elif method == 'account/rateLimits/read':
        assert msg['params'] == {'excludeResetCreditDetails': True}
        if not marker.exists():
            send({'id':msg['id'], 'error':{'message':'codex account authentication required'}})
            continue
        result = {'rateLimitsByLimitId':{'codex':{'primary':{
            'usedPercent':int(marker.read_text()),'windowDurationMins':10080,'resetsAt':WEEKLY_RESET}}}}
    else:
        raise ValueError('unexpected operation')
    send({'id':msg['id'],'result':result})
"""


def test_sign_in_poll_and_restart(qtbot, tmp_path, monkeypatch):
    now = NOW
    monkeypatch.setattr(weekly, "time", lambda: now)
    executable = tmp_path / "server.py"
    reset = NOW + (6 * 24 + 21) * 3600
    executable.write_text(FAKE_SERVER.replace("WEEKLY_RESET", str(reset)), encoding="utf-8")
    folder = tmp_path / "dedicated"
    folder.mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr(weekly, "profile_dir", lambda: folder)
    monkeypatch.setattr(weekly, "get_app_asset_path", lambda _: executable)
    spawn = weekly.subprocess.Popen
    def launch(command, **kwargs):
        assert command[:4] == [str(executable), "app-server", "--listen", "stdio://"]
        return spawn([sys.executable, "-I", str(executable)], **kwargs)
    monkeypatch.setattr(weekly.subprocess, "Popen", launch)

    opened = threading.Event()
    finish = threading.Event()
    def browser(url, **kwargs):
        assert url == "https://auth.openai.com/test"
        opened.set()
        assert finish.wait(5)
    monkeypatch.setattr(weekly.os, "startfile", browser, raising=False)

    poller = quotas.QuotaPoller()
    frozen = {"devin": "62% 7d", "codex": "35%"}
    poller.account_changed.connect(lambda provider: frozen.pop(provider, None))
    login = weekly.sign_in_window()
    try:
        poller.configure({"quota_codex": True})
        qtbot.waitUntil(lambda: poller.values == {"codex": "Sign in"})
        login.open()
        login.open()
        qtbot.waitUntil(opened.is_set)
        assert weekly.fetch_weekly() == "Sign in"
        finish.set()
        qtbot.waitUntil(lambda: poller.values == {"codex": "20% 6d 21h"})
        assert not login.failed and frozen == {"devin": "62% 7d"}
        now += 3600  # The stored reset counts down before another poll.
        assert poller.values == {"codex": "20% 6d 20h"}
        (folder / "used").write_text("81")
        poller._timer.timeout.emit()
        qtbot.waitUntil(lambda: poller.values == {"codex": "19% 6d 20h"})
        poller.configure({})
        restarted = quotas.QuotaPoller()
        restarted.configure({"quota_codex": True})
        try:
            qtbot.waitUntil(lambda: restarted.values == {"codex": "19% 6d 20h"})
            now += 7 * 86400
            assert restarted.values == {"codex": "19%"}
        finally:
            restarted.configure({})
    finally:
        finish.set()
        poller.configure({})
        qtbot.waitUntil(lambda: not login.active)
