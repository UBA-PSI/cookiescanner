import base64
import json
import logging
import pychrome

from privacyscanner.result import  Result
from privacyscanner.scanmodules.cookiebanner.base import Extractor
from privacyscanner.scanmodules.cookiebanner.detectors.utils.clickable import click_node, get_by_text
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import sanitize_file_name, take_screenshot
from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object \
    import get_object_for_remote_object, get_remote_object_id_by_node_id
from privacyscanner.scanmodules.cookiebanner.page import Page
from privacyscanner.utils import download_file

# PRIVACY_WORDING_URL = "https://raw.githubusercontent.com/RUB-SysSec/we-value-your-privacy/master/privacy_wording.json"


class PrivacyPolicyExtractor(Extractor):
    def __init__(self, page: Page, result: Result, logger: logging.Logger, options: dict):
        super().__init__(page, result, logger, options)
        self.result = result
        self.logger = logger
        self.options = options
        self.page = page
        self.privacy_wording_list = None

    def extract_information(self):
        """This function extracts the privacy policy on a page given the cookie notice."""
        self.load_json()
        words = self.check_for_language(language=self.result['language'])
        if words:
            self.logger.info('The language of the webpage is: {0}'.format(self.result['language']))
            self.logger.info(
                'The keyowrds that classify a clickable as the one of a privacy policy are: {0}'.format(words))
            preferred_detector = self.result['preferred_detector']
            cookie_notice = PrivacyPolicyExtractor.fetch_single_element(element=self.result[preferred_detector])
            searched_clickable = self.search_through_clickables(cookie_notice=cookie_notice,
                                                                words=words)
            if searched_clickable:
                privacy_policy = self.load_and_extract_policy(clickable=searched_clickable,
                                                              cookie_notice=cookie_notice)
                self.result['privacy_policy_present'] = True
                self.result['privacy_policy'] = privacy_policy
                self.result['word_count'] = len(self.result['privacy_policy']['text'].split(' '))
                searched_clickable['role'] = 'privacy policy'
                self.logger.info('A privacy policy is present.')
                # Take and save a screenshot of the policy page
                file_name = f"{sanitize_file_name(text=searched_clickable['text'])}.png"
                screenshot = take_screenshot(tab=self.page.tab, name=file_name)
                self.result.add_file(filename=file_name, contents=screenshot["contents"])
                screenshot["contents"] = base64.b64encode(screenshot["contents"]).decode('utf-8')
                self.result["screenshots"]["privacy_policy"] = [screenshot]
            else:
                self.result['privacy_policy_present'] = False
                self.logger.info('There is no privacy policy present.')
        else:
            self.result['privacy_policy_present'] = False
            self.logger.info('There is no privacy policy present.')

    def load_json(self) -> None:
        """Loads the JSON-string with the privacy wording into a dict and saves it in the extractor."""
        # path = FOLDER + '/' + file_name
        privacy_wording_list = json.loads(open(self.options['storage_path'] / 'privacy_wording.json').read())
        self.privacy_wording_list = privacy_wording_list

    def check_for_language(self, language: str) -> list or None:
        """Checks whether the language code of the page is included in the privacy wording list and returns a list of
        the matching privacy words or None if there is no match."""
        language = [entry for entry in self.privacy_wording_list if entry['country'] == language]
        if language:
            return language[0]['words']
        else:
            return None

    def search_through_clickables(self, cookie_notice: dict, words: list) -> dict or None:
        """Loops through the clickables and returns the first one that includes one of the words from the privacy
        wording list or None if there is no match."""
        searched_clickable = [clickable for clickable in cookie_notice['clickables']
                              for word in words if word in clickable['text'].lower()]
        if searched_clickable:
            return searched_clickable[0]
        else:
            return None

    def load_and_extract_policy(self, clickable: dict, cookie_notice: dict) -> dict:
        """Clicks on the clickable that has been identified as the link to the page with the privacy policy.
         It waits for three seconds and extracts the text of the page body as the privacy policy via a JS function."""
        # Fetch the clickable by text
        resulting_clickable = get_by_text(clickable_to_find=clickable, clickables=cookie_notice['clickables'])
        # Click on page
        click_node(self.page.tab, resulting_clickable['node_id'])
        self.page.tab.wait(3)
        # Get HTML
        content = self._extract_text_from_body()
        content['word_count'] = len(content['text'].split(' '))
        return content

    def _extract_text_from_body(self) -> dict:
        """JS function that extracts the text as well as the HTML of a page body."""
        document = self.page.tab.DOM.getDocument(depth=-1)
        root_node_id = document['root']['nodeId']
        js_function = """
            function getText() {
                elem = document.body
                if (!elem) elem = this;

                return {
                    'html': elem.outerHTML,
                    'text': elem.innerText,
                }
            }
            """
        try:
            remote_object_id = get_remote_object_id_by_node_id(self.page.tab, root_node_id)
            result = self.page.tab.Runtime.callFunctionOn(functionDeclaration=js_function,
                                                          objectId=remote_object_id, silent=True).get('result')
            result = get_object_for_remote_object(tab=self.page.tab, remote_object_id=result['objectId'])
            return result
        except pychrome.exceptions.CallMethodException as e:
            pass

    # Fetch a single element, either the element itself or the first element from a list
    @staticmethod
    def fetch_single_element(element: dict or list) -> dict:
        if isinstance(element, list):
            return_element = element[0]
        else:
            return_element = element
        return return_element

    @staticmethod
    def update_dependencies(options):
        # privacy_wording_list = (options['storage_path'] / 'privacy_wording.json').open('wb')
        # download_file(PRIVACY_WORDING_URL, privacy_wording_list)
        # The file matches the keywords for the country code. Since I detect the language of the website,
        # I adapted the country code to the language code, at least for English (EN)
        # Other changes may be required depending on the language for which you are extracting the policies.
        return
