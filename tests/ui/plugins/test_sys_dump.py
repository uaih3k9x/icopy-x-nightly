"""Tests for the SysDump diagnostic plugin self-check summary."""

from plugins.sys_dump.plugin import SysDumpPlugin


class FakeSysDump(SysDumpPlugin):
    def __init__(self, files=None, dirs=None, executable=None, commands=None):
        super(FakeSysDump, self).__init__(host=None)
        self.files = files or {}
        self.dirs = dirs or {}
        self.executable = set(executable or [])
        self.commands = commands or []
        self.command_log = []

    def _path_exists(self, path):
        return path in self.files or path in self.dirs or path in self.executable

    def _path_executable(self, path):
        return path in self.executable

    def _read_text(self, path):
        return self.files.get(path, '')

    def _list_names(self, path):
        return sorted(self.dirs.get(path, []))

    def _run_command(self, cmd, timeout):
        text = self._cmd_to_text(cmd)
        self.command_log.append(text)
        for marker, result in self.commands:
            if marker in text:
                return result
        return 1, '', 'missing fake command: %s' % text


def test_self_checks_report_healthy_usb_ncm_stack():
    plugin = FakeSysDump(
        files={
            '/sys/class/net/usb0/operstate': 'up\n',
            '/sys/class/net/usb0/carrier': '1\n',
            '/sys/kernel/config/usb_gadget/icopy_rescue/UDC': '20980000.usb\n',
            '/proc/modules': '',
        },
        dirs={
            '/sys/kernel/config/usb_gadget/icopy_rescue': [],
            '/sys/kernel/config/usb_gadget/icopy_rescue/functions': ['ncm.usb0'],
            '/sys/kernel/config/usb_gadget/icopy_rescue/configs/c.1': ['ncm.usb0'],
        },
        executable=['/usr/local/sbin/icopy-rescue-net.sh'],
        commands=[
            ('systemctl is-active', (0, 'active\n', '')),
            ('ip -o -4 addr show dev usb0', (
                0,
                '2: usb0    inet 192.168.7.2/24 brd 192.168.7.255 scope global usb0\n',
                '',
            )),
            ('ss -ltn', (0, 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n', '')),
            ('dmesg', (0, '[  1.0] ncm usb0 ready\n', '')),
        ],
    )

    checks = plugin._run_self_checks(['lo', 'usb0'])
    summary = plugin._format_summary_checks(checks)

    assert summary.startswith('Self check: PASS')
    assert '[PASS] usb0 IP: 192.168.7.2/24' in summary
    assert '[PASS] SSH: listening on port 22' in summary
    assert '[PASS] USB gadget:' in summary


def test_self_checks_surface_actionable_failures_first():
    plugin = FakeSysDump(
        files={'/proc/modules': ''},
        commands=[
            ('ss -ltn', (0, '', '')),
            ('ps w', (1, '', '')),
            ('dmesg', (0, '[  2.0] configfs usb_gadget is unavailable\n', '')),
        ],
    )

    checks = plugin._run_self_checks(['lo'])
    summary = plugin._format_summary_checks(checks)

    assert summary.startswith('Self check: FAIL')
    assert '[FAIL] usb0: interface missing' in summary
    assert '[FAIL] SSH: no sshd/dropbear listener seen' in summary
    assert '[WARN] Rescue script:' in summary
    assert '[WARN] dmesg USB:' in summary
