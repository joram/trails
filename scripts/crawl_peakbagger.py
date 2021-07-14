#!/usr/bin/env python3
import logging
import os
import pprint
import re

import bs4
import pygeohash

from scripts.base_spider import Spider
from scripts.crawl_trailpeak import get_geohash
from trails import Trail

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
dir_path = os.path.dirname(os.path.realpath(__file__))


class PeakbaggerPagesSpider(Spider):
    name = "peakbagger-peaks-pages"
    domain = "https://www.peakbagger.com/"
    start_urls = ['https://www.peakbagger.com/peak.aspx?pid=757']
    url_regexes = [
        r'list\.aspx\?lid=[0-9]*',
        r'peak\.aspx\?pid=[0-9]*',
        r'climber\/ascent\.aspx\?aid=[0-9]*',
    ]
    strip_params = False


def make_trail(ascent_response, peak_response, gpx_response):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    data_dir = f"{dir_path}/../trails/data"

    ascent_soup = bs4.BeautifulSoup(ascent_response.content, 'html.parser')
    peak_soup = bs4.BeautifulSoup(peak_response.content, 'html.parser')
    trail_id = "pb_" + ascent_response.request.url.split("=")[1]
    ascent_key_vals = {}
    for tr in ascent_soup.findAll("tr"):
        tds = tr.findAll("td")
        if len(tds) == 2:
            ascent_key_vals[tds[0].text.strip(" \n\xa0:")] = tds[1].text
    if "Route" not in ascent_key_vals:
        return None

    peak_key_vals = {}
    for tr in peak_soup.findAll("tr"):
        tds = tr.findAll("td")
        if len(tds) == 2:
            peak_key_vals[tds[0].text.strip(" \n\xa0:")] = tds[1].text

    peak_lat = None
    peak_lng = None
    lat_lng_str = peak_key_vals.get("Latitude/Longitude (WGS84)", "")
    results = re.findall(r'.*?(-?\d+\.\d+),\s*(-?\d+\.\d+).*', lat_lng_str)
    if len(results) == 1:
        [(peak_lat, peak_lng)] = results
        peak_lat = float(peak_lat)
        peak_lng = float(peak_lng)

    geohash, center_geohash, avg_lat, avg_lng = get_geohash(gpx_response.content)

    if not os.path.exists(f"{trail_id}.gpx"):
        with open(f"{data_dir}/{trail_id}.gpx", "wb") as f:
            f.write(gpx_response.content)

    return Trail(
        filepath=f"{data_dir}/{trail_id}.json",
        trail_id=trail_id,
        title=ascent_key_vals.get("Route"),
        description="",
        directions="",
        photos=[],
        source_url=ascent_response.url,
        stats=ascent_key_vals,
        geohash=geohash,
        gpx_filepath=f"{data_dir}/{trail_id}.gpx",
        center_lat=avg_lat,
        center_lng=avg_lng,
        nearest_peak_geohash=pygeohash.encode(peak_lat, peak_lng),
    )


def get_trails():
    spider = PeakbaggerPagesSpider()
    for response, soup in spider.crawl():
        if "ascent" in response.request.url:
            peak_response = None
            peak_link = soup.find("a", href=re.compile(r'peak\.aspx\?pid=[0-9]*'))
            if peak_link:
                peak_url = f"https://www.peakbagger.com/climber/{peak_link['href']}"
                peak_response = spider.session.get(peak_url)

            gpx_response = None
            gpx_link = soup.find("a", href=re.compile(r'GPXFile\.aspx\?aid=[.]*'))
            if gpx_link:
                url = f"https://www.peakbagger.com/climber/{gpx_link['href']}"
                gpx_response = spider.session.get(url)

            if peak_response and gpx_response:
                try:
                    trail = make_trail(response, peak_response, gpx_response)
                except:
                    continue
                if trail is not None:
                    yield trail


if __name__ == "__main__":
    for trail in get_trails():
        print(trail)
        trail.save()
