# How GlassOS updates work

Settings > Software Update installs two kinds of updates together, only when you click
**Update Now**:

- **Debian's**: security fixes, new Linux kernels, drivers, Hyprland's libraries and every other
  package GlassOS is built on. They come from Debian's own servers, as before.
- **GlassOS's own**: the desktop, apps, artwork, sounds and settings, all in one package,
  `glassos-desktop`. It comes from GlassOS's update repository on GitHub Pages:
  `https://caleb-goodnite.github.io/GlassOS/apt`.

## From a merged PR to everyone's computer

1. A PR is merged into `main`.
2. GitHub Actions (`.github/workflows/updates.yml`) builds `glassos-desktop` for amd64 and arm64
   (`scripts/make-deb.sh`), numbered `1:<build>+<release>` (`scripts/version.sh`), e.g. `1:142+1.5.0`: build 142 of GlassOS 1.5.0. Its description
   lists the latest changes, which Settings shows as "What's new".
3. It signs the repository with the GlassOS key and publishes it to the `gh-pages` branch
   (`scripts/publish-repo.sh`). GitHub Pages serves it.
4. On each computer, **Check for Updates** finds the new version, and **Update Now** installs it.
   The package's install script runs `/usr/lib/glassos/configure-system` (services, app names,
   caches, boot splash...), the same script the ISO build runs.
5. At the next login, `config-sync` brings each person's own copies of the settings files in
   `/etc/skel` (top bar, Hyprland, notifications...) up to date:
   - an untouched file is replaced;
   - an edited one gets the update merged in;
   - a clash is left alone and noted in `~/.local/state/glassos/config-sync.log`.

New packages added to `config/packages.list` arrive with the update too: `glassos-desktop`
depends on everything in the list.

## Channels

| channel  | gets                                 | how to publish                           |
|----------|--------------------------------------|------------------------------------------|
| `dev`    | every merge to `main` (test builds)  | merge a PR                               |
| `stable` | releases only                        | `git tag v1.1.0 && git push --tags`      |

The ISO picks the channel from `UPDATE_CHANNEL` in `config/glassos.conf` (currently `dev`). On an
installed computer it's set by `channel = dev` in `/etc/glassos/updates.conf` (then
`sudo /usr/lib/glassos/configure-system`). Switch the default to `stable` before handing GlassOS
to people who aren't testing it.

## One-time setup

1. `scripts/make-signing-key.sh`: makes the signing key, stores the private half as the
   `APT_SIGNING_KEY` repository secret, and writes the public half to
   `overlay/usr/share/keyrings/glassos-archive-keyring.gpg` (commit it). Keep the backup it leaves
   in your home folder somewhere safe, like a password manager, then delete the file.
2. Merge. The first workflow run creates the `gh-pages` branch.
3. GitHub > Settings > Pages: **Deploy from a branch**, `gh-pages`, `/ (root)`.
4. Build one ISO with the key in it and install it. From then on, updates arrive through
   Settings, with no ISO needed.

## Things to know

- **Build numbers decide what's newer**, not the release name, so every merge is an update even
  if a branch bumps the release. ISOs must be built with `./build.sh` (it counts the build on the
  Mac, where git is). Bump `GLASSOS_VERSION` through a PR to `main`, not only on a local branch,
  or ISOs and updates disagree about the release name.

- **Hyprland is held** (`apt-mark hold`) at the version the title-bar plugin (hyprbars) was
  compiled for, because a newer Hyprland would refuse the plugin. Moving Hyprland means rebuilding
  the plugin, which today only the ISO build does.
- **Settings files in `/etc`** that you edited are kept (`--force-confold`); unedited ones are
  replaced.
- **Computers (and VMs) set up before updates existed** have no GlassOS key, update source or
  pkexec. One command turns updates on, then Settings > Software Update does the rest:

  ```
  curl -fsSL https://caleb-goodnite.github.io/GlassOS/setup.sh | sudo bash
  ```

  (`... | sudo bash -s stable` for the stable channel.) It's `scripts/updates-setup.sh`, published
  with every update.
- **The live USB** can install updates, which is handy for testing, but they're gone at the next
  boot.

## Testing an update before merging

In the VM (`scripts/run-qemu.sh arm64`), with a throwaway key:

1. Build two versions with `scripts/make-deb.sh` and publish them with `scripts/publish-repo.sh`
   to a folder served by `python3 -m http.server`.
2. Point `UPDATE_URL` in `config/glassos.conf` at that folder, then use Settings > Software Update.
