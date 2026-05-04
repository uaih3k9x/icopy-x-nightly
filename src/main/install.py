##########################################################################
# Required Notice: Copyright ETOILE401 SAS (http://www.lab401.com)
#
# Initial author: ETOILE401 SAS & https://github.com/quantum-x/ as of April 16, 2026
#
# Since this date, each contribution is under the copyright of its respective author.
#
# Copyright of each contribution is tracked by the Git history. See the output of git shortlog -nse for a full list or git log --pretty=short --follow <path/to/sourcefile> |git shortlog -ne to track a specific file.
#
# A mailmap is maintained to map author and committer names and email addresses to canonical names and email addresses.
# If by accident a copyright was removed from a file and is not directly deducible from the Git history, please submit a PR.
#
#
# This software is licensed under the PolyForm Noncommercial License 1.0.0.
# You may not use this software for commercial purposes.
#
# A copy of the license is available at:
# https://polyformproject.org/licenses/noncommercial/1.0.0
#
# This entire header "Required Notice" must remain in place.
##########################################################################

"""IPK installer — OSS replacement for install.so.

Cython source: install.py (compiled to install.so by manufacturer)
Binary source: device_so/install.so (98,188 bytes, ARM ELF)
Ground truth: Ghidra analysis + QEMU trace (2026-04-09)

Original functions confirmed via QEMU ExtensionFileLoader:
  install_font(unpkg_path, callback)
  install_lua_dep(unpkg_path, callback)
  update_permission(unpkg_path, callback)
  install_app(unpkg_path, callback)
  restart_app(callback)
  install(unpkg_path, callback)

The callback signature is: callback(name: str, progress: int)
Progress values observed: 30, 38, 60, 100.

Chinese log messages preserved for parity with original .so output:
  "检查字体的安装..." = Checking font installation
  "正在更新所有的权限..." = Updating all permissions
  "更新权限成功！！！" = Permissions updated
  "目录已经存在，不自动解压" = Directory exists, skip extract
  "正在重启" = Restarting
"""

import os
import shlex
import shutil
import time
import zipfile


_RESCUE_SCRIPT = '/usr/local/sbin/icopy-rescue-net.sh'
_RESCUE_UNIT = '/etc/systemd/system/icopy-rescue-net.service'
_RESCUE_UNIT_LINK = (
    '/etc/systemd/system/multi-user.target.wants/icopy-rescue-net.service'
)
_RESCUE_INIT = '/etc/init.d/icopy-rescue-net'
_RESCUE_ENABLED = '/etc/icopy-rescue-net.enabled'
_RESCUE_INSTALL_LOG = '/var/log/icopy-rescue-net-install.log'


def install_font(unpkg_path, callback):
    """Copy fonts from the IPK to the system font directory.

    Looks for fonts in {unpkg_path}/res/font/, copies new ones to
    /usr/share/fonts/truetype/ (or the device's font path).

    Args:
        unpkg_path: path to extracted IPK
        callback: progress callback(name, progress)
    """
    print("Installing assets...")

    source_font_path = os.path.join(unpkg_path, 'res', 'font')
    target_font_path = '/usr/share/fonts'

    if not os.path.isdir(source_font_path):
        # No fonts in this IPK — not an error
        return

    new_fonts = os.listdir(source_font_path)
    if not new_fonts:
        return

    os.makedirs(target_font_path, exist_ok=True)

    # Fonts that should not be installed (preserved from original)
    font_no_install_list = []

    old_fonts = set(os.listdir(target_font_path)) if os.path.isdir(target_font_path) else set()

    for new_font in new_fonts:
        if new_font in font_no_install_list:
            continue

        source_font_file = os.path.join(source_font_path, new_font)
        if not os.path.isfile(source_font_file):
            continue

        font_install = os.path.join(target_font_path, new_font)
        print(" Font will install...")
        if callback:
            callback('Installing assets...', 30)
        shutil.copy(source_font_file, font_install)

    print("Assets installed.")
    if callback:
        callback('Assets installed.', 100)


