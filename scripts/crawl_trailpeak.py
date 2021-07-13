#!/usr/bin/env python3
import json
import logging
import os
import random
import re
import string
import urllib.parse
from typing import List
import gpxpy
import gpxpy.gpx
import pygeohash

import bs4
import requests
import requests_cache
from requests_cache import CachedSession
from requests_toolbelt import MultipartEncoder

from trails.peak import Peak

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
dir_path = os.path.dirname(os.path.realpath(__file__))


class Spider:
    name = "base scraper"
    cache_dir = "../data"
    start_urls = []
    to_visit_urls = []
    visited_urls = {}
    use_cache = True
    session = None
    url_regex = ""
    domain = ""
    strip_params = True

    def __init__(self):
        self.to_visit_urls = self.start_urls
        dir_path = os.path.dirname(os.path.realpath(__file__))
        requests_cache.install_cache(backend="sqlite", cache_name=f"{dir_path}/cache/")
        self.session = CachedSession()
        self.session = requests.Session()

    def crawl(self):
        while len(self.to_visit_urls) > 0:
            url = self.to_visit_urls.pop()
            if self.visited_urls.get(url, False):
                logger.debug(f"skilling url, already visited: {url}")
                continue
            response = self.get(url)
            soup = bs4.BeautifulSoup(response.content, 'html.parser')
            next_urls = self.next_urls(soup)
            logger.debug(f"adding {len(next_urls)} urls to visit")
            self.to_visit_urls += next_urls
            yield response, soup
            self.visited_urls[url] = True

    def get(self, url: str) -> requests.Response:
        response = self.session.get(url)
        return response

    def next_urls(self, soup: bs4.BeautifulSoup) -> List[str]:
        anchors = soup.findAll('a', href=re.compile(self.url_regex))
        urls = []
        for a in anchors:
            href = a["href"]
            if not href.startswith(self.domain):
                href = f"{self.domain}{href}"
                if self.strip_params and "?" in href:
                    href = href.split("?")[0]
            urls.append(href)
        return urls


class TrailpeakListPagesSpider(Spider):
    name = "trailpeak-list-pages"
    domain = "https://trailpeak.com"
    start_urls = ['https://trailpeak.com/trails?page=1']
    url_regex = r'https\:\/\/trailpeak\.com\/trails\?page\=[0-9]*'
    strip_params = False


class TrailpeakRoutePageSpider(Spider):
    name = "trailpeak-list-pages"
    domain = "https://trailpeak.com"
    start_urls = ['https://trailpeak.com/trails?page=1']
    url_regex = r'https\:\/\/trailpeak\.com\/trails\?page\=[0-9]*'
    strip_params = False

    def trail_urls(self) -> List[str]:
        for response, soup in TrailpeakListPagesSpider().crawl():
            anchors = soup.findAll('a')
            for a in anchors:
                href = a["href"]
                if href.startswith("/trail-") and href != "/trails/create":
                    if not href.startswith(self.domain):
                        href = f"{self.domain}/{href}"
                    yield href

    def crawl(self) -> (requests.Response, bs4.BeautifulSoup):
        for url in self.trail_urls():
            response = self.get(url)
            soup = bs4.BeautifulSoup(response.content, 'html.parser')
            yield response, soup


def trailpeak_trails():
    spider = TrailpeakRoutePageSpider()
    for response, soup in spider.crawl():
        description_div = soup.find("v-tab", {"title": "Description"}).findAll("p")[0]
        directions_div = soup.find("v-tab", {"title": "Directions"})

        photos = []
        photos_div = soup.find("div", {"id": "photoBox"})
        photos_attr = json.loads(photos_div.find("photo-box")[":photos"])
        if photos_attr:
            photos = [f"https://trailpeak.com{img['src']}" for img in photos_attr]

        stats = {}
        stats_div = soup.find("v-tab", {"title": "Stats"})
        for p in stats_div.findAll("p"):
            span = p.find("span")
            key = span.text.strip("\n :")
            val = span.nextSibling
            if key == "Stars":
                stats[key] = int(p.find("star-rank")[":stars"])
            else:
                stats[key] = val.strip("\t\n ")
        trail_id = None
        show_gps = soup.find("show-gps")
        if show_gps:
            trail_id = show_gps.attrs.get(":tid")
        gpx_data = get_gpx(spider, response, soup)
        geohash, center_geohash, avg_lat, avg_lng = get_geohash(gpx_data)
        peak = Peak.closest_peak(avg_lat, avg_lng)
        yield {
            "trail_id": trail_id,
            "gpx_data": gpx_data,
            "source_url": response.request.url,
            "title": soup.find("h1", {"class": "title"}).text.strip("\t\n "),
            "description": description_div.text.strip("\n "),
            "directions": directions_div.text.strip("\n "),
            "geohash": geohash,
            "center_lat": avg_lat,
            "center_lng": avg_lng,
            "center_geohash": center_geohash,
            "photos": photos,
            "stats": stats,
            "nearest_peak_geohash": peak.geohash if peak else None,
        }


