"""Browser smoke test: play a whole season in a real browser and check every screen.

Starts the dashboard on a free port with a scratch data directory, drives headless
Chrome over the DevTools protocol, and fails on any JavaScript error, failed request
or missing element. Screenshots of each screen are written for inspection.

    uv run --no-sync python scripts/browser_smoke.py [--out artifacts/rootcause/smoke]

Needs Google Chrome (or CHROME=/path/to/chrome) and the `websockets` package, which the
locked environment already contains. Nothing is downloaded.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or "",
]


class Tab:
    """A minimal DevTools client for one page."""

    def __init__(self, ws_url: str):
        from websockets.sync.client import connect
        self.ws = connect(ws_url, max_size=None, open_timeout=20)
        self.n = 0
        self.problems: list[str] = []
        for domain in ("Page", "Runtime", "Log", "Network"):
            self.send(f"{domain}.enable")

    def send(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=60))
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._event(msg)

    def _event(self, msg: dict) -> None:
        method, p = msg.get("method"), msg.get("params", {})
        if method == "Runtime.exceptionThrown":
            d = p["exceptionDetails"]
            self.problems.append("uncaught: " + (d.get("exception", {}).get("description") or d.get("text", "")))
        elif method == "Log.entryAdded" and p["entry"]["level"] == "error":
            self.problems.append(f"log error: {p['entry'].get('text')} {p['entry'].get('url', '')}")
        elif method == "Runtime.consoleAPICalled" and p.get("type") == "error":
            self.problems.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"]))
        elif method == "Network.responseReceived" and p["response"]["status"] >= 500:
            self.problems.append(f"HTTP {p['response']['status']} {p['response']['url']}")

    def js(self, expression: str):
        r = self.send("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(f"JS failed: {r['exceptionDetails'].get('exception', {}).get('description')}\n  in: {expression}")
        return r["result"].get("value")

    def wait(self, expression: str, what: str, timeout: float = 15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = self.js(expression)
            if value:
                return value
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {what}\n  heading: {self.js('document.querySelector(`h1`)?.textContent')}"
                             f"\n  alerts: {self.js('[...document.querySelectorAll(`[role=alert]`)].map(e => e.textContent).join(` | `)')}")

    def click(self, text: str, selector: str = "button, a.btn") -> None:
        found = self.js(f"""(() => {{
            const el = [...document.querySelectorAll({json.dumps(selector)})].find(e => e.textContent.trim().startsWith({json.dumps(text)}) && !e.disabled);
            if (!el) return false; el.click(); return true; }})()""")
        if not found:
            raise AssertionError(f"no enabled control starting with {text!r}")

    def fill(self, selector: str, value) -> None:
        ok = self.js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;
            el.value = {json.dumps(str(value))}; el.dispatchEvent(new Event('input', {{bubbles: true}})); return true; }})()""")
        if not ok:
            raise AssertionError(f"no input {selector}")

    def text(self, selector: str = "main") -> str:
        return self.js(f"document.querySelector({json.dumps(selector)})?.innerText || ''") or ""

    def shot(self, path: Path, width: int = 1360) -> None:
        height = int(self.js("Math.ceil(document.documentElement.scrollHeight)") or 900)
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=min(height, 6000), deviceScaleFactor=1, mobile=False)
        data = self.send("Page.captureScreenshot", format="png", captureBeyondViewport=True)["data"]
        path.write_bytes(base64.b64decode(data))
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=900, deviceScaleFactor=1, mobile=False)