def install_lua_dep(unpkg_path, callback):
    """Install LUA scripts and libraries from lua.zip.

    Searches for lua.zip in two locations:
      1. {unpkg_path}/pm3/lua.zip  — bundled inside the IPK
      2. /mnt/upan/lua.zip         — standalone on USB drive (legacy)

    Extracts to /mnt/upan/ (creates luascripts/ and lualibs/ there).
    This keeps scripts user-editable on the USB partition and avoids
    permission issues.  Only extracts if the directories don't already
    exist — preserves user modifications across reinstalls.

    Then creates symlinks in the app directory ({unpkg_path}/):
      {unpkg_path}/luascripts -> /mnt/upan/luascripts
      {unpkg_path}/lualibs    -> /mnt/upan/lualibs

    This makes both PM3 firmwares find the scripts:
      - Factory PM3: searches /mnt/upan/ directly
      - Iceman PM3:  searches CWD-relative luascripts/ (follows symlink)

    Args:
        unpkg_path: path to extracted IPK
        callback: progress callback(name, progress)
    """
    # Find lua.zip — prefer IPK-bundled, fall back to USB drive
    path_lua_zip = os.path.join(unpkg_path, 'pm3', 'lua.zip')
    if not os.path.isfile(path_lua_zip):
        path_lua_zip = os.path.join('/mnt/upan/', 'lua.zip')
    if not os.path.isfile(path_lua_zip):
        # lua.zip is optional — not shipped with every update
        return

    # Extract to /mnt/upan/ — wipe existing dirs first to prevent
    # mixed Lua versions (factory 5.1 libs + iceman 5.4 = crashes).
    upan_luascripts = '/mnt/upan/luascripts'
    upan_lualibs = '/mnt/upan/lualibs'

    if True:  # Always extract when lua.zip is present in the IPK
        for dirname in (upan_luascripts, upan_lualibs):
            if os.path.isdir(dirname):
                shutil.rmtree(dirname)
        print("Installing tools...")
        if callback:
            callback('Installing tools...', 30)
        try:
            with zipfile.ZipFile(path_lua_zip, 'r') as zf:
                zf.extractall('/mnt/upan/')
        except Exception:
            print("lua.zip extract failed")
            return

    # Create symlinks so both PM3 firmwares find the scripts.
    #
    # Iceman PM3 searches (from `script list`):
    #   ~/.proxmark3/luascripts/
    #   <app>/share/proxmark3/luascripts/   (relative to pm3 binary)
    #
    # Factory PM3 searches /mnt/upan/ directly.
    #
    # CWD-relative lualibs/ is needed for Lua require() paths.
    #
    # All symlinks point to /mnt/upan/ so scripts stay user-editable.
    symlinks = [
        # Iceman script search path: <app>/share/proxmark3/luascripts
        (os.path.join(unpkg_path, 'share', 'proxmark3', 'luascripts'),
         '/mnt/upan/luascripts'),
        # Iceman lualibs search path
        (os.path.join(unpkg_path, 'share', 'proxmark3', 'lualibs'),
         '/mnt/upan/lualibs'),
        # CWD-relative fallback (lualibs for require())
        (os.path.join(unpkg_path, 'luascripts'),
         '/mnt/upan/luascripts'),
        (os.path.join(unpkg_path, 'lualibs'),
         '/mnt/upan/lualibs'),
    ]
    for link_path, target in symlinks:
        try:
            parent = os.path.dirname(link_path)
            if not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.islink(link_path) or os.path.exists(link_path):
                os.remove(link_path)
            os.symlink(target, link_path)
        except Exception:
            pass

    print("Tools installed.")
    if callback:
        callback('Tools installed.', 100)


def update_permission(unpkg_path, callback):
    """Set permissions on the install target directory.

    Runs chmod 777 -R on /home/pi/ipk_app_new (the staged install dir).
    Also patches known OS-level bugs that affect stability.

    Args:
        unpkg_path: path to extracted IPK (used to derive target)
        callback: progress callback(name, progress)
    """
    print("Updating permissions...")
    if callback:
        callback('Updating permissions...', 30)

    target_path = os.path.join('/home/pi/', 'ipk_app_new')
    os.system('chmod 777 -R %s' % target_path)

    # Patch known OS-level stability bugs.
    _patch_gpio_crash_bug()
    _patch_sshd_session_limits()
    _install_rescue_net_service(enable=True, restart=False, backup=True)

    # Remove trojan version.so — it's only needed for checkPkg during
    # install.  At runtime it shadows our version.py (Python loads .so
    # before .py), returning stale hardcoded values instead of dynamic ones.
    _trojan_so = os.path.join(target_path, 'lib', 'version.so')
    if os.path.isfile(_trojan_so):
        os.remove(_trojan_so)
        print("Removed trojan version.so (checkPkg complete, no longer needed)")

    if callback:
        callback('Permissions updated.', 100)
    print("Permissions updated.")


