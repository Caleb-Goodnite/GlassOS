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
# the GlassOS pack, copied where it's easy to find and use as a starting point
cp -r /usr/share/glassos/soundpacks/glassos-default "/home/$LIVE_USER/Music/Sound Packs/GlassOS Default (copy)"
chown -R "$LIVE_USER:$LIVE_USER" "/home/$LIVE_USER"

say "Flathub, for the App Store"
# Flathub's repository file (its address and signing key), kept on disk so the App Store can
# add Flathub for each user without fetching it. The App Store adds it on first use, per user.
if [ ! -s /usr/share/glassos/flathub.flatpakrepo ]; then
  curl -fsSL --retry 3 https://dl.flathub.org/repo/flathub.flatpakrepo -o /usr/share/glassos/flathub.flatpakrepo \
    || echo "warning: couldn't download flathub.flatpakrepo; the App Store will fetch it when first used"
fi

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

say "GlassOS system settings (the same script every update runs)"
GLASSOS_BUILD=1 /usr/lib/glassos/configure-system

say "boot splash into the initramfs"
update-initramfs -u -k all

say "clean up"
apt-get clean
rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /var/log/*.log /var/log/apt/* /root/.bash_history
: > /etc/machine-id
rm -f /var/lib/dbus/machine-id
echo "  configured GlassOS $GLASSOS_VERSION for $ARCH"
