#!/bin/sh
# Install the .deb and prove the app actually starts on Debian.
#
# Run as root on a throwaway Debian/Ubuntu system - a container is ideal, since
# this installs packages and kills processes:
#
#   docker run --rm -v "$PWD:/src" debian:trixie \
#     sh /src/tools/deb_smoke_test.sh /src/dist/release/accessible-iptv-client_*.deb
#
# Passing means: apt resolved every dependency, the launcher is executable, and
# the wxPython window really mapped on an X display (not just "the process did
# not exit yet", which a crash during UI construction can still satisfy).

set -e

DEB="$1"
if [ -z "$DEB" ] || [ ! -f "$DEB" ]; then
    echo "usage: $0 <path-to-.deb>" >&2
    exit 2
fi

export DEBIAN_FRONTEND=noninteractive
DISPLAY_NUM=99
export DISPLAY=":${DISPLAY_NUM}"

echo "=== installing $(basename "$DEB") and its dependencies"
apt-get update -qq
# The .deb path must stay absolute-ish for apt to treat it as a file, not a name.
apt-get install -y -qq "$(readlink -f "$DEB")" xvfb xdotool >/dev/null

echo "=== installed files"
dpkg -L accessible-iptv-client | grep -E '/(bin|applications|man1)/|main\.py$'
ls -l /usr/bin/accessible-iptv-client
test -x /usr/bin/accessible-iptv-client || { echo "FAIL: launcher is not executable" >&2; exit 1; }

echo "=== import check"
python3 -c 'import wx, vlc; print("wx", wx.version())'

echo "=== launching under Xvfb"
Xvfb "$DISPLAY" -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
sleep 2

echo "=== Stalker portal dialog check"
python3 - <<'PY'
import sys

sys.path.insert(0, "/usr/lib/accessible-iptv-client")

import wx
from playlist import StalkerPortalDialog


def descendants(window):
    for child in window.GetChildren():
        yield child
        yield from descendants(child)


app = wx.App(False)
dialog = StalkerPortalDialog(None)
try:
    labels = {
        child.GetLabel()
        for child in descendants(dialog)
        if isinstance(child, wx.StaticText)
    }
    assert "Optional portal account username:" in labels
    assert "Optional portal account password:" in labels
    dialog.url_ctrl.SetValue("http://portal.example.com/c/")
    data = dialog.get_data()
    assert data is not None
    assert data["username"] == ""
    assert data["password"] == ""
    assert data["mac"]
finally:
    dialog.Destroy()
    app.Destroy()
print("PASS: Stalker portal credentials are visibly optional and may be blank")
PY

accessible-iptv-client >/tmp/app.log 2>&1 &

WINDOW=""
i=0
while [ "$i" -lt 40 ]; do
    sleep 1
    WINDOW=$(xdotool search --name "Accessible IPTV Client" 2>/dev/null | head -1 || true)
    [ -n "$WINDOW" ] && break
    i=$((i + 1))
done

APP_PID=$(pgrep -f "python3 /usr/lib/accessible-iptv-client/main.py" | head -1 || true)
echo "app pid: [${APP_PID}]  window: [${WINDOW}]"
[ -n "$WINDOW" ] && xdotool getwindowname "$WINDOW"

echo "=== application output"
cat /tmp/app.log || true

STATUS=0
if [ -z "$APP_PID" ] || [ -z "$WINDOW" ]; then
    echo "FAIL: the application did not present a window within 40s" >&2
    STATUS=1
elif grep -q "Traceback" /tmp/app.log 2>/dev/null; then
    echo "FAIL: the application logged a traceback" >&2
    STATUS=1
else
    echo "PASS: window mapped and the application is running"
fi

[ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true
pkill Xvfb 2>/dev/null || true
exit "$STATUS"