def get_geohash(gpx_data) -> (str, float, float):

    def _same_prefix(a: str, b: str) -> str:
        prefix = ""
        max_len = min([len(a), len(b)])
        for i in range(0, max_len):
            if a[i] != b[i]:
                break
            prefix = f"{prefix}{a[i]}"
        return prefix

    if gpx_data is None:
        logger.info("failed to parse gpx file: no gpx content")
        return None, None, None, None
    try:
        data = gpx_data.decode('utf-8')
        gpx = gpxpy.parse(data)
    except:
        logger.info("failed to parse gpx file")
        return None, None, None, None

    gpx.refresh_bounds()
    if gpx.bounds is None:
        if len(gpx.waypoints) == 0:
            logger.info("failed to parse gpx file: no gpx bounds")
            return None, None, None, None
        max_latitude = gpx.waypoints[0].latitude
        max_longitude = gpx.waypoints[0].longitude
        min_latitude = gpx.waypoints[0].latitude
        min_longitude = gpx.waypoints[0].longitude
        for wp in gpx.waypoints:
            max_latitude = max(max_latitude, wp.latitude)
            max_longitude = max(max_longitude, wp.longitude)
            min_latitude = min(min_latitude, wp.latitude)
            min_longitude = min(min_longitude, wp.longitude)

    else:
        max_latitude = gpx.bounds.max_latitude
        max_longitude = gpx.bounds.max_longitude
        min_latitude = gpx.bounds.min_latitude
        min_longitude = gpx.bounds.min_longitude

    ne = pygeohash.encode(max_latitude, max_longitude)
    sw = pygeohash.encode(min_latitude, min_longitude)
    avg_latitude = min_latitude + (max_latitude - min_latitude)/2
    avg_longitude = min_longitude + (max_longitude - min_longitude)/2
    avg_geohash = pygeohash.encode(avg_latitude, avg_longitude)
    return _same_prefix(ne, sw), avg_geohash, avg_latitude, avg_longitude


def get_gpx(spider, response, soup):
    csrf = soup.find("meta", {"name": "csrf-token"})["content"]
    url_encoded_xsrf = response.cookies['XSRF-TOKEN']
    xsrf = urllib.parse.unquote(url_encoded_xsrf)
    trailpeak_session = response.cookies['trailpeak_session']
    trailpeak_session = urllib.parse.unquote(trailpeak_session)

    show_gps = soup.find("show-gps")
    if show_gps is None:
        trail_id = response.request.url.split("-")[-1]
        filepath = f"{dir_path}/../trails/data/{trail_id}.gpx"
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                return f.read()
        return None

    fields = {
        'tid': show_gps.attrs.get(":tid"),
        'cntry': show_gps.attrs.get("cntry"),
        'prov': show_gps.attrs.get("prov"),
        'gfile': show_gps.attrs.get("gfile"),
    }
    boundary = '----WebKitFormBoundary' \
               + ''.join(random.sample(string.ascii_letters + string.digits, 16))
    m = MultipartEncoder(fields=fields, boundary=boundary)
    headers = {
        'authority': 'trailpeak.com',
        'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="90", "Google Chrome";v="90"',
        'dnt': '1',
        'x-xsrf-token': url_encoded_xsrf,
        'x-csrf-token': csrf,
        'sec-ch-ua-mobile': '?0',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
        'content-type': m.content_type,
        'accept': 'application/json, text/plain, */*',
        'x-requested-with': 'XMLHttpRequest',
        'origin': 'https://trailpeak.com',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'referer': 'https://trailpeak.com/trails/rennie-cove-sea-cave-near-noel-13489',
        'accept-language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'cookie': f'XSRF-TOKEN={xsrf}; trailpeak_session={trailpeak_session}',
    }
    response = spider.session.post('https://trailpeak.com/trails/fetch-gps', headers=headers, data=m)
    return response.content


if __name__ == "__main__":
    i = 0
    for trail in trailpeak_trails():
        i += 1
        if trail["trail_id"] is None:
            continue
        print(f"{i} {trail['title']} {trail['trail_id']}")
        gpx = trail.get('gpx_data')
        if gpx is not None:
            del trail["gpx_data"]


            with open(f"{dir_path}/../trails/data/{trail['trail_id']}.json", "w") as f:
                f.write(json.dumps(trail, indent=4, sort_keys=True))

            with open(f"{dir_path}/../trails/data/{trail['trail_id']}.gpx", "wb") as f:
                f.write(gpx)

