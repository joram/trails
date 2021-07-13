#!/usr/bin/env python3
import logging
import os
import re

from scripts.base_spider import Spider

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


if __name__ == "__main__":
    spider = PeakbaggerPagesSpider()
    for response, soup in spider.crawl():
        if "ascent" in response.request.url:
            peak_link = soup.find("a", href=re.compile(r'peak\.aspx\?pid=[0-9]*'))
            if peak_link:
                peak_url = f"https://www.peakbagger.com/climber/{peak_link['href']}"
                peak_response = spider.session.get(peak_url)

            gpx_links = soup.findAll("a", href=re.compile(r'GPXFile\.aspx\?aid=[.]*'))
            for a in gpx_links:
                url = f"https://www.peakbagger.com/climber/{a['href']}"
                gpx_response = spider.session.get(url)
                print(gpx_response.status_code, url)

        print(response.status_code, response.request.url)
