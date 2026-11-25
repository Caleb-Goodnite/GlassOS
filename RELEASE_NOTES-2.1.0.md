# GlassOS 2.1.0

GlassOS 2.1.0 adds dual boot. It comes in two versions: amd64 for 64-bit Intel and AMD PCs, and
arm64 for ARM computers with UEFI firmware, such as virtual machines on Apple Silicon Macs.

## What's new since 2.0.0

- **Dual boot:** the installer can keep Windows or another Linux system and install GlassOS next
  to it. It goes into free space of 12 GB or more, or into a partition you pick. The boot menu
  then offers both systems. With Windows on the disk, the clock is read in local time, as Windows
  does, so neither system shows the wrong time.
- **No room yet?** The installer explains how to shrink Windows (Disk Management > Shrink Volume)
  and stops without changing anything.

## Install

1. Write the ISO to a USB stick (4 GB or larger), turn off Secure Boot, and start from the stick.
2. Choose **Install GlassOS**.
3. Pick a disk, then choose **Erase the whole disk** or **Keep what's on it** (dual boot).
4. If Windows uses BitLocker, have its recovery key ready before installing next to it.

Computers already running GlassOS get these changes from Settings > Software Update. No reinstall
is needed.

## Files

| File | For |
|---|---|
| `GlassOS-2.1.0-amd64.iso` | 64-bit Intel and AMD PCs (UEFI and older BIOS) |
| `GlassOS-2.1.0-arm64.iso` | ARM computers and virtual machines with UEFI |

Check a download against its `.sha256` file: `shasum -a 256 -c GlassOS-2.1.0-amd64.iso.sha256`.