def _patch_gpio_crash_bug():
    """Disable gen-friendlyelec-release to prevent kernel GPIO crash.

    Kernel 4.14.111 (sun8i) has a NULL pointer dereference in
    gpiodevice_release() triggered by /usr/local/bin/gen-friendlyelec-release.
    This binary runs on every boot (rc.local) and every SSH login (10-header).
    Under memory pressure + concurrent SSH sessions, it crashes the kernel.

    Fix: comment out the binary invocation. The static /etc/friendlyelec-release
    file it generates already exists and doesn't need regeneration.
    """
    _files = ['/etc/rc.local', '/etc/update-motd.d/10-header']
    _target = '/usr/local/bin/gen-friendlyelec-release'

    for path in _files:
        try:
            if not os.path.isfile(path):
                continue
            with open(path, 'r') as f:
                content = f.read()
            if _target in content and ('# disabled' not in content or
                                       content.count(_target) > content.count('# disabled')):
                patched = content.replace(
                    _target,
                    '# disabled: GPIO crash # ' + _target)
                with open(path, 'w') as f:
                    f.write(patched)
                print("Patched %s (GPIO crash fix)" % path)
            else:
                print("Already patched: %s" % path)
        except Exception as e:
            print("Could not patch %s: %s" % (path, e))


def _patch_sshd_session_limits():
    """Add SSH session limits to prevent OOM from session buildup.

    The iCopy-X's reverse SSH tunnel reconnects aggressively, spawning
    10-30+ sshd processes that never die. On a 237MB RAM device, this
    exhausts memory in ~30 minutes, triggering OOM killer (takes out the
    app) or kernel crash.

    Fix: add keepalive + session limits to sshd_config.
    - ClientAliveInterval 15: detect dead sessions in 15s
    - ClientAliveCountMax 2: kill after 2 missed keepalives (30s total)
    - MaxSessions 4: hard limit per connection
    - LoginGraceTime 15: reject slow/stale auth attempts faster
    """
    _sshd_conf = '/etc/ssh/sshd_config'
    _marker = '# OSS session limit patch'
    _settings = {
        'ClientAliveInterval': '15',
        'ClientAliveCountMax': '2',
        'MaxSessions': '4',
        'LoginGraceTime': '15',
    }

    try:
        if not os.path.isfile(_sshd_conf):
            print("sshd_config not found, skipping SSH patch")
            return

        with open(_sshd_conf, 'r') as f:
            content = f.read()

        if _marker in content:
            print("Already patched: %s" % _sshd_conf)
            return

        lines = content.rstrip('\n').split('\n')

        # Comment out any existing conflicting settings
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                key = stripped.split()[0] if stripped.split() else ''
                if key in _settings:
                    lines[i] = '# ' + line

        # Append our settings
        lines.append('')
        lines.append(_marker)
        for key, val in _settings.items():
            lines.append('%s %s' % (key, val))

        with open(_sshd_conf, 'w') as f:
            f.write('\n'.join(lines) + '\n')

        # Restart sshd to apply (won't kill existing connections)
        os.system('systemctl restart sshd 2>/dev/null')
        print("Patched %s (SSH session limits)" % _sshd_conf)

    except Exception as e:
        print("Could not patch sshd_config: %s" % e)


def _write_file(path, content, mode=None):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    if mode is not None:
        os.chmod(path, mode)


def _backup_existing(path):
    if not os.path.exists(path):
        return ''
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = '%s.bak-%s' % (path, stamp)
    try:
        shutil.copy2(path, backup)
        return backup
    except Exception as e:
        print("Could not back up %s: %s" % (path, e))
        return ''


def _link_or_copy_unit():
    try:
        parent = os.path.dirname(_RESCUE_UNIT_LINK)
        os.makedirs(parent, exist_ok=True)
        if os.path.lexists(_RESCUE_UNIT_LINK):
            os.remove(_RESCUE_UNIT_LINK)
        os.symlink('../icopy-rescue-net.service', _RESCUE_UNIT_LINK)
        return
    except Exception as e:
        print("Could not symlink rescue unit: %s" % e)

    try:
        shutil.copy2(_RESCUE_UNIT, _RESCUE_UNIT_LINK)
    except Exception as e:
        print("Could not copy rescue unit link fallback: %s" % e)


