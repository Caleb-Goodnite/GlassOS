# Window Buttons, Dragging and Split Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every window gets Mac-style red, yellow and green buttons and a draggable title bar.
Yellow minimizes to the dock, and dragging a window to a screen edge (or Super+←/→) snaps it to
half the screen.

**Architecture:**
- The `hyprbars` Hyprland plugin is compiled in the ISO build (stage `rootfs`) against Debian
  backports' `hyprland-dev` 0.55.2.
- It is loaded and themed from `hyprland.lua`, which also holds the minimize and snap logic in
  Lua.
- GlassOS's own GTK4 apps keep their header with matching buttons from `glassui.py`.
- The dock restores minimized windows.

**Tech Stack:** Hyprland 0.55 Lua config, hyprbars v0.55.0 (C++/CMake), Python 3 + GTK4
(`glassui.py`, `dock.py`), bash (`build-in-vm.sh`).

**Spec:** `docs/superpowers/specs/2026-11-24-window-buttons-design.md`

## Global Constraints

- **Plugin source:** `https://github.com/hyprwm/hyprland-plugins`, tag `v0.55.0`, subdir
  `hyprbars`. Built against `hyprland-dev` from `trixie-backports` (0.55.2).
- **Plugin location:** `/usr/lib/glassos/hyprland/libhyprbars.so`. Build tools are removed from
  the image after building.
- **Button colours:** red `#ff5f57`, yellow `#febc2e`, green `#28c840`. Unfocused windows get grey
  buttons. Buttons sit at the left, with the symbols × − ⤢ shown on hover.
- **Minimize target:** `special:minimized`.
- **Snapping:** triggers when the pointer is within 8 px of the left/right edge on release. The
  half covers the work area (below the top bar).
- **Keys:** Super+←/→ snap. Focus-by-direction moves to Super+Alt+arrows.
- **Base branch:** `laptop-fixes`. New branch `window-buttons`, carrying the Super-tap change from
  the `main` working tree.
- **Line endings:** build from a clone made inside WSL. Never build from the Windows clone
  (it has CRLF).

## Review Focus

- **Plugin fails to load** (version mismatch). Windows must still open and move with Super+drag;
  `hyprctl plugin list` shows why. Covered by Task 2 step 4.
- **Double bars.** A GlassOS app, Firefox or a GTK3 app shows two title bars. Covered by Task 3
  step 5 (check each named app).
- **Minimized window lost.** An app minimized and then closed from the dock's right-click must
  not leave a ghost. A window minimized on desktop 2 restores onto the current desktop.
  Covered by Task 4 step 4.
- **Snapping a window larger than half the screen.** It shrinks to exactly half. Dragging it off
  the edge restores its old size, not the half size. Covered by Task 5 step 3.
- **Super tap vs Super+drag.** Moving a window with Super+drag must not open the app search on
  release. Covered by Task 3 step 5.

---

### Task 1: Spike in the live VM (throwaway, no commit)

Proves the plugin builds and loads against the shipped Hyprland before any build-system work.

- [ ] **Step 1:** In the running VM's Terminal:
  `sudo apt-get update && sudo apt-get install -y -t trixie-backports hyprland-dev && sudo apt-get install -y cmake g++ pkg-config git`.
  Expected: it installs without held packages.
- [ ] **Step 2:** Run
  `git clone --depth 1 -b v0.55.0 https://github.com/hyprwm/hyprland-plugins /tmp/hp && cmake -S /tmp/hp/hyprbars -B /tmp/hb && cmake --build /tmp/hb -j4`.
  Expected: `/tmp/hb/libhyprbars.so` exists.
- [ ] **Step 3:** Run `hyprctl plugin load /tmp/hb/libhyprbars.so`, then `hyprctl plugin list`.
  Expected: `hyprbars` is listed and Files and Terminal show a bar.
- [ ] **Step 4:** Paste Task 3's config block into the live `~/.config/hypr/hyprland.lua`.
  Check that the coloured buttons close, minimize and toggle full size.
  - If the build or load fails, **stop** and bring the error to the user. Approach 1 is not
    viable as pinned.

