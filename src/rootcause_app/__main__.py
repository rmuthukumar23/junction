"""Serve the Root Cause dashboard.

    python -m rootcause_app [--host 127.0.0.1] [--port 8765] [--data artifacts/rootcause]

Needs nothing but Python 3.12+: no packages, no build step, no credentials.
Runs are stored under --data and survive a restart.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from envkit.bundle import ROOT

from .server import serve


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rootcause_app", description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: this machine only)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", type=Path, default=ROOT / "artifacts" / "rootcause",
                    help="where runs and comparator results are stored")
    a = ap.parse_args(argv)
    server = serve(a.host, a.port, a.data)
    print(f"Root Cause is running at http://{a.host}:{server.server_address[1]}/   (runs stored in {a.data})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
