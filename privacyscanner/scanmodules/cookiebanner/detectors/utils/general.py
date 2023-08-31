import base64
import cv2
import json
import numpy as np
import pychrome

from privacyscanner.scanmodules.cookiebanner.detectors.utils.node import get_remote_object_id_by_node_id
from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object import get_object_for_remote_object

from PIL import Image
from io import BytesIO


def get_dimensions_of_remote_object(tab: pychrome.Tab, node_id: int) -> dict or None:
    """Executes a Javascript on an object referenced by node id to determine the dimensions and position (x, y, width,
    height) as a dictionary."""
    js_function = """
    function getDimensions(elem){
        if (!elem) elem = this;
        domRect = elem.getBoundingClientRect()
        return {'x': domRect['x'], 'y': domRect['y'], 'width': domRect['width'], 'height': domRect['height']}
    }"""

    try:
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                            silent=True).get('result')
        result = get_object_for_remote_object(tab, result.get('objectId'))
        return result
    except pychrome.exceptions.CallMethodException as e:
        return None


def is_page_modal(tab: pychrome.Tab, cookie_notice: dict = None) -> bool:
    """Executes a JS function to determine whether the provided clickable is modal."""
    cookie_notice_js = json.dumps(cookie_notice)

    js_function = """
        (function modal() {
            let margin = 5;
            let cookieNotice = """ + cookie_notice_js + """;

            let viewportWidth = document.documentElement.clientWidth;
            let viewportHeight = document.documentElement.clientHeight;
            let viewportHorizontalCenter = viewportWidth / 2;
            let viewportVerticalCenter = viewportHeight / 2;

            let testPositions = [
                {'x': margin, 'y': margin},
                {'x': margin, 'y': viewportVerticalCenter},
                {'x': margin, 'y': viewportHeight - margin},
                {'x': viewportVerticalCenter, 'y': margin},
                {'x': viewportVerticalCenter, 'y': viewportHeight - margin},
                {'x': viewportWidth - margin, 'y': margin},
                {'x': viewportWidth - margin, 'y': viewportVerticalCenter},
                {'x': viewportWidth - margin, 'y': viewportHeight - margin},
            ];

            if (cookieNotice) {
                if (cookieNotice.width == 'full') {
                    cookieNotice.width = viewportWidth;
                }
                if (cookieNotice.height == 'full') {
                    cookieNotice.height = viewportHeight;
                }
                for (var i = 0; i < testPositions.length; i++) {
                    let testPosition = testPositions[i];
                    if ((testPosition.x >= cookieNotice.x && testPosition.x <= (cookieNotice.x + cookieNotice.width)) &&
                            (testPosition.y >= cookieNotice.y && testPosition.y <= 
                            (cookieNotice.y + cookieNotice.height))) {
                        let index = testPositions.indexOf(testPosition);
                        testPositions.splice(index, 1);
                    }
                }
            }

            let previousContainer = document.elementFromPoint(testPositions[0].x, testPositions[0].y);
            for (var i = 1; i < testPositions.length; i++) {
                let testPosition = testPositions[i];
                let testContainer = document.elementFromPoint(testPosition.x, testPosition.y);
                if (previousContainer !== testContainer) {
                    return false;
                }
                previousContainer = testContainer;
            }
            return true;
        })();"""

    result = tab.Runtime.evaluate(expression=js_function).get('result')
    return result.get('value')


def take_screenshot(tab: pychrome.Tab, name: str) -> dict:
    """Returns a screenshot of the tab in the form of a dict. {'filename': str 'contents' base64str}"""
    # get the width and height of the viewport
    layout_metrics = tab.Page.getLayoutMetrics()
    viewport = layout_metrics.get('layoutViewport')
    width = viewport.get('clientWidth')
    height = viewport.get('clientHeight')
    x = viewport.get('pageX')
    y = viewport.get('pageY')
    screenshot_viewport = {'x': x, 'y': y, 'width': width, 'height': height, 'scale': 1}
    # take screenshot and store it
    screenshot = {'filename': name,
                  'contents': base64.b64decode(tab.Page.captureScreenshot(clip=screenshot_viewport)['data'])}
    return screenshot


