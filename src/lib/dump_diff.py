##########################################################################
# Required Notice: Copyright ETOILE401 SAS (http://www.lab401.com)
#
# Initial author: ETOILE401 SAS & https://github.com/quantum-x/ as of April 16, 2026
#
# Since this date, each contribution is under the copyright of its respective author.
#
# Copyright of each contribution is tracked by the Git history. See the output of git shortlog -nse for a full list or git log --pretty=short --follow <path/to/sourcefile> |git shortlog -ne to track a specific file.
#
# A mailmap is maintained to map author and committer names and email addresses to canonical names and email addresses.
# If by accident a copyright was removed from a file and is not directly deducible from the Git history, please submit a PR.
#
#
# This software is licensed under the PolyForm Noncommercial License 1.0.0.
# You may not use this software for commercial purposes.
#
# A copy of the license is available at:
# https://polyformproject.org/licenses/noncommercial/1.0.0
#
# This entire header "Required Notice" must remain in place.
##########################################################################

"""Binary dump diff helpers for card dump validation.

The core functions are deliberately hardware-free.  They compare two local
dump files, report SHA-256/size/equality, compact byte ranges, and optionally
group changes into MIFARE Classic blocks/sectors or Ultralight pages.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class DiffRange:
    """Contiguous half-open byte range [start, end)."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start

    def to_dict(self) -> Dict[str, int]:
        return {
            "start": self.start,
            "end": self.end,
            "length": self.length,
        }


