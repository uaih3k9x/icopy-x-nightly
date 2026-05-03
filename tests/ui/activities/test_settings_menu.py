"""Tests for SettingsMenuActivity."""

import sys
import types

import pytest

from tests.ui.conftest import MockCanvas
import actstack
from _constants import KEY_DOWN, KEY_OK, KEY_M1
from lib import resources


class MockSettings:
    def __init__(self):
        self.screen_mirror = 0
        self.language = 'en'

    def getScreenMirror(self):
        return self.screen_mirror

    def setScreenMirror(self, value):
        self.screen_mirror = int(value)

    def getLanguage(self):
        return self.language

    def setLanguage(self, value):
        self.language = str(value)


@pytest.fixture(autouse=True)
def _setup():
    actstack._reset()
    actstack._canvas_factory = lambda: MockCanvas()
    resources.setLanguage(0)
    yield
    resources.setLanguage(0)
    actstack._reset()


@pytest.fixture
def mock_settings(monkeypatch):
    settings = MockSettings()
    mod = types.ModuleType('settings')
    mod.getScreenMirror = settings.getScreenMirror
    mod.setScreenMirror = settings.setScreenMirror
    mod.getLanguage = settings.getLanguage
    mod.setLanguage = settings.setLanguage
    monkeypatch.setitem(sys.modules, 'settings', mod)
    return settings


def _start_settings():
    from activity_main import SettingsMenuActivity
    return actstack.start_activity(SettingsMenuActivity)


class TestSettingsMenuActivity:
    def test_shows_language_row(self, mock_settings):
        act = _start_settings()
        texts = act.getCanvas().get_all_text()
        assert 'Settings' in texts
        assert 'Mirror Screen?' in texts
        assert 'Language' in texts
        assert 'English' in texts

    def test_ok_toggles_screen_mirror(self, mock_settings):
        act = _start_settings()
        assert mock_settings.screen_mirror == 0
        act.onKeyEvent(KEY_OK)
        assert mock_settings.screen_mirror == 1
        act.onKeyEvent(KEY_OK)
        assert mock_settings.screen_mirror == 0

    def test_language_toggle_updates_resources_and_redraws(self, mock_settings):
        act = _start_settings()
        act.onKeyEvent(KEY_DOWN)
        act.onKeyEvent(KEY_OK)

        assert mock_settings.language == 'zh'
        assert resources.getLanguage() == 1
        texts = act.getCanvas().get_all_text()
        assert '设置' in texts
        assert '语言' in texts
        assert '中文' in texts

    def test_m1_finishes(self, mock_settings):
        act = _start_settings()
        assert actstack.get_current_activity() is act
        act.onKeyEvent(KEY_M1)
        assert actstack.get_stack_size() == 0
