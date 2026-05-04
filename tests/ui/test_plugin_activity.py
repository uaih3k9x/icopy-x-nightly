"""Tests for PluginActivity — JSON-driven plugin runner.

Covers:
  - PWR enforcement (CRITICAL): PWR always exits, never reaches plugin
  - Key dispatch: M1 finish, OK set_state, title rendering
  - State transitions: set_state renders new screen
  - Plugin helpers: set_var/get_var, show_toast

All tests run headless via MockCanvas and actstack._canvas_factory.
"""

import pytest

from tests.ui.conftest import MockCanvas
import actstack
from _constants import (
    CHECK_BOX_SIZE,
    CHECK_COLOR_CHECKED_FILL,
    CONTENT_Y0,
    KEY_PWR,
    KEY_UP,
    KEY_DOWN,
    KEY_OK,
    KEY_M1,
    KEY_M2,
    LIST_ITEM_H,
)
from plugin_activity import PluginActivity


# =====================================================================
# Test data
# =====================================================================

TEST_UI = {
    'initial_state': 'main',
    'states': {
        'main': {
            'screen': {
                'title': 'Test Plugin',
                'content': {'type': 'text', 'lines': [{'text': 'Hello'}]},
                'buttons': {'left': 'Back', 'right': None},
                'keys': {'M1': 'finish', 'OK': 'set_state:second'},
            },
        },
        'second': {
            'screen': {
                'title': 'Second',
                'content': {'type': 'text', 'lines': [{'text': 'Page 2'}]},
                'buttons': {'left': 'Back', 'right': None},
                'keys': {'M1': 'set_state:main'},
            },
        },
    },
}


class MockPlugin(object):
    """Mock entry class for testing run: action dispatch."""

    def __init__(self, host=None):
        self.host = host
        self.called = []

    def test_method(self):
        self.called.append('test_method')
        return {'status': 'done'}

    def onKeyEvent(self, key):
        """Spy: records any keys that reach the plugin."""
        self.called.append(('onKeyEvent', key))


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(autouse=True)
def reset_actstack():
    """Reset actstack state before each test."""
    actstack._reset()
    actstack._canvas_factory = lambda: MockCanvas()
    yield
    actstack._reset()


def _make_bundle(ui=None, entry_class=None, plugin_key='test_plugin'):
    """Build a standard PluginActivity bundle."""
    return {
        'plugin_dir': '/tmp/test_plugin',
        'manifest': {'name': 'Test', 'version': '1.0.0', 'permissions': ['pm3']},
        'ui_definition': ui if ui is not None else TEST_UI,
        'entry_class': entry_class,
        'plugin_key': plugin_key,
    }


def _start_plugin(ui=None, entry_class=None):
    """Start a PluginActivity with test defaults."""
    bundle = _make_bundle(ui=ui, entry_class=entry_class)
    return actstack.start_activity(PluginActivity, bundle)


# =====================================================================
# TestPWREnforcement (CRITICAL)
# =====================================================================

class TestPWREnforcement:
    """PWR ALWAYS EXITS. This is the #1 law."""

    def test_pwr_finishes_activity(self):
        """Sending PWR pops the PluginActivity from the stack."""
        act = _start_plugin()
        assert actstack.get_stack_size() == 1
        act.callKeyEvent(KEY_PWR)
        assert actstack.get_stack_size() == 0

    def test_pwr_never_reaches_plugin(self):
        """PWR is intercepted by the framework; plugin never sees it."""
        act = _start_plugin(entry_class=MockPlugin)
        instance = act._plugin_instance
        assert instance is not None

        # Replace the plugin's onKeyEvent to detect if called
        spy_calls = []

        original_onKey = act.onKeyEvent

        def patched_onKey(key):
            # This wraps the real onKeyEvent; the real one intercepts PWR
            original_onKey(key)

        act.callKeyEvent(KEY_PWR)

        # The plugin instance's onKeyEvent should never be called.
        # PluginActivity.onKeyEvent intercepts PWR before any dispatch.
        assert ('onKeyEvent', KEY_PWR) not in instance.called

    def test_pwr_dismisses_toast_first(self):
        """If a toast is showing, first PWR dismisses it; activity stays alive."""
        act = _start_plugin()
        assert actstack.get_stack_size() == 1

        # Simulate a visible toast
        class FakeToast:
            def __init__(self):
                self._showing = True

            def isShow(self):
                return self._showing

            def cancel(self):
                self._showing = False

        act._toast = FakeToast()

        # First PWR should dismiss the toast, not finish
        act.callKeyEvent(KEY_PWR)
        assert actstack.get_stack_size() == 1
        assert not act._toast.isShow()

        # Second PWR should finish (no toast visible now)
        act.callKeyEvent(KEY_PWR)
        assert actstack.get_stack_size() == 0


# =====================================================================
# TestKeyDispatch
# =====================================================================

