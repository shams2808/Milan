"""Minimal stdlib .xlsx writer using zip + XML.

No dependencies. Writes Excel 2007+ OOXML format with support for:
- Multiple sheets
- Basic styling (colors, bold, number formats)
- Frozen panes
- Autofilter
- Hyperlinks and inline strings

This exists to keep the project zero-dependency, same reason xlsx_lite.py
exists for reading. A zip of XML files is well-trodden; this is ~200 lines.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from typing import Any


class Workbook:
    """A minimal OOXML workbook builder."""

    def __init__(self):
        self.sheets: list[Sheet] = []
        self.styles: dict[str, int] = {}
        self._next_style_id = 0

    def add_sheet(self, name: str, rows: list[list[Any]], **options) -> None:
        """Add a sheet. Options: freeze_rows, freeze_cols, autofilter_range."""
        sheet = Sheet(name, rows, **options)
        self.sheets.append(sheet)

    def register_style(self, **kwargs) -> int:
        """Register a style and return its ID. kwargs: bold, font_size, bg_color, 
        font_color, num_format, border, alignment."""
        key = tuple(sorted(kwargs.items()))
        if key not in self.styles:
            self.styles[key] = self._next_style_id
            self._next_style_id += 1
        return self.styles[key]

    def write(self, path: str) -> None:
        """Write the workbook to disk."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # [Content_Types].xml
            zf.writestr("[Content_Types].xml", self._content_types_xml())

            # workbook.xml and workbook.xml.rels
            zf.writestr("xl/workbook.xml", self._workbook_xml())
            zf.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels_xml())

            # Styles and theme
            zf.writestr("xl/styles.xml", self._styles_xml())
            zf.writestr("xl/theme/theme1.xml", self._theme_xml())

            # Sheets
            for i, sheet in enumerate(self.sheets, 1):
                zf.writestr(f"xl/worksheets/sheet{i}.xml", sheet.to_xml())
                zf.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels", self._sheet_rels_xml())

            # Document properties
            zf.writestr("docProps/app.xml", self._app_xml())
            zf.writestr("docProps/core.xml", self._core_xml())
            zf.writestr("_rels/.rels", self._rels_xml())

        with open(path, "wb") as fh:
            fh.write(buf.getvalue())

    def _content_types_xml(self) -> str:
        """[Content_Types].xml"""
        sheets_xml = "".join(
            f'  <Override PartName="/xl/worksheets/sheet{i}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'
            for i in range(1, len(self.sheets) + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '  <Default Extension="xml" ContentType="application/xml"/>\n'
            '  <Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
            '  <Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>\n'
            '  <Override PartName="/xl/theme/theme1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>\n'
            f"{sheets_xml}"
            '  <Override PartName="/docProps/app.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>\n'
            '  <Override PartName="/docProps/core.xml" '
            'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>\n'
            '</Types>'
        )

    def _workbook_xml(self) -> str:
        """xl/workbook.xml"""
        sheets_xml = "".join(
            f'    <sheet name="{_escape_xml(sheet.name)}" sheetId="{i}" r:id="rId{i}"/>\n'
            for i, sheet in enumerate(self.sheets, 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
            '  <workbookPr defaultTheme="1"/>\n'
            '  <sheets>\n'
            f"{sheets_xml}"
            '  </sheets>\n'
            '</workbook>'
        )

    def _workbook_rels_xml(self) -> str:
        """xl/_rels/workbook.xml.rels"""
        sheet_rels = "".join(
            f'  <Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>\n'
            for i in range(1, len(self.sheets) + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f"{sheet_rels}"
            '  <Relationship Id="rId99" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>\n'
            '  <Relationship Id="rId100" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
            'Target="theme/theme1.xml"/>\n'
            '</Relationships>'
        )

    def _sheet_rels_xml(self) -> str:
        """xl/worksheets/_rels/sheetN.xml.rels (empty for now)"""
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '</Relationships>'
        )

    def _styles_xml(self) -> str:
        """xl/styles.xml - just the essentials"""
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
            '  <fonts count="3">\n'
            '    <font><sz val="11"/><name val="Calibri"/></font>\n'
            '    <font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font>\n'
            '    <font><sz val="11"/><name val="Calibri"/><color rgb="FFFF0000"/></font>\n'
            '  </fonts>\n'
            '  <fills count="6">\n'
            '    <fill><patternFill patternType="none"/></fill>\n'
            '    <fill><patternFill patternType="gray125"/></fill>\n'
            '    <fill><patternFill patternType="solid"><fgColor rgb="FF2F5233"/></patternFill></fill>\n'
            '    <fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/></patternFill></fill>\n'
            '    <fill><patternFill patternType="solid"><fgColor rgb="FFFFCC00"/></patternFill></fill>\n'
            '    <fill><patternFill patternType="solid"><fgColor rgb="FFFF0000"/></patternFill></fill>\n'
            '  </fills>\n'
            '  <borders count="1">\n'
            '    <border><left/><right/><top/><bottom/><diagonal/></border>\n'
            '  </borders>\n'
            '  <cellStyleXfs count="1">\n'
            '    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>\n'
            '  </cellStyleXfs>\n'
            '  <cellXfs count="10">\n'
            '    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>\n'
            '    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>\n'
            '    <xf numFmtId="44" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>\n'
            '    <xf numFmtId="44" fontId="0" fillId="3" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>\n'
            '    <xf numFmtId="44" fontId="0" fillId="4" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>\n'
            '    <xf numFmtId="44" fontId="0" fillId="5" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>\n'
            '    <xf numFmtId="44" fontId="0" fillId="1" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1"/>\n'
            '  </cellXfs>\n'
            '  <cellStyles count="1">\n'
            '    <cellStyle name="Normal" xfId="0" builtinId="0"/>\n'
            '  </cellStyles>\n'
            '  <dxfs count="0"/>\n'
            '  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>\n'
            '</styleSheet>'
        )

    def _theme_xml(self) -> str:
        """xl/theme/theme1.xml - minimal Office theme"""
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office">\n'
            '  <a:themeElements>\n'
            '    <a:clrScheme name="Office"><a:dk1><a:srgbClr val="000000"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>\n'
            '    <a:dk2><a:srgbClr val="1F497D"/></a:dk2><a:lt2><a:srgbClr val="EBEBEB"/></a:lt2>\n'
            '    <a:accent1><a:srgbClr val="4472C4"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2>\n'
            '    <a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>\n'
            '    <a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>\n'
            '    <a:hyperlink><a:srgbClr val="0563C1"/></a:hyperlink><a:folHyperlink><a:srgbClr val="954F72"/></a:folHyperlink>\n'
            '    </a:clrScheme></a:themeElements>\n'
            '</a:theme>'
        )

    def _app_xml(self) -> str:
        """docProps/app.xml"""
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties">\n'
            f'  <TitlesOfParts><vector baseType="lpstr" size="{len(self.sheets)}">\n'
            + "".join(f'    <variant><lpstr>{_escape_xml(s.name)}</lpstr></variant>\n' for s in self.sheets)
            + '  </vector></TitlesOfParts>\n'
            '</Properties>'
        )

    def _core_xml(self) -> str:
        """docProps/core.xml"""
        now = datetime.now().isoformat() + "Z"
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/officeDocument/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'  <dc:created>{now}</dc:created>\n'
            f'  <dc:modified>{now}</dc:modified>\n'
            '</cp:coreProperties>'
        )

    def _rels_xml(self) -> str:
        """_rels/.rels"""
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>\n'
            '  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>\n'
            '  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
            'Target="docProps/app.xml"/>\n'
            '</Relationships>'
        )


