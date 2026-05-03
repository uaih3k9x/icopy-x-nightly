#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  tools/boot_rescue/patch_boot_rescue.sh [boot-volume]

Default boot-volume: auto-detect a mounted boot volume under /Volumes.

This patches rootfs.cpio.gz on the iCopy-X boot partition.  It installs an
initramfs init-bottom hook that writes a rootfs rescue service before the real
system starts.  On boot, the rescue service:
  - starts sshd when available
  - exposes a network-only USB Ethernet gadget at 192.168.7.2/24
    using CDC-NCM first, CDC-ECM second, g_ether last
  - tries Wi-Fi from /mnt/upan/wifi.conf when wpa_supplicant exists

The injected rootfs service installs both a systemd unit and a SysV init.d
fallback.  It does not expose mass storage by default.

It backs up boot files before writing:
  <boot-volume>/rescue-backup-YYYYMMDD-HHMMSS/

Rollback:
  cp <backup>/rootfs.cpio.gz <boot-volume>/rootfs.cpio.gz
  sync
EOF
}

die() {
    echo "patch_boot_rescue: $*" >&2
    exit 1
}

file_size() {
    stat -c %s "$1" 2>/dev/null || stat -f %z "$1"
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

resolve_boot_volume() {
    if [[ -n "${1:-}" ]]; then
        printf '%s\n' "$1"
        return 0
    fi

    for candidate in /Volumes/boot /Volumes/BOOT /Volumes/Boot \
        /Volumes/*boot* /Volumes/*Boot* /Volumes/*BOOT*; do
        if [[ -f "$candidate/rootfs.cpio.gz" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    printf '%s\n' /Volumes/boot
}

boot="$(resolve_boot_volume "${1:-}")"

[[ -d "$boot" ]] || die "boot volume not found: $boot"
[[ -f "$boot/rootfs.cpio.gz" ]] || die "missing $boot/rootfs.cpio.gz"

for tool in gzip cpio find mktemp stat; do
    command -v "$tool" >/dev/null 2>&1 || die "missing required tool: $tool"
done

stamp="$(date +%Y%m%d-%H%M%S)"
backup="$boot/rescue-backup-$stamp"
work="$(mktemp -d)"
cleanup() {
    rm -rf "$work"
}
trap cleanup EXIT

echo "[rescue] boot volume: $boot"
echo "[rescue] backup:      $backup"
mkdir -p "$backup"

for name in rootfs.cpio.gz boot.cmd boot.scr uEnv.txt; do
    if [[ -f "$boot/$name" ]]; then
        cp -p "$boot/$name" "$backup/$name"
    fi
done

echo "[rescue] extracting initramfs"
mkdir "$work/rootfs"
(
    cd "$work/rootfs"
    gzip -dc "$boot/rootfs.cpio.gz" 2>/dev/null | cpio -idmu 2>/dev/null
)

mkdir -p "$work/rootfs/scripts/init-bottom"
cat > "$work/rootfs/scripts/init-bottom/icopy-rescue" <<'HOOK'
#!/bin/sh
PREREQ="udev"

prereqs() {
    echo "$PREREQ"
}

case "$1" in
    prereqs)
        prereqs
        exit 0
        ;;
esac

ROOT="${rootmnt:-/root}"
[ -d "$ROOT" ] || exit 0

mkdir -p "$ROOT/usr/local/sbin" "$ROOT/etc/init.d" "$ROOT/etc/rc2.d" \
    "$ROOT/etc/rc3.d" "$ROOT/etc/rc4.d" "$ROOT/etc/rc5.d" "$ROOT/var/log" \
    "$ROOT/tmp" "$ROOT/etc/systemd/system/multi-user.target.wants"

cat > "$ROOT/usr/local/sbin/icopy-rescue-net.sh" <<'SCRIPT'
#!/bin/sh
PATH=/sbin:/usr/sbin:/bin:/usr/bin
LOG=/var/log/icopy-rescue-net.log
UPAN=/mnt/upan
UPAN_PARTITION=/dev/mmcblk0p4
CONF="$UPAN/wifi.conf"
USB_IP=192.168.7.2
USB_MASK=255.255.255.0
HOST_MAC=02:00:00:00:00:01
DEV_MAC=02:00:00:00:00:02

mkdir -p /var/log /tmp /var/run/wpa_supplicant
touch "$LOG" 2>/dev/null || LOG=/tmp/icopy-rescue-net.log

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)] $*" >> "$LOG"
}

cmd_exists() {
    command -v "$1" >/dev/null 2>&1
}

start_sshd() {
    log "starting ssh service"
    mkdir -p /var/run/sshd /run/sshd >> "$LOG" 2>&1 || true
    if [ -x /etc/init.d/ssh ]; then
        /etc/init.d/ssh start >> "$LOG" 2>&1 || true
    fi
    if cmd_exists service; then
        service ssh start >> "$LOG" 2>&1 || true
        service sshd start >> "$LOG" 2>&1 || true
    fi
    if cmd_exists systemctl; then
        systemctl start ssh >> "$LOG" 2>&1 || true
        systemctl start sshd >> "$LOG" 2>&1 || true
    fi
    if cmd_exists sshd && ! pgrep -x sshd >/dev/null 2>&1; then
        /usr/sbin/sshd >> "$LOG" 2>&1 || true
    fi
}

wait_for_usb_iface() {
    iface="$1"
    for n in 1 2 3 4 5; do
        [ -e "/sys/class/net/$iface" ] && return 0
        sleep 1
    done
    return 1
}

configure_usb_iface() {
    iface="$1"
    if [ -e "/sys/class/net/$iface" ]; then
        if cmd_exists ip; then
            ip link set "$iface" up >> "$LOG" 2>&1 || true
            ip addr flush dev "$iface" >> "$LOG" 2>&1 || true
            ip addr add "$USB_IP/24" dev "$iface" >> "$LOG" 2>&1 || true
        else
            ifconfig "$iface" "$USB_IP" netmask "$USB_MASK" up >> "$LOG" 2>&1 || true
        fi
        log "$iface rescue address: $USB_IP/24"
        return 0
    fi
    return 1
}

prepare_configfs_gadget() {
    G=/sys/kernel/config/usb_gadget/icopy_rescue

    cmd_exists modprobe && modprobe libcomposite >> "$LOG" 2>&1 || true

    if [ ! -d /sys/kernel/config ]; then
        mkdir -p /sys/kernel/config >> "$LOG" 2>&1 || true
    fi
    if ! grep -q ' /sys/kernel/config ' /proc/mounts 2>/dev/null; then
        mount -t configfs none /sys/kernel/config >> "$LOG" 2>&1 || true
    fi

    [ -d /sys/kernel/config/usb_gadget ] || {
        log "configfs usb_gadget is unavailable"
        return 1
    }

    UDC="$(ls /sys/class/udc 2>/dev/null | head -n 1)"
    [ -n "$UDC" ] || {
        log "no USB device controller found"
        return 1
    }

    if [ -d "$G" ]; then
        echo "" > "$G/UDC" 2>> "$LOG" || true
        rm -f "$G/configs/c.1/ncm.usb0" "$G/configs/c.1/ecm.usb0" \
            "$G/configs/c.1/rndis.usb0" 2>> "$LOG" || true
        rmdir "$G/functions/ncm.usb0" "$G/functions/ecm.usb0" \
            "$G/functions/rndis.usb0" 2>> "$LOG" || true
    fi

    return 0
}

start_usb_configfs_function() {
    kind="$1"
    label="$2"
    product="$3"
    G=/sys/kernel/config/usb_gadget/icopy_rescue
    FUNC="$kind.usb0"

    prepare_configfs_gadget || return 1

    mkdir -p "$G" "$G/strings/0x409" "$G/configs/c.1/strings/0x409" \
        "$G/functions/$FUNC" >> "$LOG" 2>&1 || {
        log "failed to create $label configfs gadget"
        return 1
    }

    echo 0x1d6b > "$G/idVendor" 2>> "$LOG" || true
    echo 0x0104 > "$G/idProduct" 2>> "$LOG" || true
    echo 0x0200 > "$G/bcdUSB" 2>> "$LOG" || true
    echo 0x0100 > "$G/bcdDevice" 2>> "$LOG" || true
    echo icopy-rescue > "$G/strings/0x409/serialnumber" 2>> "$LOG" || true
    echo "iCopy-X Rescue" > "$G/strings/0x409/manufacturer" 2>> "$LOG" || true
    echo "$product" > "$G/strings/0x409/product" 2>> "$LOG" || true
    echo 120 > "$G/configs/c.1/MaxPower" 2>> "$LOG" || true
    echo "$label" > "$G/configs/c.1/strings/0x409/configuration" 2>> "$LOG" || true
    echo "$HOST_MAC" > "$G/functions/$FUNC/host_addr" 2>> "$LOG" || true
    echo "$DEV_MAC" > "$G/functions/$FUNC/dev_addr" 2>> "$LOG" || true

    if [ ! -e "$G/configs/c.1/$FUNC" ]; then
        ln -s "$G/functions/$FUNC" "$G/configs/c.1/" >> "$LOG" 2>&1 || {
            log "failed to link $label function"
            return 1
        }
    fi

    echo "$UDC" > "$G/UDC" 2>> "$LOG" || {
        log "failed to bind $label gadget to $UDC"
        return 1
    }

    if wait_for_usb_iface usb0; then
        log "USB $label gadget bound to $UDC"
        configure_usb_iface usb0
        return 0
    fi

    log "$label gadget bound but usb0 did not appear"
    return 1
}

start_usb_ncm_configfs() {
    start_usb_configfs_function ncm "CDC NCM" "iCopy-X Rescue NCM"
}

start_usb_ecm_configfs() {
    start_usb_configfs_function ecm "CDC ECM" "iCopy-X Rescue ECM"
}

start_usb_ether_module() {
    modprobe g_ether host_addr="$HOST_MAC" dev_addr="$DEV_MAC" >> "$LOG" 2>&1 || {
        log "g_ether modprobe failed"
        return 1
    }

    if wait_for_usb_iface usb0; then
        configure_usb_iface usb0
        return 0
    fi

    log "g_ether loaded but usb0 did not appear"
    return 1
}

start_usb_ether() {
    log "starting USB Ethernet rescue"
    for mod in g_acm_ms g_mass_storage g_serial g_ether; do
        modprobe -r "$mod" >> "$LOG" 2>&1 || true
    done

    start_usb_ncm_configfs && return 0
    log "falling back to CDC ECM configfs"
    start_usb_ecm_configfs && return 0
    log "falling back to g_ether module"
    start_usb_ether_module
}

stop_usb_ether() {
    G=/sys/kernel/config/usb_gadget/icopy_rescue
    log "stopping USB Ethernet rescue"
    if [ -d "$G" ]; then
        echo "" > "$G/UDC" 2>> "$LOG" || true
    fi
    if [ -e /sys/class/net/usb0 ]; then
        if cmd_exists ip; then
            ip link set usb0 down >> "$LOG" 2>&1 || true
        else
            ifconfig usb0 down >> "$LOG" 2>&1 || true
        fi
    fi
    modprobe -r g_ether >> "$LOG" 2>&1 || true
}

get_conf_value() {
    key="$1"
    [ -f "$CONF" ] || return 1
    sed -n "s/^[[:space:]]*$key[[:space:]]*=[[:space:]]*//p" "$CONF" \
        | sed 's/[[:space:]]*$//' | tail -n 1
}

escape_wpa() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

ensure_upan_mounted() {
    [ -f "$CONF" ] && return 0
    mkdir -p "$UPAN" >> "$LOG" 2>&1 || true

    if grep -q " $UPAN " /proc/mounts 2>/dev/null; then
        return 0
    fi

    for n in 1 2 3 4 5; do
        [ -b "$UPAN_PARTITION" ] && break
        sleep 1
    done

    if [ -b "$UPAN_PARTITION" ]; then
        mount -o rw "$UPAN_PARTITION" "$UPAN" >> "$LOG" 2>&1 || true
    fi
}

select_wifi_iface() {
    conf_iface="$(get_conf_value iface || true)"
    if [ -n "$conf_iface" ] && [ -d "/sys/class/net/$conf_iface" ]; then
        echo "$conf_iface"
        return 0
    fi
    for iface in wlan0 wlx* ra0; do
        [ -d "/sys/class/net/$iface" ] && { echo "$iface"; return 0; }
    done
    for path in /sys/class/net/*; do
        [ -e "$path" ] || continue
        iface="${path##*/}"
        case "$iface" in
            lo|eth*|usb*|sit*|tun*|tap*) ;;
            *) echo "$iface"; return 0 ;;
        esac
    done
    return 1
}

