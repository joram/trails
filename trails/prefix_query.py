"""Resolve trails whose ``center_geohash`` matches a prefix (for map viewport queries)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import gpxpy
from geojson import Feature, FeatureCollection, MultiLineString, Point

from trails.models import TrailFile, Waypoint

_GEOHASH_PREFIX_RE = re.compile(r"^[0-9b-hjkmnp-z]{2,32}$")


def longest_common_prefix(strings: List[str]) -> str:
    if not strings:
        return ""
    s0 = strings[0]
    for i, c in enumerate(s0):
        for s in strings[1:]:
            if i >= len(s) or s[i] != c:
                return s0[:i]
    return s0


def is_valid_geohash_prefix(prefix: str) -> bool:
    return bool(prefix and _GEOHASH_PREFIX_RE.match(prefix))


def _waypoints_model_to_lines(
    waypoints: Optional[List[List[Waypoint]]],
) -> List[List[List[float]]]:
    if not waypoints:
        return []
    lines: List[List[List[float]]] = []
    for leg in waypoints:
        line = [[w.lng, w.lat] for w in leg]
        if len(line) >= 2:
            lines.append(line)
    return lines


def _lines_from_gpx(gpx_path: Path) -> List[List[List[float]]]:
    try:
        raw = gpx_path.read_text(encoding="utf-8", errors="replace")
        gpx = gpxpy.parse(raw)
    except (OSError, UnicodeError, ValueError):
        return []
    lines: List[List[List[float]]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            pts = [[p.longitude, p.latitude] for p in segment.points]
            if len(pts) >= 2:
                lines.append(pts)
    for wp in gpx.waypoints:
        lines.append([[wp.longitude, wp.latitude]])
    return lines


def _feature_for_record(
    json_path: Path,
    record: TrailFile,
) -> Optional[Feature]:
    lines = _waypoints_model_to_lines(record.waypoints)
    if not lines:
        gpx_path = json_path.with_suffix(".gpx")
        if gpx_path.is_file():
            raw_lines = _lines_from_gpx(gpx_path)
            lines = [ln for ln in raw_lines if len(ln) >= 2]

    props: Dict[str, Any] = {
        "trail_id": record.trail_id,
        "title": record.title,
        "center_geohash": record.center_geohash or "",
        "source_url": record.source_url,
    }

    if lines:
        return Feature(
            geometry=MultiLineString(coordinates=lines),
            properties=props,
            id=record.trail_id,
        )

    lat, lng = record.center_lat, record.center_lng
    if lat is not None and lng is not None:
        return Feature(
            geometry=Point(coordinates=(lng, lat)),
            properties=props,
            id=record.trail_id,
        )
    return None


def _json_paths_for_geohash_prefix(root: Path, prefix: str) -> List[Path]:
    """Paths under ``root`` that can contain trails whose geohash starts with ``prefix``."""
    if len(prefix) >= 4:
        bucket = root / prefix[0] / prefix[1] / prefix[2] / prefix[3]
        if not bucket.is_dir():
            return []
        return sorted(bucket.glob("*.json"))
    if len(prefix) == 3:
        base = root / prefix[0] / prefix[1] / prefix[2]
    elif len(prefix) == 2:
        base = root / prefix[0] / prefix[1]
    else:
        return []
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.json"))


def feature_collection_for_prefix(data_dir: str | Path, prefix: str) -> FeatureCollection:
    """
    Trails whose ``center_geohash`` starts with ``prefix`` (case-insensitive).
    For prefixes of four or more characters, only the corresponding leaf bucket is scanned;
    shorter prefixes scan all nested buckets under the matching path prefix.
    """
    prefix = prefix.strip().lower()
    if not is_valid_geohash_prefix(prefix):
        return FeatureCollection([])

    root = Path(data_dir)
    paths = _json_paths_for_geohash_prefix(root, prefix)
    if not paths:
        return FeatureCollection([])

    features: List[Feature] = []
    for json_path in paths:
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            record = TrailFile.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        gh = (record.center_geohash or "").lower()
        if not gh.startswith(prefix):
            continue
        feat = _feature_for_record(json_path, record)
        if feat is not None:
            features.append(feat)

    return FeatureCollection(features)