### Task 2: Compile hyprbars in the ISO build

**Files:**
- Modify: `scripts/build-in-vm.sh` (end of `stage_rootfs`, before `apt-get clean`)
- Modify: `config/packages.list` (add the build-only note and the pin)

**Interfaces:** Produces `/usr/lib/glassos/hyprland/libhyprbars.so` inside the rootfs.

- [ ] **Step 1:** Add `build_hyprbars()` to `build-in-vm.sh`, called from `stage_rootfs` after the
  backports install. It does the following in the chroot:
  1. Install `hyprland-dev` (`-t $DEBIAN_SUITE-backports`) plus `cmake g++ pkg-config git`.
  2. Clone the pinned tag into `/tmp/hp`.
  3. Run cmake and build.
  4. `install -Dm644` the `.so` to `/usr/lib/glassos/hyprland/libhyprbars.so`.
  5. `apt-get purge -y --auto-remove` the build packages, then `rm -rf /tmp/hp`.
  6. Fail the build with a clear `log` line if the `.so` is missing.
- [ ] **Step 2:** In `packages.list`, add a comment block naming the pin, `v0.55.0`, and why
  (it must match Hyprland 0.55.2 exactly).
- [ ] **Step 3:** In WSL: `sudo bash scripts/build-in-vm.sh amd64 rootfs`.
  Expected: it ends without error, and `ls rootfs-amd64/usr/lib/glassos/hyprland/` shows
  `libhyprbars.so`. Then `chroot … dpkg -l cmake` shows it isn't installed.
- [ ] **Step 4:** Verify the plugin-failure path. Temporarily point the config at a missing path
  and boot. Expected: the desktop still loads, and Super+drag still moves windows.
- [ ] **Step 5:** Commit with the message `build: compile hyprbars title-bar plugin for Hyprland 0.55`.

### Task 3: Title bars and buttons on every window

**Files:**
- Modify: `overlay/etc/skel/.config/hypr/hyprland.lua`. Remove `hl.env("GTK_CSD", "1")`, and add
  the plugin load, theme, buttons and `no_bar` rules near the decoration section.
- Modify: `overlay/usr/share/glassos/firefox/policies.json`. Add the `browser.tabs.inTitlebar = 0`
  preference.
- Modify: `overlay/usr/lib/glassos/glassui.py`. Replace the header's close/maximize with three
  round buttons (same colours, hover symbols) at the left, plus minimize.

**Interfaces:**
- Produces the Lua function `minimize(w)`: moves window `w` to `special:minimized`. It is also
  used by the yellow button via `hyprctl dispatch`.
- Produces `glassui.traffic_lights(win) -> Gtk.Box`.

- [ ] **Step 1:** Load the plugin from `hyprland.lua`:
  `hl.plugin.load("/usr/lib/glassos/hyprland/libhyprbars.so")`. If this API is missing, use
  `exec-once hyprctl plugin load …`.
- [ ] **Step 2:** Configure the bar with `hl.config({ plugin = { hyprbars = { … } } })`:
  - `bar_buttons_alignment = "left"`, `bar_text_align = "center"`, `bar_text_font = "Inter"`;
  - `bar_blur = true`, `bar_part_of_window = true`, `icon_on_hover = true`;
  - `on_double_click` toggles full size.

  Add three `hl.plugin.hyprbars.add_button` calls (red close, yellow minimize, green full size)
  with the Global Constraints colours. Size and height should match `glassui.py`'s header.
- [ ] **Step 3:** Add a window rule `hyprbars:no_bar` for GlassOS app classes. Take the class
  names from `glassui.py`'s application IDs.
- [ ] **Step 4:** Build `traffic_lights(win)`. Its buttons call `win.close()`, the minimize
  dispatch for this window's address, and maximize/unmaximize. Use it in place of the old
  header buttons.
