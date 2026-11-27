"""Quota providers use local fixtures only. No account or external service required."""
from datetime import UTC, datetime, timedelta
import threading
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter

from netspeedtray.core import chatgpt_weekly, quotas
from netspeedtray.utils import secret_store
from netspeedtray.utils.quota_paint import draw_quotas, quota_height, quota_names, quota_width, split_quota_rect


@pytest.fixture(autouse=True)
def isolated_weekly_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(chatgpt_weekly, "profile_dir", lambda: tmp_path / "widget")


@pytest.mark.parametrize(("data", "expected"), [
    ({"daily_percentage": 0, "weekly_percentage": 82}, "18%"),
    ({"daily_percentage": 99.5}, "<1%"),
    ({"daily_percentage": 101}, "0%"),
    ({"hide_daily_quota": True, "daily_percentage": 100, "weekly_percentage": 1}, "99%"),
    ({"weekly_percentage": 0}, "100%"),
    ({"weekly_percentage": 100, "has_quota_allocation": False}, "No quota"),
    ({"weekly_percentage": True, "daily_percentage": float("nan")}, "No data"),
])
def test_devin_windows(data, expected):
    assert str(quotas.devin_readout(data)) == expected


NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
WEEKLY_RESET = "2026-11-29T04:00:00-08:00"


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        instant = NOW

        @classmethod
        def now(cls, tz):
            return cls.instant.astimezone(tz)

    monkeypatch.setattr(quotas, "datetime", Clock)
    return Clock


@pytest.mark.parametrize(("reset", "expected"), [
    (WEEKLY_RESET, "30% 2d"),
    ("2026-11-29T00:00:00Z", "30% 2d"),  # 36 hours rounds to two days on the dashboard.
    (NOW.timestamp() + 2 * 86400, "30% 2d"),
    (int((NOW.timestamp() + 2 * 86400) * 1000), "30% 2d"),
    ("2026-11-27T14:30:00Z", "30% 3h"),
    ("2026-11-27T12:12:30Z", "30% 13m"),
    ("2026-11-27T12:00:45Z", "30% <1m"),
    ("2026-11-27T12:00:00Z", "30%"),
    ("2026-11-26T12:00:00Z", "30%"),
    ("2026-11-29T04:00:00", "30%"),
    ("unknown", "30%"),
    (float("inf"), "30%"),
    (True, "30%"),
])
def test_devin_countdown_for_selected_window(reset, expected, clock):
    data = {"weekly_percentage": 70, "weekly_reset_at": reset,
            "daily_percentage": 10, "daily_reset_at": "2026-11-27T15:00:00Z"}
    assert str(quotas.devin_readout(data)) == expected


def test_devin_honors_window_visibility_when_showing_reset(clock):
    data = {"weekly_percentage": 70, "weekly_reset_at": WEEKLY_RESET,
            "daily_percentage": 85, "daily_reset_at": "2026-11-27T15:00:00Z"}
    assert str(quotas.devin_readout(data)) == "15% 3h"
    data["hide_daily_quota"] = True
    assert str(quotas.devin_readout(data)) == "30% 2d"


def test_countdown_expires_between_polls(qtbot, monkeypatch, clock):
    data = {"weekly_percentage": 70, "weekly_reset_at": (NOW + timedelta(minutes=2)).timestamp()}
    fetch = MagicMock(return_value=quotas.devin_readout(data))
    monkeypatch.setattr(quotas, "fetch_devin", fetch)
    poller = quotas.QuotaPoller()
    poller.configure({"quota_devin": True})
    try:
        qtbot.waitUntil(lambda: poller.values.get("devin") == "30% 2m")
        paused = dict(poller.values)
        clock.instant += timedelta(seconds=90)
        assert poller.values["devin"] == "30% <1m"
        clock.instant += timedelta(seconds=30)
        assert poller.values["devin"] == "30%"
        assert paused == {"devin": "30% 2m"}
        fetch.assert_called_once()
    finally:
        poller.configure({})


@pytest.mark.parametrize(("status", "expected"), [(200, "85%"), (401, "Sign in"), (302, "Retry"), (429, "Retry")])
def test_devin_request(monkeypatch, status, expected):
    monkeypatch.setattr(secret_store, "unprotect", lambda *_: "Authorization: Bearer test-fixture")
    connection = MagicMock()
    response = connection.return_value.getresponse.return_value
    response.status = status
    response.read.return_value = b'{"daily_percentage":15}'
    monkeypatch.setattr(quotas.https, "connection", connection)
    assert str(quotas.fetch_devin("org-example", "fixture")) == expected
    assert connection.call_args.args == ("app.devin.ai",)
    request = connection.return_value.request
    assert request.call_args.args == ("GET", "/api/org-example/billing/quota/usage")
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-fixture"
    assert request.call_count == 1
    connection.return_value.close.assert_called_once()


def test_malformed_org_never_contacts_provider(monkeypatch):
    monkeypatch.setattr(secret_store, "unprotect", lambda *_: "fixture")
    monkeypatch.setattr(quotas.https, "connection", lambda *_a, **_k: pytest.fail("unexpected network call"))
    assert quotas.fetch_devin("//unknown.example", "fixture") == "Set up"


def test_failed_poll_replaces_old_reading(qtbot, monkeypatch):
    monkeypatch.setattr(quotas, "fetch_devin", lambda *_: "22% 1d")
    poller = quotas.QuotaPoller()
    poller.configure({"quota_devin": True})
    qtbot.waitUntil(lambda: poller.values.get("devin") == "22% 1d")
    def offline(*_args):
        raise OSError("offline")
    monkeypatch.setattr(quotas, "fetch_devin", offline)
    poller._poll()
    qtbot.waitUntil(lambda: poller.values.get("devin") == "Retry")
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
    if not QFontDatabase.families():
        pytest.skip("text rasterization requires an installed Qt font")
    def paint(value):
        img = QImage(rect.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("black"))
        painter = QPainter(img)
        painter.setFont(font)
        draw_quotas(painter, panel, names, {"devin": value, "codex": "71%"}, vertical, "white")
        painter.end()
        return img
    a, b = paint("100% 1d"), paint("Retry")
    assert a.copy(panel) != b.copy(panel)
    assert a.copy(base) == b.copy(base)
