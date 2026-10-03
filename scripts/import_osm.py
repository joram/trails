#!/usr/bin/env python3
"""
Import hiking and ski-touring routes from OpenStreetMap (via the Overpass API)
into ``trails/data``.

Pulls, inside an ISO 3166-2 area (default ``CA-BC``):
  - hiking / foot route relations (``route=hiking|foot``)
  - ski-touring relations and ways (``piste:type=skitour``); ways already part
    of a ski-touring relation are skipped, named ways sharing a name in the
    same ~20 km cell are merged into one route, and unnamed ways that share an
    endpoint are joined into one route

Routes that already exist from another source (same name, within a few km) are
not duplicated; blank descriptions / tracks on the existing record are filled.
Run this after ``import_bc_rst.py`` so official BC records take precedence.

Data: © OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright

Run from the repo root:
    python scripts/import_osm.py [--area CA-BC] [--dry-run]
"""
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pygeohash

from open_data import (
    DATA_DIR,
    ExistingTrails,
    Leg,
    Peaks,
    TrailFile,
    build_record,
    centroid,
    clean_text,
    enrich_existing,
    http_session,
    legs_length_km,
    remove_stale,
    request_with_retry,
    write_trail,
)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SOURCE_NAME = "OpenStreetMap"
LICENSE = "ODbL 1.0 - (c) OpenStreetMap contributors"
ID_PREFIX = "osm-"
MIN_UNNAMED_KM = 1.0

QUERIES = {
    "hiking": 'relation["type"="route"]["route"~"^(hiking|foot)$"](area.a);',
    "skitour_rel": 'relation["piste:type"="skitour"](area.a);',
    "skitour_way": 'way["piste:type"="skitour"](area.a);',
}


def overpass(session, area: str, body: str) -> List[dict]:
    q = f'[out:json][timeout:600];area["ISO3166-2"="{area}"]->.a;{body}out geom;'
    r = request_with_retry(session, "POST", OVERPASS_URL, data={"data": q}, timeout=700)
    return r.json()["elements"]


def relation_legs(el: dict) -> Tuple[List[Leg], List[int]]:
    legs, way_ids = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or not m.get("geometry"):
            continue
        legs.append([(p["lat"], p["lon"], None) for p in m["geometry"]])
        way_ids.append(m["ref"])
    return legs, way_ids


def way_leg(el: dict) -> Leg:
    return [(p["lat"], p["lon"], None) for p in el.get("geometry", [])]


def join_touching(ways: List[dict]) -> List[List[dict]]:
    """Group ways into connected components by shared endpoints."""
    parent = list(range(len(ways)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_end: Dict[Tuple[float, float], int] = {}
    for i, w in enumerate(ways):
        for p in (w["geometry"][0], w["geometry"][-1]):
            key = (round(p["lat"], 6), round(p["lon"], 6))
            if key in by_end:
                parent[find(i)] = find(by_end[key])
            else:
                by_end[key] = i
    comps: Dict[int, List[dict]] = defaultdict(list)
    for i, w in enumerate(ways):
        comps[find(i)].append(w)
    return list(comps.values())


def describe(tags: Dict[str, str]) -> str:
    parts = [clean_text(tags.get("description") or tags.get("description:en"))]
    if tags.get("from") and tags.get("to"):
        parts.append(f"From {tags['from']} to {tags['to']}.")
    return "\n\n".join(p for p in parts if p)


def osm_stats(tags: Dict[str, str], activity: str) -> Dict[str, object]:
    return {
        "Activities": activity,
        "Difficulty": tags.get("sac_scale") or tags.get("piste:difficulty"),
        "Operator": tags.get("operator"),
        "Network": tags.get("network"),
        "Website": tags.get("website") or tags.get("url"),
        "Wikipedia": tags.get("wikipedia"),
        "Source": SOURCE_NAME,
        "License": LICENSE,
    }


def title_for(tags: Dict[str, str]) -> Optional[str]:
    for k in ("name", "name:en", "piste:name"):
        if tags.get(k):
            return tags[k].strip()
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", default="CA-BC", help="ISO 3166-2 code of the area to import (default CA-BC)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    args = ap.parse_args()

    session = http_session()
    results = {}
    for name, body in QUERIES.items():
        results[name] = overpass(session, args.area, body)
        print(f"Fetched {len(results[name])} OSM {name} elements in {args.area}")
        time.sleep(10)  # be polite to the public Overpass instance

    existing = ExistingTrails()
    peaks = Peaks()

    # (trail_id, title, legs, tags, activity, source_url)
    candidates = []
    skitour_way_ids = set()
    for activity, key in (("hike", "hiking"), ("ski-bc", "skitour_rel")):
        for el in results[key]:
            legs, way_ids = relation_legs(el)
            if key == "skitour_rel":
                skitour_way_ids.update(way_ids)
            title = title_for(el["tags"])
            if not legs or not title:
                continue
            candidates.append((f"{ID_PREFIX}r{el['id']}", title, legs, el["tags"], activity,
                               f"https://www.openstreetmap.org/relation/{el['id']}"))

    # Standalone ski-touring ways: merge same-named ways in the same geohash-4 cell,
    # and join unnamed ways that touch end-to-end.
    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    unnamed: List[dict] = []
    for el in results["skitour_way"]:
        if el["id"] in skitour_way_ids or len(el.get("geometry", [])) < 2:
            continue
        title = title_for(el["tags"])
        if title is None:
            unnamed.append(el)
            continue
        lat, lng = centroid([way_leg(el)])
        groups[(title, pygeohash.encode(lat, lng, precision=4))].append(el)
    named = [(title, ways) for (title, _cell), ways in groups.items()]
    for ways in join_touching(unnamed):
        legs = [way_leg(w) for w in ways]
        if legs_length_km(legs) < MIN_UNNAMED_KM:
            continue
        lat, lng = centroid(legs)
        peak = peaks.nearest(lat, lng, max_km=5.0)
        named.append((f"Ski tour near {peak[1]}" if peak else "Unnamed ski tour", ways))
    for title, ways in named:
        first = min(ways, key=lambda w: w["id"])
        candidates.append((f"{ID_PREFIX}w{first['id']}", title, [way_leg(w) for w in ways], first["tags"],
                           "ski-bc", f"https://www.openstreetmap.org/way/{first['id']}"))

    written, enriched = set(), 0
    for trail_id, title, legs, tags, activity, url in candidates:
        record: Optional[TrailFile] = build_record(
            trail_id=trail_id,
            title=title,
            legs=legs,
            description=describe(tags),
            directions="",
            source_url=url,
            stats=osm_stats(tags, activity),
            peaks=peaks,
        )
        if record is None:
            continue
        match = existing.find_match(record.title, record.center_lat, record.center_lng, ID_PREFIX)
        if match is not None:
            filled = [] if args.dry_run else enrich_existing(match, record, legs, SOURCE_NAME)
            if filled:
                enriched += 1
                print(f"  enriched {match.relative_to(DATA_DIR)} ({', '.join(filled)}) from {record.title}")
            continue
        written.add(record.trail_id if args.dry_run else write_trail(record, legs))

    removed = 0 if args.dry_run else remove_stale(DATA_DIR, ID_PREFIX, written)
    print(f"{len(written)} OSM routes written, {enriched} existing trails enriched, {removed} stale removed")


if __name__ == "__main__":
    main()
