"""Tests for post-update USB/SSH recovery scheduling."""

import importlib.util
import os
import sys


def _load_install_module():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'src', 'main', 'install.py')
    spec = importlib.util.spec_from_file_location('install_under_test', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop('install_under_test', None)
    spec.loader.exec_module(module)
    return module


def test_usb_ssh_recovery_script_restarts_rescue_net_and_ssh():
    install = _load_install_module()

    script = install._usb_ssh_recovery_script()

    assert script.startswith('#!/bin/sh\n')
    assert '/usr/local/sbin/icopy-rescue-net.sh restart' in script
    assert '192.168.7.2/24' in script
    assert '169.254.7.2/16' in script
    assert 'systemctl restart sshd' in script
    assert '/tmp/icopy-update-usb-ssh-recover.log' in script


def test_rescue_net_script_is_ncm_first_with_link_local():
    install = _load_install_module()

    script = install._rescue_net_script()

    assert script.startswith('#!/bin/sh\n')
    assert 'USB_CIDR=192.168.7.2/24' in script
    assert 'USB_LL_CIDR=169.254.7.2/16' in script
    assert 'start_usb_ncm_configfs && return 0' in script
    assert 'start_usb_ecm_configfs && return 0' in script
    assert 'start_usb_ether_module' in script
    assert 'start_sshd' in script


def test_rescue_net_service_units_enable_bootstrap():
    install = _load_install_module()

    unit = install._rescue_net_systemd_unit()
    initd = install._rescue_net_init_script()

    assert 'Before=multi-user.target icopy.service' in unit
    assert '/usr/local/sbin/icopy-rescue-net.sh start' in unit
    assert 'Default-Start:     2 3 4 5' in initd
    assert 'icopy-rescue-net.sh restart' in initd


def test_schedule_usb_ssh_recovery_uses_systemd_run(monkeypatch, tmp_path):
    install = _load_install_module()
    script_path = tmp_path / 'recover.sh'
    commands = []

    def fake_system(cmd):
        commands.append(cmd)
        return 0

    monkeypatch.setattr(install, '_usb_ssh_recovery_script',
                        lambda: '#!/bin/sh\necho ok\n')
    monkeypatch.setattr(install, 'os', install.os)
    monkeypatch.setattr(install.os, 'getpid', lambda: 1234)
    monkeypatch.setattr(install.time, 'time', lambda: 5678)
    monkeypatch.setattr(install.os, 'system', fake_system)
    monkeypatch.setattr(install.os, 'chmod', lambda path, mode: None)
    monkeypatch.setattr(install, 'open',
                        lambda path, mode: open(script_path, mode),
                        raising=False)

    install._schedule_usb_ssh_recovery()

    assert script_path.read_text() == '#!/bin/sh\necho ok\n'
    assert commands == [
        'sudo systemd-run --unit=icopy-update-usb-ssh-recover-1234-5678 '
        '--collect /bin/sh /tmp/icopy-update-usb-ssh-recover-1234-5678.sh '
        '>/tmp/icopy-update-usb-ssh-schedule.log 2>&1'
    ]
