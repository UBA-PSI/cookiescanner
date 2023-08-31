import json
import logging

from pathlib import Path
from tldextract import extract

from privacyscanner.scanmodules.cookiebanner.base import Extractor
from privacyscanner.scanmodules.cookiebanner.page import Page
from privacyscanner.utils import download_file

DISCONNECT_PATH = Path('disconnect')
DISCONNECT_DOWNLOAD_URL = "https://raw.githubusercontent.com/disconnectme/disconnect-tracking-protection/master/services.json"


class TrackerExtractor(Extractor):
    def __init__(self, page: Page, result: dict, logger: logging.Logger, options: dict):
        super().__init__(page, result, logger, options)
        self.disconnect_trackers = list()
        self.result = result
        self.logger = logger
        self.options = options
        self.page = page

    def extract_information(self):
        """Loads the disconnect list and checks each request against it. Saves all the requests with a matching url and
         the total number of matching requests in to the result dict. Apart from the matching request, it also returns the
          category, the company, the company_url and the domain of the tracker."""
        self._load_disconnect_list()
        for request in self.page.request_log:
            tracking_request = self._check_against_disconnect_list(request['url'])
            if tracking_request:
                self.disconnect_trackers.append({'url': request, 'tracker': tracking_request})
        self.result['disconnect'] = self.disconnect_trackers
        self.result['disconnect_num'] = len(self.disconnect_trackers)

    def _load_disconnect_list(self):
        """Internal function that loads the disconnect list into a dict."""
        file = open(self.options['storage_path'] / DISCONNECT_PATH / 'disconnect.json', encoding='utf-8').read()
        disconnect_list = json.loads(file)
        self.disconnect_list = disconnect_list

    def _check_against_disconnect_list(self, request: str) -> dict or None:
        """Checks a request against the disconnect list. If a request matches a domain from the list, the function
        returns the category, the company, the company url, as well as the domain or None in case of no match."""
        for category in self.disconnect_list['categories'].keys():
            for entity in self.disconnect_list['categories'][category]:
                for company in entity.keys():
                    for url in entity[company].keys():
                        # Hack to ignore other keys set to "true".
                        if entity[company][url] == "true":
                            continue
                        for domain in entity[company][url]:
                            request_domain = extract(request).registered_domain
                            # Exclude matches if it is a same-site-request (e. g. https://forbes.com is classified as
                            # 'Advertising')
                            if domain in request and len(domain) > 5 and request_domain != domain:
                                # print('The request_domain: {} and the domain: {}'.format(request_domain, domain))
                                return {'category': category, 'company': company, 'company_url': url, 'domain': domain}
        return None

    @staticmethod
    def update_dependencies(options):
        disconnect_path = options['storage_path'] / DISCONNECT_PATH
        disconnect_path.mkdir(parents=True, exist_ok=True)
        original_list = (disconnect_path / 'services.json').open('wb')
        download_file(DISCONNECT_DOWNLOAD_URL, original_list)
        disconnect_list = json.load(open(disconnect_path / 'services.json', encoding='utf-8'))
        del disconnect_list['categories']['Content']
        with open(disconnect_path / 'disconnect.json', 'w', encoding='utf-8') as f:
            json.dump(disconnect_list, f, ensure_ascii=False, indent=2)
