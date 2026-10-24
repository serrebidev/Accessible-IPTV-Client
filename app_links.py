"""Project links shown by the About dialog.

Kept out of main.py so the dialog module can use them without importing the
whole application module.
"""

import app_meta

TELEGRAM_SUPPORT_URL = "https://t.me/SerrebiProjects"
PROJECT_GITHUB_URL = "https://github.com/{owner}/Accessible-IPTV-Client".format(
    owner=app_meta.GITHUB_OWNER)
SERREBI_GITHUB_URL = "https://github.com/serrebidev"
