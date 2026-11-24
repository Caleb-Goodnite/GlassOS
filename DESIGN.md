# GlassOS design direction

This file records what GlassOS should look and sound like, and why. Read it before you change
any GlassOS screen. The anti-slop rules (github.com/miqdadbadjuber/anti-slop) are applied on top
of it as a filter.

## Design read

A desktop operating system for everyday people who want to see what their computer is doing.
Visual language: layered frosted glass over a colourful wallpaper. Dials: **ENERGY 2 / RHYTHM 1 / MOTION 2**.

- ENERGY 2: the wallpaper and glass give it presence, but the apps stay quiet so content leads.
- RHYTHM 1: system screens are uniform on purpose. Settings pages and Glass Lens pages share
  one layout (title, one-line explanation, cards), so people always know where to look.
- MOTION 2: windows fade and slide when they open and close, and pages crossfade. That motion
  shows where a window came from. Nothing loops or moves on its own.

## Owner direction (kept on purpose)

- **Glass on every surface (rule R-10 override).** The anti-slop rules limit glass blur to one or
  two elements. The owner asked for an OS-wide Liquid-Glass-like look, where stacking windows
  frosts the view more with each layer. That is the identity, so it stays.
- **Dark glass by default (R-21).** White text needs dark-tinted glass to stay readable over a
  colourful wallpaper. There is no light theme yet. If one is added it has to cover every app, the
  top bar, the dock and notifications, not just some of them.

## Decisions and their reasons

| Decision | Reason |
|---|---|
| One Glass slider, Clear to Frosted, instead of separate Frost and Tint | Modelled on macOS Golden Gate's Liquid Glass slider (owner asked to refine the glass after it). Clear: light blur (size 3), tint 0.28, vibrancy 0.75, so shapes and colour behind stay visible. Frosted: heavy grainy blur (size 10, three passes), a milky slate tint at 0.72. One control moves blur, tint and grain together, so the two can't be set to a combination that looks muddy. |
| Default glass 35: tint 0.43, blur size 5, two passes, brightness 0.67, vibrancy 0.59 | The same tint and blur as before the slider (owner asked for slightly glassier earlier), so white text stays above 5:1 over a white web page. Vibrancy is higher, and now reaches the dark parts of the wallpaper too, so the glass keeps more colour. Toward Clear, a soft shadow behind text keeps it readable. |
| Glass edges: bright top rim, fainter bottom rim, darker band just inside | Golden Gate's "darkened edge and brighter specular highlights". Light hits the top edge and comes back out at the bottom; the dark inner band separates the pane from what's behind. Window borders do the same with a gradient that is bright top-left, dim along the sides and lit again bottom-right. Used on windows, the bar, the dock, cards, buttons and switches. |
| One accent, #6aa8ff blue (changeable in Settings) | Only on primary buttons, switches that are on, and focus rings, so the next action stands out. |
| Purple tint on private browser windows | A state marker you can see from across the room: this window keeps no history. |
| Category colours in Glass Lens (apps, desktop, system, kernel) | Data colours that tell the four kinds of usage apart in the rings. |
| Rings (donut charts) for processor and memory in Glass Lens | The owner asked for a pie chart like a task manager. A ring shows each share of the whole at a glance and leaves the centre for the one number people look for; it eases over a third of a second so a change reads as movement, not a jump. |
| No CPU or RAM numbers in the top bar | The owner asked for them to go: always-on numbers are noise, and Glass Lens shows where the hardware goes when you ask. |
| Top bar privacy icons: green camera, orange microphone, blue screen, white speaker | Only appear while something is in use, so their appearance is the signal; one colour per device so you can tell which from across the room, and pointing at it names the app. |
| App Store tiles all the same size | Catalogue entries are peers, so equal tiles make the list quick to scan; the app's own icon gives each one its character. |
| "What it can reach" in plain words, risky items in amber | People decide whether to trust an app on this, so it uses everyday words ("All your files") and marks the few permissions that break the sandbox. |
| Power dialog with a 60-second countdown and Cancel focused | Shutting down by accident loses work; one keystroke (Enter, Esc) or a click outside backs out. |
| Lighter effects when there's no graphics acceleration | Blur and shadows drawn by the processor make every frame slow; one lighter blur pass keeps the glass look and the desktop responsive. |
| Inter for interface text | Built for small on-screen sizes, has tabular figures for live numbers and the clock, and its OFL licence allows shipping it. |
| JetBrains Mono only for process and package names | Those are identifiers people may type or search for, and they line up in columns. |
| Pill buttons, rounded cards (16px), rounded fields (12px) | Radius sets the hierarchy: things you press are pills, containers are cards. |
| Dim text at 85% white, never lower | Keeps secondary text above WCAG AA contrast over bright parts of the wallpaper. |
| Ribbon wallpapers ("Prism", "Tide", "Ember") | Glass only reads as glass when colour and edges sit behind it to soften. |
| No outer drop shadow on the top bar or dock | Hyprland blurs and darkens everything above 5% alpha behind them, so a soft shadow becomes a hard dark box. The blur alone lifts them off the wallpaper. |
| Click to focus | Like a Mac: moving the pointer across windows doesn't change which one you're typing in. Scrolling still reaches whatever is under the pointer. |
| App names in the top bar come from each app's launcher | App Store apps read "Tux Paint", not "org.tuxpaint.Tuxpaint". |
| Windows can't leave the screen | Owner asked. A window whose title bar is under the top bar can't be grabbed, so letting go of a window slides it back inside the screen, below the top bar. |
| Maximize hides the top bar and dock | Owner asked for the Mac's full screen: the window gets every pixel, and keeps its title bar so the same button shrinks it back. |
| Dock size Small / Medium / Large, Medium by default (36 px icons) | Owner found the 46 px dock too big. |
| Squircle window corners (radius 20, rounding power 4) | The curve eases in instead of starting abruptly like a circle's, which reads as more finished. GTK can only draw circular corners, so cards and buttons inside apps stay circular. |
| Glass Lens refreshes every two-thirds of a second | Owner's pick: 1 s felt slow, half a second too busy. Sensors that wake hardware or start programs refresh every 8 to 10 seconds. |

## Writing

- Say what the system does, in a way people can check ("the connectivity check is off in
  NetworkManager"). Don't write slogans or promises ("nothing ever leaves your device").
- No em dashes. Plain words. No "seamless", "powerful" or "effortless".
- A button says what it does: "Choose a sound pack", not "Learn more".

## Placeholders still to confirm

- **Logo and app icons.** These were drawn from code without a brief from the owner. Treat them as
  placeholders until the owner approves or supplies a mark (`scripts/make-assets.py`). The Settings
  gear replaced a stock icon the owner read as a chess pawn; the App Store icon is an arrow into a tray.
- **Default sounds.** These are synthesized stand-ins. The owner's own synth pack replaces them
  (see `soundpacks/README.md`).
