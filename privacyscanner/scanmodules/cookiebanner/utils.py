
def get_remote_object_id_by_node_id(tab: any, node_id: int):
    try:
        return tab.DOM.resolveNode(nodeId=node_id).get('object').get('objectId')
    except Exception:
        return None


def get_properties_of_remote_object(tab: any, remote_object_id: any):
    return tab.Runtime.getProperties(objectId=remote_object_id, ownProperties=True).get('result')


def get_object_for_remote_object(tab: any, remote_object_id: any):
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


def get_array_for_remote_object(tab, remote_object_id):
    array_attributes = get_properties_of_remote_object(tab, remote_object_id)
    return [
        array_element.get('value').get('value')
        for array_element in array_attributes
        if array_element.get('enumerable')
    ]


def is_remote_attribute_a_primitive(attribute):
    return attribute.get('enumerable') \
           and attribute.get('value').get('type') != 'object' \
           or attribute.get('value').get('subtype', '') == 'null'


def is_remote_attribute_an_object(attribute):
    return attribute.get('enumerable') \
           and attribute.get('value').get('type') == 'object' \
           and attribute.get('value').get('subtype', '') != 'array' \
           and attribute.get('value').get('subtype', '') != 'null'


def is_remote_attribute_an_array(attribute):
    return attribute.get('enumerable') \
           and attribute.get('value').get('type') == 'object' \
           and attribute.get('value').get('subtype', '') == 'array'
