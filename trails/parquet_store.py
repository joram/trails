"""Load and query trails from the pre-built Parquet file."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

import pandas as pd

_PARQUET_PATH = Path(__file__).resolve().parent / "trails.parquet"


@lru_cache(maxsize=1)
def _load_df() -> pd.DataFrame:
    return pd.read_parquet(_PARQUET_PATH)


def _row_to_dict(row) -> Dict[str, Any]:
    lat = row.center_lat
    lng = row.center_lng
    return {
        "trail_id": row.trail_id,
        "title": row.title,
        "description": row.description,
        "directions": row.directions,
        "photos": json.loads(row.photos),
        "source_url": row.source_url,
        "stats": json.loads(row.stats),
        "geohash": row.geohash,
        "center_lat": None if (lat != lat) else lat,  # NaN → None
        "center_lng": None if (lng != lng) else lng,
        "center_geohash": row.center_geohash,
        "nearest_peak_geohash": row.nearest_peak_geohash,
        "waypoints": json.loads(row.waypoints_json),
        "distance_km": row.distance_km,
        "vertical_gain_m": row.vertical_gain_m,
    }


def trails_for_geohash_prefix(prefix: str) -> Iterator[Dict[str, Any]]:
    """Yield trail dicts whose center_geohash starts with prefix."""
    df = _load_df()
    mask = df["center_geohash"].str.startswith(prefix, na=False)
    for row in df[mask].itertuples(index=False):
        yield _row_to_dict(row)


def trails_in_bounds(
    bounds: Tuple[float, float, float, float],
) -> Iterator[Dict[str, Any]]:
    """Yield trail dicts whose centroid lies inside (min_lat, max_lat, min_lng, max_lng)."""
    min_lat, max_lat, min_lng, max_lng = bounds
    df = _load_df()
    mask = (
        df["center_lat"].notna()
        & df["center_lng"].notna()
        & (df["center_lat"] >= min_lat)
        & (df["center_lat"] <= max_lat)
        & (df["center_lng"] >= min_lng)
        & (df["center_lng"] <= max_lng)
    )
    for row in df[mask].itertuples(index=False):
        yield _row_to_dict(row)
