"""The smallest possible .xlsx reader.

Milan promises "standard library only," and openpyxl is not installed on this
machine either -- so this exists instead of adding a dependency. An .xlsx is a
zip of XML; we only need three parts of it: the shared string table, the
sheet-name -> file mapping, and one sheet's cell grid. No styles, no formulas,
no merged-cell awareness beyond what the callers handle themselves.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_COL = re.compile(r"[A-Z]+")

# Excel's epoch is 1899-12-30, not 1900-01-01 -- this already compensates for
# the Lotus 1-2-3 leap-year bug Excel inherited, so no separate correction is
# needed for any date after March 1900.
_EPOCH = date(1899, 12, 30)


def excel_serial_to_date(serial) -> date:
    return _EPOCH + timedelta(days=int(float(serial)))


class Workbook:
    def __init__(self, path: str):
        self._path = path
        with zipfile.ZipFile(path) as z:
            self._sheets = self._sheet_map(z)
            self._sst = self._shared_strings(z)

    def _sheet_map(self, z: zipfile.ZipFile) -> dict[str, str]:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {r.get("Id"): r.get("Target") for r in rels}
        out = {}
        for sh in wb.find(f"{_NS}sheets"):
            rid = sh.get(f"{_RNS}id")
            out[sh.get("name")] = "xl/" + rid_to_target[rid]
        return out

    def _shared_strings(self, z: zipfile.ZipFile) -> list[str]:
        try:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        return [
            "".join(t.text or "" for t in si.iter(f"{_NS}t"))
            for si in root.findall(f"{_NS}si")
        ]

    def sheet_names(self) -> list[str]:
        return list(self._sheets)

    def find_sheet(self, contains: str) -> str:
        """Sheet names carry a Unicode en-dash Excel sometimes mangles on
        re-save; match loosely rather than on an exact byte sequence."""
        for name in self._sheets:
            if contains.lower() in name.lower():
                return name
        raise KeyError(f"no sheet name contains {contains!r}; have {self.sheet_names()}")

    def rows(self, sheet_name: str):
        """Yields one {col_letter: raw_string_value} dict per row, in order.
        Values are always strings (or None) -- callers convert."""
        with zipfile.ZipFile(self._path) as z:
            root = ET.fromstring(z.read(self._sheets[sheet_name]))
        for row in root.iter(f"{_NS}row"):
            cells: dict[str, str | None] = {}
            for c in row.findall(f"{_NS}c"):
                col = _COL.match(c.get("r")).group()
                if c.get("t") == "inlineStr":
                    # Inline strings live in <is><t>, not <v>. Portal and Tally
                    # exports use the shared-string table, so this branch only
                    # matters for round-tripping our own output -- which is
                    # exactly why it needs to work.
                    node = c.find(f"{_NS}is")
                    val = "".join(t.text or "" for t in node.iter(f"{_NS}t")) if node is not None else None
                else:
                    v = c.find(f"{_NS}v")
                    val = v.text if v is not None else None
                    if c.get("t") == "s" and val is not None:
                        val = self._sst[int(val)]
                cells[col] = val
            yield cells


def header_map(rows: list[dict], keys: dict[str, str], *, merge_rows: int = 1) -> dict[str, str]:
    """Given the first `merge_rows` rows of a sheet (later rows override
    earlier ones, for a two-tier merged-cell header) and a {keyword: field}
    map, return {col_letter: field} by substring match on header text.

    Matching by text, not position, because a portal or Tally export can add
    or reorder columns between filings; a hardcoded column letter breaks
    silently the moment that happens.
    """
    combined: dict[str, str] = {}
    for r in rows[:merge_rows]:
        for col, val in r.items():
            if val:
                combined[col] = re.sub(r"\s+", " ", val).strip()

    out: dict[str, str] = {}
    for col, text in combined.items():
        low = text.lower()
        for keyword, field in keys.items():
            if keyword in low:
                out[col] = field
                break
    missing = set(keys.values()) - set(out.values())
    if missing:
        raise ValueError(
            f"could not find columns for {missing} in header row(s) {combined}"
        )
    return out
