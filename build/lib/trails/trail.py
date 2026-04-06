import json
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import gpxpy
import pygeohash
from pydantic import ValidationError

from trails.models import TrailFile, TrailStats, Waypoint
from trails.peak import Peak
from geojson import FeatureCollection, Feature, MultiLineString


def trail_bucket_relative(center_geohash: Optional[str]) -> str:
    """First four geohash characters as nested path segments, or _none if missing."""
    gh = (center_geohash or "").strip()
    if len(gh) < 4:
        return "_none"
    return os.path.join(gh[0], gh[1], gh[2], gh[3])


def trail_stem_base(center_geohash: Optional[str], trail_id: str) -> str:
    """Filename stem (no extension): 10-char geohash, or short hash + trail_id, or trail_id only."""
    gh = (center_geohash or "").strip()
    tid = str(trail_id)
    if len(gh) < 4:
        return tid
    if len(gh) < 10:
        return f"{gh}_{tid}"
    return gh[:10]


def trail_data_paths(data_dir: str, center_geohash: Optional[str], trail_id: str) -> Tuple[str, str]:
    """
    JSON and GPX paths under data_dir using geohash buckets.
    When a plain {stem}.json already exists for another trail, uses {stem}_{trail_id}.json.
    """
    rel_bucket = trail_bucket_relative(center_geohash)
    bucket = os.path.join(data_dir, rel_bucket)
    stem = trail_stem_base(center_geohash, trail_id)
    simple_json = os.path.join(bucket, f"{stem}.json")
    simple_gpx = os.path.join(bucket, f"{stem}.gpx")
    if not os.path.isfile(simple_json):
        return simple_json, simple_gpx
    try:
        with open(simple_json, encoding="utf-8") as f:
            existing = TrailFile.model_validate(json.load(f))
        if str(existing.trail_id) == str(trail_id):
            return simple_json, simple_gpx
    except (OSError, json.JSONDecodeError, TypeError, ValidationError):
        pass
    suffixed = f"{stem}_{trail_id}"
    return (
        os.path.join(bucket, f"{suffixed}.json"),
        os.path.join(bucket, f"{suffixed}.gpx"),
    )


def find_trail_data_paths_by_trail_id(data_dir: str, trail_id: str) -> Optional[Tuple[str, str]]:
    """Locate JSON/GPX for a trail_id anywhere under data_dir (post-migration layout)."""
    tid = str(trail_id)
    for root, _, files in os.walk(data_dir):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            if root == data_dir and filename == "peaks.json":
                continue
            path = os.path.join(root, filename)
            try:
                with open(path, encoding="utf-8") as f:
                    record = TrailFile.model_validate(json.load(f))
                if str(record.trail_id) == tid:
                    return path, path.replace(".json", ".gpx")
            except (OSError, json.JSONDecodeError, TypeError, ValidationError):
                continue
    return None


class Trail:
    def __init__(
        self,
        filepath,
        trail_id,
        title,
        description,
        directions,
        photos,
        source_url,
        stats: Union[Dict[str, Any], TrailStats],
        geohash,
        gpx_filepath,
        center_lat,
        center_lng,
        nearest_peak_geohash,
        center_geohash_from_file: Optional[str] = None,
    ):
        self.filepath = filepath
        self.trail_id = trail_id
        self.title = title.replace("/", "-")
        self.description = description
        self.directions = directions
        self.photos = photos
        self.source_url = source_url
        self.stats = (
            stats.model_dump()
            if isinstance(stats, TrailStats)
            else TrailStats.model_validate(stats).model_dump()
        )
        self.gpx_filepath = gpx_filepath
        self.geohash = geohash
        self.center_lat = center_lat
        self.center_lng = center_lng
        if center_lat is not None and center_lng is not None:
            self.center_geohash = pygeohash.encode(center_lat, center_lng)
        else:
            self.center_geohash = center_geohash_from_file or ""
        self.nearest_peak_geohash = nearest_peak_geohash
        self._gpx_content = None
        self.peak = Peak.get_peak(self.nearest_peak_geohash)

    def __str__(self):
        return self.title

    def save(self):
        with open(self.filepath, "w") as f:
            f.write(json.dumps(self.json, indent=4, sort_keys=True))

    def json(self, skinny=True):
        data = {
            "title": self.title,
            "trail_id": self.trail_id,
            "description": self.description,
            "directions": self.directions,
            "photos": self.photos,
            "source_url": self.source_url,
            "stats": self.stats,
            "geohash": self.geohash,
            "center_lat": self.center_lat,
            "center_lng": self.center_lng,
            "center_geohash": self.center_geohash,
            "nearest_peak_geohash": self.nearest_peak_geohash,
        }

        if not skinny:
            data["waypoints"] = list(self.waypoints)

        return data

    def geojson(self) -> Optional[FeatureCollection]:
        if len(list(self.waypoints)) == 0:
            return None

        coordinates = []
        for leg in self.waypoints:
            points = []
            for coord in leg:
                points.append([coord["lng"], coord["lat"]])
            coordinates.append(points)

        return FeatureCollection([
            Feature(
                geometry=MultiLineString(
                    coordinates=coordinates
                )
            )], id=self.geohash)


    @property
    def gpx_data(self) -> str:
        if self._gpx_content is None:
            with open(self.gpx_filepath) as f:
                try:
                    self._gpx_content = f.read()
                except:
                    return ""
        return self._gpx_content

    @property
    def waypoints(self):
        data = self.gpx_data
        try:
            gpx = gpxpy.parse(data)
        except:
            return
        for track in gpx.tracks:
            for segment in track.segments:
                leg = []
                for point in segment.points:
                    leg.append(
                        Waypoint(
                            lat=point.latitude,
                            lng=point.longitude,
                            alt=point.elevation,
                        ).model_dump()
                    )
                yield leg
        for point in gpx.waypoints:
            yield [
                Waypoint(
                    lat=point.latitude,
                    lng=point.longitude,
                    alt=point.elevation,
                ).model_dump()
            ]

    @classmethod
    def count(cls) -> int:
        c = 0
        dir_path = os.path.dirname(os.path.realpath(__file__))
        data_dir = f"{dir_path}/data"
        for root, _, files in os.walk(data_dir):
            for filename in files:
                if not filename.endswith(".json"):
                    continue
                if root == data_dir and filename == "peaks.json":
                    continue
                c += 1
        return c

    @classmethod
    def load_all(cls) -> List["Trail"]:
        dir_path = os.path.dirname(os.path.realpath(__file__))
        data_dir = f"{dir_path}/data"
        for root, _, files in os.walk(data_dir):
            for filename in files:
                if not filename.endswith(".json"):
                    continue
                if root == data_dir and filename == "peaks.json":
                    continue
                filepath = os.path.join(root, filename)
                gpx_filepath = filepath.replace(".json", ".gpx")
                try:
                    with open(filepath, encoding="utf-8") as fp:
                        record = TrailFile.model_validate(json.loads(fp.read()))
                    yield Trail(
                        filepath=filepath,
                        trail_id=record.trail_id,
                        title=record.title,
                        description=record.description,
                        directions=record.directions,
                        photos=record.photos,
                        source_url=record.source_url,
                        stats=record.stats,
                        geohash=record.geohash,
                        gpx_filepath=gpx_filepath,
                        center_lat=record.center_lat,
                        center_lng=record.center_lng,
                        nearest_peak_geohash=record.nearest_peak_geohash,
                        center_geohash_from_file=record.center_geohash,
                    )
                except (OSError, json.JSONDecodeError, ValidationError, TypeError):
                    continue