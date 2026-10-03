"""
Shared helpers for importing trails from open-data sources into ``trails/data``.

Importers build ``TrailFile`` records plus track legs, then call
``write_trail``. ``ExistingTrails`` matches incoming records against what is
already on disk (by name similarity and distance) so a source can either skip
a duplicate or fill in a missing description / track on the existing record.
"""
from __future__ import annotations

import difflib
import html
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import gpxpy
import gpxpy.gpx
import pygeohash
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trails.models import TrailFile  # noqa: E402
from trails.trail import trail_data_paths  # noqa: E402

DATA_DIR = ROOT / "trails" / "data"
USER_AGENT = "joram-trails/0.1 (+https://github.com/joram/trails)"

# A leg is a list of (lat, lng, alt) points.
Point = Tuple[float, float, Optional[float]]
Leg = List[Point]

MATCH_MAX_KM = 3.0
MATCH_MIN_RATIO = 0.85
_STOPWORDS = {"the", "trail", "trails", "route", "loop", "recreation", "site", "path", "mt", "mount"}


def http_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def request_with_retry(session: requests.Session, method: str, url: str, tries: int = 5, **kw) -> requests.Response:
    """Retry on rate limiting / gateway errors with exponential backoff."""
    delay = 15.0
    for attempt in range(1, tries + 1):
        try:
            r = session.request(method, url, timeout=kw.pop("timeout", 300), **kw)
            if r.status_code not in (429, 502, 503, 504):
                r.raise_for_status()
                return r
            print(f"  HTTP {r.status_code}, retry {attempt}/{tries} in {delay:.0f}s")
        except requests.ConnectionError as exc:
            print(f"  {exc}, retry {attempt}/{tries} in {delay:.0f}s")
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(f"giving up on {url}")


def clean_text(text: Optional[str]) -> str:
    """Strip HTML tags / entities and normalise whitespace, keeping paragraph breaks."""
    if not text:
        return ""
    t = re.sub(r"(?i)<br\s*/?>", "\n", text)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\r", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def legs_length_km(legs: Sequence[Leg]) -> float:
    return sum(
        haversine_km(a[0], a[1], b[0], b[1])
        for leg in legs
        for a, b in zip(leg, leg[1:])
    )


def centroid(legs: Sequence[Leg]) -> Tuple[Optional[float], Optional[float]]:
    pts = [p for leg in legs for p in leg]
    if not pts:
        return None, None
    return (
        round(sum(p[0] for p in pts) / len(pts), 7),
        round(sum(p[1] for p in pts) / len(pts), 7),
    )


