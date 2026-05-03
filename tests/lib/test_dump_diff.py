import os

from lib import dump_diff


def _write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def test_equal_files(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    _write(a, b"\x00" * 64)
    _write(b, b"\x00" * 64)

    result = dump_diff.compare_files(str(a), str(b), dump_type="binary")

    assert result["equal"] is True
    assert result["changed_bytes"] == 0
    assert result["ranges"] == []
    assert result["first_diff_offset"] is None


def test_changed_ranges_merge_contiguous_bytes(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    _write(a, bytes(range(32)))
    data = bytearray(range(32))
    data[2] ^= 0xFF
    data[3] ^= 0xFF
    data[10] ^= 0xFF
    _write(b, bytes(data))

    result = dump_diff.compare_files(str(a), str(b), dump_type="binary")

    assert result["equal"] is False
    assert result["changed_bytes"] == 3
    assert result["first_diff_offset"] == 2
    assert result["ranges"] == [
        {"start": 2, "end": 4, "length": 2},
        {"start": 10, "end": 11, "length": 1},
    ]


def test_size_difference_counts_added_tail(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    _write(a, b"abc")
    _write(b, b"abcde")

    result = dump_diff.compare_files(str(a), str(b), dump_type="binary")

    assert result["equal_size"] is False
    assert result["changed_bytes"] == 2
    assert result["first_diff_offset"] == 3
    assert result["ranges"] == [{"start": 3, "end": 5, "length": 2}]


def test_mfc_grouping_blocks_sectors_and_trailers(tmp_path):
    a = tmp_path / "M1-1K-4B_AABBCCDD_1.bin"
    b = tmp_path / "M1-1K-4B_AABBCCDD_2.bin"
    _write(a, b"\x00" * 1024)
    data = bytearray(b"\x00" * 1024)
    data[16] = 1       # block 1
    data[63] = 1       # block 3 trailer
    data[128] = 1      # block 8 sector 2
    _write(b, bytes(data))

    result = dump_diff.compare_files(str(a), str(b))
    grouping = result["grouping"]

    assert result["dump_type"] == "mfc"
    assert grouping["blocks_changed"] == [1, 3, 8]
    assert grouping["sectors_changed"] == [0, 2]
    assert grouping["sector_trailers_changed"] == [3]


def test_mfu_grouping_pages(tmp_path):
    a = tmp_path / "M0-UL_AABBCCDDEEFF00_1.bin"
    b = tmp_path / "M0-UL_AABBCCDDEEFF00_2.bin"
    _write(a, b"\x00" * 32)
    data = bytearray(b"\x00" * 32)
    data[5] = 1
    data[12] = 1
    _write(b, bytes(data))

    result = dump_diff.compare_files(str(a), str(b), dump_type="mfu")

    assert result["grouping"]["pages_changed"] == [1, 3]
    assert "Pages: 2" in dump_diff.format_summary(result)

