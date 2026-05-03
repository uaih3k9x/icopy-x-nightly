# iCopy-X Boot Rescue

This tool patches the boot partition initramfs (`rootfs.cpio.gz`) so the device
can bring up SSH rescue access even when `/home/pi/ipk_app_main` is broken.

The default rescue path is network-only:

- USB CDC-NCM gadget first, then CDC-ECM fallback, then `g_ether` fallback.
- The NCM-first path is intended to work better with macOS USB Ethernet.
- Device IP: `192.168.7.2/24`.
- Host/Mac IP: `192.168.7.1/24`.
- Wi-Fi fallback from `/mnt/upan/wifi.conf` when `wpa_supplicant` exists.
- No USB mass storage export by default.

Avoiding mass storage is intentional. macOS can write AppleDouble, Spotlight,
and filesystem metadata to exposed volumes, which is risky for update media and
rescue partitions.

## Patch a Mounted Boot Volume

Unmount/eject the rootfs/data partitions if macOS mounted them, but keep the
small FAT boot volume mounted. Then run:

```bash
tools/boot_rescue/patch_boot_rescue.sh /Volumes/Boot
```

If the boot volume is mounted as `/Volumes/boot` or `/Volumes/BOOT`, the script
can auto-detect it:

```bash
tools/boot_rescue/patch_boot_rescue.sh
```

The script writes a backup before changing anything:

```text
/Volumes/Boot/rescue-backup-YYYYMMDD-HHMMSS/
```

## Connect Over USB

After rebooting the iCopy-X, plug USB into the Mac. In macOS Network Settings,
set the new USB Ethernet interface manually:

```text
Host/Mac IP: 192.168.7.1
Subnet:      255.255.255.0
Router:      blank
```

Then connect:

```bash
ssh root@192.168.7.2
```

If the USB gadget is holding the USB controller and you need to free it for
another mode after SSH login:

```bash
/usr/local/sbin/icopy-rescue-net.sh stop
```

Restart rescue networking:

```bash
/usr/local/sbin/icopy-rescue-net.sh restart
```

## Wi-Fi Fallback

Create `/mnt/upan/wifi.conf` on the device data volume:

```ini
ssid=YourNetwork
psk=YourPassword
```

Optional keys:

```ini
iface=wlan0
driver=nl80211,wext
hidden=1
```

Open networks:

```ini
ssid=OpenNetwork
key_mgmt=NONE
```

The rescue script will start SSH, try USB Ethernet, then try Wi-Fi DHCP, then
start SSH again.

## Installed Files

The initramfs hook writes these files into the real rootfs during boot:

```text
/usr/local/sbin/icopy-rescue-net.sh
/etc/systemd/system/icopy-rescue-net.service
/etc/systemd/system/multi-user.target.wants/icopy-rescue-net.service
/etc/init.d/icopy-rescue-net
/etc/rc2.d/S01icopy-rescue-net
/etc/rc3.d/S01icopy-rescue-net
/etc/rc4.d/S01icopy-rescue-net
/etc/rc5.d/S01icopy-rescue-net
/etc/icopy-rescue-net.enabled
```

Systemd is the preferred path. The SysV links are a fallback for images that do
not boot through systemd cleanly.

## Logs

On the device:

```text
/var/log/icopy-rescue-net.log
/var/log/icopy-rescue-net-install.log
/tmp/icopy-rescue-net.out
```

## Rollback

Copy the backed-up initramfs back to the boot volume:

```bash
cp /Volumes/Boot/rescue-backup-YYYYMMDD-HHMMSS/rootfs.cpio.gz /Volumes/Boot/rootfs.cpio.gz
sync
```

Then reboot the device.