run_dhcp() {
    iface="$1"
    if cmd_exists dhclient; then
        dhclient -r "$iface" >> "$LOG" 2>&1 || true
        dhclient -v -1 "$iface" >> "$LOG" 2>&1 || true
        return 0
    fi
    if cmd_exists udhcpc; then
        udhcpc -i "$iface" -n -q -t 5 >> "$LOG" 2>&1 || true
        return 0
    fi
    log "no DHCP client found"
    return 1
}

iface_has_ipv4() {
    iface="$1"
    if cmd_exists ip; then
        ip -4 addr show dev "$iface" 2>/dev/null | grep -q ' inet '
        return $?
    fi
    ifconfig "$iface" 2>/dev/null | grep -Eq 'inet addr:|inet '
}

start_wifi() {
    ensure_upan_mounted
    [ -f "$CONF" ] || { log "wifi.conf not found; skip Wi-Fi"; return 0; }
    cmd_exists wpa_supplicant || { log "wpa_supplicant not found; skip Wi-Fi"; return 0; }

    ssid="$(get_conf_value ssid || true)"
    psk="$(get_conf_value psk || true)"
    [ -n "$psk" ] || psk="$(get_conf_value password || true)"
    key_mgmt="$(get_conf_value key_mgmt || true)"
    hidden="$(get_conf_value hidden || true)"
    driver="$(get_conf_value driver || true)"
    [ -n "$driver" ] || driver="nl80211,wext"
    [ -n "$ssid" ] || { log "wifi.conf missing ssid"; return 1; }

    iface="$(select_wifi_iface || true)"
    [ -n "$iface" ] || { log "no Wi-Fi interface found"; return 1; }
    if iface_has_ipv4 "$iface"; then
        log "$iface already has IPv4; skip Wi-Fi rescue reconfiguration"
        return 0
    fi

    log "starting Wi-Fi rescue on $iface for SSID: $ssid"
    if cmd_exists ip; then
        ip link set "$iface" up >> "$LOG" 2>&1 || true
        ip addr flush dev "$iface" >> "$LOG" 2>&1 || true
    else
        ifconfig "$iface" up >> "$LOG" 2>&1 || true
    fi

    runtime_conf="/tmp/icopy-rescue-wpa-$iface.conf"
    {
        echo "ctrl_interface=/var/run/wpa_supplicant"
        echo "update_config=0"
        echo "network={"
        echo "    ssid=\"$(escape_wpa "$ssid")\""
        case "$hidden" in
            1|yes|true|on) echo "    scan_ssid=1" ;;
        esac
        if [ "$key_mgmt" = "NONE" ] || [ -z "$psk" ]; then
            echo "    key_mgmt=NONE"
        else
            echo "    psk=\"$(escape_wpa "$psk")\""
        fi
        echo "}"
    } > "$runtime_conf"
    chmod 600 "$runtime_conf" 2>/dev/null || true

    pkill -f "wpa_supplicant.*-i$iface" >> "$LOG" 2>&1 || true
    wpa_supplicant -B -i "$iface" -c "$runtime_conf" -D "$driver" \
        -f "/tmp/icopy-rescue-wpa-$iface.log" >> "$LOG" 2>&1 || {
        log "wpa_supplicant start failed with driver $driver"
        return 1
    }

    for n in 1 2 3 4 5 6 7 8 9 10; do
        sleep 2
        if cmd_exists wpa_cli; then
            wpa_cli -i "$iface" status >> "$LOG" 2>&1 || true
        fi
        if iwconfig "$iface" 2>/dev/null | grep -qv 'Not-Associated'; then
            break
        fi
    done

    run_dhcp "$iface"
    if cmd_exists ip; then
        ip addr show "$iface" >> "$LOG" 2>&1 || true
    else
        ifconfig "$iface" >> "$LOG" 2>&1 || true
    fi
}

