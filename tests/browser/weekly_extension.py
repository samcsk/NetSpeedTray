"""Run with PYTHONPATH=src and Playwright Chromium installed. Uses no account or external site."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

from netspeedtray.core.chatgpt_weekly import WeeklyReceiver

EXTENSION = Path(__file__).resolve().parents[2] / "assets" / "chatgpt-weekly"
USAGE = "https://chatgpt.com/settings/usage"
CARD = """<section><h2>Weekly limit</h2><p>Resets at your quota limit tomorrow</p><span>71% left</span></section>
          <section><h2>5-hour limit</h2><span>3% left</span></section>"""


def main():
    with TemporaryDirectory() as root, sync_playwright() as playwright:
        folder = Path(root) / "widget"
        receiver = WeeklyReceiver(folder)
        assert receiver.read() == "Open usage"
        context = playwright.chromium.launch_persistent_context(
            Path(root) / "profile", channel="chromium", headless=True,
            args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
        try:
            worker = next(iter(context.service_workers), None) or context.wait_for_event("serviceworker")
            connect = context.new_page()
            connect.goto(worker.url.replace("background.js", "connect.html"))
            # Exercise the connect screen and the same filesystem API without a native OS picker.
            connect.evaluate("""async marker => {
                const directory = await navigator.storage.getDirectory();
                const file = await directory.getFileHandle('active.json', {create: true});
                const writer = await file.createWritable();
                await writer.write(marker);
                await writer.close();
                window.showDirectoryPicker = async () => directory;
            }""", (folder / "active.json").read_text())
            connect.locator("#connect").click()
            connect.locator("#usage").wait_for(state="visible", timeout=6000)
            context.route(USAGE + "**", lambda route: route.fulfill(content_type="text/html", body=CARD))
            usage = context.new_page()
            usage.goto(USAGE + "/")
            connect.locator("#usage").click()
            connect.wait_for_function("""async () => {
                const {folder, id} = await connectionFolder();
                try { return (await (await folder.getFileHandle('weekly-' + id + '.json')).getFile()).size > 0; }
                catch { return false; }
            }""", timeout=10000)
            snapshot = connect.evaluate("""async () => {
                const {folder, id} = await connectionFolder();
                const file = await (await folder.getFileHandle('weekly-' + id + '.json')).getFile();
                return [id, await file.text()];
            }""")
            browser, data = snapshot
            (folder / "browser.json").write_text(json.dumps(browser))
            (folder / f"weekly-{browser}.json").write_text(data)
            assert json.loads(data)["weekly"] == {"left": 71}
            assert receiver.read() == "71%"

            # A second profile paired the same widget. Restoring the old handle must not
            # reclaim ownership until the user explicitly chooses the folder again.
            await_takeover = """async () => {
                const {folder} = await connectionFolder();
                const owner = await folder.getFileHandle('browser.json');
                const writer = await owner.createWritable();
                await writer.write(JSON.stringify('b'.repeat(32)));
                await writer.close();
            }"""
            connect.evaluate(await_takeover)
            connect.reload()
            connect.wait_for_function("document.querySelector('#status').textContent.includes('no longer connected')")
            assert connect.locator("#usage").is_hidden()
            connect.evaluate("window.showDirectoryPicker = () => navigator.storage.getDirectory(); void 0")
            connect.locator("#connect").click()
            connect.locator("#usage").wait_for(state="visible")
            assert connect.evaluate("connectionFolder().then(isPaired)")
        finally:
            context.close()
            receiver.stop()


if __name__ == "__main__":
    main()
