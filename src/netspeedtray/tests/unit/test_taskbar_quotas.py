"""Quota providers use local fixtures only. No account or external service required."""
from datetime import UTC, datetime, timedelta
import threading
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QRect, Qt
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


def test_reschedule_both_providers_without_refetching_on_save(qtbot, monkeypatch):
    devin = MagicMock(side_effect=["30%", "29%"])
    codex = MagicMock(side_effect=["20%", "19%"])
    monkeypatch.setattr(quotas, "fetch_devin", devin)
    monkeypatch.setattr(chatgpt_weekly, "fetch_weekly", codex)
    poller = quotas.QuotaPoller()
    enabled = {"quota_devin": True, "quota_codex": True}
    try:
        poller.configure({**enabled, "quota_refresh_seconds": 300})
        qtbot.waitUntil(lambda: poller.values == {"devin": "30%", "codex": "20%"})
        assert poller._timer.interval() == 300_000

        poller.configure({**enabled, "quota_refresh_seconds": 30})
        assert poller._timer.isActive() and poller._timer.interval() == 30_000
        assert poller.values == {"devin": "30%", "codex": "20%"}
        poller._timer.timeout.emit()
        qtbot.waitUntil(lambda: poller.values == {"devin": "29%", "codex": "19%"})
        assert devin.call_count == codex.call_count == 2
    finally:
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
        widths = [quota_width(fm, (name,), height) for name in names]
        assert widths[0] < widths[1]
        assert widths[1] >= 8 + fm.horizontalAdvance("ChatGPT  100% 23h 59m")
        assert panel.width() == (max(widths) if height >= len(names) * fm.height() else sum(widths))
    if not QFontDatabase.families():
        pytest.skip("text rasterization requires an installed Qt font")
    def paint(value):
        img = QImage(rect.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("black"))
        painter = QPainter(img)
        painter.setFont(font)
        draw_quotas(painter, panel, names, {"devin": value, "codex": "28% 6d 21h"}, vertical, "white", fm)
        painter.end()
        return img
    a, b = paint("100% 1d"), paint("Retry")
    assert a.copy(panel) != b.copy(panel)
    assert a.copy(base) == b.copy(base)


@pytest.mark.parametrize("height_delta", [-1, 0])
def test_full_chatgpt_countdown_ink_at_layout_switch(qapp, height_delta):
    from netspeedtray.utils.font_runs import draw_text, first_row_baseline

    font = QFont("Arial", 9)
    fm = QFontMetrics(font)
    height = 2 * fm.height() + height_delta
    names = ("Devin", "ChatGPT")
    panel = QRect(0, 0, quota_width(fm, names, height), height)
    actual = QImage(panel.size(), QImage.Format.Format_ARGB32)
    actual.fill(QColor("black"))
    reference = actual.copy()
    value = "100% 23h 59m"
    painter = QPainter(actual)
    painter.setFont(font)
    draw_quotas(painter, panel, names, {"codex": value}, False, "white", fm)
    painter.end()

    # Paint the full ChatGPT text without a clipping rectangle, at its expected baseline.
    if height_delta < 0:
        area = panel.adjusted(quota_width(fm, ("Devin",), height), 0, 0, 0)
    else:
        area = panel.adjusted(0, fm.height(), 0, 0)
    text = f"ChatGPT  {value}"
    painter = QPainter(reference)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    draw_text(painter, area.x() + (area.width() - fm.horizontalAdvance(text)) // 2,
              area.y() + first_row_baseline(fm, area.height(), 1), text)
    painter.end()
    assert actual.copy(area) == reference.copy(area)


@pytest.mark.parametrize("expected", ["28% 23h", "28%"])
def test_vertical_chatgpt_countdown_keeps_units_that_fit(qapp, expected):
    font = QFont("Arial", 9)
    fm = QFontMetrics(font)
    width = fm.horizontalAdvance(expected)
    height = quota_height(fm.height(), ("ChatGPT",))
    margin = 20
    # Leave room either side so the reference draws the entire expected text.
    panel = QRect(margin, 0, width, height)
    actual = QImage(width + 2 * margin, height, QImage.Format.Format_ARGB32)
    actual.fill(QColor("black"))
    reference = actual.copy()
    painter = QPainter(actual)
    painter.setFont(font)
    draw_quotas(painter, panel, ("ChatGPT",), {"codex": "28% 23h 59m"}, True, "white", fm)
    painter.end()
    value_row = actual.rect().adjusted(0, height // 2, 0, 0)
    painter = QPainter(reference)
    painter.setPen(QColor("white"))
    painter.setFont(font)
    painter.drawText(value_row, Qt.AlignmentFlag.AlignCenter, expected)
    painter.end()
    assert actual.copy(value_row) == reference.copy(value_row)
