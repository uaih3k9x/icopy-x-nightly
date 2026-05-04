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

"""Dump Diff plugin.

Compares the two newest dump files in a selected dump directory.  The device
UI is intentionally summary-first; use tools/dump_diff.py or the emulator web
page for detailed range output.
"""

import os

from lib import dump_diff


DUMP_ROOT = "/mnt/upan/dump"
VALID_EXT = (".bin", ".eml", ".txt", ".json", ".pm3")
TYPE_ORDER = (
    ("mf1", "Mifare Classic"),
    ("mfu", "Ultralight/NTAG"),
    ("t55xx", "T5577"),
    ("em410x", "EM410x"),
    ("hid", "HID"),
    ("icode", "ISO15693"),
    ("iclass", "iClass"),
)
TYPE_LABELS = dict(TYPE_ORDER)
TYPE_KEYS = [key for key, _label in TYPE_ORDER]


class DumpDiffPlugin(object):
    """Entry class for PluginActivity."""

    def __init__(self, host=None):
        self.host = host
        self._type_index = 0

    def on_load(self):
        """Initialize screen placeholders before the first render."""
        self._set_type_label()

    def _current_type(self):
        return TYPE_ORDER[self._type_index]

    def _set_type_label(self):
        key, label = self._current_type()
        self.host.set_var("dump_type_key", key)
        self.host.set_var("dump_type", label)

    def _selected_type(self):
        key = self.host.get_var("dump_type_key", TYPE_ORDER[self._type_index][0])
        if key not in TYPE_LABELS:
            key = TYPE_ORDER[0][0]
        self._type_index = TYPE_KEYS.index(key)
        label = TYPE_LABELS[key]
        self.host.set_var("dump_type_key", key)
        self.host.set_var("dump_type", label)
        return key, label

    def next_type(self):
        """Cycle the target dump directory."""
        self._type_index = (self._type_index + 1) % len(TYPE_ORDER)
        self._set_type_label()
        return {"status": "idle"}

    def compare_latest(self):
        """Compare the newest two files for the selected dump type."""
        key, label = self._selected_type()
        self.host.set_var("error_msg", "")
        self.host.set_var("result_text", "")
        self.host.set_progress(5, "Finding dumps...")

        directory = os.path.join(DUMP_ROOT, key)
        try:
            files = self._list_dump_files(directory)
            if len(files) < 2:
                self.host.set_var(
                    "error_msg",
                    "Need at least two %s dumps." % label,
                )
                return {"status": "error"}

            newest = files[-1]
            previous = files[-2]
            self.host.set_progress(30, "Comparing...")

            dtype = "mfc" if key == "mf1" else ("mfu" if key == "mfu" else "binary")
            result = dump_diff.compare_files(previous, newest, dump_type=dtype)
            summary = self._format_device_summary(previous, newest, result)

            self.host.set_progress(100, "Done")
            self.host.set_var("result_text", summary)
            return {"status": "done"}
        except Exception as exc:
            self.host.set_var("error_msg", str(exc))
            return {"status": "error"}

    def _list_dump_files(self, directory):
        if not os.path.isdir(directory):
            return []
        result = []
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            if not name.lower().endswith(VALID_EXT):
                continue
            result.append(path)
        result.sort(key=lambda p: (os.path.getmtime(p), p))
        return result

    def _format_device_summary(self, previous, newest, result):
        lines = [
            os.path.basename(previous),
            "vs",
            os.path.basename(newest),
            "",
            dump_diff.format_summary(result, detail_ranges=3),
        ]
        return "\n".join(lines)
