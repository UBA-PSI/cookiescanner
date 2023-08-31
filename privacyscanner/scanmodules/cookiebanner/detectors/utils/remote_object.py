import pychrome


def get_node_id_for_remote_object(tab: pychrome.Tab, remote_object_id: str) -> int:
    """Returns the node id for a given remote Javascript node id."""
    return tab.DOM.requestNode(objectId=remote_object_id).get('nodeId')


def get_array_of_node_ids_for_remote_object(tab: pychrome.Tab, remote_object_id: str) -> list:
    """Returns the node ids of all the property objects for a given object id."""
    array_attributes = get_properties_of_remote_object(tab, remote_object_id)
    remote_object_ids = [array_element.get('value').get('objectId') for array_element in array_attributes
                         if array_element.get('value') and array_element.get('enumerable')]
    node_ids = list()
    for remote_object_id in remote_object_ids:
        try:
            node_ids.append(get_node_id_for_remote_object(tab, remote_object_id))
        except pychrome.exceptions.CallMethodException as e:
            pass
    return node_ids


def get_object_for_remote_object(tab: pychrome.Tab, remote_object_id: str) -> dict:
    """Returns the properties of a remote object."""
    object_attributes = get_properties_of_remote_object(tab, remote_object_id)
    result = {
        attribute.get('name'): attribute.get('value').get('value')
        for attribute in object_attributes
        if is_remote_attribute_a_primitive(attribute)
    }
    # search for nested arrays
    result.update({
        attribute.get('name'): get_array_for_remote_object(tab, attribute.get('value').get('objectId'))
        for attribute in object_attributes
        if is_remote_attribute_an_array(attribute)
    })

    return result


def get_array_for_remote_object(tab: pychrome.Tab, remote_object_id: str) -> list:
    """Get property values of an object as a list."""
    array_attributes = get_properties_of_remote_object(tab, remote_object_id)
    return [
        array_element.get('value').get('value')
        for array_element in array_attributes
        if array_element.get('enumerable')
    ]


def is_remote_attribute_a_primitive(attribute: dict) -> bool:
    """Returns whether a remote attribute is a primitive."""
    return attribute.get('enumerable') \
           and attribute.get('value').get('type') != 'object' \
           or attribute.get('value').get('subtype', '') == 'null'


def is_remote_attribute_an_array(attribute: dict) -> bool:
    """Returns whether a remote attribute is an array."""
    return attribute.get('enumerable') \
           and attribute.get('value').get('type') == 'object' \
           and attribute.get('value').get('subtype', '') == 'array'


def get_properties_of_remote_object(tab: pychrome.Tab, remote_object_id: str) -> dict:
    """Returns the properties of a remote object."""
    return tab.Runtime.getProperties(objectId=remote_object_id, ownProperties=True).get('result')


def get_remote_object_id_by_node_id(tab: pychrome.Tab, node_id: int) -> str:
    """Returns the remote object id for a node id."""
    try:
        return tab.DOM.resolveNode(nodeId=node_id).get('object').get('objectId')
    except Exception:
        return None