def take_screenshot_banner_only(tab: pychrome.Tab, name: str, screenshot_viewport: dict) -> dict:
    """Takes a screenshot of the banner only restricted by the viewport/dimensions of the banner. Returns the screenshot
    as a dict in the form {'filename: str, 'contents': base64str}"""
    screenshot_viewport = {'x': screenshot_viewport['x'], 'y': screenshot_viewport['y'],
                           'width': screenshot_viewport['width'], 'height': screenshot_viewport['height'], 'scale': 1}
    screenshot = {'filename': name,
                  'contents': base64.b64decode(tab.Page.captureScreenshot(clip=screenshot_viewport)['data'])}
    return screenshot


def take_screenshot_banner_highlighted(tab: pychrome.Tab, node_id: int, name: str) -> dict:
    _highlight_node(tab=tab, node_id=node_id)
    screenshot = {'filename': name,
                  'contents': base64.b64decode(tab.Page.captureScreenshot()['data'])}
    hide_highlight(tab=tab)
    return screenshot


def _highlight_node(tab: pychrome.Tab, node_id: int):
    """Highlight the given node with an overlay."""
    tab.Overlay.enable()
    color_content = {'r': 152, 'g': 196, 'b': 234, 'a': 0.5}
    color_padding = {'r': 184, 'g': 226, 'b': 183, 'a': 0.5}
    color_margin = {'r': 253, 'g': 201, 'b': 148, 'a': 0.5}
    highlight_config = {'contentColor': color_content, 'paddingColor': color_padding, 'marginColor': color_margin}
    tab.Overlay.highlightNode(highlightConfig=highlight_config, nodeId=node_id)


def hide_highlight(tab: pychrome.Tab) -> None:
    """Hide all overlays in a given tab."""
    tab.Overlay.hideHighlight()
    tab.Overlay.disable()


def take_screenshots(tab: pychrome.Tab, result: dict, cookie_notice_ids: [int], detection_method: str,
                     take_screenshots: bool, screenshots_banner_only: bool) -> None:
    screenshots = list()
    if take_screenshots:
        for index, node_id in enumerate(cookie_notice_ids):
            file_name = f"{detection_method}-{index}.png"
            # highlight and take screenshot
            screenshot = take_screenshot_banner_highlighted(tab=tab, node_id=node_id, name=file_name)
            result.add_file(filename=screenshot['filename'], contents=screenshot['contents'])
            screenshots.append(
                {"filename": screenshot["filename"],
                 "contents": base64.b64encode(screenshot['contents']).decode('utf-8')
                 })
    if screenshots_banner_only:
        for index, node_id in enumerate(cookie_notice_ids):
            file_name = f"{detection_method}_banner_only-{index}.png"
            screenshot_viewport = {'x': int(result[detection_method][index]['x']),
                                   'y': int(result[detection_method][index]['y']),
                                   'width': result[detection_method][index]['width'],
                                   'height': result[detection_method][index]['height'], 'scale': 1}
            if screenshot_viewport["width"] == 0:
                screenshot_viewport["width"] = 1920
            if screenshot_viewport["height"] == 0:
                screenshot_viewport["height"] = 300
            # take screenshot of only the banner of the node
            screenshot = take_screenshot_banner_only(tab=tab, name=file_name,
                                                     screenshot_viewport=screenshot_viewport)
            result.add_file(filename=screenshot['filename'], contents=screenshot['contents'])
            screenshots.append(
                {"filename": screenshot["filename"],
                 "contents": base64.b64encode(screenshot['contents']).decode('utf-8')
                 })
    if take_screenshots or screenshots_banner_only:
        result["screenshots"][detection_method] = screenshots


def readb64(base64_string: str) -> np.ndarray:
    """Takes a base64 string and returns an image processable by opencv.
    https://stackoverflow.com/questions/33754935/read-a-base-64-encoded-image-from-memory-using-opencv-python-library/54205640"""
    pimg = Image.open(BytesIO(base64_string))
    return cv2.cvtColor(np.array(pimg), cv2.IMREAD_COLOR)


def sanitize_file_name(text: str) -> str:
    file_symbols = ['\\', '/', ',', '.', ':', ';', '%']
    file_name = ''.join([char if char not in file_symbols else ' ' for char in text])
    if len(file_name) > 50:
        file_name = file_name[: 50]
    return file_name