def _install_rescue_net_service(enable=True, restart=True, backup=True):
    """Install the default USB SSH rescue network service.

    This is intentionally app-installer side, not plugin-only.  SSH is already
    enabled on target devices; this service provides the first clean network
    path over USB-C so users do not need OTG Wi-Fi just to reach SSH.
    """
    try:
        for path in (_RESCUE_SCRIPT, _RESCUE_UNIT, _RESCUE_INIT):
            if backup:
                _backup_existing(path)

        _write_file(_RESCUE_SCRIPT, _rescue_net_script(), 0o755)
        _write_file(_RESCUE_UNIT, _rescue_net_systemd_unit(), 0o644)
        _write_file(_RESCUE_INIT, _rescue_net_init_script(), 0o755)

        for rc in ('2', '3', '4', '5'):
            link_path = '/etc/rc%s.d/S01icopy-rescue-net' % rc
            try:
                os.makedirs(os.path.dirname(link_path), exist_ok=True)
                if os.path.lexists(link_path):
                    os.remove(link_path)
                os.symlink('../init.d/icopy-rescue-net', link_path)
            except Exception as e:
                print("Could not create %s: %s" % (link_path, e))

        if enable:
            _write_file(_RESCUE_ENABLED, '1\n', 0o644)
            _link_or_copy_unit()
        elif os.path.exists(_RESCUE_ENABLED):
            os.remove(_RESCUE_ENABLED)

        _write_file(
            _RESCUE_INSTALL_LOG,
            'installed iCopy USB SSH rescue service %s\n' % (
                time.strftime('%Y-%m-%d %H:%M:%S')),
            0o644,
        )

        if restart:
            _schedule_rescue_net_restart(delay=2)
        print("Installed USB SSH rescue service")
        return True
    except Exception as e:
        print("Could not install USB SSH rescue service: %s" % e)
        return False


def _schedule_rescue_net_restart(delay=2):
    unit_name = 'icopy-rescue-net-restart-%s-%s' % (
        os.getpid(), int(time.time()))
    script_path = '/tmp/%s.sh' % unit_name
    script = (
        '#!/bin/sh\n'
        'PATH=/sbin:/usr/sbin:/bin:/usr/bin\n'
        'LOG=/tmp/icopy-rescue-net-restart.log\n'
        'exec >>"$LOG" 2>&1\n'
        'echo "[restart] scheduled $(date)"\n'
        'sleep %d\n'
        'if [ -x %s ]; then\n'
        '    echo "[restart] restarting rescue net"\n'
        '    %s restart\n'
        'else\n'
        '    echo "[restart] missing rescue script"\n'
        'fi\n'
    ) % (
        delay,
        shlex.quote(_RESCUE_SCRIPT),
        shlex.quote(_RESCUE_SCRIPT),
    )
    try:
        _write_file(script_path, script, 0o755)
    except Exception as e:
        print("Could not write rescue restart script: %s" % e)
        return

    for cmd in (
        'sudo systemd-run --unit=%s --collect /bin/sh %s' % (
            unit_name, script_path),
        'sudo systemd-run --unit=%s /bin/sh %s' % (unit_name, script_path),
    ):
        try:
            if os.system(cmd + ' >/tmp/icopy-rescue-net-schedule.log 2>&1') == 0:
                print("Scheduled USB SSH restart via systemd-run")
                return
        except Exception:
            pass

    try:
        os.system(
            'nohup sudo /bin/sh %s >/tmp/icopy-rescue-net-schedule.log 2>&1 &'
            % script_path)
        print("Scheduled USB SSH restart via nohup")
    except Exception as e:
        print("Could not schedule USB SSH restart: %s" % e)


def _rescue_net_systemd_unit():
    return (
        '[Unit]\n'
        'Description=iCopy-X USB SSH rescue network\n'
        'DefaultDependencies=no\n'
        'After=local-fs.target sysinit.target\n'
        'Wants=local-fs.target\n'
        'Before=multi-user.target icopy.service\n'
        '\n'
        '[Service]\n'
        'Type=oneshot\n'
        'ExecStart=/bin/sh -c \'nohup /usr/local/sbin/icopy-rescue-net.sh '
        'start >/tmp/icopy-rescue-net.out 2>&1 &\'\n'
        'ExecStop=/usr/local/sbin/icopy-rescue-net.sh stop\n'
        'RemainAfterExit=yes\n'
        'TimeoutStartSec=10\n'
        '\n'
        '[Install]\n'
        'WantedBy=multi-user.target\n'
    )


