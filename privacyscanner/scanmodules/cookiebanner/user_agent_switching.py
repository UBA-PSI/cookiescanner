import random_user_agent.user_agent
from random_user_agent.user_agent import UserAgent
from random_user_agent.params import SoftwareName, OperatingSystem


def get_user_agent_rotator() -> random_user_agent.user_agent.UserAgent:
    """Returns a UserAgent object with 100 different user agents. These can be queried using the
    'get_random_user_agent()' method. The object is configured to use Chrome and Firefox as well as Windows,
    Linux and Mac as operating systems."""

    software_names = [SoftwareName.CHROME.value, SoftwareName.FIREFOX.value]
    operating_systems = [OperatingSystem.WINDOWS.value, OperatingSystem.LINUX.value, OperatingSystem.MAC.value]

    user_agent_rotator = UserAgent(software_names=software_names, operating_systems=operating_systems, limit=100)
    return user_agent_rotator
