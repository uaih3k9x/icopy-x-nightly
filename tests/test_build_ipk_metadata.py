"""Tests for IPK build metadata stamps."""

import subprocess

from tools import build_ipk


def test_generate_build_hash_uses_git_head(monkeypatch):
    monkeypatch.delenv('ICOPYX_BUILD_HASH', raising=False)
    head = subprocess.check_output(
        ['git', 'rev-parse', '--short=7', 'HEAD'],
        cwd=build_ipk.REPO_ROOT,
        text=True,
    ).strip()

    assert build_ipk._generate_build_hash().startswith(head)


def test_generate_build_hash_env_override(monkeypatch):
    monkeypatch.setenv('ICOPYX_BUILD_HASH', 'manualhash')

    assert build_ipk._generate_build_hash() == 'manualhash'


def test_generate_build_hash_truncates_github_sha(monkeypatch):
    monkeypatch.setenv(
        'ICOPYX_BUILD_HASH',
        '0123456789abcdef0123456789abcdef01234567',
    )

    assert build_ipk._generate_build_hash() == '0123456'
