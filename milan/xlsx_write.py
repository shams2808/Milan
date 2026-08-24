"""Minimal .xlsx writer -- the smallest set of parts Excel accepts.

Milan is standard-library only, so this exists rather than a dependency, the
same way xlsx_lite.py exists for reading.

It emits ONLY the parts a workbook actually requires:

    [Content_Types].xml
    _rels/.rels
    xl/workbook.xml
    xl/_rels/workbook.xml.rels
    xl/styles.xml
    xl/worksheets/sheet{N}.xml

No theme, no docProps, no per-sheet .rels. An earlier version wrote all of
those and every single one was malformed -- app.xml carried extended-properties
content under the custom-properties namespace without the vt: prefixes,
core.xml used dc:created instead of dcterms:created, and the sheet .rels files
were empty. None of them are required, and each optional part is another
chance to produce a file Excel refuses to open. See INCIDENTS.md #8 and #9.

Two invariants that version violated and that validate_package() now enforces:
  * every count="N" attribute must equal the real number of children
    (cellXfs said 10 and held 7, which alone is fatal)
  * every declared content-type Override must name a part that exists, and
    every part must be declared
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime
from typing import Any

# Style ids, matching the cellXfs order written below.
S_DEFAULT, S_HEADER, S_MONEY, S_HIGHLIGHT = 0, 1, 2, 3

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Excel rejects these in a sheet name, and caps the name at 31 characters.
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _escape(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def _col_letter(idx: int) -> str:
    out, idx = "", idx + 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def _safe_sheet_name(name: str, taken: set[str]) -> str:
    clean = _BAD_SHEET_CHARS.sub("-", name)[:31] or "Sheet"
    base, n = clean, 2
    while clean.lower() in taken:
        suffix = f" {n}"
        clean, n = base[: 31 - len(suffix)] + suffix, n + 1
    taken.add(clean.lower())
    return clean


def _cell_xml(value: Any) -> tuple[str, str]:
    """(type_attribute, inner_xml). Both are decided together: a cell holding
    <is> is invalid unless it also carries t="inlineStr", and a version that
    returned only the inner XML emitted 5,757 such cells."""
    if value is None or value == "":
        return "", ""
    if isinstance(value, bool):
        return "", f'<v>{"1" if value else "0"}</v>'
    if isinstance(value, (int, float)):
        return "", f"<v>{value}</v>"
    if isinstance(value, (date, datetime)):
        dt = value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time())
        delta = dt - datetime(1899, 12, 30)
        return "", f"<v>{delta.days + delta.seconds / 86400}</v>"
    return ' t="inlineStr"', f"<is><t>{_escape(value)}</t></is>"


class Sheet:
    def __init__(self, name: str, rows: list[list[Any]], freeze_rows: int = 0,
                 freeze_cols: int = 0, autofilter_range: str = "",
                 col_widths: dict[int, float] | None = None,
                 header_style: int = S_HEADER,
                 cell_styles: dict[tuple[int, int], int] | None = None):
        self.name = name
        self.rows = rows
        self.freeze_rows = freeze_rows
        self.freeze_cols = freeze_cols
        self.autofilter_range = autofilter_range
        self.col_widths = col_widths or {}
        self.header_style = header_style
        self.cell_styles = cell_styles or {}

    def to_xml(self) -> str:
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               f'<worksheet xmlns="{_MAIN}">']

        # sheetViews (and therefore <pane>) must precede sheetData; the
        # worksheet schema fixes child order.
        if self.freeze_rows or self.freeze_cols:
            pane = "<pane"
            if self.freeze_cols:
                pane += f' xSplit="{self.freeze_cols}"'
            if self.freeze_rows:
                pane += f' ySplit="{self.freeze_rows}"'
            top_left = f"{_col_letter(self.freeze_cols)}{self.freeze_rows + 1}"
            pane += f' topLeftCell="{top_left}" activePane="bottomRight" state="frozen"/>'
            out.append(f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>')

        if self.col_widths:
            cols = "".join(
                f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>'
                for c, w in sorted(self.col_widths.items())
            )
            out.append(f"<cols>{cols}</cols>")

        out.append("<sheetData>")
        for r, row in enumerate(self.rows):
            cells = []
            for c, value in enumerate(row):
                style = self.cell_styles.get((r, c), self.header_style if r == 0 else S_DEFAULT)
                attr, inner = _cell_xml(value)
                ref = f"{_col_letter(c)}{r + 1}"
                cells.append(f'<c r="{ref}" s="{style}"{attr}>{inner}</c>' if inner
                             else f'<c r="{ref}" s="{style}"/>')
            out.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
        out.append("</sheetData>")

        # autoFilter belongs AFTER sheetData, unlike sheetViews.
        if self.autofilter_range:
            out.append(f'<autoFilter ref="{self.autofilter_range}"/>')

        out.append("</worksheet>")
        return "".join(out)


class Workbook:
    def __init__(self):
        self.sheets: list[Sheet] = []
        self._names: set[str] = set()

    def add_sheet(self, name: str, rows: list[list[Any]], **options) -> None:
        self.sheets.append(Sheet(_safe_sheet_name(name, self._names), rows, **options))

    # --- package parts ------------------------------------------------------
    def _content_types(self) -> str:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(self.sheets) + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType='
            '"application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>"
        )

    def _root_rels(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_PKG_RELS}">'
            f'<Relationship Id="rId1" Type="{_RELS}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    def _workbook(self) -> str:
        sheets = "".join(
            f'<sheet name="{_escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, s in enumerate(self.sheets, 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_MAIN}" xmlns:r="{_RELS}">'
            f"<sheets>{sheets}</sheets></workbook>"
        )

    def _workbook_rels(self) -> str:
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="{_RELS}/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(self.sheets) + 1)
        )
        styles_id = len(self.sheets) + 1
        rels += (f'<Relationship Id="rId{styles_id}" Type="{_RELS}/styles" '
                 'Target="styles.xml"/>')
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<Relationships xmlns="{_PKG_RELS}">{rels}</Relationships>')

    def _styles(self) -> str:
        fonts = [
            '<font><sz val="11"/><name val="Calibri"/></font>',
            '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>',
        ]
        fills = [
            '<fill><patternFill patternType="none"/></fill>',
            '<fill><patternFill patternType="gray125"/></fill>',
            '<fill><patternFill patternType="solid"><fgColor rgb="FF1F5132"/>'
            '<bgColor indexed="64"/></patternFill></fill>',
            '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/>'
            '<bgColor indexed="64"/></patternFill></fill>',
        ]
        # numFmtId 4 is the built-in "#,##0.00" -- built-ins avoid any
        # locale/currency-symbol surprises on the practitioner's machine.
        xfs = [
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0"'
            ' applyFont="1" applyFill="1"/>',
            '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0"'
            ' applyNumberFormat="1"/>',
            '<xf numFmtId="4" fontId="0" fillId="3" borderId="0" xfId="0"'
            ' applyNumberFormat="1" applyFill="1"/>',
        ]
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<styleSheet xmlns="{_MAIN}">'
            f'<fonts count="{len(fonts)}">{"".join(fonts)}</fonts>'
            f'<fills count="{len(fills)}">{"".join(fills)}</fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"
        )

    def write(self, path: str) -> None:
        if not self.sheets:
            raise ValueError("a workbook needs at least one sheet")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", self._content_types())
            zf.writestr("_rels/.rels", self._root_rels())
            zf.writestr("xl/workbook.xml", self._workbook())
            zf.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels())
            zf.writestr("xl/styles.xml", self._styles())
            for i, sheet in enumerate(self.sheets, 1):
                zf.writestr(f"xl/worksheets/sheet{i}.xml", sheet.to_xml())
        data = buf.getvalue()
        validate_package(data)          # never ship a file we have not checked
        with open(path, "wb") as fh:
            fh.write(data)


def validate_package(data: bytes) -> None:
    """Raise if the package is not something Excel will open.

    This exists because the workbook shipped broken twice. Checking that the
    cells looked right was not enough -- the failures were in the package:
    a count attribute that disagreed with reality, a content type that
    disagreed with a relationship, namespaces that disagreed with content.
    """
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())

        for part in names:
            try:
                ET.fromstring(z.read(part))
            except ET.ParseError as exc:
                raise ValueError(f"{part}: not well-formed XML: {exc}") from exc

        if "[Content_Types].xml" not in names:
            raise ValueError("missing [Content_Types].xml")
        ct = z.read("[Content_Types].xml").decode()

        # Every Override must name a part that exists.
        for declared in re.findall(r'PartName="/([^"]+)"', ct):
            if declared not in names:
                raise ValueError(f"content types declare {declared}, which is not in the package")

        # Every part must be typed, by Override or by Default extension.
        defaults = set(re.findall(r'<Default Extension="([^"]+)"', ct))
        declared_parts = set(re.findall(r'PartName="/([^"]+)"', ct))
        for part in names:
            if part in declared_parts or part.rsplit(".", 1)[-1] in defaults:
                continue
            raise ValueError(f"{part} has no content type")

        # Every relationship target must resolve.
        for part in names:
            if not part.endswith(".rels"):
                continue
            base = part.rsplit("_rels/", 1)[0]
            for target in re.findall(r'Target="([^"]+)"', z.read(part).decode()):
                if target.startswith(("http://", "https://")):
                    continue
                resolved = (base + target).replace("//", "/")
                if resolved not in names:
                    raise ValueError(f"{part}: relationship target {resolved} is missing")

        # Every count="N" must match the real number of children. cellXfs
        # claimed 10 while holding 7, which is fatal on its own.
        for part in names:
            if not part.startswith("xl/") or not part.endswith(".xml"):
                continue
            root = ET.fromstring(z.read(part))
            for el in root.iter():
                declared_count = el.get("count")
                if declared_count is None:
                    continue
                actual = len(list(el))
                if int(declared_count) != actual:
                    tag = el.tag.split("}")[-1]
                    raise ValueError(
                        f"{part}: <{tag} count=\"{declared_count}\"> but has {actual} children"
                    )

        # Inline strings must be typed, or Excel reads the cell as numeric.
        for part in names:
            if "worksheets/sheet" not in part:
                continue
            xml = z.read(part).decode()
            for match in re.finditer(r"<c [^>]*>(?=<is>)", xml):
                if "inlineStr" not in match.group(0):
                    raise ValueError(f"{part}: <is> on a cell without t=\"inlineStr\"")
            if re.search(r"</sheetData>\s*<pane", xml):
                raise ValueError(f"{part}: <pane> after </sheetData>")
