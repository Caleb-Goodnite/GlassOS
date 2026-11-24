GlassOS 1.0.0 "Prism" is the first release: a Linux desktop built on Debian 13 with a
frosted-glass look, Glass Lens to show where your computer's resources go, and system sounds
you can replace with your own.

## Which file do I need?

| File | For |
|---|---|
| `GlassOS-1.0.0-amd64.iso` | PCs and laptops with Intel or AMD processors (x86-64). Boots with UEFI or legacy BIOS. |
| `GlassOS-1.0.0-arm64.iso` | 64-bit ARM computers that boot with UEFI, and virtual machines on Apple Silicon Macs (tested with QEMU). |

Each ISO has a matching `.sha256` file. To check a download:

```bash
shasum -a 256 -c GlassOS-1.0.0-amd64.iso.sha256
```

## What's in it

- **Glass Lens**: who is using the processor and memory (two rings), every running app and
  service, live network connections with the program behind each one, and your hardware.
- **App Store**: browse, search and install apps from Flathub. Each app page says in plain words
  what the app can reach (the internet, your files, the camera) and lets you switch those off.
- **Privacy you can see**: an icon in the top bar whenever an app uses the camera, microphone,
  speakers or screen. Click it to quit the app or stop sharing. Settings has switches that turn
  the camera and microphone off for every app. No telemetry, no online account, no location
  service. GlassOS Help lists every connection the system makes on its own.
- **Sound packs**: every system sound comes from a folder of audio files you can swap. The default
  pack, **My Sounds**, fills any sound it doesn't have yet from the GlassOS pack.
- **Apps**: Settings, Glass Browser (WebKitGTK, third-party cookies blocked), Calculator, Help,
  Files, Terminal, Text Editor, Image Viewer and Firefox ESR.
- **Shut down safely**: Super + Alt + Backspace (Command + Option + Delete on a Mac keyboard)
  asks first and counts down from 60 seconds.
- **Installer**: choose **Install GlassOS** in the boot menu. It erases the disk you pick, so
  back up first.

## Before you install

- Turn **Secure Boot** off. GlassOS's boot loader isn't signed yet.
- It has been tested in virtual machines only (QEMU on a Mac). It hasn't been tested on real
  PC hardware yet.
- The live session's password is `glass`.

## Known problems

- NVIDIA graphics use the basic open driver; the NVIDIA driver isn't included.
- Glass Browser doesn't save passwords yet (Firefox does).
- Only GlassOS's own apps move by dragging their title bar. Other apps (Files, Terminal, App
  Store apps) move with Super + drag.
- Installing next to Windows on the same disk isn't supported yet.
- Without graphics acceleration (for example in a Mac virtual machine), GlassOS switches to
  lighter effects, and some Flathub apps are only made for Intel and AMD processors.
