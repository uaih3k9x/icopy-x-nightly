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

"""USB SSH bootstrap manager plugin.

The service itself is installed by main/install.py so the first connection does
not depend on opening this plugin.  The plugin is a maintenance panel: status,
restart, repair/reinstall, enable/disable and rollback.
"""

import importlib.util
import os
import re
import subprocess
import sys
import time


class UsbSshPlugin(object):
    RESCUE_SCRIPT = '/usr/local/sbin/icopy-rescue-net.sh'
    RESCUE_UNIT = '/etc/systemd/system/icopy-rescue-net.service'
    RESCUE_INIT = '/etc/init.d/icopy-rescue-net'
    ENABLED_FILE = '/etc/icopy-rescue-net.enabled'
    RESCUE_GADGET = '/sys/kernel/config/usb_gadget/icopy_rescue'
    USB_IFACE = 'usb0'
    USB_IP = '192.168.7.2'
    USB_LINK_LOCAL = '169.254.7.2'

    def __init__(self, host=None):
        self.host = host

    def on_load(self):
        self._set_var('status_text', 'Select Status to inspect USB SSH.')
        self._set_var('result_text', '')
        self._set_var('error_msg', '')

    def do_status(self):
        self._progress(10, 'Checking USB SSH')
        text = self._status_text()
        self._set_var('status_text', text)
        self._set_var('result_text', text)
        self._progress(100, 'Status ready')
        return {'status': 'status'}

    def do_repair(self):
        self._set_var('error_msg', '')
        self._progress(5, 'Loading installer')
        try:
            install = self._load_install_module()
            if install is None:
                raise RuntimeError('install.py helpers not found')

            self._progress(30, 'Writing service')
            ok = False
            helper = getattr(install, '_install_rescue_net_service', None)
            if callable(helper):
                ok = bool(helper(enable=True, restart=True, backup=True))
            if not ok:
                self._progress(55, 'Trying sudo')
                ok = self._repair_with_sudo(install)
            if not ok:
                raise RuntimeError('repair command failed')

            self._progress(100, 'Repair scheduled')
            text = self._done_text([
                'USB SSH service repaired.',
                'Restart scheduled.',
                'USB network may reconnect.',
            ])
            self._set_var('result_text', text)
            return {'status': 'done'}
        except Exception as exc:
            return self._error('Repair failed: %s' % exc)

    def do_restart(self):
        self._set_var('error_msg', '')
        self._progress(20, 'Scheduling restart')
        if not self._path_exists(self.RESCUE_SCRIPT):
            return self._error('Rescue script missing. Run Repair first.')
        if not self._schedule_restart():
            return self._error('Could not schedule restart')
        self._progress(100, 'Restart scheduled')
        self._set_var('result_text', self._done_text([
            'USB SSH restart scheduled.',
            'Reconnect after USB settles.',
        ]))
        return {'status': 'done'}

    def do_stop(self):
        self._set_var('error_msg', '')
        self._progress(20, 'Stopping USB')
        if not self._path_exists(self.RESCUE_SCRIPT):
            return self._error('Rescue script missing.')
        rc, stdout, stderr = self._run_command([
            'sudo', self.RESCUE_SCRIPT, 'stop'
        ], timeout=15)
        if rc != 0:
            return self._error('Stop failed: %s' % ((stderr or stdout).strip() or rc))
        self._progress(100, 'Stopped')
        self._set_var('result_text', self._done_text([
            'USB SSH stopped.',
            'Boot setting is unchanged.',
        ]))
        return {'status': 'done'}

    def do_enable(self):
        self._set_var('error_msg', '')
        self._progress(20, 'Enabling')
        if not self._path_exists(self.RESCUE_SCRIPT):
            return self.do_repair()
        rc, stdout, stderr = self._run_command([
            'sudo', self.RESCUE_SCRIPT, 'enable'
        ], timeout=10)
        if rc != 0:
            return self._error('Enable failed: %s' % ((stderr or stdout).strip() or rc))
        self._schedule_restart()
        self._progress(100, 'Enabled')
        self._set_var('result_text', self._done_text([
            'USB SSH enabled at boot.',
            'Restart scheduled.',
        ]))
        return {'status': 'done'}

    def do_disable(self):
        self._set_var('error_msg', '')
        self._progress(20, 'Disabling')
        if self._path_exists(self.RESCUE_SCRIPT):
            rc, stdout, stderr = self._run_command([
                'sudo', self.RESCUE_SCRIPT, 'disable'
            ], timeout=15)
            if rc != 0:
                return self._error(
                    'Disable failed: %s' % ((stderr or stdout).strip() or rc))
        else:
            self._run_command(['sudo', 'rm', '-f', self.ENABLED_FILE], timeout=8)
        self._progress(100, 'Disabled')
        self._set_var('result_text', self._done_text([
            'USB SSH disabled at boot.',
            'Current USB network stopped.',
        ]))
        return {'status': 'done'}

    def do_rollback(self):
        self._set_var('error_msg', '')
        self._progress(20, 'Finding backup')
        script_path = self._write_temp_script('rollback', self._rollback_script())
        if not script_path:
            return self._error('Could not write rollback script')
        self._progress(50, 'Restoring files')
        rc, stdout, stderr = self._run_command([
            'sudo', '/bin/sh', script_path
        ], timeout=20)
        if rc != 0:
            detail = (stderr or stdout).strip() or 'rc=%s' % rc
            return self._error('Rollback failed: %s' % detail)
        self._progress(100, 'Rollback done')
        self._set_var('result_text', self._done_text([
            'Rollback complete.',
            'Restart scheduled if service exists.',
        ]))
        return {'status': 'done'}

    def _status_text(self):
        lines = []
        script_ok = self._path_executable(self.RESCUE_SCRIPT)
        enabled = self._path_exists(self.ENABLED_FILE)

        lines.append('Service: %s' % ('installed' if script_ok else 'missing'))
        lines.append('Boot: %s' % ('enabled' if enabled else 'disabled'))

        rc, stdout, stderr = self._run_command(
            ['systemctl', 'is-active', 'icopy-rescue-net.service'], timeout=3)
        active = (stdout or stderr).strip()
        if rc == 0 and active:
            lines.append('Systemd: %s' % active)
        elif self._path_exists(self.RESCUE_INIT):
            lines.append('Init.d: installed')
        else:
            lines.append('Service file: missing')

        if self._path_exists('/sys/class/net/%s' % self.USB_IFACE):
            lines.append('usb0: present')
            addresses = self._usb_addresses()
            lines.append('IP: %s' % (', '.join(addresses) if addresses else 'none'))
            carrier = self._read_first_line('/sys/class/net/usb0/carrier')
            if carrier:
                lines.append('Carrier: %s' % carrier)
        else:
            lines.append('usb0: missing')

        func = self._gadget_function()
        if func:
            lines.append('Gadget: %s' % func)
        else:
            lines.append('Gadget: missing')

        lines.append('SSH: %s' % ('listening' if self._ssh_listening() else 'unknown'))
        lines.append('')
        lines.append('Connect:')
        lines.append('ssh root@169.254.7.2')
        lines.append('ssh root@192.168.7.2')
        return '\n'.join(lines)

    def _usb_addresses(self):
        rc, stdout, stderr = self._run_command([
            'ip', '-o', '-4', 'addr', 'show', 'dev', self.USB_IFACE
        ], timeout=5)
        text = stdout or stderr
        return re.findall(r'\binet\s+([0-9.]+/\d+)', text or '')

    def _gadget_function(self):
        funcs = self._list_names(os.path.join(self.RESCUE_GADGET, 'functions'))
        configs = self._list_names(os.path.join(self.RESCUE_GADGET, 'configs', 'c.1'))
        names = funcs + configs
        for prefix in ('ncm.', 'ecm.', 'rndis.'):
            for name in names:
                if name.startswith(prefix):
                    udc = self._read_first_line(os.path.join(self.RESCUE_GADGET, 'UDC'))
                    return '%s%s' % (name, ' bound' if udc else ' unbound')
        return ''

    def _ssh_listening(self):
        rc, stdout, stderr = self._run_command([
            'sh', '-c',
            'ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null || true'
        ], timeout=5)
        text = stdout or stderr
        return bool(re.search(r'(^|\s)(0\.0\.0\.0:|\*:|:::)?22\s', text or ''))

    def _repair_with_sudo(self, install):
        script = self._sudo_install_script(install)
        path = self._write_temp_script('install', script)
        if not path:
            return False
        rc, stdout, stderr = self._run_command(['sudo', '/bin/sh', path], timeout=30)
        return rc == 0

    def _sudo_install_script(self, install):
        return (
            '#!/bin/sh\n'
            'set -u\n'
            'backup() {\n'
            '    if [ -e "$1" ]; then cp -p "$1" "$1.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true; fi\n'
            '}\n'
            'mkdir -p /usr/local/sbin /etc/systemd/system '
            '/etc/systemd/system/multi-user.target.wants /etc/init.d '
            '/etc/rc2.d /etc/rc3.d /etc/rc4.d /etc/rc5.d /var/log\n'
            'backup /usr/local/sbin/icopy-rescue-net.sh\n'
            'backup /etc/systemd/system/icopy-rescue-net.service\n'
            'backup /etc/init.d/icopy-rescue-net\n'
            "cat > /usr/local/sbin/icopy-rescue-net.sh <<'ICOPY_RESCUE_NET_SCRIPT'\n"
            + install._rescue_net_script() +
            'ICOPY_RESCUE_NET_SCRIPT\n'
            'chmod 755 /usr/local/sbin/icopy-rescue-net.sh\n'
            "cat > /etc/systemd/system/icopy-rescue-net.service <<'ICOPY_RESCUE_UNIT'\n"
            + install._rescue_net_systemd_unit() +
            'ICOPY_RESCUE_UNIT\n'
            'chmod 644 /etc/systemd/system/icopy-rescue-net.service\n'
            "cat > /etc/init.d/icopy-rescue-net <<'ICOPY_RESCUE_INIT'\n"
            + install._rescue_net_init_script() +
            'ICOPY_RESCUE_INIT\n'
            'chmod 755 /etc/init.d/icopy-rescue-net\n'
            'ln -sf ../icopy-rescue-net.service '
            '/etc/systemd/system/multi-user.target.wants/icopy-rescue-net.service\n'
            'for rc in 2 3 4 5; do '
            'ln -sf ../init.d/icopy-rescue-net /etc/rc${rc}.d/S01icopy-rescue-net; '
            'done\n'
            'echo 1 > /etc/icopy-rescue-net.enabled\n'
            'echo "repaired by USB SSH plugin $(date)" > /var/log/icopy-rescue-net-install.log\n'
            'systemctl daemon-reload >/dev/null 2>&1 || true\n'
            'nohup /usr/local/sbin/icopy-rescue-net.sh restart '
            '>/tmp/icopy-rescue-net.out 2>&1 &\n'
        )

    def _rollback_script(self):
        return (
            '#!/bin/sh\n'
            'restored=0\n'
            'restore_latest() {\n'
            '    target="$1"\n'
            '    latest="$(ls -1t "$target".bak-* 2>/dev/null | head -n 1)"\n'
            '    if [ -n "$latest" ]; then\n'
            '        cp -p "$latest" "$target" || exit 1\n'
            '        restored=1\n'
            '    fi\n'
            '}\n'
            'restore_latest /usr/local/sbin/icopy-rescue-net.sh\n'
            'restore_latest /etc/systemd/system/icopy-rescue-net.service\n'
            'restore_latest /etc/init.d/icopy-rescue-net\n'
            '[ "$restored" = "1" ] || { echo "no .bak-* files found"; exit 4; }\n'
            'chmod 755 /usr/local/sbin/icopy-rescue-net.sh 2>/dev/null || true\n'
            'chmod 644 /etc/systemd/system/icopy-rescue-net.service 2>/dev/null || true\n'
            'chmod 755 /etc/init.d/icopy-rescue-net 2>/dev/null || true\n'
            'ln -sf ../icopy-rescue-net.service '
            '/etc/systemd/system/multi-user.target.wants/icopy-rescue-net.service '
            '2>/dev/null || true\n'
            'touch /etc/icopy-rescue-net.enabled\n'
            'systemctl daemon-reload >/dev/null 2>&1 || true\n'
            'nohup /usr/local/sbin/icopy-rescue-net.sh restart '
            '>/tmp/icopy-rescue-net.out 2>&1 &\n'
        )

    def _schedule_restart(self):
        install = self._load_install_module()
        helper = getattr(install, '_schedule_rescue_net_restart', None) if install else None
        if callable(helper):
            try:
                helper(delay=2)
                return True
            except Exception:
                pass
        rc, stdout, stderr = self._run_command([
            'sudo', 'sh', '-c',
            'nohup /usr/local/sbin/icopy-rescue-net.sh restart '
            '>/tmp/icopy-rescue-net.out 2>&1 &'
        ], timeout=8)
        return rc == 0

    def _load_install_module(self):
        try:
            import install
            if hasattr(install, '_rescue_net_script'):
                return install
        except Exception:
            pass

        candidates = []
        here = os.path.abspath(os.path.dirname(__file__))
        app_root = os.path.dirname(os.path.dirname(here))
        candidates.append(os.path.join(app_root, 'main', 'install.py'))
        candidates.append(os.path.join(app_root, 'src', 'main', 'install.py'))

        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    'usb_ssh_install_helpers', path)
                module = importlib.util.module_from_spec(spec)
                sys.modules.pop('usb_ssh_install_helpers', None)
                spec.loader.exec_module(module)
                if hasattr(module, '_rescue_net_script'):
                    return module
            except Exception:
                pass
        return None

    def _write_temp_script(self, prefix, content):
        path = '/tmp/icopy-usb-ssh-%s-%s-%s.sh' % (
            prefix, os.getpid(), int(time.time()))
        try:
            with open(path, 'w') as handle:
                handle.write(content)
            os.chmod(path, 0o755)
            return path
        except Exception:
            return ''

    def _done_text(self, lines):
        result = list(lines)
        result.append('')
        result.append('Connect after USB settles:')
        result.append('ssh root@169.254.7.2')
        result.append('ssh root@192.168.7.2')
        return '\n'.join(result)

    def _error(self, message):
        self._set_var('error_msg', message)
        return {'status': 'error', 'error_msg': message}

    def _path_exists(self, path):
        return os.path.exists(path)

    def _path_executable(self, path):
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def _read_text(self, path):
        try:
            with open(path, 'r') as handle:
                return handle.read()
        except Exception:
            return ''

    def _read_first_line(self, path):
        text = self._read_text(path).strip()
        return text.splitlines()[0] if text else ''

    def _list_names(self, path):
        try:
            return sorted(os.listdir(path))
        except Exception:
            return []

    def _run_command(self, cmd, timeout=10):
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

    def _set_var(self, key, value):
        if self.host is not None and hasattr(self.host, 'set_var'):
            self.host.set_var(key, value)

    def _progress(self, value, message):
        if self.host is not None and hasattr(self.host, 'set_progress'):
            self.host.set_progress(value, message)
