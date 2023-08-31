import cv2
import logging
import matplotlib.pyplot as plt
import numpy
import pychrome

from privacyscanner.scanmodules.cookiebanner import Extractor, get_remote_object_id_by_node_id
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import readb64, take_screenshot, take_screenshots
from privacyscanner.scanmodules.cookiebanner.detectors.utils.notice import get_properties_of_cookie_notice, \
    search_and_get_coordinates
from privacyscanner.scanmodules.cookiebanner.page import Page
from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object import get_node_id_for_remote_object


class SimplePerceptiveDetector(Extractor):

    def __init__(self, page: Page, result: dict, logger: logging.Logger, options: dict):
        super().__init__(page, result, logger, options)
        self.disconnect_trackers = []
        self.result = result
        self.logger = logger
        self.options = options
        self.page = page

    def extract_information(self):
        # get coordinates of search term
        coordinates = search_and_get_coordinates(page=self.page, search_string='cookie', options=self.options)
        if not coordinates:
            return
        self.prepare_site(self.page.tab)
        # take screenshot of webpage
        page_screenshot = take_screenshot(self.page.tab, "website")
        page_screenshot = readb64(page_screenshot['contents'])
        bordersize = 1
        modified_screenshot = cv2.copyMakeBorder(
            page_screenshot,
            top=bordersize,
            bottom=bordersize,
            left=bordersize,
            right=bordersize,
            borderType=cv2.BORDER_CONSTANT,
            value=[0, 0, 0]
         )
        if self.options['perceptive_show_results']:
            plt.imshow(page_screenshot)
            plt.show()

        color = self.determine_bg_color(image=page_screenshot, coordinates=coordinates)
        # get gray scale image of cookie notice
        gray_scale_image = self.naive_perceptive_detection(image=modified_screenshot, color=color)
        if self.options['perceptive_show_results']:
            plt.imshow(gray_scale_image)
            plt.show()
        # Extract the coordinates of the banner
        node_coordinates_and_contour = self.extract_coordinates_and_contour(original_image=page_screenshot,
                                                                            processed_image=gray_scale_image,
                                                                            coordinates=coordinates)
        if not node_coordinates_and_contour:
            self.logger.info("Unable to extract coordinates and consent notice dimensions - Abort perceptive detection")
            return

        node_coordinates, contour = node_coordinates_and_contour

        cookie_banner_node = self.page.tab.DOM.getNodeForLocation(
            x=node_coordinates['x'], y=node_coordinates['y'])

        if not cookie_banner_node:
            self.logger.info("Unable to extract node at location - Abort perceptive detection")
            return

        min_x = contour["x"]
        max_x = contour["x"] + contour["width"]
        min_y = contour["y"]
        max_y = contour["y"] + contour["height"]
        max_area = contour["width"] * contour["height"]

        optimized_node = get_parent_node_while_area_increases(tab=self.page.tab, node_id=cookie_banner_node['nodeId'],
                                                              min_x=min_x, max_x=max_x,
                                                              min_y=min_y, max_y=max_y,
                                                              max_area=max_area)
        if optimized_node:
            cookie_banner_node = {"nodeId": optimized_node}

        properties_of_cookie_notice = get_properties_of_cookie_notice(tab=self.page.tab,
                                                                      node_id=cookie_banner_node['nodeId'],
                                                                      options=self.options,
                                                                      page_screenshot=page_screenshot)
        self.result['perceptive'] = [properties_of_cookie_notice]
        self.result['cookie_notice_count']['perceptive'] = 1

        try:
            take_screenshots(tab=self.page.tab, result=self.result, cookie_notice_ids=[cookie_banner_node["nodeId"]],
                             detection_method="perceptive",
                             take_screenshots=self.options["take_screenshots"],
                             screenshots_banner_only=self.options["take_screenshots_banner_only"])
        except:
            pass

    def determine_bg_color(self, image: numpy.ndarray, coordinates: dict) -> list:
        """Returns the background color of a pixel in an image based on the provided coordinates in a dictionary in the
        form {'x': int, 'y': int}. Returns the RGB values in the form of a list."""
        color = image[int(coordinates['y']), int(coordinates['x'])]
        return color

    def naive_perceptive_detection(self, image: numpy.ndarray, color: list) -> numpy.ndarray:
        """Runs the perceptive detection and returns the image masked with the provided color."""
        processed_image = cv2.bitwise_xor(image, color)
        processed_image = cv2.cvtColor(processed_image, cv2.COLOR_RGB2GRAY)
        (thresh, processed_image) = cv2.threshold(processed_image, 0, 255, cv2.THRESH_BINARY)
        return processed_image

    def extract_coordinates_and_contour(self, original_image: numpy.ndarray, processed_image: numpy.ndarray,
                                        coordinates: dict) -> tuple:
        """Extracts the outer most contour that has the minimum specified area."""
        # Find my contours
        contours = cv2.findContours(processed_image, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)[0]
        candidates = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            dimensions = {'x_min': x, 'x_max': x + width, 'y_min': y, 'y_max': y + height}
            if dimensions['x_min'] < coordinates['x'] < dimensions['x_max'] \
                    and dimensions['y_min'] < coordinates['y'] < dimensions['y_max']:
                candidates.append({"contour": contour, "contour_area": cv2.contourArea(contour)})
        candidates = sorted(candidates, key=lambda candidate: candidate["contour_area"])
        if candidates:
            contour = candidates[0]["contour"]
            #cv2.drawContours(original_image, [contour], -1, (255, 0, 0), 2)
            #plt.imshow(original_image)
            #plt.show()
            x, y, width, height = cv2.boundingRect(contour)
            # No coordinate added -> contour is shifted, therefore point is already within the contour in the "real"
            # screenshot
            first_point = contour[0][0]
            return (
                {"x": int(first_point[0]), "y": int(first_point[1])},
                {"x": x, "y": y, "width": width, "height": height}
            )

    def prepare_site(self, tab: pychrome.Tab) -> None:
        """Prepare the webpage in the provided tab by removing all embedded images."""
        js_function = """
            for (var i= document.images.length; i-->0;)
                document.images[i].parentNode.removeChild(document.images[i])
        """
        try:
            result = tab.Runtime.evaluate(expression=js_function).get('result')
            return True
        except pychrome.exceptions.CallMethodException as e:
            return False

    def _prepare_detection_screenshot(self, detection_screenshot: numpy.ndarray) -> numpy.ndarray:
        """Returns an image with the detected area highlighted. Currently not used."""
        mask = cv2.inRange(detection_screenshot, (255, 0, 0), (255, 0, 0))
        inv_mask = cv2.bitwise_not(mask)
        only_rect = cv2.bitwise_and(detection_screenshot, inv_mask)
        return only_rect


