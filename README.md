# trails

A small Python package of hiking, mountaineering and ski-touring trails, plus a
lightweight map server for browsing them.

All trail data ships in a single compressed Parquet file
(`trails/trails.parquet`), so installing the package gives you the full dataset
with no extra downloads.

> Peak data has moved to its own repository:
> [joram/peaks](https://github.com/joram/peaks).

## Install

```sh
pip install .
```

## Map server

```sh
python -m trails.map_server            # http://127.0.0.1:8765/
python -m trails.map_server --host 0.0.0.0 --port 8765
```

Or with Docker:

```sh
docker build -t trails .
docker run -p 8765:8765 trails
```

Endpoints:

| Path | Description |
| --- | --- |
| `/` | Overview map (loads trails for the current viewport by geohash) |
| `/island-touring.html` | Table of Vancouver Island ski-touring routes |
| `GET /api/trails?prefix=<geohash>` | GeoJSON `FeatureCollection` for a geohash prefix (2–32 chars) |
| `GET /api/region/vancouver-island/trails` | JSON rows for Vancouver Island ski routes, with distance, vertical gain and estimated duration |

## Data pipeline

Raw trail data lives in `trails/data/` (not shipped) as JSON metadata plus
optional GPX tracks, bucketed by geohash:
`trails/data/<c>/<h>/<a>/<r>/<geohash>.json`.

1. **Crawl** sources into `trails/data/`:
   ```sh
   make crawl_trails          # scripts/crawl_peakbagger.py
   ```
   `scripts/crawl_trailpeak.py` is also available for trailpeak.com.
2. **Import open data** (geometry plus official descriptions, BC-wide):
   ```sh
   make import_open_data      # BC Recreation Sites & Trails, then OpenStreetMap
   ```
   - `scripts/import_bc_rst.py`: trails from the BC Data Catalogue
     (`FTEN_REC_TRAILS_SVW`), with descriptions, driving directions,
     activities and closure notices. Trail IDs are `bcrst-<file id>`.
   - `scripts/import_osm.py [--area CA-BC]`: hiking/foot route relations and
     ski-touring (`piste:type=skitour`) relations and ways, via Overpass.
     Trail IDs are `osm-r<relation id>` / `osm-w<way id>`.

   A record that matches an existing trail from another source (similar name,
   centroid within 3 km) is not duplicated. Instead, any blank description,
   directions or track on the existing trail is filled in, along with a
   closure notice if there is one. Re-running an import updates its records
   and removes ones that have disappeared upstream. Both accept `--dry-run`.
3. **Import** hand-collected files: drop `.json`, `.gpx` or `.kml` files into
   `trails/to_sort/` and run
   ```sh
   python scripts/to_sort.py [--dry-run]
   ```
4. **Build** the Parquet file shipped with the package:
   ```sh
   make parquet               # writes trails/trails.parquet
   ```

Run scripts from the repository root so `import trails` resolves.

## Data sources and licences

| Source | Licence |
| --- | --- |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | ODbL 1.0, © OpenStreetMap contributors |
| [Recreation Sites and Trails BC](https://www.sitesandtrailsbc.ca/) | [Open Government Licence – BC](https://www2.gov.bc.ca/gov/content/data/open-data/open-government-licence-bc) |
| trailpeak.com, peakbagger.com | Crawled; see each site's terms |

Each record's `source_url` links back to the original, and `stats.Source` /
`stats.License` name the source for open-data records. Under ODbL share-alike,
a database derived from the OSM records must also be offered under the ODbL.
