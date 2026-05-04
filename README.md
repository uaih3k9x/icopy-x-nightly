# uaih3k9x's iCopy-X Experimental Toolkit

> **注意：这是一个非常激进、完全不稳定的个人实验工具包。**
>
> 这个仓库不是上游稳定版，也不是面向普通用户的发行分支。这里会包含我正在测试的
> iCopy-X 工具、插件、模拟器、诊断功能、中文界面、更新器修复、dump/diff 实验、
> 以及其他可能还没有充分验证的改动。
>
> **请默认认为这里的东西会坏、会变、会需要重刷。** 如果你只是想要稳定版本，请优先
> 使用上游项目或正式 release。这个仓库更适合愿意协助测试、反馈问题、提出需求的人。
>
> 当某个功能在真实设备和模拟器里都验证到足够稳定之后，我会尽量把它拆成小的、
> 可 review 的改动，PR 回上游仓库。
>
> 欢迎提需求、开 issue、给测试结果，尤其欢迎提供真实设备日志、dump 文件结构、
> 更新失败截图、插件需求和复现步骤。

## English Summary

This is **uaih3k9x's aggressive experimental iCopy-X toolkit fork**.

It is not a stable upstream release. Expect breaking changes, unfinished
plugins, experimental updater behavior, emulator work, diagnostic tools,
Chinese UI experiments, dump/diff tooling, and other in-progress changes.

If a feature becomes stable after emulator and real-device testing, I will try
to split it into small reviewable patches and submit it back upstream. Issues,
feature requests, logs, dump samples, and reproducible test cases are welcome.

Use this fork at your own risk. Prefer no-flash builds unless you know exactly
why you need a flash build.

## Branches / 分支策略

This fork now uses three long-lived branches:

- `nightly` is the default development branch. New device fixes, UI work,
  plugins, rescue tools, packaging changes, and other experiments land here
  first. Expect frequent changes.
- `stable` is for changes that have worked on real hardware and are good enough
  for daily personal use. Features graduate here from `nightly`.
- `main` is the conservative baseline. Only changes that have spent time in
  `stable` and have no known serious regressions should move here.

中文说明：

- `nightly`：默认开发分支，所有实验和新功能先放这里。
- `stable`：真实设备上验证过、日常使用基本可靠的版本。
- `main`：最保守的基线，只放长期验证后很稳的改动。

If you are testing new work from this repository, use `nightly`. If you want the
least risky branch from this fork, use `main` or wait for a tagged build.

## CI / 质量门禁

This fork uses GitHub Actions for a lightweight quality gate on `nightly`,
`stable`, and `main`.  The gate does not need a self-hosted runner or a real
iCopy-X device.  It checks Python syntax, plugin structure, language resource,
plugin translation coverage, the current stable UI/unit test subset,
whitespace, and a no-flash IPK package build.

Local commands:

```bash
python tools/lint_plugin.py --all
python tools/lint_i18n.py --lang zh
python -m pytest -q \
  tests/ui/widgets/test_console_view.py \
  tests/ui/activities/test_about.py \
  tests/ui/activities/test_lua_script.py \
  tests/ui/activities/test_scan_tag.py::TestConsolePrinterActivity \
  tests/ui/activities/test_dump_files.py \
  tests/ui/activities/test_simulation.py \
  tests/ui/activities/test_sniff.py \
  tests/ui/test_plugin_activity.py \
  tests/ui/renderer/test_renderer.py \
  tests/test_install_recovery.py \
  tests/test_update_search.py \
  tests/lib/test_dump_diff.py
python tools/build_ipk.py --sn UNIVERSAL --no-flash --output /tmp/icopy-x-quality-no-flash.ipk
```

中文说明：目前没有必要自建 CI 机器。GitHub Actions 先负责挡住明显的
语法、插件、翻译表、UI 测试和打包问题；真实硬件测试、SSH 恢复、刷机验证仍然放在
本地设备流程里做。

## Experimental Work in This Fork

This fork currently carries local, in-progress work that is intentionally more
aggressive than the upstream project:

- Emulator and web-controller tooling for OrbStack/QEMU based UI testing.
- Plugin hot-reload experiments for faster local development.
- RootFS backup tooling with progress feedback for boot/rootfs/userdata dumps.
- Dump Diff tooling for quickly comparing dump outputs while the dump-file
  format rules are still being refined.
- Chinese UI resource experiments and local About-page branding.
- MIFARE Classic full-dump simulation experiments using emulator memory, not
  only UID/card-number simulation.
- macOS updater hardening that ignores AppleDouble `._*.ipk` sidecar files so
  update selection does not fail with misleading `0x05` package errors.
- USB Wi-Fi bring-up helpers for temporary SSH access without persistent
  network configuration changes.