def sha256_file(path: str) -> str:
    """Return SHA-256 hex digest for *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _append_range(ranges: List[DiffRange], start: int, end: int) -> None:
    """Append or merge a changed byte range."""
    if start >= end:
        return
    if ranges and ranges[-1].end == start:
        ranges[-1] = DiffRange(ranges[-1].start, end)
    else:
        ranges.append(DiffRange(start, end))


def _changed_ranges_equal_size(path_a: str, path_b: str) -> Tuple[int, Optional[int], List[DiffRange]]:
    """Scan equal-sized files and return changed byte count/ranges."""
    changed = 0
    first_diff = None
    ranges: List[DiffRange] = []
    offset = 0

    with open(path_a, "rb") as a, open(path_b, "rb") as b:
        while True:
            ba = a.read(CHUNK_SIZE)
            bb = b.read(CHUNK_SIZE)
            if not ba and not bb:
                break
            if ba == bb:
                offset += len(ba)
                continue

            run_start = None
            for idx, (xa, xb) in enumerate(zip(ba, bb)):
                if xa != xb:
                    abs_pos = offset + idx
                    changed += 1
                    if first_diff is None:
                        first_diff = abs_pos
                    if run_start is None:
                        run_start = abs_pos
                elif run_start is not None:
                    _append_range(ranges, run_start, offset + idx)
                    run_start = None
            if run_start is not None:
                _append_range(ranges, run_start, offset + min(len(ba), len(bb)))
            offset += len(ba)

    return changed, first_diff, ranges


def _mfc_sector_for_block(block: int) -> int:
    """Return MIFARE Classic sector number for a block index."""
    if block < 0:
        return -1
    if block < 128:
        return block // 4
    return 32 + ((block - 128) // 16)


def _mfc_block_is_trailer(block: int) -> bool:
    """Return True if *block* is a MIFARE Classic sector trailer."""
    if block < 0:
        return False
    if block < 128:
        return block % 4 == 3
    return (block - 128) % 16 == 15


def _span_indexes(ranges: Iterable[DiffRange], unit_size: int) -> List[int]:
    """Return sorted unit indexes touched by changed ranges."""
    indexes = set()
    for r in ranges:
        if r.length <= 0:
            continue
        first = r.start // unit_size
        last = (r.end - 1) // unit_size
        indexes.update(range(first, last + 1))
    return sorted(indexes)


def classify_dump(path: str, hint: Optional[str] = None) -> str:
    """Classify a dump by hint/name/size.

    Returns one of: ``mfc``, ``mfu``, ``binary``.
    """
    hint_l = (hint or "").lower()
    name_l = os.path.basename(path).lower()
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0

    if hint_l in ("mfc", "mf1", "mifare", "mifare-classic"):
        return "mfc"
    if hint_l in ("mfu", "ultralight", "ntag"):
        return "mfu"
    if size in (320, 1024, 2048, 4096) or name_l.startswith("m1-"):
        return "mfc"
    if "/mfu/" in path.lower() or name_l.startswith(("m0-", "ntag", "mfu")):
        return "mfu"
    return "binary"


def group_changes(ranges: Iterable[DiffRange], dump_type: str) -> Dict[str, object]:
    """Build block/page-aware summaries for changed byte ranges."""
    if dump_type == "mfc":
        blocks = _span_indexes(ranges, 16)
        sectors = sorted({_mfc_sector_for_block(block) for block in blocks})
        trailers = [block for block in blocks if _mfc_block_is_trailer(block)]
        return {
            "unit": "mfc-block",
            "blocks_changed": blocks,
            "block_count": len(blocks),
            "sectors_changed": sectors,
            "sector_count": len(sectors),
            "sector_trailers_changed": trailers,
            "sector_trailer_count": len(trailers),
        }
    if dump_type == "mfu":
        pages = _span_indexes(ranges, 4)
        return {
            "unit": "mfu-page",
            "pages_changed": pages,
            "page_count": len(pages),
        }
    return {
        "unit": "byte",
    }


def compare_files(path_a: str, path_b: str, dump_type: Optional[str] = None) -> Dict[str, object]:
    """Compare two dump files and return a structured summary."""
    size_a = os.path.getsize(path_a)
    size_b = os.path.getsize(path_b)
    sha_a = sha256_file(path_a)
    sha_b = sha256_file(path_b)
    equal_size = size_a == size_b
    equal = equal_size and sha_a == sha_b

    if equal_size:
        changed, first_diff, ranges = _changed_ranges_equal_size(path_a, path_b)
    else:
        common = min(size_a, size_b)
        changed, first_diff, ranges = _changed_ranges_equal_size_prefix(path_a, path_b, common)
        if first_diff is None:
            first_diff = common
        changed += abs(size_a - size_b)
        _append_range(ranges, common, max(size_a, size_b))

    dtype = dump_type or classify_dump(path_a)
    grouping = group_changes(ranges, dtype)

    return {
        "path_a": path_a,
        "path_b": path_b,
        "size_a": size_a,
        "size_b": size_b,
        "sha256_a": sha_a,
        "sha256_b": sha_b,
        "equal": equal,
        "equal_size": equal_size,
        "changed_bytes": changed,
        "first_diff_offset": first_diff,
        "ranges": [r.to_dict() for r in ranges],
        "range_count": len(ranges),
        "dump_type": dtype,
        "grouping": grouping,
    }


def _changed_ranges_equal_size_prefix(
    path_a: str,
    path_b: str,
    limit: int,
) -> Tuple[int, Optional[int], List[DiffRange]]:
    """Scan the first *limit* bytes of two files."""
    changed = 0
    first_diff = None
    ranges: List[DiffRange] = []
    offset = 0

    with open(path_a, "rb") as a, open(path_b, "rb") as b:
        remaining = limit
        while remaining > 0:
            read_size = min(CHUNK_SIZE, remaining)
            ba = a.read(read_size)
            bb = b.read(read_size)
            if not ba and not bb:
                break
            if ba == bb:
                delta = len(ba)
                offset += delta
                remaining -= delta
                continue
            run_start = None
            for idx, (xa, xb) in enumerate(zip(ba, bb)):
                if xa != xb:
                    abs_pos = offset + idx
                    changed += 1
                    if first_diff is None:
                        first_diff = abs_pos
                    if run_start is None:
                        run_start = abs_pos
                elif run_start is not None:
                    _append_range(ranges, run_start, offset + idx)
                    run_start = None
            if run_start is not None:
                _append_range(ranges, run_start, offset + min(len(ba), len(bb)))
            delta = len(ba)
            offset += delta
            remaining -= delta

    return changed, first_diff, ranges


def format_offset(offset: Optional[int]) -> str:
    """Format a byte offset for UI/CLI output."""
    if offset is None:
        return "n/a"
    return "0x%X" % offset


def format_ranges(ranges: Iterable[Dict[str, int]], limit: int = 8) -> str:
    """Return a compact textual range list."""
    parts = []
    for idx, r in enumerate(ranges):
        if idx >= limit:
            parts.append("...")
            break
        start = r["start"]
        end = r["end"]
        if end == start + 1:
            parts.append("0x%X" % start)
        else:
            parts.append("0x%X-0x%X" % (start, end - 1))
    return ", ".join(parts) if parts else "none"


def format_summary(result: Dict[str, object], detail_ranges: int = 5) -> str:
    """Return a concise multi-line diff summary for device/plugin UI."""
    if result.get("equal"):
        return (
            "Equal\n"
            "Size: %d bytes\n"
            "SHA: %s"
        ) % (result["size_a"], str(result["sha256_a"])[:12])

    lines = [
        "Different",
        "A: %d bytes" % result["size_a"],
        "B: %d bytes" % result["size_b"],
        "Changed: %d byte(s)" % result["changed_bytes"],
        "First: %s" % format_offset(result.get("first_diff_offset")),
    ]
    grouping = result.get("grouping") or {}
    if grouping.get("unit") == "mfc-block":
        lines.append("Blocks: %d" % grouping.get("block_count", 0))
        lines.append("Sectors: %d" % grouping.get("sector_count", 0))
        if grouping.get("sector_trailer_count"):
            lines.append("Trailers: %d" % grouping.get("sector_trailer_count"))
    elif grouping.get("unit") == "mfu-page":
        lines.append("Pages: %d" % grouping.get("page_count", 0))
    lines.append("Ranges: %s" % format_ranges(result.get("ranges", []), detail_ranges))
    return "\n".join(lines)

