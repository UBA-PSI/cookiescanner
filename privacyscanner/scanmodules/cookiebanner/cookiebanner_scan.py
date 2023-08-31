import hashlib
import json
import logging
import os
import psutil
import pychrome
import shutil
import subprocess
import sys
import tempfile
import time
import websocket

from pathlib import Path
from requests.exceptions import ConnectionError

from privacyscanner.exceptions import RetryScan
from privacyscanner.scanmodules import ScanModule
from privacyscanner.scanmodules.cookiebanner.detectors import NaiveDetector, FilterListDetector, \
    SimplePerceptiveDetector, BertDetector
from privacyscanner.scanmodules.cookiebanner.extractors import TrackerExtractor, CookieSyncExtractor
from privacyscanner.scanmodules.chromedevtools.utils import parse_domain
from privacyscanner.scanmodules.cookiebanner.pagescanner import ChromeBrowserStartupError, DNSNotResolvedError, \
    NotReachableError, PageScanner
from privacyscanner.scanner import slugify
from privacyscanner.utils import kill_everything, set_default_options, file_is_outdated

CHANGE_WAIT_TIME = 15

# See https://github.com/GoogleChrome/chrome-launcher/blob/master/docs/chrome-flags-for-tools.md
# See also https://peter.sh/experiments/chromium-command-line-switches/
CHROME_OPTIONS = [
    # Disable various background network services, including extension
    # updating, safe browsing service, upgrade detector, translate, UMA
    '--disable-background-networking',

    # Disable fetching safebrowsing lists. Otherwise requires a 500KB
    # download immediately after launch. This flag is likely redundant
    # if disable-background-networking is on
    '--safebrowsing-disable-auto-update',

    # Disable syncing to a Google account
    '--disable-sync',

    # Disable reporting to UMA, but allows for collection
    '--metrics-recording-only',

    # Disable installation of default apps on first run
    '--disable-default-apps',

    # Mute any audio
    '--mute-audio',

    # Skip first run wizards
    '--no-first-run',

    # Disable timers being throttled in background pages/tabs
    '--disable-background-timer-throttling',

    # Disables client-side phishing detection. Likely redundant due to
    # the safebrowsing disable
    '--disable-client-side-phishing-detection',

    # Disable popup blocking
    '--disable-popup-blocking',

    # Reloading a page that came from a POST normally prompts the user.
    '--disable-prompt-on-repost',

    # Disable a few things considered not appropriate for automation.
    # (includes password saving UI, default browser prompt, etc.)
    '--enable-automation',

    # Avoid potential instability of using Gnome Keyring or KDE wallet.
    # crbug.com/571003
    '--password-store=basic',

    # Use mock keychain on Mac to prevent blocking permissions dialogs
    '--use-mock-keychain',

    # Allows running insecure content (HTTP content on HTTPS sites)
    '--allow-running-insecure-content',

    '--disable-web-security',

    # Disable dialog to update components
    '--disable-component-update',

    # Do autoplay everything.
    '--autoplay-policy=no-user-gesture-required',

    # Disable notifications (Web Notification API)
    '--disable-notifications',

    # Disable the hang monitor
    '--disable-hang-monitor',

    # Disable GPU acceleration
    '--disable-gpu',

    # Run headless
    '--headless'
]

PREFS = {
    'profile': {
        'content_settings': {
            'exceptions': {
                # Allow flash for all sites
                'plugins': {
                    'http://*,*': {
                        'setting': 1
                    },
                    'https://*,*': {
                        'setting': 1
                    }
                }
            }
        }
    },
    'session': {
        'restore_on_startup': 4,  # 4 = Use startup_urls
        'startup_urls': ['about:blank']
    }
}

ON_NEW_DOCUMENT_JAVASCRIPT = """
(function() {
    // Do not move this function somewhere else, because it expected to
    // be found on line 6 by the debugger. It is intentionally left
    // empty because the debugger will intercept calls to it and
    // extract the arguments and the stack trace.
    function log(type, message) {
        var setBreakpointOnThisLine;
    }

    window.alert = function() {};
    window.confirm = function() {
        return true;
    };
    window.prompt = function() {
        return true;
    };

    __extra_scripts__
})();
""".lstrip()

