# TODO

This file tracks the near-term work for the iCopy-X emulator, UI, and dump tooling.

## Current Rules

- Do not commit `imgs/`, extracted rootfs/userdata images, generated IPKs, screenshots, or local device exports.
- Keep device-image work local and reproducible through OrbStack/QEMU where possible.
- Prefer small commits with one clear theme.
- Test UI changes in the 240x240 QEMU/Web simulator before considering device deployment.

## P0 - Keep The Simulator Useful

- Keep `tools/icopy_emulator_web.py` working as the main development surface.
- Keep the 9-button Web control panel aligned with the physical controls:
  `M1`, `M2`, `PWR`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `OK`, `ALL`.
- Add regression checks for common navigation flows:
  main menu, plugins menu, Dump Files, Simulation, and rootfs backup plugin.
- Avoid relying on real GD32 serial, HMI, or PM3 hardware in emulator tests unless explicitly shimmed.

## P1 - Chinese UI

- Populate `StringZH` in `src/lib/resources.py` instead of leaving Chinese strings empty.
- Add or expose a language switch:
  default English for compatibility, optional `zh_CN` for testing.
- Verify `res/font/monozhwqy.ttf` renders correctly in QEMU and on-device packaging.
- Start with high-value screens:
  main menu, buttons, toasts, plugins menu, rootfs backup plugin, Dump Files, Scan, Read, and Simulation.
- Keep Chinese labels short enough for the 240x240 display.
- Capture simulator screenshots before and after translation to catch overflow or clipped text.

## P1 - Fast Dump Diff

Add a quick way to compare two dump files.

Why this is useful:

- Verify repeated reads of the same card are stable.
- Compare original card dump vs written/cloned card dump.
- See exactly which blocks changed after write, wipe, or restore operations.
- Debug full-card simulation by confirming the dump being loaded is the expected data.

Suggested scope:

- Add a small reusable diff module first, then plug it into UI.
- Support raw binary compare for any two files:
  file size, SHA-256, equality result, changed byte ranges.
- Add card-aware formatting where the file type is obvious:
  MIFARE Classic 1K/4K as 16-byte blocks, Ultralight/NTAG as 4-byte pages,
  ISO15693 as fixed blocks when metadata is available.
- Provide a compact screen-friendly summary:
  same/different, byte count, first changed offset, changed block/page count.
- Provide a detailed text report saved next to the dumps or under a `diffs/` folder.
- In Web/emulator mode, expose a richer diff page with hex rows and highlighted differences.

Possible UI flow:

- Dump Files: choose first file -> `Diff` -> choose second file -> show summary.
- M1/M2 on the summary screen can switch between summary and changed-block list.
- OK can save a full diff report.

Implementation notes:

- For MIFARE Classic, group by 16-byte blocks.
- For MIFARE Classic 1K, mark sector trailer blocks every 4 blocks.
- For MIFARE Classic 4K, handle the larger-sector trailer layout after sector 31.
- Do not treat this as a security decision engine; it is an inspection/debug tool.
- Keep the first version format-agnostic and reliable before adding deep parsers.

Priority:

- Build this before full-card simulation if we want safer iteration.
- It is lower risk than PM3 full-card simulation and gives immediate value for testing.

## P1 - Plugin Hot Reload / Hot Plug

Goal: make plugin development fast without reflashing or restarting the whole app.

Simulator scope:

- Web UI should expose `Reload Plugins`.
- `Reload Plugins` should sync host `plugins/` into the QEMU runroot.
- The running app should unload plugin modules, rediscover manifests, and refresh visible plugin menus.
- New plugin code should apply the next time the plugin is opened.
- A plugin that is currently running should not be replaced in-place.

Device scope:

- Support safe re-scan of `/home/pi/ipk_app_main/plugins/` after a plugin is copied in.
- Keep bad plugins isolated: one broken plugin must not crash the main app.
- Do not auto-run newly inserted plugins.
- Do not replace an active plugin instance while its background task is running.
- Long-term: add a plugin manager screen for reload, enable/disable, version, author, permissions, and lint errors.

Open questions:

- Decide whether device hot plug watches the plugin directory or uses an explicit `Reload Plugins` action.
- Decide whether plugin install packages should be copied into `plugins/<name>/` directly or staged then atomically renamed into place.
- Decide whether to keep plugin bytecode/cache disabled or clean `__pycache__` on reload.

## P2 - Full-Card Simulation

Goal: simulate card data, not only UID/card number, when the PM3 firmware supports it.

Initial target:

- MIFARE Classic 1K/4K dump-based simulation.

Planned flow:

- Add `Sim Dump` from Dump Files or Tag Info.
- Detect dump type from path, metadata, filename, and file size.
- For MIFARE Classic, load the `.bin` dump into PM3 emulator memory.
- Start the matching MIFARE Classic simulation mode.
- Show clear loading/simulating/stopped states.
- Keep the existing stop path compatible with physical PM3 button behavior.

Open command questions:

- Confirm the exact PM3 command supported by the bundled firmware/client.
- Candidate command families may include `hf mf eload`, `hf mf sim`, or firmware-specific aliases.
- Current code uses `hf 14a sim -t ... --uid ...`, which is UID/type simulation, not full dump simulation.

Limits:

- Full-card simulation is tag-type dependent.
- MIFARE Classic is the best first target.
- Ultralight/NTAG, ISO15693, and LF formats need separate support checks.
- Some cards cannot be fully emulated by the available PM3 firmware/hardware.

## P2 - Rootfs Backup Follow-Ups

- Test the rootfs backup plugin on real hardware with a USB drive.
- Confirm available-space checks behave correctly before copying.
- Confirm cancellation cleans up `.part` files.
- Consider optional restore tooling only after backup is proven safe.

## P3 - Packaging And Release Hygiene

- Keep `.gitignore` strict for local images and generated artifacts.
- Build IPKs from clean state.
- Add release notes for user-visible plugins and tools.
- Keep commits split:
  Chinese UI, dump diff, full-card simulation, backup changes, emulator changes.

## Suggested Next Commits

1. `Add Chinese UI resources`
2. `Add dump diff tooling`
3. `Add dump diff UI entry`
4. `Add MIFARE Classic dump simulation`
