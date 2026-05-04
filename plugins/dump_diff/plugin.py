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

Compares the two newest logical dumps in a selected dump directory.  The
device UI is intentionally summary-first; use tools/dump_diff.py or the
emulator web page for detailed range output.
"""

import os

from lib import dump_diff
from lib import resources
from lib._constants import (
    BG_COLOR,
    BTN_BAR_Y0,
    CONTENT_Y0,
    NORMAL_TEXT_COLOR,
    SCREEN_W,
)


DUMP_ROOT = "/mnt/upan/dump"
VALID_EXT = (".bin", ".eml", ".txt", ".json", ".pm3")
VIEW_PAGE_SIZE = 64
IGNORED_NAMES = (".DS_Store",)
IGNORED_PREFIXES = ("._",)
PRIMARY_EXT_BY_TYPE = {
    "mf1": (".bin", ".eml"),
    "mfu": (".bin", ".eml"),
    "icode": (".bin", ".eml", ".json"),
    "iclass": (".bin", ".eml"),
    "legic": (".bin", ".eml"),
    "hf14a": (".bin", ".eml"),
    "t55xx": (".bin", ".eml", ".json"),
    "em4x05": (".bin", ".eml", ".json"),
    "felica": (".txt", ".bin"),
}
LF_TEXT_TYPES = (
    "em410x",
    "hid",
    "indala",
    "awid",
    "ioprox",
    "gproxii",
    "securakey",
    "viking",
    "pyramid",
    "fdx",
    "gallagher",
    "jablotron",
    "keri",
    "nedap",
    "noralsy",
    "pac",
    "paradox",
    "presco",
    "visa2000",
    "nexwatch",
)
for _key in LF_TEXT_TYPES:
    PRIMARY_EXT_BY_TYPE[_key] = (".txt", ".bin", ".pm3")

TYPE_ORDER = (
    ("mf1", "Mifare Classic"),
    ("mfu", "Ultralight/NTAG"),
    ("em410x", "EM410x"),
    ("hid", "HID Prox ID"),
    ("t55xx", "T5577"),
    ("icode", "ISO15693"),
    ("iclass", "iClass"),
    ("felica", "Felica"),
    ("viking", "Viking ID"),
    ("visa2000", "Visa2000 ID"),
    ("fdx", "Animal ID(FDX)"),
    ("paradox", "Paradox ID"),
    ("jablotron", "Jablotron ID"),
    ("pyramid", "Pyramid ID"),
    ("noralsy", "Noralsy ID"),
    ("nexwatch", "NexWatch ID"),
    ("securakey", "Securakey ID"),
    ("keri", "KERI ID"),
    ("ioprox", "IO Prox ID"),
    ("awid", "AWID ID"),
    ("legic", "Legic Mini 256"),
    ("pac", "PAC ID"),
    ("gproxii", "GProx II ID"),
    ("nedap", "NEDAP ID"),
    ("gallagher", "GALLAGHER ID"),
    ("presco", "Presco ID"),
    ("indala", "Indala ID"),
    ("em4x05", "EM4X05 ID"),
)
TYPE_LABELS = dict(TYPE_ORDER)
TYPE_KEYS = [key for key, _label in TYPE_ORDER]


class DumpDiffPlugin(object):
    """Entry class for PluginActivity."""

    def __init__(self, host=None):
        self.host = host
        self._type_index = 0
        self._clear_viewer_data()

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
        self._clear_viewer_data()
        self.host.set_progress(5, "Finding dumps...")

        directory = os.path.join(DUMP_ROOT, key)
        try:
            dumps = self._list_comparable_dumps(directory, key)
            if len(dumps) < 2:
                self.host.set_var(
                    "error_msg",
                    "Need at least two comparable %s dumps." % label,
                )
                return {"status": "error"}

            newest = dumps[-1]["path"]
            previous = dumps[-2]["path"]
            self.host.set_progress(30, "Comparing...")

            dtype = "mfc" if key == "mf1" else ("mfu" if key == "mfu" else "binary")
            result = dump_diff.compare_files(previous, newest, dump_type=dtype)
            summary = self._format_device_summary(previous, newest, result)

            self._last_previous = previous
            self._last_newest = newest
            self._last_result = result
            self._last_dump_type = dtype
            self._viewer_page = self._first_changed_page(result)

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
            if self._is_ignored_name(name):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            if not name.lower().endswith(VALID_EXT):
                continue
            result.append(path)
        result.sort(key=lambda p: (os.path.getmtime(p), p))
        return result

    def _list_comparable_dumps(self, directory, dump_type_key):
        """Return logical dumps, one selected file per stem."""
        groups = {}
        for path in self._list_dump_files(directory):
            stem = os.path.splitext(os.path.basename(path))[0]
            groups.setdefault(stem, []).append(path)

        result = []
        for stem, paths in groups.items():
            selected = self._select_primary_dump_file(paths, dump_type_key)
            if selected is None:
                continue
            result.append({
                "stem": stem,
                "path": selected,
                "mtime": max(os.path.getmtime(p) for p in paths),
            })
        result.sort(key=lambda item: (item["mtime"], item["stem"], item["path"]))
        return result

    def _select_primary_dump_file(self, paths, dump_type_key):
        if not paths:
            return None
        by_ext = {}
        for path in sorted(paths):
            ext = os.path.splitext(path)[1].lower()
            by_ext.setdefault(ext, path)

        priority = PRIMARY_EXT_BY_TYPE.get(
            dump_type_key,
            (".bin", ".txt", ".pm3", ".eml", ".json"),
        )
        for ext in priority:
            if ext in by_ext:
                return by_ext[ext]
        for ext in VALID_EXT:
            if ext in by_ext:
                return by_ext[ext]
        return sorted(paths)[0]

    def _is_ignored_name(self, name):
        if name in IGNORED_NAMES:
            return True
        return any(name.startswith(prefix) for prefix in IGNORED_PREFIXES)

    def _format_device_summary(self, previous, newest, result):
        lines = [
            os.path.basename(previous),
            "vs",
            os.path.basename(newest),
            "",
            dump_diff.format_summary(result, detail_ranges=3),
        ]
        return "\n".join(lines)

    def _clear_viewer_data(self):
        self._last_previous = None
        self._last_newest = None
        self._last_result = None
        self._last_dump_type = "binary"
        self._viewer_page = 0
        self._viewer_changed_only = False
        self._viewer_detail = True
        self._viewer_side = "B"

    def _first_changed_page(self, result):
        first = (result or {}).get("first_diff_offset")
        if first is None:
            return 0
        try:
            return max(0, int(first) // VIEW_PAGE_SIZE)
        except (TypeError, ValueError):
            return 0

    def show_viewer(self):
        """Draw the custom 64-byte diff page in the content area."""
        canvas = self._canvas()
        if canvas is None:
            return {"status": "idle"}

        canvas.delete("_jr_content")

        if not self._viewer_ready():
            self._draw_viewer_message(canvas, "No diff data")
            return {"status": "idle"}

        page_count = self._viewer_page_count()
        self._viewer_page = max(0, min(self._viewer_page, page_count - 1))
        if self._viewer_changed_only and self._viewer_changed_pages():
            if self._viewer_page not in self._viewer_changed_pages():
                self._viewer_page = self._viewer_changed_pages()[0]

        label = self._viewer_page_label(self._viewer_page)
        try:
            self.host.setTitle(
                "Diff %s %s %d/%d" % (
                    label,
                    self._viewer_side,
                    self._viewer_page + 1,
                    page_count,
                )
            )
        except Exception:
            pass

        canvas.create_rectangle(
            0,
            CONTENT_Y0,
            SCREEN_W,
            BTN_BAR_Y0,
            fill=BG_COLOR,
            outline="",
            tags="_jr_content",
        )

        offset = self._viewer_page * VIEW_PAGE_SIZE
        old_values = self._read_page_values(self._last_previous, offset)
        new_values = self._read_page_values(self._last_newest, offset)
        display_values = old_values if self._viewer_side == "A" else new_values
        changed_offsets = self._page_changed_offsets(self._viewer_page)
        changed_set = set(changed_offsets)
        total_changed_pages = len(self._viewer_changed_pages())
        mode = "Changed" if self._viewer_changed_only else "All"
        side_label = "A Old" if self._viewer_side == "A" else "B New"

        self._draw_text(
            canvas,
            8,
            44,
            "%s  %s  %d/%d page  %d/64 chg" % (
                side_label,
                mode,
                total_changed_pages,
                page_count,
                len(changed_offsets),
            ),
            fill="#4A4A4A",
            size=8,
        )

        y0 = 59
        row_h = 14
        label_x = 6
        byte_x0 = 50
        byte_gap = 22
        font_size = 9
        for row in range(8):
            row_offset = offset + row * 8
            y = y0 + row * row_h
            self._draw_text(
                canvas,
                label_x,
                y,
                "%04X" % row_offset,
                fill="#666666",
                size=8,
            )
            for col in range(8):
                idx = row * 8 + col
                abs_offset = offset + idx
                old_byte = old_values[idx]
                new_byte = new_values[idx]
                display_byte = display_values[idx]
                changed = abs_offset in changed_set
                x = byte_x0 + col * byte_gap
                text, fill, bg = self._byte_cell_style(
                    old_byte,
                    new_byte,
                    display_byte,
                    changed,
                )
                if bg:
                    canvas.create_rectangle(
                        x - 2,
                        y - 1,
                        x + 15,
                        y + 11,
                        fill=bg,
                        outline="",
                        tags="_jr_content",
                    )
                self._draw_text(canvas, x, y, text, fill=fill, size=font_size)

        self._draw_detail(canvas, old_values, new_values, changed_offsets, offset)
        return {"status": "idle"}

    def viewer_next_page(self):
        return self._viewer_step_page(1)

    def viewer_prev_page(self):
        return self._viewer_step_page(-1)

    def viewer_next_changed(self):
        return self._viewer_step_changed(1)

    def viewer_prev_changed(self):
        return self._viewer_step_changed(-1)

    def viewer_toggle_changed_only(self):
        self._viewer_changed_only = not self._viewer_changed_only
        changed_pages = self._viewer_changed_pages()
        if self._viewer_changed_only and changed_pages:
            if self._viewer_page not in changed_pages:
                self._viewer_page = self._next_changed_page_after(
                    self._viewer_page,
                    1,
                    changed_pages,
                )
        return self.show_viewer()

    def viewer_toggle_detail(self):
        self._viewer_detail = not self._viewer_detail
        return self.show_viewer()

    def viewer_toggle_side(self):
        self._viewer_side = "A" if self._viewer_side == "B" else "B"
        return self.show_viewer()

    def _viewer_step_page(self, step):
        if not self._viewer_ready():
            return self.show_viewer()
        if self._viewer_changed_only and self._viewer_changed_pages():
            return self._viewer_step_changed(step)
        page_count = self._viewer_page_count()
        if page_count > 0:
            self._viewer_page = (self._viewer_page + step) % page_count
        return self.show_viewer()

    def _viewer_step_changed(self, step):
        changed_pages = self._viewer_changed_pages()
        if changed_pages:
            self._viewer_page = self._next_changed_page_after(
                self._viewer_page,
                step,
                changed_pages,
            )
        return self.show_viewer()

    def _next_changed_page_after(self, current_page, step, changed_pages):
        if not changed_pages:
            return current_page
        if current_page in changed_pages:
            pos = changed_pages.index(current_page)
            return changed_pages[(pos + step) % len(changed_pages)]
        if step >= 0:
            for page in changed_pages:
                if page > current_page:
                    return page
            return changed_pages[0]
        for page in reversed(changed_pages):
            if page < current_page:
                return page
        return changed_pages[-1]

    def _viewer_ready(self):
        return bool(self._last_previous and self._last_newest and self._last_result)

    def _viewer_page_count(self):
        if not self._viewer_ready():
            return 1
        size_a = int(self._last_result.get("size_a", 0) or 0)
        size_b = int(self._last_result.get("size_b", 0) or 0)
        max_size = max(size_a, size_b)
        if max_size <= 0:
            return 1
        return (max_size + VIEW_PAGE_SIZE - 1) // VIEW_PAGE_SIZE

    def _viewer_changed_pages(self):
        if not self._viewer_ready():
            return []
        page_count = self._viewer_page_count()
        pages = set()
        for item in self._last_result.get("ranges", []):
            try:
                start = int(item.get("start", 0))
                end = int(item.get("end", 0))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            first = start // VIEW_PAGE_SIZE
            last = (end - 1) // VIEW_PAGE_SIZE
            for page in range(first, last + 1):
                if 0 <= page < page_count:
                    pages.add(page)
        return sorted(pages)

    def _page_changed_offsets(self, page):
        if not self._viewer_ready():
            return []
        offset = page * VIEW_PAGE_SIZE
        old_values = self._read_page_values(self._last_previous, offset)
        new_values = self._read_page_values(self._last_newest, offset)
        changed = []
        for idx, old_byte in enumerate(old_values):
            if old_byte != new_values[idx]:
                changed.append(offset + idx)
        return changed

    def _read_page_values(self, path, offset):
        values = []
        try:
            with open(path, "rb") as handle:
                handle.seek(offset)
                values = list(handle.read(VIEW_PAGE_SIZE))
        except Exception:
            values = []
        if len(values) < VIEW_PAGE_SIZE:
            values.extend([None] * (VIEW_PAGE_SIZE - len(values)))
        return values[:VIEW_PAGE_SIZE]

    def _byte_cell_style(self, old_byte, new_byte, display_byte, changed):
        if display_byte is None:
            text = "--"
        else:
            text = "%02X" % display_byte
        if not changed:
            return text, NORMAL_TEXT_COLOR, None

        if self._viewer_side == "A":
            return text, "#C7332B", "#FCE9E7"

        if new_byte is None:
            return text, "#C7332B", "#FCE9E7"
        if old_byte is None:
            return text, "#008A3A", "#E7F7EC"
        return text, "#008A3A", "#E7F7EC"

    def _draw_detail(self, canvas, old_values, new_values, changed_offsets, offset):
        if not self._viewer_detail or not changed_offsets:
            return
        abs_offset = changed_offsets[0]
        idx = abs_offset - offset
        old_text = self._byte_text(old_values[idx])
        new_text = self._byte_text(new_values[idx])
        y = 181
        self._draw_text(canvas, 8, y, "0x%04X" % abs_offset, fill="#4A4A4A", size=9)
        self._draw_text(canvas, 64, y, "A %s" % old_text, fill="#C7332B", size=9)
        self._draw_text(canvas, 122, y, "B %s" % new_text, fill="#008A3A", size=9)

    def _byte_text(self, value):
        if value is None:
            return "--"
        return "%02X" % value

    def _viewer_page_label(self, page):
        offset = page * VIEW_PAGE_SIZE
        if self._last_dump_type == "mfc":
            block = offset // 16
            if block < 128:
                return "S%02d" % (block // 4)
            sector = 32 + ((block - 128) // 16)
            sector_page = ((block - 128) % 16) // 4
            return "S%02d.%d" % (sector, sector_page + 1)
        if self._last_dump_type == "mfu":
            return "P%03d" % (offset // 4)
        return "0x%04X" % offset

    def _draw_viewer_message(self, canvas, text):
        canvas.create_rectangle(
            0,
            CONTENT_Y0,
            SCREEN_W,
            BTN_BAR_Y0,
            fill=BG_COLOR,
            outline="",
            tags="_jr_content",
        )
        self._draw_text(canvas, 120, 112, text, fill=NORMAL_TEXT_COLOR, size=11, anchor="center")

    def _draw_text(self, canvas, x, y, text, fill=NORMAL_TEXT_COLOR, size=9, anchor="nw"):
        canvas.create_text(
            x,
            y,
            text=text,
            fill=fill,
            anchor=anchor,
            font=resources.get_font_force_en(size),
            tags="_jr_content",
        )

    def _canvas(self):
        getter = getattr(self.host, "getCanvas", None)
        if not callable(getter):
            return None
        return getter()
