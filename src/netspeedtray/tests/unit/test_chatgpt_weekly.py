"""Exercise profile ownership and sign-in lifecycle without using an actual account."""
import threading
from unittest.mock import Mock

from netspeedtray.core import chatgpt_weekly as weekly, quotas


def test_first_poll_requests_sign_in_without_creating_profile(tmp_path, monkeypatch):
    folder = tmp_path / "new-profile"
    monkeypatch.setattr(weekly, "profile_dir", lambda: folder)
    assert weekly.fetch_weekly() == "Sign in"
    assert not folder.exists()


def test_close_sign_in_refreshes_enabled_provider(qtbot, tmp_path, monkeypatch):
    folder = tmp_path / "dedicated"
    edge = tmp_path / "msedge.exe"
    close_window = threading.Event()
    launched = threading.Event()
    calls = []

    def browser(args, **kwargs):
        calls.append(args)
        launched.set()
        assert close_window.wait(3)

    monkeypatch.setattr(weekly, "profile_dir", lambda: folder)
    monkeypatch.setattr(weekly, "edge_executable", lambda: edge)
    monkeypatch.setattr(weekly.subprocess, "run", browser)
    poller = quotas.QuotaPoller()
    frozen = {"devin": "62% 7d", "codex": "35%"}
    poller.account_changed.connect(lambda provider: frozen.pop(provider, None))
    login = weekly.sign_in_window()
    try:
        login.open()
        login.open()  # A second click cannot start a second browser on the same profile.
        qtbot.waitUntil(launched.is_set)
        assert calls[0][0] == str(edge) and calls[0][-1] == weekly.USAGE
        assert f"--user-data-dir={folder}" in calls[0] and len(calls) == 1
        assert weekly.fetch_weekly() == "Sign in"
        fetch = Mock(return_value="71%")
        monkeypatch.setattr(weekly, "fetch_weekly", fetch)
        poller.configure({"quota_codex": True})
        assert poller.values == {"codex": "Sign in"}
        fetch.assert_not_called()
        close_window.set()
        qtbot.waitUntil(lambda: poller.values == {"codex": "71%"})
        fetch.assert_called_once()
        assert frozen == {"devin": "62% 7d"}
    finally:
        close_window.set()
        poller.configure({})
        qtbot.waitUntil(lambda: not login.active)
