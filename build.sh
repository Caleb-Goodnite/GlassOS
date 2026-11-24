#!/bin/bash
# Build GlassOS.
#
#   ./build.sh                 build both ISOs (arm64 + amd64)
#   ./build.sh amd64           only the PC version (Intel/AMD, BIOS + UEFI)
#   ./build.sh arm64           only the ARM version (UEFI: Apple Silicon VMs, ARM laptops/servers)
#   ./build.sh amd64 configure iso    re-run just some stages after editing files (fast)
#
# Output: out/GlassOS-<version>-<arch>.iso (+ .sha256)
#
# On macOS everything runs inside a small Debian VM managed by Lima (brew install lima).
# On Debian/Ubuntu it runs directly with sudo (needs: mmdebstrap squashfs-tools xorriso mtools
# grub-common python3-pil python3-numpy fonts-inter; plus qemu-user-static for the other arch).
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
VM=glassbuild

target="${1:-all}"
[ $# -gt 0 ] && shift
case "$target" in
  all) arches=(arm64 amd64) ;;
  amd64|arm64) arches=("$target") ;;
  *) echo "usage: $0 [all|amd64|arm64] [rootfs assets configure iso]"; exit 1 ;;
esac

if [ "$(uname -s)" = Darwin ]; then
  command -v limactl >/dev/null || { echo "Install Lima first:  brew install lima"; exit 1; }
  if ! limactl list -q 2>/dev/null | grep -qx "$VM"; then
    echo "==> Creating the build VM (one time, ~2 minutes)"
    limactl create --name="$VM" --tty=false \
      --set ".mounts = [{\"location\": \"$HERE\", \"mountPoint\": \"/work\", \"writable\": true}]" \
      scripts/lima-glassbuild.yaml
  fi
  [ "$(limactl list "$VM" --format '{{.Status}}')" = Running ] || limactl start "$VM"
  for a in "${arches[@]}"; do
    limactl shell "$VM" -- sudo bash /work/scripts/build-in-vm.sh "$a" "$@"
  done
  echo
  echo "Done. Stop the build VM with:  limactl stop $VM   (delete it with: limactl delete $VM)"
else
  for a in "${arches[@]}"; do
    sudo bash scripts/build-in-vm.sh "$a" "$@"
  done
fi
ls -lh out/*.iso 2>/dev/null || true
