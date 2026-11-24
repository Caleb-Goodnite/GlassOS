#!/bin/bash
# GlassOS image builder. Runs as root on a Debian 13 machine (the Lima VM made by ./build.sh).
#
#   build-in-vm.sh <amd64|arm64> [stage...]
#
# Stages (default: all):
#   rootfs     bootstrap Debian + install every package from config/packages.list
#   assets     render wallpaper, logo, GRUB + boot splash art, and the default sound pack
#   configure  copy GlassOS files into the system and run scripts/chroot-configure.sh
#   iso        pack the system into a squashfs and build a GRUB-bootable hybrid ISO
#
# The root filesystem is kept between runs, so re-running "configure iso" after editing
# theme/config files takes a couple of minutes instead of a full rebuild.
set -euo pipefail

ARCH="${1:?usage: build-in-vm.sh <amd64|arm64> [stage...]}"
shift || true
STAGES=("$@")
[ ${#STAGES[@]} -eq 0 ] && STAGES=(rootfs assets configure iso)

SRC="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../config/glassos.conf
. "$SRC/config/glassos.conf"

WORK="/var/tmp/glassos/$ARCH"
ROOT="$WORK/rootfs"
ISO_DIR="$WORK/iso"
OUT="$SRC/out"
GEN="$SRC/assets/generated"
ISO_NAME="GlassOS-${GLASSOS_VERSION}-${ARCH}.iso"

case "$ARCH" in
  amd64) GRUB_PLATFORMS="i386-pc x86_64-efi" ;;
  arm64) GRUB_PLATFORMS="arm64-efi" ;;
  *) echo "unknown arch $ARCH" >&2; exit 1 ;;
esac

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
mkdir -p "$WORK" "$OUT"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# --- package list parsing -------------------------------------------------------------
# prints package names for this arch; $1 = main | bpo
packages() {
  local want="$1" line name rest t arch_tag bpo
  set -f
  while IFS= read -r line; do
    line="${line%%#*}"
    read -r name rest <<<"$line" || true
    [ -n "${name:-}" ] || continue
    arch_tag=""; bpo=0
    for t in $rest; do
      case "$t" in
        "[amd64]") arch_tag=amd64 ;;
        "[arm64]") arch_tag=arm64 ;;
        "[bpo]") bpo=1 ;;
      esac
    done
    [ -n "$arch_tag" ] && [ "$arch_tag" != "$ARCH" ] && continue
    if [ "$want" = bpo ] && [ $bpo = 1 ]; then echo "$name"; fi
    if [ "$want" = main ] && [ $bpo = 0 ]; then echo "$name"; fi
  done < "$SRC/config/packages.list"
  set +f
}

# --- chroot helpers -------------------------------------------------------------------
MOUNTED=0
mount_chroot() {
  [ $MOUNTED = 1 ] && return
  mount --bind /dev "$ROOT/dev"
  mount --bind /dev/pts "$ROOT/dev/pts"
  mount -t proc proc "$ROOT/proc"
  mount -t sysfs sysfs "$ROOT/sys"
  mount -t tmpfs tmpfs "$ROOT/run"
  rm -f "$ROOT/etc/resolv.conf"
  cp -L /etc/resolv.conf "$ROOT/etc/resolv.conf"
  printf '#!/bin/sh\nexit 101\n' > "$ROOT/usr/sbin/policy-rc.d"
  chmod +x "$ROOT/usr/sbin/policy-rc.d"
  MOUNTED=1
}
umount_chroot() {
  [ $MOUNTED = 1 ] || return 0
  rm -f "$ROOT/usr/sbin/policy-rc.d"
  for m in run sys proc dev/pts dev; do umount -lf "$ROOT/$m" 2>/dev/null || true; done
  MOUNTED=0
}
trap umount_chroot EXIT
in_chroot() { chroot "$ROOT" /usr/bin/env -i HOME=/root TERM="${TERM:-xterm}" \
  PATH=/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 "$@"; }

