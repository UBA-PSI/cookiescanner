import base64
import copy
import json
import pychrome
import random
import threading

from datetime import datetime
from tld.utils import get_fld
from urllib.parse import urlparse

from privacyscanner.scanmodules.chromedevtools.chromescan import ON_NEW_DOCUMENT_JAVASCRIPT, \
    EXTRACT_ARGUMENTS_JAVASCRIPT
from privacyscanner.scanmodules.cookiebanner.page import Page
from privacyscanner.scanmodules.cookiebanner.user_agent_switching import get_user_agent_rotator
from privacyscanner.scanmodules.cookiebanner.extractors.PrivacyPolicyExtractor import PrivacyPolicyExtractor
from privacyscanner.scanmodules.cookiebanner.detectors.utils.notice import detect_language
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import readb64
from privacyscanner.scanmodules.cookiebanner.detectors.utils.node import is_node_visible
from privacyscanner.scanmodules.cookiebanner.detectors.utils.ssim import calculate_ssim_score
from privacyscanner.scanmodules.cookiebanner.detectors.utils.general import sanitize_file_name, take_screenshot
from privacyscanner.scanmodules.cookiebanner.detectors.utils.clickable import click_node, get_by_text, \
    get_clickables_with_same_ssim, get_by_property
from privacyscanner.scanmodules.cookiebanner.detectors import NaiveDetector, FilterListDetector, \
    SimplePerceptiveDetector, BertDetector

# See comments in ON_NEW_DOCUMENT_JAVASCRIPT


ON_NEW_DOCUMENT_JAVASCRIPT_LINENO = 7

DETECTORS = {
    'bert': BertDetector,
    'naive': NaiveDetector,
    'perceptive': SimplePerceptiveDetector,
    'easylist-cookie': FilterListDetector,
    'i-dont-care-about-cookies': FilterListDetector
}


class ChromeBrowserStartupError(Exception):
    pass


class NotReachableError(Exception):
    pass


class DNSNotResolvedError(Exception):
    pass