def _rescue_net_init_script():
    return (
        '#!/bin/sh\n'
        '### BEGIN INIT INFO\n'
        '# Provides:          icopy-rescue-net\n'
        '# Required-Start:    $local_fs\n'
        '# Required-Stop:\n'
        '# Default-Start:     2 3 4 5\n'
        '# Default-Stop:\n'
        '# Short-Description: iCopy USB SSH rescue network\n'
        '### END INIT INFO\n'
        '\n'
        'case "$1" in\n'
        '    start|"")\n'
        '        nohup /usr/local/sbin/icopy-rescue-net.sh start '
        '>/tmp/icopy-rescue-net.out 2>&1 &\n'
        '        ;;\n'
        '    stop)\n'
        '        /usr/local/sbin/icopy-rescue-net.sh stop '
        '>/tmp/icopy-rescue-net.out 2>&1 || true\n'
        '        ;;\n'
        '    restart|force-reload)\n'
        '        /usr/local/sbin/icopy-rescue-net.sh restart '
        '>/tmp/icopy-rescue-net.out 2>&1 &\n'
        '        ;;\n'
        '    status)\n'
        '        /usr/local/sbin/icopy-rescue-net.sh status\n'
        '        ;;\n'
        'esac\n'
        'exit 0\n'
    )


