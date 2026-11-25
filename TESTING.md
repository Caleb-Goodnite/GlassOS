# Testing GlassOS yourself

Two ways to run it: in a window on this Mac (safe, nothing on the Mac changes), or on a real PC
from a USB stick. Start with the Mac window.

## On this Mac, in a window

Open Terminal in this folder and run:

```bash
scripts/run-qemu.sh arm64 --fresh
```

That starts GlassOS as if you'd plugged in the USB stick and pressed the power button, with an
empty 24 GB virtual disk to install onto. `--fresh` wipes that virtual disk first, so leave it
out if you want to keep what you installed last time.

After you've installed, start it again **without the USB stick**:

```bash
scripts/run-qemu.sh arm64 --no-cd
```

To test **your own sounds**, put them in a folder and add `--share` with that folder. It shows
up inside GlassOS as a USB drive (read-only), and plugging it in plays the device-added sound:

```bash
scripts/run-qemu.sh arm64 --no-cd --share ~/Music/MySynths
```

### Keyboard and mouse in the window

- The mouse works straight away. Click inside the window to type into GlassOS.
- **Super** (the key used in GlassOS shortcuts) is the **Command** key.
- The Mac may keep some Command shortcuts for itself. Command+Q, for one, can quit the whole
  virtual machine. If a shortcut doesn't reach GlassOS, press **Control+Option+G** to send all
  keys to the window, and press it again to get your Mac keyboard back. You can also do
  everything with the mouse: the dock at the bottom, and the GlassOS logo in the top-left corner.
- Sound plays through your Mac's speakers.
- To stop, shut down from GlassOS (the logo menu, or Command+Option+Delete), or close the window.

The PC version also runs on this Mac (`scripts/run-qemu.sh amd64 --fresh`), but the Mac has to
imitate an Intel processor, so it's 5 to 10 times slower. Use it to check that it starts, not
to judge speed.

## On a real PC

1. Write `out/GlassOS-2.0.0-amd64.iso` to a USB stick (4 GB or larger) with balenaEtcher.
2. Turn off Secure Boot in the PC's firmware settings.
3. Start the PC from the stick and pick **Try GlassOS**. Try mode runs from the stick and doesn't
   touch the PC's disks, so it's the safe way to check Wi-Fi, sound and graphics.
4. **Install GlassOS** either erases the whole disk you choose, or (option 2) keeps what's on it
   and installs next to it in free space, for dual boot. To test dual boot, shrink Windows first
   (Disk Management > Shrink Volume, 30 GB or more), then check that the boot menu starts both.

The PC version hasn't been tested on real hardware yet, so this is where you'll find the most.

## Checklist

Tick these off as you go. Anything that looks wrong, write down what you did just before it.
Screenshots: press Print (or Super+Shift+S for an area). They go to Pictures > Screenshots.

### Power on and boot menu
- [ ] The boot menu shows the GlassOS logo, Try and Install choices, and counts down
- [ ] Arrow keys move the highlight; Enter starts the highlighted choice
- [ ] The boot animation (logo and progress) shows, and the boot sound plays

### Live session (from the USB stick)
- [ ] The desktop appears without asking for a password
- [ ] Glass Lens opens with "Welcome to GlassOS"
- [ ] Picking **Install GlassOS** in the boot menu opens the installer by itself

### Installer
- [ ] It lists the disk, asks your name, username, password (twice), computer name, time zone
- [ ] The summary says exactly what will be erased, and nothing happens until you type ERASE
- [ ] Typing anything other than ERASE cancels and changes nothing
- [ ] Copying finishes and it offers to restart

### First start from the disk
- [ ] The boot menu now says GlassOS and starts by itself after 3 seconds
- [ ] The login screen shows your name, the date and time, Restart and Shut Down
- [ ] A wrong password shows "Wrong password. Try again."
- [ ] The right password logs you in, with the login sound
- [ ] The welcome page opens on the first login only

### Desktop
- [ ] Top bar: logo menu, app name, network, volume, clock. No CPU or RAM numbers, and no dark
  boxes around the pills.
- [ ] Pointing at a window doesn't switch to it; clicking does (scrolling works without clicking)
- [ ] Play a video in the browser: a white speaker icon appears top-right; pointing at it names the app
- [ ] Dock: every icon opens its app; a dot shows under open apps
- [ ] Tapping Super on its own searches apps; typing part of a name and pressing Enter opens it
- [ ] Drag the title bar of a GlassOS app (Settings, Lens, Store, Calculator, Browser) to move it;
      drag any window's edge or corner to resize it
