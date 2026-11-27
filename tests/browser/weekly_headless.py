"""Exercise the headless reader in Chromium with a temporary profile and local fixtures."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from netspeedtray.core import chatgpt_weekly as weekly

PEER = "<section><span>3% left</span><h2>5-hour limit</h2></section>"
HEADING = "<section role='region'><h2>Weekly limit</h2></section>"
CASES = [
    ("<section>" + HEADING + "<p>Resets tomorrow</p><span>71% left</span></section>" + PEER, "71%"),
    ("<section>" + HEADING + "</section><div><span>9% left</span><b>Another limit</b></div>" + PEER, "No data"),
    (PEER + "<div style='display:contents'><h2>Weekly limit</h2>"
            "<span>Resets in 1d</span><span>64</span><span>% left</span></div>", "64%"),
    (PEER + "<div style='display:contents'><h2>Weekly limit</h2>"
            "<span>Resets </span><span>tomorrow</span><p><span>0</span><span>% left</span></p></div>", "0%"),
    ("<button>Log in</button>", "Sign in"),
    ("<h2>Weekly limit</h2><script>setTimeout(() => document.body.append('88% left'), 150)</script>", "88%"),
]


def main():
    with TemporaryDirectory() as root, sync_playwright() as driver:
        for body, expected in CASES:
            # Each poll starts a fresh browser process on the widget's dedicated profile.
            context = driver.chromium.launch_persistent_context(Path(root), channel="chromium", headless=True)
            try:
                context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=body))
                with patch.object(weekly, "TIMEOUT_MS", 2000):
                    value = weekly.read_page(context.pages[0])
                assert value == expected, (value, expected)
            finally:
                context.close()


if __name__ == "__main__":
    main()
