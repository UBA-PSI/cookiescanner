# Cookiescanner
Cookiescanner is an extension of [privacyscanner](https://github.com/PrivacyScore/privacyscanner). It identifies and analyzes cookie consent notices.

## Structure (/privacyscanner/scanmodules/cookiebanner)
* db_handling: Scripts to refill the database/scanning queue
* detectors: Detectors for the banners
* detectors/utils: General functions to process nodes, notices, clickables, etc. used throughout the application
* extractors: Extract various information from the sites
* lists: fiter lists and scanning source lists
* pagescanner.py: The actual scanner

## Setup Instructions

This section describes how to set up cookiescanner. Please note that the code is provided "as is" and may no longer work. The [ChromeDevToolsProtocol](https://chromedevtools.github.io/devtools-protocol/) may have changed, causing the code to fail. If this is the case, please contact me at rg.psi@uni-bamberg.de and I will see if there is an easy fix available or if I need to retire the code.

This guide describes the setup process for Debian Unstable, as this was the operating system of the scanning host. However, any Linux distribution with Chromium, Python, and a PostgreSQL database should work.

### Prerequesites
	sudo apt install chromium
	sudo apt install python3 python3-venv
	sudo apt install postgresql
### Database
#### Start and Enable the PostgreSQL Service
	sudo systemctl start postgresql
	sudo systemctl enable postgresql
#### Create Database and User
	# Change to postgres user
	sudo su postgres
	# Enter psql shell
	psql
	# create user
	create user privacyscanner with encrypted password 'welcome';
	create database privacyscanner owner privacyscanner;
	# quit
	\q
	# Exit to normal user
	exit		
#### Import DB Schema
	# Import DB Schema (use the password you configured for "privacyscanner")
	psql -U privacyscanner -d privacyscanner -h localhost -f schema.sql
### Set Up Cookiescanner
#### Configure and Enter a Virtual Environment
	python3 -m venv venv
	# Enter the venv (the venv has to be activated for each shell that you 
	# want to run privacyscanner from)
	source venv/bin/activate
#### Install Modified Pychrome Version
		pip install pychrome/
#### Install Modified Version of Privacyscanner with the Cookiebanner Module
	pip install -e .
#### Copy the Config and Module Dependencies to the Home Directory
	cp -r .config/privacyscanner ~/.config
	cp -r .local/share/privacyscanner ~/.local/share
#### Run the BERT model
To keep the dependencies separate, the BERT model runs embedded in a web application inside a docker container, and privacyscanner accesses it via HTTP requests. First, install docker (https://docs.docker.com/engine/install/debian/ - you might have to substitute the release name of the unstable debian distribution with the current stable one, if you use unstable and want to use the docker repository), then build and run the image using the instructions further down below. Since it is quite large, the directory containing the trained ML model is stored on Zenodo together with the training data at https://doi.org/10.5281/zenodo.7884468. 

	# Move to directory with ML model
	cd 01_bert_classifier/
	# Build the container
	docker build -t paper .
	# Run the container detached
	docker run --detach --name paper --restart always --publish 9999:9999 paper

#### OPTIONAL: Change Config File To Add Additional Workers
The scanner is currently configured to run 5 scans in parallel. We used 20 in parallel for the paper which is easily achievable using sufficient resources. You can change this setting by editing the config file `~/.config/privacyscanner/config.py` and adapting the line `NUM_WORKERS = 5`.
### OPTIONAL: Update Module Dependencies
The `.local/share/privacyscanner` folder contains the dependencies used during the scans for the paper. If you want to fetch new filter lists, you can update them by running the command `privacyscanner run update_dependencies`.
### Insert Scanning Lists, Refill Scanning Queue, and Running Scans
#### Insert Scanning Lists
Copy your `.csv` files with websites into `privacyscanner/scanning_lists`. They have to either be in the form

	google.com
	a-msedge.net
	youtube.com
	facebook.com
	microsoft.com

or

	rank,domain
	1,google.com
	2,a-msedge.net
	3,youtube.com
	4,facebook.com
	5,microsoft.com

Otherwise, the insert module will throw an error.

You can list files with `privacyscanner scanning_lists` and insert a list with the command `privacyscanner insert -f example.csv`.
#### Refill the scanning queue
Use the command `privacyscanner refill_queue -m cookiebanner` to refill the scanning queue for the cookiebanner module.
####  Delete Scan Results
Use the command `privacyscanner clear_results` to clear the database. If you need the data, back it up first.
#### Scan a Single Website
You can scan a single website using the command `privacyscanner scan -m cookiebanner <site_url>`. Instead of the database, scan results will be saved in the current directory in a folder named after the scanned domain. The folder includes a JSON file with the scan results and screenshots.
#### Running the Scanner
Run the scanner in the background while redirecting output to a log file:
`privacyscanner run_workers >> scans.txt 2>&1 &`
You can terminate the scanner by looking for the PID and killing the parent process once all scans are finished:

	# Find the id of the "run_workers" process
	ps ax | grep "run_workers"
	# Kill it once scans are complete
	kill <PID>

## Sample Config File
```
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
```
