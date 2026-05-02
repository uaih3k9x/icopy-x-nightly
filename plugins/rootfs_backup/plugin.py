##########################################################################
# Required Notice: Copyright ETOILE401 SAS (http://www.lab401.com)
#
# Copyright (c) 2026: ETOILE401 SAS & https://github.com/quantum-x/
#
# This software is licensed under the PolyForm Noncommercial License 1.0.0.
# You may not use this software for commercial purposes.
#
# A copy of the license is available at:
# https://polyformproject.org/licenses/noncommercial/1.0.0
#
# This entire header "Required Notice" must remain in place.
##########################################################################

"""RootFS Backup plugin.

Copies the small boot/rootfs/userdata partitions to /mnt/upan so a user can
pull them over PC-Mode without removing the microSD card.  The ICOPY-X data
partition is deliberately skipped because the backup destination lives there.
"""

import errno
import fcntl
import hashlib
import json
import os
import shutil
import struct
import threading
import time


BACKUP_ROOT = '/mnt/upan/backups/rootfs'
UPAN_ROOT = '/mnt/upan'
CHUNK_SIZE = 4 * 1024 * 1024
PROGRESS_INTERVAL_SEC = 0.7
MIN_FREE_MARGIN = 128 * 1024 * 1024
BLKGETSIZE64 = 0x80081272

PARTITIONS = (
    ('boot', '/dev/mmcblk0p1'),
    ('rootfs', '/dev/mmcblk0p2'),
    ('userdata', '/dev/mmcblk0p3'),
)


class BackupCancelled(Exception):
    """Raised when the plugin is destroyed while a backup is running."""


def _format_bytes(value):
    """Return a compact human-readable byte count."""
    value = float(value)
    units = ('B', 'KB', 'MB', 'GB', 'TB')
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == 'B':
                return '%d%s' % (int(value), unit)
            return '%.1f%s' % (value, unit)
        value /= 1024.0
    return '%.1fTB' % value


def _safe_name(path):
    """Return a filesystem-safe suffix for a device path."""
    return os.path.basename(path).replace('/', '_')


