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

Collects read-only system information useful for USB/NCM rescue and Wi-Fi
bring-up: dmesg, network interfaces, USB/PCI inventory, kernel modules and
selected Realtek driver metadata.  Output is written to /mnt/upan/diag when
the USB storage mount is available, with /tmp/icopy_diag as a fallback.
"""

import io
import os
import re
import subprocess
import tempfile
import time


class SysDumpPlugin(object):
    """Entry class instantiated by PluginActivity."""

    OUTPUT_DIR = '/mnt/upan/diag'
    FALLBACK_DIR = os.path.join(tempfile.gettempdir(), 'icopy_diag')
    RESCUE_SCRIPT = '/usr/local/sbin/icopy-rescue-net.sh'
    RESCUE_SERVICE = 'icopy-rescue-net.service'
    RESCUE_GADGET = '/sys/kernel/config/usb_gadget/icopy_rescue'
    USB_IFACE = 'usb0'
    USB_IP = '192.168.7.2'
    HOST_IP = '192.168.7.1'

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

        ('NCM rescue service status', [
            'sh', '-c',
            'ls -la /usr/local/sbin/icopy-rescue-net.sh '
            '/etc/systemd/system/icopy-rescue-net.service '
            '/etc/init.d/icopy-rescue-net /etc/icopy-rescue-net.enabled '
            '2>&1; '
            'systemctl is-active icopy-rescue-net.service 2>&1 || true; '
            'systemctl is-enabled icopy-rescue-net.service 2>&1 || true; '
            'service icopy-rescue-net status 2>&1 || true'
        ], 10),
        ('NCM rescue logs', [
            'sh', '-c',
            'for f in /var/log/icopy-rescue-net.log '
            '/var/log/icopy-rescue-net-install.log '
            '/tmp/icopy-rescue-net.out '
            '/tmp/icopy-update-usb-ssh-recover.log '
            '/tmp/icopy-update-usb-ssh-schedule.log; do '
            'echo "--- $f ---"; '
            'if [ -e "$f" ]; then tail -n 120 "$f"; else echo "(missing)"; fi; '
            'done'
        ], 12),
        ('USB NCM IP state', [
            'sh', '-c',
            'ip addr show dev usb0 2>&1 || ifconfig usb0 2>&1 || true; '
            'for f in operstate carrier address; do '
            'p=/sys/class/net/usb0/$f; '
            'if [ -e "$p" ]; then printf "%s: " "$f"; cat "$p"; fi; '
            'done'
        ], 8),
        ('SSH listener state', [
            'sh', '-c',
            '(ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null || true); '
            'ps w | grep -E "[s]shd|[d]ropbear" || true'
        ], 8),

        ('lsusb', ['lsusb'], 10),
        ('lsusb -t', ['lsusb', '-t'], 10),
        ('lspci -nn', ['lspci', '-nn'], 10),
        ('usb sysfs devices', ['ls', '-la', '/sys/bus/usb/devices'], 8),
        ('USB gadget configfs', [
            'sh', '-c',
            'ls -la /sys/class/udc 2>&1; '
            'find /sys/kernel/config/usb_gadget -maxdepth 4 '
            '-type d -o -type l -o -type f 2>&1 | sort; '
            'if [ -e /sys/kernel/config/usb_gadget/icopy_rescue/UDC ]; then '
            'printf "icopy_rescue UDC: "; '
            'cat /sys/kernel/config/usb_gadget/icopy_rescue/UDC; fi'
        ], 12),
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
        ('USB/NCM dmesg filter', [
            'sh', '-c',
            'dmesg | grep -Ei '
            '"usb|gadget|ncm|ecm|rndis|g_ether|configfs|udc|dwc|sshd|ttyACM|g_serial|mass_storage|PM3"'
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

            self._progress(3, 'Self checks')
            checks = self._run_self_checks(interfaces)
            lines.extend(self._format_self_check_section(checks))

            total = len(self.COMMANDS)
            for idx, (title, cmd, timeout) in enumerate(self.COMMANDS):
                pct = 5 + int((idx * 90) / max(total, 1))
                self._progress(pct, title)
                lines.extend(self._run_section(title, cmd, timeout))

            self._progress(97, 'Writing file')
            self._write_file(path, '\n'.join(lines) + '\n')

            short_path = self._display_path(path)
            check_summary = self._format_summary_checks(checks)
            summary = (
                '%s\n\n'
                'Saved diagnostics:\n%s\n\n'
                'Interfaces: %s\n'
                'Wireless: %s\n'
                'Raw: NCM/IP/USB tree/dmesg included.'
            ) % (
                check_summary,
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

    def _run_self_checks(self, interfaces):
        checks = []
        self._check_rescue_service(checks)
        self._check_usb_ip(checks, interfaces)
        self._check_ssh_listener(checks)
        self._check_usb_gadget(checks)
        self._check_dmesg_usb(checks)
        return checks

    def _check_rescue_service(self, checks):
        if not self._path_exists(self.RESCUE_SCRIPT):
            checks.append(self._check(
                'WARN', 'Rescue script',
                '%s missing' % self.RESCUE_SCRIPT))
            return

        if not self._path_executable(self.RESCUE_SCRIPT):
            checks.append(self._check(
                'WARN', 'Rescue script',
                '%s exists but is not executable' % self.RESCUE_SCRIPT))
        else:
            checks.append(self._check('PASS', 'Rescue script', 'installed'))

        rc, stdout, stderr = self._run_command(
            ['systemctl', 'is-active', self.RESCUE_SERVICE], 3)
        active = (stdout or stderr).strip()
        if rc == 0 and active == 'active':
            checks.append(self._check('PASS', 'NCM service', 'active'))
            return
        if active:
            checks.append(self._check('WARN', 'NCM service', active))
            return

        if self._path_exists('/etc/init.d/icopy-rescue-net'):
            checks.append(self._check('INFO', 'NCM service', 'SysV fallback installed'))
        else:
            checks.append(self._check('WARN', 'NCM service', 'service status unknown'))

    def _check_usb_ip(self, checks, interfaces):
        if self.USB_IFACE not in interfaces:
            checks.append(self._check('FAIL', 'usb0', 'interface missing'))
            return

        operstate = self._read_first_line('/sys/class/net/%s/operstate' % self.USB_IFACE)
        carrier = self._read_first_line('/sys/class/net/%s/carrier' % self.USB_IFACE)
        rc, stdout, stderr = self._run_command(
            ['ip', '-o', '-4', 'addr', 'show', 'dev', self.USB_IFACE], 5)
        addr_text = stdout or stderr
        addresses = re.findall(r'\binet\s+([0-9.]+/\d+)', addr_text)

        if any(addr.startswith(self.USB_IP + '/') for addr in addresses):
            detail = '%s (%s)' % (', '.join(addresses), operstate or 'state unknown')
            checks.append(self._check('PASS', 'usb0 IP', detail))
        elif addresses:
            checks.append(self._check(
                'WARN', 'usb0 IP',
                'expected %s/24, found %s' % (self.USB_IP, ', '.join(addresses))))
        else:
            checks.append(self._check(
                'FAIL', 'usb0 IP',
                'missing %s/24' % self.USB_IP))

        if carrier == '1':
            checks.append(self._check('PASS', 'USB carrier', 'host link detected'))
        elif carrier == '0':
            checks.append(self._check(
                'WARN', 'USB carrier',
                'no host link; set host IP to %s/24' % self.HOST_IP))
        else:
            checks.append(self._check('INFO', 'USB carrier', 'not reported'))

    def _check_ssh_listener(self, checks):
        rc, stdout, stderr = self._run_command([
            'sh', '-c',
            'ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null || true'
        ], 5)
        listener_text = stdout or stderr
        if self._has_port_22_listener(listener_text):
            checks.append(self._check('PASS', 'SSH', 'listening on port 22'))
            return

        rc, stdout, stderr = self._run_command([
            'sh', '-c',
            'ps w | grep -E "[s]shd|[d]ropbear"'
        ], 5)
        process_text = stdout or stderr
        if rc == 0 and process_text.strip():
            checks.append(self._check('WARN', 'SSH', 'process exists, listener unclear'))
        else:
            checks.append(self._check('FAIL', 'SSH', 'no sshd/dropbear listener seen'))

    def _check_usb_gadget(self, checks):
        if self._path_exists(self.RESCUE_GADGET):
            functions = self._list_names(os.path.join(self.RESCUE_GADGET, 'functions'))
            configs = self._list_names(os.path.join(self.RESCUE_GADGET, 'configs', 'c.1'))
            udc = self._read_first_line(os.path.join(self.RESCUE_GADGET, 'UDC'))
            detail_bits = []
            if functions:
                detail_bits.append('functions=%s' % ','.join(functions))
            if configs:
                detail_bits.append('config=%s' % ','.join(configs))
            if udc:
                detail_bits.append('UDC=%s' % udc)

            detail = '; '.join(detail_bits) if detail_bits else 'present but empty'
            has_net_func = any(
                name.startswith(('ncm.', 'ecm.', 'rndis.'))
                for name in functions + configs
            )
            if has_net_func and udc:
                checks.append(self._check('PASS', 'USB gadget', detail))
            elif has_net_func:
                checks.append(self._check('WARN', 'USB gadget', detail + '; not bound'))
            else:
                checks.append(self._check('WARN', 'USB gadget', detail))
            return

        modules = self._read_text('/proc/modules')
        if 'g_ether' in modules:
            checks.append(self._check('INFO', 'USB gadget', 'g_ether fallback loaded'))
        else:
            checks.append(self._check('WARN', 'USB gadget', 'icopy_rescue gadget missing'))

    def _check_dmesg_usb(self, checks):
        rc, stdout, stderr = self._run_command([
            'sh', '-c',
            'out="$(dmesg 2>&1)"; rc=$?; '
            'if [ "$rc" -ne 0 ]; then echo "$out"; exit "$rc"; fi; '
            'printf "%s\n" "$out" | tail -n 240 | grep -Ei '
            '"usb|gadget|ncm|ecm|rndis|g_ether|configfs|udc|dwc|'
            'sshd|ttyACM|g_serial|mass_storage|PM3" | tail -n 80'
        ], 8)
        text = stdout or stderr
        stripped = text.strip()
        if rc not in (0, 1) and stripped:
            checks.append(self._check('WARN', 'dmesg', stripped.splitlines()[-1][:80]))
            return
        if not stripped:
            checks.append(self._check('INFO', 'dmesg', 'no recent USB/NCM lines'))
            return

        problem_re = re.compile(
            r'failed|failure|error|unable|no such|busy|timeout|'
            r'did not appear|cannot|can.t|unavailable',
            re.IGNORECASE)
        problems = [line for line in stripped.splitlines() if problem_re.search(line)]
        reconnects = [
            line for line in stripped.splitlines()
            if re.search(r'disconnect|reconnect|reset', line, re.IGNORECASE)
        ]

        if problems:
            checks.append(self._check(
                'WARN', 'dmesg USB',
                '%d suspicious line(s), latest: %s' % (
                    len(problems), problems[-1].strip()[:70])))
        elif reconnects:
            checks.append(self._check(
                'WARN', 'dmesg USB',
                '%d reconnect/reset line(s)' % len(reconnects)))
        else:
            checks.append(self._check('PASS', 'dmesg USB', 'no recent USB errors'))

    def _format_self_check_section(self, checks):
        lines = ['', '===== SELF CHECK SUMMARY =====']
        for item in checks:
            lines.append('[%(status)s] %(name)s: %(detail)s' % item)
        lines.append('')
        return lines

    def _format_summary_checks(self, checks):
        priority = ['FAIL', 'WARN', 'PASS', 'INFO']
        selected = []
        for status in priority:
            for item in checks:
                if item['status'] == status and item not in selected:
                    selected.append(item)
                if len(selected) >= 7:
                    break
            if len(selected) >= 7:
                break

        lines = ['Self check: %s' % self._overall_status(checks)]
        for item in selected:
            lines.append('[%(status)s] %(name)s: %(detail)s' % item)
        return '\n'.join(lines)

    def _overall_status(self, checks):
        statuses = [item['status'] for item in checks]
        if 'FAIL' in statuses:
            return 'FAIL'
        if 'WARN' in statuses:
            return 'WARN'
        return 'PASS'

    def _check(self, status, name, detail):
        return {'status': status, 'name': name, 'detail': detail}

    def _has_port_22_listener(self, text):
        for line in text.splitlines():
            if re.search(r'[:.]22(\s|$)', line):
                return True
        return False

    def _path_exists(self, path):
        return os.path.exists(path)

    def _path_executable(self, path):
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def _read_text(self, path):
        try:
            with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception:
            return ''

    def _read_first_line(self, path):
        text = self._read_text(path)
        if not text:
            return ''
        return text.splitlines()[0].strip()

    def _list_names(self, path):
        try:
            return sorted(os.listdir(path))
        except Exception:
            return []

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
