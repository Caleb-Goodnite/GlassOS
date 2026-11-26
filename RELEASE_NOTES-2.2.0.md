# GlassOS 2.2.0

GlassOS 2.2.0 adds Disk Utility and fixes video, the boot sound, full screen and the pointer. It
comes in two versions: amd64 for 64-bit Intel and AMD PCs, and arm64 for ARM computers with UEFI
firmware, such as virtual machines on Apple Silicon Macs.

## What's new since 2.1.0

- **Disk Utility:** a new app that shows each disk as a bar of its partitions and free space.
  Mount, format (ext4, exFAT, FAT32, NTFS, or left empty for another system's installer), resize
  ext4 and NTFS partitions, delete partitions, make new ones in free space, and erase a disk.
  Anything in use, including the partition GlassOS runs from, can't be changed. To shrink
  GlassOS itself, start from the USB stick.
- **YouTube and other video play in Glass Browser.** It was missing the GStreamer parts for Opus,
  H.264, AAC and AV1.
- **Full screen like the Mac:** move the pointer to the top edge and the top bar comes down with
  the window's red, yellow and green buttons. Green goes back to the size the window had. Holding
  Esc also leaves full screen.
- **The boot sound plays once.** A startup sound longer than 10 seconds used to play again for a
  moment, and the login screen waited for it.
- **The pointer shows on older graphics chips** (an older ThinkPad showed none).

## Install

1. Write the ISO to a USB stick (4 GB or larger), turn off Secure Boot, and start from the stick.
2. Choose **Install GlassOS**.
3. Pick a disk, then choose **Erase the whole disk** or **Keep what's on it** (dual boot).

Computers already running GlassOS get these changes from Settings > Software Update. No reinstall
is needed.

## Files

| File | For |
|---|---|
| `GlassOS-2.2.0-amd64.iso` | 64-bit Intel and AMD PCs (UEFI and older BIOS) |
| `GlassOS-2.2.0-arm64.iso` | ARM computers and virtual machines with UEFI |

Check a download against its `.sha256` file: `shasum -a 256 -c GlassOS-2.2.0-amd64.iso.sha256`.
