#!/usr/bin/env python3
"""
Move flat trails/data/<id>.json into geohash buckets:
  trails/data/<c>/<h>/<a>/<r>/<10-char-geohash>.json
Colliding 10-char prefixes use <stem>_<trail_id>.json.
Missing center_geohash (< 4 chars) -> trails/data/_none/<trail_id>.json
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "trails" / "data"


def bucket_rel(center_geohash: str) -> str:
    gh = (center_geohash or "").strip()
    if len(gh) < 4:
        return "_none"
    return os.path.join(gh[0], gh[1], gh[2], gh[3])


def stem_base(center_geohash: str, trail_id: str) -> str:
    gh = (center_geohash or "").strip()
    tid = str(trail_id)
    if len(gh) < 4:
        return tid
    if len(gh) < 10:
        return f"{gh}_{tid}"
    return gh[:10]


def main() -> int:
    flat_json = sorted(p for p in DATA.glob("*.json") if p.name != "peaks.json")
    items = []
    for src_json in flat_json:
        with open(src_json, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            continue
        gh = d.get("center_geohash") or ""
        tid = str(d.get("trail_id", ""))
        items.append(
            {
                "src_json": src_json,
                "src_gpx": src_json.with_suffix(".gpx"),
                "bucket": bucket_rel(gh),
                "stem": stem_base(gh, tid),
                "tid": tid,
            }
        )

    by_key = defaultdict(list)
    for it in items:
        by_key[(it["bucket"], it["stem"])].append(it)

    owner = {}
    for key, grp in by_key.items():
        grp.sort(key=lambda x: x["tid"])
        owner[key] = grp[0]["tid"]

    moves = []
    for it in items:
        key = (it["bucket"], it["stem"])
        stem = it["stem"]
        tid = it["tid"]
        dest_dir = DATA / it["bucket"]
        if owner[key] == tid:
            name = f"{stem}.json"
        else:
            name = f"{stem}_{tid}.json"
        dest_json = dest_dir / name
        dest_gpx = dest_dir / name.replace(".json", ".gpx")
        moves.append({**it, "dest_json": dest_json, "dest_gpx": dest_gpx})

    seen = {}
    for m in moves:
        k = str(m["dest_json"])
        if k in seen:
            print("Duplicate destination", k, seen[k], m["tid"], file=sys.stderr)
            return 1
        seen[k] = m["tid"]

    moves.sort(key=lambda x: x["tid"])
    for m in moves:
        m["dest_json"].parent.mkdir(parents=True, exist_ok=True)
        os.rename(m["src_json"], m["dest_json"])
        if m["src_gpx"].is_file():
            if m["dest_gpx"].exists():
                print("GPX clash", m["dest_gpx"], file=sys.stderr)
                return 1
            os.rename(m["src_gpx"], m["dest_gpx"])

    print(f"Migrated {len(moves)} trails.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