class PageScanner:
    def __init__(self, extractor_classes, detector_classes):
        self._extractor_classes = extractor_classes
        self._detector_classes = detector_classes
        self._page_loaded = threading.Event()
        self._reset()
        self._tab = None
        self._page = None

    def scan(self, browser, result, logger, options):

        self._setup_tab(browser=browser, options=options)

        self._page.scan_start = datetime.utcnow()
        try:
            self._tab.Page.navigate(url=result['site_url'],
                                    _timeout=options.get('timeout', options['timeout']))
            self._tab.wait(options['page_load_delay'])
            self._load_modules(result, logger, options)

        except pychrome.TimeoutException:
            self._tab.stop()
            browser.close_tab(self._tab)
            self._reset()
            raise

        page_screenshot = take_screenshot(self._tab, "website")
        original_screenshot = page_screenshot
        page_screenshot = readb64(page_screenshot['contents'])
        result['cookies'] = self._get_all_cookies()
        result['cookie_notice_count'] = dict()
        logger.info('Currently scanning website: {}'.format(result['site_url']))
        result['TRACKING_BEFORE_ANY_ACTION'] = False
        result['BUTTONS_HAVE_DIFFERENT_COLOR'] = False
        result['BANNER_PRESENT_WITHOUT_TRACKING'] = False
        result['SAME_SSIM'] = False

        result['language'] = detect_language(self._tab)
        result['disconnect_num'] = 0
        result['cookie_syncs_num'] = 0
        result['total_tracker_num'] = 0
        result["screenshots"] = dict()

        # Extract Responses
        has_responses = bool(self._page.response_log)
        self._tab.DOM.getDocument(depth=-1)
        if has_responses:
            self._extract_information()
            if result['disconnect_num'] or result['cookie_syncs_num']:
                result['total_tracker_num'] = result['disconnect_num'] + result['cookie_syncs_num']
                logger.info('Trackers are loaded without any user action.')
                result['TRACKING_BEFORE_ANY_ACTION'] = True
            else:
                result['total_tracker_num'] = 0
                result['TRACKING_BEFORE_ANY_ACTION'] = False
                logger.info('Trackers are not loaded with the initial page load.')
            result["screenshots"]["initial_page_load"] = [{
                "filename": f"{result['site_url'][8:]}.png",
                "contents": base64.b64encode(original_screenshot["contents"]).decode('utf-8')}]

            result["request_log"] = self._page.request_log
            result["document_request_log"] = self._page.document_request_log
            result["failed_request_log"] = self._page.failed_request_log
            result["response_log"] = self._page.response_log
            result["security_state_log"] = self._page.security_state_log
            result["response_lookup"] = self._page._response_lookup
        else:
            self._tab.stop()
            browser.close_tab(self._tab)
            if self._page.failed_request_log:
                failed_request = self._page.failed_request_log[0]
                if failed_request.get('errorText') == 'net::ERR_NAME_NOT_RESOLVED':
                    self._reset()
                    raise DNSNotResolvedError('DNS could not be resolved.')
            self._reset()
            raise NotReachableError('Not reachable for unknown reasons.')
        preferred_detector = self._get_by_priority(result, logger, options)
        result['preferred_detector'] = preferred_detector
        logger.info('The preferred detector is: {0}'.format(preferred_detector))

        # If no banner has been detected, preferred detector is 'None' -> Abort
        if not preferred_detector or len(result[preferred_detector]) == 0:
            logger.info('There has been no cookie banner detected.')
            self._tab.stop()
            browser.close_tab(self._tab)
            self._reset()
            return

        self._page._reset_page(self._tab)

        if options['extract_privacy_policy']:
            # EXTRACT PRIVACY POLICY
            policy_extractor = PrivacyPolicyExtractor(self._page, self._tab, result, logger, options)
            policy_extractor.extract_information()
            result["privacy_policy_request_log"] = self._page.request_log
            result["privacy_policy_document_request_log"] = self._page.document_request_log
            result["privacy_policy_failed_request_log"] = self._page.failed_request_log
            result["privacy_policy_response_log"] = self._page.response_log
            result["privacy_policy_security_state_log"] = self._page.security_state_log
            result["privacy_policy_response_lookup"] = self._page._response_lookup

            self._page._reset_page(self._tab)

        if options['click_clickables']:
            reloaded_options = copy.deepcopy(options)
            reloaded_options['take_screenshots'] = False
            reloaded_options['take_screenshots_banner_only'] = False

            # Put clickables in to seperate variable
            cookie_notice = self.fetch_single_element(element=result[preferred_detector])
            clickables = cookie_notice['clickables']

            current_result_dict = dict(result._result_dict)
            result._result_dict = dict()
            result._updated_keys = set()

            result.setdefault('initial_result', current_result_dict)
            result['site_url'] = result['initial_result']['site_url']
            result['language'] = result['initial_result']['language']
            self._clear_browser()

            # Get Clickables
            buttons = get_by_property(clickables=clickables, property_dict={"type": "button"})
            checkboxes = get_by_property(clickables=clickables, property_dict={"type": "checkbox"})
            links = get_by_property(clickables=clickables, property_dict={"type": "link"})

            for button in buttons:

                # Reload the tab and re-run detection
                self._reload_tab(browser, result, options)
                #  navigate and wait
                self._tab.Page.navigate(url=result['site_url'],
                                        _timeout=options.get('timeout', options['timeout']))
                self._tab.wait(options['page_load_delay'])
                self._reset_modules()

                clickable_result = dict()
                result.setdefault(str(button['node_id']), clickable_result)

                clickable_result['site_url'] = result['site_url']
                clickable_result['language'] = result['language']
                clickable_result['cookie_notice_count'] = dict()
                clickable_result['screenshots'] = None

                self._load_detector_modules(clickable_result, logger, reloaded_options, preferred_detector)
                # This call is necessary, or else the DOM elements are "visible", but cannot be accessed
                self._tab.DOM.getDocument(depth=-1)
                self._extract_detector_information()
                # In some sites, the banner disappears after interacting with it -> Return and log the occurrence
                if preferred_detector not in clickable_result:
                    result['chrome_error'] = 'banner_gone'
                    return
                reloaded_banner = self.fetch_single_element(element=clickable_result[preferred_detector])
                reloaded_clickable = get_by_text(button, reloaded_banner['clickables'])
                self._reset_modules()

                logger.info("The button '{0}' has been clicked".format(button['text']))
                self.click_and_wait(clickable=reloaded_clickable, time_in_seconds=options['page_load_delay'])
                clickable_result['cookies'] = self._get_all_cookies()
                self._load_extractor_modules(clickable_result, logger, options)
                self._extract_extractor_information()
                clickable_result['total_tracker_num'] = clickable_result['disconnect_num'] + clickable_result[
                    'cookie_syncs_num']
                button['total_tracker_num'] = clickable_result['total_tracker_num']
                result['initial_result']['total_tracker_num'] += button['total_tracker_num']

                # Take screenshots and compute SSIM
                file_name = sanitize_file_name(text=button["text"])
                clickable_clicked = take_screenshot(self._tab, name=file_name)
                result.add_file(filename=file_name + '.png', contents=clickable_clicked['contents'])
                if "button_pressed" not in result["initial_result"]["screenshots"]:
                    result["initial_result"]["screenshots"]["button_pressed"] = list()
                result["initial_result"]["screenshots"]["button_pressed"] \
                    .append({"filename": file_name + '.png',
                             "contents": base64.b64encode(clickable_clicked['contents']).decode('utf-8')})
                clickable_clicked = readb64(clickable_clicked['contents'])
                button['SSIM'] = calculate_ssim_score(image1=page_screenshot, image2=clickable_clicked)

                clickable_result["request_log"] = self._page.request_log
                clickable_result["document_request_log"] = self._page.document_request_log
                clickable_result["failed_request_log"] = self._page.failed_request_log
                clickable_result["response_log"] = self._page.response_log
                clickable_result["security_state_log"] = self._page.security_state_log
                clickable_result["response_lookup"] = self._page._response_lookup

                clickable_result["banner_visible_after_click"] = \
                    is_node_visible(tab=self._tab, node_id=reloaded_banner["node_id"])["is_visible"]

                self._clear_browser()

            self._close_tab(browser, options)
            self._reset()

        else:
            self._close_tab(browser, options)
            self._reset()

        if 'initial_result' in result:
            if result['initial_result']['total_tracker_num'] == 0 and 'cookie_notice_count' in result['initial_result'] \
                    and len(result['initial_result']['cookie_notice_count']) > 0:
                result['initial_result']['BANNER_PRESENT_WITHOUT_TRACKING'] = True
            if preferred_detector in result['initial_result']:
                banner = self.fetch_single_element(element=result['initial_result'][preferred_detector])
                clickables = banner['clickables']
                buttons = get_by_property(clickables=clickables, property_dict={"type": "button"})
                if buttons:
                    # Different Background Color
                    first_button_bg_color = buttons[0]["backgroundColor"]
                    for button in buttons:
                        if button["backgroundColor"] != first_button_bg_color:
                            result["initial_result"]["BUTTONS_HAVE_DIFFERENT_COLOR"] = True
                    # Same SSIM Value
                    buttons_with_same_ssim = get_clickables_with_same_ssim(clickables=buttons)
                    if buttons_with_same_ssim:
                        result['initial_result']['SAME_SSIM'] = True
                        result['initial_result']['SAME_SSIM_BUTTONS'] = buttons_with_same_ssim

        else:
            if result['total_tracker_num'] == 0 and 'cookie_notice_count' in result \
                    and len(result['cookie_notice_count']) > 0:
                result['BANNER_PRESENT_WITHOUT_TRACKING'] = True
                if preferred_detector in result:
                    banner = self.fetch_single_element(element=result[preferred_detector])
                    clickables = banner['clickables']
                    buttons = get_by_property(clickables=clickables, property_dict={"type": "button"})
                    if buttons:
                        # Different Background Color
                        first_button_bg_color = buttons[0]["backgroundColor"]
                        for button in buttons:
                            if button["backgroundColor"] != first_button_bg_color:
                                result["BUTTONS_HAVE_DIFFERENT_COLOR"] = True
        logger.info("Page scan finished.")
        return

    def _cb_request_will_be_sent(self, request, requestId, **kwargs):
        # To avoid reparsing the URL in many places, we parse them all here
        request['parsed_url'] = urlparse(request['url'])
        request['requestId'] = requestId
        request['document_url'] = kwargs.get('documentURL')
        request['extra'] = kwargs
        if request.get('hasPostData', False):
            if 'postData' in request:
                request['post_data'] = request['postData']
            else:
                post_data = self._tab.Network.getRequestPostData(requestId=requestId)
                # To avoid a too high memory usage by single requests
                # we just store the first 64 KiB of the post data
                request['post_data'] = post_data['postData'][:65536]
        else:
            request['post_data'] = None
        self._page.add_request(request)

        # Redirect requests don't have a received response but issue another
        # "request will be sent" event with a redirectResponse key.
        redirect_response = kwargs.get('redirectResponse')
        if redirect_response is not None:
            self._cb_response_received(redirect_response, requestId)

    def _cb_response_received(self, response, requestId, **kwargs):
        response['requestId'] = requestId
        headers_lower = {}
        for header_name, value in response['headers'].items():
            headers_lower[header_name.lower()] = value
        response['headers_lower'] = headers_lower
        response['extra'] = kwargs
        self._page.add_response(response)

    def _cb_script_parsed(self, **script):
        # The first script loaded is our script we set via the method
        # Page.addScriptToEvaluateOnNewDocument. We want to to attach
        # to the log function, which will be used to analyse the page.
        if not self._debugger_attached.is_set():
            self._log_breakpoint = self._tab.Debugger.setBreakpoint(location={
                'scriptId': script['scriptId'],
                'lineNumber': ON_NEW_DOCUMENT_JAVASCRIPT_LINENO
            })['breakpointId']
            if self._debugger_paused.is_set():
                self._tab.Debugger.resume()
            self._debugger_attached.set()

    def _cb_script_failed_to_parse(self, **kwargs):
        pass

    def _cb_paused(self, **info):
        self._debugger_paused.set()
        if self._log_breakpoint in info['hitBreakpoints']:
            call_frames = []
            for call_frame in info['callFrames']:
                javascript_result = self._tab.Debugger.evaluateOnCallFrame(
                    callFrameId=call_frame['callFrameId'],
                    expression=EXTRACT_ARGUMENTS_JAVASCRIPT)['result']
                if 'value' in javascript_result:
                    args = json.loads(javascript_result['value'])
                else:
                    # TODO: We should look for the error here and handle those
                    #       cases to reliably extract the arguments.
                    args = ['error', None]
                call_frames.append({
                    'url': call_frame['url'],
                    'functionName': call_frame['functionName'],
                    'location': {
                        'lineNumber': call_frame['location']['lineNumber'],
                        'columnNumber': call_frame['location']['columnNumber']
                    },
                    'args': args
                })
            # self._receive_log(*call_frames[0]['args'], call_frames[1:])
        if self._debugger_attached.is_set():
            self._tab.Debugger.resume()

    def _cb_resumed(self, **info):
        self._debugger_paused.clear()

    def _cb_load_event_fired(self, timestamp, **kwargs):
        self._page_loaded.set()

    def _cb_frame_scheduled_navigation(self, frameId, delay, reason, url, **kwargs):
        # We assume that our scan will finish within 60 seconds including
        # a security margin. So we just ignore scheduled navigations if
        # they are too far in future.
        if delay <= 60:
            self._document_will_change.set()

    def _cb_frame_cleared_scheduled_navigation(self, frameId):
        self._document_will_change.clear()

    def _cb_security_state_changed(self, **state):
        self._page.security_state_log.append(state)

    def _cb_loading_failed(self, **failed_request):
        self._page.add_failed_request(failed_request)

    def _cb_event_attribute_modified(self, nodeId, name, value, **kwargs):
        pass

    def _cb_event_attribute_removed(self, nodeId, name, **kwargs):
        # print('Event attribute removed fired.')
        # print(nodeId, name)
        pass

    def _cb_event_character_data_modified(self, nodeId, characterData, **kwargs):
        pass

    def _cb_child_node_count_updated(self, nodeId, childNodeCount, **kwargs):
        pass

    def _cb_child_node_inserted(self, parentNodeId, previousNodeId, node, **kwargs):
        pass

    def _cb_event_child_node_removed(self, parentNodeId, nodeId, **kwargs):
        pass

    def _cb_event_document_updated(self, **kwargs):
        pass

    def _cb_event_set_child_nodes(self, parentId, nodes, **kwargs):
        pass

    def _register_network_callbacks(self):
        self._tab.Network.requestWillBeSent = self._cb_request_will_be_sent
        self._tab.Network.responseReceived = self._cb_response_received
        self._tab.Network.loadingFailed = self._cb_loading_failed

    def _unregister_network_callbacks(self):
        self._tab.Network.requestWillBeSent = None
        self._tab.Network.responseReceived = None
        self._tab.Network.loadingFailed = None

    def _register_security_callbacks(self):
        self._tab.Security.securityStateChanged = self._cb_security_state_changed

    def _unregister_security_callbacks(self):
        self._tab.Security.securityStateChanged = None

    def _register_dom_callbacks(self):
        self._tab.DOM.attributeModified = self._cb_event_attribute_modified
        self._tab.DOM.attributeRemoved = self._cb_event_attribute_removed
        self._tab.DOM.characterDataModified = self._cb_event_character_data_modified
        self._tab.DOM.childNodeCountUpdated = self._cb_child_node_count_updated
        self._tab.DOM.childNodeInserted = self._cb_child_node_inserted
        self._tab.DOM.childNodeRemoved = self._cb_event_child_node_removed
        self._tab.DOM.documentUpdated = self._cb_event_document_updated
        self._tab.setChildNodes = self._cb_event_set_child_nodes

    def _unregister_dom_callbacks(self):
        self._tab.DOM.attributeModified = None
        self._tab.DOM.attributeRemoved = None
        self._tab.DOM.characterDataModified = None
        self._tab.DOM.childNodeCountUpdated = None
        self._tab.DOM.childNodeInserted = None
        self._tab.DOM.childNodeRemoved = None
        self._tab.DOM.documentUpdated = None
        self._tab.setChildNodes = None

    def _is_headless(self):
        try:
            js_function = """
            function isHeadless(){
                if(!window.chrome){
                    return true
                }
                else{
                    return false
                }
            }
            isHeadless()
            """
            # If window.chrome returns false, the browser is headless. Source: https://antoinevastel.com/bot%20detection/2018/01/17/detect-chrome-headless-v2.html#Chrome%20(New)
            # TODO Why not just '!window.chrome'? --> _cb_script_parse 'lineNumber': ON_NEW_DOCUMENT_JAVASCRIPT_LINENO
            result = self._tab.Runtime.evaluate(expression=js_function).get('result')
            result = result.get('value')
            return result
            # The fact that Browser.getWindowsBounds is not available
            # in headless mode is exploited here. Unfortunately, it
            # also shows a warning, which we suppress here.
            # with warnings.catch_warnings():
            #    warnings.simplefilter("ignore")
            #    self._tab.Browser.getWindowBounds(windowId=1)
            #    print(self._tab.Browser.getWindowBounds(windowId=1))
        except pychrome.exceptions.CallMethodException:
            return True
        # return False

    def _page_interaction(self):
        layout = self._tab.Page.getLayoutMetrics()
        height = layout['contentSize']['height']
        viewport_height = layout['visualViewport']['clientHeight']
        viewport_width = layout['visualViewport']['clientWidth']
        x = random.randint(0, viewport_width - 1)
        y = random.randint(0, viewport_height - 1)
        # Avoid scrolling too far, since some sites load the start page
        # when scrolling to the bottom (e.g. sueddeutsche.de)
        max_scrolldown = random.randint(int(height / 2.5), int(height / 1.5))
        last_page_y = 0
        while True:
            distance = random.randint(100, 300)
            self._tab.Input.dispatchMouseEvent(
                type='mouseWheel', x=x, y=y, deltaX=0, deltaY=distance)
            layout = self._tab.Page.getLayoutMetrics()
            page_y = layout['visualViewport']['pageY']
            # We scroll down until we have reached max_scrolldown, which was
            # obtained in the beginning. This prevents endless scrolling for
            # sites that dynamically load content (and therefore change their
            # height). In addition we check if the page indeed scrolled; this
            # prevents endless scrolling in case the content's height has
            # decreased.
            if page_y + viewport_height >= max_scrolldown or page_y <= last_page_y:
                break
            last_page_y = page_y
            self._tab.wait(random.uniform(0.050, 0.150))

    def _extract_information(self):
        for extractor in self._extractors:
            extractor.extract_information()
        for detector in self._detectors:
            detector.extract_information()

    def _extract_extractor_information(self):
        for extractor in self._extractors:
            extractor.extract_information()

    def _extract_detector_information(self):
        for detector in self._detectors:
            detector.extract_information()

    def _receive_log(self, log_type, message, call_stack):
        for extractor in self._extractors:
            extractor.receive_log(log_type, message, call_stack)

    def _register_javascript(self):
        for extractor in self._extractors:
            extra_javascript = extractor.register_javascript()
            if extra_javascript:
                self._extra_scripts.append(extra_javascript)

    def _reset(self):
        self._page_loaded.clear()
        self._document_will_change = threading.Event()
        self._debugger_attached = threading.Event()
        self._debugger_paused = threading.Event()
        self._log_breakpoint = None
        self._page = None
        self._extractors = []
        self._detectors = []
        self._extra_scripts = []
        self._CLICKED = False
        self._SETTINGS_CANDIDATES = list()

    def _setup_tab(self, browser, options):
        self._tab = browser.new_tab()
        self._tab.start()

        self._page = Page(self._tab)

        javascript_enabled = not options['disable_javascript']

        if javascript_enabled:
            self._register_javascript()

        if not javascript_enabled:
            self._tab.Emulation.setScriptExecutionDisabled(value=True)

        if self._is_headless():
            self._tab.Emulation.setDeviceMetricsOverride(
                width=options['resolution']['width'], height=options['resolution']['height'],
                screenWidth=options['resolution']['width'], screenHeight=options['resolution']['height'],
                deviceScaleFactor=0, mobile=False)

        if options['random_user_agent']:
            user_agent_rotator = get_user_agent_rotator()
            random_user_agent = user_agent_rotator.get_random_user_agent()
            self._tab.Network.setUserAgentOverride(userAgent=random_user_agent)
        else:
            useragent = self._tab.Browser.getVersion()['userAgent'] \
                .replace(
                'Headless',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36')
            self._tab.Network.setUserAgentOverride(userAgent=useragent)
        self._register_network_callbacks()
        self._register_dom_callbacks()
        self._tab.Network.enable()

        self._register_security_callbacks()
        self._tab.Security.enable()
        self._tab.Security.setIgnoreCertificateErrors(ignore=True)

        self._tab.Page.loadEventFired = self._cb_load_event_fired
        self._tab.Page.frameScheduledNavigation = self._cb_frame_scheduled_navigation
        self._tab.Page.frameClearedScheduledNavigation = self._cb_frame_cleared_scheduled_navigation
        extra_scripts = '\n'.join('(function() { %s })();' % script
                                  for script in self._extra_scripts)
        source = ON_NEW_DOCUMENT_JAVASCRIPT.replace('__extra_scripts__', extra_scripts)
        self._tab.Page.addScriptToEvaluateOnNewDocument(source=source)
        self._tab.Page.enable()

        if javascript_enabled:
            self._tab.Debugger.scriptParsed = self._cb_script_parsed
            self._tab.Debugger.scriptFailedToParse = self._cb_script_failed_to_parse
            self._tab.Debugger.paused = self._cb_paused
            self._tab.Debugger.resumed = self._cb_resumed
            self._tab.Debugger.enable()
            # Pause the JavaScript before we navigate to the page. This
            # gives us some time to setup the debugger before any JavaScript
            # runs.
            self._tab.Debugger.pause()

        javascript_enabled = not options['disable_javascript']

        if javascript_enabled:
            self._register_javascript()

        if not javascript_enabled:
            self._tab.Emulation.setScriptExecutionDisabled(value=True)

        if self._is_headless():
            self._tab.Emulation.setDeviceMetricsOverride(
                width=options['resolution']['width'], height=options['resolution']['height'],
                screenWidth=options['resolution']['width'], screenHeight=options['resolution']['height'],
                deviceScaleFactor=0, mobile=False)

        useragent = self._tab.Browser.getVersion()['userAgent'].replace('Headless', '')
        self._tab.Network.setUserAgentOverride(userAgent=useragent)
        self._register_network_callbacks()
        self._tab.Network.enable()

        self._register_security_callbacks()
        self._tab.Security.enable()
        self._tab.Security.setIgnoreCertificateErrors(ignore=True)

        self._tab.Page.loadEventFired = self._cb_load_event_fired
        self._tab.Page.frameScheduledNavigation = self._cb_frame_scheduled_navigation
        self._tab.Page.frameClearedScheduledNavigation = self._cb_frame_cleared_scheduled_navigation
        extra_scripts = '\n'.join('(function() { %s })();' % script
                                  for script in self._extra_scripts)
        source = ON_NEW_DOCUMENT_JAVASCRIPT.replace('__extra_scripts__', extra_scripts)
        self._tab.Page.addScriptToEvaluateOnNewDocument(source=source)
        self._tab.Page.enable()

        if javascript_enabled:
            self._tab.Debugger.scriptParsed = self._cb_script_parsed
            self._tab.Debugger.scriptFailedToParse = self._cb_script_failed_to_parse
            self._tab.Debugger.paused = self._cb_paused
            self._tab.Debugger.resumed = self._cb_resumed
            self._tab.Debugger.enable()
            # Pause the JavaScript before we navigate to the page. This
            # gives us some time to setup the debugger before any JavaScript
            # runs.
            self._tab.Debugger.pause()

    def _close_tab(self, browser, options):
        javascript_enabled = not options['disable_javascript']
        self._tab.Page.disable()
        if javascript_enabled:
            self._tab.Debugger.disable()
        self._unregister_network_callbacks()
        self._unregister_dom_callbacks()
        self._unregister_security_callbacks()
        self._tab.Network.disable()
        self._tab.Security.disable()
        self._tab.stop()
        browser.close_tab(self._tab)

    def _reload_tab(self, browser, result, options):
        #  CLOSE TAB
        self._close_tab(browser, options)
        #  SETUP TAB
        self._setup_tab(browser, options)

    def _load_modules(self, result, logger, options):
        for extractor_class in self._extractor_classes:
            self._extractors.append(extractor_class(self._page, result, logger, options))
        for detector_class in self._detector_classes:
            self._detectors.append(detector_class(self._page, result, logger, options))

    def _load_detector_modules(self, result, logger, options, preferred_detector):
        self._detectors = [DETECTORS[preferred_detector](self._page, result, logger, options)]

    def _load_extractor_modules(self, result, logger, options):
        for extractor_class in self._extractor_classes:
            self._extractors.append(extractor_class(self._page, result, logger, options))

    def _reset_modules(self):
        self._extractors = []
        self._detectors = []

    def _get_by_priority(self, result, logger, options):
        selected_detector = None
        detection_methods = {
            'perceptive': False, 'naive': False,
            'i-dont-care-about-cookies': False,
            'easylist-cookie': False,
            'filter_lists': False,
            'bert': False}
        if 'bert' in result:
            detection_methods['bert'] = True
        if 'perceptive' in result:
            detection_methods['perceptive'] = True
        if 'naive' in result:
            detection_methods['naive'] = True
        if 'i-dont-care-about-cookies' in result:
            detection_methods['i-dont-care-about-cookies'] = True
        if 'easylist-cookie' in result:
            detection_methods['easylist-cookie'] = True
        for detector in options['detector_priorities']:
            if detection_methods[detector]:
                selected_detector = detector
                break
        return selected_detector

    def _get_all_cookies(self):
        return self._tab.Network.getAllCookies().get('cookies')

    def _clear_browser(self):
        """Clears cache, cookies, local storage, etc. of the browser."""
        self._tab.Network.clearBrowserCache()
        self._tab.Network.clearBrowserCookies()
        self._clear_local_storage()
        # store all domains that were requested
        first_level_domains = set()
        for loaded_url in self._page.response_log:
            # invalid urls raise an exception
            try:
                first_level_domain = get_fld(loaded_url)
                first_level_domains.add(first_level_domain)
            except Exception:
                pass

        # clear the data for each domain
        for first_level_domain in first_level_domains:
            self._tab.Storage.clearDataForOrigin(origin='.' + first_level_domain, storageTypes='all')

    # Fetch a single element, either the element itself or the first element from a list
    def fetch_single_element(self, element: dict or list) -> dict:
        if isinstance(element, list):
            return_element = element[0]
        else:
            return_element = element
        return return_element

    def _clear_local_storage(self) -> None:
        """Calls localStorage.clear() to remove all keys from local storage. This is necessary because sometimes the
        consent is saved in local storage instead of cookies which can cause the scanner to break since it is unable
        to click the non-loaded consent banner. Example: https://forbes.com."""
        js_expression = 'localStorage.clear()'
        self._tab.Runtime.evaluate(expression=js_expression).get('result')

    def click_and_wait(self, clickable: dict, time_in_seconds: int):
        """Fetch a clickable element by by node_id, click it, and wait for a given amount of time."""
        self._CLICKED = True
        click_node(tab=self._tab, node_id=clickable['node_id'])
        self._tab.wait(time_in_seconds)
        self._CLICKED = False