- [ ] **Step 5:** Verify live in the VM (copy the files over as earlier):
  - Files, Terminal, Mousepad, Firefox and a store app each show exactly one bar with three
    working buttons and drag by the bar.
  - Settings and Glass Lens show the identical buttons.
  - Super+drag then releasing Super does **not** open the app search.
- [ ] **Step 6:** Commit with the message `feat: Mac-style window buttons on every window`.

### Task 4: Minimize and restore from the dock

**Files:** Modify `overlay/usr/lib/glassos/dock/dock.py` (`on_click` around line 264, and dot
drawing).

**Interfaces:** Consumes `clients()` (each window's `workspace.name`; minimized windows have
`special:minimized`).

- [ ] **Step 1:** Add `restore_window(address: str) -> None`. It runs `hyprctl dispatch` to move
  the window to the active workspace (`e+0`), then calls `focus_window(address)`.
- [ ] **Step 2:** In `on_click`, if every window of the app is minimized, restore the most
  recently focused one (lowest `focusHistoryID`).
- [ ] **Step 3:** Draw the open-app dot dimmed (CSS class `minimized`) when all of the app's
  windows are minimized.
- [ ] **Step 4:** Verify in the VM:
  1. Minimize Files: it disappears and the dot dims.
  2. Click Files in the dock: it returns, focused.
  3. Minimize it on desktop 2, switch to desktop 1 and click it: it appears on desktop 1.
  4. Minimize it, then use the dock's right-click Close: no entry is left behind.
- [ ] **Step 5:** Commit with the message `feat(dock): restore minimized windows`.

### Task 5: Split screen by edge drag and Super+←/→

**Files:** Modify `overlay/etc/skel/.config/hypr/hyprland.lua`. Extend `laptop-fixes`'
`mouse:272` release handler and the arrow binds.

**Interfaces:** Consumes `keep_on_screen(w)` and the work-area logic from `laptop-fixes`.
Produces `snap(w, side)`, where `side` is `"left"` or `"right"`, and `unsnap(w)`.

- [ ] **Step 1:** `snap(w, side)` records the window's pre-snap size and position by address in a
  Lua table. It then resizes and moves the window exactly to that half of the work area.
  `unsnap(w)` restores the record and clears it.
- [ ] **Step 2:** In the release handler:
  - If the pointer is within 8 px of the left or right edge of the work area, call `snap`.
  - Otherwise, if the window was snapped and has moved, call `unsnap`, keeping the pointer's
    relative position.
  - Bind Super+←/→ to `snap` and Super+Alt+arrows to the old focus binds.
- [ ] **Step 3:** Verify in the VM:
  1. Drag Firefox, which is wider than half the screen, to the left edge: it fills exactly the
     left half, below the top bar.
  2. Drag it away: its old size returns.
  3. Super+→ on Files: right half.
  4. Super+Alt+← moves focus.
- [ ] **Step 4:** Commit with the message `feat: snap windows to half the screen`.

### Task 6: Docs, then a full ISO build and the checklist

**Files:**
- Modify the help and welcome pages: `overlay/usr/share/glassos/help/index.html` and
  `overlay/usr/share/glassos/welcome/index.html`.
- Modify `overlay/usr/lib/glassos/lens/lens.py` (shortcuts list), `TESTING.md` (window checklist
  and Known problems) and `README.md`.

- [ ] **Step 1:** Document in all of them:
  - the buttons;
  - minimize-to-dock;
  - edge snapping and Super+←/→;
  - Super+Alt+arrows for focus.

  Remove TESTING's "Only GlassOS's own apps move by dragging their title bar" known problem.
- [ ] **Step 2:** In a WSL clone of the `window-buttons` branch, run `./build.sh amd64`.
  Expected: `out/GlassOS-1.0.0-amd64.iso` exists.
- [ ] **Step 3:** Boot the ISO with `scripts/run-qemu.ps1 -Iso <wsl path>`. Run TESTING's Desktop
  section and Review Focus items 1–5.
- [ ] **Step 4:** Commit with the message `docs: window buttons, minimize and snapping`.
