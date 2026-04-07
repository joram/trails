"""Geographic region filters for trail records (bounding boxes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from trails.parquet_store import trails_in_bounds
from trails.track_metrics import estimated_duration_h

# Vancouver Island, BC: axis-aligned bounds (WGS84).
# East edge is set west of Metro Vancouver (-123.12) so mainland trails are excluded.
VANCOUVER_ISLAND_BOUNDS: Tuple[float, float, float, float] = (
    48.15,    # min_lat (south, Juan de Fuca / Victoria area)
    50.98,    # max_lat (north, Cape Scott / Scott Islands)
    -129.65,  # min_lng (west, Pacific)
    -123.28,  # max_lng (east, Strait of Georgia side of the island)
)


def _record_activities_contains_ski(stats: Dict[str, Any]) -> bool:
    act = stats.get("Activities") or stats.get("activities") or ""
    return "ski" in str(act).lower()


def list_trails_in_bounds(
    data_dir: str | Path,
    bounds: Tuple[float, float, float, float] = VANCOUVER_ISLAND_BOUNDS,
) -> List[Dict[str, Any]]:
    """
    All trails whose centroid lies inside the given lat/lng bounding box.
    """
    rows = [
        {
            "trail_id": t["trail_id"],
            "title": t["title"],
            "center_lat": round(t["center_lat"], 6),
            "center_lng": round(t["center_lng"], 6),
            "center_geohash": t["center_geohash"],
            "source_url": t["source_url"],
            "town": str(t["stats"].get("Town") or t["stats"].get("town") or ""),
            "activities": str(
                t["stats"].get("Activities") or t["stats"].get("activities") or ""
            ),
        }
        for t in trails_in_bounds(bounds)
    ]
    rows.sort(key=lambda r: (r["title"].lower(), r["trail_id"]))
    return rows


_VI_ISLAND_CACHE: Optional[Tuple[str, List[Dict[str, Any]]]] = None


def list_vancouver_island_trails(
    data_dir: str | Path,
    *,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Cached trails inside :data:`VANCOUVER_ISLAND_BOUNDS` whose ``stats.Activities``
    contains the substring ``ski`` (case-insensitive).

    Each row includes ``distance_km``, ``vertical_gain_m``, and
    ``estimated_duration_h`` using 3 km/h horizontal and 300 m/h vertical.
    """
    global _VI_ISLAND_CACHE
    key = str(Path(data_dir).resolve()) + "#activities~ski#metrics_v2"
    if not refresh and _VI_ISLAND_CACHE is not None and _VI_ISLAND_CACHE[0] == key:
        return _VI_ISLAND_CACHE[1]

    rows: List[Dict[str, Any]] = []
    for t in trails_in_bounds(VANCOUVER_ISLAND_BOUNDS):
        if not _record_activities_contains_ski(t["stats"]):
            continue
        d_km = t["distance_km"]
        v_m = t["vertical_gain_m"]
        est_h = estimated_duration_h(d_km, v_m)
        rows.append({
            "trail_id": t["trail_id"],
            "title": t["title"],
            "center_lat": round(t["center_lat"], 6),
            "center_lng": round(t["center_lng"], 6),
            "center_geohash": t["center_geohash"],
            "source_url": t["source_url"],
            "town": str(t["stats"].get("Town") or t["stats"].get("town") or ""),
            "activities": str(
                t["stats"].get("Activities") or t["stats"].get("activities") or ""
            ),
            "distance_km": round(d_km, 2),
            "vertical_gain_m": int(round(v_m)),
            "estimated_duration_h": round(est_h, 2),
        })

    rows.sort(
        key=lambda r: (
            float(r.get("estimated_duration_h") or 0),
            r["title"].lower(),
            r["trail_id"],
        )
    )
    _VI_ISLAND_CACHE = (key, rows)
    return rows
