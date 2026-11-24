#!/bin/bash
# Try a GlassOS ISO in a virtual machine (QEMU).   brew install qemu   /   apt install qemu-system
#
#   scripts/run-qemu.sh arm64            ARM version (fast on Apple Silicon: uses hardware virtualization)
#   scripts/run-qemu.sh amd64            PC version, UEFI (on Apple Silicon this is emulated, so slow)
#   scripts/run-qemu.sh amd64 --bios     PC version, old-style BIOS boot
#   ... --disk                           also attach a blank 24 GB disk to try the installer on
#   ... --headless                       no window; serial log, monitor socket and boot audio in out/vm/
#   ... --fresh                          start over with a blank disk (deletes the old test disk)
#   ... --share DIR                      plug a Mac folder into the VM as a read-only USB drive
#                                        (e.g. your own sound pack; keep it under 500 MB)
set -euo pipefail
cd "$(dirname "$0")/.."
ARCH="${1:?usage: run-qemu.sh <arm64|amd64> [--bios] [--disk] [--headless] [--iso FILE] [--stick] [--no-cd] [--res WxH] [--share DIR]}"; shift
BIOS=0; DISK=0; HEADLESS=0; ISO=""; CD=1; RES=""; STICK=0; SHARE=""; FRESH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bios) BIOS=1 ;; --disk) DISK=1 ;; --headless) HEADLESS=1 ;;
    --iso) ISO="$2"; shift ;;
    --stick) STICK=1 ;;              # attach the ISO as a disk, the way a USB stick shows up (faster than a CD)
    --no-cd) CD=0; DISK=1 ;;          # boot the installed disk, as if the USB stick was removed
    --res) RES="$2"; shift ;;          # screen size, e.g. 1920x1080
    --fresh) FRESH=1; DISK=1 ;;        # wipe the test disk first
    --share) SHARE="$2"; shift ;;      # a folder that shows up in the VM as a USB drive
    *) echo "unknown option $1"; exit 1 ;;
  esac; shift
done
ISO="${ISO:-$(ls -1 out/GlassOS-*-"$ARCH".iso | tail -n1)}"
[ -f "$ISO" ] || { echo "no ISO for $ARCH in out/ (run ./build.sh $ARCH)"; exit 1; }
VMD=out/vm; mkdir -p "$VMD"
[ $FRESH = 1 ] && rm -f "$VMD/disk-$ARCH.qcow2" "$VMD/vars-$ARCH.fd"
FW="$(dirname "$(command -v qemu-img)")/../share/qemu"
[ -d "$FW" ] || FW=/usr/share/qemu
HOST="$(uname -m)"

GPUOPT=""
[ -n "$RES" ] && GPUOPT=",xres=${RES%x*},yres=${RES#*x}"
# memory for the VM: 4 GB, or 3 GB when the computer itself has 8 GB or less (so it doesn't swap)
HOSTMEM_GB="$( (sysctl -n hw.memsize 2>/dev/null || awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo) | awk '{print int($1 / 1073741824)}')"
MEM=4096; [ "${HOSTMEM_GB:-16}" -le 8 ] && MEM=3072
args=(-m "$MEM" -smp 4 -name "GlassOS $ARCH")
case "$ARCH" in
  arm64)
    QEMU=qemu-system-aarch64
    if [ "$HOST" = arm64 ] || [ "$HOST" = aarch64 ]; then
      if [ "$(uname -s)" = Darwin ]; then args+=(-accel hvf -cpu host); else args+=(-accel kvm -cpu host); fi
    else args+=(-cpu max); fi
    [ -f "$VMD/vars-arm64.fd" ] || cp "$FW/edk2-arm-vars.fd" "$VMD/vars-arm64.fd"
    args+=(-machine virt,highmem=on
      -drive if=pflash,format=raw,readonly=on,file="$FW/edk2-aarch64-code.fd"
      -drive if=pflash,format=raw,file="$VMD/vars-arm64.fd"
      -device virtio-gpu-pci$GPUOPT -device qemu-xhci -device usb-kbd -device usb-tablet)
    ;;
  amd64)
    QEMU=qemu-system-x86_64
    if [ "$HOST" = x86_64 ]; then
      if [ "$(uname -s)" = Darwin ]; then args+=(-accel hvf -cpu host); else args+=(-accel kvm -cpu host); fi
    else args+=(-accel tcg,thread=multi -cpu max); fi
    args+=(-machine q35 -device virtio-vga$GPUOPT -device qemu-xhci -device usb-kbd -device usb-tablet)
    if [ $BIOS = 0 ]; then
      [ -f "$VMD/vars-amd64.fd" ] || cp "$FW/edk2-i386-vars.fd" "$VMD/vars-amd64.fd"
      args+=(-drive if=pflash,format=raw,readonly=on,file="$FW/edk2-x86_64-code.fd"
             -drive if=pflash,format=raw,file="$VMD/vars-amd64.fd")
    fi
    ;;
  *) echo "arch must be arm64 or amd64"; exit 1 ;;
esac

if [ $CD = 1 ] && [ $STICK = 1 ]; then
  args+=(-drive if=none,id=stick,format=raw,readonly=on,file="$ISO" -device virtio-blk-pci,drive=stick,bootindex=1)
elif [ $CD = 1 ]; then
  args+=(-device virtio-scsi-pci,id=scsi -drive if=none,id=cd,media=cdrom,readonly=on,file="$ISO"
         -device scsi-cd,drive=cd,bootindex=1)
fi
args+=(-nic user,model=virtio-net-pci
       -device intel-hda -device hda-output,audiodev=snd)
if [ $DISK = 1 ]; then
  [ -f "$VMD/disk-$ARCH.qcow2" ] || qemu-img create -q -f qcow2 "$VMD/disk-$ARCH.qcow2" 24G
  args+=(-drive if=none,id=hd,file="$VMD/disk-$ARCH.qcow2" -device virtio-blk-pci,drive=hd,bootindex=2)
fi
if [ -n "$SHARE" ]; then
  [ -d "$SHARE" ] || { echo "--share: $SHARE is not a folder"; exit 1; }
  args+=(-drive if=none,id=share,format=raw,readonly=on,file="fat:$(cd "$SHARE" && pwd)"
         -device usb-storage,drive=share,removable=on)
fi
if [ $HEADLESS = 1 ]; then
  rm -f "$VMD/mon-$ARCH.sock"
  rm -f "$VMD/serial-$ARCH.sock"
  args+=(-display none
         -chardev socket,id=ser0,path="$VMD/serial-$ARCH.sock",server=on,wait=off,logfile="$VMD/serial-$ARCH.log"
         -serial chardev:ser0
         -monitor unix:"$VMD/mon-$ARCH.sock",server,nowait
         -monitor unix:"$VMD/ctl-$ARCH.sock",server,nowait
         -qmp unix:"$VMD/qmp-$ARCH.sock",server,nowait
         -audiodev wav,id=snd,path="$VMD/audio-$ARCH.wav")
else
  if [ "$(uname -s)" = Darwin ]; then
    args+=(-display cocoa,show-cursor=on -audiodev coreaudio,id=snd)
  else
    args+=(-display gtk -audiodev pa,id=snd)
  fi
fi
echo "Starting $QEMU with $ISO"
exec "$QEMU" "${args[@]}"