- System diagnostic dump helpers that collect device logs, USB/WLAN inventory,
  kernel modules, and network state for real-hardware debugging.
- Diag Dump now includes a small NCM/IP/USB/SSH/dmesg self-check summary before
  the raw dump.  The on-device plugin page shows only the actionable
  PASS/WARN/FAIL items, while the saved text file still contains the full
  command output.
- PC-Mode USB gadget handoff fixes. When the boot rescue USB network gadget is
  active, PC-Mode now suspends it before loading the ACM+Mass-Storage gadget and
  restores it after PC-Mode exits.
- Boot rescue tooling that can patch the boot initramfs to install a rescue SSH
  network service. The rescue path tries USB CDC-NCM first, then CDC-ECM, then
  `g_ether`, and can also attempt Wi-Fi from `/mnt/upan/wifi.conf`.
- USB SSH bootstrap is installed by the app updater and enabled by default. It
  exposes `usb0` on `192.168.7.2/24` and `169.254.7.2/16`, with a `USB SSH`
  plugin for status, restart, repair, enable/disable, and rollback.
- Post-update USB SSH recovery.  After installing an IPK, the restart path can
  schedule a short-lived recovery task that restarts the rescue USB network,
  restores `usb0` to `192.168.7.2/24` plus `169.254.7.2/16`, and restarts SSH
  when available.
- Dynamic build metadata. Local IPK builds now stamp both a build version and
  the git commit hash into the package; the About page displays the build hash
  instead of a hardcoded value.
- SSH deployment helper for copying the newest IPK to `/mnt/upan`, removing old
  root-level IPKs, avoiding macOS AppleDouble sidecars, and using a short SSH
  ControlPath that works on macOS.
- Scrollable plugin text rendering improvements, including wrapping and
  bounded text areas so plugin output can be viewed without overflowing into
  the softkey bar.
- Lua Script menu and console polish.  Lua scripts can be displayed with
  translated labels while still running their original filenames, interactive
  command-line examples are hidden by default, and Lua output uses a compact
  full-screen console that filters PM3 transport noise.
- JSON plugin list screens can mirror the selected item into plugin variables
  and render radio-style selection.  Dump Diff now uses this for direct
  dump-type selection instead of a cycle button.
- Lightweight CI quality gate and `tools/lint_i18n.py` keep the current
  English/Chinese resources, Lua script labels, and plugin UI strings from
  silently drifting.

Generated IPKs, raw images, screenshots, Wi-Fi passwords, and device diagnostic
logs are development artifacts and should not be committed here.

## Current Nightly Highlights

The current `nightly` branch is focused on making local testing and recovery
safer:

- PC-Mode and rescue USB networking no longer silently fight for the same USB
  device controller.
- No-flash IPKs identify their exact source commit on the About page.
- `Diag Dump` reports NCM service, `usb0` IP, USB carrier, SSH listener,
  active USB gadget function, and recent USB/NCM dmesg health at the top of the
  plugin output.  The raw diagnostic file still includes `ip`, `lsusb`,
  configfs USB gadget state, rescue logs, and full dmesg.
- IPK install/restart now attempts to recover USB SSH access without requiring
  a physical replug when the rescue network helper is present.
- The `USB SSH` plugin can repair the helper from the device UI and shows both
  connection addresses: `ssh root@169.254.7.2` and `ssh root@192.168.7.2`.
- Lua script output is easier to read on the 240x240 screen and avoids showing
  stale output from the previous script run.
- Dump Diff now presents dump types as a radio list, which is faster than
  cycling through types one at a time.
- The repo has a documented `nightly -> stable -> main` promotion path.
- `tools/deploy_ipk_ssh.sh` can upload the latest generated IPK over SSH:

  ```bash
  ./tools/deploy_ipk_ssh.sh 192.168.7.2
  ```

- `tools/boot_rescue/patch_boot_rescue.sh` can install a rescue SSH network
  service into a mounted boot partition's initramfs.

Latest local no-flash test package from this branch:

```text
icopy-x-sysdiag-ncm-no-flash.ipk
Build hash: aaf5810
Build version: 260504-08.00-Int
PM3 firmware: unchanged factory firmware
```

These features are useful, but they are still part of the experimental branch.
Test on your own device before trusting them.

---

# iCopy-X Open
An Open-Source version of the iCopy-X RFID Cloner device.

## What this is:

 - Usable: A **complete** rebuild of the iCopy-X device. All device functions are included.
 - Jailbroken: Installable without needing to build individual IPKs
 - Up-to-date: Runs __latest iceman firmware__ 
 - Flexible: Complete plugin system + Simplified JSON-based UI system

