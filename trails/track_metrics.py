"""Horizontal distance, vertical gain, and naive time estimates from track geometry."""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

import gpxpy

from trails.models import TrailFile, Waypoint

# Estimated pace for duration (island touring heuristics).
HORIZONTAL_KM_PER_HOUR = 3.0
VERTICAL_METERS_PER_HOUR = 300.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


Point = Tuple[float, float, Optional[float]]


def _horizontal_distance_km(points: List[Point]) -> float:
    if len(points) < 2:
        return 0.0
    d = 0.0
    for i in range(1, len(points)):
        lat1, lon1, _ = points[i - 1]
        lat2, lon2, _ = points[i]
        d += _haversine_km(lat1, lon1, lat2, lon2)
    return d


def _vertical_gain_m(points: List[Point]) -> float:
    gain = 0.0
    prev_alt: Optional[float] = None
    for _, _, alt in points:
        if alt is None:
            continue
        if prev_alt is not None and alt > prev_alt:
            gain += alt - prev_alt
        prev_alt = alt
    return gain


def _points_from_waypoints(waypoints: List[List[Waypoint]]) -> List[List[Point]]:
    legs: List[List[Point]] = []
    for leg in waypoints:
        legs.append([(w.lat, w.lng, w.alt) for w in leg])
    return legs


def _points_from_gpx(path: Path) -> List[List[Point]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        gpx = gpxpy.parse(raw)
    except (OSError, UnicodeError, ValueError):
        return []
    legs: List[List[Point]] = []
    for track in gpx.tracks:
        for seg in track.segments:
            pts: List[Point] = [
                (p.latitude, p.longitude, p.elevation) for p in seg.points
            ]
            if len(pts) >= 2:
                legs.append(pts)
    for w in gpx.waypoints:
        legs.append([(w.latitude, w.longitude, w.elevation)])
    return legs


def _metrics_for_legs(legs: List[List[Point]]) -> Tuple[float, float]:
    dist_km = 0.0
    vert_m = 0.0
    for leg in legs:
        if len(leg) < 2:
            continue
        dist_km += _horizontal_distance_km(leg)
        vert_m += _vertical_gain_m(leg)
    return dist_km, vert_m


def track_totals_km_m(record: TrailFile, json_path: Path) -> Tuple[float, float]:
    """
    Sum horizontal distance (km) and positive vertical gain (m) over all legs/segments
    from JSON ``waypoints``, falling back to sibling ``.gpx`` when there is no usable
    polyline in JSON (empty, missing, or only single-point legs).
    """
    legs: List[List[Point]] = []
    if record.waypoints:
        legs.extend(_points_from_waypoints(record.waypoints))
    dist_km, vert_m = _metrics_for_legs(legs)

    gpx_path = json_path.with_suffix(".gpx")
    if gpx_path.is_file() and dist_km < 1e-9 and vert_m < 1e-9:
        legs = _points_from_gpx(gpx_path)
        dist_km, vert_m = _metrics_for_legs(legs)

    return dist_km, vert_m


def estimated_duration_h(distance_km: float, vertical_gain_m: float) -> float:
    """Hours = horizontal time at ``HORIZONTAL_KM_PER_HOUR`` plus vertical at ``VERTICAL_METERS_PER_HOUR``."""
    h = 0.0
    if HORIZONTAL_KM_PER_HOUR > 0:
        h += distance_km / HORIZONTAL_KM_PER_HOUR
    if VERTICAL_METERS_PER_HOUR > 0:
        h += vertical_gain_m / VERTICAL_METERS_PER_HOUR
    return h