def normalize_title(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(w for w in words if w not in _STOPWORDS)


def titles_match(a: str, b: str) -> bool:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if min(len(na), len(nb)) >= 6 and (na in nb or nb in na):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= MATCH_MIN_RATIO


class Peaks:
    """Nearest-peak lookup over ``trails/data/peaks.json`` (optional; peak data now lives in joram/peaks)."""

    def __init__(self, path: Path = DATA_DIR / "peaks.json"):
        self._grid: Dict[Tuple[int, int], List[Tuple[float, float, str, str]]] = defaultdict(list)
        if not path.is_file():
            return
        for p in json.loads(path.read_text(encoding="utf-8")):
            lat, lng = float(p["Latitude"]), float(p["Longitude"])
            self._grid[(int(lat * 10), int(lng * 10))].append((lat, lng, p["geohash"], p["Geographical Name"]))

    def nearest(self, lat: float, lng: float, max_km: float = 10.0) -> Optional[Tuple[str, str, float]]:
        """Return (geohash, name, distance_km) of the closest peak within max_km."""
        best = None
        ci, cj = int(lat * 10), int(lng * 10)
        reach = 1 + int(max_km / 7)
        for i in range(ci - reach, ci + reach + 1):
            for j in range(cj - reach * 2, cj + reach * 2 + 1):
                for plat, plng, gh, name in self._grid.get((i, j), ()):
                    d = haversine_km(lat, lng, plat, plng)
                    if d <= max_km and (best is None or d < best[2]):
                        best = (gh, name, d)
        return best


class ExistingTrails:
    """Index of trail records already in ``trails/data`` for duplicate matching."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self._grid: Dict[Tuple[int, int], List[Tuple[float, float, str, str, Path]]] = defaultdict(list)
        n = 0
        for path in data_dir.rglob("*.json"):
            if path.name == "peaks.json":
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            lat, lng = raw.get("center_lat"), raw.get("center_lng")
            if lat is None or lng is None:
                continue
            self.add(float(lat), float(lng), str(raw.get("trail_id")), raw.get("title") or "", path)
            n += 1
        print(f"Indexed {n} existing trails")

    def add(self, lat: float, lng: float, trail_id: str, title: str, path: Path) -> None:
        self._grid[(int(lat * 20), int(lng * 20))].append((lat, lng, trail_id, title, path))

    def find_match(self, title: str, lat: float, lng: float, own_prefix: str) -> Optional[Path]:
        """Closest same-named record within MATCH_MAX_KM, ignoring records from this source."""
        best = None
        ci, cj = int(lat * 20), int(lng * 20)
        for i in range(ci - 1, ci + 2):
            for j in range(cj - 2, cj + 3):
                for elat, elng, tid, etitle, path in self._grid.get((i, j), ()):
                    if tid.startswith(own_prefix):
                        continue
                    d = haversine_km(lat, lng, elat, elng)
                    if d <= MATCH_MAX_KM and titles_match(title, etitle) and (best is None or d < best[0]):
                        best = (d, path)
        return best[1] if best else None


def legs_to_gpx(title: str, legs: Sequence[Leg]) -> str:
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack(name=title)
    gpx.tracks.append(track)
    for leg in legs:
        seg = gpxpy.gpx.GPXTrackSegment()
        seg.points.extend(gpxpy.gpx.GPXTrackPoint(lat, lng, elevation=alt) for lat, lng, alt in leg)
        track.segments.append(seg)
    return gpx.to_xml()


def write_trail(record: TrailFile, legs: Sequence[Leg], data_dir: Path = DATA_DIR) -> Path:
    """Write ``record`` as JSON plus a sibling GPX track into its geohash bucket."""
    json_path, gpx_path = trail_data_paths(str(data_dir), record.center_geohash, record.trail_id)
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    data = record.model_dump(exclude={"waypoints"})
    Path(json_path).write_text(json.dumps(data, indent=4, sort_keys=True), encoding="utf-8")
    if legs:
        Path(gpx_path).write_text(legs_to_gpx(record.title, legs), encoding="utf-8")
    return Path(json_path)


def build_record(
    *,
    trail_id: str,
    title: str,
    legs: Sequence[Leg],
    description: str,
    directions: str,
    source_url: str,
    stats: Dict[str, object],
    peaks: Peaks,
) -> Optional[TrailFile]:
    lat, lng = centroid(legs)
    if lat is None:
        return None
    center_gh = pygeohash.encode(lat, lng, precision=12)
    peak = peaks.nearest(lat, lng)
    stats = {k: v for k, v in stats.items() if v not in (None, "")}
    stats.setdefault("Total Distance", f"{legs_length_km(legs):.1f} km")
    return TrailFile(
        trail_id=trail_id,
        title=title,
        description=description,
        directions=directions,
        source_url=source_url,
        stats=stats,
        center_lat=lat,
        center_lng=lng,
        center_geohash=center_gh,
        geohash=center_gh[:4],
        nearest_peak_geohash=peak[0] if peak else None,
    )


def enrich_existing(path: Path, record: TrailFile, legs: Sequence[Leg], source_name: str) -> List[str]:
    """
    Fill blank description / directions / track on an existing record from ``record``,
    and copy over a closure notice if the source has one.
    Never overwrites existing content. Returns the list of fields filled.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    filled = []
    closure = record.stats.model_dump().get("Closure")
    if closure and not raw.get("stats", {}).get("Closure"):
        raw.setdefault("stats", {})["Closure"] = closure
        filled.append("closure")
    for field in ("description", "directions"):
        if not (raw.get(field) or "").strip() and getattr(record, field):
            raw[field] = getattr(record, field)
            filled.append(field)
    gpx_path = path.with_suffix(".gpx")
    has_track = bool(raw.get("waypoints")) or (gpx_path.is_file() and gpx_path.stat().st_size > 0)
    if not has_track and legs:
        gpx_path.write_text(legs_to_gpx(raw.get("title") or record.title, legs), encoding="utf-8")
        filled.append("track")
    if filled:
        stats = raw.setdefault("stats", {})
        stats.setdefault("Enriched From", record.source_url)
        stats.setdefault("Enrichment Source", source_name)
        path.write_text(json.dumps(raw, indent=4, sort_keys=True), encoding="utf-8")
    return filled


def remove_stale(data_dir: Path, prefix: str, keep_paths: set) -> int:
    """Delete records from this source that weren't written this run (gone upstream, merged, or re-bucketed)."""
    removed = 0
    keep = {Path(p).resolve() for p in keep_paths}
    for path in list(iter_source_files(data_dir, prefix)):
        if path.resolve() not in keep:
            path.unlink()
            path.with_suffix(".gpx").unlink(missing_ok=True)
            removed += 1
    return removed


def iter_source_files(data_dir: Path, prefix: str) -> Iterator[Path]:
    for path in data_dir.rglob("*.json"):
        if path.name == "peaks.json":
            continue
        try:
            if str(json.loads(path.read_text(encoding="utf-8")).get("trail_id", "")).startswith(prefix):
                yield path
        except (OSError, json.JSONDecodeError):
            continue