def _rescue_net_script():
    return r'''#!/bin/sh
PATH=/sbin:/usr/sbin:/bin:/usr/bin
LOG=/var/log/icopy-rescue-net.log
STATE=/tmp/icopy-rescue-net.state
ENABLED=/etc/icopy-rescue-net.enabled
UPAN=/mnt/upan
UPAN_PARTITION=/dev/mmcblk0p4
CONF="$UPAN/wifi.conf"
USB_IP=192.168.7.2
USB_CIDR=192.168.7.2/24
USB_LL_CIDR=169.254.7.2/16
USB_MASK=255.255.255.0
HOST_IP=192.168.7.1
HOST_MAC=02:00:00:00:00:01
DEV_MAC=02:00:00:00:00:02
G=/sys/kernel/config/usb_gadget/icopy_rescue

mkdir -p /var/log /tmp /var/run/wpa_supplicant
touch "$LOG" 2>/dev/null || LOG=/tmp/icopy-rescue-net.log

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)] $*" >> "$LOG"
}

state() {
    echo "$*" > "$STATE" 2>/dev/null || true
    log "$*"
}

cmd_exists() {
    command -v "$1" >/dev/null 2>&1
}

is_enabled() {
    [ -e "$ENABLED" ]
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

addr_present() {
    iface="$1"
    cidr="$2"
    if cmd_exists ip; then
        ip addr show dev "$iface" 2>/dev/null | grep -q " $cidr"
    else
        return 1
    fi
}

configure_usb_iface() {
    iface="$1"
    if [ ! -e "/sys/class/net/$iface" ]; then
        return 1
    fi

    if cmd_exists ip; then
        ip link set "$iface" up >> "$LOG" 2>&1 || true
        ip addr flush dev "$iface" >> "$LOG" 2>&1 || true
        ip addr add "$USB_CIDR" dev "$iface" >> "$LOG" 2>&1 || true
        addr_present "$iface" "$USB_LL_CIDR" || \
            ip addr add "$USB_LL_CIDR" dev "$iface" >> "$LOG" 2>&1 || true
    else
        ifconfig "$iface" "$USB_IP" netmask "$USB_MASK" up >> "$LOG" 2>&1 || true
    fi
    log "$iface rescue address: $USB_CIDR + $USB_LL_CIDR"
    return 0
}

prepare_configfs_gadget() {
    cmd_exists modprobe && modprobe libcomposite >> "$LOG" 2>&1 || true

    if [ ! -d /sys/kernel/config ]; then
        mkdir -p /sys/kernel/config >> "$LOG" 2>&1 || true
    fi
    if ! grep -q ' /sys/kernel/config ' /proc/mounts 2>/dev/null; then
        mount -t configfs none /sys/kernel/config >> "$LOG" 2>&1 || true
    fi

    [ -d /sys/kernel/config/usb_gadget ] || {
        state "configfs usb_gadget unavailable"
        return 1
    }

    UDC="$(ls /sys/class/udc 2>/dev/null | head -n 1)"
    [ -n "$UDC" ] || {
        state "no USB device controller found"
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
    FUNC="$kind.usb0"

    prepare_configfs_gadget || return 1

    mkdir -p "$G" "$G/strings/0x409" "$G/configs/c.1/strings/0x409" \
        "$G/functions/$FUNC" >> "$LOG" 2>&1 || {
        state "failed to create $label configfs gadget"
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
            state "failed to link $label function"
            return 1
        }
    fi

    echo "$UDC" > "$G/UDC" 2>> "$LOG" || {
        state "failed to bind $label gadget to $UDC"
        return 1
    }

    if wait_for_usb_iface usb0; then
        configure_usb_iface usb0
        state "USB $label active on $UDC"
        return 0
    fi

    state "$label gadget bound but usb0 did not appear"
    return 1
}

start_usb_ncm_configfs() {
    start_usb_configfs_function ncm "CDC NCM" "iCopy-X Rescue NCM"
}

start_usb_ecm_configfs() {
    start_usb_configfs_function ecm "CDC ECM" "iCopy-X Rescue ECM"
}

start_usb_ether_module() {
    cmd_exists modprobe || return 1
    modprobe g_ether host_addr="$HOST_MAC" dev_addr="$DEV_MAC" >> "$LOG" 2>&1 || {
        state "g_ether modprobe failed"
        return 1
    }

    if wait_for_usb_iface usb0; then
        configure_usb_iface usb0
        state "USB g_ether active"
        return 0
    fi

    state "g_ether loaded but usb0 did not appear"
    return 1
}

start_usb_ether() {
    state "starting USB SSH rescue"
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
    log "stopping USB SSH rescue"
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
    state "USB SSH rescue stopped"
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

write_wpa_conf() {
    iface="$1"
    ssid="$(get_conf_value ssid || true)"
    psk="$(get_conf_value psk || true)"
    key_mgmt="$(get_conf_value key_mgmt || true)"
    hidden="$(get_conf_value hidden || true)"
    wpa_conf="/tmp/icopy-rescue-wpa-$iface.conf"

    [ -n "$ssid" ] || return 1

    {
        echo "ctrl_interface=/var/run/wpa_supplicant"
        echo "network={"
        echo "    ssid=\"$(escape_wpa "$ssid")\""
        if [ "$key_mgmt" = "NONE" ]; then
            echo "    key_mgmt=NONE"
        else
            echo "    psk=\"$(escape_wpa "$psk")\""
        fi
        [ "$hidden" = "1" ] && echo "    scan_ssid=1"
        echo "}"
    } > "$wpa_conf"
    chmod 600 "$wpa_conf" 2>/dev/null || true
    echo "$wpa_conf"
}

run_dhcp() {
    iface="$1"
    if cmd_exists dhclient; then
        dhclient -r "$iface" >> "$LOG" 2>&1 || true
        dhclient -v -1 "$iface" >> "$LOG" 2>&1 || true
    elif cmd_exists udhcpc; then
        udhcpc -i "$iface" -n -q -t 5 >> "$LOG" 2>&1 || true
    fi
}

start_wifi() {
    ensure_upan_mounted
    [ -f "$CONF" ] || return 0
    cmd_exists wpa_supplicant || {
        log "wifi.conf present but wpa_supplicant missing"
        return 0
    }

    iface="$(select_wifi_iface || true)"
    [ -n "$iface" ] || {
        log "wifi.conf present but no wireless iface found"
        return 0
    }

    wpa_conf="$(write_wpa_conf "$iface" || true)"
    [ -n "$wpa_conf" ] || {
        log "wifi.conf missing ssid"
        return 0
    }

    driver="$(get_conf_value driver || true)"
    [ -n "$driver" ] || driver=nl80211,wext
    ip link set "$iface" up >> "$LOG" 2>&1 || true
    pkill -f "wpa_supplicant.*-i $iface" >> "$LOG" 2>&1 || true
    wpa_supplicant -B -i "$iface" -c "$wpa_conf" -D "$driver" \
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

print_status() {
    echo "enabled=$([ -e "$ENABLED" ] && echo yes || echo no)"
    echo "state=$(cat "$STATE" 2>/dev/null || echo unknown)"
    if [ -e /sys/class/net/usb0 ]; then
        echo "usb0=present"
        if cmd_exists ip; then
            ip -o -4 addr show dev usb0 2>/dev/null || true
        else
            ifconfig usb0 2>/dev/null || true
        fi
        for f in operstate carrier address; do
            p="/sys/class/net/usb0/$f"
            [ -e "$p" ] && printf "%s=" "$f" && cat "$p"
        done
    else
        echo "usb0=missing"
    fi
    if [ -e "$G/UDC" ]; then
        printf "UDC="
        cat "$G/UDC"
    fi
    if [ -d "$G/functions" ]; then
        printf "functions="
        ls "$G/functions" 2>/dev/null | tr '\n' ' '
        echo
    fi
}

case "${1:-start}" in
    start)
        if ! is_enabled; then
            state "USB SSH rescue disabled"
            exit 0
        fi
        log "iCopy USB SSH rescue starting"
        start_sshd
        start_usb_ether
        start_wifi
        start_sshd
        log "iCopy USB SSH rescue done"
        ;;
    stop)
        stop_usb_ether
        ;;
    restart|force-reload)
        stop_usb_ether
        "$0" start
        ;;
    status)
        print_status
        if [ -e /sys/class/net/usb0 ]; then
            configure_usb_iface usb0 >/dev/null 2>&1 || true
            exit 0
        fi
        exit 1
        ;;
    enable)
        touch "$ENABLED"
        state "USB SSH rescue enabled"
        ;;
    disable)
        rm -f "$ENABLED"
        stop_usb_ether
        state "USB SSH rescue disabled"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|enable|disable}" >&2
        exit 2
        ;;
esac
'''


