"""Greenhouse Bench pixel site server (stdlib only): replays recorded runs as a pixel greenhouse.

    python scripts/pixel/server.py [--port 8800] [--artifacts <dir>] [--policy-scenario normal-winter]
    python scripts/pixel/server.py --selftest          # replays scenarios/smoke.toml, prints sizes

API: GET /api/runs, /api/runs/<id>, /api/stats. See docs/features/pixel-site.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import mimetypes
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import replay as rp  # noqa: E402
import runs as runs_mod  # noqa: E402

PLACEHOLDER = (b"<!doctype html><meta charset=utf-8><title>Greenhouse Bench</title>"
               b"<body style='font:16px sans-serif;padding:2em'><h1>Greenhouse Bench pixel site</h1>"
               b"<p>index.html has not been built yet. The API is up: "
               b"<a href=/api/runs>/api/runs</a>, <a href=/api/stats>/api/stats</a>.</p>")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
         ".png": "image/png", ".webp": "image/webp", ".mjs": "text/javascript; charset=utf-8"}
STATE: dict[str, object] = {}


def safe_path(rel: str) -> Path | None:
    """A file inside scripts/pixel/ by relative name; None for anything that escapes it."""
    if not rel or "\x00" in rel or "\\" in rel:
        return None
    p = (HERE / rel).resolve()
    try:
        p.relative_to(HERE)
    except ValueError:
        return None
    if any(part.startswith(".") for part in Path(rel).parts) or p.suffix in (".py", ".pyc"):
        return None
    return p if p.is_file() else None


def load_stats(runs: runs_mod.Runs):
    """compute_stats(runs, load_replay) from analytics.py (another agent's file), loaded fresh."""
    path = HERE / "analytics.py"
    if not path.is_file():
        raise ImportError("analytics.py is missing")
    spec = importlib.util.spec_from_file_location("pixel_analytics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute_stats(runs.list(), runs.replay)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, separators=(",", ":"), default=str).encode(), "application/json")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._route(urlparse(self.path).path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # the server survives any failure
            sys.stderr.write(traceback.format_exc())
            try:
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass

    def _route(self, path: str) -> None:
        runs: runs_mod.Runs = STATE["runs"]  # type: ignore[assignment]
        if path == "/api/runs":
            self._json(200, {"runs": runs.list()})
        elif path.startswith("/api/runs/"):
            run_id = unquote(path[len("/api/runs/"):])
            if run_id.startswith("policy:") and runs.find(run_id) is None:
                self._json(404, {"error": f"unknown policy run '{run_id}'"})
                return
            try:
                out = runs.replay(run_id)
            except FileNotFoundError as exc:
                self._json(422, {"error": str(exc)})
                return
            except Exception as exc:
                sys.stderr.write(traceback.format_exc())
                self._json(500, {"error": f"replay failed: {type(exc).__name__}: {exc}"})
                return
            if out is None:
                self._json(404, {"error": f"unknown run '{run_id}'"})
            else:
                self._json(200, out)
        elif path == "/api/stats":
            try:
                self._json(200, load_stats(runs))
            except ImportError:
                self._json(200, {"error": "analytics not built yet"})
            except Exception as exc:
                sys.stderr.write(traceback.format_exc())
                self._json(200, {"error": f"analytics failed: {type(exc).__name__}: {exc}"})
        elif path.startswith("/api/"):
            self._json(404, {"error": "unknown endpoint"})
        else:
            rel = "index.html" if path == "/" else unquote(path).lstrip("/")
            f = safe_path(rel)
            if f is None:
                if rel == "index.html":
                    self._send(200, PLACEHOLDER, "text/html; charset=utf-8")
                else:
                    self._json(404, {"error": "not found"})
                return
            ctype = TYPES.get(f.suffix) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self._send(200, f.read_bytes(), ctype)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("pixel: " + fmt % args + "\n")


def selftest() -> int:
    t0 = time.time()
    out = rp.selftest("smoke")
    sizes = {k: len(json.dumps(v)) for k, v in out.items()}
    print(f"selftest ok in {time.time() - t0:.2f}s: frames={len(out['frames'])} actions={len(out['actions'])} "
          f"events={len(out['events'])} alarms={len(out['alarms'])} daily={len(out['daily'])} "
          f"verified={out['meta']['replay_verified']} bytes={sizes}")
    return 0 if out["meta"]["replay_verified"] and len(out["frames"]) == 25 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--artifacts", default=None, help="directory scanned for Harbor trial traces")
    ap.add_argument("--policy-scenario", default="normal-winter", help="scenario the scripted policy runs play")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    STATE["runs"] = runs_mod.Runs(Path(a.artifacts) if a.artifacts else None, a.policy_scenario)
    print(f"Greenhouse pixel site on http://127.0.0.1:{a.port}  artifacts={STATE['runs'].artifacts}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
