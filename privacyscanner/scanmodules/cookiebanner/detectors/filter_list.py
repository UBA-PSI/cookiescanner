import json
import logging
import os

from abp.filters import parse_filterlist
from abp.filters.parser import Filter
from pathlib import Path

from privacyscanner.result import Result
from privacyscanner.utils import download_file
from privacyscanner.scanmodules.cookiebanner import Extractor
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import readb64, take_screenshot, \
    take_screenshots
from privacyscanner.scanmodules.cookiebanner.detectors.utils.node import filter_visible_nodes
from privacyscanner.scanmodules.cookiebanner.detectors.utils.notice import get_properties_of_cookie_notices
from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object import \
    get_array_of_node_ids_for_remote_object
from privacyscanner.scanmodules.cookiebanner.page import Page


I_DONT_CARE_ABOUT_COOKIES = 'https://www.i-dont-care-about-cookies.eu/abp/'
EASYLIST_COOKIE_LIST = "https://secure.fanboy.co.nz/fanboy-cookiemonster.txt"
COOKIE_LISTS_PATH = Path('cookie_lists')


class AdblockPlusFilter:
    def __init__(self, rules_filename: str) -> None:
        with open(rules_filename) as filterlist:
            # we only need filters with type css
            # other instances are Header, Metadata, etc.
            # other type is url-pattern which is used to block script files
            self._rules = [rule for rule in parse_filterlist(filterlist) if isinstance(rule, Filter)
                           and rule.selector.get('type') == 'css']

    def get_applicable_rules(self, domain: str) -> list:
        """Returns the rules of the filter that are applicable for the given domain."""
        return [rule for rule in self._rules if self._is_rule_applicable(rule, domain)]

    @staticmethod
    def _is_rule_applicable(rule: dict, domain: str) -> bool:
        """Tests whethere a given rule is applicable for the given domain."""
        domain_options = [(key, value) for key, value in rule.options if key == 'domain']
        if len(domain_options) == 0:
            return True

        # there is only one domain option
        _, domains = domain_options[0]

        # filter exclusion rules as they should be ignored:
        # the cookie notices do exist, the ABP plugin is just not able
        # to remove them correctly
        domains = [(opt_domain, opt_applicable) for opt_domain, opt_applicable in domains if opt_applicable is True]
        if len(domains) == 0:
            return True

        # the list of domains now only consists of domains for which the rule
        # is applicable, we check for the domain and return False otherwise
        for opt_domain, _ in domains:
            if opt_domain in domain:
                return True
        return False


class FilterListDetector(Extractor):

    def __init__(self, page: Page, result: Result, logger: logging.Logger, options: dict):
        super().__init__(page, result, logger, options)
        self.disconnect_trackers = list()
        self.result = result
        self.logger = logger
        self.options = options
        self.page = page
        abp_filter_filenames = [
            self.options['storage_path'] / COOKIE_LISTS_PATH / 'easylist-cookie.txt',
            self.options['storage_path'] / COOKIE_LISTS_PATH / 'i-dont-care-about-cookies.txt'
        ]
        self.abp_filters = {
            os.path.splitext(os.path.basename(abp_filter_filename))[0]: AdblockPlusFilter(abp_filter_filename)
            for abp_filter_filename in abp_filter_filenames
        }

    def extract_information(self) -> None:
        for abp_filter_name, abp_filter in self.abp_filters.items():
            cookie_notice_rule_node_ids = list(self.find_cookie_notices_by_rules(abp_filter))
            cookie_notice_rule_node_ids = filter_visible_nodes(self.page.tab, cookie_notice_rule_node_ids)
            if not cookie_notice_rule_node_ids:
                return
            page_screenshot = take_screenshot(self.page.tab, "website")
            page_screenshot = readb64(page_screenshot['contents'])
            self.result['cookie_notice_count'][abp_filter_name] = len(cookie_notice_rule_node_ids)
            self.result[abp_filter_name] = get_properties_of_cookie_notices(
                tab=self.page.tab, node_ids=cookie_notice_rule_node_ids,
                page_screenshot=page_screenshot, options=self.options)
            try:
                take_screenshots(tab=self.page.tab, result=self.result, cookie_notice_ids=cookie_notice_rule_node_ids,
                                 detection_method=abp_filter_name,
                                 take_screenshots=self.options["take_screenshots"],
                                 screenshots_banner_only=self.options["take_screenshots_banner_only"])
            except:
                pass

    @staticmethod
    def update_dependencies(options: dict) -> None:
        """Downloads the most recent cookie lists and saves the in the storage path defined in the options."""
        easylist_path = options['storage_path'] / COOKIE_LISTS_PATH
        easylist_path.mkdir(parents=True, exist_ok=True)
        # easylist-cookie
        download_url = EASYLIST_COOKIE_LIST
        target_file = (easylist_path / 'easylist-cookie.txt').open('wb')
        download_file(download_url, target_file)
        # i-dont-care-about-cookies
        download_url = I_DONT_CARE_ABOUT_COOKIES
        target_file = (easylist_path / 'i-dont-care-about-cookies.txt').open('wb')
        download_file(download_url, target_file)

    ############################################################################
    # COOKIE NOTICE DETECTION: RULES
    ############################################################################

    def find_cookie_notices_by_rules(self, abp_filter: AdblockPlusFilter) -> list:
        """Returns the node ids of the found cookie notices.
        The function uses the AdblockPlus ruleset of the browser plugin
        `I DON'T CARE ABOUT COOKIES`.
        See: https://www.i-dont-care-about-cookies.eu/
        """
        if self.result['site_url'].startswith('https://'):
            domain = self.result['site_url'][len('https://'):]
        elif self.result['site_url'].startswith('http://'):
            domain = self.result['site_url'][len('http://'):]
        else:
            domain = self.result['site_url']
        rules = [rule.selector.get('value') for rule in abp_filter.get_applicable_rules(domain)]
        rules_js = json.dumps(rules)

        js_function = """
            (function() {
                let rules = """ + rules_js + """;
                let cookie_notices = [];
    
                rules.forEach(function(rule) {
                    let elements = document.querySelectorAll(rule);
                    elements.forEach(function(element) {
                        cookie_notices.push(element);
                    });
                });
    
                return cookie_notices;
            })();"""

        query_result = self.page.tab.Runtime.evaluate(expression=js_function).get('result')
        return get_array_of_node_ids_for_remote_object(self.page.tab, query_result.get('objectId'))
