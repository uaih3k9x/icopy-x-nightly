#!/usr/bin/env python3
"""QEMU-friendly iCopy-X app runner with keyfile input.

This script runs inside the emulated ARM Python environment.  It starts a
small background reader that watches ICOPY_KEY_FILE for logical key names and
dispatches them through keymap.key.onKey(), then launches the normal app
startup path.
"""

import os
import sys
import threading
import time


DEFAULT_KEY_FILE = '/tmp/icopy_web_keys.txt'
VALID_KEYS = {
    'UP', 'DOWN', 'LEFT', 'RIGHT', 'OK', 'M1', 'M2', 'PWR', 'ALL',
}
VALID_COMMANDS = {'RELOAD_PLUGINS'}


def _reload_plugins():
    """Reload plugin metadata/code in the running app process."""
    try:
        from lib import actmain
        plugins = actmain.reload_plugins()
        print('[WEBCTL] reloaded %d plugin(s)' % len(plugins), flush=True)
    except Exception as exc:
        print('[WEBCTL] reload plugins failed: %s' % exc, flush=True)


def _read_keys(key_file):
    """Tail key_file and dispatch logical keys to the active activity."""
    last_pos = 0
    while True:
        try:
            if os.path.exists(key_file):
                size = os.path.getsize(key_file)
                if size < last_pos:
                    last_pos = 0

                with open(key_file, 'r') as handle:
                    handle.seek(last_pos)
                    for line in handle:
                        key = line.strip().upper()
                        if not key or key.startswith('#'):
                            continue
                        if key in VALID_COMMANDS:
                            if key == 'RELOAD_PLUGINS':
                                _reload_plugins()
                            continue
                        if key not in VALID_KEYS:
                            print('[WEBKEY] ignored %s' % key, flush=True)
                            continue
                        try:
                            from lib import keymap
                            keymap.key.onKey(key)
                            print('[WEBKEY] %s' % key, flush=True)
                        except Exception as exc:
                            print('[WEBKEY] dispatch failed: %s' % exc, flush=True)
                    last_pos = handle.tell()
        except Exception as exc:
            print('[WEBKEY] reader error: %s' % exc, flush=True)
        time.sleep(0.08)


def main():
    app_dir = os.environ.get('ICOPY_APP_DIR')
    if not app_dir:
        app_dir = os.getcwd()

    main_dir = os.path.join(app_dir, 'main')
    lib_dir = os.path.join(app_dir, 'lib')
    for path in (main_dir, lib_dir):
        if path not in sys.path:
            sys.path.append(path)

    key_file = os.environ.get('ICOPY_KEY_FILE', DEFAULT_KEY_FILE)
    threading.Thread(
        target=_read_keys,
        args=(key_file,),
        daemon=True,
        name='icopy_web_keys',
    ).start()
    print('[WEBKEY] ready %s' % key_file, flush=True)

    from main import main as app_main
    app_main.main()


if __name__ == '__main__':
    main()
