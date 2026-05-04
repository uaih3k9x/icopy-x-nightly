"""Tests for Dump Diff plugin logical dump selection behavior."""

import json
import os

from plugins.dump_diff.plugin import DumpDiffPlugin, TYPE_ORDER


class FakeCanvas(object):
    def __init__(self):
        self.items = []
        self.deleted = []

    def delete(self, tag):
        self.deleted.append(tag)
        self.items = [
            item for item in self.items
            if tag not in item.get("tags", ())
        ]

    def create_rectangle(self, x1, y1, x2, y2, **kwargs):
        return self._store("rectangle", (x1, y1, x2, y2), kwargs)

    def create_text(self, x, y, **kwargs):
        return self._store("text", (x, y), kwargs)

    def _store(self, kind, coords, kwargs):
        tags = kwargs.get("tags", ())
        if isinstance(tags, str):
            tags = (tags,)
        item = {
            "type": kind,
            "coords": coords,
            "options": dict(kwargs),
            "tags": tuple(tags),
        }
        self.items.append(item)
        return len(self.items)

    def texts(self):
        return [
            item["options"]["text"]
            for item in self.items
            if item["type"] == "text"
        ]


class FakeHost(object):
    def __init__(self, values=None, canvas=None):
        self.values = dict(values or {})
        self.progress = []
        self.canvas = canvas
        self.title = ""

    def set_var(self, key, value):
        self.values[key] = value

    def get_var(self, key, default=None):
        return self.values.get(key, default)

    def set_progress(self, value, message):
        self.progress.append((value, message))

    def getCanvas(self):
        return self.canvas

    def setTitle(self, title):
        self.title = title


