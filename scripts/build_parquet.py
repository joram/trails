"""
Convert trails/data/**/*.json + *.gpx into a single compressed Parquet file.

Run from the repo root:
    python scripts/build_parquet.py

Output: trails/trails.parquet
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import gpxpy
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pygeohash
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trails.models import TrailFile
from trails.track_metrics import (
    _metrics_for_legs,
    _points_from_gpx,
    _points_from_waypoints,
)


def _resolve_centroid(record: TrailFile):
    """Return (lat, lng) from the record, decoding geohash as fallback."""
    if record.center_lat is not None and record.center_lng is not None:
        return float(record.center_lat), float(record.center_lng)
    gh = (record.center_geohash or "").strip()
    if len(gh) >= 4:
        try:
            loc = pygeohash.decode(gh)
            return float(loc.latitude), float(loc.longitude)
        except (ValueError, TypeError, AttributeError):
            pass
    return None, None


def _extract_waypoints(record: TrailFile, json_path: Path) -> list:
    """
    Return waypoints as a list[list[dict]] (legs × points × {lat, lng, alt}).
    Prefers the embedded JSON waypoints; falls back to the sibling .gpx file.
    """
    if record.waypoints:
        return [
            [{"lat": w.lat, "lng": w.lng, "alt": w.alt} for w in leg]
            for leg in record.waypoints
        ]
    gpx_path = json_path.with_suffix(".gpx")
    if gpx_path.is_file():
        legs_pts = _points_from_gpx(gpx_path)
        return [
            [{"lat": lat, "lng": lng, "alt": alt} for lat, lng, alt in leg]
            for leg in legs_pts
        ]
    return []


def _compute_metrics(record: TrailFile, json_path: Path):
    """Return (distance_km, vertical_gain_m) using JSON waypoints then GPX."""
    legs = []
    if record.waypoints:
        legs = _points_from_waypoints(record.waypoints)
    dist_km, vert_m = _metrics_for_legs(legs)
    if dist_km < 1e-9 and vert_m < 1e-9:
        gpx_path = json_path.with_suffix(".gpx")
        if gpx_path.is_file():
            legs = _points_from_gpx(gpx_path)
            dist_km, vert_m = _metrics_for_legs(legs)
    return dist_km, vert_m


def build():
    data_dir = ROOT / "trails" / "data"
    out_path = ROOT / "trails" / "trails.parquet"

    if not data_dir.is_dir():
        sys.exit(f"Data directory not found: {data_dir}")

    rows = []
    skipped = 0
    for n, json_path in enumerate(sorted(data_dir.rglob("*.json")), 1):
        if json_path.name == "peaks.json":
            continue
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            record = TrailFile.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError, ValidationError) as exc:
            print(f"  skip {json_path.name}: {exc}")
            skipped += 1
            continue

        center_lat, center_lng = _resolve_centroid(record)
        waypoints = _extract_waypoints(record, json_path)
        dist_km, vert_m = _compute_metrics(record, json_path)

        rows.append({
            "trail_id": record.trail_id,
            "title": record.title,
            "description": record.description,
            "directions": record.directions,
            "photos": json.dumps(record.photos),
            "source_url": record.source_url,
            "stats": json.dumps(record.stats.model_dump()),
            "geohash": record.geohash or "",
            "center_lat": center_lat,
            "center_lng": center_lng,
            "center_geohash": record.center_geohash or "",
            "nearest_peak_geohash": record.nearest_peak_geohash or "",
            "waypoints_json": json.dumps(waypoints),
            "distance_km": dist_km,
            "vertical_gain_m": vert_m,
        })

        if n % 500 == 0:
            print(f"  {n} trails processed...")

    print(f"Total: {len(rows)} trails written, {skipped} skipped")

    df = pd.DataFrame(rows)
    df.to_parquet(out_path, compression="zstd", compression_level=19, index=False)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"Wrote {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    build()
