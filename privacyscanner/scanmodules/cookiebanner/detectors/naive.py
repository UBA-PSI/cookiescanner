import logging
import pychrome

from privacyscanner.scanmodules.cookiebanner.base import Extractor
from privacyscanner.scanmodules.cookiebanner.detectors.utils.clickable import get_by_type
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import readb64, take_screenshot, take_screenshots
from privacyscanner.scanmodules.cookiebanner.detectors.utils.node import get_node_id_for_remote_object, \
    get_remote_object_id_by_node_id
from privacyscanner.scanmodules.cookiebanner.detectors.utils.notice import get_properties_of_cookie_notice, \
    search_and_get_coordinates
from privacyscanner.scanmodules.cookiebanner.page import Page


class NaiveDetector(Extractor):

    def __init__(self, page: Page, result: dict, logger: logging.Logger, options: dict):
        super().__init__(page, result, logger, options)
        self.disconnect_trackers = []
        self.result = result
        self.logger = logger
        self.options = options
        self.page = page

    def extract_information(self):
        page_screenshot = take_screenshot(self.page.tab, "website")
        page_screenshot = readb64(page_screenshot['contents'])

        node = search_and_get_coordinates(page=self.page, search_string="cookie", options=self.options)
        if not node:
            return
        properties_of_cookie_notice = \
            get_properties_of_cookie_notice(tab=self.page.tab, node_id=node['node_id'],
                                            options=self.options, page_screenshot=page_screenshot)
        number_of_buttons = len(
            get_by_type(clickables=properties_of_cookie_notice['clickables'], type_of_clickable='button'))
        if number_of_buttons:
            buttons_present = True
        else:
            buttons_present = False

        while not buttons_present:
            # Fetch parent node
            node_id = get_parent_node(self.page.tab, properties_of_cookie_notice['node_id'])
            # Boolean False -> No parent
            if not node_id:
                break
            else:
                properties_of_cookie_notice = \
                    get_properties_of_cookie_notice(
                        tab=self.page.tab, node_id=node_id,
                        options=self.options, page_screenshot=page_screenshot)
            number_of_buttons = len(get_by_type(clickables=properties_of_cookie_notice['clickables'],
                                                type_of_clickable='button'))
            # If present, break
            if number_of_buttons > 0:
                break

        self.result['cookie_notice_count']['naive'] = 1
        self.result['naive'] = [properties_of_cookie_notice]
        try:
            take_screenshots(tab=self.page.tab, result=self.result,
                             cookie_notice_ids=[properties_of_cookie_notice["node_id"]],
                             detection_method="naive",
                             take_screenshots=self.options["take_screenshots"],
                             screenshots_banner_only=self.options["take_screenshots_banner_only"])
        except:
            pass

    def find_cookie_notices_naive_detection(self, cookie_node_ids: list) -> list:
        """Runs the naive detection an a list of provided node ids."""
        cookie_notice_naive_ids = list()
        for node_id in cookie_node_ids:
            node_id = self.naive_detection(node_id)
            if node_id:
                cookie_notice_naive_ids.append(node_id)
        return cookie_notice_naive_ids

    def naive_detection(self, node_id: int) -> int:
        """Traverse up to the node below the BODY tag or document node and return it for a given node."""
        js_function = """
            function naiveDetection(elem) {
                if (!elem) elem = this;
                while(elem && elem.parentNode !== document) {
                    let style = getComputedStyle(elem);
                    if (elem.parentNode.tagName == "BODY") {
                        return elem;
                    }
                    elem = elem.parentNode;
                }
                return elem; // html node
            }"""

        try:
            remote_object_id = get_remote_object_id_by_node_id(tab=self.page.tab, node_id=node_id)
            result = self.page.tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                                          silent=False).get('result')
            result_node_id = get_node_id_for_remote_object(tab=self.page.tab, remote_object_id=result['objectId'])
            return result_node_id
        except pychrome.exceptions.CallMethodException as e:
            pass


def get_parent_node(tab: pychrome.Tab, node_id: int) -> dict or False:
    """Returns the parent Node for a node id or 'False' if the parent Node is the BODY tag."""
    js_function = """
         function getParentNode(elem) {
            if (!elem) elem = this;
            if (elem.nodeName === "BODY"){
                return false
            }
            if(elem.parentNode.nodeName !== "BODY") {
                return elem.parentNode
            }
            else {
                return false
            }
        }   
    """

    try:
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id, silent=True).get('result')
        result = get_node_id_for_remote_object(tab, result.get('objectId'))
        return result
    except pychrome.exceptions.CallMethodException as e:
        return False


def get_body_node_id(self, tab: pychrome.Tab) -> int:
    'Returns the ID of the body node.'
    js_function = """
    function getBody(){
        return document.body;
    }
    getBody();
    """
    result = tab.Runtime.evaluate(expression=js_function).get('result')
    result = get_node_id_for_remote_object(tab=tab, remote_object_id=result.get('objectId'))
    return result
