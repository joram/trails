#!/usr/bin/env python3
import logging
import os
import re
from typing import List

import bs4
import requests
import requests_cache
from requests_cache import CachedSession

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
    url_regexes = []
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
        urls = []
        for regex in self.url_regexes:
            anchors = soup.findAll('a', href=re.compile(regex))
            for a in anchors:
                href = a["href"]
                if not href.startswith(self.domain):
                    href = f"{self.domain}{href}"
                if self.strip_params and "?" in href:
                    href = href.split("?")[0]
                urls.append(href)
        return urls

