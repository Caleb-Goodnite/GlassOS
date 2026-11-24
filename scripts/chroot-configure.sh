#!/bin/bash
# Runs INSIDE the GlassOS root filesystem (chroot) during the "configure" build stage.
# Safe to run again: every step either overwrites or checks first.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
: "${GLASSOS_VERSION:?}" "${GLASSOS_CODENAME:?}" "${LIVE_USER:?}" "${LIVE_PASSWORD:?}" "${LIVE_HOSTNAME:?}"
: "${DEFAULT_SOUNDPACK:?}" "${DEBIAN_SUITE:?}" "${ARCH:?}"

say() { printf '  - %s\n' "$*"; }

say "language and region"
sed -i 's/^# *\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen
locale-gen >/dev/null
printf 'LANG=en_US.UTF-8\n' > /etc/default/locale
ln -sf /usr/share/zoneinfo/Etc/UTC /etc/localtime
echo Etc/UTC > /etc/timezone

say "identity (os-release)"
if ! dpkg-divert --list /usr/lib/os-release | grep -q glassos; then
  dpkg-divert --package glassos --divert /usr/lib/os-release.debian --rename --add /usr/lib/os-release >/dev/null
fi
DEBIAN_VERSION="$(cat /etc/debian_version)"
cat > /usr/lib/os-release <<EOF
PRETTY_NAME="GlassOS $GLASSOS_VERSION ($GLASSOS_CODENAME)"
NAME="GlassOS"
VERSION_ID="$GLASSOS_VERSION"
VERSION="$GLASSOS_VERSION ($GLASSOS_CODENAME)"
VERSION_CODENAME=$DEBIAN_SUITE
ID=glassos
ID_LIKE=debian
DEBIAN_VERSION_FULL=$DEBIAN_VERSION
LOGO=glassos
EOF
ln -sf ../usr/lib/os-release /etc/os-release
for f in /etc/issue /etc/issue.net; do
  dpkg-divert --list "$f" | grep -q glassos || dpkg-divert --package glassos --divert "$f.debian" --rename --add "$f" >/dev/null
done
printf 'GlassOS %s \\n \\l\n\n' "$GLASSOS_VERSION" > /etc/issue
printf 'GlassOS %s\n' "$GLASSOS_VERSION" > /etc/issue.net

say "hostname"
echo "$LIVE_HOSTNAME" > /etc/hostname
cat > /etc/hosts <<EOF
127.0.0.1	localhost
127.0.1.1	$LIVE_HOSTNAME
::1		localhost ip6-localhost ip6-loopback
ff02::1		ip6-allnodes
ff02::2		ip6-allrouters
EOF

say "live user '$LIVE_USER' (recreated from /etc/skel every build)"
if id "$LIVE_USER" >/dev/null 2>&1; then userdel -r "$LIVE_USER" >/dev/null 2>&1 || true; fi
groups=""
for g in sudo audio video render input netdev plugdev users; do
  getent group "$g" >/dev/null && groups="${groups:+$groups,}$g"
done
useradd -m -s /bin/bash -c "GlassOS Live" -G "$groups" "$LIVE_USER"
printf '%s:%s\n' "$LIVE_USER" "$LIVE_PASSWORD" | chpasswd
passwd -l root >/dev/null
for d in Desktop Documents Downloads Music Pictures Videos "Music/Sound Packs" Pictures/Screenshots; do
  install -d -o "$LIVE_USER" -g "$LIVE_USER" "/home/$LIVE_USER/$d"
done
# the default pack, copied where it's easy to find and use as a starting point
cp -r "/usr/share/glassos/soundpacks/$DEFAULT_SOUNDPACK" "/home/$LIVE_USER/Music/Sound Packs/GlassOS Default (copy)"
chown -R "$LIVE_USER:$LIVE_USER" "/home/$LIVE_USER"

