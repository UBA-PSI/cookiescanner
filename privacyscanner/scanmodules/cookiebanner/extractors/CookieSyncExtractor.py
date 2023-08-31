import logging
import tldextract

from datetime import datetime
from numpy import Infinity
from zxcvbn import zxcvbn

from privacyscanner.scanmodules.cookiebanner.base import Extractor
from privacyscanner.scanmodules.cookiebanner.page import Page

TIME_PLUS_ONE_YEAR_IN_SECONDS = datetime.now().timestamp() + 60 * 60 * 24 * 365


class CookieSyncExtractor(Extractor):
    def __init__(self, page: Page, result: dict, logger: logging.Logger, options: dict):
        super().__init__(page, result, logger, options)
        self.disconnect_trackers = list()
        self.result = result
        self.logger = logger
        self.options = options
        self.page = page

    def extract_information(self) -> None:
        """Extracts all cookies that are considered to be identifier candidates, the cookie syncs,
        and their total number."""
        self.result['id_cookies'] = self.check_cookies()
        self.result['cookie_syncs'] = self.check_identity_sync()
        self.result['cookie_syncs_num'] = len(self.result['cookie_syncs'])

    def check_cookies(self) -> list:
        """Checks whether a cookie could be an identifier. Criteria: Expiration date >= 1 year or zxcvbn value of 9
        or greater. """
        id_cookies = list()
        for cookie in self.result['cookies']:
            if cookie['value']:
                if cookie['expires'] >= TIME_PLUS_ONE_YEAR_IN_SECONDS or zxcvbn(cookie['value'])['guesses_log10'] >= 9:
                    cookie['zxcvbn'] = zxcvbn(cookie['value'])['guesses_log10']
                    if cookie['zxcvbn'] == Infinity:
                        cookie['zxcvbn'] = 1
                    id_cookies.append(cookie)
        return id_cookies

    def check_identity_sync(self) -> list:
        """Loops through all the cookies and requests and checks whether the value of a cookie is included in a request
        and adds it to the list of syncs  if it is considered to be an identifier."""
        synced_cookies = list()
        for cookie in self.result['id_cookies']:
            for request in self.page.request_log:
                if len(cookie['value']) > 10 and cookie['value'] in request['url']:
                    ext = tldextract.extract(request['url'])
                    sync_domain = '.'.join(ext[:3])
                    synced_cookies.append(
                        {'cookie_value': cookie['value'], 'sync_domain': sync_domain, 'sync_request': request['url'],
                         'zxcvbn': cookie['zxcvbn']})
        return synced_cookies
