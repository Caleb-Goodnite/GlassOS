# GlassOS 2.0.0

GlassOS 2.0.0 is the PC desktop release, built for 64-bit Intel and AMD computers (amd64).
The desktop has now been installed and confirmed working on desktop hardware.

## What's new since 1.5.0

- **Software updates:** older installations can set up the signed GlassOS update source with a
  single command. Settings can also handle systems where `pkexec` is not installed yet.
- **More dependable updates:** GlassOS package versions increase with each build, so installed
  systems can recognize newer GlassOS updates reliably.
- **Desktop controls:** choose a Windows, macOS, Linux, or GlassOS keyboard shortcut set and
  customize individual actions. Brightness controls also work on external displays without a
  hardware backlight; the dock stays compact, windows can be closed consistently, and the Wi-Fi
  indicator remains visible.
- **Desktop polish:** refined dock and icon theme options, split-screen snapping, and rounded menus.
- **More reliable installation:** the installer can use the boot-menu theme from the USB stick,
  checks that GlassOS files and login settings were installed, and keeps its error visible if a
  step fails.
- **Cleaner startup:** the login screen appears directly after the splash, with one startup sound.
  Login configuration now avoids a black screen if the temporary live-session account is gone.
- **Fixed window interaction:** releasing the mouse after dragging no longer triggers a Hyprland
  Lua error.

## Install

Write `GlassOS-2.0.0-amd64.iso` to a USB stick (4 GB or larger), turn off Secure Boot, boot the
stick, and choose **Install GlassOS**. The installer erases the selected disk. The live session
password is `glass`.

## Verify the download

The release includes `GlassOS-2.0.0-amd64.iso.sha256`. After downloading both files, verify the
ISO with:

```sh
shasum -a 256 -c GlassOS-2.0.0-amd64.iso.sha256
```