class TestKeyDispatch:
    """Key dispatch routes actions from screen key bindings."""

    def test_m1_finish_action(self):
        """M1 triggers 'finish', activity is popped from stack."""
        act = _start_plugin()
        assert actstack.get_stack_size() == 1
        act.callKeyEvent(KEY_M1)
        assert actstack.get_stack_size() == 0

    def test_ok_set_state(self):
        """OK triggers 'set_state:second', screen changes."""
        act = _start_plugin()
        assert act._current_state_id == 'main'
        act.callKeyEvent(KEY_OK)
        assert act._current_state_id == 'second'

    def test_title_from_screen(self):
        """Title is set from the screen definition."""
        act = _start_plugin()
        # After onCreate, the title should be set to the plugin name
        # (the setTitle call in onCreate uses the manifest name).
        # The screen title is set during _render_current_screen.
        canvas = act.getCanvas()
        # Find title text items
        text_items = canvas.find_withtag('tags_title_text')
        assert len(text_items) > 0
        title_text = canvas.itemcget(text_items[0], 'text')
        # Plugin onCreate sets title to manifest name first,
        # then _render_current_screen may override with screen title
        assert title_text in ('Test', 'Test Plugin')


# =====================================================================
# TestStateTransitions
# =====================================================================

class TestStateTransitions:
    """State machine transitions render new screens."""

    def test_set_state_renders_new_screen(self):
        """set_state navigates to new state and re-renders."""
        act = _start_plugin()
        assert act._current_state_id == 'main'

        # Navigate to second screen
        act._set_state('second')
        assert act._current_state_id == 'second'

        # Navigate back
        act._set_state('main')
        assert act._current_state_id == 'main'


# =====================================================================
# TestScrollableText
# =====================================================================

class TestScrollableText:
    """Scrollable plugin text pages use UP/DOWN when keys are unbound."""

    def test_up_down_scrolls_scrollable_text_output(self):
        ui = {
            'initial_state': 'main',
            'states': {
                'main': {
                    'screen': {
                        'title': 'Output',
                        'content': {
                            'type': 'text',
                            'scrollable': True,
                            'page_size': 3,
                            'lines': [
                                {'text': 'Line 0\nLine 1\nLine 2\nLine 3\nLine 4'},
                            ],
                        },
                        'buttons': {'left': 'Back', 'right': None},
                        'keys': {'M1': 'finish'},
                    },
                },
            },
        }

        act = _start_plugin(ui=ui)
        canvas = act.getCanvas()
        assert 'Line 0' in canvas.get_all_text()
        assert 'Line 3' not in canvas.get_all_text()

        act.callKeyEvent(KEY_DOWN)
        texts = canvas.get_all_text()
        assert act._text_scroll_state['main'] == 1
        assert 'Line 0' not in texts
        assert 'Line 1' in texts
        assert 'Line 3' in texts

        act.callKeyEvent(KEY_UP)
        texts = canvas.get_all_text()
        assert act._text_scroll_state['main'] == 0
        assert 'Line 0' in texts
        assert 'Line 3' not in texts

    def test_default_scroll_page_stays_clear_of_softkeys(self):
        ui = {
            'initial_state': 'main',
            'states': {
                'main': {
                    'screen': {
                        'title': 'Output',
                        'content': {
                            'type': 'text',
                            'scrollable': True,
                            'lines': [
                                {'text': '\n'.join('Line %d' % i for i in range(12))},
                            ],
                        },
                        'buttons': {'left': 'Back', 'right': 'Off'},
                        'keys': {'M1': 'finish'},
                    },
                },
            },
        }

        act = _start_plugin(ui=ui)
        texts = act.getCanvas().get_all_text()
        assert 'Line 7' in texts
        assert 'Line 8' not in texts
        assert 'Back' in texts
        assert 'Off' in texts

        act.callKeyEvent(KEY_DOWN)
        texts = act.getCanvas().get_all_text()
        assert act._text_scroll_state['main'] == 1
        assert 'Line 8' in texts

    def test_long_scrollable_text_wraps_before_paging(self):
        ui = {
            'initial_state': 'main',
            'states': {
                'main': {
                    'screen': {
                        'title': 'Output',
                        'content': {
                            'type': 'text',
                            'scrollable': True,
                            'lines': [
                                {'text': '%s\nTail marker' % ('0123456789' * 30)},
                            ],
                        },
                        'buttons': {'left': 'Back', 'right': 'Off'},
                        'keys': {'M1': 'finish'},
                    },
                },
            },
        }

        act = _start_plugin(ui=ui)
        assert 'Tail marker' not in act.getCanvas().get_all_text()

        act.callKeyEvent(KEY_DOWN)
        act.callKeyEvent(KEY_DOWN)
        assert 'Tail marker' in act.getCanvas().get_all_text()

    def test_explicit_up_down_binding_wins_over_default_text_scroll(self):
        ui = {
            'initial_state': 'main',
            'states': {
                'main': {
                    'screen': {
                        'title': 'Output',
                        'content': {
                            'type': 'text',
                            'scrollable': True,
                            'page_size': 2,
                            'lines': [{'text': 'Line 0\nLine 1\nLine 2'}],
                        },
                        'buttons': {'left': 'Back', 'right': None},
                        'keys': {'DOWN': 'set_state:other'},
                    },
                },
                'other': {
                    'screen': {
                        'title': 'Other',
                        'content': {'type': 'text', 'lines': [{'text': 'Other'}]},
                        'buttons': {'left': 'Back', 'right': None},
                    },
                },
            },
        }

        act = _start_plugin(ui=ui)
        act.callKeyEvent(KEY_DOWN)

        assert act._current_state_id == 'other'
        assert act._text_scroll_state.get('main', 0) == 0


