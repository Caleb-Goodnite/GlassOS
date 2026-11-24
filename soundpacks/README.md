# GlassOS sound packs

Every sound GlassOS makes comes from a **sound pack**: a folder of audio files named after
events. Swap the folder and the whole system sounds different: boot chime, notifications,
errors, plugging in a USB stick, all of it.

## Make your own in 2 minutes

1. Open **Sound Packs** (or Settings > Sound > Sound packs…) and click **Create starter pack**.
   This makes `~/Music/Sound Packs/<your pack>/` with a `pack.ini` and an `EVENTS.txt` list.
   In a terminal it's: `glass-soundpack new "My Synths"`
2. Drop your sounds in, named after the events below: `boot.wav`, `notification.flac`,
   `error.ogg`… Any event you skip is filled in from the pack it `inherits` from (or stays silent).
3. Click **Import a pack folder…** and pick the folder (or `glass-soundpack install <folder>`),
   then choose it from the list (or `glass-soundpack use <id>`).

Check a pack for problems before you share it: `glass-soundpack check <folder>` lists each
sound's length and points out files whose names don't match an event.

## Folder layout

```
My Synths/
├── pack.ini
├── boot.wav
├── login.flac
├── notification.ogg
├── error.wav
└── ...
```

Formats: **WAV, FLAC, OGG/Vorbis, Opus, MP3** (`.wav .flac .ogg .oga .opus .mp3`).
Any sample rate works; 48 kHz, 16- or 24-bit is ideal. Leave a little headroom (peaks around
−1 dBFS) and trim silence at the start so sounds feel instant.

## pack.ini

```ini
[pack]
name = My Synths
author = Your Name
description = Warm analog blips
# fill in any event this pack doesn't have from another pack (by folder name)
inherits = glassos-default

[files]
# optional: keep your own file names and say which event each one is for
boot = Startup.wav
warning = Application-Warning-Notification.wav

[volume]
# optional per-event loudness, 0.0 - 1.0 (multiplied by the system sound volume)
boot = 0.9
window-open = 0.4
```

A `[files]` entry wins over a file named after the event. File names are looked up inside the
pack folder only.

## Events

When an event has no file, GlassOS tries the fallbacks in order, then the inherited pack.

| File name (any extension) | When it plays | Falls back to |
|---|---|---|
| `boot` | Computer starts (before the desktop appears) | none |
| `login` | Desktop is ready after you log in | none |
| `logout` | You log out | none |
| `shutdown` | Shut Down is chosen | none |
| `reboot` | Restart is chosen | `shutdown` |
| `lock` | Screen locks | none |
| `unlock` | Screen unlocks | none |
| `notification` | An app shows a notification | none |
| `notification-low` | A low-priority notification | `notification` |
| `notification-critical` | An urgent notification | `error`, `notification` |
| `error` | Something went wrong (error dialogs, the terminal bell) | none |
| `warning` | Something needs attention | `error` |
| `device-added` | USB device plugged in | none |
| `device-removed` | USB device unplugged | none |
| `power-plugged` | Charger connected | `device-added` |
| `power-unplugged` | Charger disconnected | `device-removed` |
| `battery-low` | Battery at 15% | `warning` |
| `battery-critical` | Battery at 5% | `battery-low`, `warning` |
| `network-connected` | Connected to a network | none |
| `network-disconnected` | Lost the network connection | none |
| `window-open` | A window opens | none |
| `window-close` | A window closes | none |
| `workspace` | You switch desktops (workspaces) | none |
| `launcher` | App search opens (Super+Space) | none |
| `screenshot` | A screenshot is taken | none |
| `volume` | Volume changes (plays at the new level) | none |
| `service-failed` | A background service crashes | `error` |
| `disk-full` | Your disk is almost full | `warning` |

### Notes on specific sounds

* **boot** plays before the login screen, straight to the sound card, so it works even on
  the live USB. Keep it under about 4 seconds. Choosing a pack copies its boot sound to
  `/var/lib/glassos/sounds/` (that's the one admin step, and it only accepts audio files).
  Turn it off with `sudo touch /etc/glassos/no-boot-sound`.
* **shutdown / reboot / logout** are waited for (up to a few seconds) before the computer acts,
  so they're never cut off. Keep them short.
* **window-open, window-close, workspace, launcher, volume** happen a lot. Subtle and quiet works
  best (try a `[volume]` of 0.3 - 0.5).
* **notification-critical** is used for urgent alerts like "battery almost empty".

## Where things live

| What | Where |
|---|---|
| Packs that come with GlassOS | `/usr/share/glassos/soundpacks/` |
| Your packs | `~/.local/share/glassos/soundpacks/` |
| Which pack, volume, mutes | `~/.config/glassos/sounds.conf` |
| Boot sound in use | `/var/lib/glassos/sounds/` |

Apps that use the standard freedesktop sound theme (GTK apps, libcanberra) also play your pack:
GlassOS publishes the active pack as the sound theme `glassos`.

## Command line

```
glass-soundpack list                 # packs and which one is active
glass-soundpack use <id>             # switch packs (also sets the boot sound)
glass-soundpack test [<id>]          # play every event in turn
glass-sound <event>                  # play one event, e.g. glass-sound error
glass-soundpack volume 0.6           # system sound volume
glass-soundpack mute window-open     # silence one event (unmute to undo)
glass-soundpack off | on             # all system sounds
```
