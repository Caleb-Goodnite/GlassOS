#!/bin/sh
# Prints the glassos-desktop package version for this checkout:  1:<build>+<release>
#   e.g. 1:142+1.5.0  = build 142 (commits on this branch), GlassOS 1.5.0 (config/glassos.conf)
#
# apt installs whichever version is newer, and it compares the build number first, so every
# merge is an update even if a branch bumped the release name. The "1:" puts these above the
# old-style versions (1.0.0+git28, 1.5.0+local...) that early ISOs installed.
# GLASSOS_DEB_VERSION overrides it: build.sh works it out on the Mac, where git is, and hands it
# to the build VM, which has no git.
cd "$(dirname "$0")/.." || exit 1
if [ -n "${GLASSOS_DEB_VERSION:-}" ]; then
  echo "$GLASSOS_DEB_VERSION"
  exit 0
fi
. ./config/glassos.conf
n="$(git -c safe.directory='*' rev-list --count HEAD 2>/dev/null)"
# no git at all: build 0, so any published update counts as newer
echo "1:${n:-0}+${GLASSOS_VERSION}"