say "admin rules (sounds, Glass Lens, camera switch)"
cat > /etc/sudoers.d/glassos-tools <<'EOF'
# Lets any admin user (group "sudo") do these things without typing a password:
#  - set the boot sound from a sound pack (the script only accepts audio files from a pack folder)
#  - list which program owns each network connection, so Glass Lens can name system services
#  - switch the camera off and on (Settings > Privacy & Security)
%sudo ALL=(root) NOPASSWD: /usr/bin/glass-soundpack set-boot-file *
%sudo ALL=(root) NOPASSWD: /usr/bin/ss -H -tunap
%sudo ALL=(root) NOPASSWD: /usr/bin/glass-privacy camera off, /usr/bin/glass-privacy camera on
EOF
chmod 0440 /etc/sudoers.d/glassos-*
visudo -cq

say "services"
systemctl enable NetworkManager.service greetd.service nftables.service glassos-boot-sound.service \
  systemd-timesyncd.service bluetooth.service >/dev/null 2>&1
# Bluetooth radio stays off until you switch it on in Settings
if [ -f /etc/bluetooth/main.conf ]; then
  sed -i -e 's/^#\?AutoEnable *=.*/AutoEnable=false/' /etc/bluetooth/main.conf
  grep -q '^AutoEnable=false' /etc/bluetooth/main.conf || printf '\n[Policy]\nAutoEnable=false\n' >> /etc/bluetooth/main.conf
fi
systemctl set-default graphical.target >/dev/null
# the login screen remembers who logged in last (just the username)
install -d -m 0755 -o _greetd -g _greetd /var/cache/glass-greeter
# the login screen needs the GPU and input devices like any desktop
for g in video render input; do getent group "$g" >/dev/null && usermod -aG "$g" _greetd; done
# "Updates only when you ask": no background downloads or installs
systemctl disable apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
cat > /etc/apt/apt.conf.d/20glassos-no-auto <<'EOF'
// GlassOS: nothing is downloaded or installed unless you ask (GlassOS menu > Software Updates).
APT::Periodic::Enable "0";
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
# the sound daemon starts with the desktop (session-start), not from a target
systemctl --global disable waybar.service mako.service hypridle.service foot-server.service >/dev/null 2>&1 || true
# a crashed graphics stack shouldn't leave you staring at a black screen: text login on tty1-6 stays
systemctl enable getty@tty1.service >/dev/null 2>&1 || true

say "trimming files nobody needs (and keeping them out on updates)"
cat > /etc/dpkg/dpkg.cfg.d/50glassos-trim <<'EOF'
# GlassOS uses one cursor and one icon theme; the variants are left out.
path-exclude=/usr/share/icons/Bibata-Modern-Amber/*
path-exclude=/usr/share/icons/Bibata-Modern-Classic/*
path-exclude=/usr/share/icons/Bibata-Original-*/*
path-exclude=/usr/share/icons/Papirus-Light/*
path-exclude=/usr/share/icons/ePapirus*/*
EOF
rm -rf /usr/share/icons/Bibata-Modern-Amber /usr/share/icons/Bibata-Modern-Classic \
       /usr/share/icons/Bibata-Original-* /usr/share/icons/Papirus-Light /usr/share/icons/ePapirus*
printf '[Icon Theme]\nInherits=Bibata-Modern-Ice\n' > /usr/share/icons/default/index.theme

say "friendly app names in the launcher, and hiding helper entries"
install -d /usr/local/share/applications
rename_app() {  # rename_app <desktop-id> <new name>
  local src="/usr/share/applications/$1" dst="/usr/local/share/applications/$1"
  [ -f "$src" ] || return 0
  sed -e "0,/^Name=.*/s//Name=$2/" -e '/^Name\[/d' "$src" > "$dst"
}
rename_app foot.desktop "Terminal"
rename_app thunar.desktop "Files"
rename_app org.xfce.mousepad.desktop "Text Editor"
rename_app imv.desktop "Image Viewer"
rename_app firefox-esr.desktop "Firefox"
for id in thunar-bulk-rename thunar-settings foot-server footclient imv-dir python3.13 python3 \
          org.freedesktop.Xwayland org.xfce.mousepad-settings pulsemixer nm-connection-editor; do
  [ -f "/usr/share/applications/$id.desktop" ] || continue
  printf '[Desktop Entry]\nType=Application\nName=%s\nExec=true\nNoDisplay=true\n' "$id" \
    > "/usr/local/share/applications/$id.desktop"
