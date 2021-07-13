#!/usr/bin/env python3
import csv
import json
import logging
import os

import pygeohash

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
dir_path = os.path.dirname(os.path.realpath(__file__))


def get_peaks():

    base_dir = os.path.join(dir_path, "..")
    for filename in os.listdir(base_dir):
        if not filename.endswith(".csv"):
            continue
        print(filename)
        path = os.path.join(base_dir, filename)
        with open(path) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row['Concise Code'] == "MTN":
                    yield row


if __name__ == "__main__":
    logging.info("parsing peaks from can gov data")
    peaks = []
    for peak in get_peaks():
        peak["Latitude"] = float(peak["Latitude"])
        peak["Longitude"] = float(peak["Longitude"])
        peak["geohash"] = pygeohash.encode(
            peak["Latitude"],
            peak["Longitude"],
        )
        peaks.append(peak)
    with open(os.path.join(dir_path, "../trails/data/peaks.json"), "w") as f:
        f.write(json.dumps(peaks, sort_keys=True, indent=2))
    logging.info(f"parsed {len(peaks)} peaks from can gov data")

