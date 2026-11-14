"""Trusted per-trial HTTP sidecar. It never exposes reset, files or scoring APIs."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock
from socketserver import TCPServer
from urllib.request import urlopen

from junction_env.scheduling import Instance, ShiftPlanner


class EpisodeHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer's reverse-DNS lookup can stall offline/container startup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class EpisodeService:
    def __init__(self, instance: Instance, record_path: Path):
        self.environment = ShiftPlanner(instance)
        self.record_path = record_path
        self.lock = Lock()
        self.failed = False
        self.persist()

    def persist(self):
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.record_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.environment.record(), sort_keys=True) + "\n")
        temporary.replace(self.record_path)

    def act(self, action: dict) -> dict:
        with self.lock:
            if self.failed:
                raise RuntimeError("service failed; new harness trial required")
            try:
                result = self.environment.step(action)
                self.persist()
            except Exception:
                self.failed = True
                self.record_path.with_suffix(".error").touch()
                raise
            return result.observation

    def handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_json(self, status, value):
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/health":
                    self.send_json(503 if service.failed else 200, {"ready": not service.failed})
                elif self.path == "/observe":
                    with service.lock:
                        observation = service.environment.observe()
                    self.send_json(200, observation)
                else:
                    self.send_json(404, {"error": "unknown route"})

            def do_POST(self):
                if self.path != "/action":
                    self.send_json(404, {"error": "unknown route"})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 16384:
                        self.send_json(413, {"error": "request must be 1..16384 bytes"})
                        return
                    self.connection.settimeout(5)
                    def reject_constant(value):
                        raise ValueError("non-finite JSON number")
                    action = json.loads(self.rfile.read(size), parse_constant=reject_constant)
                except (ValueError, UnicodeError, RecursionError):
                    action = {"tool": "malformed_json"}
                try:
                    self.send_json(200, service.act(action))
                except Exception:
                    self.send_json(500, {"error": "infrastructure failure"})

        return Handler


def collect(record_path: Path, output: Path, base_url: str):
    # Executed by Harbor in the sidecar AFTER stopping the agent container.
    # Only this hook creates the artifact consumed by the separate verifier.
    with urlopen(base_url + "/health", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("environment service unavailable")
    if record_path.with_suffix(".error").exists():
        raise RuntimeError("environment persistence failed")
    record = json.loads(record_path.read_text())
    if not record["final"]["done"]:
        record["final"].update(done=True, termination="harness_interruption")
    output.write_text(json.dumps(record, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--record", type=Path, default=Path("/state/live.json"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--collect", type=Path)
    args = parser.parse_args()
    if args.collect:
        collect(args.record, args.collect, f"http://127.0.0.1:{args.port}")
        return
    if not args.instance:
        parser.error("--instance required for a new trusted episode")
    instance = Instance.from_public(json.loads(args.instance.read_text()))
    service = EpisodeService(instance, args.record)
    EpisodeHTTPServer((args.host, args.port), service.handler()).serve_forever()


if __name__ == "__main__":
    main()
