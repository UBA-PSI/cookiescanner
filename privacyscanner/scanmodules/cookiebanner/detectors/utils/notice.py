import langdetect
import numpy as np
import pychrome

from langdetect import detect

from privacyscanner.scanmodules.cookiebanner.detectors.utils.clickable import get_properties_of_clickables, \
    find_clickables_in_node, remove_invisible_clickables
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import get_dimensions_of_remote_object, \
    is_page_modal
from privacyscanner.scanmodules.cookiebanner.detectors.utils.node import get_text_of_node, is_script_or_style_node
from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object import get_remote_object_id_by_node_id
from privacyscanner.scanmodules.cookiebanner.page import Page
from privacyscanner.scanmodules.cookiebanner.utils import get_object_for_remote_object


def get_properties_of_cookie_notices(tab: pychrome.Tab, node_ids: list, options: dict,
                                     page_screenshot: np.ndarray) -> list:
    """Calls the function 'get_properties_of_cookie_notice_modified' to get the properties of each provided node id."""
    return [get_properties_of_cookie_notice(tab=tab, node_id=node_id, options=options,
                                            page_screenshot=page_screenshot) for node_id in node_ids]


def get_properties_of_cookie_notice(tab: pychrome.Tab, node_id: int, options: dict, page_screenshot: np.ndarray)\
        -> dict:
    """Returns the properties of a cookie notice."""
    js_function = """
        function getCookieNoticeProperties(elem) {
             if (!elem) elem = this;
             const style = getComputedStyle(elem);

            let width = elem.offsetWidth;
            if (width >= document.documentElement.clientWidth) {
                width = 'full';
            }
            let height = elem.offsetHeight;
            if (height >= document.documentElement.clientHeight) {
                height = 'full';
            }

             return {
                 'html': elem.outerHTML,
                 'has_id': elem.hasAttribute('id'),
                 'has_class': elem.hasAttribute('class'),
                 'id': elem.getAttribute('id'),
                 'text': elem.innerText,
                 'fontsize': style.fontSize,
                 'width': width,
                 'height': height,
                 'x': elem.getBoundingClientRect().left,
                 'y': elem.getBoundingClientRect().top,
             }
         }"""

    try:
        modified_clickables = find_clickables_in_node(tab, node_id)
        clickables_with_onclick_listeners = list()  # get_all_child_elements(tab, node_id)
        if isinstance(clickables_with_onclick_listeners, dict):
            clickables_with_onclick_listeners = None
        if clickables_with_onclick_listeners:
            modified_clickables = modified_clickables + clickables_with_onclick_listeners
        # Remove any duplicate values
        modified_clickables = list(dict.fromkeys(modified_clickables))
        modified_clickables_properties = get_properties_of_clickables(tab=tab, node_ids=modified_clickables,
                                                                      page_screenshot=page_screenshot)

        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                            silent=True).get('result')
        cookie_notice_properties = get_object_for_remote_object(tab, result.get('objectId'))
        cookie_notice_properties['node_id'] = node_id
        cookie_notice_properties['clickables'] = modified_clickables_properties
        remove_invisible_clickables(cookie_notice=cookie_notice_properties)
        cookie_notice_properties['is_page_modal'] = is_page_modal(tab, {
            'x': cookie_notice_properties.get('x'),
            'y': cookie_notice_properties.get('y'),
            'width': cookie_notice_properties.get('width'),
            'height': cookie_notice_properties.get('height'),
        })
        try:
            cookie_notice_properties['language'] = langdetect.detect(cookie_notice_properties['text'])
        except:
            cookie_notice_properties['language'] = None
        if cookie_notice_properties["height"] == "full":
            cookie_notice_properties["height"] = options["resolution"]["height"]
        if cookie_notice_properties["width"] == "full":
            cookie_notice_properties["width"] = options["resolution"]["width"]
        return cookie_notice_properties
    except pychrome.exceptions.CallMethodException as e:
        cookie_notice_properties = dict.fromkeys([
            'html', 'has_id', 'has_class', 'unique_class_combinations',
            'unique_attribute_combinations', 'id', 'class', 'text',
            'fontsize', 'width', 'height', 'x', 'y', 'node_id', 'clickables',
            'is_page_modal'])
        return cookie_notice_properties


def detect_language(tab: pychrome.Tab) -> str:
    """Uses langdetect to determine the language of a webpage."""
    try:
        result = tab.Runtime.evaluate(expression='document.body.innerText').get('result')
        language = detect(result.get('value'))
        return language
    except Exception as e:
        pass


def search_for_string(tab: pychrome.Tab, search_string: str) -> list:
    """Searches the DOM for the given string and returns all node ids where the string matches."""

    # stop execution of scripts to ensure that results do not change during search
    tab.Emulation.setScriptExecutionDisabled(value=True)

    # search for the string in a text node
    # take the parent of the text node (the element that contains the text)
    # this is necessary if an element contains more than one text node!
    # see for explanation:
    # - https://stackoverflow.com/a/2994336
    # - https://stackoverflow.com/a/11744783
    search_object = tab.DOM.performSearch(
        query="//body//*/text()[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '"
              + search_string + "')]/parent::*")

    node_ids = []
    if search_object.get('resultCount') != 0:
        search_results = tab.DOM.getSearchResults(
            searchId=search_object.get('searchId'),
            fromIndex=0,
            toIndex=int(search_object.get('resultCount')))
        node_ids = search_results.get('nodeIds')

    # remove script and style nodes
    node_ids = [node_id for node_id in node_ids if not is_script_or_style_node(tab, node_id)]

    # resume execution of scripts
    tab.Emulation.setScriptExecutionDisabled(value=False)

    # return nodes
    return node_ids


def search_and_get_coordinates(page: Page, search_string: str, options: dict = None) -> dict or None:
    """Searches a page for a string and returns all nodes with more than three words and within the bounds of the page
     on initial page load. Returns the node with the most words as a dict in the form {'node_id': int,
     'word_count': int, search_string: str}."""
    nodes = search_for_string(page.tab, search_string)
    list_of_coordinates = list()
    if nodes:
        for node_id in nodes:
            if node_id:
                properties = get_dimensions_of_remote_object(page.tab, node_id)
                properties['text'] = get_text_of_node(page.tab, node_id)
                if not properties['text']:
                    continue
                word_count = len(properties['text'].split(' '))
                if (properties['x'] == 0 and properties['y'] == 0) or properties['x'] >= \
                        options['resolution']['width'] or properties['y'] >= options['resolution']['height']:
                    continue
                else:
                    properties['node_id'] = node_id
                    properties['word_count'] = word_count
                    properties['search_string'] = search_string
                    list_of_coordinates.append(properties)
            else:
                continue
        if list_of_coordinates:
            list_of_coordinates = sorted(list_of_coordinates, key=lambda i: i['word_count'], reverse=True)
            return list_of_coordinates[0]
        else:
            return None
    else:
        return None
