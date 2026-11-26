#!/bin/bash
# Turn on GlassOS updates on a computer (or VM, or live USB) set up before updates existed.
#
#   curl -fsSL https://caleb-goodnite.github.io/GlassOS/setup.sh | sudo bash
#   curl -fsSL https://caleb-goodnite.github.io/GlassOS/setup.sh | sudo bash -s stable
#
# Adds GlassOS's signing key and update source, then installs the newest GlassOS (the
# glassos-desktop package, which brings any software GlassOS needs that's missing, like pkexec).
# After this, Settings > Software Update does the rest. ISOs built since updates existed don't
# need it. Published next to the updates by .github/workflows/updates.yml.
set -euo pipefail
SITE="https://caleb-goodnite.github.io/GlassOS"
CHANNEL="${1:-dev}"
KEY=/usr/share/keyrings/glassos-archive-keyring.gpg
[ "$(id -u)" = 0 ] || { echo "Run it with sudo:  curl -fsSL $SITE/setup.sh | sudo bash"; exit 1; }
case "$CHANNEL" in dev|stable) ;; *) echo "channel must be dev or stable"; exit 1 ;; esac
grep -q '^ID=glassos' /etc/os-release 2>/dev/null || { echo "This is for GlassOS computers only."; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> GlassOS signing key and update source ($CHANNEL channel)"
curl -fsSL "$SITE/apt/glassos-archive-keyring.gpg" -o "$KEY.tmp"
[ -s "$KEY.tmp" ] || { echo "Couldn't download the signing key."; exit 1; }
mv "$KEY.tmp" "$KEY"
chmod 644 "$KEY"
install -d /etc/glassos
printf '# GlassOS update channel: dev (every change, for testing) or stable (releases)\nchannel = %s\n' \
  "$CHANNEL" > /etc/glassos/updates.conf
cat > /etc/apt/sources.list.d/glassos.sources <<EOF
# GlassOS updates, "$CHANNEL" channel (set in /etc/glassos/updates.conf)
Types: deb
URIs: $SITE/apt
Suites: $CHANNEL
Components: main
Signed-By: $KEY
EOF

echo "==> Checking for updates"
apt-get update -q

echo "==> Installing the newest GlassOS"
# GlassOS's files are already on this computer, just not owned by a package yet:
# take the package's versions (--force-confnew)
apt-get install -y -q -o Dpkg::Options::=--force-confnew glassos-desktop

echo
echo "Done: GlassOS $(dpkg-query -W -f='${Version}' glassos-desktop) with updates turned on."
echo "From now on use Settings > Software Update. Log out and back in to see the new desktop."
[ -d /run/live/medium ] && echo "(This is the live USB: updates last until it restarts.)"
exit 0
