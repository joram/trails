import json
import os

import gpxpy


class Trail:
    def __init__(self, title, description, directions, photos, source_url, stats, gpx_filepath):
        self.title = title
        self.description = description
        self.directions = directions
        self.photos = photos
        self.source_url = source_url
        self.stats = stats
        self.gpx_filepath = gpx_filepath
        self._gpx_content = None

    @property
    def gpx_data(self):
        if self._gpx_content is None:
            with open(self.gpx_filepath) as f:
                self._gpx_content = f.read()
        return self._gpx_content

    @property
    def waypoints(self):
        data = self.gpx_data.decode('ascii')
        gpx = gpxpy.parse(data)
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    yield {
                        "lat": point.latitude,
                        "lng": point.longitude,
                        "alt": point.elevation,
                    }

    def load_all(self):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        data_dir = f"{dir_path}/data"
        for filename in os.listdir(data_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(data_dir, filename)
            gpx_filepath = filepath.replace(".json", ".gpx")
            f = open(filepath)
            data = json.loads(f.read())
            trail = Trail(
                title=data["title"],
                description=data["description"],
                directions=data["directions"],
                photos=data["photos"],
                source_url=data["source_url"],
                stats=data["stats"],
                gpx_filepath=gpx_filepath,
            )
            yield trail
