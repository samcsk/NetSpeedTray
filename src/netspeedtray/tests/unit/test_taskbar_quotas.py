"""Quota providers use local fixtures only. No account or external service required."""
import threading
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from netspeedtray.core import quotas
from netspeedtray.utils import secret_store
from netspeedtray.utils.quota_paint import draw_quotas, quota_height, quota_names, quota_width, split_quota_rect


@pytest.mark.parametrize(("data", "expected"), [
    ({"daily_percentage": 0, "weekly_percentage": 82}, "18% 7d"),
    ({"daily_percentage": 99.5}, "<1% 1d"),
    ({"daily_percentage": 101}, "0% 1d"),
    ({"hide_daily_quota": True, "daily_percentage": 100, "weekly_percentage": 1}, "99% 7d"),
    ({"weekly_percentage": 0}, "100% 7d"),
    ({"weekly_percentage": 100, "has_quota_allocation": False}, "No quota"),
    ({"weekly_percentage": True, "daily_percentage": float("nan")}, "No data"),
])
def test_devin_windows(data, expected):
    assert quotas.devin_readout(data) == expected


def test_codex_uses_window_duration_and_preserves_missing_values():
    result = {"rateLimits": {"primary": {"usedPercent": 60, "windowDurationMins": 300},
                             "secondary": {"usedPercent": 24, "windowDurationMins": 10080}}}
    assert quotas.codex_readout(result) == "40% 5h"
    del result["rateLimits"]["primary"]["usedPercent"]
    assert quotas.codex_readout(result) == "76% 7d"
    assert quotas.codex_readout({"rateLimits": {"primary": None}}) == "No data"


@pytest.mark.parametrize(("status", "expected"), [(200, "85% 1d"), (401, "Sign in"), (302, "Retry"), (429, "Retry")])
def test_devin_request(monkeypatch, status, expected):
    monkeypatch.setattr(secret_store, "unprotect", lambda *_: "Authorization: Bearer test-fixture")
    connection = MagicMock()
    response = connection.return_value.getresponse.return_value
    response.status = status
    response.read.return_value = b'{"daily_percentage":15}'
    monkeypatch.setattr(quotas, "HTTPSConnection", connection)
    assert quotas.fetch_devin("org-example", "fixture") == expected
    assert connection.call_args.args == ("app.devin.ai",)
    request = connection.return_value.request
    assert request.call_args.args == ("GET", "/api/org-example/billing/quota/usage")
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-fixture"
    assert request.call_count == 1
    connection.return_value.close.assert_called_once()


def test_malformed_org_never_contacts_provider(monkeypatch):
    monkeypatch.setattr(secret_store, "unprotect", lambda *_: "fixture")
    monkeypatch.setattr(quotas, "HTTPSConnection", lambda *_a, **_k: pytest.fail("unexpected network call"))
    assert quotas.fetch_devin("//unknown.example", "fixture") == "Set up"


def test_codex_rpc_handshake(tmp_path, monkeypatch):
    import sys
    child = tmp_path / "server.py"
    child.write_text("""
import json, sys
def read():
    return json.loads(input())
def reply(data):
    print(json.dumps(data), flush=True)
assert read()["method"] == "initialize"
reply({"id": 1, "result": {}})
assert read()["method"] == "initialized"
assert read() == {"id": 2, "method": "account/rateLimits/read"}
reply({"method": "account/updated"})
reply({"id": 2, "result": {"rateLimits": {"primary": {"usedPercent": 75, "windowDurationMins": 300}}}})
""", encoding="utf8")
    popen = quotas.subprocess.Popen
    def launch(argv, **kwargs):
        assert argv == ["codex.exe", "app-server"]
        return popen([sys.executable, str(child)], **kwargs)
    monkeypatch.setattr(quotas, "codex_executable", lambda: "codex.exe")
    monkeypatch.setattr(quotas.subprocess, "Popen", launch)
    assert quotas.fetch_codex() == "25% 5h"


@pytest.mark.parametrize("location", [
    "codex.exe",
    "node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe",
    "node_modules/@openai/codex-win32-arm64/vendor/aarch64-pc-windows-msvc/bin/codex.exe",
])
def test_windows_cli_discovery(tmp_path, monkeypatch, location):
    monkeypatch.setattr(quotas.os, "get_exec_path", lambda: [str(tmp_path)])
    (tmp_path / "codex.cmd").touch()
    assert quotas.codex_executable() is None
    exe = tmp_path / location
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.touch()
    assert quotas.codex_executable() == exe


def test_failed_poll_replaces_old_reading(qtbot, monkeypatch):
    monkeypatch.setattr(quotas, "fetch_codex", lambda: "22% 5h")
    poller = quotas.QuotaPoller()
    poller.configure({"quota_codex": True})
    qtbot.waitUntil(lambda: poller.values.get("codex") == "22% 5h")
    def offline():
        raise OSError("offline")
    monkeypatch.setattr(quotas, "fetch_codex", offline)
    poller._poll()
    qtbot.waitUntil(lambda: poller.values.get("codex") == "Retry")
    poller.configure({})


def test_adding_a_provider_keeps_the_scheduled_refresh(qtbot, monkeypatch):
    poller = quotas.QuotaPoller()
    monkeypatch.setattr(poller, "_start", lambda _name: None)
    poller.configure({"quota_devin": True})
    timer_id = poller._timer.timerId()
    poller.configure({"quota_devin": True, "quota_codex": True})
    assert poller._timer.timerId() == timer_id
    poller.configure({})


def test_slow_provider_cannot_overwrite_new_settings(qtbot, monkeypatch):
    started = threading.Event()
    finish = threading.Event()
    def fetch(org, _token):
        if org == "org-first":
            started.set()
            finish.wait(2)
            return "99% 1d"
        return "1% 7d"
    monkeypatch.setattr(quotas, "fetch_devin", fetch)
    monkeypatch.setattr(quotas, "fetch_codex", lambda: "50% 5h")
    poller = quotas.QuotaPoller()
    poller.configure({})
    assert not poller._timer.isActive()
    poller.configure({"quota_devin": True, "quota_devin_org": "org-first", "quota_codex": True})
    try:
        qtbot.waitUntil(lambda: started.is_set() and "codex" in poller.values)
        poller.configure({"quota_devin": True, "quota_devin_org": "org-second"})
        assert poller.values == {}
        finish.set()
        qtbot.waitUntil(lambda: poller.values == {"devin": "1% 7d"})
    finally:
        finish.set()
        poller.configure({})
    assert not poller.values and not poller._timer.isActive()


@pytest.mark.parametrize(("vertical", "height"), [(False, 48), (False, 20), (True, 140)])
def test_panel_draws_values_inside_reserved_space(qapp, vertical, height):
    names = quota_names({"quota_devin": True, "quota_codex": True})
    font = QFont("Arial", 9)
    fm = QFontMetrics(font)
    rect = QRect(0, 0, 52 if vertical else 160 + quota_width(fm, names, height), height)
    base, panel = split_quota_rect(rect, fm, names, vertical)
    assert base.united(panel) == rect and not base.intersects(panel)
    if vertical:
        assert panel.height() == quota_height(fm.height(), names)
    else:
        assert base.width() == 160
    def paint(value):
        img = QImage(rect.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("black"))
        painter = QPainter(img)
        painter.setFont(font)
        draw_quotas(painter, panel, names, {"devin": value, "codex": "52% 5h"}, vertical, "white")
        painter.end()
        return img
    a, b = paint("100% 1d"), paint("Retry")
    assert a.copy(panel) != b.copy(panel)
    assert a.copy(base) == b.copy(base)
