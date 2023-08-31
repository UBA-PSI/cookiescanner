import re


def remove_url_prefix(url: str) -> str:
    """Removes the prefix "http://" or "https://" if it is included in a site name.
       e. g. "https://google.com" becomes "google.com\""""
    if url.startswith('https://'):
        return url[len('https://'):]
    elif url.startswith('http://'):
        return url[len('http://'):]
    else:
        return url


def parse_dsn_dict_from_string(dsn_str: str) -> dict:
    """Parses a DSN string and returns it as a dictionary."""
    regex_str = r'((\S*)=(\S*))'
    dsn_dict = dict()
    for m in re.finditer(pattern=regex_str, string=dsn_str):
        dsn_dict[m.group(2)] = m.group(3)
    return dsn_dict


def module_exists(config: dict, module_names: str) -> bool and str or None and list:
    """This function checks whether a provided comma separated list of modules or single module actually exists in
       the scanner. It returns a boolean as well as a list of the available modules."""
    from privacyscanner.scanmodules import load_modules
    scan_modules = load_modules(config['SCAN_MODULES'], config['SCAN_MODULE_OPTIONS'])
    module_names = module_names.split(',')
    for module_name in module_names:
        if module_name not in scan_modules.keys():
            return False, module_name, scan_modules.keys()
        else:
            return True, None, scan_modules.keys()
