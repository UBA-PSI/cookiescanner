import pychrome

from privacyscanner.scanmodules.cookiebanner import get_remote_object_id_by_node_id
from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object import get_node_id_for_remote_object, \
    get_object_for_remote_object


def get_node_name(tab: pychrome.Tab, node_id: int) -> str:
    """Returns the tag description for a node id in a given tag. (e. g. html vor <html...)"""
    try:
        return tab.DOM.describeNode(nodeId=node_id).get('node').get('nodeName').lower()
    except pychrome.exceptions.CallMethodException as e:
        return None


def is_script_or_style_node(tab: pychrome.Tab, node_id: int) -> bool:
    """Returns whether the node referenced by the provided node id is a script or a style node."""
    node_name = get_node_name(tab, node_id)
    return node_name == 'script' or node_name == 'style'


def filter_visible_nodes(tab: pychrome.Tab, node_ids: list) -> list:
    """Takes a list of node ids and only returns the ones visibible."""
    return [node_id for node_id in node_ids if is_node_visible(tab, node_id).get('is_visible')]


def is_node_visible(tab: pychrome.Tab, node_id: int) -> dict[str, bool | None]:
    """Source: https://stackoverflow.com/a/41698614 adapted to also look at child nodes (especially important for fixed
    elements as they might not be "visible" themselves when they have no width or height)"""
    js_function = """
        function isVisible(elem) {
            function parseValue(value) {
                var parsedValue = parseInt(value);
                if (isNaN(parsedValue)) {
                    return 0;
                } else {
                    return parsedValue;
                }
            }

            if (!elem) elem = this;
            if (!(elem instanceof Element)) return false;
            let visible = true;
            const style = getComputedStyle(elem);

            // for these rules the childs cannot be visible, directly return
            if (style.display === 'none') return false;
            if (style.opacity < 0.1) return false;
            if (style.visibility !== 'visible') return false;

            // for these rules a child element might still be visible,
            // we need to also look at the childs, no direct return
            if (elem.offsetWidth + elem.offsetHeight + elem.getBoundingClientRect().height +
                elem.getBoundingClientRect().width === 0) {
                visible = false;
            }
            if (elem.offsetWidth < 10 || elem.offsetHeight < 10) {
                visible = false;
            }
            const elemCenter = {
                x: elem.getBoundingClientRect().left + elem.offsetWidth / 2,
                y: elem.getBoundingClientRect().top + elem.offsetHeight / 2
            };
            if (elemCenter.x < 0) visible = false;
            if (elemCenter.x > (document.documentElement.clientWidth || window.innerWidth)) visible = false;
            if (elemCenter.y < 0) visible = false;
            if (elemCenter.y > (document.documentElement.clientHeight || window.innerHeight)) visible = false;

            if (visible) {
                let pointContainer = document.elementFromPoint(elemCenter.x, elemCenter.y);
                do {
                    if (pointContainer === elem) return elem;
                    if (!pointContainer) break;
                } while (pointContainer = pointContainer.parentNode);

                pointContainer = document.elementFromPoint(elemCenter.x, elemCenter.y - (parseValue(style.fontSize)/2));
                do {
                    if (pointContainer === elem) return elem;
                    if (!pointContainer) break;
                } while (pointContainer = pointContainer.parentNode);
            }

            // check the child nodes
            if (!visible) {
                let childrenCount = elem.childNodes.length;
                for (var i = 0; i < childrenCount; i++) {
                    let isChildVisible = isVisible(elem.childNodes[i]);
                    if (isChildVisible) {
                        return isChildVisible;
                    }
                }
            }

            return false;
        }"""

    # the function `isVisible` is calling itself recursively,
    # therefore it needs to be defined beforehand
    tab.Runtime.evaluate(expression=js_function)

    try:
        # call the function `isVisible` on the node
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                            silent=True).get('result')

        # if a boolean is returned, the object is not visible
        if result.get('type') == 'boolean':
            return {
                'is_visible': result.get('value'),
                'visible_node': None,
            }
        # otherwise, the object or one of its children is visible
        else:
            return {
                'is_visible': True,
                'visible_node': get_node_id_for_remote_object(tab, result.get('objectId')),
            }
    except pychrome.exceptions.CallMethodException as e:
        # self.result.add_warning({
        #     'message': str(e),
        #    'exception': type(e).__name__,
        #    'traceback': traceback.format_exc().splitlines(),
        #    'method': 'is_node_visible',
        # })
        return {
            'is_visible': False,
            'visible_node': None,
        }


def get_text_of_node(tab: pychrome.Tab, node_id: int) -> str or None:
    """Returns the text of a node for a given node id."""
    js_function = """
        function getText(elem) {
            if (!elem) elem = this
            return {'text': elem.innerText}
        }"""

    try:
        remote_object_id = get_remote_object_id_by_node_id(tab, node_id)
        result = tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                            silent=True).get('result')
        result = get_object_for_remote_object(tab, result.get('objectId'))
        return result['text']
    except pychrome.exceptions.CallMethodException as e:
        # self.result.add_warning({
        #    'message': str(e),
        #    'exception': type(e).__name__,
        #    'traceback': traceback.format_exc().splitlines(),
        #    'method': ' _check_if_node_exists',
        # })
        return False