# TODO: There are still some contexts in which this JavaScript snippet does not
#       run properly. This requires more research.
EXTRACT_ARGUMENTS_JAVASCRIPT = '''
(function(logArguments) {
    let retval = 'null';
    if (logArguments !== null) {
        let duplicateReferences = [];
        // JSON cannot handle arbitrary data structures, especially not those
        // with circular references. Therefore we use a custom handler, that,
        // first, remember serialized objects, second, stringifies an object
        // if possible and dropping it if it is not.
        retval = JSON.stringify(logArguments, function(key, value) {
            if (typeof(value) === 'object' && value !== null) {
                if (duplicateReferences.indexOf(value) !== -1) {
                    try {
                        // This is a very ugly hack here. When we have a
                        // duplicate reference, we have to check if it is
                        // really a duplicate reference or only the same value
                        // occurring twice. Therefore, we try to JSON.stringify
                        // it without custom handler. If it throws an exception,
                        // it is indeed circular and we drop it.
                        JSON.stringify(value)
                    } catch (e) {
                        return;
                    }
                } else {
                    duplicateReferences.push(value);
                }
            }
            return value;
        });
    }
    return retval;
})(typeof(arguments) !== 'undefined' ? Array.from(arguments) : null);
'''.lstrip()

# See comments in ON_NEW_DOCUMENT_JAVASCRIPT
ON_NEW_DOCUMENT_JAVASCRIPT_LINENO = 7


class ChromeBrowser:
    def __init__(self, debugging_port=9222, chrome_executable=None):
        self._debugging_port = debugging_port
        if chrome_executable is None:
            chrome_executable = find_chrome_executable()
        self._chrome_executable = chrome_executable
        sys.setrecursionlimit(5000)

    def __enter__(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        temp_dirname = self._temp_dir.name
        user_data_dir = Path(temp_dirname) / 'chrome-profile'
        user_data_dir.mkdir()
        default_dir = user_data_dir / 'Default'
        default_dir.mkdir()
        with (default_dir / 'Preferences').open('w') as f:
            json.dump(PREFS, f)
        self._start_chrome(user_data_dir)
        return self

    def _start_chrome(self, user_data_dir):
        extra_opts = [
            '--remote-debugging-port={}'.format(self._debugging_port),
            '--enable-features=OverlayScrollbar,OverlayScrollbarFlashAfterAnyScrollUpdate,OverlayScrollbarFlashWhenMouseEnter',
            '--user-data-dir={}'.format(user_data_dir)
        ]
        command = [self._chrome_executable] + CHROME_OPTIONS + extra_opts
        self._p = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)

        self.browser = pychrome.Browser(url='http://127.0.0.1:{}'.format(
            self._debugging_port))

        # Wait until Chrome is ready
        max_tries = 100
        while max_tries > 0:
            try:
                self.browser.version()
                break
            except ConnectionError:
                time.sleep(0.1)
            max_tries -= 1
        else:
            raise ChromeBrowserStartupError('Could not connect to Chrome')

    def __exit__(self, exc_type, exc_val, exc_tb):
        kill_everything(self._p.pid)
        self._temp_dir.cleanup()


DETECTOR_CLASSES = [NaiveDetector, FilterListDetector, BertDetector, SimplePerceptiveDetector]
EXTRACTOR_CLASSES = [TrackerExtractor, CookieSyncExtractor]