def install_app(unpkg_path, callback):
    """Copy app files from unpkg to /home/pi/ipk_app_new.

    Moves the entire unpkg directory to /home/pi/unpkg, then renames
    it to /home/pi/ipk_app_new. The device's ipk_starter.py will swap
    ipk_app_new → ipk_app_main on next boot.

    Args:
        unpkg_path: path to extracted IPK
        callback: progress callback(name, progress)
    """
    target_path = '/home/pi/'
    target_path_new_pkg = os.path.join(target_path, 'ipk_app_new')
    target_path_unpkg = os.path.join(target_path, 'unpkg')

    if callback:
        callback('App installing...', 38)

    # Clean up any previous staged install
    if os.path.exists(target_path_unpkg):
        shutil.rmtree(target_path_unpkg)
    if os.path.exists(target_path_new_pkg):
        shutil.rmtree(target_path_new_pkg)

    # Move unpkg → /home/pi/unpkg → rename to ipk_app_new
    shutil.move(unpkg_path, target_path_unpkg)
    os.rename(target_path_unpkg, target_path_new_pkg)

    print("copy files finished!")
    if callback:
        callback('App installed!', 100)


def restart_app(callback):
    """Restart the iCopy service.

    Args:
        callback: progress callback(name, progress)
    """
    print("Restarting...")
    if callback:
        callback('Restarting...', 60)
        callback('Restarting...', 100)

    _schedule_usb_ssh_recovery()
    os.system('sudo service icopy restart &')