def get_parent_node_while_area_increases(tab: pychrome.Tab, node_id: int,
                                         min_x: int, max_x: int, min_y: int, max_y: int,
                                         max_area: int) -> dict:
    js_function = """
        function getParentNodeWhileAreaIncreases(elem, minX, maxX, minY, maxY, maxArea){
            var originalArea = elem.offsetHeight * elem.offsetWidth;
        
            var previousNode = elem;
            var currentNode = elem.parentNode;
        
            while (currentNode && currentNode !== document.body){
                var currentNodeRect = currentNode.getBoundingClientRect();
                var currentNodeArea = currentNode.offsetHeight * currentNode.offsetWidth;
        
                if (currentNodeArea >= originalArea &&
                    currentNodeArea <= maxArea &&
                    minX <= currentNodeRect.x <= maxX &&
                    minY <= currentNodeRect.y <= maxY){
                    previousNode = currentNode;
                    currentNode = currentNode.parentNode;
                }
                else{
                    return previousNode;
                }
            }
            return previousNode;
        }
    """

    try:
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        # -1 to account for pixel shift because of border
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                            arguments=[
                                                {"objectId": remote_object_id},
                                                {"value": min_x-1}, {"value": max_x-1},
                                                {"value": min_y-1}, {"value": max_y-1},
                                                {"value": max_area},
                                            ],
                                            silent=False).get("result")
        result = get_node_id_for_remote_object(tab, result.get('objectId'))
        return result
    except pychrome.exceptions.CallMethodException as e:
        return None
