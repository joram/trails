"""Resolve trails whose ``center_geohash`` matches a prefix (for map viewport queries)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from geojson import Feature, FeatureCollection, MultiLineString, Point

from trails.parquet_store import trails_for_geohash_prefix

_GEOHASH_PREFIX_RE = re.compile(r"^[0-9b-hjkmnp-z]{2,32}$")


def is_valid_geohash_prefix(prefix: str) -> bool:
    return bool(prefix and _GEOHASH_PREFIX_RE.match(prefix))


def _feature_for_trail(trail: Dict[str, Any]) -> Optional[Feature]:
    props: Dict[str, Any] = {
        "trail_id": trail["trail_id"],
        "title": trail["title"],
        "center_geohash": trail["center_geohash"],
        "source_url": trail["source_url"],
    }

    lines = [
        [[w["lng"], w["lat"]] for w in leg]
        for leg in trail["waypoints"]
        if len(leg) >= 2
    ]

    if lines:
        return Feature(
            geometry=MultiLineString(coordinates=lines),
            properties=props,
            id=trail["trail_id"],
        )

    lat, lng = trail.get("center_lat"), trail.get("center_lng")
    if lat is not None and lng is not None:
        return Feature(
            geometry=Point(coordinates=(lng, lat)),
            properties=props,
            id=trail["trail_id"],
        )
    return None


def feature_collection_for_prefix(data_dir: str | Path, prefix: str) -> FeatureCollection:
    """
    Trails whose ``center_geohash`` starts with ``prefix`` (case-insensitive).
    """
    prefix = prefix.strip().lower()
    if not is_valid_geohash_prefix(prefix):
        return FeatureCollection([])

    features: List[Feature] = []
    for trail in trails_for_geohash_prefix(prefix):
        feat = _feature_for_trail(trail)
        if feat is not None:
            features.append(feat)

    return FeatureCollection(features)