done

say "caches (schemas, fonts, icons, apps)"
# Debian keeps the schema compiler inside libglib (the -bin package isn't needed)
"$(ls /usr/lib/*/glib-2.0/glib-compile-schemas | head -n1)" /usr/share/glib-2.0/schemas
fc-cache -f >/dev/null
for t in /usr/share/icons/hicolor /usr/share/icons/Papirus /usr/share/icons/Papirus-Dark; do
  [ -d "$t" ] && gtk-update-icon-cache -qf "$t" || true
done
update-desktop-database -q /usr/share/applications /usr/local/share/applications || true

say "Flathub, for the App Store"
# Flathub's repository file (its address and signing key), kept on disk so the App Store can
# add Flathub for each user without fetching it. The App Store adds it on first use, per user.
if [ ! -s /usr/share/glassos/flathub.flatpakrepo ]; then
  curl -fsSL --retry 3 https://dl.flathub.org/repo/flathub.flatpakrepo -o /usr/share/glassos/flathub.flatpakrepo \
    || echo "warning: couldn't download flathub.flatpakrepo; the App Store will fetch it when first used"
fi

say "Firefox privacy policies"
install -d /usr/lib/firefox-esr/distribution /etc/firefox-esr/policies
install -m644 /usr/share/glassos/firefox/policies.json /usr/lib/firefox-esr/distribution/policies.json
install -m644 /usr/share/glassos/firefox/policies.json /etc/firefox-esr/policies/policies.json

say "system sound theme (so apps use the GlassOS sounds from the first boot)"
python3 - <<'EOF'
import sys
sys.path.insert(0, "/usr/lib/glassos")
import glasssound as g
n = g.build_sound_theme(None, "/usr/share/sounds/glassos")
print(f"    {n} sounds linked")
EOF

say "boot loader defaults (used by the installer)"
cat > /etc/default/grub <<'EOF'
# GlassOS boot menu settings. After changing this file run:  sudo update-grub
GRUB_DEFAULT=0
GRUB_TIMEOUT=3
GRUB_TIMEOUT_STYLE=menu
GRUB_DISTRIBUTOR="GlassOS"
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash plymouth.splash-delay=1 plymouth.ignore-serial-consoles loglevel=3 udev.log_level=3 vt.global_cursor_default=0"
GRUB_CMDLINE_LINUX=""
GRUB_GFXMODE=auto
GRUB_GFXPAYLOAD_LINUX=keep
GRUB_THEME="/boot/grub/themes/glassos/theme.txt"
# find Windows / other systems and offer them in the menu
GRUB_DISABLE_OS_PROBER=false
EOF

say "boot splash"
# ShowDelay=1 (and plymouth.splash-delay=1 on the kernel line): with no delay, the splash
# sometimes froze on its first frame on virtio-gpu and held up the boot for over a minute.
plymouth-set-default-theme glassos
cat > /etc/plymouth/plymouthd.conf <<'EOF'
[Daemon]
Theme=glassos
ShowDelay=1
DeviceTimeout=8
EOF
# simpledrm/virtio/efi framebuffers must be in the initramfs for the splash to show early
grep -q '^FRAMEBUFFER=y' /etc/initramfs-tools/conf.d/splash 2>/dev/null || \
  echo FRAMEBUFFER=y > /etc/initramfs-tools/conf.d/splash
cat > /etc/initramfs-tools/modules <<'EOF'
# GPU drivers loaded early so the boot splash and desktop come up at full resolution
virtio_gpu
EOF
update-initramfs -u -k all

say "clean up"
apt-get clean
rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /var/log/*.log /var/log/apt/* /root/.bash_history
: > /etc/machine-id
rm -f /var/lib/dbus/machine-id
echo "  configured GlassOS $GLASSOS_VERSION for $ARCH"
