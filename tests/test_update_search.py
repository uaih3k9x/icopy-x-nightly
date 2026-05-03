"""Tests for updater IPK discovery."""

import importlib.util
import os
import sys
import time
import zipfile


def _load_update_module():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'src', 'middleware', 'update.py')
    spec = importlib.util.spec_from_file_location('update_under_test', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop('update_under_test', None)
    spec.loader.exec_module(module)
    return module


def _write_ipk(path, valid=True):
    if not valid:
        with open(path, 'wb') as fh:
            fh.write(b'not a zip')
        return

    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('app.py', '')
        zf.writestr('lib/version.so', b'')
        zf.writestr('main/install.so', b'')


def test_search_ignores_macos_appledouble_ipk(tmp_path):
    update = _load_update_module()
    sidecar = tmp_path / '._icopy-x-oss.ipk'
    real = tmp_path / 'icopy-x-oss.ipk'
    _write_ipk(str(sidecar), valid=False)
    _write_ipk(str(real), valid=True)

    found = update.search(str(tmp_path))

    assert found == str(real)
    assert update.checkPkg() is True


def test_search_ignores_hidden_ipk(tmp_path):
    update = _load_update_module()
    hidden = tmp_path / '.staged.ipk'
    real = tmp_path / 'icopy-x-oss.ipk'
    _write_ipk(str(hidden), valid=True)
    _write_ipk(str(real), valid=True)

    assert update.search(str(tmp_path)) == str(real)


def test_search_picks_newest_visible_ipk(tmp_path):
    update = _load_update_module()
    old = tmp_path / 'old.ipk'
    new = tmp_path / 'new.ipk'
    _write_ipk(str(old), valid=True)
    _write_ipk(str(new), valid=True)
    now = time.time()
    os.utime(str(old), (now - 60, now - 60))
    os.utime(str(new), (now, now))

    assert update.search(str(tmp_path)) == str(new)


def test_newest_visible_bad_ipk_still_fails_checkpkg(tmp_path):
    update = _load_update_module()
    old = tmp_path / 'old.ipk'
    new = tmp_path / 'new.ipk'
    _write_ipk(str(old), valid=True)
    _write_ipk(str(new), valid=False)
    now = time.time()
    os.utime(str(old), (now - 60, now - 60))
    os.utime(str(new), (now, now))

    assert update.search(str(tmp_path)) == str(new)
    assert update.checkPkg() is False


def test_search_returns_none_when_only_metadata_ipk_exists(tmp_path):
    update = _load_update_module()
    _write_ipk(str(tmp_path / '._icopy-x-oss.ipk'), valid=False)

    assert update.search(str(tmp_path)) is None