- [ ] Super+drag moves a window from anywhere; Super+right-drag resizes it
- [ ] Every window fits on the screen when it opens, including Glass Lens and Settings
- [ ] Drag a window (title bar or Super+drag) past an edge or under the top bar and let go: it slides back
      fully on screen, below the top bar
- [ ] The maximize button (or double-clicking a title bar) fills the whole screen and hides the top bar and
      dock; pressing it again puts the window back where it was
- [ ] Settings > Appearance > Dock size changes the dock straight away
- [ ] Super+1 to Super+9 switch desktops
- [ ] Notifications appear top-right with a sound (try `notify-send "Test" "Hello"` in Terminal)

### Apps
- [ ] **Calculator**: buttons and keyboard both work, results are right, C clears
- [ ] **Glass Browser**: loads websites, back and forward work, a private window is tinted purple
- [ ] **Settings**: every page opens; Appearance changes the wallpaper and frost straight away
  (a new tint shows in apps you open after changing it)
- [ ] **Settings > Appearance > Effects**: Lighter turns off the shadows and lightens the blur at once
- [ ] **Settings > Privacy & Security**: "Right now" lists what's using the speakers, with Quit app;
  switching the microphone off mutes it (the volume menu shows it muted)
- [ ] **App Store**: Popular loads with icons, two or three to a row; search and every category load
  their own apps; an app's page shows screenshots, "What it can reach" and the download size
- [ ] **App Store**: Install shows progress, then Open starts the app; it also appears in the app search,
  the top bar shows its real name (e.g. "Tux Paint") and the dock shows its icon
- [ ] **App Store > Installed**: lists it; switching "The internet" off on its page stops it going online;
  Remove takes it away
- [ ] **GlassOS Help** (logo menu): opens in Glass Browser, and every topic link jumps to its section
- [ ] **Files**, **Terminal**, **Text Editor**, **Image Viewer**, **Firefox** open and work

### Glass Lens (where the hardware goes)
- [ ] Overview numbers move and roughly match `top` in Terminal
- [ ] Click through every page a few times, then check `top` in Terminal: Glass Lens stays at a few percent
- [ ] The processor and memory rings split into apps, desktop, system and kernel, and ease when they change
- [ ] Apps & Services lists every open app by its real name with a plain-English reason
- [ ] Closing an app removes it from the list
- [ ] Network & Privacy names the program behind each connection
- [ ] About lists every added package with the reason it's there

### Sound packs (your synths)
- [ ] The image starts with **My Sounds**: your Startup.wav plays at boot, and your warning sound
  plays for warnings (everything else comes from the GlassOS pack)
- [ ] Sounds page: each event plays when you click it
- [ ] **Create starter pack**, put your files in it, **Import a pack folder…**, then choose it
- [ ] Your sounds play for login, notifications, errors, plugging in the shared folder, lock, shut down
- [ ] Missing sounds fall back to the default pack (or stay silent)
- [ ] The boot sound changes to yours on the next start

### Glass look
- [ ] One window over the wallpaper: lightly frosted, white text easy to read
- [ ] Two or three windows stacked: each layer looks frostier and darker
- [ ] A GlassOS window over a white web page: text still easy to read
- [ ] Lock screen (Super+L) and unlock with your password

### Privacy facts you can check
- [ ] No connections at rest: Glass Lens > Network & Privacy shows none until you open the browser
- [ ] No automatic updates: `systemctl list-timers` shows no apt-daily timers
- [ ] Connectivity check off: `cat /etc/NetworkManager/conf.d/*` (Settings says why)
- [ ] Firefox: about:policies lists the GlassOS privacy policies

### Shut down
- [ ] Super+Alt+Backspace (Command+Option+Delete on a Mac) opens a dialog that counts down from 60
- [ ] Cancel, Esc, and a click outside the dialog each close it, and nothing happens
- [ ] Shut Down plays the shutdown sound and powers off

## Known problems

- NVIDIA graphics use the basic open driver; the NVIDIA driver isn't included.
- Glass Browser doesn't save passwords yet (Firefox does).
- In the Mac virtual machine there's no graphics acceleration, so effects are lighter and some
  Flathub apps aren't offered (they're only made for Intel and AMD processors).
- Installing next to Windows on the same disk isn't supported yet.
- Only GlassOS's own apps move by dragging their title bar. Other apps (Files, Terminal, App
  Store apps) move with Super + drag: the window manager, Hyprland, ignores the "move me"
  request apps send, and Files and Terminal have no title bar to drag.
- In a virtual machine, a window that opens right under a still pointer may ignore the first
  click until the pointer moves a little.