def _read_text(path, limit=65536):
    """Read a small text file for metadata, returning an empty string on error."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read(limit)
    except Exception:
        return ''


def _block_device_size(path):
    """Return the byte size of a block device or regular file."""
    if not os.path.exists(path):
        raise OSError(errno.ENOENT, 'Device not found', path)

    try:
        with open(path, 'rb', buffering=0) as handle:
            data = fcntl.ioctl(handle.fileno(), BLKGETSIZE64, b'\0' * 8)
            size = struct.unpack('Q', data)[0]
            if size > 0:
                return size
    except Exception:
        pass

    base = os.path.basename(path)
    sysfs_size = '/sys/class/block/%s/size' % base
    sectors = _read_text(sysfs_size).strip()
    if sectors.isdigit():
        return int(sectors) * 512

    stat_info = os.stat(path)
    if stat_info.st_size > 0:
        return stat_info.st_size

    raise OSError('Cannot determine size for %s' % path)


class RootFSBackupPlugin(object):
    """Back up iCopy-X boot/rootfs/userdata partitions with progress."""

    def __init__(self, host=None):
        self.host = host
        self._cancel = threading.Event()

    def on_destroy(self):
        """Request cancellation when the activity exits."""
        self._cancel.set()

    def do_backup(self):
        """Run the backup in a background thread."""
        self._cancel.clear()
        self.host.set_var('error_msg', '')
        self.host.set_var('result_text', '')
        self.host.set_progress(0, 'Preparing backup...')

        try:
            partitions = self._prepare_partitions()
            output_dir = self._create_output_dir()
            self._write_metadata(output_dir, partitions, 'started')

            total_bytes = sum(item['size'] for item in partitions)
            free_bytes = shutil.disk_usage(BACKUP_ROOT).free
            required = total_bytes + MIN_FREE_MARGIN
            if free_bytes < required:
                raise OSError(
                    'Need %s free, only %s available in %s' % (
                        _format_bytes(required),
                        _format_bytes(free_bytes),
                        UPAN_ROOT,
                    )
                )

            try:
                os.sync()
            except Exception:
                pass

            copied_total = 0
            results = []

            for index, part in enumerate(partitions, 1):
                self._raise_if_cancelled()
                copied = self._copy_partition(
                    output_dir,
                    part,
                    copied_total,
                    total_bytes,
                    index,
                    len(partitions),
                )
                copied_total += copied['bytes_copied']
                results.append(copied)

            self._write_manifest(output_dir, partitions, results, 'complete')
            self.host.set_progress(100, 'Backup complete')

            summary = self._summary_text(output_dir, results, total_bytes)
            self.host.set_var('result_text', summary)
            return {'status': 'done'}

        except BackupCancelled:
            self.host.set_var(
                'result_text',
                'Backup cancelled.\nPartial .part file removed.\nCheck /mnt/upan/backups/rootfs.'
            )
            return {'status': 'cancelled'}
        except Exception as exc:
            self.host.set_var('error_msg', str(exc))
            return {'status': 'error'}

    def _prepare_partitions(self):
        """Validate expected partitions and calculate their sizes."""
        partitions = []
        missing = []

        for label, path in PARTITIONS:
            if not os.path.exists(path):
                missing.append(path)
                continue
            size = _block_device_size(path)
            partitions.append({
                'label': label,
                'path': path,
                'size': size,
            })

        if missing:
            raise OSError('Missing device(s): %s' % ', '.join(missing))

        if not partitions:
            raise OSError('No partitions found to back up')

        return partitions

    def _create_output_dir(self):
        """Create a timestamped output directory on /mnt/upan."""
        if not os.path.isdir(UPAN_ROOT):
            raise OSError('%s is not mounted' % UPAN_ROOT)

        os.makedirs(BACKUP_ROOT, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.join(BACKUP_ROOT, stamp)
        suffix = 1
        while os.path.exists(output_dir):
            output_dir = os.path.join(BACKUP_ROOT, '%s_%02d' % (stamp, suffix))
            suffix += 1
        os.makedirs(output_dir)
        return output_dir

    def _write_metadata(self, output_dir, partitions, status):
        """Write useful system metadata beside the partition images."""
        meta = {
            'status': status,
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'note': 'p4 data partition skipped because /mnt/upan is the destination',
            'partitions': partitions,
            'uname': list(os.uname()) if hasattr(os, 'uname') else [],
            'cmdline': _read_text('/proc/cmdline'),
            'mounts': _read_text('/proc/mounts'),
            'os_release': _read_text('/etc/os-release'),
        }
        path = os.path.join(output_dir, 'metadata.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(meta, handle, indent=2, sort_keys=True)

    def _write_manifest(self, output_dir, partitions, results, status):
        """Write final backup manifest with sizes and SHA-256 hashes."""
        manifest = {
            'status': status,
            'completed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'backup_dir': output_dir,
            'note': 'Restore/mount these raw partition images from a trusted host.',
            'partitions': partitions,
            'images': results,
        }
        path = os.path.join(output_dir, 'manifest.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)

    def _copy_partition(self, output_dir, part, copied_before, total_bytes,
                        index, count):
        """Copy one partition to a .part file, then atomically rename it."""
        label = part['label']
        src_path = part['path']
        size = part['size']
        dev_name = _safe_name(src_path)
        final_name = '%s_%s.img' % (label, dev_name)
        final_path = os.path.join(output_dir, final_name)
        part_path = final_path + '.part'
        digest = hashlib.sha256()
        copied = 0
        last_update = 0.0

        message = '%d/%d %s 0%%' % (index, count, label)
        self.host.set_progress(int((copied_before * 100) / total_bytes), message)

        try:
            with open(src_path, 'rb', buffering=0) as source:
                with open(part_path, 'wb', buffering=0) as target:
                    while copied < size:
                        self._raise_if_cancelled()
                        to_read = min(CHUNK_SIZE, size - copied)
                        chunk = source.read(to_read)
                        if not chunk:
                            break
                        target.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)

                        now = time.time()
                        if now - last_update >= PROGRESS_INTERVAL_SEC or copied >= size:
                            last_update = now
                            total_done = copied_before + copied
                            total_pct = int((total_done * 100) / total_bytes)
                            part_pct = int((copied * 100) / size) if size else 100
                            msg = '%d/%d %s %d%% %s/%s' % (
                                index,
                                count,
                                label,
                                part_pct,
                                _format_bytes(copied),
                                _format_bytes(size),
                            )
                            self.host.set_progress(total_pct, msg)

                    target.flush()
                    os.fsync(target.fileno())

            if copied != size:
                raise IOError(
                    'Short read on %s: copied %s of %s' % (
                        src_path,
                        _format_bytes(copied),
                        _format_bytes(size),
                    )
                )

            os.rename(part_path, final_path)
            return {
                'label': label,
                'source': src_path,
                'file': final_name,
                'bytes_copied': copied,
                'sha256': digest.hexdigest(),
            }

        except BackupCancelled:
            self._remove_partial(part_path)
            raise
        except Exception:
            self._remove_partial(part_path)
            raise

    def _remove_partial(self, path):
        """Remove an incomplete .part file if present."""
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _raise_if_cancelled(self):
        """Abort if on_destroy requested cancellation."""
        if self._cancel.is_set():
            raise BackupCancelled()

    def _summary_text(self, output_dir, results, total_bytes):
        """Build the completion text shown on the device screen."""
        lines = [
            'Saved %s' % _format_bytes(total_bytes),
            output_dir.replace('/mnt/upan/', ''),
            '',
        ]
        for item in results:
            lines.append('%s: %s' % (
                item['label'],
                _format_bytes(item['bytes_copied']),
            ))
        lines.append('')
        lines.append('Pull files in PC-Mode.')
        return '\n'.join(lines)
