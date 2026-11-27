import json

import pytest

from netspeedtray.core import chatgpt_weekly as weekly


def test_weekly_receiver_lifecycle(tmp_path, monkeypatch):
    receiver = weekly.WeeklyReceiver(tmp_path)
    assert receiver.read() == "Open usage"
    marker = json.loads((tmp_path / "active.json").read_text())
    browser = "a" * 32
    (tmp_path / "browser.json").write_text(json.dumps(browser))
    output = tmp_path / f"weekly-{browser}.json"

    def publish(value):
        output.write_text(json.dumps({"session": marker["session"], "weekly": value}))

    publish({"left": 71})
    assert receiver.read() == "71%"
    publish({"left": True})
    assert receiver.read() == "Open usage"
    publish(None)
    assert receiver.read() == "No data"
    monkeypatch.setattr(weekly, "MAX_AGE", 0)
    assert receiver.read() == "Open usage"
    receiver.stop()
    assert list(tmp_path.iterdir()) == [tmp_path / "browser.json"]
    assert weekly.WeeklyReceiver(tmp_path).read() == "Open usage"


@pytest.mark.parametrize(("data", "expected"), [
    ({"left": 0}, "0%"), ({"left": 100}, "100%"), ({"left": 71, "minutes": 2700}, "71%"),
])
def test_weekly_balance(data, expected):
    assert weekly.weekly_readout(data) == expected
