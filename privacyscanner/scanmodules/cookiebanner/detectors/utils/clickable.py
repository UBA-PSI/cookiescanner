import numpy
import pychrome

from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object \
    import get_array_of_node_ids_for_remote_object, get_remote_object_id_by_node_id, get_object_for_remote_object
from privacyscanner.scanmodules.cookiebanner.detectors.utils.node import is_node_visible


def find_clickables_in_node(tab: pychrome.Tab, node_id: int) -> list:
    """Executes a JS function to find all the clickable elements in a DOM object identified by a node_id in a given Tab.
    The function returns a list of node_ids of the clickable elements."""
    js_function = """
        function getClickableElements(elem){
            function getAllClickables(elem){
                const childElements = Array.from(elem.querySelectorAll('*'));
                const clickableElements = childElements.filter(element =>{
                    const style = getComputedStyle(element);
                    return style.cursor === 'pointer';
                })
                return clickableElements;
            }
            function findCoveringNodes(nodes) {
                var coveringNodes = [];
                for(var i = 0; i < nodes.length; i++){
                    var node = nodes[i];
                    var parentNode = node.parentNode;
                    if(nodes.indexOf(parentNode) === -1){
                        coveringNodes.push(node);
                    }
                }
                return coveringNodes;
            }
            
            if (!elem) elem = this;
            var nodes = getAllClickables(elem);
            var coveringNodes = findCoveringNodes(nodes);
            return coveringNodes
        }
        """

    try:
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                            silent=True).get('result')
        return get_array_of_node_ids_for_remote_object(tab, result.get('objectId'))
    except pychrome.exceptions.CallMethodException as e:
        return []


def get_properties_of_clickables(tab: pychrome.Tab, node_ids: list, page_screenshot: numpy.ndarray):
    """Wrapper function that calls the function "get_properties_of_clickable" for each node id in the list."""
    return [get_properties_of_clickable(tab=tab, node_id=node_id, page_screenshot=page_screenshot)
            for node_id in node_ids]


def get_properties_of_clickable(tab: pychrome.Tab, node_id: int, page_screenshot: numpy.ndarray):
    """Extracts certain properties of a clickable, such as the HTML-code, the fontsize, the position,
    and the dimensions."""
    js_function = """
        function extractProperties(elem){
            if (!elem) elem = this;
            var computedStyle = getComputedStyle(elem);
            
            let clickable = new Object();
            clickable['localName'] = elem.localName;
            clickable['node'] = elem;
            clickable['id'] = elem.id;
            clickable['type'] = elem.type;
            clickable['html'] = elem.outerHTML;
            clickable['text'] = elem.innerText;
            clickable['fontsize'] = computedStyle.fontsize;
            clickable['width'] = elem.offsetWidth;
            clickable['height'] = elem.offsetHeight;
            clickable['x'] = elem.getBoundingClientRect().left;
            clickable['y'] = elem.getBoundingClientRect().top;
            clickable['backgroundColor'] = computedStyle.backgroundColor; 
            if(elem.firstElementChild != null && elem.firstElementChild.innerText){
             clickable['backgroundColor'] = 
                 getComputedStyle(elem.firstElementChild).backgroundColor;
            }
            if(clickable['localName'] == 'a'){
             clickable['href'] = elem.href;
            }
            if ('href' in clickable){
                let url = new URL(clickable['href']);
                if(url.pathname.includes("/") && url.pathname.length > 2) {
                    clickable['type'] = 'link';
                }
                else{
                    clickable['type'] = 'button';
                }   
            }
            if (elem.hasChildNodes()){
                for(node of elem.childNodes){
                    if (node.checked !== undefined || 
                        "ariaChecked" in node && node.ariaChecked !== null){
                        clickable = extractProperties(node);
                        clickable['type'] = 'checkbox';
                        clickable['text'] = elem.innerText;
                        if (node.checked || node.ariaChecked){
                            clickable['checked'] = true;
                        }
                        else{
                            clickable['checked'] = false;
                        }
                        break;
                    }
                }
            }
            if (elem.checked !== undefined || 
                "ariaChecked" in elem && elem.ariaChecked !== null){
                clickable['type'] = 'checkbox';
                clickable['text'] = elem.innerText;
                if (elem.checked || elem.ariaChecked){
                    clickable['checked'] = true;
                }
                else{
                    clickable['checked'] = false;
                }
            }
            if (!["checkbox", "link"].includes(clickable["type"])){
                clickable["type"] = "button";
            }
            return {
            'localName' : clickable['localName'], 
            'node' : elem, 'html' : clickable['html'], 
            'text': clickable['text'], 
            'fontsize' : clickable['fontsize'], 
            'width' : clickable['width'],
            'height' : clickable['height'], 
            'x' : clickable['x'], 
            'y' : clickable['y'], 
            'type' : clickable['type'],
            'backgroundColor' : clickable['backgroundColor'],
            'href' : clickable['href'], 
            'checked' : clickable['checked']
            }
        }
        """

    try:
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                            silent=True).get('result')
        properties_of_clickable = get_object_for_remote_object(tab, result.get('objectId'))
        if "html" not in properties_of_clickable:
            return {"is_visible": False}
        properties_of_clickable['node_id'] = node_id
        properties_of_clickable['is_visible'] = is_node_visible(tab, node_id).get('is_visible')
        properties_of_clickable['role'] = ''
        if properties_of_clickable["is_visible"]:
            clickable_contour = {
                "w": properties_of_clickable["width"], "h": properties_of_clickable["height"],
                "x": properties_of_clickable["x"], "y": properties_of_clickable["y"]
            }
            clickable_contour = {key: int(value) for key, value in clickable_contour.items()}
            properties_of_clickable["backgroundColor"] = extract_contour_inner_color(
                screenshot=page_screenshot, contour=clickable_contour)
        else:
            properties_of_clickable["backgroundColor"] = "rgb(255,255,255)"
        return properties_of_clickable
    except pychrome.exceptions.CallMethodException as e:
        return dict.fromkeys([
            'html', 'node', 'type', 'text', 'value', 'fontsize', 'width', 'height', 'x', 'y',
            'node_id', 'is_visible', 'role'])