# --- stages ---------------------------------------------------------------------------
stage_rootfs() {
  local main bpo
  main="$(packages main | paste -sd, -)"
  bpo="$(packages bpo | paste -sd' ' -)"
  if [ ! -x "$ROOT/usr/bin/apt-get" ]; then
    log "Bootstrapping Debian $DEBIAN_SUITE ($ARCH) - this is the slow part"
    rm -rf "$ROOT"
    local C="main contrib non-free-firmware"
    mmdebstrap --mode=root --arch="$ARCH" --variant=minbase \
      --aptopt='APT::Install-Recommends "false"' \
      --aptopt='APT::Install-Suggests "false"' \
      --dpkgopt='path-exclude=/usr/share/doc/*' \
      --dpkgopt='path-include=/usr/share/doc/*/copyright' \
      --dpkgopt='path-exclude=/usr/share/man/*' \
      --dpkgopt='path-exclude=/usr/share/info/*' \
      --dpkgopt='path-exclude=/usr/share/lintian/*' \
      --include="$main" \
      "$DEBIAN_SUITE" "$ROOT" \
      "deb $DEBIAN_MIRROR $DEBIAN_SUITE $C" \
      "deb $DEBIAN_MIRROR $DEBIAN_SUITE-updates $C" \
      "deb $DEBIAN_SECURITY_MIRROR $DEBIAN_SUITE-security $C" \
      "deb $DEBIAN_MIRROR $DEBIAN_SUITE-backports $C"
  fi
  log "Installing/refreshing packages"
  mount_chroot
  in_chroot apt-get update
  in_chroot apt-get -y full-upgrade   # include every security/bug-fix update
  # shellcheck disable=SC2086
  in_chroot apt-get install -y ${main//,/ }
  # shellcheck disable=SC2086
  in_chroot apt-get install -y -t "$DEBIAN_SUITE-backports" $bpo
  build_hyprbars
  in_chroot apt-get clean
  umount_chroot
}

# Title bars with the red/yellow/green buttons on every window come from Hyprland's official
# hyprbars plugin. A plugin only loads into the exact Hyprland version it was compiled against,
# and Debian's packaged one is older than our Hyprland, so we compile it here against the
# hyprland-dev headers of the Hyprland we just installed. The build tools are removed again.
HYPRBARS_TAG=v0.55.0   # hyprland-plugins tag for Hyprland 0.55.x; move it with every Hyprland upgrade
build_hyprbars() {
  local so=/usr/lib/glassos/hyprland/libhyprbars.so before added
  log "Compiling the hyprbars title-bar plugin ($HYPRBARS_TAG)"
  before="$(in_chroot dpkg-query -W -f='${Package}\n' | sort)"
  in_chroot apt-get install -y -t "$DEBIAN_SUITE-backports" hyprland-dev
  in_chroot apt-get install -y cmake make g++ pkg-config git ca-certificates
  # Debian's Hyprland was compiled against an older hyprutils than the hyprutils-dev now in
  # backports, and its headers don't compile against the newer one. Swap in the headers of the
  # hyprutils Hyprland actually runs with, and link against that same library, so the plugin
  # matches it exactly. (Both swaps are undone when the build packages are purged below.)
  local hu_so hu_ver
  hu_so="$(in_chroot readelf -d /usr/bin/Hyprland | grep -o 'libhyprutils\.so\.[0-9]*' | head -n1)"
  hu_ver="$(in_chroot dpkg-query -W -f='${Version}' "libhyprutils${hu_so##*.}")"
  hu_ver="${hu_ver%%-*}"
  log "Hyprland uses $hu_so (hyprutils $hu_ver)"
  rm -rf "$ROOT/tmp/hp" "$ROOT/tmp/hu"
  in_chroot git clone --depth 1 -b "v$hu_ver" https://github.com/hyprwm/hyprutils /tmp/hu
  rm -rf "$ROOT/usr/include/hyprutils"
  cp -r "$ROOT/tmp/hu/include/hyprutils" "$ROOT/usr/include/"
  local triplet=x86_64-linux-gnu
  [ "$ARCH" = arm64 ] && triplet=aarch64-linux-gnu
  ln -sf "$hu_so" "$ROOT/usr/lib/$triplet/libhyprutils.so"
  in_chroot git clone --depth 1 -b "$HYPRBARS_TAG" https://github.com/hyprwm/hyprland-plugins /tmp/hp
  in_chroot cmake -S /tmp/hp/hyprbars -B /tmp/hp/build -DCMAKE_BUILD_TYPE=Release
  in_chroot cmake --build /tmp/hp/build -j"$(nproc)"
  install -Dm644 "$ROOT/tmp/hp/build/libhyprbars.so" "$ROOT$so"
  rm -rf "$ROOT/tmp/hp" "$ROOT/tmp/hu"
  # remove only what this step installed (keeps ca-certificates etc. if the system already had them)
  added="$(comm -13 <(echo "$before") <(in_chroot dpkg-query -W -f='${Package}\n' | sort) | paste -sd' ' -)"
  # shellcheck disable=SC2086
  [ -n "$added" ] && in_chroot apt-get purge -y --auto-remove $added
  rm -rf "$ROOT/usr/include/hyprutils"; rm -f "$ROOT/usr/lib/$triplet/libhyprutils.so"   # the swapped-in copies
  [ -s "$ROOT$so" ] || { echo "hyprbars plugin was not built ($so missing)" >&2; exit 1; }
}

stage_assets() {
  log "Rendering artwork (wallpaper, logo, GRUB theme, boot splash)"
  mkdir -p "$GEN"
  python3 "$SRC/scripts/make-assets.py" "$GEN"
  log "Synthesising the default sound pack"
  python3 "$SRC/scripts/make-sounds.py" "$SRC/soundpacks/glassos-default"
}

stage_configure() {
  [ -d "$GEN" ] || stage_assets
  log "Copying GlassOS files into the system"
  rsync -rlpt "$SRC/overlay/" "$ROOT/"
  chmod 0440 "$ROOT/etc/sudoers.d/"* 2>/dev/null || true

  install -d "$ROOT/usr/share/glassos" "$ROOT/usr/share/glassos/wallpapers" \
             "$ROOT/usr/share/glassos/soundpacks" "$ROOT/usr/share/glassos/grub-theme" \
             "$ROOT/usr/share/plymouth/themes/glassos"
  install -m644 "$SRC/config/packages.list" "$ROOT/usr/share/glassos/packages.list"
  install -m644 "$SRC/soundpacks/README.md" "$ROOT/usr/share/glassos/soundpacks/README.md"
  cp "$GEN"/wallpapers/* "$ROOT/usr/share/glassos/wallpapers/"
  rsync -rlt --delete "$GEN/grub-theme/" "$ROOT/usr/share/glassos/grub-theme/"
  rsync -rlt "$SRC/grub/theme.txt" "$ROOT/usr/share/glassos/grub-theme/theme.txt"
  rsync -rlt --delete "$GEN/plymouth/" "$ROOT/usr/share/plymouth/themes/glassos/"
  cp "$SRC"/plymouth/glassos.plymouth "$SRC"/plymouth/glassos.script "$ROOT/usr/share/plymouth/themes/glassos/"
  for size in 16 24 32 48 64 128 256 512; do
    for icon in glassos glass-lens glass-sounds glass-settings glass-store; do
      [ -f "$GEN/icons/$icon-$size.png" ] || continue
      install -D -m644 "$GEN/icons/$icon-$size.png" \
        "$ROOT/usr/share/icons/hicolor/${size}x${size}/apps/$icon.png"
    done
  done
  install -m644 "$GEN/icons/glassos-symbolic.png" "$ROOT/usr/share/glassos/logo-symbolic.png"
  install -m644 "$GEN/icons/glassos-256.png" "$ROOT/usr/share/glassos/logo.png"
  for pack in "$SRC"/soundpacks/*/; do
    rsync -rlt --delete "$pack" "$ROOT/usr/share/glassos/soundpacks/$(basename "$pack")/"
  done

  cat > "$ROOT/usr/share/glassos/build-info" <<EOF
GLASSOS_VERSION=$GLASSOS_VERSION
GLASSOS_CODENAME=$GLASSOS_CODENAME
ARCH=$ARCH
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DEBIAN_SUITE=$DEBIAN_SUITE
DEFAULT_SOUNDPACK=$DEFAULT_SOUNDPACK
EOF

  log "Configuring the system (inside chroot)"
  mount_chroot
  install -m755 "$SRC/scripts/chroot-configure.sh" "$ROOT/tmp/chroot-configure.sh"
  in_chroot GLASSOS_VERSION="$GLASSOS_VERSION" GLASSOS_CODENAME="$GLASSOS_CODENAME" \
    LIVE_USER="$LIVE_USER" LIVE_PASSWORD="$LIVE_PASSWORD" LIVE_HOSTNAME="$LIVE_HOSTNAME" \
    DEFAULT_SOUNDPACK="$DEFAULT_SOUNDPACK" DEBIAN_SUITE="$DEBIAN_SUITE" ARCH="$ARCH" \
    /bin/bash /tmp/chroot-configure.sh
  rm -f "$ROOT/tmp/chroot-configure.sh"
  umount_chroot
  # NetworkManager writes resolv.conf itself on the real system
  rm -f "$ROOT/etc/resolv.conf"
}

grub_dir_args() {
  # grub-mkrescue only needs GRUB's platform module folders. We take them from the target
  # system so an arm64 build machine can still produce a BIOS+UEFI x86 ISO.
  local plat
  for plat in $GRUB_PLATFORMS; do
    [ -d "$ROOT/usr/lib/grub/$plat" ] || { echo "missing GRUB platform $plat in rootfs" >&2; exit 1; }
  done
  echo "$ROOT/usr/lib/grub"
}

stage_iso() {
  log "Building the live ISO"
  rm -rf "$ISO_DIR"
  mkdir -p "$ISO_DIR/live" "$ISO_DIR/boot/grub/themes"
  local kernel initrd
  kernel="$(ls -1 "$ROOT"/boot/vmlinuz-* | sort -V | tail -1)"
  initrd="$(ls -1 "$ROOT"/boot/initrd.img-* | sort -V | tail -1)"
  cp "$kernel" "$ISO_DIR/live/vmlinuz"
  cp "$initrd" "$ISO_DIR/live/initrd.img"
  # keep copies for direct-kernel debug boots in QEMU
  cp "$kernel" "$OUT/vmlinuz-$ARCH"; cp "$initrd" "$OUT/initrd-$ARCH.img"

  log "Compressing the system ($SQUASHFS_COMP) - takes a few minutes"
  local comp_opts=(-comp "$SQUASHFS_COMP")
  [ "$SQUASHFS_COMP" = zstd ] && comp_opts+=(-Xcompression-level 19)
  mksquashfs "$ROOT" "$ISO_DIR/live/filesystem.squashfs" "${comp_opts[@]}" -b 1M -noappend \
    -wildcards -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*' 'var/tmp/*' 'var/cache/apt/archives/*.deb'

  rsync -rlt "$GEN/grub-theme/" "$ISO_DIR/boot/grub/themes/glassos/"
  cp "$SRC/grub/theme.txt" "$ISO_DIR/boot/grub/themes/glassos/theme.txt"
  sed -e "s/@VERSION@/$GLASSOS_VERSION/g" "$SRC/grub/grub-live.cfg" > "$ISO_DIR/boot/grub/grub.cfg"
  echo "GlassOS $GLASSOS_VERSION ($GLASSOS_CODENAME) $ARCH" > "$ISO_DIR/.disk-info"

  log "Writing $ISO_NAME (GRUB: $GRUB_PLATFORMS)"
  local grubdir
  grubdir="$(grub_dir_args)"
  rm -f "$OUT/$ISO_NAME"
  # grub-mkrescue scans /usr/lib/grub for every platform it can find; give it the target's
  # copy in a private mount namespace (so the build VM's own GRUB is never mixed in).
  unshare -m bash -c "mount --bind '$grubdir' /usr/lib/grub && \
    grub-mkrescue -o '$OUT/$ISO_NAME' '$ISO_DIR' -- -volid GLASSOS"
  ( cd "$OUT" && sha256sum "$ISO_NAME" > "$ISO_NAME.sha256" )
  ls -lh "$OUT/$ISO_NAME"
  # free the space (the rootfs stays for fast rebuilds)
  rm -rf "$ISO_DIR"
}

for s in "${STAGES[@]}"; do
  case "$s" in
    rootfs) stage_rootfs ;;
    assets) stage_assets ;;
    configure) stage_configure ;;
    iso) stage_iso ;;
    *) echo "unknown stage $s" >&2; exit 1 ;;
  esac
done
log "Done: ${STAGES[*]}"
