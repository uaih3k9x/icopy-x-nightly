#!/usr/bin/env python3
"""Local web controller for the OrbStack iCopy-X emulator."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROJECT = Path(__file__).resolve().parents[1]
SCREENSHOT = PROJECT / 'build' / 'icopy-qemu-screen.png'
MACHINE = 'icopy-qemu'
DISPLAY = ':99'
KEY_FILE = '/tmp/icopy_web_keys.txt'
APP_LOG = '/tmp/icopy-app.log'
ROOT = '/mnt/icopy-runroot'
APP = ROOT + '/home/pi/ipk_app_main'
PYTHON = ROOT + '/usr/local/python-3.8.0/bin/python3.8'
SITE_PACKAGES = ROOT + '/home/pi/.local/lib/python3.8/site-packages'
RUNNER = '/home/qx/icopy-x-reimpl/tools/icopy_emulator_runner.py'

VALID_KEYS = {'UP', 'DOWN', 'LEFT', 'RIGHT', 'OK', 'M1', 'M2', 'PWR', 'ALL'}
VALID_COMMANDS = {'RELOAD_PLUGINS'}
VALID_DUMP_EXTS = ('.bin', '.eml', '.txt', '.json', '.pm3')
DUMP_ROOT = '/mnt/upan/dump'


def run_orb(command: str, *, root: bool = False, timeout: int = 15) -> subprocess.CompletedProcess:
    args = ['orb', 'run', '-m', MACHINE]
    if root:
        args.extend(['-u', 'root'])
    args.extend(['bash', '-lc', command])
    return subprocess.run(
        args,
        cwd=str(PROJECT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def optional_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        return ''
    return '%s=%s ' % (name, shell_quote(value))


def ensure_xvfb() -> dict:
    cmd = (
        'pgrep -af "Xvfb :99" >/dev/null || '
        'nohup Xvfb :99 -screen 0 240x240x24 >/tmp/icopy-xvfb.log 2>&1 < /dev/null & '
        'sleep 0.2; pgrep -af "Xvfb :99" || true'
    )
    proc = run_orb(cmd)
    return result_dict(proc)


def ensure_mounts() -> dict:
    cmd = r'''
set -e
mkdir -p /mnt/icopy-rootfs /mnt/icopy-userdata /mnt/icopy-boot /mnt/icopy-runroot
mountpoint -q /mnt/icopy-rootfs || mount -o ro,loop /home/qx/icopy-x-reimpl/imgs/20160211_162948/rootfs_mmcblk0p2.img /mnt/icopy-rootfs
mountpoint -q /mnt/icopy-userdata || mount -o ro,noload,loop /home/qx/icopy-x-reimpl/imgs/20160211_162948/userdata_mmcblk0p3.img /mnt/icopy-userdata
mountpoint -q /mnt/icopy-boot || mount -o ro,loop /home/qx/icopy-x-reimpl/imgs/20160211_162948/boot_mmcblk0p1.img /mnt/icopy-boot
mkdir -p /tmp/icopy-runroot/upper /tmp/icopy-runroot/work
mountpoint -q /mnt/icopy-runroot || mount -t overlay overlay -o lowerdir=/mnt/icopy-userdata/root:/mnt/icopy-rootfs,upperdir=/tmp/icopy-runroot/upper,workdir=/tmp/icopy-runroot/work /mnt/icopy-runroot
mkdir -p /mnt/upan/dump /mnt/upan/backups /mnt/upan/luascripts /mnt/upan/lualibs
chmod 777 /mnt/upan /mnt/upan/dump /mnt/upan/backups /mnt/upan/luascripts /mnt/upan/lualibs
findmnt /mnt/icopy-rootfs /mnt/icopy-userdata /mnt/icopy-boot /mnt/icopy-runroot
'''
    proc = run_orb(cmd, root=True, timeout=20)
    return result_dict(proc)


def sync_dev_sources() -> dict:
    """Sync editable Python/UI/plugin sources into the QEMU runroot."""
    cmd = r'''
set -e
app=/mnt/icopy-runroot/home/pi/ipk_app_main
repo=/home/qx/icopy-x-reimpl
mkdir -p "$app/lib" "$app/main" "$app/screens" "$app/plugins"
rsync -a "$repo/src/app.py" "$app/app.py"
rsync -a --delete --exclude '__pycache__/' "$repo/src/lib/" "$app/lib/"
rsync -a --exclude '__pycache__/' "$repo/src/middleware/" "$app/lib/"
rsync -a --delete --exclude '__pycache__/' "$repo/src/main/" "$app/main/"
rsync -a --delete "$repo/src/screens/" "$app/screens/"
rsync -a --delete --exclude '__pycache__/' "$repo/plugins/" "$app/plugins/"
find "$app/plugins" -maxdepth 2 -name manifest.json | sort
'''
    proc = run_orb(cmd, root=True, timeout=30)
    return result_dict(proc)


def stop_emulator() -> dict:
    cmd = r'''
python3 - <<'PY'
import os
import signal
import subprocess
import time

out = subprocess.check_output(['pgrep', '-af', 'qemu-arm'], text=True)
pids = []
for line in out.splitlines():
    parts = line.split(None, 1)
    if len(parts) != 2:
        continue
    pid, cmd = parts
    if 'python3.8' in cmd and ('icopy_emulator_runner.py' in cmd or ' app.py' in cmd):
        pids.append(int(pid))
for pid in pids:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
time.sleep(0.3)
print('stopped', pids)
PY
pgrep -af '^/usr/bin/qemu-arm .*python3.8' || true
'''
    proc = run_orb(cmd, root=True)
    return result_dict(proc)


def start_emulator() -> dict:
    ensure_mounts()
    ensure_xvfb()
    sync_dev_sources()
    run_orb(
        'rm -f {key_file} {log}; touch {key_file}; chmod 666 {key_file}'.format(
            key_file=shell_quote(KEY_FILE),
            log=shell_quote(APP_LOG),
        ),
        root=True,
    )
    cmd = (
        'cd {app}; '
        'nohup env PYTHONHOME={root}/usr/local/python-3.8.0 '
        'PYTHONPATH={app}:{app}/main:{app}/lib:{site_packages} '
        'ICOPY_APP_DIR={app} ICOPY_KEY_FILE={key_file} {lang_env}'
        'ICOPY_EMULATOR=1 DISPLAY={display} '
        '/usr/bin/qemu-arm -L {root} {python} {runner} '
        '>{log} 2>&1 < /dev/null & '
        'echo $!; sleep 4; '
        'pgrep -af "^/usr/bin/qemu-arm .*python3.8" || true; '
        'sed -n "1,120p" {log} || true'
    ).format(
        app=shell_quote(APP),
        root=shell_quote(ROOT),
        site_packages=shell_quote(SITE_PACKAGES),
        key_file=shell_quote(KEY_FILE),
        lang_env=optional_env('ICOPY_LANG'),
        display=shell_quote(DISPLAY),
        python=shell_quote(PYTHON),
        runner=shell_quote(RUNNER),
        log=shell_quote(APP_LOG),
    )
    proc = run_orb(cmd, root=True, timeout=12)
    capture_screen()
    return result_dict(proc)


def restart_emulator() -> dict:
    stop_emulator()
    return start_emulator()


def send_command(command: str) -> dict:
    command = command.upper()
    if command not in VALID_COMMANDS:
        return {'ok': False, 'error': 'invalid command'}
    cmd = 'printf "%s\\n" >> %s' % (command, shell_quote(KEY_FILE))
    proc = run_orb(cmd, root=True)
    time.sleep(0.25)
    capture_screen()
    data = result_dict(proc)
    data['command'] = command
    return data


def reload_plugins() -> dict:
    sync = sync_dev_sources()
    if not sync.get('ok'):
        return sync
    command = send_command('RELOAD_PLUGINS')
    return {
        'ok': bool(sync.get('ok')) and bool(command.get('ok')),
        'sync': sync,
        'command': command,
        'stdout': '[sync]\n%s\n[reload]\n%s' % (
            sync.get('stdout', ''),
            command.get('stdout', ''),
        ),
        'stderr': '%s%s' % (
            sync.get('stderr', ''),
            command.get('stderr', ''),
        ),
    }


def send_key(key: str) -> dict:
    key = key.upper()
    if key not in VALID_KEYS:
        return {'ok': False, 'error': 'invalid key'}
    cmd = 'printf "%s\\n" >> %s' % (key, shell_quote(KEY_FILE))
    proc = run_orb(cmd, root=True)
    time.sleep(0.12)
    capture_screen()
    data = result_dict(proc)
    data['key'] = key
    return data


def capture_screen() -> dict:
    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    cmd = 'DISPLAY=:99 import -window root /home/qx/icopy-x-reimpl/build/icopy-qemu-screen.png'
    proc = run_orb(cmd, timeout=10)
    return result_dict(proc)


def get_status() -> dict:
    capture_screen()
    cmd = (
        'echo "[processes]"; '
        'pgrep -af "^/usr/bin/qemu-arm .*python3.8|Xvfb :99" || true; '
        'echo; echo "[mounts]"; '
        'findmnt -R /mnt/icopy-rootfs /mnt/icopy-userdata /mnt/icopy-boot /mnt/icopy-runroot 2>/dev/null || true; '
        'echo; echo "[log]"; '
        'tail -n 120 /tmp/icopy-app.log 2>/dev/null || true'
    )
    proc = run_orb(cmd)
    png_b64 = ''
    if SCREENSHOT.exists():
        png_b64 = base64.b64encode(SCREENSHOT.read_bytes()).decode('ascii')
    return {
        'ok': proc.returncode == 0,
        'stdout': proc.stdout,
        'stderr': proc.stderr,
        'screenshot_b64': png_b64,
        'screenshot_mtime': SCREENSHOT.stat().st_mtime if SCREENSHOT.exists() else None,
    }


def get_log() -> dict:
    proc = run_orb('tail -n 220 /tmp/icopy-app.log 2>/dev/null || true')
    return result_dict(proc)


def list_dumps() -> dict:
    cmd = r'''
python3 - <<'PY'
import json
import os

root = '/mnt/upan/dump'
valid = ('.bin', '.eml', '.txt', '.json', '.pm3')
items = []
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if not d.startswith('.')]
    for name in filenames:
        if not name.lower().endswith(valid):
            continue
        path = os.path.join(dirpath, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        items.append({
            'path': path,
            'name': name,
            'type': os.path.relpath(dirpath, root).split(os.sep)[0],
            'size': st.st_size,
            'mtime': st.st_mtime,
        })
items.sort(key=lambda item: (item['type'], item['name']))
print(json.dumps(items))
PY
'''
    proc = run_orb(cmd, timeout=10)
    data = result_dict(proc)
    items = []
    if data.get('ok') and data.get('stdout'):
        try:
            items = json.loads(data['stdout'])
        except ValueError:
            items = []
    data['items'] = items
    return data


def _is_safe_dump_path(path: str) -> bool:
    if not path:
        return False
    norm = os.path.normpath(path)
    if not norm.startswith(DUMP_ROOT + '/'):
        return False
    if not norm.lower().endswith(VALID_DUMP_EXTS):
        return False
    return '..' not in norm.split('/')


def diff_dumps(path_a: str, path_b: str) -> dict:
    if not _is_safe_dump_path(path_a) or not _is_safe_dump_path(path_b):
        return {'ok': False, 'error': 'invalid dump path'}
    cmd = (
        'cd /home/qx/icopy-x-reimpl && '
        'python3 tools/dump_diff.py --json {a} {b}'
    ).format(a=shell_quote(path_a), b=shell_quote(path_b))
    proc = run_orb(cmd, timeout=20)
    data = result_dict(proc)
    try:
        data['diff'] = json.loads(data.get('stdout') or '{}')
    except ValueError:
        data['diff'] = None
    # tools/dump_diff.py exits 1 when files differ; that is still a
    # successful web operation as long as JSON was returned.
    if data.get('diff'):
        data['ok'] = True
    return data


def result_dict(proc: subprocess.CompletedProcess) -> dict:
    return {
        'ok': proc.returncode == 0,
        'returncode': proc.returncode,
        'stdout': proc.stdout,
        'stderr': proc.stderr,
    }


INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>iCopy-X Emulator</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --line: #d7dde4;
      --text: #17202a;
      --muted: #5c6975;
      --accent: #0b6f85;
      --accent2: #875300;
      --danger: #b42318;
      --ok: #18794e;
      --shadow: 0 1px 2px rgba(20, 31, 43, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      letter-spacing: 0;
    }
    header {
      height: 52px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 650;
    }
    .wrap {
      max-width: 1120px;
      margin: 0 auto;
      padding: 18px;
      display: grid;
      grid-template-columns: 292px 1fr;
      gap: 18px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .panel h2 {
      margin: 0;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      font-size: 13px;
      font-weight: 700;
      color: #26333f;
    }
    .screen-box {
      padding: 14px;
      display: grid;
      gap: 14px;
    }
    #screen {
      width: 240px;
      height: 240px;
      image-rendering: pixelated;
      border: 1px solid #1f2933;
      background: #111;
      display: block;
    }
    .controls {
      padding: 14px;
      display: grid;
      gap: 12px;
    }
    .keypad {
      display: grid;
      grid-template-columns: repeat(3, 72px);
      grid-template-rows: repeat(4, 46px);
      gap: 8px;
      justify-content: center;
    }
    button {
      border: 1px solid #bdc7d1;
      background: #fff;
      color: var(--text);
      border-radius: 7px;
      font: inherit;
      font-weight: 650;
      min-height: 36px;
      cursor: pointer;
    }
    button:hover { background: #eef7fa; border-color: #88b8c3; }
    button:active { transform: translateY(1px); }
    .primary { background: var(--accent); color: #fff; border-color: var(--accent); }
    .primary:hover { background: #095d70; border-color: #095d70; }
    .warn { color: var(--accent2); }
    .danger { color: var(--danger); }
    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    .toolbar button { padding: 0 12px; }
    .diff-grid {
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 8px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }
    select {
      width: 100%;
      min-width: 0;
      height: 36px;
      border: 1px solid #bdc7d1;
      border-radius: 7px;
      background: #fff;
      color: var(--text);
      font: inherit;
      padding: 0 8px;
    }
    .diff-summary {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      background: #fbfcfd;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      min-height: 54px;
      background: #fff;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 4px;
    }
    .metric strong {
      display: block;
      font-size: 14px;
      overflow-wrap: anywhere;
    }
    .ok { color: var(--ok); }
    .statusbar {
      padding: 10px 14px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--line);
      min-height: 36px;
    }
    pre {
      margin: 0;
      padding: 14px;
      min-height: 440px;
      max-height: calc(100vh - 184px);
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: #101820;
      color: #dce7ef;
      border-radius: 0 0 8px 8px;
    }
    .switch {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 760px) {
      .wrap { grid-template-columns: 1fr; }
      .screen-box { justify-items: center; }
      .diff-grid { grid-template-columns: 1fr; }
      .diff-summary { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>iCopy-X Emulator</h1>
    <label class="switch"><input id="auto" type="checkbox" checked> auto refresh</label>
  </header>
  <main class="wrap">
    <section class="panel">
      <h2>Screen</h2>
      <div class="screen-box">
        <img id="screen" alt="emulator screen">
      </div>
      <div class="controls">
        <div class="keypad">
          <button data-key="M1">M1</button>
          <button data-key="PWR" class="warn">PWR</button>
          <button data-key="M2">M2</button>
          <span></span>
          <button data-key="UP">UP</button>
          <span></span>
          <button data-key="LEFT">LEFT</button>
          <button data-key="OK" class="primary">OK</button>
          <button data-key="RIGHT">RIGHT</button>
          <span></span>
          <button data-key="DOWN">DOWN</button>
          <button data-key="ALL">ALL</button>
        </div>
      </div>
      <div class="statusbar" id="status">loading</div>
    </section>
    <section class="panel">
      <div class="toolbar">
        <button onclick="action('refresh')">Refresh</button>
        <button onclick="action('reload_plugins')">Reload Plugins</button>
        <button onclick="action('restart')" class="primary">Restart Emulator</button>
        <button onclick="action('stop')" class="danger">Stop</button>
        <button onclick="action('start')">Start</button>
      </div>
      <div class="diff-grid">
        <select id="diffA"></select>
        <select id="diffB"></select>
        <button onclick="runDiff()">Diff</button>
      </div>
      <div class="diff-summary" id="diffSummary">
        <div class="metric"><span>Status</span><strong>no diff</strong></div>
        <div class="metric"><span>Changed</span><strong>-</strong></div>
        <div class="metric"><span>First</span><strong>-</strong></div>
        <div class="metric"><span>Groups</span><strong>-</strong></div>
      </div>
      <pre id="log"></pre>
    </section>
  </main>
  <script>
    const screen = document.getElementById('screen');
    const log = document.getElementById('log');
    const statusEl = document.getElementById('status');
    const auto = document.getElementById('auto');
    const diffA = document.getElementById('diffA');
    const diffB = document.getElementById('diffB');
    const diffSummary = document.getElementById('diffSummary');

    async function api(path, body) {
      const opts = body ? {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      } : {};
      const r = await fetch(path, opts);
      return await r.json();
    }

    function stamp(text) {
      const t = new Date().toLocaleTimeString();
      statusEl.textContent = `${t} ${text}`;
    }

    async function refresh() {
      try {
        const data = await api('/api/status');
        if (data.screenshot_b64) {
          screen.src = 'data:image/png;base64,' + data.screenshot_b64;
        }
        log.textContent = data.stdout || data.stderr || '';
        stamp(data.ok ? 'ready' : 'command failed');
      } catch (e) {
        stamp('refresh failed: ' + e);
      }
    }

    function shortPath(item) {
      const type = item.type || '?';
      return `${type}/${item.name} (${item.size}B)`;
    }

    async function loadDumps() {
      const data = await api('/api/dumps');
      const items = data.items || [];
      for (const sel of [diffA, diffB]) {
        const current = sel.value;
        sel.innerHTML = '';
        for (const item of items) {
          const opt = document.createElement('option');
          opt.value = item.path;
          opt.textContent = shortPath(item);
          sel.appendChild(opt);
        }
        if (current) sel.value = current;
      }
      if (items.length >= 2 && !diffA.value && !diffB.value) {
        diffA.value = items[items.length - 2].path;
        diffB.value = items[items.length - 1].path;
      }
    }

    function fmtOffset(value) {
      if (value === null || value === undefined) return 'n/a';
      return '0x' + Number(value).toString(16).toUpperCase();
    }

    function fmtGroups(diff) {
      const g = diff.grouping || {};
      if (g.unit === 'mfc-block') {
        return `${g.block_count || 0} blocks / ${g.sector_count || 0} sectors`;
      }
      if (g.unit === 'mfu-page') {
        return `${g.page_count || 0} pages`;
      }
      return `${diff.range_count || 0} ranges`;
    }

    function renderDiff(diff) {
      if (!diff) return;
      const status = diff.equal ? '<span class="ok">equal</span>' : '<span class="danger">different</span>';
      diffSummary.innerHTML = `
        <div class="metric"><span>Status</span><strong>${status}</strong></div>
        <div class="metric"><span>Changed</span><strong>${diff.changed_bytes} byte(s)</strong></div>
        <div class="metric"><span>First</span><strong>${fmtOffset(diff.first_diff_offset)}</strong></div>
        <div class="metric"><span>Groups</span><strong>${fmtGroups(diff)}</strong></div>
      `;
      log.textContent = JSON.stringify(diff, null, 2);
    }

    async function runDiff() {
      if (!diffA.value || !diffB.value) {
        stamp('select two dumps');
        return;
      }
      stamp('diff...');
      const data = await api('/api/diff', {a: diffA.value, b: diffB.value});
      if (data.diff) {
        renderDiff(data.diff);
        stamp('diff ready');
      } else {
        log.textContent = JSON.stringify(data, null, 2);
        stamp('diff failed');
      }
    }

    async function action(name) {
      stamp(name + '...');
      if (name === 'refresh') return refresh();
      const data = await api('/api/' + name, {});
      log.textContent = (data.stdout || '') + (data.stderr ? '\n' + data.stderr : '');
      await refresh();
    }

    document.querySelectorAll('[data-key]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const key = btn.dataset.key;
        stamp('key ' + key);
        const data = await api('/api/key', {key});
        if (!data.ok) log.textContent = JSON.stringify(data, null, 2);
        await refresh();
      });
    });

    document.addEventListener('keydown', async (ev) => {
      const map = {
        ArrowUp: 'UP',
        ArrowDown: 'DOWN',
        ArrowLeft: 'LEFT',
        ArrowRight: 'RIGHT',
        Enter: 'OK',
        Escape: 'PWR',
        a: 'M1',
        d: 'M2',
        s: 'ALL'
      };
      const key = map[ev.key];
      if (!key) return;
      ev.preventDefault();
      await api('/api/key', {key});
      await refresh();
    });

    setInterval(() => { if (auto.checked) refresh(); }, 1200);
    loadDumps();
    refresh();
  </script>
</body>
</html>
'''


class Handler(BaseHTTPRequestHandler):
    def _json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, html: str) -> None:
        payload = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == '/':
            self._html(INDEX_HTML)
        elif path == '/api/status':
            self._json(get_status())
        elif path == '/api/log':
            self._json(get_log())
        elif path == '/api/dumps':
            self._json(list_dumps())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length') or '0')
        raw = self.rfile.read(length) if length else b''
        try:
            body = json.loads(raw.decode('utf-8') or '{}') if raw else {}
        except ValueError:
            body = {}

        if path == '/api/key':
            self._json(send_key(str(body.get('key', ''))))
        elif path == '/api/start':
            self._json(start_emulator())
        elif path == '/api/restart':
            self._json(restart_emulator())
        elif path == '/api/stop':
            self._json(stop_emulator())
        elif path == '/api/reload_plugins':
            self._json(reload_plugins())
        elif path == '/api/diff':
            self._json(diff_dumps(str(body.get('a', '')), str(body.get('b', ''))))
        elif path == '/api/refresh':
            self._json(get_status())
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        print('[web] ' + fmt % args)


def main() -> None:
    parser = argparse.ArgumentParser(description='iCopy-X emulator web controller')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--start-emulator', action='store_true')
    args = parser.parse_args()

    if args.start_emulator:
        print('Starting emulator...')
        result = restart_emulator()
        print(result.get('stdout', '').strip())
        if result.get('stderr'):
            print(result['stderr'].strip())

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print('Web UI: http://%s:%d' % (args.host, args.port))
    server.serve_forever()


if __name__ == '__main__':
    main()