def check(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok  {message}")


def play(tab: Tab, base: str, out: Path) -> None:
    heading = "document.querySelector('main h1')?.textContent"
    day = "document.querySelector('.hud .big')?.textContent.trim()"
    tab.send("Emulation.setDeviceMetricsOverride", width=1360, height=900, deviceScaleFactor=1, mobile=False)
    tab.send("Page.navigate", url=base + "/")

    print("start screen")
    tab.wait(f"{heading} === 'Same sensor reading. Opposite problem.'", "the start screen")
    start = tab.text()
    check("14 days" in start and "most profit" in start and "scarce water" in start, "objective, horizon and resources are stated")
    check("overfed" in start and "starving in salt" in start, "EC ambiguity is shown")
    check(len(start.split()) < 130, f"the start screen is short ({len(start.split())} words)")
    tab.shot(out / "1-start.png")
    tab.fill("#player", "Smoke Test")
    tab.click("Start")

    print("day 1")
    tab.wait(f"{day} === '1 / 14'", "the game screen")
    check(tab.js("document.querySelectorAll('.bay').length") == 4 and tab.js("!!document.querySelector('.scene-svg')"), "greenhouse with four bays")
    check(tab.js("document.querySelectorAll('.forecast .fc').length") == 7, "a seven-day forecast")
    check(tab.js("document.querySelectorAll('.ecbar .unknown').length") == 4, "every EC bar starts unsplit")
    words = len(tab.text().split())
    check(words < 230, f"the game screen is short ({words} words)")
    tab.click("Test", ".bay:nth-of-type(3) button")
    tab.wait("document.querySelector('.bay:nth-of-type(3)').innerText.includes('result tomorrow')", "the pending test")
    check("€25 spent" in tab.text(".hud"), "the test fee is charged at once")
    check(tab.js("!document.querySelector('.bay:nth-of-type(3) .bay-ec button')"), "a second sample today is not offered")

    print("plan validation")
    for zone in "ABCD":
        tab.fill(f"#{zone}-irrigation_l", 450)
    tab.wait("document.querySelector('.actionbar [role=alert]')?.innerText.includes('only 1,600 L can be delivered today')", "the shared-water message")
    check(tab.js("document.querySelector('.go').disabled"), "Next day is disabled while the plan is invalid")
    tab.fill("#A-irrigation_l", 99999)
    check(tab.js("document.querySelector('#A-irrigation_l').value") == "600", "a slider cannot exceed the per-zone limit")
    tab.shot(out / "2-invalid-plan.png")
    for zone in "ABCD":
        tab.fill(f"#{zone}-irrigation_l", 230)
    tab.wait("!document.querySelector('.actionbar [role=alert]')", "the error to clear")
    tab.fill("#C-fertilizer_g", 500)
    check("Cost today" in tab.text(".actionbar"), "the cost of today's plan is shown before committing")
    tab.click("Details", "summary")
    tab.wait("document.querySelectorAll('.drawer .chart-svg').length >= 16", "charts in the details drawer")
    check("EC sensor" not in tab.text(".house"), "detail text stays out of the main view")
    tab.shot(out / "3-day0.png")

    print("advance")
    tab.js("""(() => { const b = document.querySelector('.go'); b.click(); b.click(); b.click(); return true; })()""")
    tab.wait(f"{day} === '2 / 14'", "day 2 (after a triple click)")
    check("Yesterday:" in tab.text(".flash"), "a one-line report of the day")
    check(tab.js("!!document.querySelector('.bay:nth-of-type(3) .ecbar .nut') && !!document.querySelector('.bay:nth-of-type(3) .ecbar .salt')"),
          "the tested bay's EC bar is now split into nutrients and salts")
    check("as of day 0" in tab.text(".bay:nth-of-type(3)"), "the result is stamped with its sample day")
    check(tab.js("document.querySelector('#C-fertilizer_g').value") == "500", "yesterday's settings carry over into today's sliders")
    tab.fill("#C-flush_l", 400)
    tab.shot(out / "4-day1.png")
    for n in range(1, 14):
        tab.js("document.querySelector('.go').click()")
        if n < 13:
            tab.wait(f"{day} === '{n + 2} / 14'", f"day {n + 2}")
    print("end screen")
    tab.wait("document.querySelectorAll('.bars .bar-row').length === 5", "the end screen with comparator bars")
    end = tab.text()
    for needle in ("Net profit", "Score", "Do nothing", "Stop early", "Rule-based", "Reference planner", "not run yet", "What each zone really was"):
        check(needle.lower() in end.lower(), f"end screen shows “{needle}”")
    tab.click("How the profit was calculated", "summary")
    tab.wait("document.querySelector('main').innerText.includes('Harvest sold')", "the itemized calculation")
    for needle in ("Fresh water", "Fertilizer", "Discharge to waste", "Lab tests", "Recomputed from"):
        check(needle in tab.text(), f"calculation shows “{needle}”")
    tab.click("What-if", "summary")
    tab.click("Run the what-if analysis")
    tab.wait("document.querySelector('main').innerText.includes('Instead, on that day only')", "the what-if table")
    tab.shot(out / "5-end.png")

    print("replay")
    tab.click("Replay day by day")
    tab.wait(f"{heading} === 'Replay'", "the replay screen")
    check("Post-episode analysis" in tab.text() and "Hidden at the time" in tab.text(), "hidden state is labelled as post-episode")
    tab.click("Next day")
    tab.wait("document.querySelector('.replay-day b').textContent === 'Day 1'", "replay day 1")
    check("player's plan" in tab.text(), "the replay shows which plan was applied")
    tab.shot(out / "6-replay.png")

    print("restart")
    tab.click("New run")
    tab.wait(f"{heading} === 'Same sensor reading. Opposite problem.'", "the start screen again")
    tab.fill("#player", "Second Run")
    tab.click("Start")
    tab.wait(f"{day} === '1 / 14'", "a fresh run")
    check("€0 spent" in tab.text(".hud"), "the new run starts from zero")
    tab.send("Page.navigate", url=base + "/#/runs")
    tab.wait("document.querySelectorAll('main tbody tr').length === 2", "both runs listed")
    runs = tab.text()
    check("Smoke Test" in runs and "finished" in runs and "Second Run" in runs and "in progress" in runs,
          "the earlier result is kept next to the new run")
    check("no result yet" in runs and runs.count("€") == 1, "an unfinished run shows no result and no projection")
    tab.shot(out / "7-runs.png")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "rootcause" / "smoke")
    a = ap.parse_args()
    chrome = next((c for c in CHROME_CANDIDATES if c and Path(c).exists()), None)
    if chrome is None:
        print("NOT RUN: no Chrome found; set CHROME=/path/to/chrome")
        return 2
    a.out.mkdir(parents=True, exist_ok=True)

    from rootcause_app.server import serve
    with tempfile.TemporaryDirectory() as tmp:
        server = serve("127.0.0.1", 0, Path(tmp) / "data")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        profile = Path(tmp) / "chrome"
        proc = subprocess.Popen([chrome, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
                                 "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--remote-allow-origins=*",
                                 "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port_file = profile / "DevToolsActivePort"
            for _ in range(200):
                if port_file.exists() and port_file.read_text().strip():
                    break
                time.sleep(0.05)
            port = port_file.read_text().split()[0]
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10))
            tab = Tab(next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page"))
            play(tab, base, a.out)
            if tab.problems:
                print("FAILED: the browser reported problems:")
                for p in tab.problems:
                    print("  ", p)
                return 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            server.shutdown()
    print(f"\nBrowser smoke test passed. Screenshots: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
