#!/usr/bin/env python3
"""
Import trails from Recreation Sites and Trails BC (BC Data Catalogue WFS layer
``WHSE_FOREST_TENURE.FTEN_REC_TRAILS_SVW``) into ``trails/data``.

Each record carries the official description, driving directions, activities,
closure notice and the trail line. Trails that already exist from another
source (same name, within a few km) are not duplicated; instead any blank
description / directions / track on the existing record is filled in.

Data: Open Government Licence – British Columbia
https://www2.gov.bc.ca/gov/content/data/open-data/open-government-licence-bc

Run from the repo root:
    python scripts/import_bc_rst.py [--dry-run]
"""
from __future__ import annotations

import argparse
from typing import Dict, List

from open_data import (
    DATA_DIR,
    ExistingTrails,
    Leg,
    Peaks,
    build_record,
    clean_text,
    enrich_existing,
    http_session,
    remove_stale,
    request_with_retry,
    write_trail,
)

WFS_URL = "https://openmaps.gov.bc.ca/geo/pub/wfs"
LAYER = "pub:WHSE_FOREST_TENURE.FTEN_REC_TRAILS_SVW"
SOURCE_NAME = "Recreation Sites and Trails BC"
LICENSE = "Open Government Licence - British Columbia"
ID_PREFIX = "bcrst-"
SITE_URL = "https://www.sitesandtrailsbc.ca/search/search-result.aspx?site={id}&type=Trail"

# RSTBC activity names -> the activity tokens used by existing (trailpeak) records.
ACTIVITY_TOKENS: Dict[str, str] = {
    "Hiking": "hike",
    "Mountain Biking": "mtn-bike",
    "Snowshoeing": "snowshoe",
    "Skiing": "ski-xc",
    "Ski Touring": "ski-bc",
    "Mountaineering": "mountaineer",
    "Climbing": "climb",
    "Horseback Riding": "horse",
    "Snowmobiling": "snowmobile",
    "Trail Bike Riding - Motorized": "moto",
    "Kayaking": "kayak",
    "Canoeing": "canoe",
}


def fetch_features() -> List[dict]:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": LAYER,
        "outputFormat": "json",
        "srsName": "EPSG:4326",
    }
    r = request_with_retry(http_session(), "GET", WFS_URL, params=params)
    return r.json()["features"]


def feature_legs(geom: dict) -> List[Leg]:
    if not geom:
        return []
    lines = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
    return [[(lat, lng, None) for lng, lat, *_ in line] for line in lines if len(line) >= 2]


def activities(props: dict) -> List[str]:
    return [props[f"ACTIVITY_DESC{i}"] for i in range(1, 11) if props.get(f"ACTIVITY_DESC{i}")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    args = ap.parse_args()

    features = fetch_features()
    print(f"Fetched {len(features)} BC recreation trails")
    existing = ExistingTrails()
    peaks = Peaks()

    written, enriched, skipped = set(), 0, 0
    for f in features:
        p = f["properties"]
        if p.get("RETIREMENT_DATE"):
            continue
        legs = feature_legs(f["geometry"])
        acts = activities(p)
        tokens = sorted({ACTIVITY_TOKENS[a] for a in acts if a in ACTIVITY_TOKENS})
        record = build_record(
            trail_id=ID_PREFIX + p["FOREST_FILE_ID"],
            title=(p.get("PROJECT_NAME") or p["FOREST_FILE_ID"]).strip(),
            legs=legs,
            description=clean_text(p.get("PROJECT_DESCRIPTION")),
            directions=clean_text(p.get("DRIVING_DIRECTIONS")),
            source_url=SITE_URL.format(id=p["FOREST_FILE_ID"]),
            stats={
                "Activities": " ".join(tokens),
                "Activity Details": ", ".join(acts),
                "Closure": clean_text(p.get("CLOSURE_DESCRIPTION")),
                "Maintenance": p.get("MAINTAIN_STD_DESC"),
                "Town": p.get("SITE_LOCATION", "").title(),
                "Recreation District": p.get("REC_DISTRICT_CODE_DESC"),
                "Source": SOURCE_NAME,
                "License": LICENSE,
            },
            peaks=peaks,
        )
        if record is None:
            skipped += 1
            continue

        match = existing.find_match(record.title, record.center_lat, record.center_lng, ID_PREFIX)
        if match is not None:
            filled = [] if args.dry_run else enrich_existing(match, record, legs, SOURCE_NAME)
            if filled:
                enriched += 1
                print(f"  enriched {match.relative_to(DATA_DIR)} ({', '.join(filled)}) from {record.title}")
            continue

        if not args.dry_run:
            written.add(write_trail(record, legs))
        else:
            written.add(record.trail_id)

    removed = 0 if args.dry_run else remove_stale(DATA_DIR, ID_PREFIX, written)
    print(
        f"{len(written)} BC trails written, {enriched} existing trails enriched, "
        f"{skipped} without geometry, {removed} stale removed"
    )


if __name__ == "__main__":
    main()
