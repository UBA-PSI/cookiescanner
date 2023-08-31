import logging
import pychrome
import requests

from privacyscanner.scanmodules.cookiebanner import Extractor
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import readb64, take_screenshot, take_screenshots
from privacyscanner.scanmodules.cookiebanner.detectors.utils.notice import get_properties_of_cookie_notice
from privacyscanner.scanmodules.cookiebanner.detectors.utils.remote_object \
    import get_array_of_node_ids_for_remote_object, get_remote_object_id_by_node_id
from privacyscanner.scanmodules.cookiebanner.page import Page

host = "127.0.0.1"
port = "9999"


class BertDetector(Extractor):

    def __init__(self, page: Page, result: dict, logger: logging.Logger, options: dict):
        super().__init__(page, result, logger, options)

    def extract_information(self) -> None:
        page_screenshot = take_screenshot(self.page.tab, "website")
        page_screenshot = readb64(page_screenshot['contents'])
        # Gather the IDs of candidate elements
        candidate_element_ids = self._gather_candidate_elements()
        # Extract the text of candidate elements; discard elements without text
        candidate_elements = [
            {'node_id': candidate_element_id, 'text': self._get_node_text(node_id=candidate_element_id)}
            for candidate_element_id in candidate_element_ids
        ]
        for candidate_element in candidate_elements:
            try:
                result = requests.post(url=f"http://{host}:{port}",
                                       json={"lang": "en", "text": candidate_element}, timeout=10).json()
            except requests.exceptions.ConnectionError:
                self.logger.info("Container not reachable. Aborting detection...")
                return
            if result["is_consent_banner"] == 1:
                self.result["bert"] = \
                    [get_properties_of_cookie_notice(tab=self.page.tab,
                                                     node_id=candidate_element["node_id"],
                                                     options=self.options,
                                                     page_screenshot=page_screenshot)]
                self.result['cookie_notice_count']['bert'] = 1
                try:
                    take_screenshots(tab=self.page.tab, result=self.result,
                                     cookie_notice_ids=[candidate_element["node_id"]],
                                     detection_method="bert",
                                     take_screenshots=self.options["take_screenshots"],
                                     screenshots_banner_only=self.options["take_screenshots_banner_only"])
                except:
                    pass
                return

    def _gather_candidate_elements(self) -> list[int]:
        """Returns a list of possible banner candidate elements according to the method of Khandelwal et al.
        This means elements with a positive z-score and the first three and the last three elements of the document
        body."""
        js_function = """
            function isVisible(elem) {
                if (!elem) elem = this
                if (!(elem instanceof Element)) throw Error('DomUtil: elem is not an element.');
                const style = getComputedStyle(elem);
                if (style.display === 'none') return false;
                if (style.visibility !== 'visible') return false;
                if (style.opacity < 0.1) return false;
                if (elem.offsetWidth + elem.offsetHeight + elem.getBoundingClientRect().height +
                    elem.getBoundingClientRect().width === 0) {
                    return false;
                }
                const elemCenter   = {
                    x: elem.getBoundingClientRect().left + elem.offsetWidth / 2,
                    y: elem.getBoundingClientRect().top + elem.offsetHeight / 2
                };
                if (elemCenter.x < 0) return false;
                if (elemCenter.x > (document.documentElement.clientWidth || window.innerWidth)) return false;
                if (elemCenter.y < 0) return false;
                if (elemCenter.y > (document.documentElement.clientHeight || window.innerHeight)) return false;
                if (isNaN(elemCenter.x) || isNaN(elemCenter.y)) return false;
                let pointContainer = document.elementFromPoint(elemCenter.x, elemCenter.y);
                do {
                    if (pointContainer === elem) return true;
                } while (pointContainer = pointContainer.parentNode);
                return false;
            } 
            
            function gatherZscoreCandidates(){
                let candidates = [];
                //get all Elements with positive Z score
                let bodyChildNodes = document.body.querySelectorAll('*');
                bodyChildNodes.forEach((node) =>{
                    if (node.nodeType !== Node.ELEMENT_NODE)
                        return;
                    let computedStyle = getComputedStyle(node);
                    if (isVisible(node) && computedStyle.zIndex > 0){
                        candidates.push(node);
                    }
                })
                //get the first three child elements
                let nodeIndex = 0;
                for(i = 0; i < 3; i++){
                    if (nodeIndex == bodyChildNodes.length - 1){
                        break;
                    }
                    let currentNode = bodyChildNodes[nodeIndex];
                    if (currentNode.nodeType !== Node.ELEMENT_NODE || 
                        !isVisible(currentNode) || 
                        candidates.includes(currentNode)){
                        i--;
                        nodeIndex++;
                        continue;
                    }
                    else{
                        candidates.push(currentNode);
                        nodeIndex++;
                    }
                }
                //get the last three child elements
                nodeIndex = bodyChildNodes.length - 1;
                for(i = 0; i < 3; i++){
                    if(nodeIndex < 0){
                        break;
                    }
                    let currentNode = bodyChildNodes[nodeIndex];
                    if (currentNode.nodeType !== Node.ELEMENT_NODE || 
                        !isVisible(currentNode) || 
                        candidates.includes(currentNode)){
                        i--;
                        nodeIndex--;
                        continue;
                    }
                    else{
                        candidates.push(currentNode);
                        nodeIndex--;
                    }
                    
                }
                return candidates;
            }
            
            gatherZscoreCandidates();
            """
        result = self.page.tab.Runtime.evaluate(expression=js_function).get('result')
        result = get_array_of_node_ids_for_remote_object(tab=self.page.tab, remote_object_id=result.get('objectId'))
        return result

    def _get_node_text(self, node_id: int) -> str or None:
        """Returns the text of a node or 'None' if the node has no text, or it is impossible to retrieve it."""
        js_function = """
        function getText(elem){
            if (!elem){
                elem = this;
            }
            return elem.innerText;
        }
        """
        try:
            remote_object_id = get_remote_object_id_by_node_id(tab=self.page.tab, node_id=node_id)
            result = self.page.tab.Runtime.callFunctionOn(functionDeclaration=js_function, objectId=remote_object_id,
                                                          silent=True).get('result').get('value')
            return result
        except pychrome.exceptions.CallMethodException:
            return None

    @staticmethod
    def update_dependencies(options: dict) -> None:
        pass