def _schedule_usb_ssh_recovery():
    """Best-effort recovery for USB NCM SSH after an app update.

    Some hosts keep a stale USB-NCM session when the app is swapped and
    restarted.  Physically replugging the cable forces re-enumeration; this
    delayed helper does the device-side equivalent when the optional rescue
    network service is installed.
    """
    unit_name = 'icopy-update-usb-ssh-recover-%s-%s' % (
        os.getpid(), int(time.time()))
    service_name = unit_name + '.service'
    script_path = '/tmp/%s.sh' % unit_name

    try:
        with open(script_path, 'w') as f:
            f.write(_usb_ssh_recovery_script())
        os.chmod(script_path, 0o755)
    except Exception as e:
        print("Could not write USB/SSH recovery script: %s" % e)
        return

    # Prefer systemd-run: it creates a transient unit outside icopy.service's
    # cgroup, so "service icopy restart" will not kill the delayed recovery.
    for cmd in (
        'sudo systemd-run --unit=%s --collect /bin/sh %s' % (unit_name, script_path),
        'sudo systemd-run --unit=%s /bin/sh %s' % (unit_name, script_path),
    ):
        try:
            if os.system(cmd + ' >/tmp/icopy-update-usb-ssh-schedule.log 2>&1') == 0:
                print("Scheduled USB/SSH recovery via systemd-run")
                return
        except Exception:
            pass

    # Fallback for older images without systemd-run.
    unit_path = '/run/systemd/system/%s' % service_name
    unit_tmp_path = '/tmp/%s' % service_name
    try:
        with open(unit_tmp_path, 'w') as f:
            f.write('[Unit]\n')
            f.write('Description=iCopy update USB/SSH recovery\n')
            f.write('\n[Service]\n')
            f.write('Type=oneshot\n')
            f.write('ExecStart=/bin/sh %s\n' % script_path)
        os.chmod(unit_tmp_path, 0o644)
        if os.system(
            'sudo cp %s %s >/tmp/icopy-update-usb-ssh-schedule.log 2>&1 '
            '&& sudo systemctl daemon-reload '
            '>>/tmp/icopy-update-usb-ssh-schedule.log 2>&1 '
            '&& sudo systemctl start %s '
            '>>/tmp/icopy-update-usb-ssh-schedule.log 2>&1' % (
                unit_tmp_path, unit_path, service_name)) == 0:
            print("Scheduled USB/SSH recovery via systemd unit")
            return
    except Exception as e:
        print("Could not create USB/SSH recovery unit: %s" % e)

    # Last resort: useful on non-systemd test images, but may be killed when
    # systemd restarts icopy.service.
    cmd = "nohup sudo /bin/sh %s >/tmp/icopy-update-usb-ssh-schedule.log 2>&1 &" % script_path
    try:
        os.system(cmd)
        print("Scheduled USB/SSH recovery via nohup fallback")
    except Exception as e:
        print("Could not schedule USB/SSH recovery: %s" % e)


def _usb_ssh_recovery_script():
    """Return the shell script used by the post-update recovery unit."""
    script = (
        '#!/bin/sh\n'
        'PATH=/sbin:/usr/sbin:/bin:/usr/bin\n'
        'LOG=/tmp/icopy-update-usb-ssh-recover.log; '
        'exec >>"$LOG" 2>&1; '
        'echo "[recover] scheduled $(date)"; '
        'sleep 6; '
        'echo "[recover] running $(date)"; '
        'if [ -x /usr/local/sbin/icopy-rescue-net.sh ]; then '
        'echo "[recover] restarting rescue USB network"; '
        '/usr/local/sbin/icopy-rescue-net.sh restart; '
        'echo "[recover] rescue rc=$?"; '
        'else '
        'echo "[recover] icopy-rescue-net.sh missing"; '
        'fi; '
        'if [ -e /sys/class/net/usb0 ]; then '
        'echo "[recover] ensuring usb0 address"; '
        '(ip link set usb0 up && '
        '(ip addr show dev usb0 | grep -q "192.168.7.2" || '
        'ip addr add 192.168.7.2/24 dev usb0) && '
        '(ip addr show dev usb0 | grep -q "169.254.7.2" || '
        'ip addr add 169.254.7.2/16 dev usb0)) 2>/dev/null || '
        'ifconfig usb0 192.168.7.2 netmask 255.255.255.0 up 2>/dev/null || true; '
        'fi; '
        'mkdir -p /var/run/sshd /run/sshd 2>/dev/null; '
        'echo "[recover] restarting ssh service"; '
        'systemctl restart sshd 2>/dev/null || '
        'systemctl restart ssh 2>/dev/null || '
        'service sshd restart 2>/dev/null || '
        'service ssh restart 2>/dev/null || '
        '(/usr/sbin/sshd 2>/dev/null || true); '
        '(ip addr show dev usb0 2>/dev/null || ifconfig usb0 2>/dev/null || true); '
        'echo "[recover] done $(date)"; '
        'sync'
    )
    return script


def install(unpkg_path, callback):
    """Main install orchestrator.

    Called by update.py (or the original activity_update.so) after the IPK
    has been extracted to unpkg_path.

    Order confirmed by QEMU trace:
      1. install_font  — copy fonts to system
      2. install_lua_dep — extract LUA scripts
      3. install_app   — move files to ipk_app_new
      4. update_permission — chmod 777 -R
      5. restart_app   — restart the service

    Args:
        unpkg_path: path to extracted IPK (e.g. /tmp/.ipk/unpkg)
        callback: progress callback(name, progress)
    """
    install_font(unpkg_path, callback)
    install_lua_dep(unpkg_path, callback)
    install_app(unpkg_path, callback)
    update_permission(unpkg_path, callback)
    restart_app(callback)
