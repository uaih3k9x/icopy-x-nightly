##########################################################################
# Required Notice: Copyright ETOILE401 SAS (http://www.lab401.com)
#
# Copyright (c) 2026: ETOILE401 SAS & https://github.com/quantum-x/
#
# This software is licensed under the PolyForm Noncommercial License 1.0.0.
# You may not use this software for commercial purposes.
#
# A copy of the license is available at:
# https://polyformproject.org/licenses/noncommercial/1.0.0
#
# This entire header "Required Notice" must remain in place.
##########################################################################

"""System diagnostics dump plugin.

Collects read-only system information useful for USB Wi-Fi bring-up:
dmesg, wlan interfaces, USB/PCI inventory, kernel modules and selected
Realtek driver metadata.  Output is written to /mnt/upan/diag when the
USB storage mount is available, with /tmp/icopy_diag as a fallback.
"""

import io
import os
import subprocess
import tempfile
import time


class SysDumpPlugin(object):
    """Entry class instantiated by PluginActivity."""

    OUTPUT_DIR = '/mnt/upan/diag'
    FALLBACK_DIR = os.path.join(tempfile.gettempdir(), 'icopy_diag')

    COMMANDS = [
        ('date', ['date'], 5),
        ('uname -a', ['uname', '-a'], 5),
        ('hostname', ['hostname'], 5),
        ('uptime', ['uptime'], 5),
        ('free -m', ['free', '-m'], 8),
        ('df -h', ['df', '-h'], 10),
        ('/etc/os-release', ['cat', '/etc/os-release'], 5),
        ('/etc/issue', ['cat', '/etc/issue'], 5),

        ('/sys/class/net', ['ls', '-la', '/sys/class/net'], 5),
        ('ip link show', ['ip', 'link', 'show'], 8),
        ('ip addr show', ['ip', 'addr', 'show'], 8),
        ('/proc/net/dev', ['cat', '/proc/net/dev'], 5),
        ('/proc/net/wireless', ['cat', '/proc/net/wireless'], 5),
        ('iw dev', ['iw', 'dev'], 8),
        ('iwconfig', ['iwconfig'], 8),
        ('rfkill list', ['rfkill', 'list'], 8),

        ('lsusb', ['lsusb'], 10),
        ('lsusb -t', ['lsusb', '-t'], 10),
        ('lspci -nn', ['lspci', '-nn'], 10),
        ('usb sysfs devices', ['ls', '-la', '/sys/bus/usb/devices'], 8),
        ('pci sysfs devices', ['ls', '-la', '/sys/bus/pci/devices'], 8),

        ('lsmod', ['lsmod'], 10),
        ('/proc/modules', ['cat', '/proc/modules'], 10),
        ('modinfo 8821cu', ['modinfo', '8821cu'], 10),
        ('modinfo 88XXau', ['modinfo', '88XXau'], 10),
        ('modinfo rtl8821cu', ['modinfo', 'rtl8821cu'], 10),
        ('modinfo rtl88xxau', ['modinfo', 'rtl88xxau'], 10),
        ('modinfo 8188eu', ['modinfo', '8188eu'], 10),
        ('modinfo r8188eu', ['modinfo', 'r8188eu'], 10),
        ('modinfo rtl8xxxu', ['modinfo', 'rtl8xxxu'], 10),
        ('modinfo rtl8192cu', ['modinfo', 'rtl8192cu'], 10),
        ('modinfo 8192cu', ['modinfo', '8192cu'], 10),
        ('network tools', [
            'sh', '-c',
            'for c in ip iw iwconfig iwlist ifconfig rfkill wpa_supplicant '
            'wpa_cli dhclient udhcpc lsusb lspci modinfo insmod modprobe; do '
            'printf "%-16s " "$c"; command -v "$c" || true; done'
        ], 8),
        ('wpa_supplicant version', ['wpa_supplicant', '-v'], 8),
        ('wpa_cli version', ['wpa_cli', '-v'], 8),
        ('runtime wifi dirs', [
            'sh', '-c',
            'ls -la /tmp/icopy_wifi 2>&1; '
            'ls -la /var/run/wpa_supplicant 2>&1; '
            'ps w | grep -E "wpa_supplicant|dhclient|udhcpc" | grep -v grep'
        ], 8),
        ('wireless module files', [
            'sh', '-c',
            'd="/lib/modules/$(uname -r)"; '
            'if [ -d "$d" ]; then '
            'find "$d" -type f | grep -Ei '
            '"8188|8192|8811|8812|8814|8821|88xx|rtl|wifi|wireless|cfg80211|mac80211"; '
            'else echo "missing $d"; fi'
        ], 20),
        ('wireless dmesg filter', [
            'sh', '-c',
            'dmesg | grep -Ei '
            '"wlan|wifi|wireless|80211|cfg80211|mac80211|rtl|8188|8192|8811|8812|8814|8821|88xx|usb"'
        ], 20),
        ('dmesg', ['dmesg'], 30),
    ]

    def __init__(self, host=None):
        self.host = host

    def do_dump(self):
        """Collect diagnostics and write a timestamped text file."""
        try:
            self._set_var('error_msg', '')
            self._set_var('summary', 'Collecting diagnostics...')
            self._progress(1, 'Preparing')

            out_dir = self._choose_output_dir()
            self._ensure_dir(out_dir)
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            path = os.path.join(out_dir, 'sys_diag_%s.txt' % timestamp)

            lines = []
            lines.append('iCopy-X system diagnostics')
            lines.append('Generated: %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
            lines.append('Output: %s' % path)
            lines.append('')

            interfaces = self._list_net_interfaces()
            wireless = self._list_wireless_interfaces(interfaces)
            lines.append('Detected interfaces: %s' % self._join_or_none(interfaces))
            lines.append('Detected wireless: %s' % self._join_or_none(wireless))
            lines.append('')

            total = len(self.COMMANDS)
            for idx, (title, cmd, timeout) in enumerate(self.COMMANDS):
                pct = 5 + int((idx * 90) / max(total, 1))
                self._progress(pct, title)
                lines.extend(self._run_section(title, cmd, timeout))

            self._progress(97, 'Writing file')
            self._write_file(path, '\n'.join(lines) + '\n')

            short_path = self._display_path(path)
            summary = (
                'Saved diagnostics:\n%s\n\n'
                'Interfaces: %s\n'
                'Wireless: %s\n\n'
                'Includes dmesg, lsusb, lspci, modules and Realtek checks.'
            ) % (
                short_path,
                self._join_or_none(interfaces),
                self._join_or_none(wireless),
            )
            self._set_var('summary', summary)
            self._set_var('dump_path', path)
            self._progress(100, 'Done')
            return {
                'status': 'done',
                'summary': summary,
                'dump_path': path,
            }
        except Exception as exc:
            msg = 'Diag dump failed: %s' % exc
            self._set_var('error_msg', msg)
            return {'status': 'error', 'error_msg': msg}

    def _run_section(self, title, cmd, timeout):
        rc, stdout, stderr = self._run_command(cmd, timeout)
        out = []
        out.append('')
        out.append('===== %s =====' % title)
        out.append('$ %s' % self._cmd_to_text(cmd))
        out.append('returncode: %s' % rc)
        if stdout:
            out.append('')
            out.append(stdout.rstrip())
        if stderr:
            out.append('')
            out.append('[stderr]')
            out.append(stderr.rstrip())
        if not stdout and not stderr:
            out.append('')
            out.append('(no output)')
        return out

    def _run_command(self, cmd, timeout):
        if self.host is not None and hasattr(self.host, 'shell_command'):
            return self.host.shell_command(cmd, timeout=timeout)

        try:
            result = subprocess.run(
                cmd,
                shell=isinstance(cmd, str),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, '', 'Command timed out after %d seconds' % timeout
        except Exception as exc:
            return -1, '', str(exc)

    def _choose_output_dir(self):
        if os.path.isdir('/mnt/upan'):
            return self.OUTPUT_DIR
        return self.FALLBACK_DIR

    def _ensure_dir(self, path):
        if not os.path.isdir(path):
            os.makedirs(path)

    def _write_file(self, path, text):
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    def _list_net_interfaces(self):
        root = '/sys/class/net'
        try:
            return sorted(os.listdir(root))
        except Exception:
            return []

    def _list_wireless_interfaces(self, interfaces):
        result = []
        for name in interfaces:
            base = os.path.join('/sys/class/net', name)
            if os.path.isdir(os.path.join(base, 'wireless')):
                result.append(name)
                continue
            if os.path.exists(os.path.join(base, 'phy80211')):
                result.append(name)
        return result

    def _display_path(self, path):
        if path.startswith('/mnt/upan/'):
            return path[len('/mnt/upan/'):]
        return path

    def _join_or_none(self, items):
        return ', '.join(items) if items else '(none)'

    def _cmd_to_text(self, cmd):
        if isinstance(cmd, (list, tuple)):
            return ' '.join(cmd)
        return str(cmd)

    def _set_var(self, key, value):
        if self.host is not None and hasattr(self.host, 'set_var'):
            self.host.set_var(key, value)

    def _progress(self, value, message):
        if self.host is not None and hasattr(self.host, 'set_progress'):
            self.host.set_progress(value, message)