## What this is not:

 - It's not built on the original author's IP. All code written from scratch.
 - It's (Probably not) Bug-Free. This was a massive task. Despite thousands of UI, Functional and Regression tests, there's going to be gaps.
 - It's not useable commercially. This software cannot be used in a commercial context. See LICENCE for more information.

## What's new?
 - Full access to everything!
 - Plugin architecture - allows for building UI apps that interact with the proxmark or linux sub-system just from JSON. Also allows a "full-screen" mode for running other binaries (ie DOOM)
 - Screen mirroring: Allows the screen to be streamed to a device via USB. Can't be used at the same time as PC-Mode: Disable / Enable in settings.

# Installation
There are **two flavours** to choose from: "No Flash" and "Flash".

 - **"No Flash"**: Full open-source system, but leaves your iCopy-X's proxmark module untouched. You can easily move back and forth between factory/vanilla middleware. However, you will be limited to circa ~2022 proxmark client + firmware.
 - **"Flash"**: Full open-source system, running latest iceman firmware + client. You'll be prompted to flash after you install the IPK. Flashing **does not touch the bootloader** - you will NOT brick your device. Likewise, the iCopy-X has protections to recover from a soft-brick.

Installation is simple: 

 0. Ensure that your device is up to date (1.0.90 - get it from here: https://icopyx.com/pages/update-your-icopy-x)
 1. Download the IPK of your choice
 2. Put your iCopy-X into PC-Mode
 3. Delete ALL OTHER IPK files from the device
 4. Transfer the IPK onto your device and close PC-Mode 
 5. Navigate to About > Update, and press [OK]
 6. Device will restart
 7. While restarting, the screen will flash and stay blank for up to 10 seconds. Don't panic!

If you're using the "flash" version, there will be some extra steps:

 7. Device will restart and detect that you need to flash your device. Click OK.
 8. Read the instructions: Make sure your device has charge, make sure it's plugged in, and then Start
 9. After flashing, your device will restart.
 10. While restarting, the screen will stay blank for up to 10 seconds. Don't panic!

## I've installed it - everything looks the same

The upgrade is designed to be seamless: visually and functionally.
A good way to tell if the update worked is if your battery indicator is coloured, or if you see the "Plugins" option on the menu.

## The Plugins don't do anything (useful).

The plugins are designed as examples for developers : how to use the JSON UI framework, how to send commands to the proxmark, how to chain screens, etc.
Try DOOM for a "working" plugin.

## Companion PM3 Clients (for PC-Mode)

When your iCopy-X is in "PC-Mode", you can connect to your iCopy-X's Proxmark module directly from your computer.
Each release contains multi-platform binaries, compiled to match your device's version:
 - `clients-noflash.zip` : Contains windows, linux and macos clients for the "factory firmware" / "no flash" version
 - `clients-flash.zip` : Contains windows, linux and macos clients for the latest iceman / "flash" version.

### Using the companion client

1. Download the matching `clients-[flash|noflash].zip` for your IPK variant
2. Extract to a folder on your computer
3. Put your iCopy-X into PC-Mode
4. Connect via USB
5. Run: `proxmark3 /dev/ttyACM0` (Linux/macOS) or `proxmark3.exe COMx` (Windows)
Adjust `ttyACM0` and `COMx` according to the real port assigned to your iCopy-X.

## Screen Mirroring?

1) On your device, go to "Settings" and enable "Screen Mirror"
2) Reboot your iCopy-X (__important__)

On your computer:
1) Grab the `tools/screen_mirror/` tool from the repository. 
2) Run: `python -m pip install -r requirements.txt` 
3) Then: `python mirror_client.py` 

And everything should work.

# Technical Bits

## Why
The last official iCopy-X update was in 2022. Without updates, for many users the device is an expensive paperweight.
Open-Sourcing the device gives new life to a very capable, well-made portable RFID tool.

## How

Over 350 hours of work. A 48-core, 96GB RAM QEMU testing environment.

The project was actually multiple projects in one, each one as complex and time-consuming as the other.

 - Reliable jailbreak + proof of concept
 - Mapping & Testing: Building exhaustive testing for every function, every logic branch down to the leaf
 - Replacing the UI layer, iterating against tests until complete
 - Building the middleware, iterating against tests until complete
 - Adding support for iceman fork (requires stable upgrade + flash mechanisms)
 - Rebuilding middleware to match iceman fork (or specifically, a compatibility layer)

### Great, but how? 

After multiple PoCs, attempts, and failed iterations, the winning strategy was TDD - test driven design.

Despite its enormous complexity, the iCopy-X has a very well defined inputs and outputs - which is the core of TDD.

Based on the UI and possible proxmark outcomes, the entire logic tree was derived.
 