def _write(path, data=b"\x00", mtime=1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(str(path), (mtime, mtime))


def test_common_dump_types_are_first_and_ui_matches_plugin_order():
    expected_first = ["mf1", "mfu", "em410x", "hid", "t55xx"]
    assert [key for key, _label in TYPE_ORDER[:5]] == expected_first

    ui_path = os.path.join(
        os.path.dirname(__file__),
        "../../../plugins/dump_diff/ui.json",
    )
    with open(ui_path, "r", encoding="utf-8") as handle:
        ui = json.load(handle)
    items = ui["states"]["idle"]["screen"]["content"]["items"]

    assert [item["value"] for item in items] == [
        key for key, _label in TYPE_ORDER
    ]
    assert [item["label"] for item in items] == [
        label for _key, label in TYPE_ORDER
    ]


def test_mf1_sidecars_count_as_one_logical_dump(tmp_path):
    plugin = DumpDiffPlugin(FakeHost())
    directory = tmp_path / "mf1"

    _write(directory / "M1-1K-4B_AAAAAAAA_1.bin", b"a" * 1024, 100)
    _write(directory / "M1-1K-4B_AAAAAAAA_1.eml", b"eml-one", 100)
    _write(directory / "M1-1K-4B_BBBBBBBB_2.bin", b"b" * 1024, 200)
    _write(directory / "M1-1K-4B_BBBBBBBB_2.eml", b"eml-two", 200)

    dumps = plugin._list_comparable_dumps(str(directory), "mf1")

    assert [os.path.basename(item["path"]) for item in dumps] == [
        "M1-1K-4B_AAAAAAAA_1.bin",
        "M1-1K-4B_BBBBBBBB_2.bin",
    ]


def test_single_t55xx_dump_with_sidecars_is_not_comparable(tmp_path):
    plugin = DumpDiffPlugin(FakeHost())
    directory = tmp_path / "t55xx"

    _write(directory / "T55XX_1.bin", b"b" * 48, 100)
    _write(directory / "T55XX_1.eml", b"eml", 100)
    _write(directory / "T55XX_1.json", b"{}", 100)

    dumps = plugin._list_comparable_dumps(str(directory), "t55xx")

    assert len(dumps) == 1
    assert os.path.basename(dumps[0]["path"]) == "T55XX_1.bin"


def test_compare_latest_rejects_only_one_logical_dump(tmp_path, monkeypatch):
    plugin = DumpDiffPlugin(FakeHost({"dump_type_key": "t55xx"}))
    monkeypatch.setattr("plugins.dump_diff.plugin.DUMP_ROOT", str(tmp_path))
    directory = tmp_path / "t55xx"

    _write(directory / "T55XX_1.bin", b"b" * 48, 100)
    _write(directory / "T55XX_1.eml", b"eml", 100)
    _write(directory / "T55XX_1.json", b"{}", 100)

    result = plugin.compare_latest()

    assert result == {"status": "error"}
    assert plugin.host.values["error_msg"] == (
        "Need at least two comparable T5577 dumps."
    )


def test_appledouble_files_are_ignored(tmp_path):
    plugin = DumpDiffPlugin(FakeHost())
    directory = tmp_path / "mf1"

    _write(directory / "._M1-1K-4B_AAAAAAAA_1.eml", b"appledouble", 300)
    _write(directory / "M1-1K-4B_AAAAAAAA_1.bin", b"a" * 1024, 100)
    _write(directory / "M1-1K-4B_BBBBBBBB_2.bin", b"b" * 1024, 200)

    files = plugin._list_dump_files(str(directory))
    dumps = plugin._list_comparable_dumps(str(directory), "mf1")

    assert all(not os.path.basename(path).startswith("._") for path in files)
    assert [os.path.basename(item["path"]) for item in dumps] == [
        "M1-1K-4B_AAAAAAAA_1.bin",
        "M1-1K-4B_BBBBBBBB_2.bin",
    ]


def test_text_types_prefer_txt(tmp_path):
    plugin = DumpDiffPlugin(FakeHost())
    directory = tmp_path / "felica"

    _write(directory / "FeliCa_01120412CF22A42F_1.bin", b"binary", 100)
    _write(directory / "FeliCa_01120412CF22A42F_1.txt", b"text", 100)
    _write(directory / "FeliCa_012E59242B527338_2.txt", b"text-2", 200)

    dumps = plugin._list_comparable_dumps(str(directory), "felica")

    assert [os.path.basename(item["path"]) for item in dumps] == [
        "FeliCa_01120412CF22A42F_1.txt",
        "FeliCa_012E59242B527338_2.txt",
    ]


def test_compare_latest_uses_primary_files_not_sidecars(tmp_path, monkeypatch):
    host = FakeHost({"dump_type_key": "mf1"})
    plugin = DumpDiffPlugin(host)
    monkeypatch.setattr("plugins.dump_diff.plugin.DUMP_ROOT", str(tmp_path))
    directory = tmp_path / "mf1"

    _write(directory / "M1-1K-4B_AAAAAAAA_1.bin", b"\x00" * 1024, 100)
    _write(directory / "M1-1K-4B_AAAAAAAA_1.eml", b"eml-one", 100)
    _write(directory / "M1-1K-4B_BBBBBBBB_2.bin", b"\x01" * 1024, 200)
    _write(directory / "M1-1K-4B_BBBBBBBB_2.eml", b"eml-two", 200)

    result = plugin.compare_latest()

    assert result == {"status": "done"}
    assert "M1-1K-4B_AAAAAAAA_1.bin" in host.values["result_text"]
    assert "M1-1K-4B_BBBBBBBB_2.bin" in host.values["result_text"]
    assert ".eml" not in host.values["result_text"]


def test_compare_latest_stores_viewer_state(tmp_path, monkeypatch):
    host = FakeHost({"dump_type_key": "mf1"})
    plugin = DumpDiffPlugin(host)
    monkeypatch.setattr("plugins.dump_diff.plugin.DUMP_ROOT", str(tmp_path))
    directory = tmp_path / "mf1"

    old_data = bytearray(b"\x00" * 128)
    new_data = bytearray(old_data)
    new_data[70] = 0xAA
    _write(directory / "M1-1K-4B_AAAAAAAA_1.bin", bytes(old_data), 100)
    _write(directory / "M1-1K-4B_BBBBBBBB_2.bin", bytes(new_data), 200)

    result = plugin.compare_latest()

    assert result == {"status": "done"}
    assert plugin._last_previous.endswith("AAAAAAAA_1.bin")
    assert plugin._last_newest.endswith("BBBBBBBB_2.bin")
    assert plugin._last_dump_type == "mfc"
    assert plugin._viewer_page == 1
    assert plugin._viewer_changed_pages() == [1]


def test_viewer_changed_pages_and_changed_only_navigation(tmp_path):
    old_path = tmp_path / "old.bin"
    new_path = tmp_path / "new.bin"
    old_data = bytearray(b"\x00" * 192)
    new_data = bytearray(old_data)
    new_data[2] = 0x11
    new_data[130] = 0x22
    _write(old_path, bytes(old_data), 100)
    _write(new_path, bytes(new_data), 200)

    host = FakeHost(canvas=FakeCanvas())
    plugin = DumpDiffPlugin(host)
    plugin._last_previous = str(old_path)
    plugin._last_newest = str(new_path)
    plugin._last_result = {
        "size_a": 192,
        "size_b": 192,
        "ranges": [
            {"start": 2, "end": 3, "length": 1},
            {"start": 130, "end": 131, "length": 1},
        ],
    }
    plugin._last_dump_type = "mfc"

    assert plugin._viewer_changed_pages() == [0, 2]

    plugin.viewer_toggle_changed_only()
    assert plugin._viewer_changed_only is True
    assert plugin._viewer_page == 0

    plugin.viewer_next_page()
    assert plugin._viewer_page == 2

    plugin.viewer_prev_page()
    assert plugin._viewer_page == 0


def test_show_viewer_draws_hex_grid_and_highlights_changed_byte(tmp_path):
    old_path = tmp_path / "old.bin"
    new_path = tmp_path / "new.bin"
    old_data = bytearray(range(64))
    new_data = bytearray(old_data)
    new_data[3] = 0xFE
    _write(old_path, bytes(old_data), 100)
    _write(new_path, bytes(new_data), 200)

    canvas = FakeCanvas()
    host = FakeHost(canvas=canvas)
    plugin = DumpDiffPlugin(host)
    plugin._last_previous = str(old_path)
    plugin._last_newest = str(new_path)
    plugin._last_result = {
        "size_a": 64,
        "size_b": 64,
        "first_diff_offset": 3,
        "ranges": [{"start": 3, "end": 4, "length": 1}],
    }
    plugin._last_dump_type = "mfc"

    plugin.show_viewer()

    texts = canvas.texts()
    assert "FE" in texts
    assert "0x0003" in texts
    assert "A 03" in texts
    assert "B FE" in texts
    assert any(text.startswith("B New") for text in texts)
    assert host.title == "Diff S00 B 1/1"
    changed_cells = [
        item for item in canvas.items
        if item["type"] == "text"
        and item["options"].get("text") == "FE"
        and item["options"].get("fill") == "#008A3A"
    ]
    assert len(changed_cells) == 1


def test_viewer_toggle_side_switches_between_b_and_a_cards(tmp_path):
    old_path = tmp_path / "old.bin"
    new_path = tmp_path / "new.bin"
    old_data = bytearray(range(64))
    new_data = bytearray(old_data)
    new_data[3] = 0xFE
    _write(old_path, bytes(old_data), 100)
    _write(new_path, bytes(new_data), 200)

    canvas = FakeCanvas()
    host = FakeHost(canvas=canvas)
    plugin = DumpDiffPlugin(host)
    plugin._last_previous = str(old_path)
    plugin._last_newest = str(new_path)
    plugin._last_result = {
        "size_a": 64,
        "size_b": 64,
        "first_diff_offset": 3,
        "ranges": [{"start": 3, "end": 4, "length": 1}],
    }
    plugin._last_dump_type = "mfc"

    plugin.show_viewer()
    assert plugin._viewer_side == "B"
    assert host.title == "Diff S00 B 1/1"

    plugin.viewer_toggle_side()

    texts = canvas.texts()
    assert plugin._viewer_side == "A"
    assert host.title == "Diff S00 A 1/1"
    assert any(text.startswith("A Old") for text in texts)
    changed_cells = [
        item for item in canvas.items
        if item["type"] == "text"
        and item["options"].get("text") == "03"
        and item["options"].get("fill") == "#C7332B"
    ]
    assert len(changed_cells) == 1
