import json
import os


class Trail:
    def __init__(self, title, description, directions, photos, source_url, stats, gps_filepath):
        self.title = title
        self.description = description
        self.directions = directions
        self.photos = photos
        self.source_url = source_url
        self.stats = stats
        self.gps_filepath = gps_filepath
        self._gps_content = None

    @property
    def gps_data(self):
        if self._gps_content is None:
            with open(self.gps_filepath) as f:
                self._gps_content = f.read()
        return self._gps_content

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
                gps_filepath=gpx_filepath,
            )
            yield trail