The iCopy-X was mocked entirely in QEMU, and exhaustive "flow" tests were built against every function. The branches were triggered by building thousands of 
mocked RFID fixtures that would trigger Proxmark behavior.

Once the tests were functional, the UI layer was built and tested against the emulated flows.

When the UI was functional, the middleware was built, flow by flow.

When all flows were passing tests, real-device testing began, with thousands of traces being taken to replace the mocked behavior and confirm real behavior.

This process was then repeated across all phases: prototyping, "no flash", and finally "flash" versions.

The Github CI/CD pipelines and tooling evolved along the way to allow anyone to be able to compile without needing to build an environment locally.

## Who? 

https://github.com/quantum-x from https://www.lab401.com

## I flashed my device and I don't like it and I want to go back to vanilla...

### Via the UI
Add a factory pm3 firmware image (found in an original .IPK archive:  `res/firmware/pm3/fullimage.elf`) inside the `res/firmware/pm3` folder of a "flash". Copy to your device, install and flash. Then, install the "noflash.ipk" on your device. __or__

### Via SSH
1) Connect to your device via SSH (You'll need USB-C Ethernet connector/hub): login: root/fa
2) Transfer the factory pm3 firmware image (found in an original .IPK archive:  `res/firmware/pm3/fullimage.elf`) to the icopy-x.
3) `systemctl stop icopy`
4) `/home/pi/ipk_app_main/pm3/proxmark3 /dev/ttyACM0 --flash --force --image /path/to/fullimage.elf`
5) Reboot your device, install "noflash.ipk"

### Via PC-Mode
1) Place your iCopy-X in PC-Mode
2) Use the latest proxmark3 client to flash your device: proxmark3 /dev/ttyACM0 --flash --force --image fullimage.elf

## Does this solve the "Boot Timeout" problem?
Not directly. "Boot Timeout" means that the GD32 (Microcontroller, that controls that hardware) hasn't received the signal to handoff the screen to the linux device / UI. There are multiple things that can cause this - but the fasted solution is: reflash the microSD card.

Please see the following page for more information, and factory images to reflash your microSD!
https://lab401.com/blogs/academy/icopy-xs-fixing-the-boot-timeout-problem

Once your device is reflashed and booting, you can apply the Open Source IPKs.

## Known issues

- Only tested on the iCopy-XS - other versions __probably__ will work with the no-flash version.
- iClass SE/SEOS via External Module: not integrated, marked as non-critical
- External Auto-Hardnested UI tool: Out of scope, marked as non-critical
- On iceman firmware, issues with specific chipsets. These weren't detected by the module - it's a PM3 issue (or a problem with our testing fixtures)
  - GproxII
  - NexWatch
  - IDTek
  - Noralsy
  - Original iCopy-X Gen1a tags appear to be undetectable. __This is not a bug!__ Curiously, for some reason - the device's read range is enhanced on iceman's release. You may need to have a gap of up to 2cm above the device for stable reading! Anything closer over saturates the reader/tag.
- "Flash" version is built directly from the latest tagged release of the iceman repo. If an update changes command syntax or responses, this will break functionality on the iCopy-X device. Our goal was to get the device running on latest iceman. There's a full CI/CD build pipeline, allowing you to mix and match your own proxmark versions. However keeping the iCopy-X's compatibility layer mapped to changes in the iceman repo is up to the community.
- "Flow Tests" - the backbone of this project - are not passing as of the official release. After the project got 1:1 parity with the original middleware, these decoupled. In an ideal world - these should be made to work (and also be made to mock the iceman firmware+client responses). They're an excellent tool for ensuring stability across the entire codebase. 

## Disclaimer

There are multiple hardware revisions of the iCopy-X.
Testing was performed against the first revision, but should work on all revisions.

## Wait! There's a .so file! You said there's no closed source!
This is the jailbreak - the vanilla firmware requires a valid `version.so` to process an IPK.

# What's next

The goal of this project was to open-source the iCopy-X. The future maintenance is beyond the scope of the original project, but we hope that the community will appreciate the value of this project and keep it alive!

Some suggestions would be:

 - Integrate 4+ years of iceman repo functions, tag types and progress into the UI
 - Integrate new magic cards

# Licence

This code is distributed under PolyForm Noncommercial License 1.0.0.
Why this licence? When we'd discussed open-source with the original manufacturers they had concerns about cloning. Out of respect for the genuinely incredible hard work that they put into the iCopy-X - we do not want to be an avenue for cloners.

This code is intended for pentesters and RFID enthusiasts. It is intended to open a closed device to progress and provoke community evolution - not for profit.
If you plan on selling the code, selling an SD card with the code, or embedding the code or its derivatives in a device and selling the device: this is NOT permitted. 
