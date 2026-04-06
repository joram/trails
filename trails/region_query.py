"""Geographic region filters for trail records (bounding boxes)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pygeohash
from pydantic import ValidationError

from trails.models import TrailFile
from trails.track_metrics import estimated_duration_h, track_totals_km_m

# Vancouver Island, BC: axis-aligned bounds (WGS84).
# East edge is set west of Metro Vancouver (-123.12) so mainland trails are excluded.
VANCOUVER_ISLAND_BOUNDS: Tuple[float, float, float, float] = (
    48.15,   # min_lat (south, Juan de Fuca / Victoria area)
    50.98,   # max_lat (north, Cape Scott / Scott Islands)
    -129.65, # min_lng (west, Pacific)
    -123.28, # max_lng (east, Strait of Georgia side of the island)
)


def _centroid(record: TrailFile) -> Optional[Tuple[float, float]]:
    if record.center_lat is not None and record.center_lng is not None:
        return float(record.center_lat), float(record.center_lng)
    gh = (record.center_geohash or "").strip()
    if len(gh) < 4:
        return None
    try:
        loc = pygeohash.decode(gh)
        return float(loc.latitude), float(loc.longitude)
    except (ValueError, TypeError, AttributeError):
        return None


def _in_bounds(
    lat: float,
    lng: float,
    bounds: Tuple[float, float, float, float],
) -> bool:
    min_lat, max_lat, min_lng, max_lng = bounds
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def _row_from_record(record: TrailFile, lat: float, lng: float) -> Dict[str, Any]:
    stats = record.stats.model_dump()
    town = stats.get("Town") or stats.get("town") or ""
    act = stats.get("Activities")
    if act is None:
        act = stats.get("activities")
    activities = "" if act is None or act == "" else str(act)

    return {
        "trail_id": record.trail_id,
        "title": record.title,
        "center_lat": round(lat, 6),
        "center_lng": round(lng, 6),
        "center_geohash": record.center_geohash or "",
        "source_url": record.source_url,
        "town": str(town) if town else "",
        "activities": activities,
    }


def _iter_trails_in_bounds(
    root: Path,
    bounds: Tuple[float, float, float, float],
) -> Iterator[Tuple[Path, TrailFile, float, float]]:
    for json_path in sorted(root.rglob("*.json")):
        if json_path.name == "peaks.json":
            continue
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            record = TrailFile.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError, ValidationError):
            continue

        c = _centroid(record)
        if c is None:
            continue
        lat, lng = c
        if not _in_bounds(lat, lng, bounds):
            continue

        yield json_path, record, lat, lng


def list_trails_in_bounds(
    data_dir: str | Path,
    bounds: Tuple[float, float, float, float] = VANCOUVER_ISLAND_BOUNDS,
) -> List[Dict[str, Any]]:
    """
    All trails whose centroid (``center_lat``/``center_lng``, or decoded
    ``center_geohash``) lies inside the given lat/lng bounding box.
    """
    root = Path(data_dir)
    rows = [
        _row_from_record(record, lat, lng)
        for _, record, lat, lng in _iter_trails_in_bounds(root, bounds)
    ]
    rows.sort(key=lambda r: (r["title"].lower(), r["trail_id"]))
    return rows


def _record_activities_contains_ski(record: TrailFile) -> bool:
    stats = record.stats.model_dump()
    act = stats.get("Activities")
    if act is None:
        act = stats.get("activities")
    act_s = "" if act is None or act == "" else str(act)
    return "ski" in act_s.lower()


_VI_ISLAND_CACHE: Optional[Tuple[str, List[Dict[str, Any]]]] = None


def list_vancouver_island_trails(
    data_dir: str | Path,
    *,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Cached trails inside :data:`VANCOUVER_ISLAND_BOUNDS` whose ``stats.Activities``
    contains the substring ``ski`` (case-insensitive).

    Each row includes ``distance_km``, ``vertical_gain_m`` (positive elevation
    gain along track geometry from JSON waypoints or sibling GPX), and
    ``estimated_duration_h`` using 3 km/h horizontal and 300 m/h vertical.
    """
    global _VI_ISLAND_CACHE
    key = str(Path(data_dir).resolve()) + "#activities~ski#metrics_v2"
    if (
        not refresh
        and _VI_ISLAND_CACHE is not None
        and _VI_ISLAND_CACHE[0] == key
    ):
        return _VI_ISLAND_CACHE[1]

    root = Path(data_dir)
    rows: List[Dict[str, Any]] = []
    for json_path, record, lat, lng in _iter_trails_in_bounds(
        root, VANCOUVER_ISLAND_BOUNDS
    ):
        if not _record_activities_contains_ski(record):
            continue
        d_km, v_m = track_totals_km_m(record, json_path)
        est_h = estimated_duration_h(d_km, v_m)
        row = _row_from_record(record, lat, lng)
        row["distance_km"] = round(d_km, 2)
        row["vertical_gain_m"] = int(round(v_m))
        row["estimated_duration_h"] = round(est_h, 2)
        rows.append(row)

    rows.sort(
        key=lambda r: (
            float(r.get("estimated_duration_h") or 0),
            r["title"].lower(),
            r["trail_id"],
        )
    )
    _VI_ISLAND_CACHE = (key, rows)
    return rows
