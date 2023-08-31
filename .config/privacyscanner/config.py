QUEUE_DB_DSN = 'dbname=privacyscanner user=privacyscanner password=welcome host=localhost'
MAX_EXECUTION_TIMES = {None: 300}
SCAN_MODULE_OPTIONS = {
        'cookiebanner':{
            'chrome_executable': '/usr/bin/chromium',
            # Specifies which detection method is active
            'detectors':{
                'bert': True,
                'easylist-cookie': True,
                'i-dont-care-about-cookies': True,
                'naive': True,
                'perceptive': True 
            },
            # Specifies the priority according to which banners are analyzed
            # Only one banner is clicked through during a scan attempt
            'detector_priorities': [
                'bert',
                'perceptive',
                'naive',
                'i-dont-care-about-cookies',
                'easylist-cookie'
                ],
            'disable_javascript': False,
            # Take screenshots of the page as well as a screenshot of the page
            # after each button press
            'take_screenshots': True,
            # Take a screenshot of just the detected banner and save it in the
            # result
            'take_screenshots_banner_only': True,
            # The screen resolution
            'resolution':{
                'width': 1920,
                'height': 1080
                },
            # Width of the scrollbar - Necessary as to not go beyond the bounds
            # of the screenshot during analysis
            # 'scrollbar_width_in_px': 15,
            # Click the elements in the banner
            'click_clickables': True,
            # Shows a matplotlib window of the detected contour (sanity
            # check during development)
            'perceptive_show_results': False,
            # Extracts the content of the privacy policy if present
            # Privacy policies are detected via a keyword list
            'extract_privacy_policy': True,
            # Timeout of the scanner
            'timeout': 60,
            # Old keyword detection just matches the string, new method 
            # extracts the node with matching keyword and highest word count 
            # and only if the word count of the node is three or bigger
            'old_kw_detection': False,
            # Randomize the user agent to mitigate triggering DDOS protection
            'random_user_agent': False,
            # Save the logger output of the scan
			'save_logs': False,
            # Wait time before any action (clicking, etc.)
            'page_load_delay': 5,
        },
}
SCAN_MODULES = ['privacyscanner.scanmodules.chromedevtools.ChromeDevtoolsScanModule',
                'privacyscanner.scanmodules.dns.DNSScanModule',
                'privacyscanner.scanmodules.mail.MailScanModule',
                'privacyscanner.scanmodules.serverleaks.ServerleaksScanModule',
                'privacyscanner.scanmodules.testsslsh.TestsslshHttpsScanModule',
                'privacyscanner.scanmodules.testsslsh.TestsslshMailScanModule',
                'privacyscanner.scanmodules.cookiebanner.cookiebanner_scan.CookiebannerScanModule']
NUM_WORKERS = 5
MAX_EXECUTIONS = 100
RAVEN_DSN = None
MAX_TRIES = 3
STORAGE_PATH = '~/.local/share/privacyscanner'
