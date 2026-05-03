"""Tests for batteryui title-bar status polling."""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from lib import batteryui


class FakeBatteryBar:
    def __init__(self):
        self.battery = None
        self.charging = None
        self.destroyed = False

    def setBattery(self, value):
        self.battery = value

    def setCharging(self, value):
        self.charging = value

    def isDestroy(self):
        return self.destroyed


class FakeWiFiIndicator:
    def __init__(self):
        self.signal = 'unset'
        self.destroyed = False

    def setSignal(self, value):
        self.signal = value

    def isDestroy(self):
        return self.destroyed


def setup_function(_func):
    batteryui._reset_for_tests()


def teardown_function(_func):
    batteryui._reset_for_tests()


def test_read_wifi_signal_from_proc_wireless(tmp_path):
    path = tmp_path / "wireless"
    path.write_text(
        "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
        " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
        " wlan0: 0000   35.  -55.  -256        0      0      0      0      0        0\n"
    )

    assert batteryui._read_wifi_signal(str(path)) == 50


def test_read_wifi_signal_returns_none_without_link(tmp_path):
    path = tmp_path / "wireless"
    path.write_text(
        "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
        " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
        " wlan0: 0000    0.  -256  -256        0      0      0      0      0        0\n"
    )

    assert batteryui._read_wifi_signal(str(path)) is None


def test_update_views_pushes_wifi_signal():
    bar = FakeBatteryBar()
    wifi = FakeWiFiIndicator()

    batteryui.register(bar, wifi)
    batteryui.__update_views(77, True, 86)

    assert bar.battery == 77
    assert bar.charging is True
    assert wifi.signal == 86