def click_node(tab: pychrome.Tab, node_id: int):
    """Fetches a JS object via node id and clicks on it."""
    js_function = """
        function clickNode(elem) {
            if (!elem) elem = this;
            elem.click();
        }"""

    try:
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id, silent=True).get(
            'result')
        return True
    except pychrome.exceptions.CallMethodException as e:
        return False


def extract_contour_inner_color(screenshot: numpy.ndarray, contour: numpy.ndarray, options: dict = None) -> str:
    """Loops through all the points that are within the contour and returns the most prevalent color in the form
    rgb(r, g, b) as a string. Or white rgb(255,255,255) if no point can be sampled."""
    x = contour['x']
    y = contour['y']
    w = contour['w']
    h = contour['h']
    sampled_points = list()
    for i in range(x + 1, x + w - 2, 5):
        for j in range(y + 1, y + h - 2, 5):
            if i >= screenshot.shape[1] or j >= screenshot.shape[0]:
                break
            else:
                sampled_points.append({'x': i, 'y': j})
    count = dict()
    for point in sampled_points:
        color = screenshot[point['y'], point['x']]
        color = 'rgb({0},{1},{2})'.format(color[0], color[1], color[2])
        count[color] = count.get(color, 0) + 1
    count = sorted(count.items(), key=lambda k: k[1], reverse=True)
    count = {k: v for k, v in count}
    internal_color = list(count.keys())
    if internal_color:
        return internal_color[0]
    else:
        return 'rgb(255,255,255)'


def get_by_text(clickable_to_find: dict, clickables: list) -> dict:
    """Loops through all clickables and returns the one that has the same text as the provided clickable. Necessary
    because sometimes the node ids change between page reloads."""
    for clickable in clickables:
        if clickable_to_find['text'] == clickable['text']:
            return clickable


def get_by_type(clickables: list, type_of_clickable: str) -> list:
    """Takes a list of clickables and returns the one that match the provided clickable type."""
    clickables_by_type = []
    for clickable in clickables:
        if clickable['type'] == type_of_clickable:
            clickables_by_type.append(clickable)
    return clickables_by_type


def get_by_property(clickables: list, property_dict: dict) -> list:
    """Takes a list of clickables and returns all that match the specified property. Returns none if the property is
    not present in the clickable."""
    result = list()
    property_name = list(property_dict)[0]
    property_value = property_dict[property_name]
    for clickable in clickables:
        # Continue if clickable does not have that property.
        if property_name not in clickable:
            continue
        if clickable[property_name] == property_value:
            result.append(clickable)
    return result


def get_clickables_with_same_ssim(clickables: list) -> list:
    """Loops through all clickables and returns a list of the ones with the same SSIM value."""
    same_ssim = list()
    for clickable_x in clickables:
        if 'SSIM' not in clickable_x:
            continue
        for clickable_y in clickables:
            if 'SSIM'not in clickable_y:
                continue
            if clickable_x['node_id'] != clickable_y['node_id'] and clickable_x['SSIM'] == clickable_y['SSIM']:
                if clickable_x not in same_ssim:
                    same_ssim.append(clickable_x)
                if clickable_y not in same_ssim:
                    same_ssim.append(clickable_y)
    return same_ssim


def remove_invisible_clickables(cookie_notice: dict) -> None:
    """Loop through all clickables in a cookie notice and remove the ones that according to the Javascript output
    are invisible."""
    cookie_notice['clickables'] = [clickable for clickable in cookie_notice['clickables'] if
                                   clickable['is_visible']]
