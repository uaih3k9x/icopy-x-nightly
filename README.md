# uaih3k9x's iCopy-X Toolkit

> **注意：这是 iCopy-X Open 的个人维护分支。**
>
> `stable` 只放已经在本地验证、适合日常测试的改动；`nightly` 会继续承载更激进的
> 设备恢复、诊断、插件和 UI 实验。真实设备测试前，优先使用 no-flash 包。

## English Summary

This is a personal maintenance fork of the open-source iCopy-X rebuild.

The `stable` branch carries changes that are intended to be usable for regular
device testing. The `nightly` branch carries faster-moving recovery,
diagnostic, plugin, and UI experiments.

Prefer no-flash builds unless you intentionally need to update the Proxmark
module firmware. The original upstream README is preserved in
[docs/UPSTREAM_README.md](docs/UPSTREAM_README.md).

## Branches

This fork uses three long-lived branches:

- `nightly`: active development branch for new fixes, plugins, and experiments.
- `stable`: tested changes suitable for daily personal use.
- `main`: conservative baseline after changes have spent time in `stable`.

Use `stable` for the safer fork build. Use `nightly` only when you want to test
the newest work and can recover the device if something breaks.

## Stable Focus

The current `stable` branch includes the focused dump-diff and plugin UI work:

- Update search ignores macOS AppleDouble IPK sidecars such as `._*.ipk`.
- Plugin text output can be scrollable and stays inside the softkey-safe area.
- JSON plugin list screens can mirror the selected value into plugin variables.
- `Dump Diff` compares the newest two logical dumps for a selected type,
  ignores macOS sidecars, groups dump sidecar files by stem, and selects the
  primary file per dump type.
- `Dump Diff` lists common dump types first.
- `Dump Diff` includes an on-device 64-byte page viewer with changed-byte
  highlighting, A/B switching, changed-page navigation, and all-pages versus
  changed-only mode.

Generated IPKs, raw images, screenshots, Wi-Fi passwords, and device diagnostic
logs are local artifacts and should not be committed.

## Build

No-flash builds leave the Proxmark module firmware untouched and are the safer
default for this fork:

```bash
python tools/build_ipk.py \
  --sn UNIVERSAL \
  --no-flash \
  --output ./icopy-x-stable-no-flash.ipk
```

Flash builds update the Proxmark firmware and should only be used when you are
intentionally testing the flash path:

```bash
python tools/build_ipk.py \
  --sn UNIVERSAL \
  --output ./icopy-x-stable-flash.ipk
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

Useful focused checks before committing or publishing a stable build:

```bash
python tools/lint_plugin.py --all
PYTHONPATH=src:. pytest \
  tests/ui/test_plugin_activity.py \
  tests/ui/plugins/test_dump_diff_plugin.py \
  tests/lib/test_dump_diff.py \
  tests/test_update_search.py
python tools/build_ipk.py --sn UNIVERSAL --no-flash --output /tmp/icopy-x-quality-no-flash.ipk
```

Real hardware validation still needs to happen locally before treating a build
as known-good for your device.

## Upstream Context

This repository is based on the Lab401/quantum-x open-source iCopy-X rebuild.
The original README is kept in
[docs/UPSTREAM_README.md](docs/UPSTREAM_README.md) for installation background,
project history, and upstream caveats.

License terms remain PolyForm Noncommercial License 1.0.0. See
[LICENSE.md](LICENSE.md) for the full text.
