#!/bin/bash
# Build the glassos-desktop package: every GlassOS file (overlay/, artwork, sound packs) in one
# Debian package, so installed computers can update GlassOS with apt like any other software.
#
#   scripts/make-deb.sh <amd64|arm64> <version> <out-dir> [notes-file]
#
# Needs the generated artwork in assets/generated (scripts/make-assets.py) and the synthesised
# default sound pack (scripts/make-sounds.py). Used by the ISO build and by the update workflow
# (.github/workflows/updates.yml). notes-file: one change per line, shown in Settings > Software Update.
set -euo pipefail
ARCH="${1:?arch}" VERSION="${2:?version}" OUT="${3:?out dir}" NOTES="${4:-}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
GEN="$SRC/assets/generated"
# shellcheck source=../config/glassos.conf
. "$SRC/config/glassos.conf"
[ -d "$GEN/wallpapers" ] || { echo "run scripts/make-assets.py first ($GEN missing)" >&2; exit 1; }

PKG="$(mktemp -d)"
trap 'rm -rf "$PKG"' EXIT
R="$PKG/root"
mkdir -p "$R"

# --- files ---------------------------------------------------------------------------------------
# Live-USB-only files stay out: the installer deletes them, and an update must never bring back
# the live session's password-free sudo.
rsync -rlpt --exclude /etc/sudoers.d/glassos-live --exclude /usr/share/applications/glass-install.desktop \
  "$SRC/overlay/" "$R/"
chmod 0440 "$R"/etc/sudoers.d/* 2>/dev/null || true
install -d "$R/usr/share/glassos/wallpapers" "$R/usr/share/glassos/soundpacks" \
           "$R/usr/share/glassos/grub-theme" "$R/usr/share/plymouth/themes/glassos"
install -m644 "$SRC/config/packages.list" "$R/usr/share/glassos/packages.list"
install -m644 "$SRC/soundpacks/README.md" "$R/usr/share/glassos/soundpacks/README.md"
cp "$GEN"/wallpapers/* "$R/usr/share/glassos/wallpapers/"
rsync -rlt "$GEN/grub-theme/" "$R/usr/share/glassos/grub-theme/"
cp "$SRC/grub/theme.txt" "$R/usr/share/glassos/grub-theme/theme.txt"
rsync -rlt "$GEN/plymouth/" "$R/usr/share/plymouth/themes/glassos/"
cp "$SRC"/plymouth/glassos.plymouth "$SRC"/plymouth/glassos.script "$R/usr/share/plymouth/themes/glassos/"
for size in 16 24 32 48 64 128 256 512; do
  for icon in glassos glass-lens glass-sounds glass-settings glass-store; do
    [ -f "$GEN/icons/$icon-$size.png" ] || continue
    install -D -m644 "$GEN/icons/$icon-$size.png" "$R/usr/share/icons/hicolor/${size}x${size}/apps/$icon.png"
  done
done
install -m644 "$GEN/icons/glassos-symbolic.png" "$R/usr/share/glassos/logo-symbolic.png"
install -m644 "$GEN/icons/glassos-256.png" "$R/usr/share/glassos/logo.png"
for pack in "$SRC"/soundpacks/*/; do
  rsync -rlt "$pack" "$R/usr/share/glassos/soundpacks/$(basename "$pack")/"
done
cat > "$R/usr/share/glassos/build-info" <<EOF
GLASSOS_VERSION=$VERSION
GLASSOS_RELEASE=$GLASSOS_VERSION
GLASSOS_BUILD_NUMBER=$(v="${VERSION#*:}"; echo "${v%%+*}")
GLASSOS_CODENAME=$GLASSOS_CODENAME
ARCH=$ARCH
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DEBIAN_SUITE=$DEBIAN_SUITE
DEFAULT_SOUNDPACK=$DEFAULT_SOUNDPACK
UPDATE_URL=$UPDATE_URL
UPDATE_CHANNEL=$UPDATE_CHANNEL
EOF

# Every version of every /etc/skel file GlassOS has ever shipped. When an update changes one of
# them, your copy in your home folder is updated too, if it's one of these (you never edited it).
# Edited copies are merged instead (config-sync).
{
  cd "$SRC"
  if git rev-parse --git-dir >/dev/null 2>&1; then
    git log --format=%H -- overlay/etc/skel | while read -r c; do
      git ls-tree -r "$c" -- overlay/etc/skel | while read -r _ _ blob path; do
        printf '%s  %s\n' "$(git cat-file blob "$blob" | sha256sum | cut -d' ' -f1)" "${path#overlay/etc/skel/}"
      done
    done
  fi
  (cd "$R/etc/skel" && find . -type f -printf '%P\n' | while read -r p; do
    printf '%s  %s\n' "$(sha256sum < "$p" | cut -d' ' -f1)" "$p"; done)
} | sort -u > "$PKG/skel-known"
install -m644 "$PKG/skel-known" "$R/usr/share/glassos/skel-known.sha256"

# --- package metadata ----------------------------------------------------------------------------
# Depends: everything in config/packages.list for this CPU, so a package GlassOS adds later is
# installed by the update that needs it.
deps="$(sed -e 's/#.*//' "$SRC/config/packages.list" | awk -v a="$ARCH" '
  NF { for (i = 2; i <= NF; i++) if (($i == "[amd64]" || $i == "[arm64]") && $i != "[" a "]") next
       print $1 }' | sort -u | paste -sd, - | sed 's/,/, /g')"
mkdir -p "$R/DEBIAN"
{
  echo "Package: glassos-desktop"
  echo "Version: $VERSION"
  echo "Architecture: $ARCH"
  echo "Maintainer: GlassOS <https://github.com/Caleb-Goodnite/GlassOS>"
  echo "Installed-Size: $(du -sk "$R" | cut -f1)"
  echo "Depends: $deps"
  echo "Section: misc"
  echo "Priority: optional"
  echo "Homepage: https://github.com/Caleb-Goodnite/GlassOS"
  echo "Description: GlassOS $GLASSOS_VERSION ($GLASSOS_CODENAME) desktop"
  if [ -n "$NOTES" ] && [ -s "$NOTES" ]; then
    # shown as "What's new" in Settings > Software Update
    sed -e 's/^[[:space:]]*//' -e '/^$/d' -e 's/^/ * /' "$NOTES" | head -n 20
  else
    echo " The GlassOS desktop, apps, artwork and sounds."
  fi
} > "$R/DEBIAN/control"
# Files in /etc are configuration: an update replaces them unless you edited them yourself.
(cd "$R" && find etc -type f -printf '/%p\n' | sort) > "$R/DEBIAN/conffiles"
install -m755 "$SRC/scripts/deb/preinst" "$SRC/scripts/deb/postinst" "$SRC/scripts/deb/postrm" "$R/DEBIAN/"

mkdir -p "$OUT"
deb="$OUT/glassos-desktop_${VERSION#*:}_${ARCH}.deb"   # (no "1:" in file names)
dpkg-deb --root-owner-group -Zxz --build "$R" "$deb" >/dev/null
echo "$deb"