case "${1:-start}" in
    start)
        log "iCopy rescue net starting"
        start_sshd
        start_usb_ether
        start_wifi
        start_sshd
        log "iCopy rescue net done"
        ;;
    stop)
        stop_usb_ether
        ;;
    restart|force-reload)
        stop_usb_ether
        "$0" start
        ;;
    status)
        if [ -e /sys/class/net/usb0 ]; then
            configure_usb_iface usb0
            exit 0
        fi
        exit 1
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}" >&2
        exit 2
        ;;
esac
SCRIPT
chmod 755 "$ROOT/usr/local/sbin/icopy-rescue-net.sh"

cat > "$ROOT/etc/systemd/system/icopy-rescue-net.service" <<'SCRIPT'
[Unit]
Description=iCopy-X rescue SSH network
DefaultDependencies=no
After=local-fs.target sysinit.target
Wants=local-fs.target
Before=multi-user.target icopy.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'nohup /usr/local/sbin/icopy-rescue-net.sh start >/tmp/icopy-rescue-net.out 2>&1 &'
ExecStop=/usr/local/sbin/icopy-rescue-net.sh stop
RemainAfterExit=yes
TimeoutStartSec=10

[Install]
WantedBy=multi-user.target
SCRIPT
chmod 644 "$ROOT/etc/systemd/system/icopy-rescue-net.service"
ln -sf ../icopy-rescue-net.service \
    "$ROOT/etc/systemd/system/multi-user.target.wants/icopy-rescue-net.service"

