#!/bin/bash
# Put glassos-desktop packages into the signed apt repository that installed computers update from.
#
#   scripts/publish-repo.sh <repo-dir> <dev|stable> <file.deb>...
#
# <repo-dir> is served as-is over HTTPS (GitHub Pages: .../GlassOS/apt). Each channel keeps only
# its newest packages. Signs with the GPG key already imported (SIGNING_KEY_ID picks one).
set -euo pipefail
REPO="${1:?repo dir}" SUITE="${2:?suite}"
shift 2
[ $# -gt 0 ] || { echo "no packages given" >&2; exit 1; }
case "$SUITE" in dev|stable) ;; *) echo "suite must be dev or stable" >&2; exit 1 ;; esac
KEY="${SIGNING_KEY_ID:-$(gpg --batch --list-secret-keys --with-colons | awk -F: '$1 == "fpr" { print $10; exit }')}"
[ -n "$KEY" ] || { echo "no GPG signing key imported" >&2; exit 1; }

mkdir -p "$REPO/pool/main/$SUITE"
rm -f "$REPO/pool/main/$SUITE"/*.deb
cp "$@" "$REPO/pool/main/$SUITE/"
cd "$REPO"
for arch in amd64 arm64; do
  d="dists/$SUITE/main/binary-$arch"
  mkdir -p "$d"
  apt-ftparchive --arch "$arch" packages "pool/main/$SUITE" > "$d/Packages"
  gzip -9nkf "$d/Packages"
done
apt-ftparchive \
  -o APT::FTPArchive::Release::Origin=GlassOS \
  -o APT::FTPArchive::Release::Label=GlassOS \
  -o APT::FTPArchive::Release::Suite="$SUITE" \
  -o APT::FTPArchive::Release::Codename="$SUITE" \
  -o APT::FTPArchive::Release::Architectures="amd64 arm64" \
  -o APT::FTPArchive::Release::Components=main \
  -o APT::FTPArchive::Release::Description="GlassOS updates ($SUITE)" \
  release "dists/$SUITE" > "dists/$SUITE/Release.tmp"
mv "dists/$SUITE/Release.tmp" "dists/$SUITE/Release"
gpg --batch --yes --local-user "$KEY" --clearsign -o "dists/$SUITE/InRelease" "dists/$SUITE/Release"
gpg --batch --yes --local-user "$KEY" -abs -o "dists/$SUITE/Release.gpg" "dists/$SUITE/Release"
# the public key, for setting up updates by hand on a computer installed before they existed
gpg --batch --yes --export "$KEY" > glassos-archive-keyring.gpg
echo "published $(ls "pool/main/$SUITE") to $SUITE"