# =====================================================================
# TestListSelectionState
# =====================================================================

class TestListSelectionState:
    """JSON list screens can mirror selection into plugin variables."""

    def test_selected_item_updates_vars_and_radio_check(self):
        ui = {
            'initial_state': 'main',
            'states': {
                'main': {
                    'screen': {
                        'title': '{dump_type}',
                        'content': {
                            'type': 'list',
                            'style': 'radio',
                            'selected': 0,
                            'selected_var': 'dump_type_key',
                            'selected_label_var': 'dump_type',
                            'checked_by_selection': True,
                            'items': [
                                {'label': 'Mifare Classic', 'value': 'mf1'},
                                {'label': 'Ultralight/NTAG', 'value': 'mfu'},
                            ],
                        },
                        'buttons': {'left': 'Back', 'right': '{dump_type}'},
                        'keys': {'DOWN': 'scroll:1'},
                    },
                },
            },
        }

        act = _start_plugin(ui=ui)
        assert act.get_var('dump_type_key') == 'mf1'
        assert act.get_var('dump_type') == 'Mifare Classic'
        assert 'Mifare Classic' in act.getCanvas().get_all_text()

        checked = [
            item for _iid, item in act.getCanvas().get_items_by_type('rectangle')
            if item['options'].get('fill') == CHECK_COLOR_CHECKED_FILL
        ]
        assert len(checked) == 1
        assert checked[0]['coords'][1] == (
            CONTENT_Y0 + LIST_ITEM_H // 2 - CHECK_BOX_SIZE // 2
        )

        act.callKeyEvent(KEY_DOWN)
        assert act.get_var('dump_type_key') == 'mfu'
        assert act.get_var('dump_type') == 'Ultralight/NTAG'
        assert 'Ultralight/NTAG' in act.getCanvas().get_all_text()

        checked = [
            item for _iid, item in act.getCanvas().get_items_by_type('rectangle')
            if item['options'].get('fill') == CHECK_COLOR_CHECKED_FILL
        ]
        assert len(checked) == 1
        assert checked[0]['coords'][1] == (
            CONTENT_Y0 + LIST_ITEM_H + LIST_ITEM_H // 2 - CHECK_BOX_SIZE // 2
        )


# =====================================================================
# TestSoftkeyRendering
# =====================================================================

class TestSoftkeyRendering:
    """PluginActivity owns softkeys so JSON buttons are not double-drawn."""

    def test_softkeys_render_once_via_base_activity(self):
        act = _start_plugin()
        canvas = act.getCanvas()

        assert canvas.find_withtag('_jr_buttons') == ()

        left_ids = canvas.find_withtag('tags_btn_left')
        assert len(left_ids) == 1
        assert canvas.itemcget(left_ids[0], 'text') == 'Back'

    def test_softkey_active_state_from_dict_button(self):
        ui = {
            'initial_state': 'main',
            'states': {
                'main': {
                    'screen': {
                        'title': 'Buttons',
                        'content': {'type': 'text',
                                    'lines': [{'text': 'Hello'}]},
                        'buttons': {
                            'left': {'text': 'Back', 'active': False},
                            'right': {'text': 'Again', 'active': True},
                        },
                    },
                },
            },
        }
        act = _start_plugin(ui=ui)
        canvas = act.getCanvas()

        assert canvas.find_withtag('_jr_buttons') == ()
        assert len(canvas.find_withtag('tags_btn_left')) == 1
        assert len(canvas.find_withtag('tags_btn_right')) == 1
        assert act._m1_active is False
        assert act._m2_active is True


# =====================================================================
# TestPluginHelpers
# =====================================================================

class TestPluginHelpers:
    """Tests for helper methods exposed to plugin code."""

    def test_set_var_get_var(self):
        """set_var stores and get_var retrieves state variables."""
        act = _start_plugin()
        act.set_var('test_key', 'test_value')
        assert act.get_var('test_key') == 'test_value'
        assert act.get_var('nonexistent', 'default') == 'default'

    def test_show_toast_creates_canvas_items(self):
        """show_toast creates visible items on the canvas."""
        act = _start_plugin()
        canvas = act.getCanvas()
        items_before = len(canvas.find_all())
        # show_toast creates a Toast widget and calls show()
        # which creates canvas items (mask, text, etc.)
        act.show_toast('Hello World', timeout=3000)
        items_after = len(canvas.find_all())
        # Toast should add at least one canvas item
        assert items_after > items_before
