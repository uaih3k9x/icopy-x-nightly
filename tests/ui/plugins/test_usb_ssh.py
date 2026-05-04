"""Tests for the USB SSH maintenance plugin."""

from plugins.usb_ssh.plugin import UsbSshPlugin


class FakeHost(object):
    def __init__(self):
        self.vars = {}
        self.progress = []

    def set_var(self, key, value):
        self.vars[key] = value

    def set_progress(self, value, message):
        self.progress.append((value, message))


class FakeUsbSsh(UsbSshPlugin):
    def __init__(self, files=None, dirs=None, executable=None, commands=None):
        super(FakeUsbSsh, self).__init__(host=FakeHost())
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

    def _run_command(self, cmd, timeout=10):
        text = ' '.join(cmd) if isinstance(cmd, list) else cmd
        self.command_log.append(text)
        for marker, result in self.commands:
            if marker in text:
                return result
        return 1, '', 'missing fake command: %s' % text


def test_status_reports_healthy_usb_ssh_stack():
    plugin = FakeUsbSsh(
        files={
            '/etc/icopy-rescue-net.enabled': '1\n',
            '/sys/class/net/usb0/carrier': '1\n',
            '/sys/kernel/config/usb_gadget/icopy_rescue/UDC': '20980000.usb\n',
        },
        dirs={
            '/sys/class/net/usb0': [],
            '/sys/kernel/config/usb_gadget/icopy_rescue/functions': ['ncm.usb0'],
            '/sys/kernel/config/usb_gadget/icopy_rescue/configs/c.1': ['ncm.usb0'],
        },
        executable=['/usr/local/sbin/icopy-rescue-net.sh'],
        commands=[
            ('systemctl is-active', (0, 'active\n', '')),
            ('ip -o -4 addr show dev usb0', (
                0,
                '2: usb0 inet 192.168.7.2/24 scope global usb0\n'
                '2: usb0 inet 169.254.7.2/16 scope global usb0\n',
                '',
            )),
            ('ss -ltn', (0, 'LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n', '')),
        ],
    )

    result = plugin.do_status()
    text = plugin.host.vars['status_text']

    assert result == {'status': 'status'}
    assert 'Service: installed' in text
    assert 'Boot: enabled' in text
    assert '192.168.7.2/24' in text
    assert '169.254.7.2/16' in text
    assert 'Gadget: ncm.usb0 bound' in text
    assert 'SSH: listening' in text


def test_repair_uses_install_helper_when_available():
    class FakeInstall(object):
        def __init__(self):
            self.calls = []

        def _install_rescue_net_service(self, **kwargs):
            self.calls.append(kwargs)
            return True

    fake_install = FakeInstall()
    plugin = FakeUsbSsh()
    plugin._load_install_module = lambda: fake_install

    result = plugin.do_repair()

    assert result == {'status': 'done'}
    assert fake_install.calls == [{
        'enable': True,
        'restart': True,
        'backup': True,
    }]
    assert 'USB SSH service repaired.' in plugin.host.vars['result_text']


def test_disable_runs_service_disable_action():
    plugin = FakeUsbSsh(
        executable=['/usr/local/sbin/icopy-rescue-net.sh'],
        commands=[
            ('sudo /usr/local/sbin/icopy-rescue-net.sh disable', (0, '', '')),
        ],
    )

    result = plugin.do_disable()

    assert result == {'status': 'done'}
    assert 'sudo /usr/local/sbin/icopy-rescue-net.sh disable' in plugin.command_log