cat > "$ROOT/etc/init.d/icopy-rescue-net" <<'SCRIPT'
#!/bin/sh
### BEGIN INIT INFO
# Provides:          icopy-rescue-net
# Required-Start:    $local_fs
# Required-Stop:
# Default-Start:     2 3 4 5
# Default-Stop:
# Short-Description: iCopy rescue SSH network
### END INIT INFO

case "$1" in
    start|"")
        nohup /usr/local/sbin/icopy-rescue-net.sh start >/tmp/icopy-rescue-net.out 2>&1 &
        ;;
    stop)
        /usr/local/sbin/icopy-rescue-net.sh stop >/tmp/icopy-rescue-net.out 2>&1 || true
        ;;
    restart|force-reload)
        /usr/local/sbin/icopy-rescue-net.sh restart >/tmp/icopy-rescue-net.out 2>&1 &
        ;;
    status)
        /usr/local/sbin/icopy-rescue-net.sh status
        ;;
esac
exit 0
SCRIPT
chmod 755 "$ROOT/etc/init.d/icopy-rescue-net"

for rc in 2 3 4 5; do
    ln -sf ../init.d/icopy-rescue-net "$ROOT/etc/rc${rc}.d/S01icopy-rescue-net"
done

touch "$ROOT/etc/icopy-rescue-net.enabled"
echo "installed icopy rescue net service with systemd and SysV fallback" > "$ROOT/var/log/icopy-rescue-net-install.log" 2>/dev/null || true
exit 0
HOOK
chmod 755 "$work/rootfs/scripts/init-bottom/icopy-rescue"

