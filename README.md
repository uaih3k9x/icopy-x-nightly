# uaih3k9x's iCopy-X Experimental Toolkit

> **注意：这是一个激进、经常变化、面向测试的个人实验分支。**
>
> 这里不是上游稳定版，也不是给普通用户无脑安装的 release。这个仓库会放我正在验证的
> iCopy-X 插件、中文界面、更新器修复、USB SSH 恢复、dump/diff 工具、模拟器测试、
> 诊断功能，以及其他还没有完全稳定的改动。
>
> 请默认认为 `nightly` 会坏、会变、会需要重刷。真实设备测试前，优先使用 no-flash 包。

## English Summary

This is an aggressive experimental fork of the open-source iCopy-X rebuild.
It carries unfinished device fixes, plugins, diagnostics, USB SSH recovery,
Chinese UI work, emulator tooling, and dump/diff experiments.

Use it at your own risk. Prefer no-flash builds unless you know exactly why you
need to flash the Proxmark module. When a change becomes stable enough on real
hardware, I will try to split it into reviewable patches for upstream.

The original upstream README content is preserved in
[docs/UPSTREAM_README.md](docs/UPSTREAM_README.md).

## Branches

This fork uses three long-lived branches:

- `nightly`: default development branch. New fixes, plugins, recovery tools,
  and UI experiments land here first.
- `stable`: changes that have worked on real hardware and are suitable for
  daily personal use.
- `main`: conservative baseline for changes that spent time in `stable`.

If you are testing new work from this fork, use `nightly`. If you want the
least risky branch, use `main` or wait for a tagged build.

## Current Focus

The current `nightly` branch is focused on device recovery, local testing, and
dump inspection:

- `Dump Diff`: compares the two newest logical dumps for a selected type,
  ignores macOS AppleDouble sidecars, groups dump sidecar files by stem, and
  selects the primary file per dump type.
- `Dump Diff` sector viewer: shows 64-byte pages, highlights changed bytes,
  supports A/B card switching, changed-page navigation, and an all-pages versus
  changed-only toggle.
- USB SSH bootstrap: exposes `usb0` on `192.168.7.2/24` and `169.254.7.2/16`,
  with an on-device plugin for status, repair, restart, enable/disable, and
  rollback.
- Post-update USB SSH recovery: after IPK install, the restart path can try to
  restore USB networking and SSH without a physical replug.
- `Diag Dump`: saves USB, NCM, WLAN, IP, SSH, kernel-module, rescue-log, and
  dmesg state; the on-device page shows the actionable PASS/WARN/FAIL summary.
- PC-Mode USB gadget handoff: PC-Mode suspends the rescue USB network gadget
  before loading ACM+Mass-Storage, then restores it afterward.
- Plugin UI polish: scrollable plugin text wraps inside the softkey-safe area,
  JSON list screens can mirror selected values, and plugin UI strings are
  checked for English/Chinese drift.
- Build metadata: local IPK builds stamp a build version and git hash; the
  About page displays the build hash.

Generated IPKs, raw images, screenshots, Wi-Fi passwords, and device diagnostic
logs are local artifacts and should not be committed.

## Build

No-flash builds leave the Proxmark module firmware untouched and are the safer
default for testing this fork:

```bash
python tools/build_ipk.py \
  --sn UNIVERSAL \
  --no-flash \
  --output ./icopy-x-nightly-no-flash.ipk
```

Flash builds update the Proxmark firmware and should only be used when you are
intentionally testing the flash path:

```bash
python tools/build_ipk.py \
  --sn UNIVERSAL \
  --output ./icopy-x-nightly-flash.ipk
```

## Install

Manual install path:

1. Make sure the device is on the official `1.0.90` base firmware.
2. Build or download one IPK.
3. Put the iCopy-X into PC-Mode.
4. Remove other root-level `.ipk` files from the mounted USB storage.
5. Copy the new IPK to the device storage.
6. Close PC-Mode.
7. Open `About > Update` on the device and press `OK`.
8. Wait for the restart. A blank screen for several seconds during restart is
   expected.

SSH deployment helper:

```bash
./tools/deploy_ipk_ssh.sh 192.168.7.2
```

The helper copies the newest generated IPK to `/mnt/upan`, removes old
root-level IPKs, avoids macOS AppleDouble sidecars, and uses a short SSH
ControlPath that works on macOS.

## USB SSH

When the bootstrap is present and enabled, the common connection targets are:

```bash
ssh root@192.168.7.2
ssh root@169.254.7.2
```

The on-device `USB SSH` plugin can show status, restart the helper, repair the
installed files, enable/disable the service, and roll back the bootstrap.

## Dump Diff Controls

`Plugins > Dump Diff` compares the newest two logical dumps in the selected
dump directory. Common types are listed first: Mifare Classic, Ultralight/NTAG,
EM410x, HID Prox, T5577, ISO15693, iClass, and Felica.

Viewer controls:

- `OK`: toggle A/B card view.
- `LEFT` / `RIGHT`: previous or next 64-byte page.
- `UP` / `DOWN`: previous or next changed page.
- `M2`: next changed page.
- `ALL`: toggle all pages versus changed-only mode.
- `M1`: back to the text result page.
- `PWR`: global exit.

Color convention:

- B/new view highlights changed bytes in green.
- A/old view highlights changed bytes in red.
- Missing bytes are shown as `--`.

## Local Quality Gate

Useful focused checks before committing:

```bash
python tools/lint_plugin.py --all
python tools/lint_i18n.py --lang zh
PYTHONPATH=src:. pytest \
  tests/ui/test_plugin_activity.py \
  tests/ui/plugins/test_dump_diff_plugin.py \
  tests/lib/test_dump_diff.py
python tools/build_ipk.py --sn UNIVERSAL --no-flash --output /tmp/icopy-x-quality-no-flash.ipk
```

The GitHub Actions quality gate is intentionally lightweight. It checks Python
syntax, plugin structure, translation coverage, a stable UI/unit subset,
whitespace, and a no-flash package build. Real hardware validation still needs
to happen locally.

## Upstream Context

This repository is based on the Lab401/quantum-x open-source iCopy-X rebuild.
The original README is kept in
[docs/UPSTREAM_README.md](docs/UPSTREAM_README.md) for installation background,
project history, and upstream caveats.

License terms remain PolyForm Noncommercial License 1.0.0. See
[LICENSE.md](LICENSE.md) for the full text.
