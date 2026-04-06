#!/usr/bin/env python3
"""
Move trail files from an inbox into the geohash bucket layout under ``trails/data``.

Handles, per matching basename (stem):

- ``*.json`` (validated ``TrailFile``) plus optional sibling ``*.gpx`` / ``*.kml`` in the inbox
- ``*.gpx`` and/or ``*.kml`` alone: centroid from track/geometry, ``trail_id`` from sanitized stem,
  ``center_geohash`` from ``pygeohash.encode`` (precision 12)

Uses ``trail_data_paths`` for the same folder and stem rules as the library.

Run from the repository root (so ``import trails`` resolves)::

    python scripts/to_sort.py
    python scripts/to_sort.py --dry-run

Options ``--from`` / ``--data-dir`` accept absolute or repo-relative paths.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import gpxpy
import pygeohash
from pydantic import ValidationError

from trails.models import TrailFile
from trails.trail import trail_bucket_relative, trail_data_paths, trail_stem_base


def _resolve(repo: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (repo / path)


def sanitize_trail_id(stem: str) -> str:
    s = stem.strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-zA-Z0-9_.-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_.-")
    if not s:
        s = "import"
    if len(s) > 120:
        s = s[:120]
    if not (s[0].isalnum()):
        s = "t_" + s
    return s


def _bbox_center(pts: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if not pts:
        return None
    lats = [p[0] for p in pts]
    lngs = [p[1] for p in pts]
    return (sum(lats) / len(lats), sum(lngs) / len(lngs))


def centroid_from_gpx(path: Path) -> Optional[Tuple[float, float]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        gpx = gpxpy.parse(raw)
    except (OSError, UnicodeError, ValueError):
        return None
    gpx.refresh_bounds()
    if gpx.bounds is not None:
        b = gpx.bounds
        return (
            (b.min_latitude + b.max_latitude) / 2,
            (b.min_longitude + b.max_longitude) / 2,
        )
    pts: List[Tuple[float, float]] = []
    for track in gpx.tracks:
        for seg in track.segments:
            for p in seg.points:
                pts.append((p.latitude, p.longitude))
    for w in gpx.waypoints:
        pts.append((w.latitude, w.longitude))
    for r in gpx.routes:
        for p in r.points:
            pts.append((p.latitude, p.longitude))
    return _bbox_center(pts)


def _parse_coordinate_tokens(text: str) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    if not text or not text.strip():
        return out
    for chunk in re.split(r"[\s\n]+", text.strip()):
        if not chunk:
            continue
        parts = chunk.split(",")
        if len(parts) >= 2:
            try:
                lng, lat = float(parts[0]), float(parts[1])
                out.append((lat, lng))
            except ValueError:
                continue
    return out


def centroid_from_kml(path: Path) -> Optional[Tuple[float, float]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(raw)
    except (OSError, UnicodeError, ET.ParseError):
        return None
    pts: List[Tuple[float, float]] = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag != "coordinates":
            continue
        if el.text:
            pts.extend(_parse_coordinate_tokens(el.text))
    return _bbox_center(pts)


def centroid_from_gpx_kml(gpx_path: Optional[Path], kml_path: Optional[Path]) -> Optional[Tuple[float, float]]:
    all_pts: List[Tuple[float, float]] = []
    if gpx_path and gpx_path.is_file():
        c = centroid_from_gpx(gpx_path)
        if c:
            all_pts.append(c)
    if kml_path and kml_path.is_file():
        c = centroid_from_kml(kml_path)
        if c:
            all_pts.append(c)
    return _bbox_center(all_pts) if all_pts else None


def _dest_triple(data_dir_s: str, center_geohash: Optional[str], trail_id: str) -> Tuple[Path, Path, Path]:
    j, p = trail_data_paths(data_dir_s, center_geohash, trail_id)
    pj = Path(j)
    return pj, Path(p), pj.with_suffix(".kml")


def _allocate_import_stem(bucket: Path, center_geohash: Optional[str], trail_id: str) -> str:
    """
    Unique filename stem for GPX/KML-only imports: avoids clashes when ``trail_data_paths``
    would reuse the same 10-char stem because no JSON exists yet.
    """
    ghs = (center_geohash or "").strip()
    base = trail_stem_base(center_geohash, trail_id)
    if len(ghs) >= 10:
        path_stem = f"{base}_{trail_id}"
    else:
        path_stem = base
    cand = path_stem
    n = 0
    while True:
        b = bucket / cand
        if not any(b.with_suffix(x).exists() for x in (".json", ".gpx", ".kml")):
            return cand
        n += 1
        cand = f"{path_stem}_{n}"


def _import_dest_triple(
    data_dir_s: str, center_geohash: Optional[str], trail_id: str
) -> Tuple[Path, Path, Path]:
    rel = trail_bucket_relative(center_geohash)
    bucket = Path(data_dir_s) / rel
    stem = _allocate_import_stem(bucket, center_geohash, trail_id)
    base = bucket / stem
    return base.with_suffix(".json"), base.with_suffix(".gpx"), base.with_suffix(".kml")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sort trail files from inbox into trails/data layout")
    parser.add_argument(
        "--from",
        "-f",
        dest="inbox",
        default="trails/to_sort",
        help="Inbox directory (default: trails/to_sort)",
    )
    parser.add_argument(
        "--data-dir",
        "-d",
        default="trails/data",
        help="Destination data root (default: trails/data)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Print moves only; do not rename files",
    )
    args = parser.parse_args()

    inbox = _resolve(REPO, args.inbox)
    data_dir = _resolve(REPO, args.data_dir)

    if not inbox.is_dir():
        print(f"error: inbox is not a directory: {inbox}", file=sys.stderr)
        return 1
    if not data_dir.is_dir():
        print(f"error: data directory not found: {data_dir}", file=sys.stderr)
        return 1

    data_dir_s = str(data_dir)
    moved = 0
    skipped = 0
    errors = 0

    groups: DefaultDict[str, Dict[str, Optional[Path]]] = defaultdict(
        lambda: {"json": None, "gpx": None, "kml": None}
    )
    for p in inbox.iterdir():
        if not p.is_file():
            continue
        low = p.suffix.lower()
        if low == ".json":
            if p.name == "peaks.json":
                print(f"skip (reserved name): {p.name}")
                skipped += 1
                continue
            groups[p.stem]["json"] = p
        elif low == ".gpx":
            groups[p.stem]["gpx"] = p
        elif low == ".kml":
            groups[p.stem]["kml"] = p

    for stem in sorted(groups.keys()):
        g = groups[stem]
        src_json = g["json"]
        src_gpx = g["gpx"]
        src_kml = g["kml"]

        if src_json is not None:
            try:
                raw = json.loads(src_json.read_text(encoding="utf-8"))
                record = TrailFile.model_validate(raw)
            except (OSError, json.JSONDecodeError, ValidationError, TypeError) as e:
                print(f"error: {src_json.name}: {e}", file=sys.stderr)
                errors += 1
                continue

            tid = record.trail_id
            gh = record.center_geohash
            dst_json, dst_gpx, dst_kml = _dest_triple(data_dir_s, gh, tid)

            plan_json = src_json.resolve() != dst_json.resolve()
            plan_gpx = (
                src_gpx is not None
                and src_gpx.is_file()
                and src_gpx.resolve() != dst_gpx.resolve()
            )
            plan_kml = (
                src_kml is not None
                and src_kml.is_file()
                and src_kml.resolve() != dst_kml.resolve()
            )
            if not plan_json and not plan_gpx and not plan_kml:
                print(f"skip (already at destination): {stem}")
                skipped += 1
                continue

            if args.dry_run:
                if plan_json:
                    print(f"mv {src_json} -> {dst_json}")
                if plan_gpx:
                    print(f"mv {src_gpx} -> {dst_gpx}")
                if plan_kml:
                    print(f"mv {src_kml} -> {dst_kml}")
                moved += 1
                continue

            dst_json.parent.mkdir(parents=True, exist_ok=True)
            try:
                if plan_json:
                    os.replace(src_json, dst_json)
                if plan_gpx:
                    os.replace(src_gpx, dst_gpx)
                if plan_kml:
                    os.replace(src_kml, dst_kml)
            except OSError as e:
                print(f"error: move {stem}: {e}", file=sys.stderr)
                errors += 1
                continue

            print(f"moved trail {tid} -> {dst_json.relative_to(data_dir)}")
            moved += 1
            continue

        # GPX and/or KML only
        if src_gpx is None and src_kml is None:
            skipped += 1
            continue

        center = centroid_from_gpx_kml(src_gpx, src_kml)
        if center is None:
            print(f"error: {stem}: could not compute centroid from GPX/KML", file=sys.stderr)
            errors += 1
            continue

        lat, lng = center
        gh = pygeohash.encode(lat, lng, precision=12)
        tid = sanitize_trail_id(stem)
        _, dst_gpx, dst_kml = _import_dest_triple(data_dir_s, gh, tid)

        plan_gpx = src_gpx is not None and src_gpx.is_file() and src_gpx.resolve() != dst_gpx.resolve()
        plan_kml = src_kml is not None and src_kml.is_file() and src_kml.resolve() != dst_kml.resolve()
        if not plan_gpx and not plan_kml:
            print(f"skip (already at destination): {stem}")
            skipped += 1
            continue

        if args.dry_run:
            if plan_gpx:
                print(f"mv {src_gpx} -> {dst_gpx}")
            if plan_kml:
                print(f"mv {src_kml} -> {dst_kml}")
            moved += 1
            continue

        had_gpx = src_gpx is not None and src_gpx.is_file()
        had_kml = src_kml is not None and src_kml.is_file()
        try:
            dst_gpx.parent.mkdir(parents=True, exist_ok=True)
            if had_gpx:
                os.replace(src_gpx, dst_gpx)
            if had_kml:
                os.replace(src_kml, dst_kml)
        except OSError as e:
            print(f"error: move {stem}: {e}", file=sys.stderr)
            errors += 1
            continue

        rel = dst_gpx.relative_to(data_dir) if had_gpx else dst_kml.relative_to(data_dir)
        print(f"moved import {tid} ({stem}) -> {rel}")
        moved += 1

    print(f"done: moved={moved}, skipped={skipped}, errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