class CookieScan:
    def __init__(self, extractor_classes, detector_classes):
        self._extractor_classes = extractor_classes
        self._detector_classes = []

    def scan(self, result, logger, options, meta, debugging_port=9222):
        executable = options['chrome_executable']
        if options['detectors']['easylist-cookie'] or options['detectors']['i-dont-care-about-cookies']:
            self._detector_classes.append(FilterListDetector)
        if options['detectors']['naive']:
            self._detector_classes.append(NaiveDetector)
        if options['detectors']['bert']:
            self._detector_classes.append(BertDetector)
        if options['detectors']['perceptive']:
            self._detector_classes.append(SimplePerceptiveDetector)
        if options['save_logs']:
            home_path = Path.home()
            log_path = Path(os.path.join(home_path, 'cookiebanner_logs'))
            log_path.mkdir(parents=True, exist_ok=True)
            log_file_name = slugify(result['site_url']) + '_'
            log_file_name += hashlib.sha512(result['site_url'].encode()).hexdigest()[:10]
            log_file_path = os.path.join(log_path, log_file_name)
            logger.addHandler(logging.FileHandler(log_file_path))
        scanner = PageScanner(self._extractor_classes, self._detector_classes)
        chrome_error = None
        content = None
        with ChromeBrowser(debugging_port, executable) as browser:
            try:
                content = scanner.scan(browser.browser, result, logger, options)
            except pychrome.TimeoutException:
                if meta.is_first_try:
                    raise RetryScan('First timeout with Chrome.')
                chrome_error = 'timeout'
            except ChromeBrowserStartupError:
                if meta.is_first_try:
                    raise RetryScan('Chrome startup problem.')
                chrome_error = 'startup-problem'
            except NotReachableError:
                if meta.is_first_try:
                    raise RetryScan('Not reachable')
                logger.exception('Neither responses, nor failed requests.')
                chrome_error = 'not-reachable'
            except DNSNotResolvedError:
                if meta.is_first_try:
                    raise RetryScan('DNS could not be resolved.')
                chrome_error = 'dns-not-resolved'
            # Attempt to catch websocket exception
            except websocket.WebSocketException:
                if meta.is_first_try:
                    raise RetryScan('')
                if 'initial_result' in result:
                    logger.exception('Browser crashed after interacting with the website.')
                    chrome_error = 'websocket-exception-interaction'
                else:
                    logger.exception('Browser crashed without interacting with the website.')
                    chrome_error = 'websocket-exception-no-interaction'
            finally:
                psutil.Process(browser._p.pid).kill()
        result['chrome_error'] = chrome_error
        result['reachable'] = not bool(chrome_error)
        return content


class CookiebannerScanModule(ScanModule):
    name = 'cookiebanner'
    dependencies = []
    required_keys = ['site_url']

    def __init__(self, options):
        if 'chrome_executable' not in options:
            options['chrome_executable'] = find_chrome_executable()
            set_default_options(options, {
                'disable_javascript': False,
                'https_same_content_threshold': 0.9
            })
        super().__init__(options)

    def scan_site(self, result, meta):
        debugging_port = 9222 + meta.worker_id
        scanner = CookieScan(EXTRACTOR_CLASSES, DETECTOR_CLASSES)
        content = scanner.scan(result, self.logger, self.options, meta, debugging_port)
        return content

    def update_dependencies(self):
        max_age = 14 * 24 * 3600
        cache_file = Path(parse_domain.cache_file)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        if file_is_outdated(cache_file, max_age):
            parse_domain.update(fetch_now=True)
        for extractor_class in EXTRACTOR_CLASSES:
            if hasattr(extractor_class, 'update_dependencies'):
                extractor_class.update_dependencies(self.options)
        for detector_class in DETECTOR_CLASSES:
            if hasattr(detector_class, 'update_dependencies'):
                detector_class.update_dependencies(self.options)


def find_chrome_executable():
    chrome_executable = shutil.which('google-chrome')
    if chrome_executable is None:
        macos_chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if Path(macos_chrome).exists():
            chrome_executable = macos_chrome
    if chrome_executable is None:
        chrome_executable = shutil.which('chromium')
    if chrome_executable is None:
        chrome_executable = shutil.which('chromium-browser')
    if chrome_executable is None:
        raise ChromeBrowserStartupError('Could not find google-chrome or chromium.')
    return chrome_executable
