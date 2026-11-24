# Window buttons, dragging and split screen: design

Date: 2026-11-24. Status: waiting for approval.

## What and why

Every window in GlassOS gets Mac-style coloured buttons and can be dragged by its title bar,
and two windows can share the screen side by side. Today only GlassOS's own apps have buttons
(close and full size, no minimize). Other apps (Files, Terminal, Firefox, App Store apps) have
none and only move with Super+drag. GlassOS is aiming for a Mac feel, so this needs to behave the
same for every app, not just ours.

## Goals

- **Every window** shows three round buttons at the left of its title bar: red closes, yellow
  minimizes, green toggles full size and back. Each shows its symbol (×, −, ⤢) on hover, like macOS.
- **Every window** moves by dragging its title bar, and full size toggles on a double-click.
- **Minimize** exists: the window leaves the screen, and clicking its app in the dock brings it back.
- **Split screen**: drag a window against the left or right screen edge and it fills that half.
  Super+← and Super+→ do the same from the keyboard. Dragging it away restores its old size.

## Non-goals

- No Mac-style full-screen *Spaces*. Green is full size, as GlassOS already does on `laptop-fixes`.
- No quarter-screen corners and no top-edge snapping in this round.
- No change to the everything search (Super+Space). It's parked until this ships.

## Anti-goals (a failure even if it "works")

- **Two title bars on one window.** An app that draws its own title bar must not also get the
  plugin's bar.
- **Buttons that look different between GlassOS apps and other apps.**
- **A Hyprland update that silently loses the bars.** If the plugin fails to load, windows must
  still work (Super+drag, keyboard shortcuts) and the build log must say why.

## Approaches considered

1. **Picked: Hyprland's official title-bar plugin, `hyprbars`, on every window.** Compiled
   during the ISO build from the `hyprland-plugins` v0.55.0 tag against Debian backports'
   `hyprland-dev` 0.55.2, an exact match for the Hyprland GlassOS ships. One uniform bar for all
   apps. Cost: extra build step, and the pin must move with every Hyprland upgrade.
2. *GlassOS apps only*: add a minimize button to `glassui.py`'s header and leave other apps as
   they are. Safe, but Files, Terminal, Firefox and store apps keep behaving differently, so it
   fails the main goal.
3. *Debian's packaged plugin* (`hyprland-plugin-hyprbars`, 0.53 in backports): built for an
   older Hyprland, so it won't load. Ruled out.

## Design

**Title bars.** `hyprbars` is loaded from `hyprland.lua` and themed to match the glass look:
- the bar is translucent and blurred, with the title centred in Inter;
- the buttons sit at the left, are about 12 px, and use the macOS colours (red `#ff5f57`,
  yellow `#febc2e`, green `#28c840`);
- when a window isn't focused, its buttons turn grey;
- a double-click on the bar toggles full size.

**Avoiding double bars.**
- `GTK_CSD=1` is removed from the session, so GTK3 apps stop drawing their own title bar and
  get the plugin's.
- GlassOS's own apps keep their header (it holds their tabs and controls) but get the
  `hyprbars:no_bar` rule. `glassui.py` swaps its close/maximize buttons for the same three
  coloured buttons, so they look identical.
- Firefox draws its own tab strip. It is set to use the system title bar
  (`browser.tabs.inTitlebar = 0`) via the existing policies, so it gets the plugin bar.
- Any other app found drawing its own bar gets a `no_bar` rule listed in `hyprland.lua` with
  the reason.

**Minimize.**
- Yellow moves the window to a hidden workspace (`special:minimized`). Windows there don't
  show on any desktop.
- The dock already lists open windows per app (`dock.py` `clients()`). Clicking an app whose
  windows are all minimized brings the most recent one back to the current desktop and
  focuses it.
- The open-app dot shows minimized windows too, dimmed.

**Full size.** Green toggles the same full-size state as GlassOS apps' maximize, so it builds
on `laptop-fixes`' "full size works like a Mac full screen" change.

**Split screen.**
- When you let go of a dragged window, if the pointer is within about 8 px of the left or
  right screen edge, the window snaps. It is resized to that half of the work area (below the
  top bar, above the dock gap) and moved there.
- The window's size before snapping is remembered. Dragging it off the edge again restores
  that size.
- Super+← and Super+→ snap the focused window. They currently move focus between windows,
  which matters little on a floating desktop, so they are taken over. Focus-by-direction
  moves to Super+Alt+arrows.

**Build.**
- `build-in-vm.sh` gets a step that installs `hyprland-dev`, `cmake`, `g++` and `pkg-config`
  in a throwaway chroot step.
- It builds `hyprbars` at the pinned tag and copies `libhyprbars.so` to
  `/usr/lib/glassos/hyprland/`.
- It then removes the build tools from the image.
- The tag and Hyprland version are recorded in `config/packages.list` with the reason.

**Docs.**
- Help, the welcome page, Glass Lens' shortcuts, `TESTING.md` and `README.md` are updated:
  the TESTING "only GlassOS apps drag by their title bar" known problem goes away, and
  snapping is added to the checklist.

## Decisions taken (correct any of these)

- **Builds on `laptop-fixes`, not `main`.** It changes the same files and adds the full-size
  behaviour green relies on. The Super-tap change already made on `main` gets carried over.
- **Buttons sit at the left**, like macOS.
- **Super+←/→ are repurposed for snapping.**

## Verification

- **Spike first, before touching the build.** In the live VM: install `hyprland-dev` and the
  build tools, compile hyprbars, `hyprctl plugin load` it, and check bars, buttons, drag,
  minimize and snap on Files, Terminal, Firefox and a GlassOS app.
- **Then the real build:** rebuild the amd64 ISO in WSL Ubuntu (from a fresh clone inside
  WSL, because the Windows clone has CRLF line endings) and run the TESTING checklist's
  window section.

## Left to the builder

- Exact bar height, padding and font size, chosen to match `glassui.py`'s header.
- How the dock keeps track of minimized windows: the window list is enough, no extra state
  file.