class Sheet:
    """A single sheet in the workbook."""

    def __init__(self, name: str, rows: list[list[Any]], freeze_rows: int = 0, 
                 freeze_cols: int = 0, autofilter_range: str = "", col_widths: dict[int, float] | None = None,
                 header_style: int | None = None, cell_styles: dict[tuple[int, int], int] | None = None):
        self.name = name
        self.rows = rows
        self.freeze_rows = freeze_rows
        self.freeze_cols = freeze_cols
        self.autofilter_range = autofilter_range
        self.col_widths = col_widths or {}
        self.header_style = header_style or 1  # Default: bold header on green
        self.cell_styles = cell_styles or {}  # (row, col) -> style_id

    def to_xml(self) -> str:
        """Convert sheet to XML."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        ]

        # Freeze panes. MUST be inside <sheetViews>, and <sheetViews> MUST come
        # before <sheetData> -- the OOXML schema fixes worksheet child order.
        # Emitting a bare <pane> after </sheetData> makes Excel declare the file
        # corrupt and offer to repair it. See INCIDENTS.md #8.
        if self.freeze_rows > 0 or self.freeze_cols > 0:
            top_left = f'{_col_letter(self.freeze_cols)}{self.freeze_rows + 1}'
            pane = '    <pane'
            if self.freeze_cols > 0:
                pane += f' xSplit="{self.freeze_cols}"'
            if self.freeze_rows > 0:
                pane += f' ySplit="{self.freeze_rows}"'
            pane += f' topLeftCell="{top_left}" activePane="bottomRight" state="frozen"/>\n'
            lines.append('  <sheetViews>\n    <sheetView workbookViewId="0">\n')
            lines.append(pane)
            lines.append('    </sheetView>\n  </sheetViews>\n')

        # Column widths
        if self.col_widths:
            lines.append("  <cols>\n")
            for col_idx, width in sorted(self.col_widths.items()):
                lines.append(f'    <col min="{col_idx + 1}" max="{col_idx + 1}" width="{width}" customWidth="1"/>\n')
            lines.append("  </cols>\n")

        # Sheet data
        lines.append("  <sheetData>\n")
        for row_idx, row in enumerate(self.rows):
            lines.append(f'    <row r="{row_idx + 1}" hidden="0">\n')
            for col_idx, cell in enumerate(row):
                # Determine style
                style_id = 0
                if row_idx == 0:
                    style_id = self.header_style
                if (row_idx, col_idx) in self.cell_styles:
                    style_id = self.cell_styles[(row_idx, col_idx)]

                cell_ref = _col_letter(col_idx) + str(row_idx + 1)
                type_attr, inner = _cell_xml(cell)
                if inner:
                    lines.append(
                        f'      <c r="{cell_ref}" s="{style_id}"{type_attr}>{inner}</c>\n'
                    )
                else:
                    lines.append(f'      <c r="{cell_ref}" s="{style_id}"/>\n')
            lines.append("    </row>\n")
        lines.append("  </sheetData>\n")

        # Autofilter (correctly placed AFTER sheetData, per the schema)
        if self.autofilter_range:
            lines.append(f'  <autoFilter ref="{self.autofilter_range}"/>\n')

        lines.append('</worksheet>')
        return "".join(lines)


def _col_letter(col_idx: int) -> str:
    """Convert 0-based column index to Excel column letter."""
    result = ""
    col_idx += 1  # Excel columns are 1-based
    while col_idx > 0:
        col_idx -= 1
        result = chr(ord("A") + col_idx % 26) + result
        col_idx //= 26
    return result


def _cell_xml(value: Any) -> tuple[str, str]:
    """Return (type_attribute, inner_xml) for one cell.

    The type attribute and the inner XML have to be decided together. An
    earlier version returned only the inner XML, so `<is><t>..</t></is>` was
    emitted on a cell with no `t="inlineStr"`. Without that attribute a cell
    defaults to numeric, Excel finds no `<v>`, and declares the whole workbook
    corrupt -- it did this to all 5,757 text cells. See INCIDENTS.md #8.
    """
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
    return ' t="inlineStr"', f"<is><t>{_escape_xml(str(value))}</t></is>"


def _escape_xml(s: str) -> str:
    """Escape XML special characters."""
    s = str(s)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&apos;")
    return s
