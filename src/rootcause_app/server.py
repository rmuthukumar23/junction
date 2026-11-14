"""HTTP server for the dashboard. Standard library only.

    GET  /                          the app
    GET  /api/config                scenario title, seed suites
    GET  /api/runs                  every stored run, newest first
    POST /api/runs                  {seed, player} -> a new run (never replaces one)
    GET  /api/runs/<id>/view        what the player may see now (reads only)
    POST /api/runs/<id>/call        {tool, args, expect_day?} -> the engine's reply, as an agent gets it
    GET  /api/runs/<id>/report      result, analysis and comparators; only once the run is over
    GET  /api/runs/<id>/whatif      one-day substitutions on the finished run

The browser holds no state that matters: it renders what `/view` returns and
posts tool calls. Hidden state leaves the server only through `/report` and
`/whatif`, and both refuse until the episode has ended.
"""
from __future__ import annotations

import json
import mimetypes
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from envkit.bundle import ROOT

from . import DEMO_SEED, DEVELOPMENT_SEEDS, EVALUATION_SEEDS
from .analysis import counterfactuals
from .compare import comparators, llm_results
from .store import Conflict, NotFound, RunStore

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024
RUN_PATH = re.compile(r"^/api/runs/([^/]+)/(view|call|report|whatif)$")


class App:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.store = RunStore(self.data_dir)
        self._compare_lock = threading.Lock()

    def config(self) -> dict[str, Any]:
        s = self.store.scenario
        return {"scenario": s.id, "title": s.title, "bundle": self.store.bundle, "days": s.shift.windows,
                "seeds": {"demo": DEMO_SEED, "development": list(DEVELOPMENT_SEEDS), "evaluation": list(EVALUATION_SEEDS)}}

    def handle(self, method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        if method == "GET" and path == "/api/config":
            return 200, self.config()
        if path == "/api/runs":
            if method == "GET":
                return 200, {"runs": self.store.list()}
            if method == "POST":
                body = body if isinstance(body, dict) else {}
                try:
                    run = self.store.create(body.get("seed", DEMO_SEED), body.get("player"))
                except ValueError as e:
                    return 400, {"error": str(e)}
                with run.lock:
                    return 201, {"run": run.summary()}
        match = RUN_PATH.match(path)
        if not match:
            return 404, {"error": "no such endpoint"}
        run = self.store.get(match.group(1))
        action = match.group(2)
        with run.lock:
            if action == "view" and method == "GET":
                return 200, self.store.view(run)
            if action == "call" and method == "POST":
                if not isinstance(body, dict) or not isinstance(body.get("tool"), str):
                    return 400, {"error": "body must be {\"tool\": name, \"args\": {...}}"}
                expect = body.get("expect_day")
                if expect is not None and expect != run.sim.day:
                    # A repeated or stale click: the day it was meant for has already been played.
                    return 409, {"error": f"This request was made on day {expect}, but the run is now on day "
                                          f"{run.sim.day}. Nothing was applied.", "day": run.sim.day}
                return 200, run.call(body["tool"], body.get("args") or {})
            if action == "report" and method == "GET":
                report = self.store.report(run)
                seed = int(run.meta["seed"])
            elif action == "whatif" and method == "GET":
                if not run.episode.done:
                    raise Conflict("What-if analysis uses hidden state and opens only when the episode is over.")
                days = [int(d) for d in query.get("day", []) if d.isdigit()] or None
                return 200, counterfactuals(self.store.scenario, int(run.meta["seed"]), run.records(), days)
            else:
                return 405, {"error": "method not allowed"}
        with self._compare_lock:   # comparators run outside the run's lock; they do not touch it
            report["comparators"] = comparators(self.store.scenario, seed, self.data_dir)
        report["llm"] = llm_results(ROOT, self.store.scenario.id, seed)
        return 200, report


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RootCause/1"

        def log_message(self, format: str, *args: Any) -> None:   # quiet by default
            pass

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.removeprefix("/static/")
            target = (STATIC / rel).resolve()
            if not target.is_relative_to(STATIC) or not target.is_file() or not (path == "/" or path.startswith("/static/")):
                self._send(404, {"error": "not found"})
                return
            data = target.read_bytes()
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", f"{kind}; charset=utf-8" if kind.startswith("text/") or kind.endswith("javascript") else kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _api(self, method: str) -> None:
            url = urlparse(self.path)
            body = None
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self._send(413, {"error": "request too large"})
                    return
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._send(400, {"error": "body is not valid JSON"})
                    return
            try:
                status, payload = app.handle(method, url.path, parse_qs(url.query), body)
            except NotFound as e:
                status, payload = 404, {"error": str(e)}
            except Conflict as e:
                status, payload = 409, {"error": str(e)}
            except Exception as e:   # never leak a traceback, never take the server down
                status, payload = 500, {"error": f"internal error: {type(e).__name__}"}
                self.log_error("%s %s failed: %r", method, url.path, e)
            self._send(status, payload)

        def do_GET(self) -> None:
            if self.path.startswith("/api/"):
                self._api("GET")
            else:
                self._static(urlparse(self.path).path)

        def do_POST(self) -> None:
            if self.path.startswith("/api/"):
                self._api("POST")
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


def serve(host: str, port: int, data_dir: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(App(data_dir)))
    server.daemon_threads = True
    return server
