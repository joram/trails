"""
Serve static pages and JSON APIs:

- ``/`` — overview map (geohash viewport)
- ``/island-touring.html`` — Vancouver Island touring routes (table)
- ``GET /api/trails?prefix=`` — GeoJSON by geohash prefix (2–32 chars)
- ``GET /api/region/vancouver-island/trails`` — JSON rows (Vancouver Island, Activities contains ``ski``; includes distance / vert / est. duration)

Run from the repository root::

    python -m trails.map_server

Then open http://127.0.0.1:8765/
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trails.prefix_query import feature_collection_for_prefix, is_valid_geohash_prefix
from trails.region_query import list_vancouver_island_trails


def _dirs() -> tuple[Path, Path]:
    pkg = Path(__file__).resolve().parent
    return pkg / "static", pkg / "data"


class MapRequestHandler(BaseHTTPRequestHandler):
    static_dir: Path = Path(".")
    data_dir: Path = Path(".")

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[map_server] {self.address_string()} - {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path or "/"

        if path == "/api/trails":
            qs = parse_qs(parsed.query)
            raw = (qs.get("prefix") or [""])[0]
            prefix = raw.strip().lower()
            if not is_valid_geohash_prefix(prefix):
                body = json.dumps({"type": "FeatureCollection", "features": []})
                self._send(200, body.encode("utf-8"), "application/geo+json")
                return
            fc = feature_collection_for_prefix(self.data_dir, prefix)
            body = json.dumps(fc, separators=(",", ":"))
            self._send(200, body.encode("utf-8"), "application/geo+json")
            return

        if path == "/api/region/vancouver-island/trails":
            qs = parse_qs(parsed.query)
            refresh = (qs.get("refresh") or [""])[0].lower() in ("1", "true", "yes")
            rows = list_vancouver_island_trails(self.data_dir, refresh=refresh)
            body = json.dumps(rows, separators=(",", ":"))
            self._send(200, body.encode("utf-8"), "application/json; charset=utf-8")
            return

        if path in ("/", "/index.html"):
            index = self.static_dir / "index.html"
            if not index.is_file():
                self._send(404, b"missing static/index.html", "text/plain; charset=utf-8")
                return
            self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            return

        if path == "/island-touring.html":
            page = self.static_dir / "island_touring.html"
            if not page.is_file():
                self._send(404, b"missing static/island_touring.html", "text/plain; charset=utf-8")
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trails map preview server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    static_dir, data_dir = _dirs()
    if not data_dir.is_dir():
        raise SystemExit(f"Trail data directory not found: {data_dir}")

    MapRequestHandler.static_dir = static_dir
    MapRequestHandler.data_dir = data_dir

    server = HTTPServer((args.host, args.port), MapRequestHandler)
    print(f"Serving at http://{args.host}:{args.port}/")
    print(f"  Overview map:      http://{args.host}:{args.port}/")
    print(f"  Island touring:    http://{args.host}:{args.port}/island-touring.html")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
