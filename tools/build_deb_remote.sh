#!/bin/bash
# Build, lint and smoke-test the .deb for one tag on the Linux release host (local WSL Ubuntu, ssh alias wsl-build).
# tools/release.py pipes this over SSH and copies the printed .deb back:
#
#   ssh wsl-build bash -s -- v1.2.3 < tools/build_deb_remote.sh
#
# Everything runs in throwaway debian:trixie containers, like debian-package.yml
# on a runner. The last line of output is the .deb's path on the host.
set -euo pipefail

tag="$1"
repo="${IPTV_REPO_URL:-https://git.serrebiradio.com/serrebi/Accessible-IPTV-Client.git}"
work="$(mktemp -d /tmp/iptv-deb-XXXXXX)"

# ffmpeg.exe is an LFS object the .deb does not ship.
GIT_LFS_SKIP_SMUDGE=1 git clone --quiet --depth 1 --branch "$tag" "$repo" "$work/src" >&2
epoch="$(git -C "$work/src" log -1 --pretty=%ct)"

docker run --rm -e SOURCE_DATE_EPOCH="$epoch" -v "$work/src:/src" -w /src debian:trixie sh -c '
  set -e
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends python3 dpkg-dev lintian >/dev/null
  python3 tools/build_deb.py --version "'"${tag#v}"'" --output-dir dist/release
  deb="$(ls dist/release/accessible-iptv-client_*_all.deb)"
  dpkg-deb --info "$deb"
  lintian --tag-display-limit 0 --fail-on error "$deb"
  chown -R '"$(id -u):$(id -g)"' dist
' >&2

deb="$(ls "$work"/src/dist/release/accessible-iptv-client_*_all.deb)"
docker run --rm -v "$work/src:/src" debian:trixie sh /src/tools/deb_smoke_test.sh "/src/${deb#"$work/src/"}" >&2
echo "$deb"
