# GlassOS

A Linux desktop built on Debian 13, with a frosted-glass look, a hardware monitor that shows
where your computer's resources go (Glass Lens), and system sounds you can replace with your own.

Version 0.1 is a working prototype. It boots, runs, installs to a disk, and has been tested in
virtual machines (QEMU on a Mac). It hasn't been tested on real PC hardware yet.

## What's in it

| Part | What it is |
|---|---|
| Linux kernel + GRUB | Debian's kernel (6.12 LTS), booted by GRUB with a GlassOS theme |
| Boot splash | Plymouth theme: logo, progress bar, boot sound |
| Login screen | `glass-greeter`: a GTK login screen for greetd, running in the `cage` compositor. The text login (`tuigreet`) takes over if it can't start. |
| Desktop | Hyprland (window manager), Waybar (top bar), a GlassOS dock, mako (notifications), hyprlock (lock screen) |
| GlassOS apps | Glass Lens, Settings, App Store (Flathub), Browser (WebKitGTK), Calculator, Sound Packs, Help |
| Other apps | Files (Thunar), Terminal (foot), Text Editor (Mousepad), Image Viewer (imv), Firefox ESR |
| Installer | `glass-install`: a guided terminal installer that erases one disk and installs GlassOS on it |

Every package GlassOS adds is listed with its reason in `config/packages.list`. That list is
also shown in Glass Lens > About.

## Build it

On a Mac (Apple Silicon), with Homebrew:

```bash
brew install lima qemu
```

```bash
./build.sh
```

The first build creates a small Debian VM called `glassbuild` (Lima) and builds inside it.
That build takes 15 to 25 minutes, and later builds are quicker. You get
`out/GlassOS-0.1-arm64.iso` and `out/GlassOS-0.1-amd64.iso` (the PC version).

To rebuild only what you changed:

```bash
./build.sh arm64 configure iso
```

The stages are `rootfs` (packages), `assets` (wallpapers, logo, boot art), `configure` (copies `overlay/`
into the system and sets it up), and `iso`.

On Debian or Ubuntu, `./build.sh` runs directly with sudo. The comment at the top of `build.sh`
lists the tools it needs.

## Try it in a virtual machine

```bash
scripts/run-qemu.sh arm64
```

This opens a window running the ARM build. The live session logs in by itself. The password is `glass`.

- `scripts/run-qemu.sh amd64` runs the PC build. On a Mac this is emulated, so it's slow.
- Add `--disk` to attach a blank 24 GB virtual disk you can install to. Then add `--no-cd` to boot
  the installed system, as if the USB stick had been removed.
- Add `--res 1920x1080` to set the screen size.
- Add `--fresh` to start over with a blank virtual disk.
- Add `--share <folder>` to plug a folder from your Mac into the VM as a USB drive (for example,
  your own sound pack).

`TESTING.md` walks through a full test, from the boot menu to shutting down, with a checklist.

## Install it on a computer

1. Write `out/GlassOS-0.1-amd64.iso` to a USB stick (4 GB or larger) with balenaEtcher,
   Rufus, or `dd`.
2. Turn off Secure Boot in the computer's firmware settings. GlassOS's boot loader isn't signed yet.
3. Boot from the USB stick and choose **Install GlassOS** in the boot menu.
4. The installer asks for a disk, your name, a password, and a time zone. It then shows what it
   will do and waits for you to type `ERASE`. **It erases the whole disk you choose.** Installing
   alongside Windows on the same disk isn't supported yet.
5. When it's done, remove the USB stick and restart.

## Drivers and compatibility

GlassOS uses Debian's kernel and drivers, so it supports the same hardware as Debian 13.

- **Graphics:** Intel, AMD and most virtual machines use the open-source Mesa drivers, which are included.
  NVIDIA cards fall back to the basic `nouveau` driver. The NVIDIA driver isn't included yet.
- **Wi-Fi and Bluetooth:** Intel, Realtek and some Broadcom chips need firmware files from Debian's
  `non-free-firmware` section. The common ones are included. If your Wi-Fi isn't detected, run
  `sudo apt install firmware-misc-nonfree` (or the firmware package your chip needs) over a wired connection.
- **Sound:** PipeWire, with WirePlumber.
- **Printers, scanners, phones:** not set up yet.
- **Apps:** the App Store installs apps from Flathub (Flatpak, per user, no admin password).
  Anything packaged for Debian 13 also installs with `sudo apt install <name>`.
- **Windows apps:** Steam (games, through Proton) and Bottles (other programs, through Wine) are in
  the App Store. Many programs run; ones with anti-cheat or strict copy protection usually don't.
- **ARM computers** (including the Mac VM): Flathub apps published only for Intel/AMD aren't offered.

The same guide, written for people using GlassOS, ships inside it as **GlassOS Help**
(`overlay/usr/share/glassos/help/index.html`, opened from the logo menu).

## Make your own sound pack

See `soundpacks/README.md`. A sound pack is a folder of audio files named after events
(`boot.wav`, `notification.ogg`, `error.flac`), plus an optional `pack.ini`. Import it in
Sound Packs, or copy it to `~/.local/share/glassos/soundpacks/`.

## Change the design

`DESIGN.md` records the design direction and the reason behind each visual decision. The
artwork comes from code in `scripts/make-assets.py`. The look of the GlassOS apps lives in
`overlay/usr/lib/glassos/glassui.py`.

## Folder map

| Folder | Contents |
|---|---|
| `config/` | Version and names (`glassos.conf`), package list with reasons |
| `overlay/` | Files copied into the system as-is (apps, settings, default user config) |
| `grub/`, `plymouth/` | Boot menu and boot splash themes |
| `scripts/` | Build scripts, artwork and sound generators, VM test tools |
| `soundpacks/` | The default sound pack and the sound pack guide |
| `out/` | Built ISOs, logs and VM files (not part of the source) |

## Licence

Not chosen yet. The Debian packages inside the ISO keep their own licences (see
`/usr/share/doc/<package>/copyright` in the running system).
