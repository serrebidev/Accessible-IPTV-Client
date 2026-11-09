"""Project links shown by the About dialog.

Kept out of main.py so the dialog module can use them without importing the
whole application module.
"""

import app_meta

TELEGRAM_SUPPORT_URL = "https://t.me/SerrebiProjects"
PROJECT_FORGEJO_URL = "https://{host}/{owner}/{repo}".format(
    host=app_meta.FORGEJO_HOST, owner=app_meta.FORGEJO_OWNER,
    repo=app_meta.FORGEJO_REPO)
SERREBI_FORGEJO_URL = "https://{host}/{owner}".format(
    host=app_meta.FORGEJO_HOST, owner=app_meta.FORGEJO_OWNER)
