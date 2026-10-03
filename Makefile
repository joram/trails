crawl_trails:
	./scripts/crawl_peakbagger.py
	#./scripts/crawl_trailpeak.py

crawl_peaks:
	./scripts/crawl_peaks.py

# Open-data imports; BC first so official records win over OSM duplicates.
import_open_data:
	python scripts/import_bc_rst.py
	python scripts/import_osm.py

parquet:
	python scripts/build_parquet.py
