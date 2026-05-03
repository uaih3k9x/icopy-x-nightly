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

"""Temporary USB Wi-Fi manager plugin.

This plugin intentionally avoids persistent networking changes:

* does not edit /etc/network/interfaces
* does not edit /etc/wpa_supplicant/*
* does not enable or disable systemd services
* writes runtime state only under /tmp/icopy_wifi

Connection settings are read from /mnt/upan/wifi.conf so secrets are not
stored in the repository.  Rebooting clears the runtime process state.
Use the plugin's Disconnect action to stop a connection without rebooting.
"""

import io
import os
import re
import signal
import subprocess
import tempfile
import time


class WiFiManagerPlugin(object):
    """Entry class instantiated by PluginActivity."""

    CONFIG_PATHS = (
        '/mnt/upan/wifi.conf',
        '/mnt/upan/wifi/wifi.conf',
    )
    RUNTIME_DIR = os.path.join(tempfile.gettempdir(), 'icopy_wifi')
    DIAG_DIR = '/mnt/upan/diag'
    FALLBACK_DIAG_DIR = os.path.join(tempfile.gettempdir(), 'icopy_diag')

    def __init__(self, host=None):
        self.host = host
        self._last_log_path = ''

    def on_load(self):
        self._set_var('status_short', self._short_status())
        self._set_var('scan_lines', '')
        self._set_var('connect_lines', '')
        self._set_var('disconnect_lines', '')
        self._set_var('error_msg', '')

    def on_destroy(self):
        # Do not auto-disconnect. Users often need Wi-Fi to stay up after
        # leaving this screen for SSH/SCP. Runtime state is still reboot-safe.
        pass

    def do_scan(self):
        """Discover wireless interfaces and nearby access points."""
        self._set_var('error_msg', '')
        self._progress(5, 'Finding Wi-Fi')

        lines = []
        raw_log = []
        interfaces = self._wireless_interfaces()
        config = self._read_config(allow_missing=True)
        wanted_ssid = config.get('ssid', '')

        lines.append('Interfaces: %s' % self._join_or_none(interfaces))
        if wanted_ssid:
            lines.append('Config SSID: %s' % wanted_ssid)
        lines.append('')

        if not interfaces:
            lines.append('No wireless interface found.')
            lines.append('Insert USB Wi-Fi and retry.')
            self._write_diag('wifi_scan', '\n'.join(lines))
            scan_lines = '\n'.join(lines)
            self._set_var('scan_lines', scan_lines)
            return {'status': 'scan_done', 'scan_lines': scan_lines}

        networks = []
        for idx, iface in enumerate(interfaces):
            self._progress(10 + idx * 20, 'Scanning %s' % iface)
            self._run(['ip', 'link', 'set', iface, 'up'], timeout=8)
            lines.append('[%s]' % iface)
            raw_log.append('===== interface %s =====' % iface)
            raw_log.extend(self._status_sections(iface))

            scan_out = self._scan_iface(iface)
            raw_log.extend(scan_out['log'])
            parsed = self._parse_iwlist(scan_out.get('stdout', ''))
            if parsed:
                networks.extend(parsed)
                for net in parsed[:8]:
                    marker = '*' if wanted_ssid and net.get('ssid') == wanted_ssid else '-'
                    lines.append('%s %s %s %s' % (
                        marker,
                        net.get('ssid') or '<hidden>',
                        net.get('quality') or '',
                        net.get('security') or '',
                    ))
                if len(parsed) > 8:
                    lines.append('... %d more' % (len(parsed) - 8))
            else:
                msg = scan_out.get('error') or 'No APs parsed'
                lines.append(msg)
            lines.append('')

        if wanted_ssid:
            found = any(n.get('ssid') == wanted_ssid for n in networks)
            lines.append('Configured SSID: %s' % ('FOUND' if found else 'not seen'))

        log_path = self._write_diag(
            'wifi_scan',
            '\n'.join(lines) + '\n\n' + '\n'.join(raw_log),
        )
        lines.append('Log: %s' % self._display_path(log_path))
        scan_lines = '\n'.join(lines)
        self._set_var('scan_lines', scan_lines)
        self._set_var('status_short', self._short_status())
        self._progress(100, 'Scan done')
        return {'status': 'scan_done', 'scan_lines': scan_lines}

    def do_connect(self):
        """Connect to the SSID configured in /mnt/upan/wifi.conf."""
        self._set_var('error_msg', '')
        self._progress(3, 'Reading config')

        config = self._read_config(allow_missing=False)
        ssid = config.get('ssid', '').strip()
        if not ssid:
            raise ValueError('wifi.conf missing ssid=...')
        self._validate_config(config)
        if not self._command_exists('wpa_supplicant'):
            raise RuntimeError('wpa_supplicant not found')

        iface = self._select_iface(config.get('iface', '').strip())
        if not iface:
            raise RuntimeError('No wireless interface found')

        self._ensure_dir(self.RUNTIME_DIR, mode=0o700)
        self._ensure_dir('/var/run/wpa_supplicant', mode=0o755)
        log_lines = []
        log_lines.append('WiFi connect attempt')
        log_lines.append('Time: %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
        log_lines.append('SSID: %s' % ssid)
        log_lines.append('Interface: %s' % iface)

        self._progress(10, 'Preparing iface')
        log_lines.extend(self._command_section(['ip', 'link', 'set', iface, 'up'], 8))
        log_lines.extend(self._command_section(['ip', 'addr', 'flush', 'dev', iface], 8))
        self._stop_managed_wpa(iface, log_lines)

        conf_path = self._runtime_conf_path(iface)
        pid_path = self._pid_path(iface)
        wpa_log_path = self._runtime_log_path(iface)
        self._write_file(conf_path, self._build_wpa_config(config), mode=0o600)
        log_lines.append('===== sanitized runtime config =====')
        log_lines.append(self._redacted_wpa_config(conf_path))

        driver = 'existing'
        if self._wpa_cli_available(iface):
            self._progress(25, 'Configuring WPA')
            log_lines.extend(self._connect_with_wpa_cli(iface, config))
        else:
            driver = self._choose_driver(iface, config.get('driver', '').strip())
            cmd = [
                'wpa_supplicant',
                '-B',
                '-P', pid_path,
                '-i', iface,
                '-c', conf_path,
                '-D', driver,
                '-f', wpa_log_path,
            ]

            self._progress(25, 'Starting WPA')
            log_lines.extend(self._command_section(cmd, 15))
            log_lines.extend(self._runtime_wpa_log_section(wpa_log_path))

        self._wait_for_association(iface, log_lines, timeout=20)

        self._progress(45, 'Checking link')
        log_lines.extend(self._status_sections(iface))

        self._progress(60, 'DHCP')
        log_lines.extend(self._dhcp(iface))

        self._progress(85, 'Final status')
        log_lines.extend(self._status_sections(iface))
        ipv4 = self._ipv4_for_iface(iface)
        associated = self._is_associated(iface)
        diag_path = self._write_diag('wifi_connect', '\n'.join(log_lines))
        self._last_log_path = diag_path

        if ipv4:
            summary = [
                'Connected.',
                'SSID: %s' % ssid,
                'Iface: %s' % iface,
                'IP: %s' % ipv4,
                'Driver: %s' % driver,
                'Log: %s' % self._display_path(diag_path),
                '',
                'M2 disconnects.',
                'Reboot clears runtime state.',
            ]
            text = '\n'.join(summary)
            self._set_var('connect_lines', text)
            self._set_var('status_short', self._short_status())
            self._progress(100, 'Connected')
            return {'status': 'connected', 'connect_lines': text}

        detail = 'Associated but no IPv4' if associated else 'Not associated'
        log_lines.extend(self._runtime_wpa_log_section(wpa_log_path))
        log_lines.extend(self._command_section([
            'sh', '-c',
            'ps w | grep -E "wpa_supplicant|dhclient|udhcpc" | grep -v grep'
        ], 8))
        log_lines.extend(self._command_section([
            'sh', '-c',
            'dmesg | tail -80'
        ], 8))
        diag_path = self._write_diag('wifi_connect', '\n'.join(log_lines))
        self._last_log_path = diag_path
        msg = (
            'Connect failed: %s\nSSID: %s\nIface: %s\nLog: %s\n\n'
            'Check password and AP range.'
        ) % (detail, ssid, iface, self._display_path(diag_path))
        self._set_var('error_msg', msg)
        return {'status': 'error', 'error_msg': msg}

    def do_disconnect(self):
        """Stop plugin-managed Wi-Fi runtime state."""
        self._set_var('error_msg', '')
        self._progress(10, 'Disconnecting')

        config = self._read_config(allow_missing=True)
        iface = self._select_iface(config.get('iface', '').strip())
        lines = []
        lines.append('WiFi disconnect')
        lines.append('Time: %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
        lines.append('Interface: %s' % (iface or '(none)'))

        if iface:
            lines.extend(self._release_dhcp(iface))
            self._stop_managed_wpa(iface, lines)
            lines.extend(self._command_section(['ip', 'addr', 'flush', 'dev', iface], 8))
            lines.extend(self._command_section(['ip', 'link', 'set', iface, 'down'], 8))
            lines.extend(self._status_sections(iface))

        diag_path = self._write_diag('wifi_disconnect', '\n'.join(lines))
        text = 'Disconnected.\nLog: %s\n\nOK scans again.\nM2 reconnects.' % (
            self._display_path(diag_path),
        )
        self._set_var('disconnect_lines', text)
        self._set_var('status_short', self._short_status())
        self._progress(100, 'Disconnected')
        return {'status': 'disconnected', 'disconnect_lines': text}

    def do_status(self):
        """Refresh connection status on the connected screen."""
        config = self._read_config(allow_missing=True)
        iface = self._select_iface(config.get('iface', '').strip())
        if not iface:
            text = 'No wireless interface found.'
        else:
            text = '\n'.join(self._status_summary(iface))
        self._set_var('connect_lines', text)
        self._set_var('status_short', self._short_status())
        return {'status': 'connected', 'connect_lines': text}

    # ------------------------------------------------------------------
    # Config and interface discovery
    # ------------------------------------------------------------------

    def _read_config(self, allow_missing=False):
        path = None
        for candidate in self.CONFIG_PATHS:
            if os.path.isfile(candidate):
                path = candidate
                break
        if path is None:
            if allow_missing:
                return {}
            raise RuntimeError(
                'Missing /mnt/upan/wifi.conf\n'
                'Example:\nssid=YourWiFi\npsk=YourPassword'
            )

        config = {}
        with io.open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or line.startswith(';'):
                    continue
                if '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip().lower()
                value = value.strip().strip('"').strip("'")
                config[key] = value
        config['_path'] = path
        return config

    def _wireless_interfaces(self):
        root = '/sys/class/net'
        interfaces = []
        try:
            names = sorted(os.listdir(root))
        except Exception:
            names = []

        for name in names:
            if name == 'lo':
                continue
            base = os.path.join(root, name)
            if os.path.isdir(os.path.join(base, 'wireless')):
                interfaces.append(name)
                continue
            if os.path.exists(os.path.join(base, 'phy80211')):
                interfaces.append(name)

        if interfaces:
            return interfaces

        # Fallback for old Wireless Extensions drivers.
        rc, out, err = self._run(['iwconfig'], timeout=8)
        text = out + '\n' + err
        current = None
        for line in text.splitlines():
            if not line:
                current = None
                continue
            if not line.startswith(' ') and not line.startswith('\t'):
                current = line.split()[0]
                if 'no wireless extensions' in line:
                    current = None
                elif current and current not in interfaces:
                    interfaces.append(current)
        return interfaces

    def _select_iface(self, preferred=''):
        interfaces = self._wireless_interfaces()
        if preferred and preferred in interfaces:
            return preferred
        if preferred and os.path.exists(os.path.join('/sys/class/net', preferred)):
            return preferred
        return interfaces[0] if interfaces else ''

    # ------------------------------------------------------------------
    # Scan and parse
    # ------------------------------------------------------------------

    def _scan_iface(self, iface):
        log = []
        cmd = ['iwlist', iface, 'scan']
        rc, out, err = self._run(cmd, timeout=25)
        log.extend(self._format_command(cmd, rc, out, err))
        if rc == 0 and out:
            return {'stdout': out, 'stderr': err, 'log': log}

        fallback = ['iw', 'dev', iface, 'scan']
        rc2, out2, err2 = self._run(fallback, timeout=25)
        log.extend(self._format_command(fallback, rc2, out2, err2))
        return {
            'stdout': out or out2,
            'stderr': err + '\n' + err2,
            'log': log,
            'error': (err2 or err or 'Scan command returned no output').strip(),
        }

    def _parse_iwlist(self, text):
        networks = []
        current = None
        for line in text.splitlines():
            s = line.strip()
            if 'Cell ' in s and 'Address:' in s:
                if current is not None:
                    networks.append(current)
                current = {'security': 'open'}
                continue
            if current is None:
                continue
            if s.startswith('ESSID:'):
                current['ssid'] = self._unquote(s[6:].strip())
            elif 'Quality=' in s:
                m = re.search(r'Quality=([^ ]+)', s)
                if m:
                    current['quality'] = m.group(1)
                m = re.search(r'Signal level=([^ ]+ ?[^ ]*)', s)
                if m:
                    current['signal'] = m.group(1)
            elif s.startswith('Encryption key:'):
                current['security'] = 'encrypted' if s.endswith('on') else 'open'
            elif 'WPA2' in s or 'IEEE 802.11i' in s:
                current['security'] = 'WPA2'
            elif 'WPA Version 1' in s:
                current['security'] = 'WPA'

        if current is not None:
            networks.append(current)

        # Collapse duplicate SSIDs while keeping the strongest first.
        seen = set()
        result = []
        for item in networks:
            ssid = item.get('ssid', '')
            key = ssid or repr(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    # ------------------------------------------------------------------
    # Connection control
    # ------------------------------------------------------------------

    def _build_wpa_config(self, config):
        ssid = config.get('ssid', '')
        psk = config.get('psk', config.get('password', ''))
        key_mgmt = config.get('key_mgmt', '').upper()
        hidden = config.get('hidden', '0').lower() in ('1', 'true', 'yes', 'on')
        country = config.get('country', 'CN')

        lines = [
            'ctrl_interface=/var/run/wpa_supplicant',
            'update_config=0',
            'country=%s' % country,
            '',
            'network={',
            '\tssid="%s"' % self._escape_wpa(ssid),
        ]
        if hidden:
            lines.append('\tscan_ssid=1')
        if key_mgmt == 'NONE' or not psk:
            lines.append('\tkey_mgmt=NONE')
        else:
            lines.append('\tpsk="%s"' % self._escape_wpa(psk))
        lines.append('}')
        lines.append('')
        return '\n'.join(lines)

    def _validate_config(self, config):
        ssid = config.get('ssid', '').strip()
        psk = config.get('psk', config.get('password', '')).strip()
        key_mgmt = config.get('key_mgmt', '').strip().upper()
        if not ssid:
            raise ValueError('wifi.conf missing ssid=...')
        if key_mgmt == 'NONE':
            return
        if not psk:
            raise ValueError(
                'wifi.conf has empty psk for encrypted Wi-Fi.\n'
                'Fill psk=... or set key_mgmt=NONE for open Wi-Fi.'
            )
        if len(psk) < 8 or len(psk) > 63:
            raise ValueError('WPA/WPA2 psk must be 8-63 characters')

    def _wpa_cli_available(self, iface):
        if not self._command_exists('wpa_cli'):
            return False
        rc, out, err = self._run(['wpa_cli', '-i', iface, 'status'], timeout=8)
        text = out + '\n' + err
        return rc == 0 and ('wpa_state=' in text or 'address=' in text)

    def _connect_with_wpa_cli(self, iface, config):
        log = []
        ssid = config.get('ssid', '').strip()
        psk = config.get('psk', config.get('password', '')).strip()
        key_mgmt = config.get('key_mgmt', '').strip().upper()
        hidden = config.get('hidden', '0').lower() in ('1', 'true', 'yes', 'on')

        log.extend(self._command_section(['wpa_cli', '-i', iface, 'status'], 8))
        # Runtime only. We do not call save_config, so reboot restores state.
        log.extend(self._command_section(['wpa_cli', '-i', iface, 'remove_network', 'all'], 8))
        rc, out, err = self._run(['wpa_cli', '-i', iface, 'add_network'], timeout=8)
        log.extend(self._format_command(['wpa_cli', '-i', iface, 'add_network'], rc, out, err))
        net_id = ''
        if rc == 0 and out.strip():
            for line in out.strip().splitlines():
                candidate = line.strip()
                if candidate.isdigit():
                    net_id = candidate
                    break
        if not net_id.isdigit():
            log.append('Could not allocate wpa_cli network id')
            return log

        log.extend(self._command_section([
            'wpa_cli', '-i', iface, 'set_network', net_id,
            'ssid', '"%s"' % self._escape_wpa(ssid)
        ], 8))
        if hidden:
            log.extend(self._command_section([
                'wpa_cli', '-i', iface, 'set_network', net_id,
                'scan_ssid', '1'
            ], 8))
        if key_mgmt == 'NONE':
            log.extend(self._command_section([
                'wpa_cli', '-i', iface, 'set_network', net_id,
                'key_mgmt', 'NONE'
            ], 8))
        else:
            psk_cmd = [
                'wpa_cli', '-i', iface, 'set_network', net_id,
                'psk', '"%s"' % self._escape_wpa(psk)
            ]
            rc, out, err = self._run(psk_cmd, timeout=8)
            log.extend(self._format_command([
                'wpa_cli', '-i', iface, 'set_network', net_id,
                'psk', '<redacted>'
            ], rc, out, err))

        log.extend(self._command_section(['wpa_cli', '-i', iface, 'enable_network', net_id], 8))
        log.extend(self._command_section(['wpa_cli', '-i', iface, 'select_network', net_id], 8))
        log.extend(self._command_section(['wpa_cli', '-i', iface, 'reassociate'], 8))
        return log

    def _wait_for_association(self, iface, log_lines, timeout=20):
        deadline = time.time() + timeout
        last_state = ''
        while time.time() < deadline:
            rc, out, err = self._run(['wpa_cli', '-i', iface, 'status'], timeout=5)
            state = ''
            for line in out.splitlines():
                if line.startswith('wpa_state='):
                    state = line.split('=', 1)[1]
                    break
            if state:
                last_state = state
            if state == 'COMPLETED' or self._is_associated(iface):
                log_lines.append('Association wait: associated (%s)' % (state or 'iwconfig'))
                return True
            time.sleep(1)
        log_lines.append('Association wait timeout. Last state: %s' % (last_state or '(unknown)'))
        return False

    def _runtime_wpa_log_section(self, path):
        lines = ['===== runtime wpa log =====']
        if not os.path.exists(path):
            lines.append('%s not found' % path)
            return lines
        try:
            with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            lines.append(text.rstrip() if text else '(empty)')
        except Exception as exc:
            lines.append('Could not read %s: %s' % (path, exc))
        return lines

    def _redacted_wpa_config(self, path):
        try:
            with io.open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.read().splitlines()
        except Exception as exc:
            return 'Could not read %s: %s' % (path, exc)
        redacted = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('psk='):
                indent = line[:len(line) - len(line.lstrip())]
                redacted.append(indent + 'psk=<redacted>')
            else:
                redacted.append(line)
        return '\n'.join(redacted)

    def _choose_driver(self, iface, configured):
        if configured:
            return configured
        rc, out, err = self._run(['iw', 'dev'], timeout=8)
        if iface and iface in out:
            return 'nl80211,wext'
        iwc_rc, iwc_out, iwc_err = self._run(['iwconfig', iface], timeout=8)
        if iwc_rc == 0 and ('<WIFI@REALTEK>' in iwc_out or 'unassociated' in iwc_out):
            return 'wext'
        return 'nl80211,wext'

    def _dhcp(self, iface):
        if self._command_exists('dhclient'):
            out = []
            out.extend(self._command_section(['dhclient', '-r', iface], 12))
            out.extend(self._command_section(['dhclient', '-v', '-1', iface], 35))
            return out
        if self._command_exists('udhcpc'):
            return self._command_section(['udhcpc', '-i', iface, '-n', '-q', '-t', '5'], 35)
        return ['===== DHCP =====', 'No dhclient or udhcpc found']

    def _release_dhcp(self, iface):
        if self._command_exists('dhclient'):
            return self._command_section(['dhclient', '-r', iface], 12)
        return ['===== DHCP release =====', 'dhclient not found']

    def _stop_managed_wpa(self, iface, log_lines):
        pid_path = self._pid_path(iface)
        pid = self._read_pid(pid_path)
        if not pid:
            log_lines.append('No managed wpa_supplicant pid for %s' % iface)
            return
        if not self._pid_cmdline_contains(pid, 'wpa_supplicant'):
            log_lines.append('Ignoring stale pid %s for %s' % (pid, iface))
            self._safe_unlink(pid_path)
            return
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if self._pid_exists(pid):
                os.kill(pid, signal.SIGKILL)
            log_lines.append('Stopped managed wpa_supplicant pid %s' % pid)
        except OSError as exc:
            log_lines.append('Could not stop pid %s: %s' % (pid, exc))
        self._safe_unlink(pid_path)

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _short_status(self):
        iface = self._select_iface('')
        if not iface:
            return 'No Wi-Fi interface.'
        ip = self._ipv4_for_iface(iface)
        if ip:
            return '%s %s' % (iface, ip)
        if self._is_associated(iface):
            return '%s associated, no IP' % iface
        return '%s not connected' % iface

    def _status_summary(self, iface):
        lines = []
        lines.append('Iface: %s' % iface)
        lines.append('IP: %s' % (self._ipv4_for_iface(iface) or '(none)'))
        lines.append('Associated: %s' % ('yes' if self._is_associated(iface) else 'no'))
        if self._last_log_path:
            lines.append('Log: %s' % self._display_path(self._last_log_path))
        lines.append('')
        rc, out, err = self._run(['iwconfig', iface], timeout=8)
        lines.append((out or err or '').strip())
        return lines

    def _status_sections(self, iface):
        out = []
        out.extend(self._command_section(['ip', 'link', 'show', iface], 8))
        out.extend(self._command_section(['ip', 'addr', 'show', iface], 8))
        out.extend(self._command_section(['iwconfig', iface], 8))
        if self._command_exists('wpa_cli'):
            out.extend(self._command_section(['wpa_cli', '-i', iface, 'status'], 8))
        return out

    def _ipv4_for_iface(self, iface):
        rc, out, err = self._run(['ip', '-4', 'addr', 'show', 'dev', iface], timeout=8)
        if rc != 0:
            return ''
        m = re.search(r'\binet\s+([0-9.]+/\d+)', out)
        return m.group(1) if m else ''

    def _is_associated(self, iface):
        rc, out, err = self._run(['iwconfig', iface], timeout=8)
        text = out + '\n' + err
        if 'Not-Associated' in text or 'unassociated' in text:
            return False
        if 'Access Point:' in text and 'ESSID:"' in text:
            return True
        return False

    # ------------------------------------------------------------------
    # Command, file and formatting helpers
    # ------------------------------------------------------------------

    def _run(self, cmd, timeout=10):
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

    def _command_section(self, cmd, timeout):
        rc, out, err = self._run(cmd, timeout)
        return self._format_command(cmd, rc, out, err)

    def _format_command(self, cmd, rc, out, err):
        lines = ['===== %s =====' % self._cmd_to_text(cmd)]
        lines.append('returncode: %s' % rc)
        if out:
            lines.append(out.rstrip())
        if err:
            lines.append('[stderr]')
            lines.append(err.rstrip())
        if not out and not err:
            lines.append('(no output)')
        return lines

    def _command_exists(self, name):
        rc, out, err = self._run(['sh', '-c', 'command -v "$1"', 'sh', name], timeout=5)
        return rc == 0 and bool(out.strip())

    def _ensure_dir(self, path, mode=0o755):
        if not os.path.isdir(path):
            os.makedirs(path)
        try:
            os.chmod(path, mode)
        except Exception:
            pass

    def _write_file(self, path, text, mode=None):
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        if mode is not None:
            try:
                os.chmod(path, mode)
            except Exception:
                pass

    def _write_diag(self, prefix, text):
        out_dir = self.DIAG_DIR if os.path.isdir('/mnt/upan') else self.FALLBACK_DIAG_DIR
        self._ensure_dir(out_dir)
        path = os.path.join(out_dir, '%s_%s.txt' % (
            prefix,
            time.strftime('%Y%m%d_%H%M%S'),
        ))
        self._write_file(path, text + '\n')
        return path

    def _runtime_conf_path(self, iface):
        return os.path.join(self.RUNTIME_DIR, 'wpa_%s.conf' % iface)

    def _runtime_log_path(self, iface):
        return os.path.join(self.RUNTIME_DIR, 'wpa_%s.log' % iface)

    def _pid_path(self, iface):
        return os.path.join(self.RUNTIME_DIR, 'wpa_%s.pid' % iface)

    def _read_pid(self, path):
        try:
            with io.open(path, 'r', encoding='utf-8') as f:
                return int(f.read().strip())
        except Exception:
            return None

    def _pid_exists(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _pid_cmdline_contains(self, pid, text):
        try:
            with io.open('/proc/%d/cmdline' % pid, 'r', encoding='utf-8') as f:
                cmdline = f.read().replace('\x00', ' ')
            return text in cmdline and self.RUNTIME_DIR in cmdline
        except Exception:
            return False

    def _safe_unlink(self, path):
        try:
            os.unlink(path)
        except OSError:
            pass

    def _cmd_to_text(self, cmd):
        if isinstance(cmd, (list, tuple)):
            return ' '.join(cmd)
        return str(cmd)

    def _display_path(self, path):
        if path.startswith('/mnt/upan/'):
            return path[len('/mnt/upan/'):]
        return path

    def _join_or_none(self, items):
        return ', '.join(items) if items else '(none)'

    def _unquote(self, value):
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        return value.replace('\\"', '"')

    def _escape_wpa(self, value):
        return value.replace('\\', '\\\\').replace('"', '\\"')

    def _set_var(self, key, value):
        if self.host is not None and hasattr(self.host, 'set_var'):
            self.host.set_var(key, value)

    def _progress(self, value, message):
        if self.host is not None and hasattr(self.host, 'set_progress'):
            self.host.set_progress(value, message)
