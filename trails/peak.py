import json
import os

import geopy.distance
import pygeohash

_peaks_by_geohash = None


class Peak:
    def __init__(self, title, lat, lng, geohash):
        self.title = title
        self.lat = lat
        self.lng = lng
        self.geohash = geohash

    @property
    def json(self):
        return {
            "title": self.title,
            "lat": self.lat,
            "lng": self.lng,
            "geohash": self.geohash,
        }

    def distance(self, lat, lng) -> float:
        coords_1 = (self.lat, self.lng)
        coords_2 = (lat, lng)
        return geopy.distance.distance(coords_1, coords_2).km

    @classmethod
    def closest_peak(cls, lat, lng):
        if lat is None or lng is None:
            return None

        closest_dist = None
        closest_peak = None
        geohash = pygeohash.encode(lat, lng)
        cls._load_peaks()
        for peak in _peaks_by_geohash.values():
            if peak.geohash[:2] != geohash[:2]:
                continue
            dist = peak.distance(lat, lng)
            if closest_dist is None or dist < closest_dist:
                closest_dist = dist
                closest_peak = peak
        return closest_peak

    @classmethod
    def get_peak(cls, geohash) -> "Peak":
        cls._load_peaks()
        peak = _peaks_by_geohash.get(geohash)
        return peak

    @classmethod
    def _load_peaks(cls):
        global _peaks_by_geohash
        dir_path = os.path.dirname(os.path.realpath(__file__))
        with open(os.path.join(dir_path, "data/peaks.json")) as f:
            peaks_json = json.loads(f.read())
            _peaks_by_geohash = {}
            for peak_json in peaks_json:
                peak = Peak(
                    title=peak_json["Geographical Name"],
                    lat=peak_json["Latitude"],
                    lng=peak_json["Longitude"],
                    geohash=peak_json["geohash"],
                )
                _peaks_by_geohash[peak.geohash] = peak
