#!/bin/sh
# Prints the glassos-desktop package version for this checkout:
#   1.0.0          a tagged release (HEAD is tag v1.0.0): the "stable" channel
#   1.0.0+git142   anything else, numbered by commits so every build is newer than the last
cd "$(dirname "$0")/.." || exit 1
. ./config/glassos.conf
g() { git -c safe.directory='*' "$@" 2>/dev/null; }
if [ "$(g describe --tags --exact-match HEAD)" = "v$GLASSOS_VERSION" ]; then
  echo "$GLASSOS_VERSION"
elif n="$(g rev-list --count HEAD)" && [ -n "$n" ]; then
  echo "${GLASSOS_VERSION}+git${n}"
else
  echo "${GLASSOS_VERSION}+local$(date -u +%Y%m%d%H%M)"
fi