if ! grep -q '/scripts/init-bottom/icopy-rescue' "$work/rootfs/scripts/init-bottom/ORDER" 2>/dev/null; then
    cat >> "$work/rootfs/scripts/init-bottom/ORDER" <<'EOF'
/scripts/init-bottom/icopy-rescue "$@"
[ -e /conf/param.conf ] && . /conf/param.conf
EOF
fi

echo "[rescue] repacking initramfs"
(
    cd "$work/rootfs"
    find . -print | LC_ALL=C sort | cpio -o --format newc -R 0:0 2>/dev/null | gzip -9 > "$work/rootfs.cpio.gz"
)

old_size="$(file_size "$boot/rootfs.cpio.gz")"
new_size="$(file_size "$work/rootfs.cpio.gz")"
echo "[rescue] rootfs.cpio.gz: $old_size -> $new_size bytes"

echo "[rescue] writing patched initramfs"
tmp_boot="$boot/rootfs.cpio.gz.rescue-new"
cp "$work/rootfs.cpio.gz" "$tmp_boot"
sync
mv "$tmp_boot" "$boot/rootfs.cpio.gz"
sync

echo "[rescue] verifying patched initramfs contains hook"
if gzip -dc "$boot/rootfs.cpio.gz" 2>/dev/null | cpio -t 2>/dev/null | grep -Eq '^(\./)?scripts/init-bottom/icopy-rescue$'; then
    echo "[rescue] hook present"
else
    die "patched initramfs verification failed"
fi

cat <<EOF
[rescue] done.

After reboot:
  USB Ethernet device IP: 192.168.7.2/24
  Set host/Mac USB Ethernet IP to: 192.168.7.1/24
  SSH: ssh root@192.168.7.2

Wi-Fi will also be attempted from:
  /mnt/upan/wifi.conf

Logs on device:
  /var/log/icopy-rescue-net.log
  /var/log/icopy-rescue-net-install.log

To temporarily free the USB gadget after SSH login:
  /usr/local/sbin/icopy-rescue-net.sh stop

Rollback:
  cp "$backup/rootfs.cpio.gz" "$boot/rootfs.cpio.gz"
  sync
EOF
